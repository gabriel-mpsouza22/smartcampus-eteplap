"""
Cadastro único de alunos
------------------------
Antes, cada módulo que lidava com alunos tinha sua própria cópia dos dados:
Ocorrências mantinha sua tabela própria, e a Biblioteca simplesmente digitava
nome/turma/curso como texto livre a cada empréstimo — sem nenhum vínculo com
o cadastro de Ocorrências, gerando nomes duplicados, digitados diferente
(ex: "João Silva" vs "joao silva") e sem histórico consolidado.

Este módulo centraliza o CRUD de alunos numa única tabela ("alunos") no
SCEDS. Qualquer módulo do sistema — Ocorrências, Biblioteca, Prevenção de
Evasão, e outros que vierem — usa estas mesmas funções para buscar, criar
e consultar alunos. Um aluno cadastrado em qualquer lugar do sistema
aparece automaticamente em todos os outros.

Série e curso nunca são digitados livremente: são sempre derivados da
turma escolhida, a partir da lista fixa em core/turmas.json — isso evita
que o mesmo aluno acabe com "Redes" num cadastro e "redes" (minúsculo) em
outro.
"""

import json
from pathlib import Path

BASE_CORE = Path(__file__).resolve().parent
CAMINHO_TURMAS = BASE_CORE / "turmas.json"


def _carregar_config() -> dict:
    from core.config_path import carregar_config
    return carregar_config(BASE_CORE.parent)


def _get_db():
    import sys
    sys.path.insert(0, str(BASE_CORE.parent))
    from sceds import SCEDS
    cfg = _carregar_config()
    db = SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")
    # Auto-evolução de schema: instalações feitas antes da funcionalidade
    # de avanço de ano letivo não têm a coluna "status". Em vez de exigir
    # que o cliente rode uma migração manual, garantimos a coluna aqui,
    # de forma idempotente, toda vez que o banco é aberto.
    db.adicionar_coluna_se_ausente("alunos", {"nome": "status", "tipo": "TEXTO", "modificadores": []})
    db.adicionar_coluna_se_ausente("alunos", {"nome": "matricula", "tipo": "TEXTO", "modificadores": []})
    return db


def carregar_turmas() -> list[dict]:
    """Carrega a lista fixa de turmas (turma → série + curso)."""
    with open(CAMINHO_TURMAS, encoding="utf-8") as f:
        return json.load(f)["turmas"]


def turma_info(turma: str) -> dict | None:
    """Retorna {turma, serie, curso} para uma turma válida, ou None."""
    return next((t for t in carregar_turmas() if t["turma"] == turma), None)


def turmas_no_escopo() -> list[dict]:
    """
    Como carregar_turmas(), mas já filtrada pelo escopo de turno do
    usuário logado — para preencher <select> de turma nas telas: uma
    coordenadora restrita ao Integral nunca deve sequer VER a opção de
    escolher uma turma da Noite, não só ter os resultados escondidos
    depois de escolhida.
    """
    escopo = _escopo_turno_da_requisicao()
    turmas = carregar_turmas()
    if not escopo:
        return turmas
    return [t for t in turmas if t.get("turno") in escopo]


def _completar(aluno: dict) -> dict:
    aluno.setdefault("serie", "—")
    aluno.setdefault("turma", "—")
    aluno.setdefault("curso", "—")
    aluno.setdefault("status", "ativo")
    aluno.setdefault("matricula", "")
    info = turma_info(aluno["turma"])
    aluno["turno_resolvido"] = info.get("turno") if info else None
    return aluno


def _escopo_turno_da_requisicao() -> set[str] | None:
    """
    Resolve o escopo de turno do usuário logado nesta requisição, se
    houver um (fora de um request Flask — scripts, mock data, wizard —
    isso simplesmente não se aplica e retorna None, sem restringir nada).
    Retorna None quando o usuário pode ver todos os turnos (inclusive
    quando não há usuário logado, ex.: rotas públicas), ou um conjunto
    de nomes de turno quando o acesso deve ser restrito.
    """
    try:
        from core.auth import usuario_logado
        usuario = usuario_logado()
    except Exception:
        return None
    if not usuario:
        return None
    escopo = usuario.get("escopo_turno") or ["todos"]
    if "todos" in escopo:
        return None
    return set(escopo)


def _turno_por_turma() -> dict[str, str]:
    """Mapa turma → turno. Usado por outros módulos (dashboard, monitoramento)
    para filtrar registros que só guardam o nome da turma (ex.: 'aluno_turma'
    em ocorrências/saídas), não o dict completo do aluno."""
    return {t["turma"]: t.get("turno") for t in carregar_turmas()}


def _filtrar_por_escopo_turno(alunos: list[dict]) -> list[dict]:
    escopo = _escopo_turno_da_requisicao()
    if not escopo:
        return alunos
    return [a for a in alunos if a.get("turno_resolvido") in escopo]


def buscar(busca: str = "", turma: str = "", incluir_formados: bool = False,
           db=None, limite: int | None = None) -> list[dict]:
    """
    Busca alunos no cadastro único.
    busca            — pesquisa parcial por nome OU matrícula (prefixo
                       exato), case-insensitive. Matrícula tem prioridade:
                       se o termo bater com uma matrícula, esse resultado
                       vem primeiro (matrícula é identificador mais
                       confiável que nome, ver core/pontualidade.py).
    turma            — filtro exato de turma
    incluir_formados — por padrão, alunos já concluídos/formados (ver
                       core/promocoes.py) não aparecem nas listagens do
                       dia a dia (matrícula, ocorrências, biblioteca…),
                       para não confundir a secretaria com quem já saiu
                       da escola. Passe True para telas que precisam do
                       histórico completo.

    Escopo de turno: se o usuário logado tem um cargo restrito a um ou
    mais turnos (ex.: "Integral"), alunos de outros turnos nunca
    aparecem aqui — nem em Ocorrências, Biblioteca, Evasão, Pontualidade
    ou Saídas, já que todos usam esta mesma função.
    """
    db = db or _get_db()
    alunos = db.buscar("alunos", ordenar_por="nome")

    if turma:
        alunos = [a for a in alunos if a.get("turma") == turma]

    if busca:
        termo = busca.strip().lower()
        por_matricula = [a for a in alunos if termo and a.get("matricula", "").lower().startswith(termo)]
        por_nome = [a for a in alunos if termo in a.get("nome", "").lower() and a not in por_matricula]
        alunos = por_matricula + por_nome

    alunos = [_completar(a) for a in alunos]
    alunos = _filtrar_por_escopo_turno(alunos)

    if not incluir_formados:
        alunos = [a for a in alunos if a.get("status", "ativo") != "formado"]

    if limite:
        alunos = alunos[:limite]
    return alunos


def buscar_um(aluno_id: int, db=None) -> dict | None:
    db = db or _get_db()
    aluno = db.buscar_um("alunos", onde={"id": aluno_id})
    if not aluno:
        return None
    aluno = _completar(aluno)
    # Mesmo por ID direto, um aluno fora do escopo de turno do usuário
    # logado não deve ser acessível — sem essa checagem, dava pra
    # contornar o filtro de listagem simplesmente sabendo o ID.
    if not _filtrar_por_escopo_turno([aluno]):
        return None
    return aluno


def criar(nome: str, turma: str, matricula: str = "", db=None) -> dict:
    """
    Cria um aluno no cadastro único. Lança ValueError com mensagem amigável
    se os dados forem inválidos (usada diretamente em respostas de API).
    matricula é opcional — nem toda interação (ex.: primeiro atraso
    registrado na portaria) tem essa informação disponível na hora.
    """
    nome = (nome or "").strip()
    turma = (turma or "").strip()
    matricula = (matricula or "").strip()
    if not nome or not turma:
        raise ValueError("Preencha o nome e selecione a turma.")

    info = turma_info(turma)
    if not info:
        raise ValueError("Turma inválida. Selecione uma das opções da lista.")

    db = db or _get_db()
    registro = db.inserir("alunos", {
        "nome":      nome,
        "serie":     info["serie"],
        "turma":     info["turma"],
        "curso":     info["curso"],
        "matricula": matricula,
    })
    return registro


def atualizar(aluno_id: int, nome: str, turma: str, matricula: str | None = None, db=None) -> dict:
    """
    Atualiza nome e/ou turma de um aluno já cadastrado. Série e curso são
    sempre recalculados a partir da turma escolhida (nunca digitados livremente).
    matricula: passe None para não alterar o valor já cadastrado.
    Lança ValueError com mensagem amigável se os dados forem inválidos.
    """
    nome = (nome or "").strip()
    turma = (turma or "").strip()
    if not nome or not turma:
        raise ValueError("Preencha o nome e selecione a turma.")

    info = turma_info(turma)
    if not info:
        raise ValueError("Turma inválida. Selecione uma das opções da lista.")

    db = db or _get_db()
    if not db.buscar_um("alunos", onde={"id": aluno_id}):
        raise ValueError("Aluno não encontrado.")

    novos_dados = {
        "nome":  nome,
        "serie": info["serie"],
        "turma": info["turma"],
        "curso": info["curso"],
    }
    if matricula is not None:
        novos_dados["matricula"] = matricula.strip()

    db.atualizar("alunos", novos_dados, onde={"id": aluno_id})

    return buscar_um(aluno_id, db=db)


def remover(aluno_id: int, db=None) -> bool:
    db = db or _get_db()
    if not db.buscar_um("alunos", onde={"id": aluno_id}):
        return False
    db.deletar("alunos", onde={"id": aluno_id})
    return True
