
import json
from pathlib import Path
from datetime import datetime, date
from flask import Blueprint, render_template, jsonify, request
from core.auth import login_obrigatorio, usuario_logado

blueprint = Blueprint("agendamento", __name__,
                      template_folder="../../templates/agendamento")

BASE = Path(__file__).resolve().parent


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    cfg = json.load(open(BASE.parent.parent / "core" / "config.json", encoding="utf-8"))
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

def _carregar_recursos() -> list:
    with open(BASE / "recursos.json", encoding="utf-8") as f:
        return json.load(f)["recursos"]

def _recurso_por_id(rid: str) -> dict | None:
    return next((r for r in _carregar_recursos() if r["id"] == rid), None)

def _horas_conflitam(ini1, fim1, ini2, fim2) -> bool:
    return ini1 < fim2 and fim1 > ini2

def _verificar_conflito(db, recurso_id: str, data: str,
                        hora_inicio: str, hora_fim: str,
                        excluir_id: int | None = None) -> dict | None:
    """Busca reserva ativa que conflite com o intervalo solicitado."""
    todas = db.buscar("reservas", onde={"data_reserva": data, "recurso_id": recurso_id})
    ativas = [r for r in todas if not r.get("devolvido")]
    for r in ativas:
        if excluir_id and r["id"] == excluir_id:
            continue
        if _horas_conflitam(hora_inicio, hora_fim, r["hora_inicio"], r["hora_fim"]):
            return r
    return None

def _enriquecer_reservas(db, reservas: list, usuario_id: int) -> list:
    """
    Adiciona professor_nome (buscado da tabela usuarios quando ausente),
    recurso_icone, recurso_nome_exibicao e flag e_minha.
    """
    recursos_map = {r["id"]: r for r in _carregar_recursos()}

    usuarios = db.buscar("usuarios")
    nomes_map = {u["id"]: u["nome"] for u in usuarios}

    for r in reservas:
        rec = recursos_map.get(r.get("recurso_id"), {})
        r["recurso_nome_exibicao"] = rec.get("nome", r.get("recurso_nome", ""))
        r["recurso_icone"]         = rec.get("icone", "📦")
        r["e_minha"]               = r.get("professor_id") == usuario_id

        if not r.get("professor_nome"):
            r["professor_nome"] = nomes_map.get(r.get("professor_id"), "Desconhecido")

    return reservas


@blueprint.route("/")
@login_obrigatorio
def index():
    return render_template("agendamento/index.html",
                           recursos=_carregar_recursos(),
                           hoje=date.today().isoformat())


@blueprint.route("/api/recursos")
@login_obrigatorio
def api_recursos():
    return jsonify(_carregar_recursos())


@blueprint.route("/api/reservas")
@login_obrigatorio
def api_reservas():
    data       = request.args.get("data", date.today().isoformat())
    recurso_id = request.args.get("recurso_id")
    so_minhas  = request.args.get("apenas_minhas", "false").lower() == "true"

    db     = _get_db()
    filtro = {"data_reserva": data}
    if recurso_id:
        filtro["recurso_id"] = recurso_id

    reservas = db.buscar("reservas", onde=filtro, ordenar_por="hora_inicio")
    reservas = [r for r in reservas if not r.get("devolvido")]

    usuario = usuario_logado()
    if so_minhas:
        reservas = [r for r in reservas if r.get("professor_id") == usuario["id"]]

    return jsonify(_enriquecer_reservas(db, reservas, usuario["id"]))


@blueprint.route("/api/reservas", methods=["POST"])
@login_obrigatorio
def api_nova_reserva():
    dados        = request.get_json(force=True)
    usuario      = usuario_logado()
    recurso_id   = dados.get("recurso_id",   "").strip()
    data_reserva = dados.get("data_reserva", "").strip()
    hora_inicio  = dados.get("hora_inicio",  "").strip()
    hora_fim     = dados.get("hora_fim",     "").strip()

    if not all([recurso_id, data_reserva, hora_inicio, hora_fim]):
        return jsonify({"ok": False, "erro": "Preencha todos os campos."}), 400

    recurso = _recurso_por_id(recurso_id)
    if not recurso:
        return jsonify({"ok": False, "erro": "Recurso inválido."}), 400
    if hora_inicio >= hora_fim:
        return jsonify({"ok": False, "erro": "Horário de início deve ser antes do fim."}), 400
    if data_reserva < date.today().isoformat():
        return jsonify({"ok": False, "erro": "Não é possível reservar datas passadas."}), 400

    db       = _get_db()
    conflito = _verificar_conflito(db, recurso_id, data_reserva, hora_inicio, hora_fim)
    if conflito:
        usuarios  = db.buscar("usuarios")
        nomes_map = {u["id"]: u["nome"] for u in usuarios}
        nome_conf = conflito.get("professor_nome") or nomes_map.get(conflito.get("professor_id"), "outro professor")
        return jsonify({
            "ok":  False,
            "erro": (f"{recurso['nome']} já está reservado das "
                     f"{conflito['hora_inicio']} às {conflito['hora_fim']} "
                     f"por {nome_conf}."),
        }), 409

    registro = db.inserir("reservas", {
        "professor_id":   usuario["id"],
        "professor_nome": usuario["nome"],
        "recurso_tipo":   recurso["tipo"],
        "recurso_nome":   recurso["nome"],
        "recurso_id":     recurso_id,
        "data_reserva":   data_reserva,
        "hora_inicio":    hora_inicio,
        "hora_fim":       hora_fim,
        "devolvido":      False,
        "data_devolucao": None,
    })
    return jsonify({"ok": True, "reserva": registro}), 201


@blueprint.route("/api/reservas/<int:reserva_id>", methods=["DELETE"])
@login_obrigatorio
def api_cancelar_reserva(reserva_id: int):
    db      = _get_db()
    usuario = usuario_logado()
    reserva = db.buscar_um("reservas", onde={"id": reserva_id})
    if not reserva:
        return jsonify({"ok": False, "erro": "Reserva não encontrada."}), 404
    if usuario["perfil"] == "professor" and reserva.get("professor_id") != usuario["id"]:
        return jsonify({"ok": False, "erro": "Você só pode cancelar suas próprias reservas."}), 403
    db.atualizar("reservas",
                 {"devolvido": True, "data_devolucao": datetime.now().isoformat()},
                 onde={"id": reserva_id})
    return jsonify({"ok": True})


@blueprint.route("/api/disponibilidade")
@login_obrigatorio
def api_disponibilidade():
    rid  = request.args.get("recurso_id", "")
    data = request.args.get("data", "")
    ini  = request.args.get("hora_inicio", "")
    fim  = request.args.get("hora_fim", "")
    if not all([rid, data, ini, fim]):
        return jsonify({"disponivel": False, "erro": "Parâmetros incompletos."}), 400
    db       = _get_db()
    conflito = _verificar_conflito(db, rid, data, ini, fim)
    if conflito:
        usuarios  = db.buscar("usuarios")
        nomes_map = {u["id"]: u["nome"] for u in usuarios}
        conflito["professor_nome"] = (conflito.get("professor_nome")
                                      or nomes_map.get(conflito.get("professor_id"), "?"))
    return jsonify({"disponivel": conflito is None, "conflito": conflito})


@blueprint.route("/api/visao-geral")
@login_obrigatorio
def api_visao_geral():
    """Retorna reservas de TODOS os recursos para uma data, agrupadas por recurso_id."""
    data    = request.args.get("data", date.today().isoformat())
    db      = _get_db()
    usuario = usuario_logado()

    todas = db.buscar("reservas", onde={"data_reserva": data})
    todas = [r for r in todas if not r.get("devolvido")]
    todas = _enriquecer_reservas(db, todas, usuario["id"])

    por_recurso: dict[str, list] = {}
    for r in todas:
        por_recurso.setdefault(r["recurso_id"], []).append(r)

    return jsonify(por_recurso)