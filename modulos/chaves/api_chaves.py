"""
Módulo: Controle de Chaves
----------------------------
Registro de retirada e devolução de chaves físicas (salas, laboratórios,
armários) — resolve o clássico "quem ficou com a chave do laboratório?"
sem depender de caderno de papel na portaria.

Modelo de acesso (revisado): só a SECRETARIA opera este módulo. Ela é
quem fisicamente entrega e recebe a chave no balcão, então é ela quem
registra no sistema — escolhendo o professor (de uma lista vinda do
cadastro de usuários) e a chave entregue. Professores não têm acesso
a este módulo; não retiram nem devolvem nada eles mesmos no sistema,
já que quem passa pelo controle é sempre a secretaria.

Uma chave só pode estar em um de dois estados: DISPONÍVEL ou EM USO — o
estado é sempre derivado do último movimento em aberto (sem devolução),
nunca guardado solto, para não ter como o cadastro e o histórico
divergirem.
"""

import json
from pathlib import Path
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request

blueprint = Blueprint("chaves", __name__,
                      template_folder="../../templates/chaves")

from core.auth import perfil_obrigatorio, usuario_logado, listar_usuarios

BASE = Path(__file__).resolve().parent

PERFIL_OPERADOR = "secretaria"  # único perfil (além de admin) que opera o módulo


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    from core.config_path import carregar_config
    cfg = carregar_config(BASE.parent.parent)
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")


def _movimento_aberto(db, chave_id: int) -> dict | None:
    """Retorna o movimento de retirada ainda sem devolução, se houver."""
    movimentos = db.buscar("chaves_movimentos", onde={"chave_id": chave_id})
    abertos = [m for m in movimentos if not m.get("devolvido_em")]
    return abertos[-1] if abertos else None


def _enriquecer(db, chave: dict) -> dict:
    """Adiciona o status atual (disponível/em uso) e dados de atraso à chave."""
    aberto = _movimento_aberto(db, chave["id"])
    chave["em_uso"] = aberto is not None

    if aberto:
        prevista = aberto.get("devolucao_prevista")
        atraso = bool(prevista) and datetime.now() > datetime.fromisoformat(prevista)
        chave["movimento_atual"] = {
            "id":                 aberto["id"],
            "professor_id":       aberto.get("professor_id"),
            "professor_nome":     aberto["professor_nome"],
            "retirado_em":        aberto["retirado_em"],
            "devolucao_prevista": prevista,
            "registrado_por":     aberto.get("registrado_por", ""),
            "observacao":         aberto.get("observacao") or "",
            "atrasada":           atraso,
        }
    else:
        chave["movimento_atual"] = None

    return chave


def _listar_professores() -> list[dict]:
    """Professores ativos, para o seletor da secretaria."""
    usuarios = listar_usuarios()
    return sorted(
        [{"id": u["id"], "nome": u["nome"]} for u in usuarios if u["perfil"] == "professor" and u.get("ativo", True)],
        key=lambda u: u["nome"]
    )


@blueprint.route("/")
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def index():
    return render_template("chaves/index.html", professores=_listar_professores())


@blueprint.route("/api/status")
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def api_status():
    db = _get_db()
    chaves = [c for c in db.buscar("chaves") if c.get("ativa", True)]
    chaves = [_enriquecer(db, c) for c in chaves]

    em_uso    = [c for c in chaves if c["em_uso"]]
    atrasadas = [c for c in em_uso if c["movimento_atual"]["atrasada"]]

    return jsonify({
        "total":       len(chaves),
        "disponiveis": len(chaves) - len(em_uso),
        "em_uso":      len(em_uso),
        "atrasadas":   len(atrasadas),
    })


@blueprint.route("/api/professores")
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def api_listar_professores():
    return jsonify(_listar_professores())


@blueprint.route("/api/chaves")
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def api_listar_chaves():
    """Query: busca (nome parcial), status (disponivel|em_uso|atrasada)."""
    busca  = request.args.get("busca", "").strip().lower()
    status = request.args.get("status", "").strip()

    db = _get_db()
    chaves = [c for c in db.buscar("chaves", ordenar_por="nome") if c.get("ativa", True)]
    chaves = [_enriquecer(db, c) for c in chaves]

    if busca:
        chaves = [c for c in chaves if busca in c["nome"].lower() or busca in (c.get("local") or "").lower()]

    if status == "disponivel":
        chaves = [c for c in chaves if not c["em_uso"]]
    elif status == "em_uso":
        chaves = [c for c in chaves if c["em_uso"]]
    elif status == "atrasada":
        chaves = [c for c in chaves if c["em_uso"] and c["movimento_atual"]["atrasada"]]

    return jsonify(chaves)


@blueprint.route("/api/chaves", methods=["POST"])
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def api_cadastrar_chave():
    dados = request.get_json(force=True)
    nome  = (dados.get("nome") or "").strip()
    local = (dados.get("local") or "").strip()
    icone = (dados.get("icone") or "🔑").strip() or "🔑"

    if not nome:
        return jsonify({"ok": False, "erro": "Informe o nome da chave (ex: Laboratório de Redes 1)."}), 400

    db = _get_db()
    existente = next((c for c in db.buscar("chaves") if c["nome"].lower() == nome.lower() and c.get("ativa", True)), None)
    if existente:
        return jsonify({"ok": False, "erro": "Já existe uma chave ativa com esse nome."}), 400

    registro = db.inserir("chaves", {
        "nome":         nome,
        "local":        local,
        "icone":        icone,
        "observacoes":  (dados.get("observacoes") or "").strip(),
        "ativa":        True,
        "criada_em":    datetime.now().isoformat(),
    })
    return jsonify({"ok": True, "chave": _enriquecer(db, registro)}), 201


@blueprint.route("/api/chaves/<int:chave_id>", methods=["DELETE"])
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def api_desativar_chave(chave_id: int):
    """Desativa (não apaga) a chave — preserva o histórico de movimentações."""
    db = _get_db()
    chave = db.buscar_um("chaves", onde={"id": chave_id})
    if not chave:
        return jsonify({"ok": False, "erro": "Chave não encontrada."}), 404

    if _movimento_aberto(db, chave_id):
        return jsonify({"ok": False, "erro": "Essa chave está em uso. Registre a devolução antes de desativá-la."}), 409

    db.atualizar("chaves", {"ativa": False}, onde={"id": chave_id})
    return jsonify({"ok": True})


@blueprint.route("/api/chaves/<int:chave_id>/entregar", methods=["POST"])
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def api_entregar_chave(chave_id: int):
    """
    Body: professor_id (obrigatório), devolucao_prevista (obrigatório, ISO
    datetime — até quando a chave deve voltar), observacao (opcional).
    Registra que a secretaria entregou a chave a um professor.
    """
    db = _get_db()
    chave = db.buscar_um("chaves", onde={"id": chave_id})
    if not chave or not chave.get("ativa", True):
        return jsonify({"ok": False, "erro": "Chave não encontrada."}), 404

    if _movimento_aberto(db, chave_id):
        return jsonify({"ok": False, "erro": "Essa chave já está em uso."}), 409

    dados = request.get_json(force=True, silent=True) or {}
    professor_id = dados.get("professor_id")
    if not professor_id:
        return jsonify({"ok": False, "erro": "Selecione o professor que está retirando a chave."}), 400

    professor = next((p for p in _listar_professores() if p["id"] == professor_id), None)
    if not professor:
        return jsonify({"ok": False, "erro": "Professor inválido ou inativo."}), 400

    devolucao_prevista_raw = (dados.get("devolucao_prevista") or "").strip()
    if not devolucao_prevista_raw:
        return jsonify({"ok": False, "erro": "Informe até quando a chave deve ser devolvida."}), 400

    try:
        devolucao_prevista = datetime.fromisoformat(devolucao_prevista_raw)
    except ValueError:
        return jsonify({"ok": False, "erro": "Horário de devolução inválido."}), 400

    agora = datetime.now()
    if devolucao_prevista <= agora:
        return jsonify({"ok": False, "erro": "O horário de devolução precisa ser depois de agora."}), 400

    operador = usuario_logado()

    movimento = db.inserir("chaves_movimentos", {
        "chave_id":            chave_id,
        "chave_nome":          chave["nome"],
        "professor_id":        professor["id"],
        "professor_nome":      professor["nome"],
        "registrado_por":      operador["nome"],
        "retirado_em":         agora.isoformat(),
        "devolucao_prevista":  devolucao_prevista.isoformat(),
        "observacao":          (dados.get("observacao") or "").strip(),
        "devolvido_em":        None,
        "devolvido_por":       None,
    })
    return jsonify({"ok": True, "movimento": movimento}), 201


@blueprint.route("/api/chaves/<int:chave_id>/devolver", methods=["POST"])
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def api_devolver_chave(chave_id: int):
    """A secretaria confirma que o professor devolveu a chave no balcão."""
    db = _get_db()
    chave = db.buscar_um("chaves", onde={"id": chave_id})
    if not chave:
        return jsonify({"ok": False, "erro": "Chave não encontrada."}), 404

    aberto = _movimento_aberto(db, chave_id)
    if not aberto:
        return jsonify({"ok": False, "erro": "Essa chave já está disponível."}), 409

    operador = usuario_logado()
    db.atualizar("chaves_movimentos", {
        "devolvido_em":  datetime.now().isoformat(),
        "devolvido_por": operador["nome"],
    }, onde={"id": aberto["id"]})

    return jsonify({"ok": True})


@blueprint.route("/api/chaves/<int:chave_id>/historico")
@perfil_obrigatorio(PERFIL_OPERADOR, "admin")
def api_historico_chave(chave_id: int):
    db = _get_db()
    if not db.buscar_um("chaves", onde={"id": chave_id}):
        return jsonify({"ok": False, "erro": "Chave não encontrada."}), 404

    movimentos = db.buscar("chaves_movimentos", onde={"chave_id": chave_id}, ordenar_por="retirado_em")
    return jsonify(list(reversed(movimentos))[:30])
