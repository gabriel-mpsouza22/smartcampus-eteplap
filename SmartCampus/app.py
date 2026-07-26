
import json
import secrets
import logging
from pathlib import Path
from datetime import timedelta

from flask import Flask, render_template, request, redirect, url_for, jsonify, session


BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "core" / "config.json"

def carregar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


app = Flask(
    __name__,
    template_folder=str(BASE / "templates"),
    static_folder=str(BASE / "static"),
)


config = carregar_config()

chave_secreta_path = BASE / "core" / ".secret_key"
if chave_secreta_path.exists():
    app.secret_key = chave_secreta_path.read_bytes()
else:
    chave = secrets.token_bytes(32)
    chave_secreta_path.write_bytes(chave)
    app.secret_key = chave

app.permanent_session_lifetime = timedelta(hours=8)


log_path = BASE / "logs" / "servidor.log"
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
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
    modulos_do_perfil,
    login_obrigatorio,
)
from core.router import registrar_blueprints, perfil_para_cor, perfil_para_label


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
            "modulos":     modulos_do_perfil(usuario["perfil"]),
            "cor_perfil":  perfil_para_cor(usuario["perfil"]),
            "label_perfil":perfil_para_label(usuario["perfil"]),
        }
    return {
        **identidade,
        "usuario":     None,
        "modulos":     [],
        "cor_perfil":  "#4A4A4A",
        "label_perfil":"",
    }


@app.route("/")
def raiz():
    """Redireciona para o dashboard se logado, senão para o login."""
    if usuario_logado():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Tela e processamento de login por senha única."""
    if usuario_logado():
        return redirect(url_for("dashboard"))

    if request.method == "GET":
        return render_template("login.html", erro=None)

    senha = request.form.get("senha", "").strip()

    if not senha:
        return render_template("login.html", erro="Informe sua senha.")

    usuario = autenticar(senha)

    if not usuario:
        app.logger.warning(f"[Auth] Tentativa de login falhou — IP: {request.remote_addr}")
        return render_template("login.html", erro="Senha incorreta. Tente novamente.")

    criar_sessao(usuario)
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
        app.logger.info(f"[Auth] Logout — {usuario['nome']} ({usuario['perfil']})")
    destruir_sessao()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_obrigatorio
def dashboard():
    """Painel principal com os módulos do perfil logado."""
    return render_template("dashboard.html")



@app.route("/api/status")
def status():
    """Endpoint de health-check do servidor."""
    return jsonify({
        "status":  "ok",
        "sistema": "Smart Campus ETEPLAP",
        "versao":  config.get("versao", "1.0.0"),
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


if __name__ == "__main__":
    host  = config.get("host_api", "0.0.0.0")
    porta = int(config.get("porta_api", 5000))

    print(f"""
╔══════════════════════════════════════════════════════╗
║      Smart Campus ETEPLAP — Servidor iniciando       ║
╠══════════════════════════════════════════════════════╣
║  Endereço local : http://localhost:{porta:<20}║
║  Rede escolar   : http://[IP-deste-PC]:{porta:<17}║
║  Para encerrar  : Ctrl+C                             ║
╚══════════════════════════════════════════════════════╝
""")

    app.run(
        host=host,
        port=porta,
        debug=False,
        threaded=True,
    )
