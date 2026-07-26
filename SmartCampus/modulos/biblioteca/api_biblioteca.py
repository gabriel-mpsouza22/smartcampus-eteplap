
import json
from pathlib import Path
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, jsonify, request
from core.auth import login_obrigatorio, usuario_logado

blueprint = Blueprint("biblioteca", __name__,
                      template_folder="../../templates/biblioteca")

BASE = Path(__file__).resolve().parent
DIAS_EMPRESTIMO_PADRAO = 7


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    cfg = json.load(open(BASE.parent.parent / "core" / "config.json", encoding="utf-8"))
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

def _livro_disponivel(db, livro_id: int) -> bool:
    """Um livro está disponível se não há empréstimo ativo (devolvido=False) para ele."""
    emprestimos = db.buscar("emprestimos", onde={"livro_id": livro_id})
    return not any(not e.get("devolvido") for e in emprestimos)

def _enriquecer_livro(db, livro: dict) -> dict:
    """Adiciona campo 'disponivel' e, se emprestado, dados do empréstimo ativo."""
    emprestimos_ativos = [
        e for e in db.buscar("emprestimos", onde={"livro_id": livro["id"]})
        if not e.get("devolvido")
    ]
    livro["disponivel"] = len(emprestimos_ativos) == 0
    livro["emprestimo_ativo"] = emprestimos_ativos[0] if emprestimos_ativos else None
    if livro["emprestimo_ativo"]:
        hoje = date.today().isoformat()
        livro["emprestimo_ativo"]["atrasado"] = livro["emprestimo_ativo"]["data_prevista_devolucao"] < hoje
    return livro


@blueprint.route("/")
@login_obrigatorio
def index():
    return render_template("biblioteca/index.html", hoje=date.today().isoformat())


@blueprint.route("/api/status")
@login_obrigatorio
def api_status():
    db     = _get_db()
    livros = db.buscar("livros")
    emprestimos = db.buscar("emprestimos")

    ativos    = [e for e in emprestimos if not e.get("devolvido")]
    hoje      = date.today().isoformat()
    atrasados = [e for e in ativos if e["data_prevista_devolucao"] < hoje]

    return jsonify({
        "total_livros":     len(livros),
        "total_emprestados":len(ativos),
        "total_disponiveis":len(livros) - len(ativos),
        "total_atrasados":  len(atrasados),
    })


@blueprint.route("/api/livros")
@login_obrigatorio
def api_listar_livros():
    """
    Query params:
      busca      — pesquisa em nome/autor/genero (case-insensitive, parcial)
      genero     — filtro exato
      prateleira — filtro exato
      status     — 'disponivel' | 'emprestado' | (vazio = todos)
    """
    db     = _get_db()
    busca  = request.args.get("busca", "").strip().lower()
    genero = request.args.get("genero", "").strip()
    prat   = request.args.get("prateleira", "").strip()
    status = request.args.get("status", "").strip()

    livros = db.buscar("livros", ordenar_por="nome")

    if genero:
        livros = [l for l in livros if l.get("genero") == genero]
    if prat:
        livros = [l for l in livros if l.get("prateleira") == prat]
    if busca:
        def bate(l):
            alvo = f"{l.get('nome','')} {l.get('autor','')} {l.get('genero','')}".lower()
            return busca in alvo
        livros = [l for l in livros if bate(l)]

    livros = [_enriquecer_livro(db, l) for l in livros]

    if status == "disponivel":
        livros = [l for l in livros if l["disponivel"]]
    elif status == "emprestado":
        livros = [l for l in livros if not l["disponivel"]]

    return jsonify(livros)

@blueprint.route("/api/generos")
@login_obrigatorio
def api_generos():
    """Retorna gêneros distintos já cadastrados, para autocomplete."""
    db = _get_db()
    livros = db.buscar("livros")
    generos = sorted({l["genero"] for l in livros if l.get("genero")})
    return jsonify(generos)

@blueprint.route("/api/prateleiras")
@login_obrigatorio
def api_prateleiras():
    """Retorna prateleiras distintas já cadastradas, para autocomplete."""
    db = _get_db()
    livros = db.buscar("livros")
    prateleiras = sorted({l["prateleira"] for l in livros if l.get("prateleira")})
    return jsonify(prateleiras)

@blueprint.route("/api/livros", methods=["POST"])
@login_obrigatorio
def api_cadastrar_livro():
    """
    Cadastra um ou mais exemplares do mesmo título de uma vez.
    Body: nome, autor, genero, prateleira, quantidade (opcional, padrão 1).

    Se quantidade > 1, cria N exemplares independentes, numerados no nome
    (ex: "Dom Casmurro 1", "Dom Casmurro 2", ...), cada um podendo ser
    emprestado separadamente dos demais.
    """
    dados = request.get_json(force=True)
    nome       = dados.get("nome", "").strip()
    autor      = dados.get("autor", "").strip()
    genero     = dados.get("genero", "").strip()
    prateleira = dados.get("prateleira", "").strip()

    if not nome or not autor:
        return jsonify({"ok": False, "erro": "Nome e autor são obrigatórios."}), 400

    try:
        quantidade = int(dados.get("quantidade", 1))
    except (TypeError, ValueError):
        quantidade = 1
    quantidade = max(1, min(quantidade, 200))

    db = _get_db()
    criados = []

    if quantidade == 1:
        criados.append(db.inserir("livros", {
            "nome": nome, "autor": autor, "genero": genero, "prateleira": prateleira,
        }))
    else:
        for i in range(1, quantidade + 1):
            criados.append(db.inserir("livros", {
                "nome": f"{nome} {i}", "autor": autor, "genero": genero, "prateleira": prateleira,
            }))

    return jsonify({"ok": True, "livros": criados, "quantidade": len(criados)}), 201

@blueprint.route("/api/livros/<int:livro_id>", methods=["PUT"])
@login_obrigatorio
def api_editar_livro(livro_id: int):
    db    = _get_db()
    livro = db.buscar_um("livros", onde={"id": livro_id})
    if not livro:
        return jsonify({"ok": False, "erro": "Livro não encontrado."}), 404

    dados = request.get_json(force=True)
    campos = {}
    for campo in ("nome", "autor", "genero", "prateleira"):
        if campo in dados:
            valor = dados[campo].strip() if isinstance(dados[campo], str) else dados[campo]
            campos[campo] = valor

    if "nome" in campos and not campos["nome"]:
        return jsonify({"ok": False, "erro": "Nome não pode ficar vazio."}), 400
    if "autor" in campos and not campos["autor"]:
        return jsonify({"ok": False, "erro": "Autor não pode ficar vazio."}), 400

    db.atualizar("livros", campos, onde={"id": livro_id})
    return jsonify({"ok": True})

@blueprint.route("/api/livros/<int:livro_id>", methods=["DELETE"])
@login_obrigatorio
def api_remover_livro(livro_id: int):
    db    = _get_db()
    livro = db.buscar_um("livros", onde={"id": livro_id})
    if not livro:
        return jsonify({"ok": False, "erro": "Livro não encontrado."}), 404

    if not _livro_disponivel(db, livro_id):
        return jsonify({"ok": False,
                        "erro": "Não é possível remover: livro está emprestado no momento."}), 409

    db.deletar("livros", onde={"id": livro_id})
    return jsonify({"ok": True})

@blueprint.route("/api/livros/lote", methods=["DELETE"])
@login_obrigatorio
def api_remover_livros_lote():
    """
    Remove vários exemplares de uma vez (usado pelo botão "desfazer" após
    um cadastro de múltiplos exemplares). Body: { "ids": [1, 2, 3] }.
    Exemplares já emprestados são pulados, não bloqueiam os demais.
    """
    dados = request.get_json(force=True)
    ids = dados.get("ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "erro": "Informe a lista de ids em 'ids'."}), 400

    db = _get_db()
    removidos = []
    bloqueados = []

    for livro_id in ids:
        if not db.buscar_um("livros", onde={"id": livro_id}):
            continue
        if _livro_disponivel(db, livro_id):
            db.deletar("livros", onde={"id": livro_id})
            removidos.append(livro_id)
        else:
            bloqueados.append(livro_id)

    return jsonify({"ok": True, "removidos": removidos, "bloqueados": bloqueados})


@blueprint.route("/api/emprestimos")
@login_obrigatorio
def api_listar_emprestimos():
    """
    Query params:
      status — 'ativos' | 'atrasados' | 'historico' | (vazio = ativos)
      busca  — pesquisa por nome do aluno
    """
    db     = _get_db()
    status = request.args.get("status", "ativos")
    busca  = request.args.get("busca", "").strip().lower()

    emprestimos = db.buscar("emprestimos", ordenar_por="data_prevista_devolucao")
    hoje = date.today().isoformat()

    if status == "ativos":
        emprestimos = [e for e in emprestimos if not e.get("devolvido")]
    elif status == "atrasados":
        emprestimos = [e for e in emprestimos
                       if not e.get("devolvido") and e["data_prevista_devolucao"] < hoje]
    elif status == "historico":
        emprestimos = [e for e in emprestimos if e.get("devolvido")]

    if busca:
        emprestimos = [e for e in emprestimos if busca in e.get("aluno_nome", "").lower()]

    livros_map = {l["id"]: l for l in db.buscar("livros")}
    for e in emprestimos:
        livro = livros_map.get(e.get("livro_id"), {})
        e["livro_nome"]  = livro.get("nome", "— livro removido —")
        e["livro_autor"] = livro.get("autor", "")
        e["atrasado"]    = (not e.get("devolvido")) and e["data_prevista_devolucao"] < hoje
        if e["atrasado"]:
            dias_atraso = (date.today() - date.fromisoformat(e["data_prevista_devolucao"])).days
            e["dias_atraso"] = dias_atraso

    return jsonify(emprestimos)

@blueprint.route("/api/emprestimos", methods=["POST"])
@login_obrigatorio
def api_novo_emprestimo():
    """
    Body JSON:
      livro_id, aluno_nome, aluno_turma, aluno_curso, dias (opcional, padrão 7)
    """
    dados = request.get_json(force=True)
    livro_id     = dados.get("livro_id")
    aluno_nome   = dados.get("aluno_nome", "").strip()
    aluno_turma  = dados.get("aluno_turma", "").strip()
    aluno_curso  = dados.get("aluno_curso", "").strip()
    dias         = dados.get("dias", DIAS_EMPRESTIMO_PADRAO)

    if not all([livro_id, aluno_nome, aluno_turma, aluno_curso]):
        return jsonify({"ok": False, "erro": "Preencha livro, nome, turma e curso do aluno."}), 400

    try:
        dias = int(dias)
        if dias < 1: dias = DIAS_EMPRESTIMO_PADRAO
    except (TypeError, ValueError):
        dias = DIAS_EMPRESTIMO_PADRAO

    db    = _get_db()
    livro = db.buscar_um("livros", onde={"id": livro_id})
    if not livro:
        return jsonify({"ok": False, "erro": "Livro não encontrado."}), 404

    if not _livro_disponivel(db, livro_id):
        emp_atual = next(
            (e for e in db.buscar("emprestimos", onde={"livro_id": livro_id}) if not e.get("devolvido")),
            None
        )
        nome_atual = emp_atual.get("aluno_nome", "outro aluno") if emp_atual else "outro aluno"
        return jsonify({"ok": False,
                        "erro": f"'{livro['nome']}' já está emprestado para {nome_atual}."}), 409

    hoje_data = date.today()
    prevista  = hoje_data + timedelta(days=dias)

    registro = db.inserir("emprestimos", {
        "livro_id":                livro_id,
        "aluno_nome":               aluno_nome,
        "aluno_turma":              aluno_turma,
        "aluno_curso":              aluno_curso,
        "data_emprestimo":          hoje_data.isoformat(),
        "data_prevista_devolucao":  prevista.isoformat(),
        "devolvido":                False,
        "data_devolucao":           None,
    })
    return jsonify({"ok": True, "emprestimo": registro}), 201

@blueprint.route("/api/emprestimos/<int:emprestimo_id>/devolver", methods=["POST"])
@login_obrigatorio
def api_devolver(emprestimo_id: int):
    db  = _get_db()
    emp = db.buscar_um("emprestimos", onde={"id": emprestimo_id})
    if not emp:
        return jsonify({"ok": False, "erro": "Empréstimo não encontrado."}), 404
    if emp.get("devolvido"):
        return jsonify({"ok": False, "erro": "Este empréstimo já foi devolvido."}), 400

    db.atualizar("emprestimos",
                 {"devolvido": True, "data_devolucao": date.today().isoformat()},
                 onde={"id": emprestimo_id})
    return jsonify({"ok": True})

@blueprint.route("/api/emprestimos/<int:emprestimo_id>/renovar", methods=["POST"])
@login_obrigatorio
def api_renovar(emprestimo_id: int):
    """Estende a data prevista de devolução por mais N dias (padrão 7)."""
    db  = _get_db()
    emp = db.buscar_um("emprestimos", onde={"id": emprestimo_id})
    if not emp:
        return jsonify({"ok": False, "erro": "Empréstimo não encontrado."}), 404
    if emp.get("devolvido"):
        return jsonify({"ok": False, "erro": "Este empréstimo já foi devolvido."}), 400

    dados = request.get_json(silent=True) or {}
    dias  = dados.get("dias", DIAS_EMPRESTIMO_PADRAO)
    try:
        dias = int(dias)
    except (TypeError, ValueError):
        dias = DIAS_EMPRESTIMO_PADRAO

    base = max(date.today(), date.fromisoformat(emp["data_prevista_devolucao"]))
    nova_data = base + timedelta(days=dias)

    db.atualizar("emprestimos",
                 {"data_prevista_devolucao": nova_data.isoformat()},
                 onde={"id": emprestimo_id})
    return jsonify({"ok": True, "nova_data": nova_data.isoformat()})