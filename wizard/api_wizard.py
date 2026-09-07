"""
Wizard de Instalação/Configuração — Smart Campus.

Usado pela equipe de vendas/implantação para configurar uma instalação
nova para uma instituição, transformando as respostas coletadas na
configuração inicial que o sistema já sabe ler (core/config.json,
core/turmas.json, modulos/sinal/horarios_*.json,
modulos/iot/dispositivos.json e o usuário admin no SCEDS).

Não exige login: o wizard roda ANTES de existir qualquer usuário
administrador na instalação. Todo o progresso fica em memória (sessão
Flask) até a etapa final "/instalar" — nenhum arquivo real é tocado
antes disso.
"""

import json
from pathlib import Path

from flask import Blueprint, render_template, jsonify, request, session

from wizard import logica
from core.config_path import resolver_config_path

blueprint = Blueprint("wizard", __name__, template_folder="../templates/wizard")

BASE_PROJETO   = Path(__file__).resolve().parent.parent
CORE           = BASE_PROJETO / "core"
# IMPORTANTE: nunca montar este caminho na mão (CORE / "config.json").
# No .exe empacotado, __file__ resolve para dentro da pasta temporária
# do PyInstaller (_MEIPASS), que é apagada ao fechar o programa — um
# caminho montado na mão faria o Wizard gravar os módulos contratados
# ali, e a gravação desapareceria na próxima abertura. resolver_config_path()
# respeita SMARTCAMPUS_CONFIG_PATH (setado por launcher.py), apontando
# para o config.json real e persistente ao lado do .exe.
CONFIG_PATH    = resolver_config_path(BASE_PROJETO)
TURMAS_PATH    = CORE / "turmas.json"
SINAL_DIR      = BASE_PROJETO / "modulos" / "sinal"
IOT_DISPOSITIVOS_PATH = BASE_PROJETO / "modulos" / "iot" / "dispositivos.json"

SESSION_KEY = "wizard_estado"

# Reexportados de wizard/logica.py (lógica pura, compartilhada com o
# instalador desktop) para não quebrar quem já importa daqui.
MODULOS_DISPONIVEIS  = logica.MODULOS_DISPONIVEIS
IDS_MODULOS_VALIDOS  = logica.IDS_MODULOS_VALIDOS


def _instalacao_ja_concluida() -> bool:
    """
    Descobre se esta instalação já tem um administrador configurado.

    O wizard não exige login por necessidade (ele roda ANTES de existir
    qualquer usuário no sistema), mas isso o torna, por padrão, um
    endpoint de reconfiguração/criação de administrador aberto a
    qualquer pessoa na rede da instituição — inclusive depois da
    instalação já estar pronta e em uso. Este guard fecha essa janela:
    uma vez que exista um admin, o wizard para de aceitar requisições.
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        caminho_base = Path(cfg.get("caminho_base", "."))
        if not caminho_base.is_absolute():
            caminho_base = BASE_PROJETO

        import sys
        sys.path.insert(0, str(BASE_PROJETO))
        from sceds import SCEDS

        db = SCEDS(caminho_base / "sceds" / "data")
        return len(db.buscar("usuarios", onde={"perfil": "admin"})) > 0
    except Exception:
        # Sem config.json legível, sem pasta sceds/data ainda, etc. —
        # tudo isso significa "instalação nova", então o wizard deve
        # continuar liberado.
        return False


@blueprint.before_request
def _bloquear_wizard_apos_instalacao():
    if not _instalacao_ja_concluida():
        return None

    if request.path.startswith("/wizard/api/"):
        return jsonify({
            "ok": False,
            "error": {
                "code": "JA_INSTALADO",
                "message": "Este sistema já foi configurado. Para alterar "
                           "configurações da instituição, acesse como "
                           "administrador em /admin.",
            },
        }), 403

    return render_template("wizard/ja_instalado.html"), 403


# ──────────────────────────────────────────────────────────────
# Estado do wizard (sessão)
# ──────────────────────────────────────────────────────────────

def _estado_padrao() -> dict:
    return logica.estado_padrao()


def _carregar_estado() -> dict:
    estado = session.get(SESSION_KEY)
    if not estado:
        estado = _estado_padrao()
        session[SESSION_KEY] = estado
    return estado


def _salvar_estado(estado: dict) -> None:
    session[SESSION_KEY] = estado
    session.modified = True


# ──────────────────────────────────────────────────────────────
# Páginas
# ──────────────────────────────────────────────────────────────

@blueprint.route("/")
def pagina_wizard():
    return render_template("wizard/wizard.html", modulos=MODULOS_DISPONIVEIS)


# ──────────────────────────────────────────────────────────────
# Estado (rascunho em sessão)
# ──────────────────────────────────────────────────────────────

@blueprint.route("/api/estado", methods=["GET"])
def api_obter_estado():
    return jsonify(_carregar_estado())


@blueprint.route("/api/estado", methods=["PUT"])
def api_salvar_estado():
    """
    Body: { secao: str, dados: <qualquer coisa serializável> }
    Faz merge raso (substitui a chave "secao" inteira pelo valor enviado).
    Nenhum arquivo real do sistema é alterado aqui — só a sessão.
    """
    corpo = request.get_json(force=True) or {}
    secao = corpo.get("secao")
    dados = corpo.get("dados")

    if secao not in _estado_padrao():
        return jsonify({"ok": False, "erro": f"Seção de estado desconhecida: '{secao}'."}), 400

    estado = _carregar_estado()
    estado[secao] = dados
    _salvar_estado(estado)
    return jsonify({"ok": True})


@blueprint.route("/api/estado", methods=["DELETE"])
def api_reiniciar_estado():
    """Descarta o rascunho atual e recomeça o wizard do zero."""
    session.pop(SESSION_KEY, None)
    return jsonify({"ok": True})


@blueprint.route("/api/modulos")
def api_modulos():
    return jsonify(MODULOS_DISPONIVEIS)


# ──────────────────────────────────────────────────────────────
# Validação (usada tanto por etapa quanto na revisão final)
# ──────────────────────────────────────────────────────────────

def _validar_horarios(lista, nome_lista):
    return logica.validar_horarios(lista, nome_lista)


def _validar_turmas(turmas):
    return logica.validar_turmas(turmas)


def _validar_admin(admin):
    return logica.validar_admin(admin)


def _validar_estado_completo(estado):
    return logica.validar_estado_completo(estado)


@blueprint.route("/api/validar", methods=["POST"])
def api_validar():
    estado = _carregar_estado()
    erros = _validar_estado_completo(estado)
    return jsonify({"ok": len(erros) == 0, "erros": erros})


# ──────────────────────────────────────────────────────────────
# Instalação definitiva
# ──────────────────────────────────────────────────────────────

def _montar_config(estado, config_atual):
    return logica.montar_config(estado, config_atual)


def _montar_turmas(estado):
    return logica.montar_turmas(estado)


def _montar_horarios(lista, chave, descricao):
    return logica.montar_horarios(lista, chave, descricao)


def _montar_dispositivos_iot(estado):
    return logica.montar_dispositivos_iot(estado)


@blueprint.route("/api/instalar", methods=["POST"])
def api_instalar():
    """
    Aplica definitivamente a configuração coletada. Idempotente-ish:
    se qualquer validação falhar, nada é escrito em disco.
    """
    estado = _carregar_estado()
    erros = _validar_estado_completo(estado)
    if erros:
        return jsonify({"ok": False, "etapa": "validacao", "erros": erros}), 400

    etapas_concluidas = []
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config_atual = json.load(f)

        nova_config = _montar_config(estado, config_atual)
        etapas_concluidas.append("Validando configurações")

        novas_turmas = _montar_turmas(estado)
        etapas_concluidas.append("Criando estrutura de dados")

        # --- Só a partir daqui gravamos em disco ---
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(nova_config, f, ensure_ascii=False, indent=2)
        etapas_concluidas.append("Salvando configuração da instituição")

        with open(TURMAS_PATH, "w", encoding="utf-8") as f:
            json.dump(novas_turmas, f, ensure_ascii=False, indent=2)
        etapas_concluidas.append("Configurando turmas")

        if "sinal" in nova_config.get("modulos_ativos", []):
            horarios = estado.get("horarios", {})
            padrao = _montar_horarios(horarios.get("padrao", []), "padrao", "Segunda a Sexta")
            with open(SINAL_DIR / "horarios_padrao.json", "w", encoding="utf-8") as f:
                json.dump(padrao, f, ensure_ascii=False, indent=2)

            if estado.get("funcionamento", {}).get("sabado_diferente"):
                sabado = _montar_horarios(horarios.get("sabado", []), "sabado", "Sábado")
                with open(SINAL_DIR / "horarios_sabado.json", "w", encoding="utf-8") as f:
                    json.dump(sabado, f, ensure_ascii=False, indent=2)

            if estado.get("funcionamento", {}).get("prova_diferente"):
                prova = _montar_horarios(horarios.get("prova", []), "prova", "Dia de Prova")
                with open(SINAL_DIR / "horarios_prova.json", "w", encoding="utf-8") as f:
                    json.dump(prova, f, ensure_ascii=False, indent=2)
        etapas_concluidas.append("Configurando horários")

        if "iot" in nova_config.get("modulos_ativos", []):
            dispositivos = _montar_dispositivos_iot(estado)
            with open(IOT_DISPOSITIVOS_PATH, "w", encoding="utf-8") as f:
                json.dump(dispositivos, f, ensure_ascii=False, indent=2)
        etapas_concluidas.append("Configurando módulos")

        # Admin — feito por último, usa core.auth (depende do caminho_base já salvo em config.json)
        import sys
        sys.path.insert(0, str(BASE_PROJETO))
        from core.auth import criar_usuario

        admin = estado["admin"]
        registro = criar_usuario(admin["nome"].strip(), "admin", admin["senha"])
        etapas_concluidas.append("Criando administrador")

        etapas_concluidas.append("Finalizando")
        session.pop(SESSION_KEY, None)

        return jsonify({
            "ok": True,
            "etapas_concluidas": etapas_concluidas,
            "id_instalacao": nova_config["implantacao"]["id_instalacao"],
            "nome_escola": nova_config["nome_escola"],
            "admin_id": registro.get("id"),
        })

    except ValueError as e:
        # Erro de validação vindo de core.auth (ex: senha duplicada)
        return jsonify({"ok": False, "etapa": etapas_concluidas[-1] if etapas_concluidas else "início", "erros": [str(e)]}), 400
    except Exception as e:
        return jsonify({"ok": False, "etapa": etapas_concluidas[-1] if etapas_concluidas else "início", "erros": [f"Erro inesperado: {e}"]}), 500
