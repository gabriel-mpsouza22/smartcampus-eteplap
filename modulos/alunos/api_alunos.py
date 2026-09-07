"""
Cadastro de Alunos
-------------------
Tela dedicada ao CRUD de alunos do cadastro único (core/alunos.py).
Acesso permitido para: Secretaria, Coordenação e Administrador — os
mesmos perfis que precisam manter a base de alunos em dia, já que
qualquer outro módulo (Ocorrências, Biblioteca, Evasão, Sinal/WhatsApp
por turma, etc.) depende deste cadastro estar correto.
"""

from flask import Blueprint, render_template, jsonify, request
from core.auth import perfil_obrigatorio, usuario_logado
from core import alunos as cadastro_alunos
from core import promocoes

blueprint = Blueprint("alunos", __name__, template_folder="../../templates/alunos")

PERFIS_PERMITIDOS = ("secretaria", "coordenadora", "admin")


@blueprint.route("/")
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def painel():
    """Renderiza a tela de cadastro de alunos."""
    return render_template(
        "alunos/painel.html",
        turmas=cadastro_alunos.turmas_no_escopo(),
    )


@blueprint.route("/promocao")
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def promocao_painel():
    """Renderiza a tela de avanço de ano letivo (fim de ano)."""
    return render_template(
        "alunos/promocao.html",
        turmas=cadastro_alunos.turmas_no_escopo(),
    )


@blueprint.route("/api/promocao/turma")
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_promocao_turma():
    """Query: turma. Retorna alunos da turma + sugestão de destino de cada um."""
    turma = request.args.get("turma", "")
    try:
        dados = promocoes.montar_painel_turma(turma)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, **dados})


@blueprint.route("/api/promocao/ultimo-lote")
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_promocao_ultimo_lote():
    """Retorna o último lote de avanço ainda desfazível, se houver."""
    lote = promocoes.ultimo_lote_desfazivel()
    return jsonify({"ok": True, "lote": lote})


@blueprint.route("/api/promocao/confirmar", methods=["POST"])
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_promocao_confirmar():
    """Body: {turma_origem, decisoes: [{aluno_id, acao, nova_turma}]}."""
    dados = request.get_json(force=True) or {}
    usuario = usuario_logado()
    try:
        resumo = promocoes.aplicar_lote(
            dados.get("decisoes", []),
            turma_origem=dados.get("turma_origem", ""),
            executado_por=(usuario or {}).get("nome", ""),
        )
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, **resumo})


@blueprint.route("/api/promocao/desfazer", methods=["POST"])
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_promocao_desfazer():
    """Body: {lote_id}."""
    dados = request.get_json(force=True) or {}
    try:
        quantidade = promocoes.desfazer_lote(dados.get("lote_id"))
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, "quantidade": quantidade})


@blueprint.route("/api/turmas")
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_turmas():
    """Lista fixa de turmas (turma → série + curso)."""
    return jsonify(cadastro_alunos.turmas_no_escopo())


@blueprint.route("/api/lista")
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_lista():
    """Query opcional: busca (nome), turma."""
    busca = request.args.get("busca", "")
    turma = request.args.get("turma", "")
    lista = cadastro_alunos.buscar(busca=busca, turma=turma)
    return jsonify(lista)


@blueprint.route("/api/alunos", methods=["POST"])
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_criar():
    """Body: nome, turma, matricula (opcional)."""
    dados = request.get_json(force=True)
    try:
        registro = cadastro_alunos.criar(dados.get("nome", ""), dados.get("turma", ""), dados.get("matricula", ""))
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, "aluno": registro}), 201


@blueprint.route("/api/alunos/<int:aluno_id>", methods=["PUT"])
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_atualizar(aluno_id: int):
    """Body: nome, turma, matricula (opcional)."""
    dados = request.get_json(force=True)
    try:
        registro = cadastro_alunos.atualizar(aluno_id, dados.get("nome", ""), dados.get("turma", ""), dados.get("matricula"))
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, "aluno": registro})


@blueprint.route("/api/alunos/<int:aluno_id>", methods=["DELETE"])
@perfil_obrigatorio(*PERFIS_PERMITIDOS)
def api_remover(aluno_id: int):
    """Remove um aluno do cadastro único."""
    if not cadastro_alunos.remover(aluno_id):
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404
    return jsonify({"ok": True})
