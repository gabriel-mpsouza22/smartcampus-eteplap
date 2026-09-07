"""
Módulo: Controle de Visitantes
-------------------------------
Duas interfaces sobre a mesma fonte de verdade (tabela `visitantes_visitas`):

- Portaria (`/visitantes/portaria`): operação — identificar, registrar,
  confirmar, voltar. Poucos campos, sem confirmação extra, foco automático.
- Central de Visitantes (`/visitantes/central`): consulta/acompanhamento
  para Secretaria, Coordenação e Direção — quem está no campus agora,
  busca, histórico por visitante, indicadores e alertas.

Toda alteração relevante também grava um evento imutável em
`visitantes_eventos` (append-only) — é a fonte de verdade para auditoria
e para a linha do tempo mostrada na Central.

Princípio de dados invisíveis: o usuário só informa o que só ele sabe
(nome, destino, motivo). Data, horário, permanência e responsável pelo
registro são sempre calculados/preenchidos pelo sistema.
"""

import json
from pathlib import Path
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, jsonify, request

from core.auth import perfil_obrigatorio, usuario_logado
from core.notificacoes import notificar_se_ausente, resolver as resolver_notificacao

blueprint = Blueprint("visitantes", __name__, template_folder="../../templates/visitantes")

BASE = Path(__file__).resolve().parent

PERFIS_CONSULTA = ("secretaria", "coordenadora", "admin")
PERFIS_PORTARIA = ("portaria", "admin")
PERFIS_TODOS = ("portaria", "secretaria", "coordenadora", "admin")

MOTIVOS = [
    {"id": "reuniao",     "label": "Reunião"},
    {"id": "atendimento", "label": "Atendimento"},
    {"id": "entrega",     "label": "Entrega"},
    {"id": "manutencao",  "label": "Manutenção"},
    {"id": "servico",     "label": "Prestação de serviço"},
    {"id": "outro",       "label": "Outro"},
]

DESTINOS = [
    "Direção", "Coordenação", "Secretaria", "Biblioteca",
    "Professores", "Manutenção/Infraestrutura", "Outro setor",
]

# Tempo (em minutos) sem saída registrada a partir do qual a visita
# passa a aparecer na seção de alerta da Central — não é um erro,
# apenas algo que pode merecer verificação.
LIMIAR_ALERTA_MINUTOS = 180


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    from core.config_path import carregar_config
    cfg = carregar_config(BASE.parent.parent)
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")


def _garantir_tabelas(db) -> None:
    if not db.tabela_existe("visitantes_visitas"):
        db.criar_tabela("visitantes_visitas", [
            {"nome": "id",                  "tipo": "INTEIRO",   "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
            {"nome": "visitante_nome",      "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "visitante_documento", "tipo": "TEXTO",     "modificadores": []},
            {"nome": "destino",             "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "motivo",              "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "motivo_detalhe",      "tipo": "TEXTO",     "modificadores": []},
            {"nome": "observacao",          "tipo": "TEXTO",     "modificadores": []},
            {"nome": "status",              "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "entrada_em",          "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
            {"nome": "saida_em",            "tipo": "DATA_HORA", "modificadores": []},
            {"nome": "registrado_por",      "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "saida_registrada_por","tipo": "TEXTO",     "modificadores": []},
            {"nome": "criado_em",           "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
        ])
    if not db.tabela_existe("visitantes_eventos"):
        db.criar_tabela("visitantes_eventos", [
            {"nome": "id",        "tipo": "INTEIRO",   "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
            {"nome": "visita_id", "tipo": "INTEIRO",   "modificadores": ["NAO_NULO"]},
            {"nome": "tipo",      "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "autor",     "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "detalhe",   "tipo": "TEXTO",     "modificadores": []},
            {"nome": "criado_em", "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
        ])


def _registrar_evento(db, visita_id: int, tipo: str, autor: str, detalhe: str = "") -> None:
    db.inserir("visitantes_eventos", {
        "visita_id": visita_id, "tipo": tipo, "autor": autor,
        "detalhe": detalhe, "criado_em": datetime.now().isoformat(),
    })


def _motivo_label(motivo_id: str) -> str:
    return next((m["label"] for m in MOTIVOS if m["id"] == motivo_id), motivo_id)


def _permanencia_min(entrada_iso: str, saida_iso: str | None) -> int:
    inicio = datetime.fromisoformat(entrada_iso)
    fim = datetime.fromisoformat(saida_iso) if saida_iso else datetime.now()
    return max(0, int((fim - inicio).total_seconds() // 60))


def _formatar_permanencia(minutos: int) -> str:
    h, m = divmod(minutos, 60)
    return f"{h}h{m:02d}" if h else f"{m} min"


def _serializar(v: dict) -> dict:
    v = dict(v)
    minutos = _permanencia_min(v["entrada_em"], v.get("saida_em"))
    v["motivo_label"] = _motivo_label(v["motivo"])
    v["permanencia_min"] = minutos
    v["permanencia_label"] = _formatar_permanencia(minutos)
    v["em_alerta"] = v["status"] == "no_campus" and minutos >= LIMIAR_ALERTA_MINUTOS
    return v


# ---------------------------------------------------------------- Páginas

@blueprint.route("/portaria")
@perfil_obrigatorio(*PERFIS_PORTARIA)
def pagina_portaria():
    return render_template("visitantes/portaria.html", motivos=MOTIVOS, destinos=DESTINOS)


@blueprint.route("/central")
@perfil_obrigatorio(*PERFIS_CONSULTA)
def pagina_central():
    return render_template("visitantes/central.html", destinos=DESTINOS)


# -------------------------------------------------------------- Listagens

@blueprint.route("/api/visitas")
@perfil_obrigatorio(*PERFIS_TODOS)
def api_listar_visitas():
    """
    Query: status ('no_campus' | 'todas', padrão 'no_campus'),
    data (YYYY-MM-DD, filtra pela data de entrada — só usado quando
    status=todas), destino, q (busca por nome).
    """
    db = _get_db()
    _garantir_tabelas(db)

    status_filtro = request.args.get("status", "no_campus")
    destino_filtro = request.args.get("destino", "").strip()
    data_filtro = request.args.get("data", "").strip()
    termo = request.args.get("q", "").strip().lower()

    visitas = db.buscar("visitantes_visitas")

    if status_filtro == "no_campus":
        visitas = [v for v in visitas if v["status"] == "no_campus"]
    elif status_filtro == "saiu":
        visitas = [v for v in visitas if v["status"] == "finalizada"]

    if data_filtro:
        visitas = [v for v in visitas if v["entrada_em"][:10] == data_filtro]

    if destino_filtro:
        visitas = [v for v in visitas if v["destino"] == destino_filtro]

    if termo:
        visitas = [v for v in visitas if termo in v["visitante_nome"].lower()]

    visitas.sort(key=lambda v: v["entrada_em"], reverse=True)
    return jsonify([_serializar(v) for v in visitas])


@blueprint.route("/api/visitas/<int:visita_id>")
@perfil_obrigatorio(*PERFIS_TODOS)
def api_detalhe_visita(visita_id: int):
    db = _get_db()
    _garantir_tabelas(db)
    visita = db.buscar_um("visitantes_visitas", onde={"id": visita_id})
    if not visita:
        return jsonify({"ok": False, "erro": "Visita não encontrada."}), 404

    historico = [v for v in db.buscar("visitantes_visitas")
                 if v["visitante_nome"].lower() == visita["visitante_nome"].lower()]
    historico.sort(key=lambda v: v["entrada_em"], reverse=True)

    return jsonify({
        "ok": True,
        "visita": _serializar(visita),
        "historico": [_serializar(v) for v in historico],
        "total_visitas": len(historico),
    })


@blueprint.route("/api/visitas/<int:visita_id>/historico-eventos")
@perfil_obrigatorio(*PERFIS_CONSULTA, "portaria")
def api_historico_eventos(visita_id: int):
    db = _get_db()
    _garantir_tabelas(db)
    if not db.buscar_um("visitantes_visitas", onde={"id": visita_id}):
        return jsonify({"ok": False, "erro": "Visita não encontrada."}), 404
    eventos = db.buscar("visitantes_eventos", onde={"visita_id": visita_id}, ordenar_por="id")
    return jsonify(eventos)


@blueprint.route("/api/visitantes/buscar")
@perfil_obrigatorio(*PERFIS_TODOS)
def api_buscar_visitante():
    """
    Autocomplete usado na Portaria ao digitar o nome: identifica
    visitantes recorrentes sem preencher nada automaticamente — só
    devolve o histórico para reduzir digitação e apoiar reconhecimento.
    """
    termo = request.args.get("q", "").strip().lower()
    if len(termo) < 2:
        return jsonify([])

    db = _get_db()
    _garantir_tabelas(db)
    visitas = [v for v in db.buscar("visitantes_visitas") if termo in v["visitante_nome"].lower()]

    por_nome: dict[str, list[dict]] = {}
    for v in visitas:
        por_nome.setdefault(v["visitante_nome"], []).append(v)

    resultado = []
    for nome, lista in por_nome.items():
        lista.sort(key=lambda v: v["entrada_em"], reverse=True)
        ativa = next((v for v in lista if v["status"] == "no_campus"), None)
        resultado.append({
            "nome": nome,
            "visitas_anteriores": len(lista),
            "ultima_visita": lista[0]["entrada_em"],
            "destino_ultima": lista[0]["destino"],
            "tem_visita_ativa": ativa is not None,
            "visita_ativa_id": ativa["id"] if ativa else None,
        })
    resultado.sort(key=lambda r: r["visitas_anteriores"], reverse=True)
    return jsonify(resultado[:8])


# ---------------------------------------------------------------- Registro

@blueprint.route("/api/visitas", methods=["POST"])
@perfil_obrigatorio(*PERFIS_PORTARIA)
def api_registrar_entrada():
    """
    Body: nome, destino, motivo (id de MOTIVOS), motivo_detalhe (se
    motivo == 'outro'), documento (opcional), observacao (opcional).
    """
    usuario = usuario_logado()
    dados = request.get_json(force=True) or {}

    nome = (dados.get("nome") or "").strip()
    destino = (dados.get("destino") or "").strip()
    motivo = (dados.get("motivo") or "").strip()
    motivo_detalhe = (dados.get("motivo_detalhe") or "").strip()
    documento = (dados.get("documento") or "").strip()
    observacao = (dados.get("observacao") or "").strip()

    if not nome or not destino or not motivo:
        return jsonify({"ok": False, "erro": "Informe nome, destino e motivo da visita."}), 400
    if motivo not in {m["id"] for m in MOTIVOS}:
        return jsonify({"ok": False, "erro": "Motivo inválido."}), 400

    db = _get_db()
    _garantir_tabelas(db)

    # Proteção contra duplicidade (item 14): mesmo nome já com visita ativa.
    ativa = next((v for v in db.buscar("visitantes_visitas", onde={"status": "no_campus"})
                  if v["visitante_nome"].strip().lower() == nome.lower()), None)
    if ativa:
        return jsonify({
            "ok": False,
            "erro": f"{nome} já possui uma entrada ativa.",
            "visita_ativa": _serializar(ativa),
        }), 409

    agora = datetime.now().isoformat()
    registro = db.inserir("visitantes_visitas", {
        "visitante_nome":       nome,
        "visitante_documento":  documento or None,
        "destino":              destino,
        "motivo":               motivo,
        "motivo_detalhe":       motivo_detalhe or None,
        "observacao":           observacao or None,
        "status":               "no_campus",
        "entrada_em":           agora,
        "saida_em":             None,
        "registrado_por":       usuario["nome"],
        "saida_registrada_por": None,
        "criado_em":            agora,
    })

    _registrar_evento(db, registro["id"], "entrada", usuario["nome"],
                       f"Destino: {destino}. Motivo: {_motivo_label(motivo)}.")

    return jsonify({"ok": True, "visita": _serializar(registro)}), 201


@blueprint.route("/api/visitas/<int:visita_id>/saida", methods=["POST"])
@perfil_obrigatorio(*PERFIS_PORTARIA)
def api_registrar_saida(visita_id: int):
    usuario = usuario_logado()
    db = _get_db()
    _garantir_tabelas(db)

    visita = db.buscar_um("visitantes_visitas", onde={"id": visita_id})
    if not visita:
        return jsonify({"ok": False, "erro": "Visita não encontrada."}), 404
    if visita["status"] != "no_campus":
        return jsonify({"ok": False, "erro": "Esta visita já foi encerrada."}), 409

    agora = datetime.now().isoformat()
    qtd = db.atualizar("visitantes_visitas", {
        "status":               "finalizada",
        "saida_em":             agora,
        "saida_registrada_por": usuario["nome"],
    }, onde={"id": visita_id, "status": "no_campus"})

    if qtd == 0:
        return jsonify({"ok": False, "erro": "Esta visita já foi encerrada por outra pessoa."}), 409

    _registrar_evento(db, visita_id, "saida", usuario["nome"])

    resolver_notificacao(modulo="visitantes", tipo="alerta_permanencia", referencia_id=visita_id)
    resolver_notificacao(modulo="visitantes", tipo="alerta_permanencia_secretaria", referencia_id=visita_id)

    atualizada = db.buscar_um("visitantes_visitas", onde={"id": visita_id})
    return jsonify({"ok": True, "visita": _serializar(atualizada)})


@blueprint.route("/api/visitas/<int:visita_id>/corrigir", methods=["POST"])
@perfil_obrigatorio(*PERFIS_CONSULTA)
def api_corrigir_visita(visita_id: int):
    """
    Correção manual (item 25/17 — auditoria): Secretaria/Coordenação
    podem ajustar destino/observação de um registro. A alteração fica
    registrada no histórico de auditoria; nada é apagado silenciosamente.
    """
    usuario = usuario_logado()
    dados = request.get_json(force=True, silent=True) or {}
    motivo_correcao = (dados.get("motivo_correcao") or "").strip()

    db = _get_db()
    _garantir_tabelas(db)
    visita = db.buscar_um("visitantes_visitas", onde={"id": visita_id})
    if not visita:
        return jsonify({"ok": False, "erro": "Visita não encontrada."}), 404
    if not motivo_correcao:
        return jsonify({"ok": False, "erro": "Informe o motivo da correção."}), 400

    campos = {}
    detalhes = []
    if "destino" in dados and dados["destino"].strip() and dados["destino"] != visita["destino"]:
        campos["destino"] = dados["destino"].strip()
        detalhes.append(f"Destino: {visita['destino']} → {campos['destino']}")
    if "observacao" in dados and dados["observacao"].strip() != (visita.get("observacao") or ""):
        campos["observacao"] = dados["observacao"].strip()
        detalhes.append("Observação atualizada.")

    if not campos:
        return jsonify({"ok": False, "erro": "Nenhuma alteração informada."}), 400

    db.atualizar("visitantes_visitas", campos, onde={"id": visita_id})
    _registrar_evento(db, visita_id, "correcao", usuario["nome"],
                       f"{'; '.join(detalhes)} Motivo: {motivo_correcao}")

    atualizada = db.buscar_um("visitantes_visitas", onde={"id": visita_id})
    return jsonify({"ok": True, "visita": _serializar(atualizada)})


# ------------------------------------------------------------- Indicadores

@blueprint.route("/api/indicadores")
@perfil_obrigatorio(*PERFIS_CONSULTA)
def api_indicadores():
    db = _get_db()
    _garantir_tabelas(db)

    hoje = date.today().isoformat()
    todas = db.buscar("visitantes_visitas")

    no_campus = [v for v in todas if v["status"] == "no_campus"]
    hoje_entradas = [v for v in todas if v["entrada_em"][:10] == hoje]
    hoje_saidas = [v for v in todas if v.get("saida_em") and v["saida_em"][:10] == hoje]
    sem_saida = [v for v in no_campus]

    permanencias_hoje = [_permanencia_min(v["entrada_em"], v.get("saida_em")) for v in hoje_entradas]
    tempo_medio = round(sum(permanencias_hoje) / len(permanencias_hoje)) if permanencias_hoje else 0

    alertas = [_serializar(v) for v in no_campus
               if _permanencia_min(v["entrada_em"], None) >= LIMIAR_ALERTA_MINUTOS]

    for a in alertas:
        notificar_se_ausente(
            modulo="visitantes", tipo="alerta_permanencia", referencia_id=a["id"],
            titulo=f"Visitante há {a['permanencia_label']} no campus — {a['visitante_nome']}",
            mensagem=f"Destino: {a['destino']} · entrada às {a['entrada_em'][11:16]}",
            url="/visitantes/central", destinatario_tipo="perfil", destinatario_valor="coordenadora",
        )
        notificar_se_ausente(
            modulo="visitantes", tipo="alerta_permanencia_secretaria", referencia_id=a["id"],
            titulo=f"Visitante há {a['permanencia_label']} no campus — {a['visitante_nome']}",
            mensagem=f"Destino: {a['destino']} · entrada às {a['entrada_em'][11:16]}",
            url="/visitantes/central", destinatario_tipo="perfil", destinatario_valor="secretaria",
        )

    por_motivo: dict[str, int] = {}
    for v in hoje_entradas:
        por_motivo[v["motivo"]] = por_motivo.get(v["motivo"], 0) + 1
    total_hoje = len(hoje_entradas) or 1
    distribuicao_motivo = [
        {"motivo": _motivo_label(m["id"]), "percentual": round(100 * por_motivo.get(m["id"], 0) / total_hoje)}
        for m in MOTIVOS if por_motivo.get(m["id"])
    ]

    por_destino: dict[str, int] = {}
    for v in hoje_entradas:
        por_destino[v["destino"]] = por_destino.get(v["destino"], 0) + 1
    destino_mais_procurado = max(por_destino, key=por_destino.get) if por_destino else None

    return jsonify({
        "no_campus":              len(no_campus),
        "entradas_hoje":          len(hoje_entradas),
        "saidas_hoje":            len(hoje_saidas),
        "sem_saida":              len(sem_saida),
        "tempo_medio_permanencia": tempo_medio,
        "tempo_medio_label":       _formatar_permanencia(tempo_medio),
        "destino_mais_procurado": destino_mais_procurado,
        "distribuicao_motivo":    distribuicao_motivo,
        "alertas":                alertas[:10],
    })
