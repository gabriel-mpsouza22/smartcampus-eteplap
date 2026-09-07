"""
Rotas do Controle de Pontualidade.
Lógica de negócio real mora em core/pontualidade.py — aqui é só a
camada HTTP (autenticação por perfil, parsing de request, jsonify).
"""

from datetime import date
from flask import Blueprint, render_template, jsonify, request
from core.auth import perfil_obrigatorio, usuario_logado
from core import alunos as cadastro_alunos
from core import pontualidade

blueprint = Blueprint("pontualidade", __name__, template_folder="../../templates/pontualidade")

PERFIS_PORTARIA = ("portaria", "secretaria", "coordenadora", "admin")
PERFIS_COORDENACAO = ("coordenadora", "secretaria", "admin")


# ──────────────────────────────────────────────────────────────
# Páginas
# ──────────────────────────────────────────────────────────────

@blueprint.route("/")
@perfil_obrigatorio(*PERFIS_PORTARIA)
def portaria():
    """Tela de registro de entrada — uso intensivo pela portaria."""
    return render_template("pontualidade/portaria.html", turmas=cadastro_alunos.turmas_no_escopo())


@blueprint.route("/dashboard")
@perfil_obrigatorio(*PERFIS_COORDENACAO)
def dashboard():
    """Resumo mensal para coordenação/direção."""
    hoje = date.today()
    return render_template("pontualidade/dashboard.html", ano=hoje.year, mes=hoje.month)


@blueprint.route("/aluno/<int:aluno_id>")
@perfil_obrigatorio(*PERFIS_PORTARIA)
def perfil_aluno(aluno_id: int):
    """Perfil histórico de pontualidade de um aluno."""
    return render_template("pontualidade/perfil_aluno.html", aluno_id=aluno_id)


@blueprint.route("/configuracao")
@perfil_obrigatorio(*PERFIS_COORDENACAO)
def configuracao():
    """Tela de configuração das regras de horário e reincidência."""
    return render_template("pontualidade/configuracao.html")


# ──────────────────────────────────────────────────────────────
# API — portaria
# ──────────────────────────────────────────────────────────────

@blueprint.route("/api/buscar")
@perfil_obrigatorio(*PERFIS_PORTARIA)
def api_buscar():
    """Query: q. Busca rápida por nome ou matrícula para a tela da portaria."""
    termo = request.args.get("q", "")
    return jsonify(pontualidade.buscar_alunos_portaria(termo))


@blueprint.route("/api/registrar", methods=["POST"])
@perfil_obrigatorio(*PERFIS_PORTARIA)
def api_registrar():
    """Body: aluno_id. Registra entrada de um aluno já cadastrado."""
    dados = request.get_json(force=True) or {}
    usuario = usuario_logado()
    try:
        evento = pontualidade.registrar_entrada(
            dados.get("aluno_id"),
            operador=(usuario or {}).get("nome", ""),
            observacoes=dados.get("observacoes", ""),
        )
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, "evento": evento})


@blueprint.route("/api/registrar-novo", methods=["POST"])
@perfil_obrigatorio(*PERFIS_PORTARIA)
def api_registrar_novo():
    """Body: nome, turma, matricula (opcional). Cadastro progressivo + registro em uma tacada só."""
    dados = request.get_json(force=True) or {}
    usuario = usuario_logado()
    try:
        evento = pontualidade.registrar_entrada_com_cadastro_rapido(
            dados.get("nome", ""), dados.get("turma", ""), dados.get("matricula", ""),
            operador=(usuario or {}).get("nome", ""),
        )
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, "evento": evento}), 201


@blueprint.route("/api/turmas")
@perfil_obrigatorio(*PERFIS_PORTARIA)
def api_turmas():
    return jsonify(cadastro_alunos.turmas_no_escopo())


# ──────────────────────────────────────────────────────────────
# API — perfil do aluno
# ──────────────────────────────────────────────────────────────

@blueprint.route("/api/aluno/<int:aluno_id>/historico")
@perfil_obrigatorio(*PERFIS_PORTARIA)
def api_historico_aluno(aluno_id: int):
    try:
        dados = pontualidade.historico_aluno(aluno_id, apenas_atrasos=request.args.get("todos") != "1")
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 404
    return jsonify({"ok": True, **dados})


# ──────────────────────────────────────────────────────────────
# API — dashboard / coordenação
# ──────────────────────────────────────────────────────────────

@blueprint.route("/api/resumo-hoje")
@perfil_obrigatorio(*PERFIS_PORTARIA)
def api_resumo_hoje():
    """Só números (sem nomes) — usado no resumo do Painel do Porteiro."""
    return jsonify(pontualidade.resumo_hoje())


@blueprint.route("/api/dashboard")
@perfil_obrigatorio(*PERFIS_COORDENACAO)
def api_dashboard():
    """Query: ano, mes."""
    hoje = date.today()
    ano = request.args.get("ano", hoje.year, type=int)
    mes = request.args.get("mes", hoje.month, type=int)
    return jsonify(pontualidade.dashboard_mensal(ano, mes))


# ──────────────────────────────────────────────────────────────
# API — configuração (regras de horário + reincidência)
# ──────────────────────────────────────────────────────────────

@blueprint.route("/api/configuracao")
@perfil_obrigatorio(*PERFIS_COORDENACAO)
def api_config_ler():
    return jsonify(pontualidade.carregar_config())


@blueprint.route("/api/configuracao", methods=["POST"])
@perfil_obrigatorio(*PERFIS_COORDENACAO)
def api_config_salvar():
    """Body: {regras: [...], reincidencia: {...}}."""
    dados = request.get_json(force=True) or {}
    erros = pontualidade.validar_regras(dados.get("regras", []))
    if erros:
        return jsonify({"ok": False, "erro": " ".join(erros)}), 400

    reincidencia = dados.get("reincidencia", {})
    if not isinstance(reincidencia.get("minimo_atrasos"), int) or reincidencia["minimo_atrasos"] < 1:
        return jsonify({"ok": False, "erro": "O número mínimo de atrasos deve ser um inteiro maior que zero."}), 400
    if reincidencia.get("condicao") not in ("mais_de", "igual_ou_mais_de"):
        return jsonify({"ok": False, "erro": "Condição de reincidência inválida."}), 400
    if reincidencia.get("periodo") not in ("semana", "mes"):
        return jsonify({"ok": False, "erro": "Período de reincidência inválido."}), 400

    pontualidade.salvar_config({"regras": dados["regras"], "reincidencia": reincidencia})
    return jsonify({"ok": True})
