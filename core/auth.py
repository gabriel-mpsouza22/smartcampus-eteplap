
import json
import hashlib
import functools
import logging
import secrets
from pathlib import Path
from datetime import datetime
from flask import session, redirect, url_for, request, jsonify


from core.config_path import resolver_config_path

logger = logging.getLogger("smartcampus.auth")

# Verdadeiro assim que uma tentativa de hashing/verificação já constatou,
# nesta execução do processo, que o bcrypt não está instalado. Evita
# logar o mesmo aviso CRÍTICO a cada requisição de login — uma vez por
# processo já é suficiente para o time de suporte perceber e corrigir a
# instalação (instalar o wheel de bcrypt correto para a versão do Python
# em uso).
_avisou_bcrypt_ausente = False


def _bcrypt_disponivel() -> bool:
    try:
        import bcrypt  # noqa: F401
        return True
    except ImportError:
        global _avisou_bcrypt_ausente
        if not _avisou_bcrypt_ausente:
            _avisou_bcrypt_ausente = True
            logger.critical(
                "bcrypt não está instalado nesta instalação — caindo para o "
                "fallback SHA-256+salt (mais fraco contra quebra offline caso "
                "o arquivo de usuários vaze). Instale o wheel de bcrypt "
                "correspondente à versão do Python em uso o quanto antes; "
                "senhas em SHA-256 são automaticamente atualizadas para "
                "bcrypt no próximo login bem-sucedido de cada usuário, assim "
                "que bcrypt estiver disponível."
            )
        return False

_CONFIG_PATH = resolver_config_path(Path(__file__).resolve().parent.parent)

def _carregar_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def _get_db():
    """Retorna instância do SCEDS apontando para os dados do projeto."""
    config = _carregar_config()
    base = Path(config["caminho_base"])
    import sys
    sys.path.insert(0, str(base))
    from sceds import SCEDS
    db = SCEDS(base / "sceds" / "data")
    # Auto-evolução de schema: instalações feitas antes do sistema de
    # Cargos e Permissões não têm a coluna "cargo_id" — adicionada aqui
    # de forma idempotente, sem exigir migração manual (mesmo espírito
    # de core/alunos.py). Usuários sem cargo_id continuam funcionando
    # normalmente: core.cargos.resolver_efetivo() cai no cargo padrão
    # do perfil deles automaticamente.
    if db.tabela_existe("usuarios"):
        db.adicionar_coluna_se_ausente("usuarios", {"nome": "cargo_id", "tipo": "INTEIRO", "modificadores": []})
    return db


# Mapeia o "id" usado nos itens de menu abaixo para o "id" de módulo
# usado em core/router.py e em config.json → modulos_ativos. Precisa
# existir porque um único módulo (ex: Secretaria-Portaria) pode gerar
# dois itens de menu diferentes conforme o perfil (secretaria/portaria).
MENU_ID_PARA_MODULO = {
    "sinal":          "sinal",
    "agendamento":    "agendamento",
    "biblioteca":     "biblioteca",
    "secretaria":     "secretaria_portaria",
    "portaria":       "secretaria_portaria",
    "chaves":         "chaves",
    "iot":            "iot",
    "ocorrencias":    "ocorrencias",
    "evasao":         "evasao",
    "monitoramento":  "monitoramento",
    "chamados":       "chamados",
    "alunos":         "alunos",
    "pontualidade":   "pontualidade",
    "admin":          "admin",
    "saidas_secretaria":   "saidas",
    "saidas_coordenacao":  "saidas",
    "saidas_portaria":     "saidas",
    "visitantes_portaria": "visitantes",
    "visitantes_central":  "visitantes",
}


MODULOS_POR_PERFIL: dict[str, list[dict]] = {
    "professor": [
        {"id": "agendamento", "nome": "Agendamento de Recursos",
         "icone": "i-calendar", "url": "/agendamento/", "cor": "#2E86AB"},
        {"id": "chamados",    "nome": "Chamados Técnicos",
         "icone": "i-wrench", "url": "/chamados/",     "cor": "#3A7CA5"},
    ],
    "aluno_chamados": [
        {"id": "chamados",    "nome": "Chamados Técnicos",
         "icone": "i-wrench", "url": "/chamados/",     "cor": "#3A7CA5"},
    ],
    "portaria": [
        {"id": "visitantes_portaria", "nome": "Controle de Visitantes",
         "icone": "i-users", "url": "/visitantes/portaria", "cor": "#E76F51"},
        {"id": "saidas_portaria", "nome": "Saídas de Alunos",
         "icone": "i-door", "url": "/saidas/portaria", "cor": "#E76F51"},
        {"id": "portaria",    "nome": "Painel da Portaria",
         "icone": "i-door", "url": "/portaria/",    "cor": "#E76F51"},
        {"id": "pontualidade","nome": "Controle de Pontualidade",
         "icone": "i-clock", "url": "/pontualidade/", "cor": "#E76F51"},
        {"id": "iot",         "nome": "Monitoramento IoT",
         "icone": "i-antenna", "url": "/iot/painel",   "cor": "#2A9D8F"},
    ],
    "bibliotecaria": [
        {"id": "biblioteca",  "nome": "Biblioteca",
         "icone": "i-books", "url": "/biblioteca/",  "cor": "#8338EC"},
    ],
    "coordenadora": [
        {"id": "visitantes_central", "nome": "Visitantes",
         "icone": "i-users", "url": "/visitantes/central", "cor": "#F4A261"},
        {"id": "saidas_coordenacao", "nome": "Saídas de Alunos",
         "icone": "i-clipboard", "url": "/saidas/coordenacao", "cor": "#F4A261"},
        {"id": "sinal",       "nome": "Controle do Sinal",
         "icone": "i-bell", "url": "/sinal/painel", "cor": "#F4A261"},
        {"id": "ocorrencias", "nome": "Ocorrências",
         "icone": "i-clipboard", "url": "/ocorrencias/", "cor": "#E63946"},
        {"id": "evasao",      "nome": "Prevenção de Evasão",
         "icone": "i-target", "url": "/evasao/",      "cor": "#9D174D"},
        {"id": "monitoramento","nome": "Monitoramento",
         "icone": "i-bar-chart", "url": "/monitoramento/","cor": "#6A4C93"},
        {"id": "alunos",      "nome": "Cadastro de Alunos",
         "icone": "i-graduation", "url": "/alunos/",   "cor": "#2A9D8F"},
        {"id": "pontualidade","nome": "Pontualidade",
         "icone": "i-bar-chart", "url": "/pontualidade/dashboard", "cor": "#E76F51"},
    ],
    "secretaria": [
        {"id": "visitantes_central", "nome": "Visitantes",
         "icone": "i-users", "url": "/visitantes/central", "cor": "#457B9D"},
        {"id": "saidas_secretaria", "nome": "Saídas de Alunos",
         "icone": "i-door", "url": "/saidas/secretaria", "cor": "#457B9D"},
        {"id": "secretaria",  "nome": "Painel da Secretaria",
         "icone": "i-building", "url": "/secretaria/",  "cor": "#457B9D"},
        {"id": "agendamento", "nome": "Agendamento de Recursos",
         "icone": "i-calendar", "url": "/agendamento/", "cor": "#2E86AB"},
        {"id": "chaves",      "nome": "Controle de Chaves",
         "icone": "i-key", "url": "/chaves/",      "cor": "#B5838D"},
        {"id": "alunos",      "nome": "Cadastro de Alunos",
         "icone": "i-graduation", "url": "/alunos/",   "cor": "#2A9D8F"},
        {"id": "pontualidade","nome": "Controle de Pontualidade",
         "icone": "i-door", "url": "/pontualidade/", "cor": "#E76F51"},
    ],
    "admin": [
        {"id": "visitantes_central", "nome": "Visitantes",
         "icone": "i-users", "url": "/visitantes/central", "cor": "#457B9D"},
        {"id": "visitantes_portaria", "nome": "Visitantes — Portaria",
         "icone": "i-users", "url": "/visitantes/portaria", "cor": "#E76F51"},
        {"id": "saidas_secretaria", "nome": "Saídas de Alunos",
         "icone": "i-door", "url": "/saidas/secretaria", "cor": "#457B9D"},
        {"id": "agendamento", "nome": "Agendamento de Recursos",
         "icone": "i-calendar", "url": "/agendamento/", "cor": "#2E86AB"},
        {"id": "biblioteca",  "nome": "Biblioteca",
         "icone": "i-books", "url": "/biblioteca/",  "cor": "#8338EC"},
        {"id": "sinal",       "nome": "Controle do Sinal",
         "icone": "i-bell", "url": "/sinal/painel", "cor": "#F4A261"},
        {"id": "portaria",    "nome": "Painel da Portaria",
         "icone": "i-door", "url": "/portaria/",    "cor": "#E76F51"},
        {"id": "secretaria",  "nome": "Painel da Secretaria",
         "icone": "i-building", "url": "/secretaria/",  "cor": "#457B9D"},
        {"id": "chaves",      "nome": "Controle de Chaves",
         "icone": "i-key", "url": "/chaves/",      "cor": "#B5838D"},
        {"id": "iot",         "nome": "Monitoramento IoT",
         "icone": "i-antenna", "url": "/iot/painel",   "cor": "#2A9D8F"},
        {"id": "ocorrencias", "nome": "Ocorrências",
         "icone": "i-clipboard", "url": "/ocorrencias/", "cor": "#E63946"},
        {"id": "evasao",      "nome": "Prevenção de Evasão",
         "icone": "i-target", "url": "/evasao/",      "cor": "#9D174D"},
        {"id": "monitoramento","nome": "Gráficos e Análise",
         "icone": "i-bar-chart", "url": "/monitoramento/","cor": "#6A4C93"},
        {"id": "chamados",    "nome": "Chamados Técnicos",
         "icone": "i-wrench", "url": "/chamados/",     "cor": "#3A7CA5"},
        {"id": "admin",       "nome": "Administração",
         "icone": "i-tools",  "url": "/admin/",       "cor": "#1A1A2E"},
        {"id": "alunos",      "nome": "Cadastro de Alunos",
         "icone": "i-graduation", "url": "/alunos/",   "cor": "#2A9D8F"},
        {"id": "pontualidade","nome": "Pontualidade",
         "icone": "i-clock", "url": "/pontualidade/dashboard", "cor": "#E76F51"},
    ],
}


def _verificar_bcrypt(senha: str, hash_armazenado: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(senha.encode("utf-8"), hash_armazenado.encode("utf-8"))
    except Exception:
        return False

def _verificar_sha256(senha: str, hash_armazenado: str) -> bool:
    """
    Fallback para hashes SHA-256 gerados durante instalação sem bcrypt.

    Usa secrets.compare_digest (tempo constante) em vez de `==` direto
    em string: comparação normal de string faz short-circuit no
    primeiro byte diferente, o que teoricamente vaza, por timing, até
    onde o hash da tentativa e o hash correto coincidem — um jeito de
    reduzir a busca de força bruta a "um byte de cada vez" em vez de
    "o hash inteiro de uma vez". Medição local mostrou a diferença na
    ordem de 1ns (dominada por ruído do interpretador/rede), tornando
    o ataque pouco prático aqui — mas corrigir custa nada e é a prática
    correta para qualquer comparação de segredo/hash.
    """
    try:
        _, salt, h = hash_armazenado.split(":")
        h_calculado = hashlib.sha256(f"{salt}{senha}".encode()).hexdigest()
        return secrets.compare_digest(h_calculado, h)
    except Exception:
        return False

def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    if hash_armazenado.startswith("sha256:"):
        return _verificar_sha256(senha, hash_armazenado)
    return _verificar_bcrypt(senha, hash_armazenado)


def _atualizar_para_bcrypt_se_possivel(db, usuario: dict, senha_digitada: str) -> None:
    """
    Upgrade transparente de hash: se o usuário ainda tem uma senha em
    SHA-256+salt (fallback usado quando bcrypt não estava disponível no
    momento em que a senha foi definida) e o bcrypt já está disponível
    agora, re-hasheia a senha em bcrypt e atualiza o registro — sem
    exigir nenhuma ação do usuário além de logar normalmente. Login
    nunca falha por causa disso: qualquer problema aqui é apenas logado,
    nunca propagado.
    """
    hash_atual = usuario.get("senha_hash", "")
    if not hash_atual.startswith("sha256:") or not _bcrypt_disponivel():
        return
    try:
        novo_hash = _hash_senha(senha_digitada)
        db.atualizar("usuarios", {"senha_hash": novo_hash}, onde={"id": usuario["id"]})
        logger.info(
            "[Auth] Hash de senha do usuário id=%s atualizado de SHA-256 para bcrypt.",
            usuario["id"],
        )
    except Exception:
        logger.exception(
            "[Auth] Falha ao atualizar hash de senha para bcrypt (usuário id=%s).",
            usuario.get("id"),
        )


def reconfirmar_senha(senha_digitada: str) -> bool:
    """
    Reautentica a senha de quem está logado NESTA sessão (não de
    'qualquer usuário válido' — especificamente o dono da sessão atual),
    para confirmar ações sensíveis mesmo com a conta já aberta na tela.

    Existe porque login aqui é só por senha, sem usuário: se alguém deixa
    a própria sessão aberta num computador compartilhado, qualquer pessoa
    que sente na frente já está "logada" como ela. Pedir a senha de novo
    na hora de uma ação irreversível (como autorizar a saída de um aluno)
    garante que foi mesmo a coordenadora quem apertou o botão, não
    alguém que só achou a tela aberta.

    Retorna False também quando não há sessão ativa — nunca lança
    exceção, para que o chamador sempre trate como "não confirmado".
    """
    if not senha_digitada:
        return False
    db = _get_db()
    registro = db.buscar_um("usuarios", onde={"id": session.get("usuario_id")})
    if not registro or not registro.get("ativo", False):
        return False
    return verificar_senha(senha_digitada, registro.get("senha_hash", ""))


def autenticar(senha_digitada: str) -> dict | None:
    """
    Itera sobre todos os usuários ativos e compara a senha (bcrypt, com
    fallback para SHA-256+salt apenas se bcrypt não estiver instalado —
    ver _bcrypt_disponivel). Retorna dict com 'id', 'nome', 'perfil' se
    autenticado, ou None.
    """
    if not senha_digitada or len(senha_digitada.strip()) < 4:
        return None

    db = _get_db()
    usuarios = db.buscar("usuarios", onde={"ativo": True})

    for usuario in usuarios:
        if verificar_senha(senha_digitada, usuario.get("senha_hash", "")):
            _atualizar_para_bcrypt_se_possivel(db, usuario, senha_digitada)
            return {
                "id":     usuario["id"],
                "nome":   usuario["nome"],
                "perfil": usuario["perfil"],
            }

    return None


def criar_sessao(usuario: dict) -> None:
    """Salva os dados do usuário na sessão Flask."""
    session.permanent = True
    session["usuario_id"]     = usuario["id"]
    session["usuario_nome"]   = usuario["nome"]
    session["usuario_perfil"] = usuario["perfil"]
    session["login_em"]       = datetime.now().isoformat()

def destruir_sessao() -> None:
    """Encerra a sessão atual."""
    session.clear()

def usuario_logado() -> dict | None:
    """
    Retorna os dados do usuário logado a partir da sessão, ou None.

    Além de checar a sessão, confirma que o usuário ainda está ativo no
    banco. Sem isso, desativar um usuário (ex.: funcionário desligado)
    não revogava sessões já abertas — o cookie continuava valendo por até
    8h (app.permanent_session_lifetime) mesmo depois da conta ter sido
    desativada. Isso custa uma leitura no SCEDS por requisição autenticada;
    para o volume de uma instalação por escola isso é aceitável, e é a
    troca certa em favor de revogação imediata.
    """
    if "usuario_id" not in session:
        return None

    db = _get_db()
    registro = db.buscar_um("usuarios", onde={"id": session["usuario_id"]})
    if not registro or not registro.get("ativo", False):
        session.clear()
        return None

    from core.cargos import resolver_efetivo
    cargo = resolver_efetivo(registro, db=db)

    return {
        "id":     registro["id"],
        "nome":   registro["nome"],
        "perfil": registro["perfil"],
        **cargo,  # cargo_id, cargo_nome, perfil_base, modulos, escopo_turno
    }

# Agrupamento hierárquico da sidebar — dá ao usuário a sensação de uma
# única plataforma organizada por área, em vez de uma lista plana de
# módulos soltos. Mapeado pelo "id" do item de menu (não pelo id do
# módulo em si, já que um módulo pode gerar itens diferentes conforme
# o perfil — ver MENU_ID_PARA_MODULO acima).
GRUPO_DO_ITEM_MENU = {
    "alunos": "academico", "pontualidade": "academico",
    "evasao": "academico", "ocorrencias": "academico",

    "agendamento": "operacao", "chaves": "operacao",
    "saidas_secretaria": "operacao", "saidas_coordenacao": "operacao",
    "saidas_portaria": "operacao",
    "visitantes_portaria": "operacao", "visitantes_central": "operacao",
    "porteiro_painel": "operacao",

    "biblioteca": "servicos", "chamados": "servicos",
    "secretaria": "servicos", "portaria": "servicos",

    "iot": "infraestrutura", "monitoramento": "infraestrutura",
    "sinal": "infraestrutura",

    "admin": "administracao",
}

# Ordem fixa de exibição dos grupos — grupos sem nenhum item para o
# perfil atual simplesmente não aparecem (ver menu_agrupado_do_perfil).
_ORDEM_GRUPOS = ["academico", "operacao", "servicos", "infraestrutura", "administracao"]

_LABEL_GRUPO = {
    "academico": "Acadêmico",
    "operacao": "Operação",
    "servicos": "Serviços",
    "infraestrutura": "Infraestrutura",
    "administracao": "Administração",
}


def menu_agrupado_do_perfil(perfil: str) -> list[dict]:
    """Atalho legado — ver modulos_do_perfil(). Preferir menu_agrupado_do_usuario()."""
    return _agrupar_itens_menu(modulos_do_perfil(perfil))


def menu_agrupado_do_usuario(usuario: dict) -> list[dict]:
    """Como menu_agrupado_do_perfil, mas ciente do cargo específico do usuário."""
    return _agrupar_itens_menu(modulos_do_usuario(usuario))


def _agrupar_itens_menu(itens: list[dict]) -> list[dict]:
    por_grupo: dict[str, list[dict]] = {}
    for item in itens:
        grupo = GRUPO_DO_ITEM_MENU.get(item["id"], "operacao")
        por_grupo.setdefault(grupo, []).append(item)

    return [
        {"chave": grupo, "label": _LABEL_GRUPO[grupo], "itens": por_grupo[grupo]}
        for grupo in _ORDEM_GRUPOS
        if por_grupo.get(grupo)
    ]


def modulos_do_perfil(perfil: str) -> list[dict]:
    """
    Atalho legado: módulos do cargo PADRÃO de um perfil (ignora
    qualquer customização feita num cargo específico). Preferir
    modulos_do_usuario(usuario) sempre que houver um usuário logado —
    esta função existe para chamadas antigas que só têm o nome do
    perfil em mãos.
    """
    from core.cargos import cargo_padrao_do_perfil
    cargo = cargo_padrao_do_perfil(perfil)
    ids_permitidos = set(cargo["modulos"]) if cargo else set()
    return _filtrar_modulos_ativos(MODULOS_POR_PERFIL.get(perfil, []), ids_permitidos)


def modulos_do_usuario(usuario: dict, mesclar_porteiro: bool = True) -> list[dict]:
    """
    Retorna os módulos disponíveis para o usuário logado (dict retornado
    por usuario_logado()), já cruzando três filtros:
      1. o que o perfil-base do cargo normalmente pode acessar,
      2. o subconjunto que o cargo específico do usuário deixa visível,
      3. os módulos efetivamente contratados/ativos nesta instalação.

    mesclar_porteiro=False devolve a lista "crua", sem substituir
    pontualidade/saidas_portaria/visitantes_portaria pelo item
    combinado "porteiro_painel". Use False sempre que for checar se um
    ID individual específico está disponível (ex.: decidir quais abas
    mostrar dentro do próprio Painel do Porteiro) — usar a versão
    mesclada aí faria os 3 IDs "sumirem" exatamente quando há 2+
    disponíveis, que é o único caso em que a mesclagem acontece.
    """
    itens_base = MODULOS_POR_PERFIL.get(usuario.get("perfil_base") or usuario.get("perfil"), [])
    ids_permitidos = set(usuario.get("modulos") or [])
    itens = _filtrar_modulos_ativos(itens_base, ids_permitidos)
    return _mesclar_painel_porteiro(itens) if mesclar_porteiro else itens


# Módulos individuais absorvidos pelo Painel do Porteiro quando o
# usuário tem acesso a 2 ou mais deles ao mesmo tempo — junta 3 tarefas
# que antes exigiam navegar entre telas separadas numa única tela com
# abas (ver modulos/secretaria_portaria/api_sp.py -> pagina_portaria_unificada).
# Com só 1 disponível não há nada a "juntar": mostra o item normal.
_IDS_ABSORVIDOS_PELO_PAINEL_PORTEIRO = {"pontualidade", "saidas_portaria", "visitantes_portaria"}


def _mesclar_painel_porteiro(itens: list[dict]) -> list[dict]:
    presentes = [i for i in itens if i["id"] in _IDS_ABSORVIDOS_PELO_PAINEL_PORTEIRO]
    if len(presentes) < 2:
        return itens  # nada a ganhar juntando um único item — mantém como está

    item_combinado = {
        "id": "porteiro_painel", "nome": "Painel do Porteiro",
        "icone": "i-grid", "url": "/portaria/painel-unificado", "cor": "#E76F51",
    }
    restantes = [i for i in itens if i["id"] not in _IDS_ABSORVIDOS_PELO_PAINEL_PORTEIRO]
    # Entra no topo do grupo "Operação" (ver GRUPO_DO_ITEM_MENU) — é a
    # tarefa mais frequente do dia do porteiro, não devia estar escondida.
    return [item_combinado] + restantes


def _filtrar_modulos_ativos(itens: list[dict], ids_permitidos_pelo_cargo: set) -> list[dict]:
    from core.router import modulos_ativos_permitidos
    permitidos_instalacao = modulos_ativos_permitidos(_carregar_config())

    return [
        item for item in itens
        if item["id"] in ids_permitidos_pelo_cargo
        and MENU_ID_PARA_MODULO.get(item["id"], item["id"]) in permitidos_instalacao
    ]


def login_obrigatorio(f):
    """
    Decorator: redireciona para a tela de login se não houver sessão ativa.
    Para rotas de API (que retornam JSON), retorna 401 em vez de redirecionar.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not usuario_logado():
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"erro": "Não autenticado"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def perfil_obrigatorio(*perfis_permitidos):
    """
    Decorator: além de exigir login, verifica se o perfil tem permissão.
    Uso: @perfil_obrigatorio('admin', 'coordenadora')
    """
    def decorador(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            usuario = usuario_logado()
            if not usuario:
                if request.path.startswith("/api/") or request.is_json:
                    return jsonify({"erro": "Não autenticado"}), 401
                return redirect(url_for("login"))
            if usuario["perfil"] not in perfis_permitidos:
                return jsonify({"erro": "Acesso negado para este perfil"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorador


def _hash_senha(senha: str) -> str:
    """
    Gera o hash da senha. Usa bcrypt se disponível; caso contrário,
    cai para SHA-256 com salt (mesmo formato usado pelo install.py),
    já que nem todo Python tem wheel de bcrypt disponível (ex: 3.14
    recente). Toda vez que o fallback é usado, um aviso CRÍTICO é
    logado uma vez por processo (ver _bcrypt_disponivel) — hashes assim
    gerados são automaticamente atualizados para bcrypt no primeiro
    login bem-sucedido depois que bcrypt passar a estar disponível
    (ver _atualizar_para_bcrypt_se_possivel).
    """
    if _bcrypt_disponivel():
        import bcrypt
        return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    import os as _os, hashlib as _hashlib
    salt = _os.urandom(16).hex()
    h = _hashlib.sha256(f"{salt}{senha}".encode()).hexdigest()
    return f"sha256:{salt}:{h}"

def criar_usuario(nome: str, perfil: str, senha: str, cargo_id: int | None = None) -> dict:
    """
    Cria um novo usuário no SCEDS.
    Lança ValueError se a senha já existir no sistema (colisão proibida).

    cargo_id: se informado, o usuário fica vinculado a esse cargo
    específico (ex.: "Coordenadora do Integral") e o perfil é derivado
    automaticamente do perfil_base do cargo — o parâmetro `perfil` é
    então ignorado. Se omitido, mantém o comportamento antigo: o
    usuário fica no cargo PADRÃO daquele perfil (sem customização).

    A checagem de colisão e a inserção acontecem atomicamente (mesmo
    lock da tabela, via inserir_com_validacao) — checar e inserir como
    duas chamadas separadas permitia que duas requisições concorrentes
    (ex.: dois administradores criando conta ao mesmo tempo) passassem
    ambas pela checagem antes de qualquer uma escrever, resultando em
    dois usuários com a mesma senha e quebrando a premissa do modelo de
    login por senha única (achado de pentest, corrigido).
    """
    db = _get_db()

    if cargo_id is not None:
        from core.cargos import cargo_por_id
        cargo = cargo_por_id(cargo_id, db=db)
        if not cargo:
            raise ValueError("Cargo inválido.")
        perfil = cargo["perfil_base"]

    if not nome or not perfil or not senha:
        raise ValueError("Nome, perfil e senha são obrigatórios.")
    if perfil not in MODULOS_POR_PERFIL:
        raise ValueError(f"Perfil inválido: '{perfil}'.")
    if len(senha) < 6:
        raise ValueError("A senha deve ter no mínimo 6 caracteres.")

    def _recusar_se_senha_duplicada(registros_existentes):
        for u in registros_existentes:
            if verificar_senha(senha, u.get("senha_hash", "")):
                raise ValueError("Esta senha já está em uso por outro usuário.")

    registro = db.inserir_com_validacao("usuarios", {
        "nome":       nome,
        "perfil":     perfil,
        "cargo_id":   cargo_id,
        "senha_hash": _hash_senha(senha),
        "ativo":      True,
        "criado_em":  datetime.now().isoformat(),
    }, _recusar_se_senha_duplicada)
    return registro


def alterar_cargo_usuario(usuario_id: int, cargo_id: int) -> dict:
    """Muda o cargo de um usuário já existente (o perfil legado é
    atualizado junto, a partir do perfil_base do novo cargo)."""
    from core.cargos import cargo_por_id
    db = _get_db()
    cargo = cargo_por_id(cargo_id, db=db)
    if not cargo:
        raise ValueError("Cargo inválido.")
    if not db.buscar_um("usuarios", onde={"id": usuario_id}):
        raise ValueError("Usuário não encontrado.")
    db.atualizar("usuarios", {"cargo_id": cargo_id, "perfil": cargo["perfil_base"]}, onde={"id": usuario_id})
    return db.buscar_um("usuarios", onde={"id": usuario_id})

def desativar_usuario(usuario_id: int) -> bool:
    """Desativa um usuário pelo ID. Retorna True se bem-sucedido."""
    db = _get_db()
    qtd = db.atualizar("usuarios", {"ativo": False}, onde={"id": usuario_id})
    return qtd > 0

def reativar_usuario(usuario_id: int) -> bool:
    """Reativa um usuário previamente desativado. Retorna True se bem-sucedido."""
    db = _get_db()
    qtd = db.atualizar("usuarios", {"ativo": True}, onde={"id": usuario_id})
    return qtd > 0

def redefinir_senha(usuario_id: int, nova_senha: str) -> None:
    """
    Redefine a senha de um usuário existente.
    Lança ValueError se a nova senha for muito curta ou já estiver em uso por outro usuário.

    Checagem de colisão e atualização são atômicas (mesma correção de
    corrida aplicada em criar_usuario — ver o comentário lá).
    """
    if not nova_senha or len(nova_senha) < 6:
        raise ValueError("A senha deve ter no mínimo 6 caracteres.")

    db = _get_db()
    alvo = db.buscar_um("usuarios", onde={"id": usuario_id})
    if not alvo:
        raise ValueError("Usuário não encontrado.")

    def _recusar_se_senha_duplicada(registros_existentes):
        for u in registros_existentes:
            if u["id"] != usuario_id and verificar_senha(nova_senha, u.get("senha_hash", "")):
                raise ValueError("Esta senha já está em uso por outro usuário.")

    db.atualizar_com_validacao(
        "usuarios",
        {"senha_hash": _hash_senha(nova_senha)},
        onde={"id": usuario_id},
        validador=_recusar_se_senha_duplicada,
    )

def listar_usuarios() -> list[dict]:
    """Retorna todos os usuários (sem expor o hash da senha), com o
    nome do cargo efetivo de cada um já resolvido."""
    from core.cargos import resolver_efetivo
    db = _get_db()
    usuarios = db.buscar("usuarios", ordenar_por="perfil")
    resultado = []
    for u in usuarios:
        cargo = resolver_efetivo(u, db=db)
        item = {k: v for k, v in u.items() if k != "senha_hash"}
        item["cargo_id"] = cargo["cargo_id"]
        item["cargo_nome"] = cargo["cargo_nome"]
        resultado.append(item)
    return resultado


# --------------------------------------------------------------------
# Recuperação de acesso de administrador
#
# Substitui o antigo corrigir_admin.py (script solto, senha fixa e
# previsível "Admin@2026", sem registro de que foi usado). Este fluxo:
#   - só pode ser iniciado por quem já está logado na própria máquina do
#     servidor (a rota que chama isto em app.py é restrita a 127.0.0.1 —
#     nunca acessível pela rede da escola);
#   - gera um token de uso único, aleatório, que expira em 15 minutos;
#   - grava o token APENAS no arquivo de log do servidor (não na tela,
#     não em nenhuma resposta HTTP) — quem tem acesso ao log já tem
#     acesso equivalente ao servidor, então isso não abre uma porta nova;
#   - fica registrado no log quando foi gerado e quando foi usado, o que
#     o script antigo nunca fazia.
# --------------------------------------------------------------------

import secrets as _secrets
import time as _time

_RECUPERACAO_VALIDADE_SEGUNDOS = 15 * 60
_recuperacao_estado: dict | None = None  # {"token": str, "expira_em": float}


def gerar_token_recuperacao_admin() -> str:
    """
    Gera (ou renova) um token de recuperação de acesso de administrador,
    válido por 15 minutos. Retorna o token para ser registrado em log —
    quem chama esta função é responsável por logá-lo, nunca por
    devolvê-lo numa resposta HTTP.
    """
    global _recuperacao_estado
    token = _secrets.token_urlsafe(24)
    _recuperacao_estado = {"token": token, "expira_em": _time.time() + _RECUPERACAO_VALIDADE_SEGUNDOS}
    return token


def redefinir_senha_admin_via_token(token: str, nova_senha: str) -> None:
    """
    Usa um token gerado por `gerar_token_recuperacao_admin` para definir
    uma nova senha para TODOS os usuários de perfil 'admin' (mesmo
    comportamento do corrigir_admin.py original — não escolhe um admin
    específico, porque numa recuperação de emergência não se pode supor
    que quem está operando sabe distinguir qual conta é qual).

    Levanta ValueError se o token for inválido, já tiver expirado, ou já
    tiver sido usado (o token é de uso único: é apagado do estado assim
    que usado com sucesso, mesmo que a troca de senha falhe depois por
    outro motivo).
    """
    global _recuperacao_estado

    if not _recuperacao_estado:
        raise ValueError("Nenhuma recuperação de acesso foi solicitada.")
    if _time.time() > _recuperacao_estado["expira_em"]:
        _recuperacao_estado = None
        raise ValueError("O token de recuperação expirou. Solicite um novo.")
    if not _secrets.compare_digest(token, _recuperacao_estado["token"]):
        raise ValueError("Token de recuperação inválido.")

    # Token consumido — mesmo que a validação de senha abaixo falhe, quem
    # quiser tentar de novo precisa solicitar um novo token.
    _recuperacao_estado = None

    if not nova_senha or len(nova_senha) < 6:
        raise ValueError("A senha deve ter no mínimo 6 caracteres.")

    db = _get_db()
    admins = [u for u in db.buscar("usuarios") if u.get("perfil") == "admin"]
    if not admins:
        raise ValueError("Nenhum administrador encontrado no sistema.")

    for u in db.buscar("usuarios"):
        if u["perfil"] != "admin" and verificar_senha(nova_senha, u.get("senha_hash", "")):
            raise ValueError("Esta senha já está em uso por outro usuário.")

    novo_hash = _hash_senha(nova_senha)
    for admin in admins:
        db.atualizar("usuarios", {"senha_hash": novo_hash, "ativo": True}, onde={"id": admin["id"]})

