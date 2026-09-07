"""
Módulo: Autorizações de Saída de Alunos
----------------------------------------
Ver documento de arquitetura para o raciocínio completo por trás deste
módulo. Resumo do que este arquivo implementa:

- Uma única entidade "ExitAuthorization" (tabela `saidas_autorizacoes`)
  compartilhada por Secretaria, Coordenação e Portaria — nenhum setor
  possui seu próprio registro.
- O status é escrito diretamente na autorização por simplicidade de
  leitura, mas toda transição também grava um evento imutável em
  `saidas_eventos` (append-only) — essa tabela é a fonte de verdade
  para auditoria e histórico.
- Workflow configurável por instalação via core/config.json:
    "saidas_requer_coordenacao"   (bool, padrão True)  — Fluxo A por padrão
    "saidas_permite_envio_direto" (bool, padrão False) — habilita Fluxo B
  Fluxo C (Coordenação → Portaria) está sempre disponível: uma
  autorização criada pela Coordenação já nasce "autorizada".
- Expiração é verificada de forma preguiçosa (lazy) a cada listagem —
  suficiente para o MVP; a documentação de arquitetura recomenda migrar
  para um job agendado antes de haver muitos clientes simultâneos.
"""

import json
from pathlib import Path
from datetime import datetime, date
from flask import Blueprint, render_template, jsonify, request

from core.auth import perfil_obrigatorio, usuario_logado, reconfirmar_senha
from core import alunos as core_alunos
from core.notificacoes import notificar, resolver as resolver_notificacao
from core.auditoria import registrar as registrar_auditoria

blueprint = Blueprint("saidas", __name__, template_folder="../../templates/saidas")

BASE = Path(__file__).resolve().parent

ESTADOS_ATIVOS = {"aguardando_coordenacao", "autorizada"}
ESTADOS_TERMINAIS = {"saida_registrada", "rejeitada", "cancelada", "revogada", "expirada"}

MOTIVOS = [
    {"id": "consulta_medica",   "label": "Consulta médica"},
    {"id": "atendimento_familiar", "label": "Atendimento familiar"},
    {"id": "compromisso_externo", "label": "Compromisso externo"},
    {"id": "emergencia",        "label": "Emergência"},
    {"id": "atividade_externa", "label": "Atividade externa"},
    {"id": "saida_autorizada",  "label": "Saída autorizada pela família"},
    {"id": "outro",             "label": "Outro"},
]


def _get_db():
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    from sceds import SCEDS
    from core.config_path import carregar_config
    cfg = carregar_config(BASE.parent.parent)
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")


def _carregar_config() -> dict:
    from core.config_path import carregar_config
    return carregar_config(BASE.parent.parent)


def _requer_coordenacao() -> bool:
    return bool(_carregar_config().get("saidas_requer_coordenacao", True))


def _permite_envio_direto() -> bool:
    return bool(_carregar_config().get("saidas_permite_envio_direto", False))


def _garantir_tabelas(db) -> None:
    """Cria as tabelas do módulo na primeira execução, se ainda não existirem."""
    if not db.tabela_existe("saidas_autorizacoes"):
        db.criar_tabela("saidas_autorizacoes", [
            {"nome": "id",                    "tipo": "INTEIRO",   "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
            {"nome": "aluno_id",               "tipo": "INTEIRO",   "modificadores": ["NAO_NULO"]},
            {"nome": "aluno_nome",             "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "aluno_turma",            "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "data",                   "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "horario_previsto",       "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "motivo",                 "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "observacao",             "tipo": "TEXTO",     "modificadores": []},
            {"nome": "responsavel_nome",       "tipo": "TEXTO",     "modificadores": []},
            {"nome": "responsavel_relacao",    "tipo": "TEXTO",     "modificadores": []},
            {"nome": "origem",                 "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "solicitante",            "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "requer_coordenacao",     "tipo": "BOOLEANO",  "modificadores": ["NAO_NULO"]},
            {"nome": "status",                 "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "autorizado_por",         "tipo": "TEXTO",     "modificadores": []},
            {"nome": "autorizado_em",          "tipo": "DATA_HORA", "modificadores": []},
            {"nome": "motivo_rejeicao",        "tipo": "TEXTO",     "modificadores": []},
            {"nome": "motivo_revogacao",       "tipo": "TEXTO",     "modificadores": []},
            {"nome": "revogado_por",           "tipo": "TEXTO",     "modificadores": []},
            {"nome": "revogado_em",            "tipo": "DATA_HORA", "modificadores": []},
            {"nome": "saida_registrada_em",    "tipo": "DATA_HORA", "modificadores": []},
            {"nome": "saida_registrada_por",   "tipo": "TEXTO",     "modificadores": []},
            {"nome": "criado_em",              "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
        ])
    if not db.tabela_existe("saidas_eventos"):
        db.criar_tabela("saidas_eventos", [
            {"nome": "id",              "tipo": "INTEIRO",   "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
            {"nome": "autorizacao_id",  "tipo": "INTEIRO",   "modificadores": ["NAO_NULO"]},
            {"nome": "tipo",            "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "autor",           "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "estado_anterior", "tipo": "TEXTO",     "modificadores": []},
            {"nome": "estado_novo",     "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "detalhe",         "tipo": "TEXTO",     "modificadores": []},
            {"nome": "criado_em",       "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
        ])


def _registrar_evento(db, autorizacao_id: int, tipo: str, autor: str,
                       estado_anterior: str | None, estado_novo: str, detalhe: str = "") -> None:
    db.inserir("saidas_eventos", {
        "autorizacao_id":  autorizacao_id,
        "tipo":            tipo,
        "autor":           autor,
        "estado_anterior": estado_anterior,
        "estado_novo":     estado_novo,
        "detalhe":         detalhe,
        "criado_em":       datetime.now().isoformat(),
    })


def _expirar_vencidas(db) -> None:
    """
    Verificação preguiçosa de expiração: qualquer autorização de um dia
    anterior a hoje que ainda esteja em estado não-terminal é marcada
    como expirada. Chamada no início de toda listagem do módulo.
    """
    hoje = date.today().isoformat()
    pendentes = [a for a in db.buscar("saidas_autorizacoes")
                 if a["data"] < hoje and a["status"] in ESTADOS_ATIVOS]
    for autorizacao in pendentes:
        db.atualizar("saidas_autorizacoes", {"status": "expirada"}, onde={"id": autorizacao["id"]})
        _registrar_evento(db, autorizacao["id"], "expirada", "sistema",
                           autorizacao["status"], "expirada", "Expirada automaticamente (dia seguinte).")


def _serializar(a: dict) -> dict:
    """Adiciona campos derivados úteis para a interface."""
    a = dict(a)
    a["pode_registrar_saida"] = a["status"] == "autorizada"
    a["pode_revogar"] = a["status"] in ESTADOS_ATIVOS
    a["motivo_label"] = next((m["label"] for m in MOTIVOS if m["id"] == a["motivo"]), a["motivo"])
    return a


# ---------------------------------------------------------------- Páginas

@blueprint.route("/secretaria")
@perfil_obrigatorio("secretaria", "admin")
def pagina_secretaria():
    return render_template("saidas/secretaria.html", hoje=date.today().isoformat(), motivos=MOTIVOS)


@blueprint.route("/coordenacao")
@perfil_obrigatorio("coordenadora", "admin")
def pagina_coordenacao():
    return render_template("saidas/coordenacao.html", hoje=date.today().isoformat())


@blueprint.route("/portaria")
@perfil_obrigatorio("portaria", "admin")
def pagina_portaria():
    return render_template("saidas/portaria.html", hoje=date.today().isoformat())


# ------------------------------------------------------------- Busca de aluno

@blueprint.route("/api/alunos/buscar")
@perfil_obrigatorio("secretaria", "coordenadora", "portaria", "admin")
def api_buscar_aluno():
    """Query: q (nome ou matrícula). Reaproveita o cadastro único de alunos."""
    termo = request.args.get("q", "").strip()
    if len(termo) < 2:
        return jsonify([])
    resultados = core_alunos.buscar(busca=termo, limite=8)
    return jsonify(resultados)


# ------------------------------------------------------------- Listagem geral

@blueprint.route("/api/autorizacoes")
@perfil_obrigatorio("secretaria", "coordenadora", "portaria", "admin")
def api_listar_autorizacoes():
    """
    Query: data (padrão hoje), status (opcional, um dos estados válidos).
    A Secretaria enxerga tudo que criou/está em andamento no dia; a
    Coordenação enxerga a fila pendente; a Portaria enxerga só o que já
    está autorizado para hoje. O filtro por perfil é aplicado no
    frontend de cada painel — aqui devolvemos os dados do dia,
    já ordenados por horário previsto.
    """
    db = _get_db()
    _garantir_tabelas(db)
    _expirar_vencidas(db)

    data_filtro = request.args.get("data", date.today().isoformat())
    status_filtro = request.args.get("status", "").strip()

    autorizacoes = db.buscar("saidas_autorizacoes", onde={"data": data_filtro})
    if status_filtro:
        autorizacoes = [a for a in autorizacoes if a["status"] == status_filtro]

    autorizacoes.sort(key=lambda a: a["horario_previsto"])
    return jsonify([_serializar(a) for a in autorizacoes])


@blueprint.route("/api/autorizacoes/<int:autorizacao_id>/historico")
@perfil_obrigatorio("secretaria", "coordenadora", "portaria", "admin")
def api_historico(autorizacao_id: int):
    db = _get_db()
    _garantir_tabelas(db)
    if not db.buscar_um("saidas_autorizacoes", onde={"id": autorizacao_id}):
        return jsonify({"ok": False, "erro": "Autorização não encontrada."}), 404
    eventos = db.buscar("saidas_eventos", onde={"autorizacao_id": autorizacao_id}, ordenar_por="id")
    return jsonify(eventos)


# ------------------------------------------------------------- Criação (Secretaria / Coordenação)

@blueprint.route("/api/autorizacoes", methods=["POST"])
@perfil_obrigatorio("secretaria", "coordenadora", "admin")
def api_criar_autorizacao():
    """
    Body: aluno_id, horario_previsto (HH:MM), motivo (id da lista MOTIVOS),
    observacao (opcional), responsavel_nome/relacao (opcional),
    envio_direto (opcional, bool — só tem efeito para perfil secretaria e
    apenas se a instalação habilitar "saidas_permite_envio_direto").
    """
    usuario = usuario_logado()
    dados = request.get_json(force=True) or {}

    aluno_id = dados.get("aluno_id")
    horario = (dados.get("horario_previsto") or "").strip()
    motivo = (dados.get("motivo") or "").strip()
    observacao = (dados.get("observacao") or "").strip()
    responsavel_nome = (dados.get("responsavel_nome") or "").strip()
    responsavel_relacao = (dados.get("responsavel_relacao") or "").strip()
    envio_direto = bool(dados.get("envio_direto")) and _permite_envio_direto()

    if not aluno_id or not horario or not motivo:
        return jsonify({"ok": False, "erro": "Selecione o aluno, o horário previsto e o motivo."}), 400
    if motivo not in {m["id"] for m in MOTIVOS}:
        return jsonify({"ok": False, "erro": "Motivo inválido."}), 400

    aluno = core_alunos.buscar_um(aluno_id)
    if not aluno:
        return jsonify({"ok": False, "erro": "Aluno não encontrado."}), 404

    db = _get_db()
    _garantir_tabelas(db)
    hoje = date.today().isoformat()

    # Item 41 — prevenção de duplicidade: já existe autorização ativa hoje?
    ativa_existente = next((a for a in db.buscar("saidas_autorizacoes", onde={"aluno_id": aluno_id, "data": hoje})
                             if a["status"] in ESTADOS_ATIVOS), None)
    if ativa_existente:
        return jsonify({
            "ok": False,
            "erro": f"Já existe uma autorização ativa para {aluno['nome']} hoje.",
            "autorizacao_existente": _serializar(ativa_existente),
        }), 409

    # Item 24 — impedir nova saída se já houve uma saída registrada hoje.
    ja_saiu = next((a for a in db.buscar("saidas_autorizacoes", onde={"aluno_id": aluno_id, "data": hoje})
                     if a["status"] == "saida_registrada"), None)
    if ja_saiu:
        return jsonify({"ok": False, "erro": f"{aluno['nome']} já teve uma saída registrada hoje."}), 409

    perfil = usuario["perfil"]
    if perfil == "coordenadora":
        # Fluxo C: Coordenação → Portaria (já nasce autorizada).
        origem, status = "coordenacao", "autorizada"
        requer_coordenacao = False
    elif envio_direto:
        # Fluxo B: Secretaria → Portaria, sem passar pela Coordenação.
        origem, status = "secretaria", "autorizada"
        requer_coordenacao = False
    else:
        requer_coordenacao = _requer_coordenacao()
        origem = "secretaria"
        status = "aguardando_coordenacao" if requer_coordenacao else "autorizada"

    registro = db.inserir("saidas_autorizacoes", {
        "aluno_id":            aluno_id,
        "aluno_nome":          aluno["nome"],
        "aluno_turma":         aluno["turma"],
        "data":                hoje,
        "horario_previsto":    horario,
        "motivo":              motivo,
        "observacao":          observacao,
        "responsavel_nome":    responsavel_nome,
        "responsavel_relacao": responsavel_relacao,
        "origem":              origem,
        "solicitante":         usuario["nome"],
        "requer_coordenacao":  requer_coordenacao,
        "status":              status,
        "autorizado_por":      usuario["nome"] if status == "autorizada" else None,
        "autorizado_em":       datetime.now().isoformat() if status == "autorizada" else None,
        "motivo_rejeicao":     None,
        "motivo_revogacao":    None,
        "revogado_por":        None,
        "revogado_em":         None,
        "saida_registrada_em": None,
        "saida_registrada_por": None,
        "criado_em":           datetime.now().isoformat(),
    })

    _registrar_evento(db, registro["id"], "criada", usuario["nome"], None, status,
                       f"Origem: {origem}." + (" Envio direto à Portaria." if status == "autorizada" else ""))

    if status == "aguardando_coordenacao":
        notificar(modulo="saidas", tipo="aguardando_aprovacao",
                  titulo=f"Saída aguardando aprovação — {aluno['nome']}",
                  mensagem=f"{aluno['turma']} · previsto para {horario}",
                  url="/saidas/coordenacao", destinatario_tipo="perfil", destinatario_valor="coordenadora",
                  referencia_id=registro["id"], criado_por=usuario["nome"])
    elif status == "autorizada":
        notificar(modulo="saidas", tipo="pronta_portaria",
                  titulo=f"Saída autorizada — {aluno['nome']}",
                  mensagem=f"{aluno['turma']} · previsto para {horario}",
                  url="/saidas/portaria", destinatario_tipo="perfil", destinatario_valor="portaria",
                  referencia_id=registro["id"], criado_por=usuario["nome"])

    return jsonify({"ok": True, "autorizacao": _serializar(registro)}), 201


# ------------------------------------------------------------- Coordenação: aprovar / rejeitar

@blueprint.route("/api/autorizacoes/<int:autorizacao_id>/aprovar", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_aprovar(autorizacao_id: int):
    """Body: senha (obrigatório) — reconfirma que é mesmo quem está logado
    apertando o botão, não alguém que achou a sessão aberta num PC
    compartilhado. Autorizar a saída de um aluno libera a portaria a
    deixá-lo ir embora, então essa confirmação existe mesmo a conta já
    estando logada."""
    usuario = usuario_logado()
    dados = request.get_json(force=True, silent=True) or {}
    senha = dados.get("senha", "")

    if not reconfirmar_senha(senha):
        registrar_auditoria(usuario, "tentativa_aprovacao_saida_senha_incorreta",
                             entidade="saidas_autorizacoes", entidade_id=autorizacao_id)
        return jsonify({"ok": False, "erro": "Senha incorreta. A autorização não foi confirmada."}), 403

    db = _get_db()
    _garantir_tabelas(db)

    autorizacao = db.buscar_um("saidas_autorizacoes", onde={"id": autorizacao_id})
    if not autorizacao:
        return jsonify({"ok": False, "erro": "Autorização não encontrada."}), 404
    if autorizacao["status"] != "aguardando_coordenacao":
        return jsonify({"ok": False, "erro": "Esta autorização não está mais aguardando análise."}), 409

    agora = datetime.now().isoformat()
    qtd = db.atualizar("saidas_autorizacoes", {
        "status":          "autorizada",
        "autorizado_por":  usuario["nome"],
        "autorizado_em":   agora,
    }, onde={"id": autorizacao_id, "status": "aguardando_coordenacao"})

    if qtd == 0:
        return jsonify({"ok": False, "erro": "Esta autorização já foi tratada por outra pessoa."}), 409

    _registrar_evento(db, autorizacao_id, "aprovada", usuario["nome"], "aguardando_coordenacao", "autorizada")
    resolver_notificacao(modulo="saidas", tipo="aguardando_aprovacao", referencia_id=autorizacao_id)
    notificar(modulo="saidas", tipo="pronta_portaria",
              titulo=f"Saída autorizada — {autorizacao['aluno_nome']}",
              mensagem=f"{autorizacao['aluno_turma']} · previsto para {autorizacao['horario_previsto']}",
              url="/saidas/portaria", destinatario_tipo="perfil", destinatario_valor="portaria",
              referencia_id=autorizacao_id, criado_por=usuario["nome"])
    return jsonify({"ok": True})


@blueprint.route("/api/autorizacoes/<int:autorizacao_id>/rejeitar", methods=["POST"])
@perfil_obrigatorio("coordenadora", "admin")
def api_rejeitar(autorizacao_id: int):
    usuario = usuario_logado()
    dados = request.get_json(force=True, silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    if not motivo:
        return jsonify({"ok": False, "erro": "Informe o motivo da rejeição."}), 400

    db = _get_db()
    _garantir_tabelas(db)
    autorizacao = db.buscar_um("saidas_autorizacoes", onde={"id": autorizacao_id})
    if not autorizacao:
        return jsonify({"ok": False, "erro": "Autorização não encontrada."}), 404
    if autorizacao["status"] != "aguardando_coordenacao":
        return jsonify({"ok": False, "erro": "Esta autorização não está mais aguardando análise."}), 409

    qtd = db.atualizar("saidas_autorizacoes", {
        "status": "rejeitada",
        "motivo_rejeicao": motivo,
    }, onde={"id": autorizacao_id, "status": "aguardando_coordenacao"})

    if qtd == 0:
        return jsonify({"ok": False, "erro": "Esta autorização já foi tratada por outra pessoa."}), 409

    _registrar_evento(db, autorizacao_id, "rejeitada", usuario["nome"], "aguardando_coordenacao", "rejeitada", motivo)
    resolver_notificacao(modulo="saidas", tipo="aguardando_aprovacao", referencia_id=autorizacao_id)
    return jsonify({"ok": True})


# ------------------------------------------------------------- Revogação / cancelamento

@blueprint.route("/api/autorizacoes/<int:autorizacao_id>/revogar", methods=["POST"])
@perfil_obrigatorio("secretaria", "coordenadora", "admin")
def api_revogar(autorizacao_id: int):
    """
    Disponível para Secretaria e Coordenação enquanto a autorização não
    tiver saída registrada — cobre tanto "cancelar antes de autorizar"
    quanto "revogar depois de já enviada à Portaria" (item 18 da
    especificação). A Portaria vê a mudança na próxima atualização da
    fila (polling).
    """
    usuario = usuario_logado()
    dados = request.get_json(force=True, silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()

    db = _get_db()
    _garantir_tabelas(db)
    autorizacao = db.buscar_um("saidas_autorizacoes", onde={"id": autorizacao_id})
    if not autorizacao:
        return jsonify({"ok": False, "erro": "Autorização não encontrada."}), 404
    if autorizacao["status"] not in ESTADOS_ATIVOS:
        return jsonify({"ok": False, "erro": "Esta autorização não pode mais ser revogada."}), 409

    estado_anterior = autorizacao["status"]
    qtd = db.atualizar("saidas_autorizacoes", {
        "status":           "revogada",
        "motivo_revogacao": motivo,
        "revogado_por":      usuario["nome"],
        "revogado_em":       datetime.now().isoformat(),
    }, onde={"id": autorizacao_id, "status": estado_anterior})

    if qtd == 0:
        return jsonify({"ok": False, "erro": "Esta autorização já foi alterada por outra pessoa. Atualize a tela."}), 409

    _registrar_evento(db, autorizacao_id, "revogada", usuario["nome"], estado_anterior, "revogada", motivo)
    resolver_notificacao(modulo="saidas", tipo="aguardando_aprovacao", referencia_id=autorizacao_id)
    resolver_notificacao(modulo="saidas", tipo="pronta_portaria", referencia_id=autorizacao_id)
    return jsonify({"ok": True})


# ------------------------------------------------------------- Portaria: registrar saída

@blueprint.route("/api/autorizacoes/<int:autorizacao_id>/registrar-saida", methods=["POST"])
@perfil_obrigatorio("portaria", "admin")
def api_registrar_saida(autorizacao_id: int):
    """
    A Portaria nunca digita o horário — o sistema grava o momento exato
    do clique. O filtro onde={"status": "autorizada"} na atualização
    garante atomicidade: se dois porteiros clicarem ao mesmo tempo, ou
    se a Coordenação revogar no instante exato do clique, apenas uma
    dessas operações terá efeito (item 24 da especificação).
    """
    usuario = usuario_logado()
    db = _get_db()
    _garantir_tabelas(db)

    autorizacao = db.buscar_um("saidas_autorizacoes", onde={"id": autorizacao_id})
    if not autorizacao:
        return jsonify({"ok": False, "erro": "Autorização não encontrada."}), 404
    if autorizacao["status"] != "autorizada":
        return jsonify({"ok": False, "erro": "Esta autorização não está mais disponível para saída (pode ter sido revogada ou já registrada)."}), 409

    agora = datetime.now().isoformat()
    qtd = db.atualizar("saidas_autorizacoes", {
        "status":               "saida_registrada",
        "saida_registrada_em":  agora,
        "saida_registrada_por": usuario["nome"],
    }, onde={"id": autorizacao_id, "status": "autorizada"})

    if qtd == 0:
        return jsonify({"ok": False, "erro": "Essa saída já foi registrada ou a autorização foi revogada."}), 409

    _registrar_evento(db, autorizacao_id, "saida_registrada", usuario["nome"], "autorizada", "saida_registrada")
    resolver_notificacao(modulo="saidas", tipo="pronta_portaria", referencia_id=autorizacao_id)
    return jsonify({"ok": True, "horario": agora})
