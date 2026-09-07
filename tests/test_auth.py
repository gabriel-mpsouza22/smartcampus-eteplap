"""
Testes de core/auth.py.

Foco: os pontos que a auditoria classificou como ALTA/CRÍTICA — hashing
de senha, revogação de sessão ao desativar usuário, e o fluxo de
recuperação de acesso do admin (token de uso único, expiração).
"""
import time

import pytest


@pytest.fixture
def db_usuarios(pasta_tmp):
    from sceds import SCEDS
    db = SCEDS(pasta_tmp / "dados")
    db.criar_tabela("usuarios", [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome", "tipo": "TEXTO"},
        {"nome": "perfil", "tipo": "TEXTO"},
        {"nome": "senha_hash", "tipo": "TEXTO"},
        {"nome": "ativo", "tipo": "BOOLEANO"},
    ])
    return db


@pytest.fixture
def auth_isolado(db_usuarios, monkeypatch):
    """core.auth com _get_db substituído por um SCEDS isolado em tmp_path."""
    import core.auth as auth
    monkeypatch.setattr(auth, "_get_db", lambda: db_usuarios)
    return auth


def test_hash_e_verificacao_de_senha(auth_isolado):
    h = auth_isolado._hash_senha("MinhaSenha123")
    assert auth_isolado.verificar_senha("MinhaSenha123", h)
    assert not auth_isolado.verificar_senha("SenhaErrada", h)


def test_login_atualiza_hash_sha256_para_bcrypt_automaticamente(auth_isolado, db_usuarios, monkeypatch):
    """
    Um usuário cujo hash foi gerado em SHA-256 (porque bcrypt não estava
    disponível na hora de criar a conta) deve, ao logar com sucesso
    depois que bcrypt já está disponível, ter seu hash silenciosamente
    atualizado para bcrypt — sem exigir nenhuma ação do usuário.
    """
    import hashlib
    import os as _os

    # Simula um usuário criado quando bcrypt não estava disponível.
    salt = _os.urandom(16).hex()
    senha = "SenhaAntiga123"
    hash_sha256 = f"sha256:{salt}:{hashlib.sha256(f'{salt}{senha}'.encode()).hexdigest()}"
    registro = db_usuarios.inserir("usuarios", {
        "nome": "Ana", "perfil": "admin", "senha_hash": hash_sha256, "ativo": True,
    })
    assert registro["senha_hash"].startswith("sha256:")

    # bcrypt está disponível agora (é uma dependência do projeto) —
    # login bem-sucedido deve disparar o upgrade.
    usuario = auth_isolado.autenticar(senha)
    assert usuario is not None

    atualizado = db_usuarios.buscar_um("usuarios", onde={"id": registro["id"]})
    assert not atualizado["senha_hash"].startswith("sha256:")
    # a senha original continua validando normalmente com o hash novo
    assert auth_isolado.verificar_senha(senha, atualizado["senha_hash"])


def test_criar_usuario_recusa_senha_duplicada(auth_isolado):
    auth_isolado.criar_usuario("Ana", "admin", "SenhaUnica123")
    with pytest.raises(ValueError):
        auth_isolado.criar_usuario("Bruno", "professor", "SenhaUnica123")


def test_desativar_usuario_revoga_acesso(auth_isolado, db_usuarios):
    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "teste"

    registro = auth_isolado.criar_usuario("Ana", "admin", "SenhaUnica123")

    with app.test_request_context():
        from flask import session
        session["usuario_id"] = registro["id"]

        # antes de desativar: usuario_logado() deve retornar o usuário
        assert auth_isolado.usuario_logado() is not None

        auth_isolado.desativar_usuario(registro["id"])

        # depois de desativar: a MESMA sessão (cookie já emitido) deve
        # parar de valer na próxima checagem — essa é a garantia que
        # faltava antes da correção (achado ALTA da auditoria).
        assert auth_isolado.usuario_logado() is None


def test_token_recuperacao_admin_uso_unico(auth_isolado, db_usuarios):
    auth_isolado.criar_usuario("Admin", "admin", "SenhaAntiga123")

    token = auth_isolado.gerar_token_recuperacao_admin()

    # token errado não deve funcionar nem consumir o estado
    with pytest.raises(ValueError):
        auth_isolado.redefinir_senha_admin_via_token("token-invalido", "SenhaNova123")

    # token certo funciona
    auth_isolado.redefinir_senha_admin_via_token(token, "SenhaNova123")

    admin = db_usuarios.buscar_um("usuarios", onde={"perfil": "admin"})
    assert auth_isolado.verificar_senha("SenhaNova123", admin["senha_hash"])

    # reuso do mesmo token deve falhar
    with pytest.raises(ValueError):
        auth_isolado.redefinir_senha_admin_via_token(token, "OutraSenha123")


def test_token_recuperacao_expira(auth_isolado, monkeypatch):
    auth_isolado.criar_usuario("Admin", "admin", "SenhaAntiga123")
    token = auth_isolado.gerar_token_recuperacao_admin()

    # avança o relógio interno do módulo além da validade (15 min) —
    # captura o valor real ANTES de aplicar o patch, para não referenciar
    # a própria função já substituída dentro da lambda.
    tempo_futuro = time.time() + auth_isolado._RECUPERACAO_VALIDADE_SEGUNDOS + 1
    monkeypatch.setattr(auth_isolado._time, "time", lambda: tempo_futuro)

    with pytest.raises(ValueError):
        auth_isolado.redefinir_senha_admin_via_token(token, "SenhaNova123")
