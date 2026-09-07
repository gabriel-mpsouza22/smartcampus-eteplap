"""
Avanço de ano letivo (promoção de alunos)
------------------------------------------
No fim do ano letivo, a secretaria/coordenação precisa mover a maior
parte dos alunos para a série seguinte, manter alguns retidos na
mesma turma, e formar quem concluiu a última série. Feito manualmente
(editando aluno por aluno na tela de cadastro), isso é lento e sujeito
a erro — e um erro aqui bagunça o ano letivo inteiro.

Este módulo:
  1. Sugere automaticamente para onde cada aluno deveria ir, a partir
     da lista fixa de turmas (mesma turma/curso, uma série acima).
  2. Aplica as decisões de uma turma inteira em uma única operação.
  3. Guarda um "lote" com o estado anterior de cada aluno afetado, para
     que a operação inteira possa ser desfeita com um clique — mesmo
     depois de fechada a tela, não só enquanto o aviso de sucesso está
     na tela.
"""

import json
from datetime import datetime

from core import alunos as cadastro_alunos

ACOES_VALIDAS = {"avancar", "reter", "concluir"}


def _get_db():
    return cadastro_alunos._get_db()


def _garantir_tabela_historico(db):
    if not db.tabela_existe("promocoes_historico"):
        db.criar_tabela("promocoes_historico", [
            {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
            {"nome": "executado_em", "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
            {"nome": "executado_por", "tipo": "TEXTO", "modificadores": []},
            {"nome": "turma_origem", "tipo": "TEXTO", "modificadores": []},
            {"nome": "quantidade", "tipo": "INTEIRO", "modificadores": ["NAO_NULO"]},
            {"nome": "resumo", "tipo": "TEXTO", "modificadores": []},
            # JSON serializado — lista com o registro completo de cada
            # aluno ANTES da alteração, para permitir desfazer o lote.
            {"nome": "estados_antes", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
            {"nome": "desfeito", "tipo": "BOOLEANO", "modificadores": []},
        ])


# ──────────────────────────────────────────────────────────────
# Sugestão automática de destino
# ──────────────────────────────────────────────────────────────

def _ordem_series(turmas: list[dict]) -> list[str]:
    """Ordem das séries pela primeira vez que aparecem em turmas.json (ordem pedagógica crescente)."""
    vistas: list[str] = []
    for t in turmas:
        if t["serie"] not in vistas:
            vistas.append(t["serie"])
    return vistas


def opcoes_proxima_turma(turma_atual: str, turmas: list[dict] | None = None) -> tuple[list[dict], bool]:
    """
    Retorna (candidatas, e_ultima_serie) para uma turma de origem.
    candidatas   — turmas da série seguinte que podem receber o aluno
                   (prioriza o mesmo curso; se nenhuma bater, mostra
                   todas as turmas da próxima série como alternativa).
    e_ultima_serie — True quando não há próxima série: o aluno aprovado
                   aqui conclui o curso em vez de avançar de turma.
    """
    turmas = turmas if turmas is not None else cadastro_alunos.carregar_turmas()
    info = cadastro_alunos.turma_info(turma_atual)
    if not info:
        return [], False

    ordem = _ordem_series(turmas)
    try:
        idx = ordem.index(info["serie"])
    except ValueError:
        return [], False

    if idx + 1 >= len(ordem):
        return [], True

    proxima_serie = ordem[idx + 1]
    candidatas = [t for t in turmas if t["serie"] == proxima_serie]
    mesmo_curso = [t for t in candidatas if t.get("curso") == info.get("curso")]
    return (mesmo_curso or candidatas), False


def montar_painel_turma(turma: str) -> dict:
    """Monta os dados para a tela de avanço: alunos ativos da turma + sugestão de destino."""
    info = cadastro_alunos.turma_info(turma)
    if not info:
        raise ValueError("Turma inválida.")

    turmas = cadastro_alunos.carregar_turmas()
    candidatas, ultima_serie = opcoes_proxima_turma(turma, turmas)
    sugestao = candidatas[0]["turma"] if len(candidatas) == 1 else (candidatas[0]["turma"] if candidatas else None)
    ambigua = len(candidatas) > 1

    alunos = cadastro_alunos.buscar(turma=turma)  # já exclui formados por padrão
    linhas = [
        {
            "id": a["id"],
            "nome": a["nome"],
            "acao_sugerida": "concluir" if ultima_serie else "avancar",
            "turma_sugerida": None if ultima_serie else sugestao,
        }
        for a in alunos
    ]

    return {
        "turma": turma,
        "serie": info["serie"],
        "curso": info["curso"],
        "ultima_serie": ultima_serie,
        "opcoes_turma_destino": [] if ultima_serie else candidatas,
        "sugestao_ambigua": ambigua,
        "alunos": linhas,
    }


# ──────────────────────────────────────────────────────────────
# Aplicação em lote + desfazer
# ──────────────────────────────────────────────────────────────

def aplicar_lote(decisoes: list[dict], turma_origem: str = "", executado_por: str = "") -> dict:
    """
    decisoes: [{"aluno_id": int, "acao": "avancar"|"reter"|"concluir", "nova_turma": str|None}]
    Aplica todas as decisões de uma vez e grava um snapshot do estado
    anterior de cada aluno afetado, para permitir desfazer o lote
    inteiro depois (ver desfazer_lote).
    """
    if not decisoes:
        raise ValueError("Nenhum aluno para processar.")

    db = _get_db()
    _garantir_tabela_historico(db)

    estados_antes = []
    resumo = {"avancados": 0, "retidos": 0, "formados": 0}

    for d in decisoes:
        acao = d.get("acao")
        if acao not in ACOES_VALIDAS:
            raise ValueError(f"Ação desconhecida: {acao!r}.")

        aluno = cadastro_alunos.buscar_um(d["aluno_id"], db=db)
        if not aluno:
            continue
        estados_antes.append(dict(aluno))  # snapshot completo, para desfazer

        if acao == "avancar":
            nova_turma = d.get("nova_turma")
            info = cadastro_alunos.turma_info(nova_turma) if nova_turma else None
            if not info:
                raise ValueError(f"Selecione uma turma de destino válida para '{aluno['nome']}'.")
            db.atualizar("alunos", {
                "serie": info["serie"], "turma": info["turma"], "curso": info["curso"],
            }, onde={"id": aluno["id"]})
            resumo["avancados"] += 1

        elif acao == "reter":
            # Permanece na mesma turma — nada muda nos dados do aluno,
            # mas ele entra no snapshot mesmo assim, para que o lote
            # inteiro (incluindo quem NÃO mudou) possa ser desfeito de
            # forma consistente caso a operação toda precise ser revertida.
            resumo["retidos"] += 1

        elif acao == "concluir":
            db.atualizar("alunos", {"status": "formado"}, onde={"id": aluno["id"]})
            resumo["formados"] += 1

    if not estados_antes:
        raise ValueError("Nenhum aluno válido para processar.")

    resumo_texto = f"{resumo['avancados']} avançado(s), {resumo['retidos']} retido(s), {resumo['formados']} concluído(s)"
    lote = db.inserir("promocoes_historico", {
        "executado_em": datetime.now(),
        "executado_por": executado_por,
        "turma_origem": turma_origem,
        "quantidade": len(estados_antes),
        "resumo": resumo_texto,
        "estados_antes": json.dumps(estados_antes, ensure_ascii=False),
        "desfeito": False,
    })

    resumo["lote_id"] = lote["id"]
    resumo["resumo_texto"] = resumo_texto
    return resumo


def ultimo_lote_desfazivel() -> dict | None:
    """Retorna o lote mais recente ainda não desfeito, ou None."""
    db = _get_db()
    _garantir_tabela_historico(db)
    lotes = db.buscar("promocoes_historico", onde={"desfeito": False}, ordenar_por="id")
    return lotes[-1] if lotes else None


def desfazer_lote(lote_id: int) -> int:
    """
    Restaura o estado anterior de todos os alunos afetados pelo lote
    indicado. Retorna quantos alunos foram restaurados.
    """
    db = _get_db()
    _garantir_tabela_historico(db)

    lote = db.buscar_um("promocoes_historico", onde={"id": lote_id})
    if not lote:
        raise ValueError("Lote não encontrado.")
    if lote.get("desfeito"):
        raise ValueError("Este avanço já foi desfeito anteriormente.")

    estados = json.loads(lote["estados_antes"])
    for estado in estados:
        db.atualizar("alunos", {
            "nome":   estado["nome"],
            "serie":  estado["serie"],
            "turma":  estado["turma"],
            "curso":  estado["curso"],
            "status": estado.get("status", "ativo"),
        }, onde={"id": estado["id"]})

    db.atualizar("promocoes_historico", {"desfeito": True}, onde={"id": lote_id})
    return len(estados)
