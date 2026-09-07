"""
Controle de Pontualidade
-------------------------
Regras de negócio do registro de entradas na portaria. Mantido separado
das rotas Flask (modulos/pontualidade/api_pontualidade.py) para ser
testável isoladamente, no mesmo espírito de core/promocoes.py e
wizard/logica.py.

Conceitos:

  Regras de horário (configuráveis por escola, nunca fixas no código)
  → decidem o "status" de uma entrada a partir do horário registrado.

  Evento de entrada — cada registro na portaria. Guarda uma cópia da
  turma do aluno NO MOMENTO do evento (não uma referência viva), para
  que o histórico continue correto mesmo depois de o aluno mudar de
  turma ou passar pelo avanço de ano letivo.

  Reincidência — regra configurável (nº mínimo de atrasos por período)
  usada para destacar alunos que merecem atenção da coordenação.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

from core import alunos as cadastro_alunos

BASE_CORE = Path(__file__).resolve().parent
CAMINHO_CONFIG = BASE_CORE / "config_pontualidade.json"

STATUS_LABELS_PADRAO = {
    "normal":       "Entrada normal",
    "atraso":       "Atraso",
    "atraso_leve":  "Atraso leve",
    "atraso_grave": "Atraso grave",
}

CONFIG_PADRAO = {
    "regras": [
        {"ate": "07:45", "status": "normal",       "label": "Entrada normal"},
        {"de": "07:46", "ate": "08:19",             "status": "atraso",       "label": "Atraso — perdeu a 1ª aula"},
        {"de": "08:20", "ate": "08:22",             "status": "atraso_leve",  "label": "Entrada permitida na 2ª aula"},
        {"de": "08:23", "ate": "09:09",             "status": "atraso_grave", "label": "Atraso — entrada só no intervalo"},
        {"de": "09:10",                             "status": "atraso_grave", "label": "Entrada a partir do intervalo"},
    ],
    "reincidencia": {
        "minimo_atrasos": 3,
        "condicao": "mais_de",   # "mais_de" | "igual_ou_mais_de"
        "periodo": "semana",     # "semana" | "mes"
    },
}


def _get_db():
    return cadastro_alunos._get_db()


def _garantir_tabela_eventos(db):
    if not db.tabela_existe("entradas_pontualidade"):
        db.criar_tabela("entradas_pontualidade", [
            {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
            {"nome": "aluno_id", "tipo": "INTEIRO", "modificadores": ["NAO_NULO"]},
            # snapshot no momento do evento — histórico não muda quando
            # o aluno troca de turma ou é promovido/retido depois.
            {"nome": "aluno_nome", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
            {"nome": "aluno_turma", "tipo": "TEXTO", "modificadores": []},
            {"nome": "data", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},       # YYYY-MM-DD
            {"nome": "horario", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},    # HH:MM
            {"nome": "status", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
            {"nome": "status_label", "tipo": "TEXTO", "modificadores": []},
            {"nome": "operador", "tipo": "TEXTO", "modificadores": []},
            {"nome": "observacoes", "tipo": "TEXTO", "modificadores": []},
            {"nome": "criado_em", "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
        ])


def resumo_hoje() -> dict:
    """
    Contagem simples dos registros de hoje — sem nomes de alunos, só
    números — pra alimentar o resumo do Painel do Porteiro sem expor
    dados individuais numa tela de uso rápido, compartilhada e visível
    o dia inteiro.
    """
    from datetime import date
    db = _get_db()
    _garantir_tabela_eventos(db)
    hoje = date.today().isoformat()
    eventos = db.buscar("entradas_pontualidade", onde={"data": hoje})
    return {
        "total_hoje": len(eventos),
        "atrasos_hoje": len([e for e in eventos if e["status"] != "normal"]),
    }


# ──────────────────────────────────────────────────────────────
# Configuração (regras de horário + regra de reincidência)
# ──────────────────────────────────────────────────────────────

def carregar_config() -> dict:
    if not CAMINHO_CONFIG.exists():
        salvar_config(CONFIG_PADRAO)
        return json.loads(json.dumps(CONFIG_PADRAO))
    with open(CAMINHO_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def salvar_config(config: dict) -> None:
    # Ordena as regras pelo horário de início — a ordem determina qual
    # regra "vence" em classificar_horario(), então deixamos isso
    # automático em vez de depender do admin reordenar manualmente na tela.
    config = dict(config)
    config["regras"] = sorted(config.get("regras", []), key=lambda r: r.get("de") or "00:00")
    with open(CAMINHO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def validar_regras(regras: list[dict]) -> list[str]:
    """Valida a lista de faixas de horário. Retorna lista de erros (vazia = válida)."""
    erros = []
    if not regras:
        erros.append("Defina pelo menos uma regra de horário.")
        return erros

    for i, r in enumerate(regras, 1):
        de, ate = r.get("de"), r.get("ate")
        if not de and not ate:
            erros.append(f"Regra {i}: informe pelo menos um horário de início ou fim.")
            continue
        for campo, valor in (("de", de), ("ate", ate)):
            if valor:
                try:
                    datetime.strptime(valor, "%H:%M")
                except ValueError:
                    erros.append(f"Regra {i}: horário '{campo}' inválido ('{valor}'). Use o formato HH:MM.")
        if not r.get("status") or not r.get("label"):
            erros.append(f"Regra {i}: preencha o status e a descrição.")
    return erros


def classificar_horario(horario: str, regras: list[dict] | None = None) -> dict:
    """
    Aplica as regras configuradas a um horário HH:MM e retorna
    {"status": ..., "label": ...}. A primeira regra cuja faixa contém o
    horário vence — por isso a ordem das regras importa (regras devem
    ser cadastradas da mais cedo para a mais tarde).
    """
    regras = regras if regras is not None else carregar_config()["regras"]
    for r in regras:
        de, ate = r.get("de"), r.get("ate")
        if de and horario < de:
            continue
        if ate and horario > ate:
            continue
        return {"status": r["status"], "label": r["label"]}
    # Nenhuma regra bateu (configuração incompleta) — não trava o
    # registro, só marca como não classificado para a coordenação notar.
    return {"status": "sem_classificacao", "label": "Fora das faixas configuradas"}


# ──────────────────────────────────────────────────────────────
# Busca rápida (portaria) + cadastro progressivo
# ──────────────────────────────────────────────────────────────

def buscar_alunos_portaria(termo: str, limite: int = 8) -> list[dict]:
    """
    Busca para a tela da portaria: nome ou matrícula, com informação
    suficiente para o porteiro confirmar visualmente (nome + turma +
    matrícula) e nunca criar um cadastro duplicado sem perceber.
    """
    if not termo or len(termo.strip()) < 2:
        return []
    return cadastro_alunos.buscar(busca=termo, limite=limite)


def registrar_entrada(aluno_id: int, operador: str = "", observacoes: str = "",
                       agora: datetime | None = None) -> dict:
    """Registra uma entrada para um aluno já cadastrado. Horário é sempre o do servidor."""
    aluno = cadastro_alunos.buscar_um(aluno_id)
    if not aluno:
        raise ValueError("Aluno não encontrado.")
    return _criar_evento(aluno, operador, observacoes, agora)


def registrar_entrada_com_cadastro_rapido(nome: str, turma: str, matricula: str = "",
                                           operador: str = "", observacoes: str = "",
                                           agora: datetime | None = None) -> dict:
    """
    Cria o aluno (cadastro progressivo — só o mínimo necessário) e já
    registra a entrada em uma única operação, para não quebrar o fluxo
    da portaria em duas etapas.
    """
    db = _get_db()
    aluno = cadastro_alunos.criar(nome, turma, matricula, db=db)
    return _criar_evento(aluno, operador, observacoes, agora, db=db)


def _criar_evento(aluno: dict, operador: str, observacoes: str,
                   agora: datetime | None, db=None) -> dict:
    agora = agora or datetime.now()
    db = db or _get_db()
    _garantir_tabela_eventos(db)

    classificacao = classificar_horario(agora.strftime("%H:%M"))

    evento = db.inserir("entradas_pontualidade", {
        "aluno_id": aluno["id"],
        "aluno_nome": aluno["nome"],
        "aluno_turma": aluno.get("turma", ""),
        "data": agora.strftime("%Y-%m-%d"),
        "horario": agora.strftime("%H:%M"),
        "status": classificacao["status"],
        "status_label": classificacao["label"],
        "operador": operador,
        "observacoes": observacoes,
        "criado_em": agora,
    })
    return evento


# ──────────────────────────────────────────────────────────────
# Perfil histórico do aluno
# ──────────────────────────────────────────────────────────────

def historico_aluno(aluno_id: int, apenas_atrasos: bool = True) -> dict:
    """Histórico completo de entradas de um aluno + estatísticas resumidas."""
    # buscar_um não filtra "formado" (só buscar() faz isso) — então um
    # aluno que já concluiu o curso ainda aparece aqui normalmente,
    # o que é correto: o perfil histórico deve continuar acessível
    # mesmo depois de o aluno se formar.
    aluno = cadastro_alunos.buscar_um(aluno_id)
    if not aluno:
        raise ValueError("Aluno não encontrado.")

    db = _get_db()
    _garantir_tabela_eventos(db)
    eventos = db.buscar("entradas_pontualidade", onde={"aluno_id": aluno_id}, ordenar_por="data")
    eventos = sorted(eventos, key=lambda e: (e["data"], e["horario"]), reverse=True)

    if apenas_atrasos:
        eventos_relevantes = [e for e in eventos if e["status"] != "normal"]
    else:
        eventos_relevantes = eventos

    total_atrasos = len([e for e in eventos if e["status"] != "normal"])
    ultimo_atraso = next((e for e in eventos if e["status"] != "normal"), None)

    horarios_atraso = [e["horario"] for e in eventos if e["status"] != "normal"]
    media_horario = _media_horarios(horarios_atraso) if horarios_atraso else None
    faixa_frequente = _faixa_mais_frequente(horarios_atraso) if horarios_atraso else None

    return {
        "aluno": aluno,
        "eventos": eventos_relevantes,
        "total_atrasos": total_atrasos,
        "ultimo_atraso": ultimo_atraso["data"] if ultimo_atraso else None,
        "media_horario": media_horario,
        "faixa_mais_frequente": faixa_frequente,
    }


def _media_horarios(horarios: list[str]) -> str:
    """Média de uma lista de horários HH:MM, como HH:MM."""
    total_minutos = sum(int(h[:2]) * 60 + int(h[3:5]) for h in horarios)
    media = total_minutos // len(horarios)
    return f"{media // 60:02d}:{media % 60:02d}"


def _faixa_mais_frequente(horarios: list[str], largura_min: int = 20) -> str:
    """Faixa de X minutos com mais ocorrências, ex: '07:50–08:10'."""
    def bucket(h):
        minutos = int(h[:2]) * 60 + int(h[3:5])
        inicio = (minutos // largura_min) * largura_min
        return inicio

    contagem = Counter(bucket(h) for h in horarios)
    inicio_mais_comum = contagem.most_common(1)[0][0]
    fim = inicio_mais_comum + largura_min
    return f"{inicio_mais_comum // 60:02d}:{inicio_mais_comum % 60:02d}–{fim // 60:02d}:{fim % 60:02d}"


# ──────────────────────────────────────────────────────────────
# Dashboard mensal + reincidência
# ──────────────────────────────────────────────────────────────

DIAS_SEMANA_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _eventos_do_periodo(ano: int, mes: int) -> list[dict]:
    db = _get_db()
    _garantir_tabela_eventos(db)
    prefixo = f"{ano:04d}-{mes:02d}"
    return [e for e in db.buscar("entradas_pontualidade") if e["data"].startswith(prefixo)]


def _semana_do_mes(data_str: str) -> int:
    """Número da semana ISO — usado para agrupar reincidência 'por semana'."""
    d = date.fromisoformat(data_str)
    return d.isocalendar()[1]


def alunos_reincidentes(ano: int, mes: int, config: dict | None = None) -> list[dict]:
    """
    Alunos que bateram a regra de reincidência configurada dentro do
    mês informado (a regra em si pode olhar por semana ou pelo mês
    inteiro — ver core/config_pontualidade.json).
    """
    config = config or carregar_config()
    regra = config["reincidencia"]
    minimo = regra["minimo_atrasos"]
    condicao = regra["condicao"]
    periodo = regra["periodo"]

    eventos = [e for e in _eventos_do_periodo(ano, mes) if e["status"] != "normal"]

    por_aluno = defaultdict(list)
    for e in eventos:
        por_aluno[e["aluno_id"]].append(e)

    def bate_regra(qtd: int) -> bool:
        return qtd > minimo if condicao == "mais_de" else qtd >= minimo

    resultado = []
    for aluno_id, evs in por_aluno.items():
        if periodo == "semana":
            semanas = defaultdict(int)
            for e in evs:
                semanas[_semana_do_mes(e["data"])] += 1
            semanas_reincidentes = [s for s, qtd in semanas.items() if bate_regra(qtd)]
            if not semanas_reincidentes:
                continue
            qtd_semanas = len(semanas_reincidentes)
        else:
            if not bate_regra(len(evs)):
                continue
            qtd_semanas = None

        ultimo = max(evs, key=lambda e: (e["data"], e["horario"]))
        resultado.append({
            "aluno_id": aluno_id,
            "nome": evs[0]["aluno_nome"],
            "turma": evs[0]["aluno_turma"],
            "atrasos_no_mes": len(evs),
            "semanas_reincidentes": qtd_semanas,
            "ultimo_atraso": ultimo["data"],
        })

    resultado.sort(key=lambda r: r["atrasos_no_mes"], reverse=True)
    return resultado


def dashboard_mensal(ano: int, mes: int) -> dict:
    """Monta todos os dados da tela de Controle de Pontualidade (coordenação)."""
    eventos = _eventos_do_periodo(ano, mes)
    atrasos = [e for e in eventos if e["status"] != "normal"]

    alunos_distintos = {e["aluno_id"] for e in atrasos}
    reincidentes = alunos_reincidentes(ano, mes)

    por_turma = Counter(e["aluno_turma"] or "—" for e in atrasos)
    top_turmas = [{"nome": t, "total": q} for t, q in por_turma.most_common(8)]

    turma_com_mais = top_turmas[0]["nome"] if top_turmas else "—"

    por_dia_semana = Counter(DIAS_SEMANA_PT[date.fromisoformat(e["data"]).weekday()] for e in atrasos)
    dia_com_mais = por_dia_semana.most_common(1)[0][0] if por_dia_semana else "—"

    faixa_com_mais = _faixa_mais_frequente([e["horario"] for e in atrasos], largura_min=15) if atrasos else "—"

    # série diária do mês (para o gráfico de linha)
    ultimo_dia = _ultimo_dia_do_mes(ano, mes)
    contagem_por_dia = Counter(e["data"] for e in atrasos)
    labels_dias = [f"{d:02d}" for d in range(1, ultimo_dia + 1)]
    valores_dias = [contagem_por_dia.get(f"{ano:04d}-{mes:02d}-{d:02d}", 0) for d in range(1, ultimo_dia + 1)]

    # concentração por faixa de horário (para o ranking de barras)
    faixas = Counter()
    for e in atrasos:
        minutos = int(e["horario"][:2]) * 60 + int(e["horario"][3:5])
        inicio = (minutos // 15) * 15
        faixas[f"{inicio // 60:02d}:{inicio % 60:02d}"] += 1
    top_faixas_horario = [{"nome": f, "total": q} for f, q in sorted(faixas.items())]

    return {
        "kpis": {
            "total_atrasos": len(atrasos),
            "alunos_atrasados": len(alunos_distintos),
            "alunos_reincidentes": len(reincidentes),
            "turma_com_mais_atrasos": turma_com_mais,
            "dia_semana_com_mais_atrasos": dia_com_mais,
            "faixa_horario_com_mais_atrasos": faixa_com_mais,
        },
        "reincidentes": reincidentes,
        "top_turmas": top_turmas,
        "atrasos_por_dia": {"labels": labels_dias, "valores": valores_dias},
        "atrasos_por_horario": top_faixas_horario,
    }


def _ultimo_dia_do_mes(ano: int, mes: int) -> int:
    proximo_mes = date(ano + (mes == 12), (mes % 12) + 1, 1)
    return (proximo_mes - timedelta(days=1)).day
