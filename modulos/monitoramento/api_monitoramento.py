
import json
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import Counter
from flask import Blueprint, render_template, jsonify, request
from core.auth import perfil_obrigatorio

blueprint = Blueprint("monitoramento", __name__,
                      template_folder="../../templates/monitoramento")

BASE = Path(__file__).resolve().parent

MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez"]


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    from core.config_path import carregar_config
    cfg = carregar_config(BASE.parent.parent)
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

def _nomes_meses_recentes(qtd: int) -> list[str]:
    """Retorna os últimos N meses no formato 'jan/25', em português, mais antigo primeiro."""
    hoje = date.today().replace(day=1)
    meses = []
    for i in range(qtd - 1, -1, -1):
        ano = hoje.year
        mes = hoje.month - i
        while mes <= 0:
            mes += 12
            ano -= 1
        meses.append(f"{MESES_PT[mes - 1]}/{str(ano)[2:]}")
    return meses

def _chaves_meses_recentes(qtd: int) -> list[str]:
    """Retorna as chaves 'YYYY-MM' correspondentes aos últimos N meses, mais antigo primeiro."""
    hoje = date.today().replace(day=1)
    chaves = []
    for i in range(qtd - 1, -1, -1):
        ano, mes = hoje.year, hoje.month - i
        while mes <= 0:
            mes += 12; ano -= 1
        chaves.append(f"{ano:04d}-{mes:02d}")
    return chaves

def _chave_mes(iso_data: str) -> str:
    """Extrai 'YYYY-MM' de uma string ISO de data/data_hora."""
    return (iso_data or "")[:7]

def _periodo_param() -> str:
    """Lê o parâmetro ?periodo=mes|tudo da query string. Padrão: 'tudo'."""
    p = request.args.get("periodo", "tudo").strip().lower()
    return p if p in ("mes", "tudo") else "tudo"


def _turnos_disponiveis_para_usuario() -> list[str]:
    """Turnos que o usuário logado pode selecionar no filtro: a interseção
    entre os turnos que existem na escola e o escopo do seu cargo (se
    ele tiver "todos", são todos os turnos existentes)."""
    from core.alunos import _escopo_turno_da_requisicao
    from core.cargos import turnos_existentes
    todos = turnos_existentes()
    escopo = _escopo_turno_da_requisicao()
    return [t for t in todos if t in escopo] if escopo else todos


def _turno_param() -> str | None:
    """Lê ?turno=<nome>, validando contra o que o usuário pode ver.
    Retorna None (sem filtro extra de turno) se ausente/inválido/"todos"."""
    valor = (request.args.get("turno") or "").strip()
    disponiveis = _turnos_disponiveis_para_usuario()
    return valor if valor and valor in disponiveis else None


def _no_escopo(registros: list[dict], campo: str = "turma") -> list[dict]:
    """Filtra pelo escopo de turno do usuário logado E, se presente, pelo
    ?turno= escolhido manualmente no seletor da tela."""
    from core.alunos import _escopo_turno_da_requisicao, _turno_por_turma
    turno_por_turma = _turno_por_turma()
    escopo = _escopo_turno_da_requisicao()
    turno_selecionado = _turno_param()

    resultado = registros
    if escopo:
        resultado = [r for r in resultado if turno_por_turma.get(r.get(campo)) in escopo]
    if turno_selecionado:
        resultado = [r for r in resultado if turno_por_turma.get(r.get(campo)) == turno_selecionado]
    return resultado


def _mapa_usuarios(db) -> dict[int, str]:
    """Mapa id → nome de todos os usuários, para resolver nomes ausentes em registros antigos."""
    return {u["id"]: u["nome"] for u in db.buscar("usuarios")}


@blueprint.route("/api/turnos")
@perfil_obrigatorio("coordenadora", "admin")
def api_turnos():
    """Turnos que este usuário pode selecionar no filtro dos gráficos."""
    return jsonify({"turnos": _turnos_disponiveis_para_usuario()})


@blueprint.route("/")
@perfil_obrigatorio("coordenadora", "admin")
def index():
    return render_template("monitoramento/index.html")


@blueprint.route("/api/geral")
@perfil_obrigatorio("coordenadora", "admin")
def api_geral():
    db = _get_db()
    hoje_iso = date.today().isoformat()
    inicio_mes = date.today().replace(day=1).isoformat()

    reservas = db.buscar("reservas")
    reservas_ativas_mes = [r for r in reservas
                           if not r.get("devolvido") and r.get("data_reserva", "") >= inicio_mes]

    emprestimos = db.buscar("emprestimos")
    emprestimos_ativos = [e for e in emprestimos if not e.get("devolvido")]
    emprestimos_atrasados = [e for e in emprestimos_ativos
                             if e.get("data_prevista_devolucao", "") < hoje_iso]

    from core.alunos import buscar as buscar_alunos
    alunos = buscar_alunos(db=db)  # já aplica o escopo de turno automaticamente
    alunos = _no_escopo(alunos)     # + o filtro manual de ?turno=, se houver
    ids_no_escopo = {a["id"] for a in alunos}

    ocorrencias = [o for o in db.buscar("ocorrencias") if o.get("aluno_id") in ids_no_escopo]
    ocorrencias_mes = [o for o in ocorrencias if o.get("data_hora", "")[:10] >= inicio_mes]

    limite_alerta = (datetime.now() - timedelta(days=30)).isoformat()

    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from modulos.ocorrencias.api_ocorrencias import _e_elogio

    contagem_por_aluno = Counter(
        o["aluno_id"] for o in ocorrencias
        if not _e_elogio(o.get("tipo", ""), db=db) and o.get("data_hora", "") >= limite_alerta
    )
    alunos_em_alerta = sum(1 for c in contagem_por_aluno.values() if c >= 3)

    leituras_iot = db.buscar("leituras_iot")

    # Distinção por turno: um resumo rápido lado a lado de cada turno que
    # o usuário pode ver (só aparece de fato quando há mais de um turno
    # no escopo — pra uma coordenadora restrita a um só turno não faz
    # sentido "comparar" com ela mesma).
    por_turno = []
    turnos = _turnos_disponiveis_para_usuario()
    if len(turnos) > 1:
        from core.alunos import carregar_turmas
        turno_por_turma_map = {t["turma"]: t.get("turno") for t in carregar_turmas()}
        for turno in turnos:
            alunos_turno = [a for a in alunos if turno_por_turma_map.get(a.get("turma")) == turno]
            ids_turno = {a["id"] for a in alunos_turno}
            ocor_turno_mes = [o for o in ocorrencias_mes if o.get("aluno_id") in ids_turno]
            por_turno.append({
                "turno": turno,
                "alunos": len(alunos_turno),
                "ocorrencias_mes": len(ocor_turno_mes),
            })

    return jsonify({
        "reservas_ativas_mes":    len(reservas_ativas_mes),
        "livros_total":           len(db.buscar("livros")),
        "emprestimos_ativos":     len(emprestimos_ativos),
        "emprestimos_atrasados":  len(emprestimos_atrasados),
        "ocorrencias_mes":        len(ocorrencias_mes),
        "alunos_cadastrados":     len(alunos),
        "alunos_em_alerta":       alunos_em_alerta,
        "leituras_iot_total":     len(leituras_iot),
        "por_turno":              por_turno,
    })


@blueprint.route("/api/agendamento")
@perfil_obrigatorio("coordenadora", "admin")
def api_agendamento():
    periodo = _periodo_param()
    db = _get_db()
    reservas = [r for r in db.buscar("reservas") if not r.get("devolvido")]

    if periodo == "mes":
        inicio_mes = date.today().replace(day=1).isoformat()
        reservas = [r for r in reservas if r.get("data_reserva", "") >= inicio_mes]

    usuarios_map = _mapa_usuarios(db)

    def nome_professor(r: dict) -> str:
        nome = r.get("professor_nome")
        if nome:
            return nome
        nome = usuarios_map.get(r.get("professor_id"))
        return nome or "Professor removido"

    por_recurso = Counter(r.get("recurso_nome") or "Recurso removido" for r in reservas)
    top_recursos = por_recurso.most_common(6)

    por_professor = Counter(nome_professor(r) for r in reservas)
    top_professores = por_professor.most_common(5)

    return jsonify({
        "periodo":         periodo,
        "total_reservas":  len(reservas),
        "top_recursos":    [{"nome": n, "total": t} for n, t in top_recursos],
        "top_professores": [{"nome": n, "total": t} for n, t in top_professores],
    })


@blueprint.route("/api/biblioteca")
@perfil_obrigatorio("coordenadora", "admin")
def api_biblioteca():
    periodo = _periodo_param()
    db = _get_db()
    livros = {l["id"]: l for l in db.buscar("livros")}
    emprestimos = db.buscar("emprestimos")

    emprestimos_filtrados = emprestimos
    if periodo == "mes":
        inicio_mes = date.today().replace(day=1).isoformat()
        emprestimos_filtrados = [e for e in emprestimos if e.get("data_emprestimo", "") >= inicio_mes]

    contagem_livro = Counter(e["livro_id"] for e in emprestimos_filtrados)
    top_livros = []
    for livro_id, total in contagem_livro.most_common(6):
        livro = livros.get(livro_id)
        if livro:
            top_livros.append({"nome": livro["nome"], "autor": livro.get("autor", ""), "total": total})

    hoje_iso = date.today().isoformat()
    atrasados = [e for e in emprestimos
                if not e.get("devolvido") and e.get("data_prevista_devolucao", "") < hoje_iso]

    meses = _nomes_meses_recentes(6)
    chaves_meses = _chaves_meses_recentes(6)
    contagem_mes = Counter(_chave_mes(e.get("data_emprestimo", "")) for e in emprestimos)
    serie_mensal = [contagem_mes.get(k, 0) for k in chaves_meses]

    return jsonify({
        "periodo":            periodo,
        "total_livros":       len(livros),
        "total_emprestimos":  len(emprestimos_filtrados),
        "total_atrasados":    len(atrasados),
        "top_livros":         top_livros,
        "serie_mensal":       {"labels": meses, "valores": serie_mensal},
    })


@blueprint.route("/api/ocorrencias")
@perfil_obrigatorio("coordenadora", "admin")
def api_ocorrencias():
    periodo = _periodo_param()
    db = _get_db()
    from core.alunos import buscar as buscar_alunos
    alunos_lista = _no_escopo(buscar_alunos(db=db))
    alunos = {a["id"]: a for a in alunos_lista}
    ocorrencias = [o for o in db.buscar("ocorrencias") if o.get("aluno_id") in alunos]

    from core import tipos_ocorrencia as tipos_mod
    from modulos.ocorrencias.api_ocorrencias import normalizar_tipo, _e_elogio

    ocorrencias_filtradas = ocorrencias
    if periodo == "mes":
        inicio_mes = date.today().replace(day=1).isoformat()
        ocorrencias_filtradas = [o for o in ocorrencias if o.get("data_hora", "")[:10] >= inicio_mes]

    tipos_map = tipos_mod.mapa(db=db)
    por_tipo = Counter(normalizar_tipo(o.get("tipo", "outro"), db=db) for o in ocorrencias_filtradas)
    tipos_dados = [
        {"nome": tipos_map.get(t, {}).get("nome", t), "total": c}
        for t, c in por_tipo.most_common()
    ]

    por_turma = Counter(
        alunos[o["aluno_id"]].get("turma") or "Sem turma"
        for o in ocorrencias_filtradas
        if not _e_elogio(o.get("tipo", ""), db=db) and o.get("aluno_id") in alunos
    )
    top_turmas = [{"nome": n, "total": t} for n, t in por_turma.most_common(6)]

    # Distinção por turno (ver api_geral) — só aparece quando o usuário
    # pode ver mais de um turno.
    por_turno = []
    turnos = _turnos_disponiveis_para_usuario()
    if len(turnos) > 1:
        contagem_turno = Counter(
            alunos[o["aluno_id"]].get("turno_resolvido")
            for o in ocorrencias_filtradas
            if not _e_elogio(o.get("tipo", ""), db=db) and o.get("aluno_id") in alunos
        )
        por_turno = [{"turno": t, "total": contagem_turno.get(t, 0)} for t in turnos]

    meses = _nomes_meses_recentes(6)
    chaves_meses = _chaves_meses_recentes(6)
    contagem_mes = Counter(
        _chave_mes(o.get("data_hora", "")) for o in ocorrencias if not _e_elogio(o.get("tipo", ""))
    )
    serie_mensal = [contagem_mes.get(k, 0) for k in chaves_meses]

    return jsonify({
        "periodo":       periodo,
        "total":         len(ocorrencias_filtradas),
        "por_tipo":      tipos_dados,
        "top_turmas":    top_turmas,
        "por_turno":     por_turno,
        "serie_mensal":  {"labels": meses, "valores": serie_mensal},
    })


@blueprint.route("/api/iot")
@perfil_obrigatorio("coordenadora", "admin")
def api_iot():
    db = _get_db()
    leituras = db.buscar("leituras_iot")

    limite_30d = (datetime.now() - timedelta(days=30)).isoformat()

    agua = [l for l in leituras if l.get("tipo") == "agua" and l.get("data_hora", "") >= limite_30d]
    portao_eventos = [l for l in leituras if l.get("tipo") == "portao_status" and l.get("data_hora", "") >= limite_30d]
    ac_eventos = [l for l in leituras if l.get("tipo") == "ac_status" and l.get("data_hora", "") >= limite_30d]

    por_sensor: dict[str, dict] = {}
    for l in sorted(agua, key=lambda x: x.get("data_hora", "")):
        por_sensor[l["sensor_id"]] = l

    return jsonify({
        "agua_ultimas": [
            {"sensor_id": sid, "valor": l["valor"], "data_hora": l["data_hora"]}
            for sid, l in por_sensor.items()
        ],
        "total_eventos_portao_30d": len(portao_eventos),
        "total_eventos_ac_30d":     len(ac_eventos),
        "total_leituras_agua_30d":  len(agua),
    })
