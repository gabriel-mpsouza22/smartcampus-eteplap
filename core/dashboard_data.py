"""
Agregação de dados para o Dashboard (Command Center).

Este módulo NÃO cria estado novo nem tabelas próprias: ele apenas lê o
que os módulos já existentes gravam no SCEDS e monta um resumo
operacional contextual por perfil.

Princípio central: o dashboard nunca pode quebrar por causa de um
módulo específico. Cada widget é calculado de forma isolada — se uma
tabela não existir ainda (instalação nova, módulo nunca usado) ou algo
der errado, aquele widget some da tela e o restante do dashboard segue
funcionando normalmente. Erros são sempre registrados no log.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent


def _carregar_config() -> dict:
    from core.config_path import resolver_config_path
    with open(resolver_config_path(_BASE), encoding="utf-8") as f:
        return json.load(f)


def _get_db():
    config = _carregar_config()
    caminho_base = Path(config["caminho_base"])
    if str(caminho_base) not in sys.path:
        sys.path.insert(0, str(caminho_base))
    from sceds import SCEDS
    return SCEDS(caminho_base / "sceds" / "data")


def _modulos_ativos() -> set:
    from core.router import modulos_ativos_permitidos
    return modulos_ativos_permitidos(_carregar_config())


def _seguro(nome_widget: str, fn, *args, **kwargs):
    """Executa fn protegendo o dashboard: qualquer falha vira log + widget ausente."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(f"[Dashboard] Widget '{nome_widget}' indisponível: {e}")
        return None


def _no_escopo_turno(registros: list[dict], campo_turma: str = "aluno_turma") -> list[dict]:
    """
    Filtra uma lista de registros (ocorrências, saídas, entradas de
    pontualidade...) pelo escopo de turno do usuário logado, usando o
    nome de turma gravado no próprio registro (campo_turma). Sem
    usuário logado ou com escopo "todos", devolve a lista sem alterar.
    """
    from core.alunos import _escopo_turno_da_requisicao, _turno_por_turma
    escopo = _escopo_turno_da_requisicao()
    if not escopo:
        return registros
    turno_por_turma = _turno_por_turma()
    return [r for r in registros if turno_por_turma.get(r.get(campo_turma)) in escopo]


# ── stats individuais (cada uma assume que a tabela pode não existir) ──

def _stat_alunos(db) -> dict | None:
    from core.alunos import buscar as buscar_alunos
    total = len(buscar_alunos(db=db))
    if total == 0:
        return None
    return {"id": "alunos", "label": "Alunos matriculados", "valor": total,
            "icone": "i-graduation", "cor": "azul", "url": "/alunos/"}


def _stat_pontualidade_hoje(db) -> dict | None:
    hoje = date.today().isoformat()
    registros = db.buscar("entradas_pontualidade", onde={"data": hoje})
    registros = _no_escopo_turno(registros)
    if not registros:
        return None
    pontuais = sum(1 for r in registros if r.get("status") == "normal")
    pct = round((pontuais / len(registros)) * 100)
    return {"id": "pontualidade", "label": "Pontualidade hoje", "valor": f"{pct}%",
            "sublabel": f"{pontuais} de {len(registros)} entradas",
            "icone": "i-clock", "cor": "verde" if pct >= 85 else "amarelo",
            "url": "/pontualidade/dashboard"}


def _stat_ocorrencias_7d(db) -> dict | None:
    limite = (datetime.now() - timedelta(days=7)).isoformat()
    todas = db.buscar("ocorrencias")
    recentes = [o for o in todas if o.get("data_hora", "") >= limite]
    recentes = _no_escopo_turno(recentes)
    return {"id": "ocorrencias", "label": "Ocorrências (7 dias)", "valor": len(recentes),
            "icone": "i-clipboard", "cor": "vermelho" if len(recentes) > 5 else "texto",
            "url": "/ocorrencias/"}


def _stat_saidas_pendentes(db) -> dict | None:
    ativas = {"aguardando_coordenacao", "autorizada"}
    todas = db.buscar("saidas_autorizacoes")
    pendentes = [a for a in todas if a.get("status") in ativas]
    pendentes = _no_escopo_turno(pendentes)
    return {"id": "saidas", "label": "Saídas pendentes", "valor": len(pendentes),
            "icone": "i-door", "cor": "amarelo" if pendentes else "texto",
            "url": "/saidas/secretaria"}


def _stat_visitantes_dentro(db) -> dict | None:
    dentro = db.buscar("visitantes_visitas", onde={"status": "no_campus"})
    return {"id": "visitantes", "label": "Visitantes no campus", "valor": len(dentro),
            "icone": "i-users", "cor": "azul" if dentro else "texto",
            "url": "/visitantes/central"}


def _stat_chamados_abertos(db) -> dict | None:
    todos = db.buscar("chamados")
    abertos = [c for c in todos if c.get("status") in ("aberto", "em_atendimento")]
    return {"id": "chamados", "label": "Chamados pendentes", "valor": len(abertos),
            "icone": "i-wrench", "cor": "amarelo" if abertos else "texto",
            "url": "/chamados/"}


def _stat_emprestimos_atrasados(db) -> dict | None:
    hoje = date.today().isoformat()
    todos = db.buscar("emprestimos")
    ativos = [e for e in todos if not e.get("devolvido")]
    if not ativos:
        return None
    atrasados = [e for e in ativos if e.get("data_prevista_devolucao", "9999") < hoje]
    return {"id": "biblioteca", "label": "Empréstimos ativos", "valor": len(ativos),
            "sublabel": f"{len(atrasados)} atrasados" if atrasados else "nenhum atrasado",
            "icone": "i-books", "cor": "vermelho" if atrasados else "texto",
            "url": "/biblioteca/"}


def _stat_reservas_hoje(db) -> dict | None:
    hoje = date.today().isoformat()
    reservas = db.buscar("reservas", onde={"data_reserva": hoje})
    return {"id": "agendamento", "label": "Reservas hoje", "valor": len(reservas),
            "icone": "i-calendar", "cor": "texto", "url": "/agendamento/"}


def _evasao_criticos(db) -> list[dict]:
    """Reaproveita o mesmo motor de score usado no módulo de Evasão,
    em vez de duplicar a lógica de risco aqui."""
    from modulos.evasao.api_evasao import calcular_score_aluno, _modulo_ocorrencias
    from core.alunos import buscar as buscar_alunos
    ocor_mod = _modulo_ocorrencias()
    alunos = buscar_alunos(db=db, incluir_formados=False)
    criticos = []
    for aluno in alunos:
        r = calcular_score_aluno(db, ocor_mod, aluno)
        if r["nivel"]["id"] == "critico":
            criticos.append(aluno)
    return criticos


def _stat_evasao(db) -> dict | None:
    criticos = _evasao_criticos(db)
    if not criticos:
        return None
    return {"id": "evasao", "label": "Alunos em risco crítico", "valor": len(criticos),
            "icone": "i-target", "cor": "vermelho", "url": "/evasao/"}


# ── área de atenção (situações que pedem ação) ──

def _alertas(db, ativos: set) -> list[dict]:
    alertas = []

    if "chamados" in ativos:
        abertos = [c for c in db.buscar("chamados")
                   if c.get("status") in ("aberto", "em_atendimento")]
        altos = [c for c in abertos if c.get("prioridade") in ("alta", "urgente")]
        if altos:
            alertas.append({
                "nivel": "critico", "titulo": f"{len(altos)} chamado(s) de alta prioridade em aberto",
                "descricao": "Existem chamados técnicos urgentes aguardando atendimento.",
                "url": "/chamados/",
            })

    if "evasao" in ativos:
        criticos = _seguro("evasao_alertas", _evasao_criticos, db) or []
        if criticos:
            alertas.append({
                "nivel": "critico", "titulo": f"{len(criticos)} aluno(s) em risco crítico de evasão",
                "descricao": "Frequência e/ou histórico disciplinar indicam necessidade de intervenção.",
                "url": "/evasao/",
            })

    if "saidas" in ativos:
        aguardando = [a for a in db.buscar("saidas_autorizacoes")
                      if a.get("status") == "aguardando_coordenacao"]
        if aguardando:
            alertas.append({
                "nivel": "atencao", "titulo": f"{len(aguardando)} saída(s) aguardando autorização da coordenação",
                "descricao": "Solicitações de saída de alunos ainda não foram avaliadas.",
                "url": "/saidas/coordenacao",
            })

    if "visitantes" in ativos:
        limite = (datetime.now() - timedelta(hours=3)).isoformat()
        antigos = [v for v in db.buscar("visitantes_visitas", onde={"status": "no_campus"})
                   if v.get("entrada_em", "") < limite]
        if antigos:
            alertas.append({
                "nivel": "atencao", "titulo": f"{len(antigos)} visitante(s) no campus há mais de 3 horas",
                "descricao": "Verifique se a saída desses visitantes precisa ser registrada.",
                "url": "/visitantes/central",
            })

    if "biblioteca" in ativos:
        hoje = date.today().isoformat()
        atrasados = [e for e in db.buscar("emprestimos")
                     if not e.get("devolvido") and e.get("data_prevista_devolucao", "9999") < hoje]
        muito_atrasados = [
            e for e in atrasados
            if (date.today() - date.fromisoformat(e["data_prevista_devolucao"])).days >= 7
        ]
        if muito_atrasados:
            alertas.append({
                "nivel": "atencao", "titulo": f"{len(muito_atrasados)} empréstimo(s) com mais de 7 dias de atraso",
                "descricao": "Considere entrar em contato com os alunos para devolução.",
                "url": "/biblioteca/",
            })

    return alertas


# ── atividade recente (timeline unificada) ──

def _atividade_recente(db, ativos: set, limite: int = 8) -> list[dict]:
    eventos = []

    if "ocorrencias" in ativos:
        for o in db.buscar("ocorrencias", ordenar_por="data_hora")[-15:]:
            eventos.append({
                "quando": o.get("data_hora", ""),
                "titulo": f"Ocorrência registrada — {o.get('tipo', 'sem tipo')}",
                "icone": "i-clipboard", "url": "/ocorrencias/",
            })

    if "saidas" in ativos:
        for a in db.buscar("saidas_autorizacoes", ordenar_por="criado_em")[-15:]:
            eventos.append({
                "quando": a.get("criado_em", ""),
                "titulo": f"Saída solicitada — {a.get('aluno_nome', 'aluno')} ({a.get('aluno_turma', '')})",
                "icone": "i-door", "url": "/saidas/secretaria",
            })

    if "visitantes" in ativos:
        for v in db.buscar("visitantes_visitas", ordenar_por="criado_em")[-15:]:
            eventos.append({
                "quando": v.get("criado_em", ""),
                "titulo": f"Visitante — {v.get('visitante_nome', '')} ({v.get('destino', '')})",
                "icone": "i-users", "url": "/visitantes/central",
            })

    if "chamados" in ativos:
        for c in db.buscar("chamados", ordenar_por="aberto_em")[-15:]:
            eventos.append({
                "quando": c.get("aberto_em", ""),
                "titulo": f"Chamado aberto — {c.get('titulo', '')}",
                "icone": "i-wrench", "url": "/chamados/",
            })

    if "biblioteca" in ativos:
        for e in db.buscar("emprestimos", ordenar_por="data_emprestimo")[-15:]:
            eventos.append({
                "quando": e.get("data_emprestimo", ""),
                "titulo": f"Empréstimo — {e.get('aluno_nome', '')}",
                "icone": "i-books", "url": "/biblioteca/",
            })

    eventos.sort(key=lambda e: e["quando"], reverse=True)
    return eventos[:limite]


# ── composição por perfil ──

_STATS_POR_PERFIL: dict[str, list] = {
    "admin": [_stat_alunos, _stat_pontualidade_hoje, _stat_ocorrencias_7d,
              _stat_saidas_pendentes, _stat_visitantes_dentro, _stat_chamados_abertos],
    "coordenadora": [_stat_evasao, _stat_ocorrencias_7d, _stat_pontualidade_hoje,
                     _stat_saidas_pendentes],
    "portaria": [_stat_visitantes_dentro, _stat_saidas_pendentes, _stat_pontualidade_hoje],
    "secretaria": [_stat_visitantes_dentro, _stat_saidas_pendentes, _stat_chamados_abertos],
    "bibliotecaria": [_stat_emprestimos_atrasados],
    "professor": [_stat_reservas_hoje, _stat_chamados_abertos],
    "aluno_chamados": [_stat_chamados_abertos],
}

# quais domínios de alerta/atividade fazem sentido em cada dashboard —
# evita, por exemplo, um bibliotecário ver alertas de chamados técnicos.
_DOMINIOS_POR_PERFIL: dict[str, set] = {
    "admin": {"chamados", "evasao", "saidas", "visitantes", "biblioteca", "ocorrencias"},
    "coordenadora": {"evasao", "saidas", "ocorrencias"},
    "portaria": {"saidas", "visitantes"},
    "secretaria": {"saidas", "visitantes", "chamados"},
    "bibliotecaria": {"biblioteca"},
    "professor": {"chamados"},
    "aluno_chamados": {"chamados"},
}


def montar_dashboard(perfil: str) -> dict:
    """
    Monta o resumo do Command Center para o perfil informado.
    Retorna sempre uma estrutura válida (possivelmente vazia) — nunca
    lança exceção para fora, para não derrubar a renderização do
    dashboard.
    """
    vazio = {"resumo": [], "atencao": [], "atividade": []}

    db = _seguro("conexao_sceds", _get_db)
    if db is None:
        return vazio

    ativos = _seguro("modulos_ativos", _modulos_ativos) or set()

    funcs = _STATS_POR_PERFIL.get(perfil, [])
    resumo = []
    for fn in funcs:
        # cada stat já checa internamente a presença de dados; aqui só
        # filtramos por módulo efetivamente contratado nesta instalação
        # (o id do stat corresponde 1:1 ao id em "modulos_ativos").
        resultado = _seguro(fn.__name__, fn, db)
        if resultado and resultado["id"] in ativos:
            resumo.append(resultado)

    dominios = _DOMINIOS_POR_PERFIL.get(perfil, set()) & ativos
    atencao = _seguro("alertas", _alertas, db, dominios) or []
    atividade = _seguro("atividade", _atividade_recente, db, dominios) or []

    return {"resumo": resumo, "atencao": atencao, "atividade": atividade}
