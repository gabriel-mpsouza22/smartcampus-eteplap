
import json
from pathlib import Path
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request

blueprint = Blueprint("ocorrencias", __name__,
                      template_folder="../../templates/ocorrencias")

from core.auth import perfil_obrigatorio, login_obrigatorio
from core.notificacoes import notificar_se_ausente
from core import alunos as cadastro_alunos
from core import tipos_ocorrencia as tipos_mod

BASE = Path(__file__).resolve().parent

DIAS_JANELA_ALERTA = 30
LIMITE_OCORRENCIAS_ALERTA = 3


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    from core.config_path import carregar_config
    cfg = carregar_config(BASE.parent.parent)
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

def normalizar_tipo(tipo_bruto: str, db=None) -> str:
    """Normaliza o campo 'tipo' de uma ocorrência para o tipo_id canônico
    da régua desta escola. Lida com registros antigos salvos com
    espaço/acento em vez do id correto."""
    return tipos_mod.normalizar_tipo(tipo_bruto, db=db)

def _tipo_info(tipo_bruto: str, db=None) -> dict:
    return tipos_mod.tipo_info(normalizar_tipo(tipo_bruto, db=db), db=db)

def _e_elogio(tipo_bruto: str, db=None) -> bool:
    return tipos_mod.e_elogio(tipo_bruto, db=db)

def _carregar_turmas() -> list[dict]:
    """Lista fixa de turmas (turma → série + curso), compartilhada via core.alunos."""
    return cadastro_alunos.turmas_no_escopo()

def _turma_info(turma: str) -> dict | None:
    """Retorna {turma, serie, curso} para uma turma válida, ou None se não existir na lista."""
    return cadastro_alunos.turma_info(turma)

def _contar_ocorrencias_recentes(db, aluno_id: int) -> int:
    """Conta ocorrências (exceto elogio) dos últimos N dias para um aluno."""
    limite = datetime.now() - timedelta(days=DIAS_JANELA_ALERTA)
    todas = db.buscar("ocorrencias", onde={"aluno_id": aluno_id})
    recentes = [
        o for o in todas
        if not _e_elogio(o.get("tipo", ""), db=db) and datetime.fromisoformat(o["data_hora"]) >= limite
    ]
    return len(recentes)


@blueprint.route("/")
@perfil_obrigatorio("coordenadora", "admin")
def index():
    db = _get_db()
    return render_template("ocorrencias/index.html", tipos=tipos_mod.listar(db=db), turmas=_carregar_turmas())


@blueprint.route("/api/turmas")
@login_obrigatorio
def api_turmas():
    return jsonify(_carregar_turmas())


@blueprint.route("/api/tipos")
@login_obrigatorio
def api_tipos():
    return jsonify(tipos_mod.listar())


@blueprint.route("/configurar-tipos")
@perfil_obrigatorio("coordenadora", "admin")
def pagina_configurar_tipos():
    return render_template("ocorrencias/configurar_tipos.html")


@blueprint.route("/api/tipos", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_criar_tipo():
    """Body: nome, cor, severidade (0 a 3)."""
    dados = request.get_json(force=True) or {}
    try:
        tipo = tipos_mod.criar(dados.get("nome", ""), dados.get("cor", ""), dados.get("severidade", 1))
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, "tipo": tipo}), 201


@blueprint.route("/api/tipos/<tipo_id>", methods=["PUT"])
@perfil_obrigatorio("coordenadora", "admin")
def api_atualizar_tipo(tipo_id: str):
    """Body: nome?, cor?, severidade?, ordem? (qualquer subconjunto)."""
    dados = request.get_json(force=True) or {}
    try:
        tipo = tipos_mod.atualizar(
            tipo_id,
            nome=dados.get("nome"), cor=dados.get("cor"),
            severidade=dados.get("severidade"), ordem=dados.get("ordem"),
        )
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True, "tipo": tipo})


@blueprint.route("/api/tipos/<tipo_id>", methods=["DELETE"])
@perfil_obrigatorio("coordenadora", "admin")
def api_remover_tipo(tipo_id: str):
    try:
        removido = tipos_mod.remover(tipo_id)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    if not removido:
        return jsonify({"ok": False, "erro": "Tipo não encontrado."}), 404
    return jsonify({"ok": True})


@blueprint.route("/api/status")
@perfil_obrigatorio("coordenadora", "admin")
def api_status():
    db = _get_db()
    todas = db.buscar("ocorrencias")
    alunos = cadastro_alunos.buscar(db=db)
    ids_no_escopo = {a["id"] for a in alunos}
    todas = [o for o in todas if o.get("aluno_id") in ids_no_escopo]

    hoje = datetime.now().date()
    inicio_mes = hoje.replace(day=1).isoformat()

    do_mes = [o for o in todas if o.get("data_hora", "")[:10] >= inicio_mes]
    elogios_mes = [o for o in do_mes if _e_elogio(o.get("tipo", ""), db=db)]

    em_alerta = 0
    for aluno in alunos:
        if _contar_ocorrencias_recentes(db, aluno["id"]) >= LIMITE_OCORRENCIAS_ALERTA:
            em_alerta += 1

    return jsonify({
        "total_alunos_cadastrados": len(alunos),
        "ocorrencias_mes":          len(do_mes),
        "elogios_mes":              len(elogios_mes),
        "alunos_em_alerta":         em_alerta,
    })


@blueprint.route("/api/alunos")
@perfil_obrigatorio("coordenadora", "admin")
def api_buscar_alunos():
    """Query: busca (nome parcial, para autocomplete)."""
    busca = request.args.get("busca", "").strip()
    db = _get_db()
    alunos = cadastro_alunos.buscar(busca=busca, db=db)

    for a in alunos:
        a["ocorrencias_recentes"] = _contar_ocorrencias_recentes(db, a["id"])
        a["em_alerta"] = a["ocorrencias_recentes"] >= LIMITE_OCORRENCIAS_ALERTA

    return jsonify(alunos[:20] if busca else alunos)

@blueprint.route("/api/alunos", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_cadastrar_aluno():
    """
    Body: nome, turma.
    Série e curso NÃO são mais digitados pelo usuário — são derivados
    automaticamente a partir da turma escolhida (lista fixa em turmas.json),
    garantindo que os dados fiquem sempre padronizados.
    """
    dados = request.get_json(force=True)
    nome  = dados.get("nome", "").strip()
    turma = dados.get("turma", "").strip()

    db = _get_db()
    try:
        registro = cadastro_alunos.criar(nome, turma, db=db)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400

    return jsonify({"ok": True, "aluno": registro}), 201

@blueprint.route("/api/alunos/<int:aluno_id>/ficha")
@perfil_obrigatorio("coordenadora", "admin")
def api_ficha_aluno(aluno_id: int):
    """Retorna dados do aluno + histórico completo de ocorrências, mais recente primeiro."""
    db = _get_db()
    aluno = cadastro_alunos.buscar_um(aluno_id, db=db)
    if not aluno:
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404

    ocorrencias = db.buscar("ocorrencias", onde={"aluno_id": aluno_id}, ordenar_por="data_hora")
    ocorrencias = list(reversed(ocorrencias))
    for o in ocorrencias:
        o["tipo_info"] = _tipo_info(o.get("tipo", "outro"), db=db)

    aluno["ocorrencias"] = ocorrencias
    aluno["total_ocorrencias"] = len(ocorrencias)
    aluno["ocorrencias_recentes"] = _contar_ocorrencias_recentes(db, aluno_id)
    aluno["em_alerta"] = aluno["ocorrencias_recentes"] >= LIMITE_OCORRENCIAS_ALERTA

    return jsonify({"ok": True, "aluno": aluno})

@blueprint.route("/api/alunos/<int:aluno_id>", methods=["DELETE"])
@perfil_obrigatorio("admin")
def api_remover_aluno(aluno_id: int):
    """Somente admin remove aluno (e seu histórico), para evitar exclusões acidentais."""
    db = _get_db()
    if not cadastro_alunos.buscar_um(aluno_id, db=db):
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404
    db.deletar("ocorrencias", onde={"aluno_id": aluno_id})
    db.deletar("alunos", onde={"id": aluno_id})
    return jsonify({"ok": True})


@blueprint.route("/api/ocorrencias")
@perfil_obrigatorio("coordenadora", "admin")
def api_listar_ocorrencias():
    """
    Query params:
      busca      — nome do aluno (parcial)
      tipo       — filtro por tipo
      dias       — janela em dias a partir de hoje (padrão: sem filtro = tudo)
    """
    db     = _get_db()
    busca  = request.args.get("busca", "").strip().lower()
    tipo   = request.args.get("tipo", "").strip()
    dias   = request.args.get("dias", type=int)

    ocorrencias = db.buscar("ocorrencias", ordenar_por="data_hora")
    ocorrencias = list(reversed(ocorrencias))

    if tipo:
        ocorrencias = [o for o in ocorrencias if normalizar_tipo(o.get("tipo", ""), db=db) == tipo]

    if dias:
        limite = (datetime.now() - timedelta(days=dias)).isoformat()
        ocorrencias = [o for o in ocorrencias if o.get("data_hora", "") >= limite]

    alunos_map = {a["id"]: a for a in cadastro_alunos.buscar(db=db)}
    resultado = []
    for o in ocorrencias:
        aluno = alunos_map.get(o.get("aluno_id"))
        if not aluno:
            continue
        nome_aluno = aluno.get("nome", "")
        if busca and busca not in nome_aluno.lower():
            continue
        o["aluno_nome"]  = nome_aluno or "(sem nome)"
        o["aluno_turma"] = aluno.get("turma", "—")
        o["aluno_curso"] = aluno.get("curso", "—")
        o["tipo_info"]   = _tipo_info(o.get("tipo", "outro"), db=db)
        resultado.append(o)

    return jsonify(resultado)

@blueprint.route("/api/ocorrencias", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_nova_ocorrencia():
    """Body: aluno_id, tipo, envolvido_2 (opcional), descricao."""
    dados      = request.get_json(force=True)
    aluno_id   = dados.get("aluno_id")
    tipo       = dados.get("tipo", "").strip()
    envolvido2 = dados.get("envolvido_2", "").strip()
    descricao  = dados.get("descricao", "").strip()

    if not aluno_id or not tipo or not descricao:
        return jsonify({"ok": False, "erro": "Selecione o aluno, o tipo e escreva a descrição."}), 400

    if tipo not in tipos_mod.mapa():
        return jsonify({"ok": False, "erro": "Tipo de ocorrência inválido."}), 400

    db = _get_db()
    aluno = cadastro_alunos.buscar_um(aluno_id, db=db)
    if not aluno:
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404

    registro = db.inserir("ocorrencias", {
        "aluno_id":    aluno_id,
        "tipo":        tipo,
        "envolvido_2": envolvido2,
        "descricao":   descricao,
        "data_hora":   datetime.now().isoformat(),
    })
    registro["tipo_info"]  = _tipo_info(tipo, db=db)
    registro["aluno_nome"] = aluno.get("nome", "(sem nome)")

    novo_total_recente = _contar_ocorrencias_recentes(db, aluno_id)
    aluno_em_alerta = novo_total_recente >= LIMITE_OCORRENCIAS_ALERTA

    if aluno_em_alerta:
        # notificar_se_ausente por aluno_id (não por ocorrência) — o alerta é
        # sobre o padrão de recorrência, não sobre este registro isolado; se
        # já existe um aviso pendente para esse aluno, não duplica a cada
        # nova ocorrência.
        notificar_se_ausente(
            modulo="ocorrencias", tipo="aluno_em_alerta", referencia_id=aluno_id,
            titulo=f"Aluno com ocorrências recorrentes — {registro['aluno_nome']}",
            mensagem=f"{novo_total_recente} ocorrências recentes.",
            url="/ocorrencias/", destinatario_tipo="perfil", destinatario_valor="admin",
        )

    return jsonify({
        "ok": True,
        "ocorrencia": registro,
        "aluno_em_alerta": aluno_em_alerta,
        "aluno_ocorrencias_recentes": novo_total_recente,
    }), 201

@blueprint.route("/api/ocorrencias/<int:numero>", methods=["DELETE"])
@perfil_obrigatorio("coordenadora", "admin")
def api_remover_ocorrencia(numero: int):
    db = _get_db()
    if not db.buscar_um("ocorrencias", onde={"numero": numero}):
        return jsonify({"ok": False, "erro": "Ocorrência não encontrada."}), 404
    db.deletar("ocorrencias", onde={"numero": numero})
    return jsonify({"ok": True})
