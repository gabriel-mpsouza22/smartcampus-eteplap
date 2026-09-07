
import json
import requests as req
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, jsonify, request
from core.auth import login_obrigatorio, perfil_obrigatorio

blueprint = Blueprint("sinal", __name__, template_folder="../../templates/sinal")

BASE_SINAL     = Path(__file__).resolve().parent
BASE_PROJETO   = BASE_SINAL.parent.parent
CONFIG_PATH    = BASE_PROJETO / "core" / "config.json"
PASTA_SONS     = BASE_SINAL / "sons"
TIMEOUT        = 4
EXTENSOES_PERMITIDAS = {".wav"}
TAMANHO_MAXIMO_MB     = 8


def _cfg() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _modo_sinal() -> str:
    """'local' (mesma máquina, thread interna) ou 'remoto' (PC dedicado ao som)."""
    return _cfg().get("sinal_modo", "local")


def _url_sinal() -> str:
    return _cfg().get("sinal_url", "http://127.0.0.1:5001")


# --------------------------------------------------------------------
# No modo local, o motor do sinal roda como thread deste mesmo
# processo (sem rede). No modo remoto, ele roda num PC separado e é
# acessado via HTTP (sinal.pyw). As funções abaixo abstraem essa
# diferença para o resto do arquivo: sempre devolvem (dict, codigo_http).
# --------------------------------------------------------------------

def _motor():
    """Importa motor.py (lazy, só quando modo local é usado)."""
    from modulos.sinal import motor
    motor.iniciar_scheduler()
    return motor


def _proxy(metodo: str, rota: str, **kwargs):
    """Faz uma requisição HTTP para o sinal.pyw remoto."""
    url = f"{_url_sinal()}{rota}"
    try:
        resp = getattr(req, metodo)(url, timeout=TIMEOUT, **kwargs)
        return resp.json(), resp.status_code
    except req.exceptions.ConnectionError:
        return {"ok": False, "erro": "App de sinal não está rodando. Inicie o sinal.pyw no PC do som."}, 503
    except req.exceptions.Timeout:
        return {"ok": False, "erro": "App de sinal demorou para responder."}, 504
    except Exception as e:
        return {"ok": False, "erro": str(e)}, 500


def _status():
    if _modo_sinal() == "local":
        return _motor().obter_status(), 200
    return _proxy("get", "/status")


def _tocar():
    if _modo_sinal() == "local":
        _motor().tocar_sinal()
        return {"ok": True, "mensagem": "Sinal tocado manualmente."}, 200
    return _proxy("post", "/tocar")


def _cancelar(hid: str):
    if _modo_sinal() == "local":
        try:
            _motor().cancelar_horario(hid)
            return {"ok": True, "mensagem": f"Horário {hid} cancelado."}, 200
        except ValueError as e:
            return {"ok": False, "erro": str(e)}, 400
    return _proxy("post", f"/cancelar/{hid}")


def _restaurar(hid: str):
    if _modo_sinal() == "local":
        _motor().restaurar_horario(hid)
        return {"ok": True, "mensagem": f"Horário {hid} restaurado."}, 200
    return _proxy("post", f"/restaurar/{hid}")


def _trocar_lista(nova: str):
    if _modo_sinal() == "local":
        try:
            _motor().trocar_lista(nova)
            return {"ok": True, "lista": nova}, 200
        except ValueError as e:
            return {"ok": False, "erro": str(e)}, 400
    return _proxy("put", "/lista", json={"lista": nova})


def _sons():
    if _modo_sinal() == "local":
        motor = _motor()
        return {
            "sons":      motor.sons_disponiveis(),
            "som_ativo": motor._config_som().get("som_ativo", motor.SOM_PADRAO),
        }, 200
    return _proxy("get", "/sons")


def _sons_ativo(arquivo: str):
    if _modo_sinal() == "local":
        try:
            resultado = _motor().definir_som_ativo(arquivo)
            return {"ok": True, **resultado}, 200
        except FileNotFoundError as e:
            return {"ok": False, "erro": str(e)}, 404
        except ValueError as e:
            return {"ok": False, "erro": str(e)}, 400
    return _proxy("put", "/sons/ativo", json={"arquivo": arquivo})


def _sons_testar(arquivo: str):
    if _modo_sinal() == "local":
        try:
            nome = _motor().testar_som(arquivo)
            return {"ok": True, "mensagem": f"Tocando teste: {nome}"}, 200
        except FileNotFoundError as e:
            return {"ok": False, "erro": str(e)}, 404
        except ValueError as e:
            return {"ok": False, "erro": str(e)}, 400
    return _proxy("post", f"/sons/testar/{arquivo}")


def _whatsapp(corpo: dict):
    if _modo_sinal() == "local":
        try:
            resultado = _motor().enviar_whatsapp(
                corpo.get("turmas", []),
                corpo.get("horario_saida", ""),
                corpo.get("motivo", ""),
                nome_escola=_cfg().get("sigla_escola", "Smart Campus"),
            )
            return {"ok": len(resultado["enviados"]) > 0, **resultado}, 200
        except ValueError as e:
            return {"ok": False, "erro": str(e)}, 400
    return _proxy("post", "/whatsapp", json=corpo)


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

    status_dados, codigo = _status()
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
    dados, codigo = _status()
    return jsonify(dados), codigo


@blueprint.route("/api/tocar", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_tocar():
    dados, codigo = _tocar()
    return jsonify(dados), codigo


@blueprint.route("/api/cancelar/<hid>", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_cancelar(hid: str):
    dados, codigo = _cancelar(hid)
    return jsonify(dados), codigo


@blueprint.route("/api/restaurar/<hid>", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_restaurar(hid: str):
    dados, codigo = _restaurar(hid)
    return jsonify(dados), codigo


@blueprint.route("/api/lista", methods=["PUT"])
@perfil_obrigatorio("coordenadora", "admin")
def api_lista():
    corpo = request.get_json(force=True)
    nova  = corpo.get("lista", "")
    if nova not in ("padrao", "sabado", "prova"):
        return jsonify({"ok": False, "erro": "Lista inválida."}), 400
    dados, codigo = _trocar_lista(nova)
    return jsonify(dados), codigo


@blueprint.route("/api/whatsapp", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_whatsapp():
    corpo = request.get_json(force=True)
    dados, codigo = _whatsapp(corpo)
    return jsonify(dados), codigo


@blueprint.route("/api/sons")
@login_obrigatorio
def api_sons():
    """Lista os sons disponíveis e qual está selecionado."""
    dados, codigo = _sons()
    return jsonify(dados), codigo


@blueprint.route("/api/sons/ativo", methods=["PUT"])
@perfil_obrigatorio("coordenadora", "admin")
def api_sons_ativo():
    """Define qual som cadastrado será usado ao tocar o sinal."""
    corpo = request.get_json(force=True)
    dados, codigo = _sons_ativo(corpo.get("arquivo", ""))
    return jsonify(dados), codigo


@blueprint.route("/api/sons/testar/<arquivo>", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_sons_testar(arquivo):
    """Toca um som específico para o usuário ouvir antes de escolher."""
    dados, codigo = _sons_testar(arquivo)
    return jsonify(dados), codigo


@blueprint.route("/api/sons/upload", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_sons_upload():
    """
    Recebe um novo arquivo de som (.wav) e salva na pasta de sons do
    sinal. Isso é feito sempre localmente pelo servidor principal
    (não importa o sinal_modo) — no modo remoto, a pasta de sons deve
    estar em um caminho compartilhado/sincronizado com o PC do som
    (ver manual técnico); no modo local ela já é a mesma pasta usada
    pelo motor do sinal.
    """
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400

    nome = secure_filename(arquivo.filename)
    extensao = Path(nome).suffix.lower()
    if extensao not in EXTENSOES_PERMITIDAS:
        return jsonify({"ok": False, "erro": "Apenas arquivos .wav são aceitos."}), 400

    arquivo.seek(0, 2)
    tamanho_mb = arquivo.tell() / (1024 * 1024)
    arquivo.seek(0)
    if tamanho_mb > TAMANHO_MAXIMO_MB:
        return jsonify({"ok": False, "erro": f"Arquivo muito grande (máx. {TAMANHO_MAXIMO_MB} MB)."}), 400

    if not nome:
        return jsonify({"ok": False, "erro": "Nome de arquivo inválido."}), 400

    PASTA_SONS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_SONS / nome

    contador = 1
    base_nome = destino.stem
    while destino.exists():
        destino = PASTA_SONS / f"{base_nome}_{contador}{extensao}"
        contador += 1

    arquivo.save(destino)

    return jsonify({"ok": True, "arquivo": destino.name}), 201


@blueprint.route("/api/sons/<arquivo>", methods=["DELETE"])
@perfil_obrigatorio("coordenadora", "admin")
def api_sons_remover(arquivo):
    """Remove um som cadastrado (o som padrão sinal.wav não pode ser removido)."""
    nome = secure_filename(arquivo)
    if not nome or nome == "sinal.wav":
        return jsonify({"ok": False, "erro": "Este som não pode ser removido."}), 400

    caminho = PASTA_SONS / nome
    if not caminho.exists():
        return jsonify({"ok": False, "erro": "Arquivo não encontrado."}), 404

    caminho.unlink()
    return jsonify({"ok": True})
