
import json
import secrets
import logging
from pathlib import Path
from datetime import timedelta, datetime

from flask import Flask, render_template, request, redirect, url_for, jsonify, session


from core.config_path import resolver_config_path

BASE = Path(__file__).resolve().parent
CONFIG_PATH = resolver_config_path(BASE)

def carregar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _corrigir_caminho_base_se_necessario(cfg: dict) -> dict:
    """
    Proteção só para execução a partir do código-fonte (python app.py
    direto, sem passar pelo launcher.py/.exe compilado).

    O launcher.py já resolve isso para o .exe final (ver
    _sincronizar_dados_persistentes lá), mas aquela lógica explicitamente
    não roda fora do binário compilado — então rodar direto do
    código-fonte com o caminho_base herdado de outra instalação (ex.:
    o valor de fábrica "C:\\SmartCampus", ou o de uma instalação
    anterior copiada para outra pasta) faz o sistema procurar
    sceds/data no lugar ERRADO: cria uma pasta de dados vazia lá, sem
    nenhuma tabela, e qualquer operação (inclusive o wizard criando o
    admin) falha com "Tabela 'X' não encontrada".

    Corrige silenciosamente apenas quando é claramente um caso de
    execução local (não mexe em nada se sceds/data já existir e tiver
    as tabelas certas no caminho_base configurado).
    """
    caminho_configurado = Path(cfg.get("caminho_base", "."))
    schema_no_caminho_configurado = caminho_configurado / "sceds" / "data" / "usuarios.schema.json"
    schema_local = BASE / "sceds" / "data" / "usuarios.schema.json"

    if schema_no_caminho_configurado.exists():
        return cfg  # caminho_base já está correto, nada a fazer

    if not schema_local.exists():
        return cfg  # nem localmente existe — deixa o erro real aparecer

    logging.getLogger("smartcampus").warning(
        "caminho_base em config.json ('%s') não contém sceds/data — "
        "corrigindo automaticamente para a pasta do projeto ('%s'). "
        "Isso só deveria acontecer rodando a partir do código-fonte; "
        "no .exe final, o launcher.py já cuida disso antes de chegar aqui.",
        caminho_configurado, BASE,
    )
    cfg["caminho_base"] = str(BASE)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


app = Flask(
    __name__,
    template_folder=str(BASE / "templates"),
    static_folder=str(BASE / "static"),
)


config = carregar_config()
config = _corrigir_caminho_base_se_necessario(config)

chave_secreta_path = BASE / "core" / ".secret_key"
if chave_secreta_path.exists():
    app.secret_key = chave_secreta_path.read_bytes()
else:
    chave = secrets.token_bytes(32)
    chave_secreta_path.write_bytes(chave)
    try:
        # Restringe leitura/escrita ao dono do arquivo (defesa em
        # profundidade: um usuário sem privilégio no mesmo Windows/Linux
        # não deveria conseguir ler a chave de assinatura de sessão só
        # por estar logado na mesma máquina). Melhor esforço: em Windows
        # isto mapeia para o atributo somente-leitura, não um ACL
        # completo — a proteção real de disco continua sendo
        # criptografia de disco a nível de SO, já documentada como fora
        # do escopo da aplicação em core/backup.py.
        chave_secreta_path.chmod(0o600)
    except OSError:
        pass
    app.secret_key = chave

app.permanent_session_lifetime = timedelta(hours=8)

# Segurança de cookie de sessão. HTTPONLY já é o padrão do Flask, mas fica
# explícito aqui para não depender de comportamento implícito de versão.
# SECURE fica condicionado a HTTPS estar habilitado nesta instalação
# (config.json -> "https_habilitado") porque, sem TLS configurado na
# frente do servidor, marcar o cookie como Secure faria o navegador
# simplesmente parar de enviá-lo — pior que o estado atual. Ver
# core/config.json e a documentação de instalação para como habilitar
# HTTPS (recomendado sempre que o servidor for acessível pela rede da
# escola, não só via localhost).
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(config.get("https_habilitado", False))


# IMPORTANTE: usa cfg["caminho_base"] (pasta de dados persistente da
# instalação), não BASE (pasta do próprio app.py). No .exe empacotado,
# BASE aponta para dentro da pasta temporária do PyInstaller (_MEIPASS),
# apagada quando o programa fecha — gravar o log ali faz ele nunca
# aparecer na pasta \logs real, ao lado do .exe (mesmo raciocínio já
# aplicado em core/auditoria.py para o auditoria.jsonl).
log_path = Path(config["caminho_base"]) / "logs" / "servidor.log"
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    # force=True é essencial aqui: quando rodando via launcher.py (.exe
    # empacotado), o processo já chamou logging.basicConfig() antes
    # (para smartcampus_erro.log, no _preparar_log). basicConfig() é
    # um no-op silencioso se o logger raiz já tem handlers — sem
    # force=True, o FileHandler abaixo chega a CRIAR servidor.log (por
    # isso o arquivo existe), mas nunca fica de fato anexado ao logger,
    # e todo log real continua indo parar em smartcampus_erro.log.
    # Resultado: servidor.log sempre com 0 bytes.
    force=True,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(log_path), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


import sys
sys.path.insert(0, str(BASE))

from core.auth import (
    autenticar,
    criar_sessao,
    destruir_sessao,
    usuario_logado,
    modulos_do_usuario,
    menu_agrupado_do_usuario,
    login_obrigatorio,
    MENU_ID_PARA_MODULO,
    gerar_token_recuperacao_admin,
    redefinir_senha_admin_via_token,
)
from core.router import registrar_blueprints, perfil_para_cor, perfil_para_label
from core.auditoria import registrar as registrar_auditoria

# Backup automático — roda em background dentro do próprio processo desde
# o momento em que o app é carregado (tanto em `python app.py` quanto
# quando o launcher.py do .exe importa este módulo), sem depender de
# nenhuma infraestrutura externa. Ver core/backup.py para o motivo do
# design e as garantias/limites reais desse mecanismo.
from core.backup import iniciar_agendador as _iniciar_backup_agendado

_caminho_base_dados = Path(config.get("caminho_base", str(BASE)))
_iniciar_backup_agendado(
    pasta_dados=_caminho_base_dados / "sceds" / "data",
    pasta_backups=_caminho_base_dados / "backups",
)


@app.context_processor
def injetar_contexto():
    """
    Injeta variáveis disponíveis em todos os templates:
    usuario, modulos, cor_perfil, label_perfil, nome_escola, sigla_escola, bairro_cidade
    """
    identidade = {
        "nome_escola":   config.get("nome_escola", "Smart Campus"),
        "sigla_escola":  config.get("sigla_escola", ""),
        "bairro_cidade": config.get("bairro_cidade", ""),
    }

    usuario = usuario_logado()
    if usuario:
        return {
            **identidade,
            "usuario":     usuario,
            "modulos":     modulos_do_usuario(usuario),
            "menu_agrupado": menu_agrupado_do_usuario(usuario),
            "cor_perfil":  perfil_para_cor(usuario.get("perfil_base") or usuario["perfil"]),
            "label_perfil": usuario.get("cargo_nome") or perfil_para_label(usuario["perfil"]),
            "menu_para_modulo": MENU_ID_PARA_MODULO,
        }
    return {
        **identidade,
        "usuario":     None,
        "modulos":     [],
        "menu_agrupado": [],
        "cor_perfil":  "#4A4A4A",
        "label_perfil":"",
        "menu_para_modulo": {},
    }


def _instalacao_precisa_do_wizard() -> bool:
    """
    True quando esta instalação ainda não tem nenhum usuário 'admin' —
    ou seja, quando o wizard de instalação (wizard/api_wizard.py) ainda
    não rodou. Mesma verificação que o próprio wizard já faz para se
    autobloquear depois de instalado (_instalacao_ja_concluida lá);
    aqui é o inverso, usado para REDIRECIONAR pra ele antes do login.
    """
    try:
        db = _get_db_saude()
        return len(db.buscar("usuarios", onde={"perfil": "admin"})) == 0
    except Exception:
        # Sem sceds/data legível ainda (instalação bem nova) — trata
        # como "precisa do wizard", que é o estado seguro aqui.
        return True


@app.route("/")
def raiz():
    """Redireciona para o wizard (instalação nova), dashboard (já logado)
    ou login, nessa ordem de prioridade."""
    if _instalacao_precisa_do_wizard():
        return redirect(url_for("wizard.pagina_wizard"))
    if usuario_logado():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Tela e processamento de login por senha única, com proteção
    contra tentativas repetidas de adivinhação de senha (rate limit
    por IP)."""
    if _instalacao_precisa_do_wizard():
        return redirect(url_for("wizard.pagina_wizard"))
    if usuario_logado():
        return redirect(url_for("dashboard"))

    from core.rate_limit import esta_bloqueado, registrar_falha, registrar_sucesso
    chave_limite = request.remote_addr or "desconhecido"

    if request.method == "GET":
        return render_template("login.html", erro=None)

    bloqueado, segundos_restantes = esta_bloqueado(chave_limite)
    if bloqueado:
        minutos = max(1, segundos_restantes // 60)
        app.logger.warning(f"[Auth] Login bloqueado por excesso de tentativas — IP: {chave_limite}")
        return render_template(
            "login.html",
            erro=f"Muitas tentativas incorretas. Tente novamente em cerca de {minutos} minuto(s).",
        ), 429

    senha = request.form.get("senha", "").strip()

    if not senha:
        return render_template("login.html", erro="Informe sua senha.")

    try:
        usuario = autenticar(senha)
    except FileNotFoundError as e:
        app.logger.error(f"[Auth] Base de dados incompleta/corrompida: {e}")
        return render_template(
            "login.html",
            erro="Falha ao acessar os dados da instalação. Contate o suporte técnico.",
        )

    if not usuario:
        registrar_falha(chave_limite)
        registrar_auditoria(None, "login_falhou", ip=request.remote_addr)
        app.logger.warning(f"[Auth] Tentativa de login falhou — IP: {chave_limite}")
        return render_template("login.html", erro="Senha incorreta. Tente novamente.")

    registrar_sucesso(chave_limite)
    criar_sessao(usuario)
    registrar_auditoria(usuario, "login", ip=request.remote_addr)
    app.logger.info(
        f"[Auth] Login bem-sucedido — {usuario['nome']} ({usuario['perfil']}) "
        f"— IP: {request.remote_addr}"
    )
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    """Encerra a sessão e redireciona para o login."""
    usuario = usuario_logado()
    if usuario:
        registrar_auditoria(usuario, "logout", ip=request.remote_addr)
        app.logger.info(f"[Auth] Logout — {usuario['nome']} ({usuario['perfil']})")
    destruir_sessao()
    return redirect(url_for("login"))


def _somente_localhost():
    """
    Restringe uma rota a requisições originadas da própria máquina do
    servidor. Usado nas rotas de recuperação de acesso de administrador:
    isso garante que ninguém na rede da escola (Wi-Fi de alunos,
    professores etc.) consiga sequer tentar esse fluxo — só quem já tem
    acesso físico ou remoto (RDP/SSH) ao computador onde o SmartCampus
    está instalado.
    """
    if request.remote_addr not in ("127.0.0.1", "::1"):
        app.logger.warning(
            f"[Auth] Tentativa de acesso à recuperação de admin fora do "
            f"servidor local — IP: {request.remote_addr}"
        )
        return jsonify({"ok": False, "erro": "Este recurso só está disponível localmente no servidor."}), 403
    return None


@app.route("/recuperar-acesso", methods=["GET"])
def recuperar_acesso_pagina():
    """
    Tela de recuperação de acesso do administrador — substitui o antigo
    corrigir_admin.py. Só acessível a partir do próprio computador onde o
    servidor está rodando (ver _somente_localhost). Quem estiver aqui
    deve, em seguida, verificar o arquivo de log do servidor para obter o
    token de uso único gerado por /recuperar-acesso/gerar-token.
    """
    bloqueado = _somente_localhost()
    if bloqueado:
        return bloqueado
    return render_template("recuperar_acesso.html")


@app.route("/recuperar-acesso/gerar-token", methods=["POST"])
def recuperar_acesso_gerar_token():
    bloqueado = _somente_localhost()
    if bloqueado:
        return bloqueado

    token = gerar_token_recuperacao_admin()
    app.logger.warning(
        "[Auth] Token de recuperação de acesso de administrador gerado "
        f"(válido por 15 min): {token}"
    )
    return jsonify({
        "ok": True,
        "mensagem": "Token gerado. Consulte o arquivo de log do servidor para obtê-lo.",
    })


@app.route("/recuperar-acesso/confirmar", methods=["POST"])
def recuperar_acesso_confirmar():
    bloqueado = _somente_localhost()
    if bloqueado:
        return bloqueado

    dados = request.get_json(force=True)
    token = (dados.get("token") or "").strip()
    nova_senha = (dados.get("nova_senha") or "").strip()

    try:
        redefinir_senha_admin_via_token(token, nova_senha)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400

    registrar_auditoria(None, "recuperou_acesso_admin", entidade="usuarios", ip=request.remote_addr)
    app.logger.warning("[Auth] Senha de administrador redefinida via recuperação de acesso local.")
    return jsonify({"ok": True, "mensagem": "Senha do administrador redefinida com sucesso."})


def _get_db_saude():
    """Instancia o conector SCEDS do mesmo jeito que o resto do app, isolado
    aqui para o endpoint /saude não depender de nenhum módulo de negócio."""
    base = Path(config.get("caminho_base", str(BASE)))
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    from sceds import SCEDS
    return SCEDS(base / "sceds" / "data")


@app.route("/saude")
def saude():
    """
    Health check — pensado para responder em segundos a "o sistema não
    está funcionando", sem exigir login nem acesso remoto ao servidor.
    Não expõe nenhum dado de aluno/usuário — só status técnico da
    instalação, então é seguro deixar sem autenticação.
    """
    import shutil as _shutil

    resultado = {"ok": True, "verificacoes": {}}

    # 1) SCEDS acessível (consegue listar tabelas de fato, não só o caminho existir)
    try:
        db = _get_db_saude()
        total_tabelas = len(db.listar_tabelas())
        resultado["verificacoes"]["sceds"] = {"ok": True, "total_tabelas": total_tabelas}
    except Exception as e:
        resultado["ok"] = False
        resultado["verificacoes"]["sceds"] = {"ok": False, "erro": str(e)}

    # 2) Licença válida
    try:
        from core.licenca import verificar_ou_none
        pasta_dados = Path(config.get("caminho_base", str(BASE)))
        payload, erro = verificar_ou_none(pasta_dados / "licenca.smc", pasta_cache=pasta_dados)
        if payload is not None:
            resultado["verificacoes"]["licenca"] = {"ok": True, "valida_ate": payload.get("valida_ate")}
        else:
            resultado["ok"] = False
            resultado["verificacoes"]["licenca"] = {"ok": False, "erro": erro or "Licença inválida."}
    except Exception as e:
        resultado["ok"] = False
        resultado["verificacoes"]["licenca"] = {"ok": False, "erro": str(e)}

    # 3) Espaço em disco livre — menos de 500MB é risco real: o SCEDS
    #    reescreve arquivos inteiros e o backup zip precisa de espaço
    #    temporário, não é só um detalhe informativo.
    try:
        pasta_dados = Path(config.get("caminho_base", str(BASE)))
        livre_mb = round(_shutil.disk_usage(pasta_dados).free / (1024 * 1024), 1)
        resultado["verificacoes"]["disco"] = {"ok": livre_mb > 500, "livre_mb": livre_mb}
        if livre_mb <= 500:
            resultado["ok"] = False
    except Exception as e:
        resultado["verificacoes"]["disco"] = {"ok": False, "erro": str(e)}

    # 4) Idade do backup mais recente — alerta (não derruba o "ok" geral)
    #    se estiver mais velho que 24h, sinal de que o agendador de
    #    core/backup.py pode ter parado.
    try:
        pasta_backups = Path(config.get("caminho_base", str(BASE))) / "backups"
        backups = sorted(pasta_backups.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        if backups:
            idade_horas = round((datetime.now().timestamp() - backups[0].stat().st_mtime) / 3600, 1)
            resultado["verificacoes"]["backup"] = {"ok": idade_horas < 24, "idade_horas": idade_horas}
        else:
            resultado["verificacoes"]["backup"] = {"ok": False, "erro": "Nenhum backup encontrado ainda."}
    except Exception as e:
        resultado["verificacoes"]["backup"] = {"ok": False, "erro": str(e)}

    status_http = 200 if resultado["ok"] else 503
    return jsonify(resultado), status_http


@app.route("/dashboard")
@login_obrigatorio
def dashboard():
    """
    Command Center: painel contextual por perfil, com resumo
    operacional, área de atenção e atividade recente, além do acesso
    rápido aos módulos do perfil logado.
    """
    from core.dashboard_data import montar_dashboard

    usuario = usuario_logado()
    painel = montar_dashboard(usuario["perfil"])
    return render_template("dashboard.html", painel=painel)



@app.route("/api/status")
def status():
    """Endpoint de health-check do servidor."""
    return jsonify({
        "status":  "ok",
        "sistema": f"Smart Campus — {config.get('nome_escola') or 'não configurado'}",
        "versao":  config.get("versao", "v3.02.16"),
    })


@app.route("/api/eu")
@login_obrigatorio
def api_eu():
    """Retorna os dados do usuário logado (para uso por módulos via JS)."""
    return jsonify(usuario_logado())



@app.errorhandler(403)
def erro_403(e):
    return render_template(
        "erro.html",
        codigo=403,
        titulo="Acesso negado",
        mensagem="Você não tem permissão para acessar esta página."
    ), 403


@app.errorhandler(404)
def erro_404(e):
    return render_template(
        "erro.html",
        codigo=404,
        titulo="Página não encontrada",
        mensagem="A página que você procura não existe ou foi movida."
    ), 404


@app.errorhandler(500)
def erro_500(e):
    app.logger.error(f"[500] Erro interno: {e}")
    return render_template(
        "erro.html",
        codigo=500,
        titulo="Erro interno",
        mensagem="Ocorreu um erro no servidor. Contate o administrador."
    ), 500



registrar_blueprints(app)

# O wizard de instalação é registrado sempre, independente de
# "modulos_ativos" — ele roda antes de existir configuração/admin
# na instalação, então não pode depender do que ainda será definido.
from wizard.api_wizard import blueprint as wizard_blueprint
app.register_blueprint(wizard_blueprint, url_prefix="/wizard")

# Notificações também são infraestrutura sempre presente, não um módulo
# contratável — todo módulo pode gerar notificações independentemente
# do pacote de módulos ativado nesta instalação.
from core.notificacoes import blueprint as notificacoes_blueprint
app.register_blueprint(notificacoes_blueprint, url_prefix="/notificacoes")


if __name__ == "__main__":
    host  = config.get("host_api", "0.0.0.0")
    porta = int(config.get("porta_api", 5000))
    https_habilitado = bool(config.get("https_habilitado", False))

    ssl_context = None
    esquema = "http"
    if https_habilitado:
        from core.tls import obter_contexto_ssl
        try:
            pasta_dados = Path(config.get("caminho_base", str(BASE)))
            ssl_context = obter_contexto_ssl(pasta_dados)
            esquema = "https"
        except Exception as e:
            # Não deixa o servidor inteiro cair por causa do TLS — melhor
            # subir sem HTTPS e deixar isso visível no log do que a escola
            # ficar sem sistema nenhum. https_habilitado=True + falha aqui
            # é algo que precisa ser investigado, mas não é motivo para
            # negar acesso a portaria/portões etc.
            app.logger.error(f"[TLS] Falha ao preparar HTTPS, subindo em HTTP: {e}")

    nome_exibicao = config.get("sigla_escola") or config.get("nome_escola") or "não configurado"
    titulo = f"Smart Campus — {nome_exibicao}"
    titulo = titulo[:50]  # nunca estoura a largura da caixa, mesmo com nome bem comprido
    print(f"""
╔══════════════════════════════════════════════════════╗
║{titulo.center(54)}║
╠══════════════════════════════════════════════════════╣
║  Endereço local : {esquema}://localhost:{porta:<20}║
║  Rede escolar   : {esquema}://[IP-deste-PC]:{porta:<17}║
║  Para encerrar  : Ctrl+C                             ║
╚══════════════════════════════════════════════════════╝
""")

    app.run(
        host=host,
        port=porta,
        debug=False,
        threaded=True,
        ssl_context=ssl_context,
    )
