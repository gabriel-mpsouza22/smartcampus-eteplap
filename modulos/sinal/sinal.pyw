"""
Servidor standalone do sinal — usado apenas no modo "remoto" (quando o
PC ligado à caixa de som é diferente do servidor principal). Roda como
processo separado, expõe a mesma lógica de motor.py via um mini
servidor Flask na porta 5001, que o servidor principal acessa via HTTP
(ver core/api_sinal.py e sinal_modo em core/config.json).

No modo "local" (mesma máquina), este arquivo NÃO é usado — o servidor
principal chama as funções de motor.py diretamente, sem rede.
"""

import logging
import threading
from pathlib import Path
from flask import Flask, jsonify, request

import motor

BASE_SINAL   = Path(__file__).resolve().parent
BASE_PROJETO = BASE_SINAL.parent.parent

LOG_PATH = BASE_PROJETO / "logs" / "sinal.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SINAL] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
    ],
)

mini_app = Flask(__name__)
mini_app.config["JSON_AS_ASCII"] = False


@mini_app.route("/status")
def status():
    return jsonify(motor.obter_status())


@mini_app.route("/sons")
def listar_sons():
    return jsonify({
        "sons":      motor.sons_disponiveis(),
        "som_ativo": motor._config_som().get("som_ativo", motor.SOM_PADRAO),
    })


@mini_app.route("/sons/ativo", methods=["PUT"])
def definir_som_ativo():
    dados = request.get_json(force=True)
    try:
        resultado = motor.definir_som_ativo(dados.get("arquivo", ""))
        return jsonify({"ok": True, **resultado})
    except (ValueError, FileNotFoundError) as e:
        codigo = 404 if isinstance(e, FileNotFoundError) else 400
        return jsonify({"ok": False, "erro": str(e)}), codigo


@mini_app.route("/sons/testar/<arquivo>", methods=["POST"])
def testar_som(arquivo):
    try:
        nome = motor.testar_som(arquivo)
        return jsonify({"ok": True, "mensagem": f"Tocando teste: {nome}"})
    except (ValueError, FileNotFoundError) as e:
        codigo = 404 if isinstance(e, FileNotFoundError) else 400
        return jsonify({"ok": False, "erro": str(e)}), codigo


@mini_app.route("/tocar", methods=["POST"])
def tocar():
    logging.info("Toque manual acionado pelo painel web.")
    motor.tocar_sinal()
    return jsonify({"ok": True, "mensagem": "Sinal tocado manualmente."})


@mini_app.route("/cancelar/<hid>", methods=["POST"])
def cancelar(hid):
    try:
        motor.cancelar_horario(hid)
        return jsonify({"ok": True, "mensagem": f"Horário {hid} cancelado."})
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


@mini_app.route("/restaurar/<hid>", methods=["POST"])
def restaurar(hid):
    motor.restaurar_horario(hid)
    return jsonify({"ok": True, "mensagem": f"Horário {hid} restaurado."})


@mini_app.route("/lista", methods=["PUT"])
def trocar_lista():
    dados = request.get_json(force=True)
    try:
        motor.trocar_lista(dados.get("lista", ""))
        return jsonify({"ok": True, "lista": dados.get("lista", "")})
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


@mini_app.route("/whatsapp", methods=["POST"])
def enviar_whatsapp():
    dados = request.get_json(force=True)
    try:
        resultado = motor.enviar_whatsapp(
            dados.get("turmas", []),
            dados.get("horario_saida", ""),
            dados.get("motivo", ""),
        )
        return jsonify({"ok": len(resultado["enviados"]) > 0, **resultado})
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


if __name__ == "__main__":
    logging.info("=== Sinal — servidor remoto standalone iniciando ===")

    t_scheduler = threading.Thread(target=motor._loop_scheduler, daemon=True, name="scheduler-sinal")
    t_scheduler.start()

    logging.info("Mini servidor do sinal ouvindo na porta 5001.")
    mini_app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False, threaded=True)
