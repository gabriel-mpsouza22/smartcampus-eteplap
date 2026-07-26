
import json
import requests as req
from pathlib import Path
from flask import Blueprint, render_template, jsonify, request
from core.auth import login_obrigatorio, perfil_obrigatorio

blueprint = Blueprint("sinal", __name__, template_folder="../../templates/sinal")

BASE_SINAL   = Path(__file__).resolve().parent
SINAL_URL    = "http://127.0.0.1:5001"
TIMEOUT      = 4


def _proxy(metodo: str, rota: str, **kwargs):
    """
    Faz uma requisição HTTP para o sinal.pyw.
    Retorna (dict_resposta, status_code).
    Em caso de falha de conexão, retorna erro estruturado.
    """
    url = f"{SINAL_URL}{rota}"
    try:
        resp = getattr(req, metodo)(url, timeout=TIMEOUT, **kwargs)
        return resp.json(), resp.status_code
    except req.exceptions.ConnectionError:
        return {"ok": False, "erro": "App de sinal não está rodando. Inicie o sinal.pyw."}, 503
    except req.exceptions.Timeout:
        return {"ok": False, "erro": "App de sinal demorou para responder."}, 504
    except Exception as e:
        return {"ok": False, "erro": str(e)}, 500

def _carregar_grupos() -> list:
    """Carrega lista de grupos WhatsApp configurados."""
    path = BASE_SINAL / "whatsapp_grupos.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def _carregar_motivos() -> dict:
    """Carrega dicionário de motivos de saída antecipada."""
    path = BASE_SINAL / "whatsapp_grupos.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("motivos", {})


@blueprint.route("/painel")
@perfil_obrigatorio("coordenadora", "admin")
def painel():
    """Renderiza o painel de controle do sinal."""
    cfg_wp   = _carregar_grupos()
    grupos   = cfg_wp.get("grupos", [])
    motivos  = cfg_wp.get("motivos", {})

    status_dados, codigo = _proxy("get", "/status")
    status_inicial = status_dados if codigo == 200 else None

    return render_template(
        "sinal/painel.html",
        status=status_inicial,
        grupos=grupos,
        motivos=motivos,
    )


@blueprint.route("/api/status")
@login_obrigatorio
def api_status():
    """Retorna o status atual do sinal (proxy para sinal.pyw)."""
    dados, codigo = _proxy("get", "/status")
    return jsonify(dados), codigo


@blueprint.route("/api/tocar", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_tocar():
    """Toca o sinal manualmente."""
    dados, codigo = _proxy("post", "/tocar")
    return jsonify(dados), codigo


@blueprint.route("/api/cancelar/<hid>", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_cancelar(hid: str):
    """Cancela um horário futuro pelo ID."""
    dados, codigo = _proxy("post", f"/cancelar/{hid}")
    return jsonify(dados), codigo


@blueprint.route("/api/restaurar/<hid>", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_restaurar(hid: str):
    """Restaura um horário cancelado."""
    dados, codigo = _proxy("post", f"/restaurar/{hid}")
    return jsonify(dados), codigo


@blueprint.route("/api/lista", methods=["PUT"])
@perfil_obrigatorio("coordenadora", "admin")
def api_lista():
    """Troca a lista de horários ativa."""
    corpo = request.get_json(force=True)
    nova  = corpo.get("lista", "")
    if nova not in ("padrao", "sabado", "prova"):
        return jsonify({"ok": False, "erro": "Lista inválida."}), 400
    dados, codigo = _proxy("put", "/lista", json={"lista": nova})
    return jsonify(dados), codigo


@blueprint.route("/api/whatsapp", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_whatsapp():
    """Envia mensagem de saída antecipada via WhatsApp."""
    corpo = request.get_json(force=True)
    dados, codigo = _proxy("post", "/whatsapp", json=corpo)
    return jsonify(dados), codigo
