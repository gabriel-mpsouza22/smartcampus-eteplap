"""
Módulo: Chamados Técnicos
----------------------------
Fila de suporte técnico atendida pelos próprios alunos do curso de Redes
de Computadores, sob orientação da administração — ex: "o monitor da
máquina 4 do Laboratório 2 não liga".

Papéis:
  - professor (e admin): abre o chamado, acompanha o andamento e pode
    cancelá-lo enquanto ainda não foi resolvido.
  - aluno_chamados: só enxerga a fila e os próprios atendimentos; assume
    um chamado da fila e, ao concluir, registra o que foi feito.
  - admin: enxerga tudo, pode cancelar qualquer chamado em qualquer
    estado (ex: chamado duplicado ou aberto por engano).

Cada chamado tem no máximo um "dono" por vez: quem assumiu. Ninguém mais
pode assumir um chamado já assumido — evita dois alunos pisando no
mesmo problema sem saber.
"""

import json
from pathlib import Path
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request

blueprint = Blueprint("chamados", __name__,
                      template_folder="../../templates/chamados")

from core.auth import perfil_obrigatorio, usuario_logado
from core.notificacoes import notificar, resolver as resolver_notificacao

BASE = Path(__file__).resolve().parent

PERFIL_ABRE     = ("professor", "admin")
PERFIL_ATENDE   = ("aluno_chamados", "admin")
TODOS_PERFIS    = ("professor", "aluno_chamados", "admin")

CATEGORIAS = [
    {"id": "computador", "nome": "Computador",       "icone": "i-monitor"},
    {"id": "rede",       "nome": "Rede / Internet",  "icone": "i-antenna"},
    {"id": "software",   "nome": "Software",         "icone": "i-tools"},
    {"id": "audio_video","nome": "Áudio / Projeção", "icone": "i-projector"},
    {"id": "outro",      "nome": "Outro",             "icone": "i-tag"},
]

PRIORIDADES = [
    {"id": "baixa", "nome": "Baixa",  "classe": "baixo"},
    {"id": "media", "nome": "Média",  "classe": "moderado"},
    {"id": "alta",  "nome": "Alta",   "classe": "critico"},
]


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    from core.config_path import carregar_config
    cfg = carregar_config(BASE.parent.parent)
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")


def _categoria(id_cat: str) -> dict:
    return next((c for c in CATEGORIAS if c["id"] == id_cat), CATEGORIAS[-1])


def _enriquecer(chamado: dict) -> dict:
    chamado["categoria_info"] = _categoria(chamado.get("categoria", "outro"))
    prio = next((p for p in PRIORIDADES if p["id"] == chamado.get("prioridade")), PRIORIDADES[0])
    chamado["prioridade_info"] = prio
    return chamado


@blueprint.route("/")
@perfil_obrigatorio(*TODOS_PERFIS)
def index():
    usuario = usuario_logado()
    return render_template(
        "chamados/index.html",
        categorias=CATEGORIAS,
        prioridades=PRIORIDADES,
        pode_abrir=usuario["perfil"] in PERFIL_ABRE,
        pode_atender=usuario["perfil"] in PERFIL_ATENDE,
    )


@blueprint.route("/api/stats")
@perfil_obrigatorio(*TODOS_PERFIS)
def api_stats():
    usuario = usuario_logado()
    db = _get_db()
    chamados = db.buscar("chamados")

    if usuario["perfil"] == "professor":
        chamados = [c for c in chamados if c["aberto_por_id"] == usuario["id"]]

    return jsonify({
        "aberto":          len([c for c in chamados if c["status"] == "aberto"]),
        "em_atendimento":  len([c for c in chamados if c["status"] == "em_atendimento"]),
        "resolvido":       len([c for c in chamados if c["status"] == "resolvido"]),
        "total":           len(chamados),
    })


@blueprint.route("/api/chamados")
@perfil_obrigatorio(*TODOS_PERFIS)
def api_listar():
    """
    Query: status (aberto|em_atendimento|resolvido|cancelado), escopo
    (meus — só os relevantes pra quem está logado).
    Cada perfil só enxerga o que faz sentido pra ele:
      - professor: só os chamados que ele mesmo abriu.
      - aluno_chamados: a fila inteira (pra poder assumir) + o que já é seu.
      - admin: tudo.
    """
    usuario = usuario_logado()
    status  = request.args.get("status", "").strip()
    escopo  = request.args.get("escopo", "").strip()

    db = _get_db()
    chamados = db.buscar("chamados", ordenar_por="aberto_em")
    chamados = list(reversed(chamados))

    if usuario["perfil"] == "professor":
        chamados = [c for c in chamados if c["aberto_por_id"] == usuario["id"]]

    if escopo == "meus":
        if usuario["perfil"] == "aluno_chamados":
            chamados = [c for c in chamados if c.get("atribuido_a_id") == usuario["id"]]
        elif usuario["perfil"] == "professor":
            pass  # já é só os dele
        # admin com escopo "meus" não teria sentido — ignorado de propósito

    if status:
        chamados = [c for c in chamados if c["status"] == status]

    chamados = [_enriquecer(c) for c in chamados]
    return jsonify(chamados)


@blueprint.route("/api/chamados", methods=["POST"])
@perfil_obrigatorio(*PERFIL_ABRE)
def api_abrir():
    dados = request.get_json(force=True, silent=True) or {}

    titulo = (dados.get("titulo") or "").strip()
    local  = (dados.get("local") or "").strip()
    categoria  = (dados.get("categoria") or "").strip()
    prioridade = (dados.get("prioridade") or "media").strip()
    descricao  = (dados.get("descricao") or "").strip()

    if not titulo:
        return jsonify({"ok": False, "erro": "Descreva em poucas palavras qual é o problema."}), 400
    if not local:
        return jsonify({"ok": False, "erro": "Informe onde é o problema (sala, laboratório, equipamento)."}), 400
    if categoria not in {c["id"] for c in CATEGORIAS}:
        return jsonify({"ok": False, "erro": "Selecione uma categoria válida."}), 400
    if prioridade not in {p["id"] for p in PRIORIDADES}:
        prioridade = "media"

    usuario = usuario_logado()
    db = _get_db()

    chamado = db.inserir("chamados", {
        "titulo":          titulo,
        "descricao":       descricao,
        "categoria":       categoria,
        "local":           local,
        "prioridade":      prioridade,
        "status":          "aberto",
        "aberto_por_id":   usuario["id"],
        "aberto_por_nome": usuario["nome"],
        "aberto_em":       datetime.now().isoformat(),
    })
    notificar(modulo="chamados", tipo="chamado_aberto",
              titulo=f"Novo chamado — {titulo}",
              mensagem=f"{local} · categoria: {_categoria(categoria)['nome']}",
              url="/chamados/", destinatario_tipo="perfil", destinatario_valor="aluno_chamados",
              referencia_id=chamado["id"], criado_por=usuario["nome"])
    return jsonify({"ok": True, "chamado": _enriquecer(chamado)}), 201


@blueprint.route("/api/chamados/<int:chamado_id>/assumir", methods=["POST"])
@perfil_obrigatorio(*PERFIL_ATENDE)
def api_assumir(chamado_id: int):
    """O aluno pega o chamado pra si — só é possível se ainda estiver na fila."""
    db = _get_db()
    chamado = db.buscar_um("chamados", onde={"id": chamado_id})
    if not chamado:
        return jsonify({"ok": False, "erro": "Chamado não encontrado."}), 404
    if chamado["status"] != "aberto":
        return jsonify({"ok": False, "erro": "Esse chamado já foi assumido por outra pessoa ou não está mais na fila."}), 409

    usuario = usuario_logado()
    db.atualizar("chamados", {
        "status":           "em_atendimento",
        "atribuido_a_id":   usuario["id"],
        "atribuido_a_nome": usuario["nome"],
        "assumido_em":      datetime.now().isoformat(),
    }, onde={"id": chamado_id})

    resolver_notificacao(modulo="chamados", tipo="chamado_aberto", referencia_id=chamado_id)
    chamado = db.buscar_um("chamados", onde={"id": chamado_id})
    return jsonify({"ok": True, "chamado": _enriquecer(chamado)})


@blueprint.route("/api/chamados/<int:chamado_id>/resolver", methods=["POST"])
@perfil_obrigatorio(*PERFIL_ATENDE)
def api_resolver(chamado_id: int):
    """Body: resolucao (obrigatório) — o que foi feito pra resolver."""
    db = _get_db()
    chamado = db.buscar_um("chamados", onde={"id": chamado_id})
    if not chamado:
        return jsonify({"ok": False, "erro": "Chamado não encontrado."}), 404
    if chamado["status"] != "em_atendimento":
        return jsonify({"ok": False, "erro": "Só é possível concluir um chamado que está em atendimento."}), 409

    usuario = usuario_logado()
    if usuario["perfil"] != "admin" and chamado.get("atribuido_a_id") != usuario["id"]:
        return jsonify({"ok": False, "erro": "Só quem assumiu o chamado pode concluí-lo."}), 403

    dados = request.get_json(force=True, silent=True) or {}
    resolucao = (dados.get("resolucao") or "").strip()
    if not resolucao:
        return jsonify({"ok": False, "erro": "Descreva rapidamente o que foi feito pra resolver."}), 400

    db.atualizar("chamados", {
        "status":       "resolvido",
        "resolucao":    resolucao,
        "resolvido_em": datetime.now().isoformat(),
    }, onde={"id": chamado_id})

    notificar(modulo="chamados", tipo="chamado_resolvido",
              titulo=f"Chamado concluído — {chamado['titulo']}",
              mensagem=resolucao, url="/chamados/",
              destinatario_tipo="usuario", destinatario_valor=chamado["aberto_por_id"],
              referencia_id=chamado_id, criado_por=usuario["nome"])

    chamado = db.buscar_um("chamados", onde={"id": chamado_id})
    return jsonify({"ok": True, "chamado": _enriquecer(chamado)})


@blueprint.route("/api/chamados/<int:chamado_id>/cancelar", methods=["POST"])
@perfil_obrigatorio(*TODOS_PERFIS)
def api_cancelar(chamado_id: int):
    """
    Quem abriu pode cancelar enquanto não foi resolvido (ex: resolveu
    sozinho, abriu duplicado). Admin pode cancelar em qualquer estado.
    """
    db = _get_db()
    chamado = db.buscar_um("chamados", onde={"id": chamado_id})
    if not chamado:
        return jsonify({"ok": False, "erro": "Chamado não encontrado."}), 404

    usuario = usuario_logado()
    dono = chamado["aberto_por_id"] == usuario["id"]
    if usuario["perfil"] != "admin" and not dono:
        return jsonify({"ok": False, "erro": "Só quem abriu o chamado (ou a administração) pode cancelá-lo."}), 403
    if usuario["perfil"] != "admin" and chamado["status"] == "resolvido":
        return jsonify({"ok": False, "erro": "Esse chamado já foi resolvido e não pode mais ser cancelado."}), 409

    dados = request.get_json(force=True, silent=True) or {}
    db.atualizar("chamados", {
        "status":               "cancelado",
        "cancelado_em":         datetime.now().isoformat(),
        "motivo_cancelamento":  (dados.get("motivo") or "").strip(),
    }, onde={"id": chamado_id})

    resolver_notificacao(modulo="chamados", tipo="chamado_aberto", referencia_id=chamado_id)
    return jsonify({"ok": True})
