"""
Módulo: Prevenção de Evasão Escolar
------------------------------------
Cruza dados já coletados por outros módulos do Smart Campus (ocorrências
disciplinares e uso da biblioteca) com a frequência escolar — hoje ainda
registrada manualmente pela coordenação, já que o sistema não possui
integração automática com um diário de classe — para calcular um SCORE
DE RISCO DE EVASÃO por aluno (0 a 100) e gerar alertas para a coordenação
agir antes do abandono se concretizar.

Importante: nenhuma predição aqui é "mágica" nem baseada em modelo
estatístico complexo. É um score transparente, com pesos e motivos
explícitos, para que a coordenação sempre entenda POR QUE um aluno
está sinalizado — e possa confiar (ou contestar) o resultado.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request

blueprint = Blueprint("evasao", __name__,
                      template_folder="../../templates/evasao")

from core.auth import perfil_obrigatorio
from core.notificacoes import notificar_se_ausente
from core import alunos as cadastro_alunos

BASE = Path(__file__).resolve().parent


# ══════════════════════════════════════════════════════════════
# CONFIGURAÇÃO DO MODELO DE SCORE
# ══════════════════════════════════════════════════════════════

JANELA_DISCIPLINAR_DIAS = 60      # olha ocorrências dos últimos 60 dias
JANELA_ENGAJAMENTO_DIAS = 90      # olha uso da biblioteca dos últimos 90 dias
VALIDADE_FREQUENCIA_DIAS = 45     # um registro de frequência mais velho que isso conta como "desatualizado"

LIMITE_FREQUENCIA_ATENCAO = 85.0  # abaixo disso já soma risco
LIMITE_FREQUENCIA_CRITICA = 75.0  # abaixo disso é sinal forte de evasão (padrão usado por redes estaduais)

# Pesos relativos de cada componente no score final.
# Quando um componente não tem dado disponível (ex: frequência nunca
# registrada), seu peso é redistribuído entre os componentes restantes,
# em vez de contar como "risco zero" — o que esconderia o problema.
PESOS = {
    "frequencia":  0.45,
    "disciplinar": 0.40,
    "engajamento": 0.15,
}

NIVEIS = [
    # (limite_inferior, id, nome, cor)
    (75, "critico",  "Crítico",  "vermelho"),
    (55, "alto",     "Alto",     "laranja"),
    (30, "moderado", "Moderado", "amarelo"),
    (0,  "baixo",    "Baixo",    "verde"),
]


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    from core.config_path import carregar_config
    cfg = carregar_config(BASE.parent.parent)
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")


def _modulo_ocorrencias():
    """Importa funções do módulo de ocorrências (fonte principal de dados disciplinares)."""
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from modulos.ocorrencias import api_ocorrencias as m
    return m


def _nivel_para(score: float) -> dict:
    for limite, nivel_id, nome, cor in NIVEIS:
        if score >= limite:
            return {"id": nivel_id, "nome": nome, "cor": cor}
    return {"id": "baixo", "nome": "Baixo", "cor": "verde"}


def _frequencia_atual(db, aluno_id: int) -> dict | None:
    """Retorna o registro de frequência mais recente de um aluno, ou None."""
    registros = db.buscar("evasao_frequencia", onde={"aluno_id": aluno_id}, ordenar_por="registrado_em")
    return registros[-1] if registros else None


def _componente_disciplinar(db, ocor_mod, aluno_id: int) -> tuple[float | None, list[str], int]:
    """
    Soma a severidade das ocorrências (exceto elogios) dentro da janela.
    Cada ponto de severidade vale 15 pontos de risco, com teto em 100.
    Retorna (pontuacao_0_a_100, motivos, quantidade_no_periodo).
    """
    limite = datetime.now() - timedelta(days=JANELA_DISCIPLINAR_DIAS)
    todas = db.buscar("ocorrencias", onde={"aluno_id": aluno_id})
    recentes = [
        o for o in todas
        if not ocor_mod._e_elogio(o.get("tipo", ""), db=db) and o.get("data_hora")
        and datetime.fromisoformat(o["data_hora"]) >= limite
    ]

    if not todas:
        # Aluno sem nenhum histórico no módulo de ocorrências: não há dado, não presumir risco.
        return None, [], 0

    soma_severidade = sum(ocor_mod._tipo_info(o.get("tipo", ""), db=db).get("severidade", 1) for o in recentes)
    pontuacao = min(100.0, soma_severidade * 15)

    motivos = []
    if recentes:
        motivos.append(
            f"{len(recentes)} ocorrência(s) disciplinar(es) nos últimos {JANELA_DISCIPLINAR_DIAS} dias"
        )
    tipos_graves = {ocor_mod._tipo_info(o.get("tipo", ""), db=db)["nome"]
                    for o in recentes if ocor_mod._tipo_info(o.get("tipo", ""), db=db).get("severidade", 0) >= 3}
    if tipos_graves:
        motivos.append(f"Inclui ao menos uma ocorrência grave ({', '.join(sorted(tipos_graves))})")

    return pontuacao, motivos, len(recentes)


def _componente_frequencia(freq: dict | None) -> tuple[float | None, list[str]]:
    """
    Converte o percentual de frequência mais recente em pontuação de risco.
    Quanto menor a frequência, maior o risco. Sem registro → sem dado.
    """
    if not freq:
        return None, []

    percentual = float(freq.get("percentual", 100))
    motivos = []

    if percentual >= LIMITE_FREQUENCIA_ATENCAO:
        pontuacao = max(0.0, (100 - percentual) * 3)
    else:
        # abaixo do limite de atenção, o risco cresce mais rápido
        deficit = LIMITE_FREQUENCIA_ATENCAO - percentual
        pontuacao = min(100.0, 45 + deficit * 4)

    if percentual < LIMITE_FREQUENCIA_CRITICA:
        motivos.append(f"Frequência de {percentual:.0f}% — abaixo do limite crítico de {LIMITE_FREQUENCIA_CRITICA:.0f}%")
    elif percentual < LIMITE_FREQUENCIA_ATENCAO:
        motivos.append(f"Frequência de {percentual:.0f}% — em queda, abaixo do ideal")

    registrado_em = freq.get("registrado_em", "")
    if registrado_em:
        idade = datetime.now() - datetime.fromisoformat(registrado_em)
        if idade.days > VALIDADE_FREQUENCIA_DIAS:
            motivos.append(f"Frequência registrada há {idade.days} dias — considere atualizar")

    return pontuacao, motivos


def _livro_nome(db, livro_id) -> str:
    """Busca o nome de um livro pelo id (usado para mostrar qual livro o aluno pegou)."""
    if livro_id is None:
        return "—"
    livro = db.buscar_um("livros", onde={"id": livro_id})
    return livro["nome"] if livro else "—"


def _emprestimos_aluno(db, aluno: dict) -> list[dict]:
    """
    Retorna os empréstimos de biblioteca do aluno (mais recentes primeiro),
    já com o nome do livro resolvido. Vincula por aluno_id sempre que disponível;
    empréstimos antigos (pré-cadastro único), sem aluno_id, ainda são considerados
    via nome, para não perder o sinal do histórico existente.
    """
    nome = (aluno.get("nome") or "").strip().lower()

    def _e_do_aluno(e: dict) -> bool:
        if e.get("aluno_id") is not None:
            return e["aluno_id"] == aluno["id"]
        return nome and (e.get("aluno_nome") or "").strip().lower() == nome

    emprestimos = [e for e in db.buscar("emprestimos") if _e_do_aluno(e)]
    emprestimos.sort(key=lambda e: e.get("data_emprestimo", ""), reverse=True)

    for e in emprestimos:
        e["livro_nome"] = _livro_nome(db, e.get("livro_id"))

    return emprestimos


def _componente_engajamento(db, aluno: dict) -> tuple[float | None, list[str]]:
    """
    Sinal fraco e opcional: uso da biblioteca como proxy de vínculo com a escola.
    Alunos sem NENHUM uso de recursos no período não são necessariamente em risco
    — por isso este componente tem peso baixo e nunca decide o score sozinho.

    Além de olhar SE o aluno pegou algum livro, este componente agora também
    considera QUAL livro está com o aluno no momento: um empréstimo em aberto
    (não devolvido) e muito atrasado é um sinal de possível afastamento da
    escola (o aluno não voltou nem para devolver o livro), então soma um
    pouco mais de risco e aparece nomeado nos motivos.
    """
    limite = (datetime.now() - timedelta(days=JANELA_ENGAJAMENTO_DIAS)).date().isoformat()
    emprestimos = _emprestimos_aluno(db, aluno)
    if not emprestimos:
        return None, []

    usou_recentemente = any(e.get("data_emprestimo", "") >= limite for e in emprestimos)

    em_aberto = [e for e in emprestimos if not e.get("devolvido")]
    hoje = datetime.now().date()
    motivos = []
    pontuacao_atraso = 0.0

    for e in em_aberto:
        prevista = e.get("data_prevista_devolucao")
        if not prevista:
            continue
        try:
            dias_atraso = (hoje - datetime.fromisoformat(prevista).date()).days
        except ValueError:
            continue
        if dias_atraso > 30:
            motivos.append(
                f"Está com o livro \"{e['livro_nome']}\" emprestado há mais de {dias_atraso} dias "
                f"sem devolver — pode indicar afastamento da escola"
            )
            pontuacao_atraso = max(pontuacao_atraso, min(40.0, dias_atraso / 3))

    if not usou_recentemente:
        return min(100.0, 60.0 + pontuacao_atraso), (
            motivos or ["Sem uso de biblioteca/recursos nos últimos 90 dias (sinal fraco)"]
        )

    if not motivos and em_aberto:
        # Empréstimo em dia: não é risco, mas é o motivo pelo qual o score deste
        # componente é 0 — deixamos isso explícito em vez de omitir a informação.
        livro = em_aberto[0]["livro_nome"]
        motivos.append(f"Está com o livro \"{livro}\" emprestado, dentro do prazo (sinal positivo de vínculo)")
    elif not motivos:
        motivos.append("Uso recente da biblioteca/recursos registrado (sinal positivo de vínculo)")

    return round(pontuacao_atraso, 1) if pontuacao_atraso else 0.0, motivos


def calcular_score_aluno(db, ocor_mod, aluno: dict) -> dict:
    """
    Calcula o score de risco de evasão de um aluno, combinando os
    componentes disponíveis com redistribuição de peso para os ausentes.
    """
    freq = _frequencia_atual(db, aluno["id"])

    pontos_freq, motivos_freq = _componente_frequencia(freq)
    pontos_disc, motivos_disc, qtd_ocorrencias = _componente_disciplinar(db, ocor_mod, aluno["id"])
    pontos_eng, motivos_eng = _componente_engajamento(db, aluno)

    componentes = {
        "frequencia":  pontos_freq,
        "disciplinar": pontos_disc,
        "engajamento": pontos_eng,
    }

    disponiveis = {k: v for k, v in componentes.items() if v is not None}

    if not disponiveis:
        score = 0.0
    else:
        peso_total_disponivel = sum(PESOS[k] for k in disponiveis)
        score = sum(v * (PESOS[k] / peso_total_disponivel) for k, v in disponiveis.items())

    motivos = motivos_freq + motivos_disc + motivos_eng
    if not disponiveis:
        motivos = ["Sem dados suficientes (frequência, ocorrências ou biblioteca) para avaliar este aluno."]

    nivel = _nivel_para(score)

    return {
        "score": round(score, 1),
        "nivel": nivel,
        "motivos": motivos,
        "dados_suficientes": bool(disponiveis),
        "componentes": {
            "frequencia":  round(pontos_freq, 1) if pontos_freq is not None else None,
            "disciplinar": round(pontos_disc, 1) if pontos_disc is not None else None,
            "engajamento": round(pontos_eng, 1) if pontos_eng is not None else None,
        },
        "frequencia_atual": freq,
        "ocorrencias_recentes": qtd_ocorrencias,
    }


# ══════════════════════════════════════════════════════════════
# FICHAS DE ALUNOS (visão completa + resumos prontos para apresentar)
# ══════════════════════════════════════════════════════════════

def _formatar_data_br(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _montar_resumos(aluno: dict, r: dict, ocorrencias: list[dict], emprestimos: list[dict]) -> dict:
    """
    Gera alguns textos de resumo prontos, em diferentes tons/finalidades,
    para a coordenação apresentar sobre o aluno sem precisar redigir do zero.
    Nenhum deles esconde as informações complexas — apenas as organiza; os
    dados detalhados continuam disponíveis na própria ficha do aluno.
    """
    nome = aluno.get("nome", "—")
    freq = r.get("frequencia_atual")
    n_oc = len(ocorrencias)
    graves = [o for o in ocorrencias if o.get("tipo_info", {}).get("severidade", 0) >= 3]
    em_aberto = [e for e in emprestimos if not e.get("devolvido")]

    linha_freq = (
        f"frequência de {freq['percentual']:.0f}% (referente a {freq.get('periodo_referencia', '—')})"
        if freq else "sem registro de frequência ainda"
    )

    # --- Geral / visão rápida ---
    geral = (
        f"{nome} ({aluno.get('turma','—')} · {aluno.get('curso','—')}) está com risco de evasão "
        f"\"{r['nivel']['nome']}\" (score {r['score']:.0f}/100). {linha_freq.capitalize()}. "
        f"{n_oc} ocorrência(s) disciplinar(es) registrada(s) no total"
        + (f", sendo {len(graves)} grave(s)." if graves else ".")
    )

    # --- Para reunião com a família ---
    trechos_familia = [f"{nome} está atualmente classificado(a) com risco {r['nivel']['nome'].lower()} de evasão escolar."]
    if freq:
        trechos_familia.append(f"A frequência mais recente registrada é de {freq['percentual']:.0f}%.")
    else:
        trechos_familia.append("Ainda não há um registro de frequência lançado no sistema para este aluno.")
    if n_oc:
        trechos_familia.append(f"Há {n_oc} ocorrência(s) disciplinar(es) no histórico, que podem ser detalhadas durante a conversa.")
    else:
        trechos_familia.append("Não há ocorrências disciplinares registradas.")
    if em_aberto:
        trechos_familia.append(f"O aluno está com {len(em_aberto)} livro(s) da biblioteca ainda não devolvido(s).")
    familia = " ".join(trechos_familia)

    # --- Para conselho de classe ---
    motivos_txt = "; ".join(r["motivos"]) if r["motivos"] else "nenhum sinal de risco identificado no momento"
    conselho = (
        f"Aluno: {nome} — Turma: {aluno.get('turma','—')} ({aluno.get('curso','—')}).\n"
        f"Score de risco: {r['score']:.0f}/100 — nível {r['nivel']['nome']}.\n"
        f"Componentes: frequência={r['componentes']['frequencia']}, "
        f"disciplinar={r['componentes']['disciplinar']}, engajamento={r['componentes']['engajamento']}.\n"
        f"Motivos apontados pelo sistema: {motivos_txt}."
    )

    # --- Alerta objetivo (para ação rápida da coordenação) ---
    if r["nivel"]["id"] in ("critico", "alto"):
        alerta = (
            f"⚠ {nome} ({aluno.get('turma','—')}) precisa de atenção prioritária — "
            f"risco {r['nivel']['nome'].lower()} de evasão. Principal motivo: "
            f"{r['motivos'][0] if r['motivos'] else 'combinação de fatores'}. Sugestão: agendar conversa esta semana."
        )
    else:
        alerta = f"{nome} não está entre os casos prioritários no momento (risco {r['nivel']['nome'].lower()})."

    return {
        "geral":    geral,
        "familia":  familia,
        "conselho": conselho,
        "alerta":   alerta,
    }


@blueprint.route("/fichas")
@perfil_obrigatorio("coordenadora", "admin")
def fichas():
    ocor_mod = _modulo_ocorrencias()
    return render_template("evasao/fichas.html", turmas=ocor_mod._carregar_turmas())


@blueprint.route("/api/fichas")
@perfil_obrigatorio("coordenadora", "admin")
def api_fichas():
    """
    Retorna todos os alunos agrupados por turma, com todas as informações
    relevantes (score, frequência, ocorrências, empréstimos de biblioteca)
    e resumos prontos para apresentação — sem omitir os dados complexos.
    """
    db = _get_db()
    ocor_mod = _modulo_ocorrencias()

    busca = request.args.get("busca", "").strip()
    turma_filtro = request.args.get("turma", "").strip()

    alunos = cadastro_alunos.buscar(busca=busca, turma=turma_filtro, db=db)

    grupos: dict[str, dict] = {}

    for aluno in alunos:
        r = calcular_score_aluno(db, ocor_mod, aluno)

        ocorrencias = db.buscar("ocorrencias", onde={"aluno_id": aluno["id"]}, ordenar_por="data_hora")
        ocorrencias = list(reversed(ocorrencias))
        for o in ocorrencias:
            o["tipo_info"] = ocor_mod._tipo_info(o.get("tipo", "outro"), db=db)

        emprestimos = _emprestimos_aluno(db, aluno)
        for e in emprestimos:
            e["data_emprestimo_br"] = _formatar_data_br(e.get("data_emprestimo"))
            e["data_prevista_devolucao_br"] = _formatar_data_br(e.get("data_prevista_devolucao"))

        resumos = _montar_resumos(aluno, r, ocorrencias, emprestimos)

        ficha = {
            "id":        aluno["id"],
            "nome":      aluno["nome"],
            "serie":     aluno.get("serie", "—"),
            "turma":     aluno.get("turma", "—"),
            "curso":     aluno.get("curso", "—"),
            "tecnico_ti": aluno.get("tecnico_ti", False),
            "score":     r["score"],
            "nivel":     r["nivel"],
            "motivos":   r["motivos"],
            "componentes": r["componentes"],
            "dados_suficientes": r["dados_suficientes"],
            "frequencia_atual": r["frequencia_atual"],
            "ocorrencias": ocorrencias,
            "emprestimos": emprestimos,
            "resumos":   resumos,
        }

        chave = aluno.get("turma", "—")
        if chave not in grupos:
            grupos[chave] = {
                "turma": chave,
                "curso": aluno.get("curso", "—"),
                "serie": aluno.get("serie", "—"),
                "alunos": [],
            }
        grupos[chave]["alunos"].append(ficha)

    resultado = sorted(grupos.values(), key=lambda g: g["turma"])
    for g in resultado:
        g["alunos"].sort(key=lambda a: a["nome"])

    return jsonify(resultado)


# ══════════════════════════════════════════════════════════════
# ROTAS
# ══════════════════════════════════════════════════════════════

@blueprint.route("/")
@perfil_obrigatorio("coordenadora", "admin")
def index():
    ocor_mod = _modulo_ocorrencias()
    return render_template("evasao/index.html", turmas=ocor_mod._carregar_turmas())


@blueprint.route("/api/status")
@perfil_obrigatorio("coordenadora", "admin")
def api_status():
    db = _get_db()
    ocor_mod = _modulo_ocorrencias()
    alunos = cadastro_alunos.buscar(db=db)

    contagem = {"critico": 0, "alto": 0, "moderado": 0, "baixo": 0}
    avaliados = 0
    for aluno in alunos:
        resultado = calcular_score_aluno(db, ocor_mod, aluno)
        if resultado["dados_suficientes"]:
            avaliados += 1
        contagem[resultado["nivel"]["id"]] += 1

    return jsonify({
        "total_alunos": len(alunos),
        "avaliados":    avaliados,
        "criticos":     contagem["critico"],
        "altos":        contagem["alto"],
        "moderados":    contagem["moderado"],
        "baixos":       contagem["baixo"],
    })


@blueprint.route("/api/ranking")
@perfil_obrigatorio("coordenadora", "admin")
def api_ranking():
    """
    Query params:
      busca — nome do aluno (parcial)
      turma — filtro exato de turma
      nivel — critico | alto | moderado | baixo
    Retorna todos os alunos ordenados do maior para o menor risco.
    """
    db = _get_db()
    ocor_mod = _modulo_ocorrencias()

    busca = request.args.get("busca", "").strip()
    turma = request.args.get("turma", "").strip()
    nivel_filtro = request.args.get("nivel", "").strip()

    alunos = cadastro_alunos.buscar(busca=busca, turma=turma, db=db)

    resultado = []
    for aluno in alunos:
        r = calcular_score_aluno(db, ocor_mod, aluno)
        if nivel_filtro and r["nivel"]["id"] != nivel_filtro:
            continue

        resultado.append({
            "id":       aluno["id"],
            "nome":     aluno["nome"],
            "serie":    aluno.get("serie", "—"),
            "turma":    aluno.get("turma", "—"),
            "curso":    aluno.get("curso", "—"),
            "score":    r["score"],
            "nivel":    r["nivel"],
            "motivos":  r["motivos"],
            "dados_suficientes": r["dados_suficientes"],
        })

    resultado.sort(key=lambda a: a["score"], reverse=True)
    return jsonify(resultado)


@blueprint.route("/api/alunos/<int:aluno_id>/detalhe")
@perfil_obrigatorio("coordenadora", "admin")
def api_detalhe_aluno(aluno_id: int):
    db = _get_db()
    ocor_mod = _modulo_ocorrencias()

    aluno = cadastro_alunos.buscar_um(aluno_id, db=db)
    if not aluno:
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404

    r = calcular_score_aluno(db, ocor_mod, aluno)

    ocorrencias = db.buscar("ocorrencias", onde={"aluno_id": aluno_id}, ordenar_por="data_hora")
    ocorrencias = list(reversed(ocorrencias))
    for o in ocorrencias:
        o["tipo_info"] = ocor_mod._tipo_info(o.get("tipo", "outro"), db=db)

    emprestimos = _emprestimos_aluno(db, aluno)

    return jsonify({
        "ok": True,
        "aluno": {
            "id":     aluno["id"],
            "nome":   aluno["nome"],
            "serie":  aluno.get("serie", "—"),
            "turma":  aluno.get("turma", "—"),
            "curso":  aluno.get("curso", "—"),
        },
        "score":          r["score"],
        "nivel":          r["nivel"],
        "motivos":        r["motivos"],
        "componentes":    r["componentes"],
        "pesos":          PESOS,
        "frequencia_atual": r["frequencia_atual"],
        "ocorrencias":    ocorrencias[:10],
        "emprestimos":    emprestimos[:10],
    })


@blueprint.route("/api/alunos/<int:aluno_id>/frequencia", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_registrar_frequencia(aluno_id: int):
    """
    Body: percentual (0-100), periodo_referencia (ex: 'ago/2026', opcional).
    Cada chamada cria um NOVO registro (histórico preservado); o score
    sempre usa o mais recente.
    """
    db = _get_db()
    aluno = cadastro_alunos.buscar_um(aluno_id, db=db)
    if not aluno:
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404

    dados = request.get_json(force=True) or {}
    try:
        percentual = float(dados.get("percentual"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "Informe um percentual de frequência válido."}), 400

    if not (0 <= percentual <= 100):
        return jsonify({"ok": False, "erro": "O percentual deve estar entre 0 e 100."}), 400

    periodo = (dados.get("periodo_referencia") or "").strip() or datetime.now().strftime("%m/%Y")

    from core.auth import usuario_logado
    usuario = usuario_logado()

    registro = db.inserir("evasao_frequencia", {
        "aluno_id":            aluno_id,
        "percentual":          percentual,
        "periodo_referencia":  periodo,
        "registrado_por":      usuario["nome"] if usuario else "",
        "registrado_em":       datetime.now().isoformat(),
    })

    ocor_mod = _modulo_ocorrencias()
    novo_resultado = calcular_score_aluno(db, ocor_mod, aluno)

    if novo_resultado["nivel"]["id"] in ("alto", "critico"):
        notificar_se_ausente(
            modulo="evasao", tipo="risco_elevado", referencia_id=aluno_id,
            titulo=f"Risco {novo_resultado['nivel']['nome'].lower()} de evasão — {aluno.get('nome','')}",
            mensagem=f"{aluno.get('turma','—')} · score {novo_resultado['score']:.0f}/100",
            url="/evasao/fichas", destinatario_tipo="perfil", destinatario_valor="admin",
        )

    return jsonify({
        "ok": True,
        "registro": registro,
        "novo_score": novo_resultado["score"],
        "novo_nivel": novo_resultado["nivel"],
    }), 201
