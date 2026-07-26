
import json
import threading
import logging
import sys
import os
from pathlib import Path
from datetime import datetime, date
from flask import Flask, jsonify, request


BASE_SINAL = Path(__file__).resolve().parent
BASE_PROJETO = BASE_SINAL.parent.parent

CONFIG_PATH = BASE_PROJETO / "core" / "config.json"
print(__file__)
def _cfg():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

LOG_PATH = BASE_PROJETO / "logs" / "sinal.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SINAL] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
    ],
)


ARQUIVO_SOM = BASE_SINAL / "sons" / "sinal.wav"
_tocando = threading.Lock()

def tocar_sinal():
    if not ARQUIVO_SOM.exists():
        logging.warning(f"Arquivo de som não encontrado: {ARQUIVO_SOM}")
        return

    def _play():
        with _tocando:
            try:
                import winsound
                winsound.PlaySound(str(ARQUIVO_SOM), winsound.SND_FILENAME)
                logging.info("Sinal reproduzido com sucesso.")
            except Exception as e:
                logging.error(f"Erro ao reproduzir sinal: {e}")

    threading.Thread(target=_play, daemon=True).start()


ESTADO_PATH = BASE_SINAL / "estado_sinal.json"

def _estado_inicial() -> dict:
    return {
        "lista_ativa":   "padrao",
        "data_atual":    date.today().isoformat(),
        "cancelamentos": [],
        "tocados_hoje":  [],
    }

def carregar_estado() -> dict:
    """Carrega o estado persistido. Se for de outro dia, reinicia."""
    if ESTADO_PATH.exists():
        try:
            with open(ESTADO_PATH, encoding="utf-8") as f:
                estado = json.load(f)
            if estado.get("data_atual") == date.today().isoformat():
                return estado
        except Exception:
            pass
    estado = _estado_inicial()
    salvar_estado(estado)
    return estado

def salvar_estado(estado: dict) -> None:
    estado["data_atual"] = date.today().isoformat()
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)

_estado = carregar_estado()
_lock_estado = threading.Lock()


def carregar_horarios(nome_lista: str) -> list:
    """Carrega a lista de horários do JSON correspondente."""
    nomes = {"padrao": "horarios_padrao.json",
             "sabado": "horarios_sabado.json",
             "prova":  "horarios_prova.json"}
    arquivo = BASE_SINAL / nomes.get(nome_lista, "horarios_padrao.json")
    with open(arquivo, encoding="utf-8") as f:
        dados = json.load(f)
    return dados["horarios"]


def loop_scheduler():
    """
    Loop executado em thread separada. Verifica a cada 20 segundos
    se algum sinal deve ser tocado agora.
    """
    import time

    logging.info("Scheduler de sinal iniciado.")

    while True:
        try:
            agora = datetime.now()
            hora_atual = agora.strftime("%H:%M")

            with _lock_estado:
                if _estado["data_atual"] != date.today().isoformat():
                    _estado.update(_estado_inicial())
                    salvar_estado(_estado)
                    logging.info("Novo dia — estado reiniciado.")

                lista_ativa   = _estado["lista_ativa"]
                cancelamentos = set(_estado["cancelamentos"])
                tocados       = set(_estado["tocados_hoje"])

            horarios = carregar_horarios(lista_ativa)

            for h in horarios:
                hid  = h["id"]
                hora = h["hora"]

                if hid in tocados or hid in cancelamentos:
                    continue
                if hora != hora_atual:
                    continue

                logging.info(f"Tocando sinal {hid} — {hora} — {h.get('descricao','')}")
                tocar_sinal()

                with _lock_estado:
                    _estado["tocados_hoje"].append(hid)
                    salvar_estado(_estado)

                break

        except Exception as e:
            logging.error(f"Erro no scheduler: {e}")

        time.sleep(20)


mini_app = Flask(__name__)
mini_app.config["JSON_AS_ASCII"] = False

@mini_app.route("/status")
def status():
    """Retorna o estado atual do sinal para o painel web."""
    with _lock_estado:
        lista_ativa   = _estado["lista_ativa"]
        cancelamentos = set(_estado["cancelamentos"])
        tocados       = set(_estado["tocados_hoje"])

    horarios  = carregar_horarios(lista_ativa)
    agora     = datetime.now().strftime("%H:%M")

    proximo = None
    for h in horarios:
        if h["id"] not in cancelamentos and h["hora"] > agora:
            proximo = h
            break

    for h in horarios:
        hid = h["id"]
        if hid in cancelamentos:
            h["status"] = "cancelado"
        elif hid in tocados:
            h["status"] = "tocado"
        elif h["hora"] == agora:
            h["status"] = "tocando"
        elif h["hora"] < agora:
            h["status"] = "passado"
        else:
            h["status"] = "pendente"

    return jsonify({
        "lista_ativa":  lista_ativa,
        "hora_atual":   agora,
        "proximo":      proximo,
        "horarios":     horarios,
        "som_presente": ARQUIVO_SOM.exists(),
    })


@mini_app.route("/tocar", methods=["POST"])
def tocar():
    """Toca o sinal manualmente (acionado pelo painel web)."""
    logging.info("Toque manual acionado pelo painel web.")
    tocar_sinal()
    return jsonify({"ok": True, "mensagem": "Sinal tocado manualmente."})


@mini_app.route("/cancelar/<hid>", methods=["POST"])
def cancelar(hid):
    """Cancela um horário futuro pelo ID."""
    with _lock_estado:
        tocados       = set(_estado["tocados_hoje"])
        cancelamentos = _estado["cancelamentos"]

        if hid in tocados:
            return jsonify({"ok": False, "erro": "Este sinal já foi tocado."}), 400

        if hid not in cancelamentos:
            cancelamentos.append(hid)
            salvar_estado(_estado)
            logging.info(f"Horário {hid} cancelado.")

    return jsonify({"ok": True, "mensagem": f"Horário {hid} cancelado."})


@mini_app.route("/restaurar/<hid>", methods=["POST"])
def restaurar(hid):
    """Restaura um horário cancelado."""
    with _lock_estado:
        if hid in _estado["cancelamentos"]:
            _estado["cancelamentos"].remove(hid)
            salvar_estado(_estado)
            logging.info(f"Horário {hid} restaurado.")

    return jsonify({"ok": True, "mensagem": f"Horário {hid} restaurado."})


@mini_app.route("/lista", methods=["PUT"])
def trocar_lista():
    """Troca a lista de horários ativa (padrao | sabado | prova)."""
    dados     = request.get_json(force=True)
    nova_lista = dados.get("lista", "")
    if nova_lista not in ("padrao", "sabado", "prova"):
        return jsonify({"ok": False, "erro": "Lista inválida."}), 400

    with _lock_estado:
        _estado["lista_ativa"]   = nova_lista
        _estado["cancelamentos"] = []
        _estado["tocados_hoje"]  = []
        salvar_estado(_estado)
        logging.info(f"Lista trocada para '{nova_lista}'.")

    return jsonify({"ok": True, "lista": nova_lista})


@mini_app.route("/whatsapp", methods=["POST"])
def enviar_whatsapp():
    """
    Envia mensagem de saída antecipada para os grupos WhatsApp.
    Usa pywhatkit (requer WhatsApp Web aberto no navegador).
    """
    dados         = request.get_json(force=True)
    turmas        = dados.get("turmas", [])
    horario_saida = dados.get("horario_saida", "")
    motivo_id     = dados.get("motivo", "")

    if not turmas or not horario_saida:
        return jsonify({"ok": False, "erro": "Informe turmas e horário de saída."}), 400

    grupos_path = BASE_SINAL / "whatsapp_grupos.json"
    with open(grupos_path, encoding="utf-8") as f:
        cfg_wp = json.load(f)

    motivo_texto = cfg_wp["motivos"].get(motivo_id, motivo_id)
    data_hoje    = date.today().strftime("%d/%m/%Y")
    turmas_str   = ", ".join(turmas)

    mensagem = (
        f"🔔 *Aviso — ETEPLAP*\n\n"
        f"Informamos que as turmas *{turmas_str}* terão "
        f"saída antecipada hoje ({data_hoje}) às *{horario_saida}*.\n\n"
        f"Motivo: {motivo_texto}.\n\n"
        f"_Mensagem automática — Smart Campus ETEPLAP_"
    )

    grupos_alvo = []
    for grupo in cfg_wp["grupos"]:
        for turma in turmas:
            if turma in grupo["turmas"]:
                grupos_alvo.append(grupo)
                break

    if not grupos_alvo:
        return jsonify({"ok": False, "erro": "Nenhum grupo encontrado para as turmas selecionadas."}), 400

    erros    = []
    enviados = []

    for grupo in grupos_alvo:
        numero = grupo.get("numero", "").strip()
        if not numero:
            erros.append(f"Número não configurado para '{grupo['nome']}'.")
            continue

        try:
            import pywhatkit
            pywhatkit.sendwhatmsg(
                f"+{numero}", mensagem,
                time_hour=datetime.now().hour,
                time_min=datetime.now().minute + 1,
                wait_time=15,
                tab_close=True,
                close_time=3,
            )
            enviados.append(grupo["nome"])
            logging.info(f"WhatsApp enviado para {grupo['nome']} ({numero}).")

        except ImportError:
            from urllib.parse import quote
            link = f"https://wa.me/{numero}?text={quote(mensagem)}"
            erros.append(f"pywhatkit não instalado. Link manual para {grupo['nome']}: {link}")
            logging.warning(f"pywhatkit ausente. Link gerado para {grupo['nome']}.")

        except Exception as e:
            erros.append(f"Erro ao enviar para {grupo['nome']}: {e}")
            logging.error(f"Erro WhatsApp {grupo['nome']}: {e}")

    return jsonify({
        "ok":       len(enviados) > 0,
        "enviados": enviados,
        "erros":    erros,
        "mensagem": mensagem,
    })



if __name__ == "__main__":
    logging.info("=== Sinal ETEPLAP iniciando ===")
    logging.info(f"Lista ativa: {_estado['lista_ativa']}")
    logging.info(f"Som: {ARQUIVO_SOM} ({'OK' if ARQUIVO_SOM.exists() else 'AUSENTE'})")

    t_scheduler = threading.Thread(target=loop_scheduler, daemon=True, name="scheduler-sinal")
    t_scheduler.start()

    logging.info("Mini servidor do sinal ouvindo na porta 5001.")
    mini_app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False, threaded=True)
