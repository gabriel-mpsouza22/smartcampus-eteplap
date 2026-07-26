
import json
import threading
import logging
from pathlib import Path
from datetime import datetime, date, time as dtime
from flask import Blueprint, render_template, jsonify, request
from core.auth import perfil_obrigatorio, login_obrigatorio

blueprint = Blueprint("iot", __name__, template_folder="../../templates/iot")

BASE = Path(__file__).resolve().parent
ESTADO_PORTOES_PATH = BASE / "estado_portoes.json"
ESTADO_AC_PATH       = BASE / "estado_ac.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [IOT] %(message)s")


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    cfg = json.load(open(BASE.parent.parent / "core" / "config.json", encoding="utf-8"))
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

def _carregar_config() -> dict:
    with open(BASE / "dispositivos.json", encoding="utf-8") as f:
        return json.load(f)

def _sensor_agua_por_id(sid: str) -> dict | None:
    cfg = _carregar_config()
    return next((s for s in cfg["agua"]["sensores"] if s["id"] == sid), None)

def _portao_por_id(pid: str) -> dict | None:
    cfg = _carregar_config()
    return next((p for p in cfg["portoes"]["lista"] if p["id"] == pid), None)

def _checar_token(token_recebido: str, token_esperado: str) -> bool:
    return bool(token_recebido) and token_recebido == token_esperado


def _estado_portoes_inicial() -> dict:
    cfg = _carregar_config()
    portoes = {}
    for p in cfg["portoes"]["lista"]:
        portoes[p["id"]] = {
            "estado_atual":    "fechado",
            "estado_desejado": "fechado",
            "atualizado_em":   None,
        }
    return {
        "portoes": portoes,
        "ultima_automacao_abertura":  None,
        "ultima_automacao_fechamento": None,
    }

def _carregar_estado_portoes() -> dict:
    if ESTADO_PORTOES_PATH.exists():
        try:
            with open(ESTADO_PORTOES_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    estado = _estado_portoes_inicial()
    _salvar_estado_portoes(estado)
    return estado

def _salvar_estado_portoes(estado: dict) -> None:
    with open(ESTADO_PORTOES_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)

_lock_portoes = threading.Lock()


def _estado_ac_inicial() -> dict:
    return {
        "estado_atual":    "desligado",
        "estado_desejado": "desligado",
        "atualizado_em":   None,
        "ultima_automacao_data": None,
    }

def _carregar_estado_ac() -> dict:
    if ESTADO_AC_PATH.exists():
        try:
            with open(ESTADO_AC_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    estado = _estado_ac_inicial()
    _salvar_estado_ac(estado)
    return estado

def _salvar_estado_ac(estado: dict) -> None:
    with open(ESTADO_AC_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)

_lock_ac = threading.Lock()


def _loop_automacoes():
    """
    Thread em segundo plano (roda dentro do processo do app.py).
    Verifica a cada 20s se é hora de disparar as automações programadas.
    """
    import time as _time
    logging.info("Scheduler de automações IoT iniciado.")

    while True:
        try:
            agora = datetime.now()
            hoje  = date.today().isoformat()
            hora_atual = agora.strftime("%H:%M")
            cfg = _carregar_config()

            with _lock_portoes:
                estado_p = _carregar_estado_portoes()
                if (hora_atual == cfg["portoes"]["horario_abertura"]
                        and estado_p.get("ultima_automacao_abertura") != hoje):
                    for pid in estado_p["portoes"]:
                        estado_p["portoes"][pid]["estado_desejado"] = "aberto"
                    estado_p["ultima_automacao_abertura"] = hoje
                    _salvar_estado_portoes(estado_p)
                    logging.info("Automação: portões programados para ABRIR.")

                if (hora_atual == cfg["portoes"]["horario_fechamento"]
                        and estado_p.get("ultima_automacao_fechamento") != hoje):
                    for pid in estado_p["portoes"]:
                        estado_p["portoes"][pid]["estado_desejado"] = "fechado"
                    estado_p["ultima_automacao_fechamento"] = hoje
                    _salvar_estado_portoes(estado_p)
                    logging.info("Automação: portões programados para FECHAR.")

            with _lock_ac:
                estado_a = _carregar_estado_ac()
                dia_semana = agora.weekday()
                if (hora_atual == cfg["ar_condicionado"]["horario_ligar"]
                        and dia_semana in cfg["ar_condicionado"]["dias_semana_automacao"]
                        and estado_a.get("ultima_automacao_data") != hoje):
                    estado_a["estado_desejado"] = "ligado"
                    estado_a["ultima_automacao_data"] = hoje
                    _salvar_estado_ac(estado_a)
                    logging.info("Automação: ar-condicionados programados para LIGAR.")

        except Exception as e:
            logging.error(f"Erro no scheduler de automações: {e}")

        _time.sleep(20)


if not hasattr(blueprint, "_scheduler_iniciado"):
    _thread_scheduler = threading.Thread(target=_loop_automacoes, daemon=True, name="iot-scheduler")
    _thread_scheduler.start()
    blueprint._scheduler_iniciado = True


@blueprint.route("/painel")
@perfil_obrigatorio("portaria", "admin")
def painel():
    cfg = _carregar_config()
    return render_template("iot/painel.html",
                           sensores_agua=cfg["agua"]["sensores"],
                           portoes=cfg["portoes"]["lista"])


@blueprint.route("/api/status")
@login_obrigatorio
def api_status():
    db  = _get_db()
    cfg = _carregar_config()

    agua = []
    for sensor in cfg["agua"]["sensores"]:
        leituras = db.buscar("leituras_iot", onde={"sensor_id": sensor["id"]}, ordenar_por="data_hora")
        ultima = leituras[-1] if leituras else None
        agua.append({
            "id":             sensor["id"],
            "nome":           sensor["nome"],
            "limite_minimo":  sensor["limite_minimo"],
            "nivel":          ultima["valor"] if ultima else None,
            "data_hora":      ultima["data_hora"] if ultima else None,
            "alerta":         (ultima is not None and ultima["valor"] < sensor["limite_minimo"]),
            "sem_sinal":      ultima is None,
        })

    estado_p = _carregar_estado_portoes()
    portoes = []
    for p in cfg["portoes"]["lista"]:
        info = estado_p["portoes"].get(p["id"], {})
        portoes.append({
            "id":              p["id"],
            "nome":            p["nome"],
            "estado_atual":    info.get("estado_atual", "desconhecido"),
            "estado_desejado": info.get("estado_desejado", "desconhecido"),
            "atualizado_em":   info.get("atualizado_em"),
        })

    estado_a = _carregar_estado_ac()

    return jsonify({
        "agua":            agua,
        "portoes":         portoes,
        "ar_condicionado": {
            "nome":            cfg["ar_condicionado"]["nome"],
            "quantidade":      cfg["ar_condicionado"]["quantidade"],
            "estado_atual":    estado_a.get("estado_atual"),
            "estado_desejado": estado_a.get("estado_desejado"),
            "atualizado_em":   estado_a.get("atualizado_em"),
        },
        "horarios": {
            "portao_abertura":   cfg["portoes"]["horario_abertura"],
            "portao_fechamento": cfg["portoes"]["horario_fechamento"],
            "ac_ligar":          cfg["ar_condicionado"]["horario_ligar"],
        },
    })


@blueprint.route("/agua/<sensor_id>", methods=["POST"])
def api_agua_leitura(sensor_id):
    """ESP32 envia o nível de água lido (0-100%). Header: X-Device-Token."""
    sensor = _sensor_agua_por_id(sensor_id)
    if not sensor:
        return jsonify({"ok": False, "erro": "Sensor de água desconhecido."}), 404

    token = request.headers.get("X-Device-Token", "")
    if not _checar_token(token, sensor["token"]):
        return jsonify({"ok": False, "erro": "Token inválido."}), 401

    dados = request.get_json(force=True, silent=True) or {}
    nivel = dados.get("nivel")
    if nivel is None:
        return jsonify({"ok": False, "erro": "Informe o campo 'nivel'."}), 400

    try:
        nivel = float(nivel)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "Nível inválido."}), 400

    db = _get_db()
    db.inserir("leituras_iot", {
        "sensor_id": sensor_id,
        "tipo":      "agua",
        "valor":     nivel,
        "data_hora": datetime.now().isoformat(),
    })

    alerta = nivel < sensor["limite_minimo"]
    if alerta:
        logging.warning(f"Alerta de nível baixo: {sensor['nome']} em {nivel}%")

    return jsonify({"ok": True, "alerta": alerta}), 201


@blueprint.route("/portao/<pid>/comando")
def api_portao_comando(pid):
    """ESP32 consulta periodicamente o estado desejado (polling)."""
    cfg = _carregar_config()
    if not _checar_token(request.headers.get("X-Device-Token", ""), cfg["portoes"]["token"]):
        return jsonify({"ok": False, "erro": "Token inválido."}), 401

    if not _portao_por_id(pid):
        return jsonify({"ok": False, "erro": "Portão desconhecido."}), 404

    with _lock_portoes:
        estado = _carregar_estado_portoes()
        info = estado["portoes"].get(pid, {})

    return jsonify({"ok": True, "estado_desejado": info.get("estado_desejado", "fechado")})

@blueprint.route("/portao/<pid>/status", methods=["POST"])
def api_portao_status(pid):
    """ESP32 informa o estado físico atual do portão, após executar a ação."""
    cfg = _carregar_config()
    if not _checar_token(request.headers.get("X-Device-Token", ""), cfg["portoes"]["token"]):
        return jsonify({"ok": False, "erro": "Token inválido."}), 401

    if not _portao_por_id(pid):
        return jsonify({"ok": False, "erro": "Portão desconhecido."}), 404

    dados = request.get_json(force=True, silent=True) or {}
    novo_estado = dados.get("estado", "").strip().lower()
    if novo_estado not in ("aberto", "fechado"):
        return jsonify({"ok": False, "erro": "Estado deve ser 'aberto' ou 'fechado'."}), 400

    with _lock_portoes:
        estado = _carregar_estado_portoes()
        estado["portoes"].setdefault(pid, {})
        estado["portoes"][pid]["estado_atual"]  = novo_estado
        estado["portoes"][pid]["atualizado_em"] = datetime.now().isoformat()
        _salvar_estado_portoes(estado)

    db = _get_db()
    db.inserir("leituras_iot", {
        "sensor_id": f"portao_{pid}", "tipo": "portao_status",
        "valor": 1.0 if novo_estado == "aberto" else 0.0,
        "data_hora": datetime.now().isoformat(),
    })
    return jsonify({"ok": True})

@blueprint.route("/portao/<pid>/abrir", methods=["POST"])
@perfil_obrigatorio("portaria", "admin")
def api_portao_abrir(pid):
    """Botão manual do painel web: define o estado desejado como 'aberto'."""
    if not _portao_por_id(pid):
        return jsonify({"ok": False, "erro": "Portão desconhecido."}), 404

    with _lock_portoes:
        estado = _carregar_estado_portoes()
        estado["portoes"].setdefault(pid, {})
        estado["portoes"][pid]["estado_desejado"] = "aberto"
        _salvar_estado_portoes(estado)

    return jsonify({"ok": True, "mensagem": "Comando de abertura enviado. Aguardando o portão confirmar."})

@blueprint.route("/portao/<pid>/fechar", methods=["POST"])
@perfil_obrigatorio("portaria", "admin")
def api_portao_fechar(pid):
    """Botão manual do painel web: define o estado desejado como 'fechado'."""
    if not _portao_por_id(pid):
        return jsonify({"ok": False, "erro": "Portão desconhecido."}), 404

    with _lock_portoes:
        estado = _carregar_estado_portoes()
        estado["portoes"].setdefault(pid, {})
        estado["portoes"][pid]["estado_desejado"] = "fechado"
        _salvar_estado_portoes(estado)

    return jsonify({"ok": True, "mensagem": "Comando de fechamento enviado."})


@blueprint.route("/ac/comando")
def api_ac_comando():
    """ESP32 (controlador IR) consulta periodicamente o estado desejado."""
    cfg = _carregar_config()
    if not _checar_token(request.headers.get("X-Device-Token", ""), cfg["ar_condicionado"]["token"]):
        return jsonify({"ok": False, "erro": "Token inválido."}), 401

    with _lock_ac:
        estado = _carregar_estado_ac()

    return jsonify({"ok": True, "estado_desejado": estado.get("estado_desejado", "desligado")})

@blueprint.route("/ac/status", methods=["POST"])
def api_ac_status():
    """ESP32 informa o estado físico atual dos ACs, após executar a ação IR."""
    cfg = _carregar_config()
    if not _checar_token(request.headers.get("X-Device-Token", ""), cfg["ar_condicionado"]["token"]):
        return jsonify({"ok": False, "erro": "Token inválido."}), 401

    dados = request.get_json(force=True, silent=True) or {}
    novo_estado = dados.get("estado", "").strip().lower()
    if novo_estado not in ("ligado", "desligado"):
        return jsonify({"ok": False, "erro": "Estado deve ser 'ligado' ou 'desligado'."}), 400

    with _lock_ac:
        estado = _carregar_estado_ac()
        estado["estado_atual"]  = novo_estado
        estado["atualizado_em"] = datetime.now().isoformat()
        _salvar_estado_ac(estado)

    db = _get_db()
    db.inserir("leituras_iot", {
        "sensor_id": "ar_condicionado", "tipo": "ac_status",
        "valor": 1.0 if novo_estado == "ligado" else 0.0,
        "data_hora": datetime.now().isoformat(),
    })
    return jsonify({"ok": True})

@blueprint.route("/ac/ligar", methods=["POST"])
@perfil_obrigatorio("portaria", "admin")
def api_ac_ligar():
    """Botão manual do painel web: define o estado desejado como 'ligado'."""
    with _lock_ac:
        estado = _carregar_estado_ac()
        estado["estado_desejado"] = "ligado"
        _salvar_estado_ac(estado)
    return jsonify({"ok": True, "mensagem": "Comando enviado. Aguardando confirmação dos ACs."})

@blueprint.route("/ac/desligar", methods=["POST"])
@perfil_obrigatorio("portaria", "admin")
def api_ac_desligar():
    """Botão manual do painel web: define o estado desejado como 'desligado'."""
    with _lock_ac:
        estado = _carregar_estado_ac()
        estado["estado_desejado"] = "desligado"
        _salvar_estado_ac(estado)
    return jsonify({"ok": True, "mensagem": "Comando enviado."})