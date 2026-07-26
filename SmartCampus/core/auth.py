
import json
import hashlib
import functools
from pathlib import Path
from datetime import datetime
from flask import session, redirect, url_for, request, jsonify


_CONFIG_PATH = Path(__file__).parent / "config.json"

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
    return SCEDS(base / "sceds" / "data")


MODULOS_POR_PERFIL: dict[str, list[dict]] = {
    "professor": [
        {"id": "agendamento", "nome": "Agendamento de Recursos",
         "icone": "📅", "url": "/agendamento/", "cor": "#2E86AB"},
    ],
    "portaria": [
        {"id": "portaria",    "nome": "Painel da Portaria",
         "icone": "🚪", "url": "/portaria/",    "cor": "#E76F51"},
        {"id": "iot",         "nome": "Monitoramento IoT",
         "icone": "📡", "url": "/iot/painel",   "cor": "#2A9D8F"},
    ],
    "bibliotecaria": [
        {"id": "biblioteca",  "nome": "Biblioteca",
         "icone": "📚", "url": "/biblioteca/",  "cor": "#8338EC"},
    ],
    "coordenadora": [
        {"id": "sinal",       "nome": "Controle do Sinal",
         "icone": "🔔", "url": "/sinal/painel", "cor": "#F4A261"},
        {"id": "ocorrencias", "nome": "Ocorrências",
         "icone": "📋", "url": "/ocorrencias/", "cor": "#E63946"},
        {"id": "monitoramento","nome": "Monitoramento",
         "icone": "📊", "url": "/monitoramento/","cor": "#6A4C93"},
    ],
    "secretaria": [
        {"id": "secretaria",  "nome": "Painel da Secretaria",
         "icone": "🏢", "url": "/secretaria/",  "cor": "#457B9D"},
        {"id": "agendamento", "nome": "Agendamento de Recursos",
         "icone": "📅", "url": "/agendamento/", "cor": "#2E86AB"},
    ],
    "admin": [
        {"id": "agendamento", "nome": "Agendamento de Recursos",
         "icone": "📅", "url": "/agendamento/", "cor": "#2E86AB"},
        {"id": "biblioteca",  "nome": "Biblioteca",
         "icone": "📚", "url": "/biblioteca/",  "cor": "#8338EC"},
        {"id": "sinal",       "nome": "Controle do Sinal",
         "icone": "🔔", "url": "/sinal/painel", "cor": "#F4A261"},
        {"id": "portaria",    "nome": "Painel da Portaria",
         "icone": "🚪", "url": "/portaria/",    "cor": "#E76F51"},
        {"id": "secretaria",  "nome": "Painel da Secretaria",
         "icone": "🏢", "url": "/secretaria/",  "cor": "#457B9D"},
        {"id": "iot",         "nome": "Monitoramento IoT",
         "icone": "📡", "url": "/iot/painel",   "cor": "#2A9D8F"},
        {"id": "ocorrencias", "nome": "Ocorrências",
         "icone": "📋", "url": "/ocorrencias/", "cor": "#E63946"},
        {"id": "monitoramento","nome": "Gráficos e Análise",
         "icone": "📊", "url": "/monitoramento/","cor": "#6A4C93"},
        {"id": "admin",       "nome": "Administração",
         "icone": "⚙️",  "url": "/admin/",       "cor": "#1A1A2E"},
    ],
}


def _verificar_bcrypt(senha: str, hash_armazenado: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(senha.encode("utf-8"), hash_armazenado.encode("utf-8"))
    except Exception:
        return False

def _verificar_sha256(senha: str, hash_armazenado: str) -> bool:
    """Fallback para hashes SHA-256 gerados durante instalação sem bcrypt."""
    try:
        _, salt, h = hash_armazenado.split(":")
        return hashlib.sha256(f"{salt}{senha}".encode()).hexdigest() == h
    except Exception:
        return False

def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    if hash_armazenado.startswith("sha256:"):
        return _verificar_sha256(senha, hash_armazenado)
    return _verificar_bcrypt(senha, hash_armazenado)


def autenticar(senha_digitada: str) -> dict | None:
    """
    Itera sobre todos os usuários ativos e compara a senha via bcrypt.
    Retorna dict com 'id', 'nome', 'perfil' se autenticado, ou None.
    """
    if not senha_digitada or len(senha_digitada.strip()) < 4:
        return None

    db = _get_db()
    usuarios = db.buscar("usuarios", onde={"ativo": True})

    for usuario in usuarios:
        if verificar_senha(senha_digitada, usuario.get("senha_hash", "")):
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
    """
    if "usuario_id" not in session:
        return None
    return {
        "id":     session["usuario_id"],
        "nome":   session["usuario_nome"],
        "perfil": session["usuario_perfil"],
    }

def modulos_do_perfil(perfil: str) -> list[dict]:
    """Retorna a lista de módulos disponíveis para o perfil dado."""
    return MODULOS_POR_PERFIL.get(perfil, [])


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
    já que nem todo Python tem wheel de bcrypt disponível (ex: 3.14 recente).
    """
    try:
        import bcrypt
        return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    except ImportError:
        import os as _os, hashlib as _hashlib
        salt = _os.urandom(16).hex()
        h = _hashlib.sha256(f"{salt}{senha}".encode()).hexdigest()
        return f"sha256:{salt}:{h}"

def criar_usuario(nome: str, perfil: str, senha: str) -> dict:
    """
    Cria um novo usuário no SCEDS.
    Lança ValueError se a senha já existir no sistema (colisão proibida).
    """
    if not nome or not perfil or not senha:
        raise ValueError("Nome, perfil e senha são obrigatórios.")
    if perfil not in MODULOS_POR_PERFIL:
        raise ValueError(f"Perfil inválido: '{perfil}'.")
    if len(senha) < 6:
        raise ValueError("A senha deve ter no mínimo 6 caracteres.")

    db = _get_db()

    todos = db.buscar("usuarios")
    for u in todos:
        if verificar_senha(senha, u.get("senha_hash", "")):
            raise ValueError("Esta senha já está em uso por outro usuário.")

    registro = db.inserir("usuarios", {
        "nome":       nome,
        "perfil":     perfil,
        "senha_hash": _hash_senha(senha),
        "ativo":      True,
        "criado_em":  datetime.now().isoformat(),
    })
    return registro

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
    """
    if not nova_senha or len(nova_senha) < 6:
        raise ValueError("A senha deve ter no mínimo 6 caracteres.")

    db = _get_db()
    alvo = db.buscar_um("usuarios", onde={"id": usuario_id})
    if not alvo:
        raise ValueError("Usuário não encontrado.")

    for u in db.buscar("usuarios"):
        if u["id"] != usuario_id and verificar_senha(nova_senha, u.get("senha_hash", "")):
            raise ValueError("Esta senha já está em uso por outro usuário.")

    db.atualizar("usuarios", {"senha_hash": _hash_senha(nova_senha)}, onde={"id": usuario_id})

def listar_usuarios() -> list[dict]:
    """Retorna todos os usuários (sem expor o hash da senha)."""
    db = _get_db()
    usuarios = db.buscar("usuarios", ordenar_por="perfil")
    return [
        {k: v for k, v in u.items() if k != "senha_hash"}
        for u in usuarios
    ]

