
import json
import re
import shutil
import string
import random
import secrets
import unicodedata
import zipfile
from pathlib import Path
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, send_file

from core.auth import (
    perfil_obrigatorio, listar_usuarios, criar_usuario,
    desativar_usuario, reativar_usuario, redefinir_senha,
    MODULOS_POR_PERFIL, usuario_logado, alterar_cargo_usuario,
)
from core.router import perfil_para_label
from core.auditoria import registrar as registrar_auditoria
import core.cargos as cargos_mod

blueprint = Blueprint("admin", __name__, template_folder="../templates/admin")

BASE = Path(__file__).resolve().parent
CAMINHO_RECURSOS      = BASE.parent / "modulos" / "agendamento" / "recursos.json"
CAMINHO_DISPOSITIVOS  = BASE.parent / "modulos" / "iot" / "dispositivos.json"


def _caminho_config() -> Path:
    from core.config_path import resolver_config_path
    return resolver_config_path(BASE.parent)

def _carregar_config() -> dict:
    with open(_caminho_config(), encoding="utf-8") as f:
        return json.load(f)

def _salvar_config(cfg: dict) -> None:
    with open(_caminho_config(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def _get_db():
    import sys
    cfg = _carregar_config()
    base = Path(cfg["caminho_base"])
    sys.path.insert(0, str(base))
    from sceds import SCEDS
    return SCEDS(base / "sceds" / "data")

def _pasta_backup() -> Path:
    """
    Pasta única de backups, compartilhada entre o agendador automático
    (core/backup.py, iniciado em app.py) e este painel administrativo —
    os dois leem/escrevem no mesmo lugar e no mesmo formato de arquivo
    (.zip único por backup, sem pasta intermediária), então "Fazer
    backup agora" aqui e os backups automáticos de 6 em 6 horas aparecem
    juntos na mesma listagem, sem duplicar mecanismo.
    """
    cfg = _carregar_config()
    return Path(cfg["caminho_base"]) / "backups"

def _pasta_dados_sceds() -> Path:
    cfg = _carregar_config()
    return Path(cfg["caminho_base"]) / "sceds" / "data"

def _pasta_logs() -> Path:
    cfg = _carregar_config()
    return Path(cfg["caminho_base"]) / "logs"


def _slugificar(texto: str) -> str:
    """Converte um nome em um id de recurso (slug): minúsculo, sem acento, com underscores."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")
    return slug or "recurso"


def _gerar_token() -> str:
    return secrets.token_hex(12)


def gerar_senha_sugerida(nome: str = "") -> str:
    """Gera uma senha legível e razoavelmente segura, no mesmo espírito do instalador."""
    sufixo = "".join(random.choices(string.digits, k=4))
    especial = random.choice("@#$!")
    if nome:
        base = "".join(ch for ch in nome if ch.isalnum())[:6].capitalize() or "Usuario"
        return f"{base}{especial}{sufixo}"
    chars = string.ascii_letters + string.digits + "@#$!"
    return "".join(random.choices(chars, k=10))


@blueprint.route("/")
@perfil_obrigatorio("admin")
def index():
    return render_template("admin/index.html")


@blueprint.route("/usuarios")
@perfil_obrigatorio("admin")
def pagina_usuarios():
    perfis = sorted(MODULOS_POR_PERFIL.keys())
    labels_perfil = {p: perfil_para_label(p) for p in perfis}
    return render_template("admin/usuarios.html", perfis=perfis, labels_perfil=labels_perfil,
                            cargos=cargos_mod.listar_cargos())

@blueprint.route("/api/usuarios")
@perfil_obrigatorio("admin")
def api_listar_usuarios():
    return jsonify(listar_usuarios())

@blueprint.route("/api/usuarios/sugerir-senha")
@perfil_obrigatorio("admin")
def api_sugerir_senha():
    nome = request.args.get("nome", "")
    return jsonify({"senha": gerar_senha_sugerida(nome)})

@blueprint.route("/api/usuarios", methods=["POST"])
@perfil_obrigatorio("admin")
def api_criar_usuario():
    """Body: nome, senha, e (cargo_id) OU (perfil, legado — vira o cargo padrão daquele perfil)."""
    dados    = request.get_json(force=True)
    nome     = dados.get("nome", "").strip()
    senha    = dados.get("senha", "").strip()
    cargo_id = dados.get("cargo_id")
    perfil   = dados.get("perfil", "").strip()

    try:
        registro = criar_usuario(nome, perfil, senha, cargo_id=cargo_id)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400

    registrar_auditoria(
        usuario_logado(), "criou_usuario", entidade="usuarios",
        entidade_id=registro["id"], detalhes={"nome": nome, "cargo_id": cargo_id, "perfil": registro.get("perfil")},
    )
    return jsonify({"ok": True, "usuario": {k: v for k, v in registro.items() if k != "senha_hash"}}), 201

@blueprint.route("/api/usuarios/<int:usuario_id>/cargo", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_alterar_cargo_usuario(usuario_id: int):
    """Body: cargo_id."""
    dados = request.get_json(force=True)
    cargo_id = dados.get("cargo_id")
    try:
        registro = alterar_cargo_usuario(usuario_id, cargo_id)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    registrar_auditoria(usuario_logado(), "alterou_cargo_usuario", entidade="usuarios",
                         entidade_id=usuario_id, detalhes={"cargo_id": cargo_id})
    return jsonify({"ok": True, "usuario": {k: v for k, v in registro.items() if k != "senha_hash"}})

@blueprint.route("/api/usuarios/<int:usuario_id>/desativar", methods=["POST"])
@perfil_obrigatorio("admin")
def api_desativar_usuario(usuario_id: int):
    if desativar_usuario(usuario_id):
        registrar_auditoria(usuario_logado(), "desativou_usuario", entidade="usuarios", entidade_id=usuario_id)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "erro": "Usuário não encontrado."}), 404

@blueprint.route("/api/usuarios/<int:usuario_id>/reativar", methods=["POST"])
@perfil_obrigatorio("admin")
def api_reativar_usuario(usuario_id: int):
    if reativar_usuario(usuario_id):
        registrar_auditoria(usuario_logado(), "reativou_usuario", entidade="usuarios", entidade_id=usuario_id)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "erro": "Usuário não encontrado."}), 404

@blueprint.route("/api/usuarios/<int:usuario_id>/redefinir-senha", methods=["POST"])
@perfil_obrigatorio("admin")
def api_redefinir_senha(usuario_id: int):
    """Body: nova_senha (opcional — se ausente, gera uma automaticamente)."""
    dados = request.get_json(silent=True) or {}
    nova_senha = dados.get("nova_senha", "").strip()

    db = _get_db()
    usuario = db.buscar_um("usuarios", onde={"id": usuario_id})
    if not usuario:
        return jsonify({"ok": False, "erro": "Usuário não encontrado."}), 404

    if not nova_senha:
        nova_senha = gerar_senha_sugerida(usuario["nome"])

    try:
        redefinir_senha(usuario_id, nova_senha)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400

    registrar_auditoria(usuario_logado(), "redefiniu_senha", entidade="usuarios", entidade_id=usuario_id)
    return jsonify({"ok": True, "nova_senha": nova_senha})


# ── Cargos e Permissões -------------------------------------------------

@blueprint.route("/cargos")
@perfil_obrigatorio("admin")
def pagina_cargos():
    perfis = sorted(MODULOS_POR_PERFIL.keys())
    labels_perfil = {p: perfil_para_label(p) for p in perfis}
    catalogo_modulos = {p: cargos_mod.modulos_disponiveis(p) for p in perfis}
    catalogo_modulos_exibicao = {p: cargos_mod.modulos_com_status_contrato(p) for p in perfis}
    return render_template(
        "admin/cargos.html",
        perfis=perfis,
        labels_perfil=labels_perfil,
        catalogo_modulos=catalogo_modulos,
        catalogo_modulos_exibicao=catalogo_modulos_exibicao,
        turnos_existentes=cargos_mod.turnos_existentes(),
    )

@blueprint.route("/api/cargos")
@perfil_obrigatorio("admin")
def api_listar_cargos():
    return jsonify(cargos_mod.listar_cargos())

@blueprint.route("/api/cargos", methods=["POST"])
@perfil_obrigatorio("admin")
def api_criar_cargo():
    """Body: nome, perfil_base, modulos ([...]), escopo_turno ([...] ou ["todos"])."""
    dados = request.get_json(force=True)
    try:
        cargo = cargos_mod.criar_cargo(
            nome=dados.get("nome", ""),
            perfil_base=dados.get("perfil_base", ""),
            modulos=dados.get("modulos") or [],
            escopo_turno=dados.get("escopo_turno") or ["todos"],
        )
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    registrar_auditoria(usuario_logado(), "criou_cargo", entidade="cargos", entidade_id=cargo["id"],
                         detalhes={"nome": cargo["nome"]})
    return jsonify({"ok": True, "cargo": cargo}), 201

@blueprint.route("/api/cargos/<int:cargo_id>", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_atualizar_cargo(cargo_id: int):
    """Body: nome?, modulos?, escopo_turno? (qualquer subconjunto — só atualiza o que vier)."""
    dados = request.get_json(force=True)
    try:
        cargo = cargos_mod.atualizar_cargo(
            cargo_id,
            nome=dados.get("nome"),
            modulos=dados.get("modulos"),
            escopo_turno=dados.get("escopo_turno"),
        )
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    registrar_auditoria(usuario_logado(), "atualizou_cargo", entidade="cargos", entidade_id=cargo_id, detalhes=dados)
    return jsonify({"ok": True, "cargo": cargo})

@blueprint.route("/api/cargos/<int:cargo_id>", methods=["DELETE"])
@perfil_obrigatorio("admin")
def api_remover_cargo(cargo_id: int):
    try:
        removido = cargos_mod.remover_cargo(cargo_id)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    if not removido:
        return jsonify({"ok": False, "erro": "Cargo não encontrado."}), 404
    registrar_auditoria(usuario_logado(), "removeu_cargo", entidade="cargos", entidade_id=cargo_id)
    return jsonify({"ok": True})


@blueprint.route("/backup")
@perfil_obrigatorio("admin")
def pagina_backup():
    return render_template("admin/backup.html")

@blueprint.route("/api/backup/historico")
@perfil_obrigatorio("admin")
def api_backup_historico():
    """Lista os backups já realizados (arquivos backup_*.zip em /backups)."""
    pasta = _pasta_backup()
    pasta.mkdir(parents=True, exist_ok=True)

    itens = []
    for zip_path in sorted(pasta.glob("backup_*.zip"), reverse=True):
        try:
            with zipfile.ZipFile(zip_path) as zf:
                total_tabelas = sum(1 for n in zf.namelist() if n.endswith(".sceds"))
        except zipfile.BadZipFile:
            # Backup interrompido/corrompido nunca deveria existir com o
            # nome final (core/backup.py só faz os.replace após terminar
            # a escrita com sucesso) — mas se acontecer por qualquer
            # outro motivo, não deixa a listagem inteira quebrar por causa
            # de um arquivo ruim.
            total_tabelas = 0
        itens.append({
            "nome":           zip_path.stem,
            "data_hora":      zip_path.stem.replace("backup_", ""),
            "total_tabelas":  total_tabelas,
            "tamanho_kb":     round(zip_path.stat().st_size / 1024, 1),
            "zip_disponivel": True,
        })
    return jsonify(itens[:30])

@blueprint.route("/api/backup/executar", methods=["POST"])
@perfil_obrigatorio("admin")
def api_backup_executar():
    """Executa um backup completo de todas as tabelas do SCEDS, agora."""
    from core.backup import executar_backup

    try:
        zip_path = executar_backup(_pasta_dados_sceds(), _pasta_backup())
    except Exception as e:
        return jsonify({"ok": False, "erro": f"Falha ao gerar backup: {e}"}), 500

    with zipfile.ZipFile(zip_path) as zf:
        total_tabelas = sum(1 for n in zf.namelist() if n.endswith(".sceds"))

    return jsonify({
        "ok": True,
        "nome": zip_path.stem,
        "total_tabelas": total_tabelas,
        "mensagem": f"Backup concluído com {total_tabelas} tabela(s).",
    }), 201

@blueprint.route("/api/backup/download/<nome>")
@perfil_obrigatorio("admin")
def api_backup_download(nome: str):
    """Envia o arquivo .zip de um backup específico para download."""
    nome_seguro = Path(nome).name
    zip_path = _pasta_backup() / f"{nome_seguro}.zip"
    if not zip_path.exists():
        return jsonify({"ok": False, "erro": "Backup não encontrado."}), 404
    return send_file(zip_path, as_attachment=True, download_name=f"{nome_seguro}.zip")

@blueprint.route("/api/backup/<nome>", methods=["DELETE"])
@perfil_obrigatorio("admin")
def api_backup_remover(nome: str):
    """Remove um backup antigo para liberar espaço."""
    nome_seguro = Path(nome).name
    zip_path = _pasta_backup() / f"{nome_seguro}.zip"

    if not zip_path.exists():
        return jsonify({"ok": False, "erro": "Backup não encontrado."}), 404

    zip_path.unlink()
    return jsonify({"ok": True})


@blueprint.route("/configuracoes")
@perfil_obrigatorio("admin")
def pagina_configuracoes():
    return render_template("admin/configuracoes.html")

@blueprint.route("/api/configuracoes")
@perfil_obrigatorio("admin")
def api_obter_configuracoes():
    return jsonify(_carregar_config())

@blueprint.route("/api/configuracoes", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_salvar_configuracoes():
    """
    Body: porta_api, host_api, https_habilitado (todos opcionais — só
    altera o que for enviado). Alterações exigem reiniciar o servidor
    manualmente para ter efeito.
    """
    dados = request.get_json(force=True)
    cfg = _carregar_config()

    if "porta_api" in dados:
        try:
            porta = int(dados["porta_api"])
            if not (1 <= porta <= 65535):
                raise ValueError
            cfg["porta_api"] = porta
        except (TypeError, ValueError):
            return jsonify({"ok": False, "erro": "Porta inválida."}), 400

    if "host_api" in dados:
        host = str(dados["host_api"]).strip()
        if host:
            cfg["host_api"] = host

    if "https_habilitado" in dados:
        # Liga/desliga o certificado TLS autoassinado (ver core/tls.py).
        # Ligar isto faz o servidor passar a exigir https:// no endereço
        # acessado — endereços http:// salvos antigos (favoritos, atalhos)
        # param de funcionar até serem atualizados.
        cfg["https_habilitado"] = bool(dados["https_habilitado"])

    _salvar_config(cfg)
    return jsonify({"ok": True, "config": cfg, "aviso": "Reinicie o servidor (app.py) para aplicar as mudanças."})


# ── Módulos contratados -------------------------------------------------
# Antes, mudar o pacote de módulos de uma escola exigia rodar um script
# de linha de comando (licenciamento/emitir_licenca.py ou editar
# config.json na mão). Esta tela substitui isso por alguns cliques,
# direto no navegador — é a fonte de verdade lida por
# core/router.py -> modulos_ativos_permitidos em todo o sistema
# (registro de rotas, menu lateral, tela de Cargos).

CATALOGO_MODULOS_VENDAVEIS = [
    {"id": "sinal",               "nome": "Sinal (toque de aula)"},
    {"id": "agendamento",         "nome": "Agendamento de Recursos"},
    {"id": "biblioteca",          "nome": "Biblioteca"},
    {"id": "secretaria_portaria", "nome": "Secretaria e Portaria"},
    {"id": "iot",                 "nome": "Monitoramento IoT"},
    {"id": "ocorrencias",         "nome": "Ocorrências"},
    {"id": "evasao",              "nome": "Prevenção de Evasão"},
    {"id": "chaves",              "nome": "Controle de Chaves"},
    {"id": "chamados",            "nome": "Chamados Técnicos"},
    {"id": "monitoramento",       "nome": "Gráficos e Análise"},
    {"id": "alunos",              "nome": "Cadastro de Alunos"},
    {"id": "pontualidade",        "nome": "Controle de Pontualidade"},
    {"id": "saidas",              "nome": "Saídas de Alunos"},
    {"id": "visitantes",          "nome": "Controle de Visitantes"},
]
_IDS_MODULOS_VENDAVEIS = {m["id"] for m in CATALOGO_MODULOS_VENDAVEIS}


@blueprint.route("/modulos")
@perfil_obrigatorio("admin")
def pagina_modulos():
    return render_template("admin/modulos.html")


@blueprint.route("/api/modulos")
@perfil_obrigatorio("admin")
def api_obter_modulos():
    ativos = set(_carregar_config().get("modulos_ativos") or _IDS_MODULOS_VENDAVEIS)
    return jsonify({
        "catalogo": CATALOGO_MODULOS_VENDAVEIS,
        "ativos": sorted(ativos & _IDS_MODULOS_VENDAVEIS),
    })


@blueprint.route("/api/modulos", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_salvar_modulos():
    """Body: {"ativos": ["sinal", "biblioteca", ...]} — substitui a lista inteira."""
    dados = request.get_json(force=True)
    novos = dados.get("ativos")
    if not isinstance(novos, list):
        return jsonify({"ok": False, "erro": "Envie a lista de módulos em \"ativos\"."}), 400

    invalidos = set(novos) - _IDS_MODULOS_VENDAVEIS
    if invalidos:
        return jsonify({"ok": False, "erro": f"Módulo(s) desconhecido(s): {', '.join(sorted(invalidos))}."}), 400

    cfg = _carregar_config()
    cfg["modulos_ativos"] = sorted(set(novos))
    _salvar_config(cfg)
    registrar_auditoria(usuario_logado(), "atualizou_modulos_contratados", entidade="config",
                         detalhes={"modulos_ativos": cfg["modulos_ativos"]})
    return jsonify({
        "ok": True,
        "ativos": cfg["modulos_ativos"],
        "aviso": "Um módulo recém-ativado só passa a responder por URL depois que o servidor "
                 "for reiniciado. Desativar tem efeito imediato no menu e na tela de Cargos.",
    })

@blueprint.route("/api/logs")
@perfil_obrigatorio("admin")
def api_logs():
    """Retorna as últimas N linhas do log do servidor. Query: linhas (padrão 100)."""
    linhas_qtd = request.args.get("linhas", 100, type=int)
    linhas_qtd = max(10, min(linhas_qtd, 1000))

    caminho_log = _pasta_logs() / "servidor.log"
    if not caminho_log.exists():
        return jsonify({"linhas": [], "erro": "Arquivo de log ainda não existe."})

    with open(caminho_log, encoding="utf-8", errors="replace") as f:
        todas = f.readlines()

    ultimas = [l.rstrip("\n") for l in todas[-linhas_qtd:]]
    return jsonify({"linhas": ultimas, "total_arquivo": len(todas)})

@blueprint.route("/api/auditoria")
@perfil_obrigatorio("admin")
def api_auditoria():
    """
    Log de auditoria de negócio — quem fez o quê, quando (login, logout,
    criação/desativação de usuário, redefinição de senha, recuperação de
    acesso). Diferente de /api/logs, que é log técnico do servidor.
    Query: limite (padrão 200), usuario_id, acao.
    """
    from core.auditoria import listar as listar_auditoria

    limite = request.args.get("limite", 200, type=int)
    limite = max(10, min(limite, 1000))
    usuario_id = request.args.get("usuario_id", type=int)
    acao = request.args.get("acao")

    eventos = listar_auditoria(limite=limite, filtro_usuario_id=usuario_id, filtro_acao=acao)
    return jsonify(eventos)

@blueprint.route("/api/status-sistema")
@perfil_obrigatorio("admin")
def api_status_sistema():
    """Informações gerais para o painel: espaço usado, quantidade de tabelas, versão."""
    cfg = _carregar_config()
    db = _get_db()

    pasta_dados = Path(cfg["caminho_base"]) / "sceds" / "data"
    tamanho_dados = sum(f.stat().st_size for f in pasta_dados.glob("*.sceds")) if pasta_dados.exists() else 0

    return jsonify({
        "versao":            cfg.get("versao", "?"),
        "caminho_base":      cfg.get("caminho_base"),
        "total_tabelas":     len(db.listar_tabelas()),
        "tamanho_dados_kb":  round(tamanho_dados / 1024, 1),
    })


# ══════════════════════════════════════════════════════════════
# GERENCIAMENTO DE RECURSOS (Agendamento)
# Antes era só editando modulos/agendamento/recursos.json na mão.
# ══════════════════════════════════════════════════════════════

TIPOS_RECURSO_VALIDOS = ("laboratorio", "sala", "espaco", "equipamento")


def _carregar_recursos() -> list:
    with open(CAMINHO_RECURSOS, encoding="utf-8") as f:
        return json.load(f)["recursos"]


def _salvar_recursos(recursos: list) -> None:
    with open(CAMINHO_RECURSOS, "w", encoding="utf-8") as f:
        json.dump({"recursos": recursos}, f, ensure_ascii=False, indent=2)


def _recurso_em_uso(recurso_id: str) -> bool:
    """True se existir alguma reserva ativa (não devolvida) para esse recurso."""
    db = _get_db()
    reservas = db.buscar("reservas", onde={"recurso_id": recurso_id})
    return any(not r.get("devolvido") for r in reservas)


@blueprint.route("/recursos")
@perfil_obrigatorio("admin")
def pagina_recursos():
    return render_template("admin/recursos.html", tipos=TIPOS_RECURSO_VALIDOS)


@blueprint.route("/api/recursos")
@perfil_obrigatorio("admin")
def api_listar_recursos():
    return jsonify(_carregar_recursos())


@blueprint.route("/api/recursos", methods=["POST"])
@perfil_obrigatorio("admin")
def api_criar_recurso():
    """Body: nome, tipo, icone (opcional)."""
    dados = request.get_json(force=True)
    nome  = (dados.get("nome") or "").strip()
    tipo  = (dados.get("tipo") or "").strip()
    icone = (dados.get("icone") or "i-box").strip() or "i-box"

    if not nome:
        return jsonify({"ok": False, "erro": "Informe o nome do recurso."}), 400
    if tipo not in TIPOS_RECURSO_VALIDOS:
        return jsonify({"ok": False, "erro": "Tipo inválido."}), 400

    recursos = _carregar_recursos()

    slug_base = _slugificar(nome)
    slug = slug_base
    contador = 2
    ids_existentes = {r["id"] for r in recursos}
    while slug in ids_existentes:
        slug = f"{slug_base}_{contador}"
        contador += 1

    novo = {"id": slug, "nome": nome, "tipo": tipo, "icone": icone}
    recursos.append(novo)
    _salvar_recursos(recursos)

    return jsonify({"ok": True, "recurso": novo}), 201


@blueprint.route("/api/recursos/<recurso_id>", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_editar_recurso(recurso_id: str):
    """Body: nome, tipo, icone. O id nunca muda (reservas antigas referenciam ele)."""
    dados = request.get_json(force=True)
    recursos = _carregar_recursos()
    recurso = next((r for r in recursos if r["id"] == recurso_id), None)
    if not recurso:
        return jsonify({"ok": False, "erro": "Recurso não encontrado."}), 404

    nome  = (dados.get("nome") or "").strip()
    tipo  = (dados.get("tipo") or "").strip()
    icone = (dados.get("icone") or "").strip()

    if nome:
        recurso["nome"] = nome
    if tipo:
        if tipo not in TIPOS_RECURSO_VALIDOS:
            return jsonify({"ok": False, "erro": "Tipo inválido."}), 400
        recurso["tipo"] = tipo
    if icone:
        recurso["icone"] = icone

    _salvar_recursos(recursos)
    return jsonify({"ok": True, "recurso": recurso})


@blueprint.route("/api/recursos/<recurso_id>", methods=["DELETE"])
@perfil_obrigatorio("admin")
def api_remover_recurso(recurso_id: str):
    recursos = _carregar_recursos()
    if not any(r["id"] == recurso_id for r in recursos):
        return jsonify({"ok": False, "erro": "Recurso não encontrado."}), 404

    if _recurso_em_uso(recurso_id):
        return jsonify({"ok": False, "erro": "Esse recurso tem reservas ativas. Aguarde a devolução antes de remover."}), 409

    recursos = [r for r in recursos if r["id"] != recurso_id]
    _salvar_recursos(recursos)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════
# CONFIGURAÇÃO DE DISPOSITIVOS IoT
# Antes era só editando modulos/iot/dispositivos.json na mão.
# Trocar um token aqui exige reconfigurar o firmware do dispositivo
# físico correspondente — o front avisa isso antes de confirmar.
# ══════════════════════════════════════════════════════════════

def _carregar_dispositivos() -> dict:
    with open(CAMINHO_DISPOSITIVOS, encoding="utf-8") as f:
        return json.load(f)


def _salvar_dispositivos(cfg: dict) -> None:
    with open(CAMINHO_DISPOSITIVOS, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


@blueprint.route("/dispositivos-iot")
@perfil_obrigatorio("admin")
def pagina_dispositivos_iot():
    return render_template("admin/dispositivos_iot.html")


@blueprint.route("/api/dispositivos-iot")
@perfil_obrigatorio("admin")
def api_obter_dispositivos():
    return jsonify(_carregar_dispositivos())


# ---- Sensores de água ------------------------------------------------

@blueprint.route("/api/dispositivos-iot/agua/sensores", methods=["POST"])
@perfil_obrigatorio("admin")
def api_criar_sensor_agua():
    """Body: nome, hardware, limite_minimo."""
    dados = request.get_json(force=True)
    nome  = (dados.get("nome") or "").strip()
    if not nome:
        return jsonify({"ok": False, "erro": "Informe o nome do sensor."}), 400

    try:
        limite = int(dados.get("limite_minimo", 20))
    except (TypeError, ValueError):
        limite = 20

    cfg = _carregar_dispositivos()
    slug_base = _slugificar(nome)
    slug = slug_base
    contador = 2
    ids_existentes = {s["id"] for s in cfg["agua"]["sensores"]}
    while slug in ids_existentes:
        slug = f"{slug_base}_{contador}"
        contador += 1

    novo = {
        "id":             slug,
        "nome":           nome,
        "hardware":       (dados.get("hardware") or "ESP32 + JSN-SR04T").strip(),
        "limite_minimo":  limite,
        "token":          _gerar_token(),
    }
    cfg["agua"]["sensores"].append(novo)
    _salvar_dispositivos(cfg)
    return jsonify({"ok": True, "sensor": novo}), 201


@blueprint.route("/api/dispositivos-iot/agua/sensores/<sensor_id>", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_editar_sensor_agua(sensor_id: str):
    """Body: nome, hardware, limite_minimo (o id e o token não mudam aqui)."""
    dados = request.get_json(force=True)
    cfg = _carregar_dispositivos()
    sensor = next((s for s in cfg["agua"]["sensores"] if s["id"] == sensor_id), None)
    if not sensor:
        return jsonify({"ok": False, "erro": "Sensor não encontrado."}), 404

    if dados.get("nome"):
        sensor["nome"] = dados["nome"].strip()
    if dados.get("hardware"):
        sensor["hardware"] = dados["hardware"].strip()
    if "limite_minimo" in dados:
        try:
            sensor["limite_minimo"] = int(dados["limite_minimo"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "erro": "Limite mínimo inválido."}), 400

    _salvar_dispositivos(cfg)
    return jsonify({"ok": True, "sensor": sensor})


@blueprint.route("/api/dispositivos-iot/agua/sensores/<sensor_id>", methods=["DELETE"])
@perfil_obrigatorio("admin")
def api_remover_sensor_agua(sensor_id: str):
    cfg = _carregar_dispositivos()
    antes = len(cfg["agua"]["sensores"])
    cfg["agua"]["sensores"] = [s for s in cfg["agua"]["sensores"] if s["id"] != sensor_id]
    if len(cfg["agua"]["sensores"]) == antes:
        return jsonify({"ok": False, "erro": "Sensor não encontrado."}), 404

    _salvar_dispositivos(cfg)
    return jsonify({"ok": True})


@blueprint.route("/api/dispositivos-iot/agua/sensores/<sensor_id>/gerar-token", methods=["POST"])
@perfil_obrigatorio("admin")
def api_gerar_token_sensor_agua(sensor_id: str):
    cfg = _carregar_dispositivos()
    sensor = next((s for s in cfg["agua"]["sensores"] if s["id"] == sensor_id), None)
    if not sensor:
        return jsonify({"ok": False, "erro": "Sensor não encontrado."}), 404

    sensor["token"] = _gerar_token()
    _salvar_dispositivos(cfg)
    return jsonify({"ok": True, "token": sensor["token"]})


# ---- Portões -----------------------------------------------------------

@blueprint.route("/api/dispositivos-iot/portoes", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_editar_portoes():
    """Body: hardware, horario_abertura, horario_fechamento."""
    dados = request.get_json(force=True)
    cfg = _carregar_dispositivos()

    for campo in ("hardware", "horario_abertura", "horario_fechamento"):
        if dados.get(campo):
            cfg["portoes"][campo] = dados[campo].strip()

    _salvar_dispositivos(cfg)
    return jsonify({"ok": True, "portoes": cfg["portoes"]})


@blueprint.route("/api/dispositivos-iot/portoes/gerar-token", methods=["POST"])
@perfil_obrigatorio("admin")
def api_gerar_token_portoes():
    cfg = _carregar_dispositivos()
    cfg["portoes"]["token"] = _gerar_token()
    _salvar_dispositivos(cfg)
    return jsonify({"ok": True, "token": cfg["portoes"]["token"]})


@blueprint.route("/api/dispositivos-iot/portoes/lista", methods=["POST"])
@perfil_obrigatorio("admin")
def api_adicionar_portao():
    """Body: nome."""
    dados = request.get_json(force=True)
    nome = (dados.get("nome") or "").strip()
    if not nome:
        return jsonify({"ok": False, "erro": "Informe o nome do portão."}), 400

    cfg = _carregar_dispositivos()
    slug_base = _slugificar(nome)
    slug = slug_base
    contador = 2
    ids_existentes = {p["id"] for p in cfg["portoes"]["lista"]}
    while slug in ids_existentes:
        slug = f"{slug_base}_{contador}"
        contador += 1

    novo = {"id": slug, "nome": nome}
    cfg["portoes"]["lista"].append(novo)
    _salvar_dispositivos(cfg)
    return jsonify({"ok": True, "portao": novo}), 201


@blueprint.route("/api/dispositivos-iot/portoes/lista/<portao_id>", methods=["DELETE"])
@perfil_obrigatorio("admin")
def api_remover_portao(portao_id: str):
    cfg = _carregar_dispositivos()
    antes = len(cfg["portoes"]["lista"])
    cfg["portoes"]["lista"] = [p for p in cfg["portoes"]["lista"] if p["id"] != portao_id]
    if len(cfg["portoes"]["lista"]) == antes:
        return jsonify({"ok": False, "erro": "Portão não encontrado."}), 404

    _salvar_dispositivos(cfg)
    return jsonify({"ok": True})


# ---- Ar-condicionado -----------------------------------------------------

@blueprint.route("/api/dispositivos-iot/ar-condicionado", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_editar_ar_condicionado():
    """Body: nome, hardware, quantidade, horario_ligar, dias_semana_automacao (lista de 0-6, 0=segunda)."""
    dados = request.get_json(force=True)
    cfg = _carregar_dispositivos()
    ac = cfg["ar_condicionado"]

    for campo in ("nome", "hardware", "horario_ligar"):
        if dados.get(campo):
            ac[campo] = dados[campo].strip()

    if "quantidade" in dados:
        try:
            ac["quantidade"] = int(dados["quantidade"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "erro": "Quantidade inválida."}), 400

    if "dias_semana_automacao" in dados:
        try:
            dias = [int(d) for d in dados["dias_semana_automacao"]]
            if any(d < 0 or d > 6 for d in dias):
                raise ValueError
            ac["dias_semana_automacao"] = sorted(set(dias))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "erro": "Dias da semana inválidos."}), 400

    _salvar_dispositivos(cfg)
    return jsonify({"ok": True, "ar_condicionado": ac})


@blueprint.route("/api/dispositivos-iot/ar-condicionado/gerar-token", methods=["POST"])
@perfil_obrigatorio("admin")
def api_gerar_token_ar_condicionado():
    cfg = _carregar_dispositivos()
    cfg["ar_condicionado"]["token"] = _gerar_token()
    _salvar_dispositivos(cfg)
    return jsonify({"ok": True, "token": cfg["ar_condicionado"]["token"]})
