
import json
from pathlib import Path
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request

blueprint = Blueprint("ocorrencias", __name__,
                      template_folder="../../templates/ocorrencias")

from core.auth import perfil_obrigatorio, login_obrigatorio

BASE = Path(__file__).resolve().parent


TIPOS = [
    {"id": "elogio",              "nome": "Elogio",                "cor": "verde",    "severidade": 0},
    {"id": "advertencia_verbal",  "nome": "Advertência Verbal",    "cor": "amarelo",  "severidade": 1},
    {"id": "advertencia_escrita", "nome": "Advertência Escrita",   "cor": "laranja",  "severidade": 2},
    {"id": "comunicado_pais",     "nome": "Comunicado aos Pais",   "cor": "azul",     "severidade": 2},
    {"id": "suspensao",           "nome": "Suspensão",             "cor": "vermelho", "severidade": 3},
    {"id": "outro",               "nome": "Outro",                 "cor": "cinza",    "severidade": 1},
]
TIPOS_MAP = {t["id"]: t for t in TIPOS}
DIAS_JANELA_ALERTA = 30
LIMITE_OCORRENCIAS_ALERTA = 3

TIPO_ALIASES = {
    "advertencia verbal":    "advertencia_verbal",
    "advertência verbal":    "advertencia_verbal",
    "advertencia escrita":   "advertencia_escrita",
    "advertência escrita":   "advertencia_escrita",
    "comunicado aos pais":   "comunicado_pais",
    "comunicado pais":       "comunicado_pais",
    "suspensão":             "suspensao",
}


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    cfg = json.load(open(BASE.parent.parent / "core" / "config.json", encoding="utf-8"))
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

def normalizar_tipo(tipo_bruto: str) -> str:
    """
    Normaliza o campo 'tipo' de uma ocorrência para o id canônico.
    Lida com registros antigos salvos com espaço/acento em vez do id correto.
    """
    chave = (tipo_bruto or "").strip().lower()
    if chave in TIPOS_MAP:
        return chave
    if chave in TIPO_ALIASES:
        return TIPO_ALIASES[chave]
    tentativa = chave.replace(" ", "_")
    return tentativa if tentativa in TIPOS_MAP else chave

def _tipo_info(tipo_bruto: str) -> dict:
    tipo_id = normalizar_tipo(tipo_bruto)
    return TIPOS_MAP.get(tipo_id, {"id": tipo_id, "nome": tipo_bruto or tipo_id, "cor": "cinza", "severidade": 1})

def _e_elogio(tipo_bruto: str) -> bool:
    return normalizar_tipo(tipo_bruto) == "elogio"

def _carregar_turmas() -> list[dict]:
    """Carrega a lista fixa de turmas (turma → série + curso) do arquivo de configuração."""
    with open(BASE / "turmas.json", encoding="utf-8") as f:
        return json.load(f)["turmas"]

def _turma_info(turma: str) -> dict | None:
    """Retorna {turma, serie, curso} para uma turma válida, ou None se não existir na lista."""
    return next((t for t in _carregar_turmas() if t["turma"] == turma), None)

def _contar_ocorrencias_recentes(db, aluno_id: int) -> int:
    """Conta ocorrências (exceto elogio) dos últimos N dias para um aluno."""
    limite = datetime.now() - timedelta(days=DIAS_JANELA_ALERTA)
    todas = db.buscar("ocorrencias", onde={"aluno_id": aluno_id})
    recentes = [
        o for o in todas
        if not _e_elogio(o.get("tipo", "")) and datetime.fromisoformat(o["data_hora"]) >= limite
    ]
    return len(recentes)


@blueprint.route("/")
@perfil_obrigatorio("coordenadora", "admin")
def index():
    return render_template("ocorrencias/index.html", tipos=TIPOS, turmas=_carregar_turmas())


@blueprint.route("/api/turmas")
@login_obrigatorio
def api_turmas():
    return jsonify(_carregar_turmas())


@blueprint.route("/api/tipos")
@login_obrigatorio
def api_tipos():
    return jsonify(TIPOS)


@blueprint.route("/api/status")
@perfil_obrigatorio("coordenadora", "admin")
def api_status():
    db = _get_db()
    todas = db.buscar("ocorrencias")
    alunos = db.buscar("alunos_ocorrencias")

    hoje = datetime.now().date()
    inicio_mes = hoje.replace(day=1).isoformat()

    do_mes = [o for o in todas if o.get("data_hora", "")[:10] >= inicio_mes]
    elogios_mes = [o for o in do_mes if _e_elogio(o.get("tipo", ""))]

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
    busca = request.args.get("busca", "").strip().lower()
    db = _get_db()
    alunos = db.buscar("alunos_ocorrencias", ordenar_por="nome")

    if busca:
        alunos = [a for a in alunos if busca in a.get("nome", "").lower()]

    for a in alunos:
        a.setdefault("serie", "—")
        a.setdefault("turma", "—")
        a.setdefault("curso", "—")
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

    if not nome or not turma:
        return jsonify({"ok": False, "erro": "Preencha o nome e selecione a turma."}), 400

    info_turma = _turma_info(turma)
    if not info_turma:
        return jsonify({"ok": False, "erro": "Turma inválida. Selecione uma das opções da lista."}), 400

    db = _get_db()
    registro = db.inserir("alunos_ocorrencias", {
        "nome":  nome,
        "serie": info_turma["serie"],
        "turma": info_turma["turma"],
        "curso": info_turma["curso"],
    })
    return jsonify({"ok": True, "aluno": registro}), 201

@blueprint.route("/api/alunos/<int:aluno_id>/ficha")
@perfil_obrigatorio("coordenadora", "admin")
def api_ficha_aluno(aluno_id: int):
    """Retorna dados do aluno + histórico completo de ocorrências, mais recente primeiro."""
    db = _get_db()
    aluno = db.buscar_um("alunos_ocorrencias", onde={"id": aluno_id})
    if not aluno:
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404

    ocorrencias = db.buscar("ocorrencias", onde={"aluno_id": aluno_id}, ordenar_por="data_hora")
    ocorrencias = list(reversed(ocorrencias))
    for o in ocorrencias:
        o["tipo_info"] = _tipo_info(o.get("tipo", "outro"))

    aluno.setdefault("serie", "—")
    aluno.setdefault("turma", "—")
    aluno.setdefault("curso", "—")

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
    if not db.buscar_um("alunos_ocorrencias", onde={"id": aluno_id}):
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404
    db.deletar("ocorrencias", onde={"aluno_id": aluno_id})
    db.deletar("alunos_ocorrencias", onde={"id": aluno_id})
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
        ocorrencias = [o for o in ocorrencias if normalizar_tipo(o.get("tipo", "")) == tipo]

    if dias:
        limite = (datetime.now() - timedelta(days=dias)).isoformat()
        ocorrencias = [o for o in ocorrencias if o.get("data_hora", "") >= limite]

    alunos_map = {a["id"]: a for a in db.buscar("alunos_ocorrencias")}
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
        o["tipo_info"]   = _tipo_info(o.get("tipo", "outro"))
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

    if tipo not in TIPOS_MAP:
        return jsonify({"ok": False, "erro": "Tipo de ocorrência inválido."}), 400

    db = _get_db()
    aluno = db.buscar_um("alunos_ocorrencias", onde={"id": aluno_id})
    if not aluno:
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404

    registro = db.inserir("ocorrencias", {
        "aluno_id":    aluno_id,
        "tipo":        tipo,
        "envolvido_2": envolvido2,
        "descricao":   descricao,
        "data_hora":   datetime.now().isoformat(),
    })
    registro["tipo_info"]  = _tipo_info(tipo)
    registro["aluno_nome"] = aluno.get("nome", "(sem nome)")

    novo_total_recente = _contar_ocorrencias_recentes(db, aluno_id)

    return jsonify({
        "ok": True,
        "ocorrencia": registro,
        "aluno_em_alerta": novo_total_recente >= LIMITE_OCORRENCIAS_ALERTA,
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
