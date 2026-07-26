
import json
from pathlib import Path
from datetime import datetime, date
from flask import Blueprint, render_template, jsonify, request
from core.auth import login_obrigatorio, perfil_obrigatorio, usuario_logado

blueprint = Blueprint("sp", __name__,
                      template_folder="../../templates")

BASE = Path(__file__).resolve().parent
LIMITE_MENSAGENS = 80


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    cfg = json.load(open(BASE.parent.parent / "core" / "config.json", encoding="utf-8"))
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")


@blueprint.route("/secretaria/")
@perfil_obrigatorio("secretaria", "admin")
def pagina_secretaria():
    return render_template("secretaria/painel.html", hoje=date.today().isoformat())

@blueprint.route("/portaria/")
@perfil_obrigatorio("portaria", "admin")
def pagina_portaria():
    return render_template("portaria/painel.html", hoje=date.today().isoformat())


@blueprint.route("/api/compromissos")
@login_obrigatorio
def api_listar_compromissos():
    """Query: data (YYYY-MM-DD, padrão hoje)."""
    data = request.args.get("data", date.today().isoformat())
    db   = _get_db()
    compromissos = db.buscar("compromissos", onde={"data": data}, ordenar_por="hora")
    return jsonify(compromissos)

@blueprint.route("/api/compromissos", methods=["POST"])
@perfil_obrigatorio("secretaria", "admin")
def api_novo_compromisso():
    """Body: data, hora, responsavel, motivo."""
    dados       = request.get_json(force=True)
    data_c      = dados.get("data", "").strip()
    hora        = dados.get("hora", "").strip()
    responsavel = dados.get("responsavel", "").strip()
    motivo      = dados.get("motivo", "").strip()

    if not all([data_c, hora, responsavel, motivo]):
        return jsonify({"ok": False, "erro": "Preencha data, hora, responsável e motivo."}), 400

    try:
        datetime.strptime(data_c, "%Y-%m-%d")
    except ValueError:
        return jsonify({"ok": False, "erro": "Data inválida."}), 400

    db = _get_db()
    registro = db.inserir("compromissos", {
        "data":        data_c,
        "hora":        hora,
        "responsavel": responsavel,
        "motivo":      motivo,
        "criado_em":   datetime.now().isoformat(),
    })
    return jsonify({"ok": True, "compromisso": registro}), 201

@blueprint.route("/api/compromissos/<int:compromisso_id>", methods=["DELETE"])
@perfil_obrigatorio("secretaria", "admin")
def api_cancelar_compromisso(compromisso_id: int):
    db = _get_db()
    if not db.buscar_um("compromissos", onde={"id": compromisso_id}):
        return jsonify({"ok": False, "erro": "Compromisso não encontrado."}), 404
    db.deletar("compromissos", onde={"id": compromisso_id})
    return jsonify({"ok": True})


@blueprint.route("/api/chat/mensagens")
@perfil_obrigatorio("secretaria", "portaria", "admin")
def api_chat_mensagens():
    """
    Retorna as últimas mensagens do chat.
    Query opcional: desde_id — retorna apenas mensagens com id maior que esse
    (usado para polling incremental, evita reenviar tudo a cada requisição).
    """
    db = _get_db()
    desde_id = request.args.get("desde_id", type=int)

    mensagens = db.buscar("mensagens_chat", ordenar_por="id")

    if desde_id:
        mensagens = [m for m in mensagens if m["id"] > desde_id]
    else:
        mensagens = mensagens[-LIMITE_MENSAGENS:]

    return jsonify(mensagens)

@blueprint.route("/api/chat/enviar", methods=["POST"])
@perfil_obrigatorio("secretaria", "portaria", "admin")
def api_chat_enviar():
    """Body: texto. O remetente é sempre o usuário logado (nunca confia no cliente)."""
    dados = request.get_json(force=True)
    texto = dados.get("texto", "").strip()

    if not texto:
        return jsonify({"ok": False, "erro": "Mensagem vazia."}), 400
    if len(texto) > 500:
        return jsonify({"ok": False, "erro": "Mensagem muito longa (máx. 500 caracteres)."}), 400

    usuario = usuario_logado()
    db = _get_db()
    registro = db.inserir("mensagens_chat", {
        "remetente": usuario["nome"],
        "texto":     texto,
        "data_hora": datetime.now().isoformat(),
    })
    return jsonify({"ok": True, "mensagem": registro}), 201
