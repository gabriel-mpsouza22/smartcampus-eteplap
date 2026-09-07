"""
Serviço central de notificações
--------------------------------
Infraestrutura, não um "módulo" contratável — por isso é registrado
direto no app.py (como o wizard), disponível em toda instalação,
independente do pacote de módulos escolhido.

Qualquer módulo do sistema pode gerar uma notificação chamando
`notificar(...)` no ponto onde já emite o evento que interessa (uma
saída pendente de aprovação, um chamado aberto, um alerta de
permanência de visitante etc.) — não é preciso alterar a estrutura
do módulo, só adicionar essa chamada.

Duas ideias centrais no modelo de dados:

- `resolvida`: quando o motivo da notificação deixa de existir (o
  chamado foi respondido, a saída foi aprovada), o próprio módulo
  chama `resolver()` e a notificação some do sino/badge de todo mundo
  — não depende de alguém ter clicado nela.
- `lida_por`: quando o destinatário é um perfil inteiro (ex: toda a
  Coordenação), várias pessoas enxergam a mesma notificação. Cada uma
  marca como lida para si mesma; não deveria sumir para as outras só
  porque uma pessoa abriu.
"""

import json
from pathlib import Path
from datetime import datetime
from flask import Blueprint, jsonify, request

from core.auth import login_obrigatorio, usuario_logado

blueprint = Blueprint("notificacoes", __name__)

BASE = Path(__file__).resolve().parent.parent  # raiz do projeto (core/ está um nível abaixo)

# Quantidade de notificações resolvidas mantidas apenas para histórico
# (não contam em nenhum contador, mas evitam que o arquivo cresça sem limite).
LIMITE_RESOLVIDAS_MANTIDAS = 500


def _get_db():
    import sys
    sys.path.insert(0, str(BASE))
    from sceds import SCEDS
    from core.config_path import carregar_config
    cfg = carregar_config(BASE)
    return SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")


def _garantir_tabela(db) -> None:
    if not db.tabela_existe("notificacoes"):
        db.criar_tabela("notificacoes", [
            {"nome": "id",                  "tipo": "INTEIRO",   "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
            {"nome": "modulo",              "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "tipo",                "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "titulo",              "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "mensagem",            "tipo": "TEXTO",     "modificadores": []},
            {"nome": "url",                 "tipo": "TEXTO",     "modificadores": []},
            {"nome": "destinatario_tipo",   "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},  # "perfil" | "usuario"
            {"nome": "destinatario_valor",  "tipo": "TEXTO",     "modificadores": ["NAO_NULO"]},
            {"nome": "referencia_id",       "tipo": "TEXTO",     "modificadores": []},  # id do registro de origem (chamado, saída...), para auto-resolução
            {"nome": "lida_por",            "tipo": "TEXTO",     "modificadores": []},  # lista de ids de usuário, serializada em JSON (SCEDS não tem tipo lista/JSON nativo)
            {"nome": "resolvida",           "tipo": "BOOLEANO",  "modificadores": ["NAO_NULO"]},
            {"nome": "resolvida_em",        "tipo": "DATA_HORA", "modificadores": []},
            {"nome": "criado_por",          "tipo": "TEXTO",     "modificadores": []},
            {"nome": "criado_em",           "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
        ])


# ---------------------------------------------------------------- API interna
# Chamada pelos outros módulos (não é HTTP — é uma função Python normal).

def _get_lida_por(notif: dict) -> list[str]:
    bruto = notif.get("lida_por")
    if not bruto:
        return []
    try:
        return json.loads(bruto)
    except (TypeError, ValueError):
        return []


def notificar(modulo: str, tipo: str, titulo: str, mensagem: str = "", url: str = "",
              destinatario_tipo: str = "perfil", destinatario_valor: str = "",
              referencia_id: str | None = None, criado_por: str | None = None) -> dict:
    """
    Cria uma notificação.

    destinatario_tipo="perfil"  → destinatario_valor é um perfil (ex: "coordenadora"),
                                   visível para todos os usuários daquele perfil.
    destinatario_tipo="usuario" → destinatario_valor é o id do usuário específico.
    """
    db = _get_db()
    _garantir_tabela(db)
    return db.inserir("notificacoes", {
        "modulo": modulo, "tipo": tipo, "titulo": titulo, "mensagem": mensagem, "url": url,
        "destinatario_tipo": destinatario_tipo, "destinatario_valor": str(destinatario_valor),
        "referencia_id": str(referencia_id) if referencia_id is not None else None,
        "lida_por": json.dumps([]), "resolvida": False, "resolvida_em": None,
        "criado_por": criado_por, "criado_em": datetime.now().isoformat(),
    })


def notificar_se_ausente(modulo: str, tipo: str, referencia_id: str, **kwargs) -> dict | None:
    """
    Como `notificar()`, mas não duplica: só cria se não existir uma
    notificação pendente (não resolvida) para o mesmo evento de origem.

    Feito para condições verificadas de forma preguiçosa a cada
    requisição (ex: "visitante com permanência acima do limite",
    recalculado a cada polling da Central de Visitantes) — sem isso,
    cada checagem periódica criaria uma notificação nova para a mesma
    situação.
    """
    db = _get_db()
    _garantir_tabela(db)
    existente = next((n for n in db.buscar("notificacoes", onde={
        "modulo": modulo, "tipo": tipo, "referencia_id": str(referencia_id), "resolvida": False,
    })), None)
    if existente:
        return None
    return notificar(modulo=modulo, tipo=tipo, referencia_id=referencia_id, **kwargs)


def resolver(modulo: str, tipo: str, referencia_id: str) -> int:
    """
    Marca como resolvida qualquer notificação pendente para esse evento
    de origem — some do sino/badge de todo mundo, não só de quem clicou.
    Chamar quando o motivo da notificação deixa de existir (chamado
    respondido, saída aprovada, chave devolvida...).
    """
    db = _get_db()
    _garantir_tabela(db)
    return db.atualizar("notificacoes", {
        "resolvida": True, "resolvida_em": datetime.now().isoformat(),
    }, onde={"modulo": modulo, "tipo": tipo, "referencia_id": str(referencia_id), "resolvida": False})


# -------------------------------------------------------------- Visibilidade

def _visivel_para(notif: dict, usuario: dict) -> bool:
    if notif["destinatario_tipo"] == "usuario":
        return notif["destinatario_valor"] == str(usuario["id"])
    return notif["destinatario_valor"] == usuario["perfil"]


def _nao_lida_por(notif: dict, usuario: dict) -> bool:
    return str(usuario["id"]) not in _get_lida_por(notif)


def _pendentes_para(db, usuario: dict) -> list[dict]:
    todas = db.buscar("notificacoes", onde={"resolvida": False})
    visiveis = [n for n in todas if _visivel_para(n, usuario)]
    return [n for n in visiveis if _nao_lida_por(n, usuario)]


# ------------------------------------------------------------------- Páginas

@blueprint.route("/api/contagem")
@login_obrigatorio
def api_contagem():
    """
    { "total": N, "por_modulo": {"saidas": 2, "chamados": 1, ...} }
    'por_modulo' usa sempre o id real do módulo (o mesmo usado em
    modulos_ativos_permitidos), não o id do item de menu — a sidebar
    faz essa tradução ao ler o atributo data-modulo de cada link.
    """
    db = _get_db()
    _garantir_tabela(db)
    usuario = usuario_logado()
    pendentes = _pendentes_para(db, usuario)

    por_modulo: dict[str, int] = {}
    for n in pendentes:
        por_modulo[n["modulo"]] = por_modulo.get(n["modulo"], 0) + 1

    return jsonify({"total": len(pendentes), "por_modulo": por_modulo})


@blueprint.route("/api/listar")
@login_obrigatorio
def api_listar():
    """Notificações pendentes mais recentes, para o dropdown do sino."""
    db = _get_db()
    _garantir_tabela(db)
    usuario = usuario_logado()
    pendentes = _pendentes_para(db, usuario)
    pendentes.sort(key=lambda n: n["criado_em"], reverse=True)
    limite = int(request.args.get("limite", 20))
    return jsonify(pendentes[:limite])


@blueprint.route("/api/<int:notif_id>/marcar-lida", methods=["POST"])
@login_obrigatorio
def api_marcar_lida(notif_id: int):
    db = _get_db()
    _garantir_tabela(db)
    usuario = usuario_logado()
    notif = db.buscar_um("notificacoes", onde={"id": notif_id})
    if not notif:
        return jsonify({"ok": False, "erro": "Notificação não encontrada."}), 404

    lidos = _get_lida_por(notif)
    if str(usuario["id"]) not in lidos:
        lidos.append(str(usuario["id"]))
        db.atualizar("notificacoes", {"lida_por": json.dumps(lidos)}, onde={"id": notif_id})

    return jsonify({"ok": True})


@blueprint.route("/api/marcar-todas-lidas", methods=["POST"])
@login_obrigatorio
def api_marcar_todas_lidas():
    db = _get_db()
    _garantir_tabela(db)
    usuario = usuario_logado()
    pendentes = _pendentes_para(db, usuario)

    for n in pendentes:
        lidos = _get_lida_por(n)
        lidos.append(str(usuario["id"]))
        db.atualizar("notificacoes", {"lida_por": json.dumps(lidos)}, onde={"id": n["id"]})

    return jsonify({"ok": True, "marcadas": len(pendentes)})
