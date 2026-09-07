"""
Lógica pura de validação e montagem de configuração do wizard de
instalação. Sem nenhuma dependência de Flask — usada tanto pelo
wizard web (wizard/api_wizard.py) quanto pelo instalador desktop
(instalador/gui_instalador.py), para as duas superfícies aplicarem
exatamente as mesmas regras.
"""

import re
import secrets
from datetime import datetime

# Módulos vendáveis realmente existentes no projeto (ids usados em
# core/router.py e config.json → modulos_ativos). 'admin' não entra
# aqui: é sempre incluído automaticamente pelo próprio sistema.
MODULOS_DISPONIVEIS = [
    {"id": "sinal",               "nome": "Sinal",                    "descricao": "Toque automático dos sinais sonoros conforme os horários da instituição."},
    {"id": "agendamento",         "nome": "Agendamento de Recursos",  "descricao": "Reserva de laboratórios, salas e equipamentos pelos professores."},
    {"id": "biblioteca",         "nome": "Biblioteca",               "descricao": "Catálogo e empréstimos de livros, com controle de cópias."},
    {"id": "secretaria_portaria", "nome": "Secretaria e Portaria",    "descricao": "Painéis operacionais do dia a dia da secretaria e da portaria."},
    {"id": "iot",                 "nome": "Monitoramento IoT",        "descricao": "Sensores de água, portões e ar-condicionado controlados via ESP32."},
    {"id": "ocorrencias",         "nome": "Ocorrências",              "descricao": "Registro de ocorrências disciplinares por aluno/turma."},
    {"id": "evasao",              "nome": "Prevenção de Evasão",      "descricao": "Fichas e sinais de risco de evasão escolar por aluno."},
    {"id": "chaves",              "nome": "Controle de Chaves",       "descricao": "Controle de retirada e devolução de chaves de salas/laboratórios."},
    {"id": "chamados",            "nome": "Chamados Técnicos",        "descricao": "Abertura e atendimento de chamados técnicos de TI."},
    {"id": "monitoramento",       "nome": "Gráficos e Análise",       "descricao": "Painéis analíticos e gráficos gerais da instituição."},
    {"id": "alunos",              "nome": "Cadastro de Alunos",       "descricao": "Cadastro único de alunos usado por outros módulos."},
    {"id": "pontualidade",        "nome": "Controle de Pontualidade", "descricao": "Registro de entradas e atrasos na portaria, com histórico e painel de reincidência para a coordenação."},
    {"id": "saidas",              "nome": "Saídas de Alunos",         "descricao": "Autorização de saída de alunos durante o período escolar, com fluxo configurável entre Secretaria, Coordenação e Portaria."},
    {"id": "visitantes",          "nome": "Controle de Visitantes",   "descricao": "Registro de entrada/saída de visitantes pela Portaria, com painel de acompanhamento para Secretaria e Coordenação."},
]
IDS_MODULOS_VALIDOS = {m["id"] for m in MODULOS_DISPONIVEIS}


def estado_padrao() -> dict:
    return {
        "instituicao": {},
        "estrutura":   {},
        "turmas":      [],
        "funcionamento": {},
        "horarios": {"padrao": [], "sabado": [], "prova": []},
        "modulos_ativos": [],
        "sinal": {},
        "iot": {},
        "admin": {},
    }


def gerar_token() -> str:
    return secrets.token_hex(12)


def slugificar(texto: str) -> str:
    texto = texto.strip().lower()
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return texto.strip("_") or "item"


# ──────────────────────────────────────────────────────────────
# Validação
# ──────────────────────────────────────────────────────────────

def validar_horarios(lista: list, nome_lista: str) -> list[str]:
    erros = []
    horas_vistas = set()
    for i, item in enumerate(lista):
        hora = (item.get("hora") or "").strip()
        if not re.match(r"^\d{2}:\d{2}$", hora):
            erros.append(f"[{nome_lista}] Horário inválido em '{item.get('descricao', f'item {i+1}')}': '{hora}'.")
            continue
        if hora in horas_vistas:
            erros.append(f"[{nome_lista}] Horário duplicado: {hora}.")
        horas_vistas.add(hora)
    return erros


def validar_turmas(turmas: list) -> list[str]:
    erros = []
    if not turmas:
        erros.append("Nenhuma turma foi definida.")
    vistos = set()
    for t in turmas:
        nome = (t.get("turma") or "").strip()
        if not nome:
            erros.append("Existe uma turma sem nome.")
            continue
        chave = (nome, t.get("serie"), t.get("curso"))
        if chave in vistos:
            erros.append(f"Turma duplicada: '{nome}' ({t.get('serie') or '—'}).")
        vistos.add(chave)
    return erros


def validar_admin(admin: dict) -> list[str]:
    erros = []
    nome = (admin.get("nome") or "").strip()
    senha = admin.get("senha") or ""
    confirmacao = admin.get("confirmacao") or ""
    if not nome:
        erros.append("Informe o nome do administrador.")
    if len(senha) < 6:
        erros.append("A senha deve ter no mínimo 6 caracteres.")
    if senha != confirmacao:
        erros.append("A confirmação de senha não confere.")
    return erros


def validar_estado_completo(estado: dict) -> list[str]:
    erros = []

    inst = estado.get("instituicao", {})
    if not (inst.get("nome") or "").strip():
        erros.append("Informe o nome completo da instituição.")
    if not (inst.get("sigla") or "").strip():
        erros.append("Informe a sigla/nome curto da instituição.")

    erros += validar_turmas(estado.get("turmas", []))

    modulos_ativos = estado.get("modulos_ativos", [])
    invalidos = set(modulos_ativos) - IDS_MODULOS_VALIDOS
    if invalidos:
        erros.append(f"Módulo(s) desconhecido(s) selecionado(s): {', '.join(invalidos)}.")
    if not modulos_ativos:
        erros.append("Selecione pelo menos um módulo contratado antes de continuar.")

    if "sinal" in modulos_ativos:
        horarios = estado.get("horarios", {})
        erros += validar_horarios(horarios.get("padrao", []), "Horário padrão")
        if estado.get("funcionamento", {}).get("sabado_diferente"):
            erros += validar_horarios(horarios.get("sabado", []), "Horário de sábado")
        if estado.get("funcionamento", {}).get("prova_diferente"):
            erros += validar_horarios(horarios.get("prova", []), "Horário de prova")

        sinal = estado.get("sinal", {})
        if sinal.get("modo") == "remoto" and not (sinal.get("url") or "").strip():
            erros.append("Informe o endereço do computador remoto do sinal.")

    erros += validar_admin(estado.get("admin", {}))

    return erros


# ──────────────────────────────────────────────────────────────
# Montagem dos arquivos finais
# ──────────────────────────────────────────────────────────────

def montar_config(estado: dict, config_atual: dict) -> dict:
    inst = estado["instituicao"]
    cfg = dict(config_atual)  # preserva caminho_base, porta_api, host_api, encoding, versao já existentes
    cfg["nome_escola"]   = inst.get("nome", "").strip()
    cfg["sigla_escola"]  = inst.get("sigla", "").strip()
    cidade = inst.get("cidade", "").strip()
    bairro = inst.get("bairro", "").strip()
    cfg["cidade"] = cidade
    cfg["bairro_cidade"] = bairro or cidade
    if inst.get("estado"):
        cfg["estado_uf"] = inst["estado"].strip().upper()
    cfg["modulos_ativos"] = estado.get("modulos_ativos", [])

    if "sinal" in cfg["modulos_ativos"]:
        sinal = estado.get("sinal", {})
        cfg["sinal_modo"] = sinal.get("modo", "local")
        if cfg["sinal_modo"] == "remoto":
            cfg["sinal_url"] = sinal.get("url", "").strip()
        else:
            cfg.pop("sinal_url", None)

    cfg["implantacao"] = {
        "responsavel":       inst.get("responsavel_implantacao", ""),
        "id_instalacao":     estado.get("_id_instalacao") or secrets.token_hex(4),
        "instalado_em":      datetime.now().isoformat(),
    }
    return cfg


def montar_turmas(estado: dict) -> dict:
    turmas_saida = []
    for t in estado.get("turmas", []):
        item = {
            "turma": t.get("turma", "").strip(),
            "serie": t.get("serie", "").strip(),
            "curso": (t.get("curso") or "").strip(),
        }
        if t.get("turno"):
            item["turno"] = t["turno"].strip()
        turmas_saida.append(item)
    return {
        "observacao": "Lista fixa de turmas da escola. Editar aqui atualiza as opções disponíveis no cadastro único de alunos, usado por Ocorrências, Biblioteca e Prevenção de Evasão.",
        "turmas": turmas_saida,
    }


def montar_horarios(lista: list, chave: str, descricao: str) -> dict:
    horarios = []
    for i, h in enumerate(lista):
        horarios.append({
            "id":         h.get("id") or f"{chave.upper()[:1]}{i+1:02d}",
            "hora":       h.get("hora", "").strip(),
            "descricao":  h.get("descricao", "").strip(),
            "cancelado":  False,
        })
    return {"lista": chave, "descricao": descricao, "horarios": horarios}


def montar_dispositivos_iot(estado: dict) -> dict:
    iot = estado.get("iot", {})
    dados = {"observacao": "Cada dispositivo físico tem seu próprio token. Configure o firmware do ESP32 para enviar esse token no header X-Device-Token."}

    if iot.get("agua_ativo"):
        sensores = []
        for s in iot.get("agua_sensores", []):
            nome = (s.get("nome") or "").strip()
            if not nome:
                continue
            sensores.append({
                "id":            slugificar(nome),
                "nome":          nome,
                "hardware":      s.get("hardware") or "ESP32 + JSN-SR04T",
                "limite_minimo": int(s.get("limite_minimo") or 20),
                "token":         gerar_token(),
            })
        dados["agua"] = {"sensores": sensores}

    if iot.get("portoes_ativo"):
        lista = []
        for p in iot.get("portoes_lista", []):
            nome = (p.get("nome") or "").strip()
            if not nome:
                continue
            lista.append({"id": slugificar(nome), "nome": nome})
        dados["portoes"] = {
            "token":             gerar_token(),
            "hardware":          "ESP32 + atuador",
            "horario_abertura":  iot.get("portoes_horario_abertura", "07:00"),
            "horario_fechamento": iot.get("portoes_horario_fechamento", "21:00"),
            "lista": lista,
        }

    if iot.get("ac_ativo"):
        dados["ar_condicionado"] = {
            "token":     gerar_token(),
            "hardware":  "ESP32 + módulo IR",
            "nome":      iot.get("ac_nome") or "Ar-condicionados",
            "quantidade": int(iot.get("ac_quantidade") or 1),
            "horario_ligar": iot.get("ac_horario_ligar", "07:00"),
            "dias_semana_automacao": iot.get("ac_dias_semana") or [0, 1, 2, 3, 4],
        }

    return dados
