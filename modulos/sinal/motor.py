"""
Motor do Sinal
--------------
Toda a lógica de tocar sinal, gerenciar horários, estado do dia,
sons selecionáveis e envio de WhatsApp — sem nenhuma dependência de
Flask/rede. Usado de duas formas, conforme a configuração
"sinal_modo" em core/config.json:

  - "local"  → core/api_sinal.py chama estas funções diretamente,
               dentro do mesmo processo do servidor principal
               (mesma máquina que a caixa de som).
  - "remoto" → sinal.pyw roda como processo à parte, num PC dedicado
               à caixa de som, expondo estas mesmas funções via um
               mini servidor Flask próprio (porta 5001), que o
               servidor principal acessa por HTTP.

Manter a lógica aqui, num só lugar, evita os dois modos divergirem.
"""

import json
import logging
import threading
import time
from pathlib import Path
from datetime import datetime, date

BASE_SINAL = Path(__file__).resolve().parent

PASTA_SONS      = BASE_SINAL / "sons"
CONFIG_SOM_PATH = BASE_SINAL / "config_sinal.json"
ESTADO_PATH     = BASE_SINAL / "estado_sinal.json"
GRUPOS_PATH     = BASE_SINAL / "whatsapp_grupos.json"
SOM_PADRAO      = "sinal.wav"

_tocando     = threading.Lock()
_lock_estado = threading.Lock()
_estado      = None
_scheduler_iniciado = False
_scheduler_lock = threading.Lock()


# ---------------------------------------------------------------- sons

def _config_som() -> dict:
    """Carrega a configuração do som selecionado. Se não existir, cria com o padrão."""
    if CONFIG_SOM_PATH.exists():
        try:
            with open(CONFIG_SOM_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("som_ativo"):
                return cfg
        except Exception as e:
            logging.warning(f"[SINAL] Config de som corrompida/ilegível, usando padrão: {e}")
    cfg = {"som_ativo": SOM_PADRAO}
    _salvar_config_som(cfg)
    return cfg


def _salvar_config_som(cfg: dict) -> None:
    with open(CONFIG_SOM_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def arquivo_som_ativo() -> Path:
    """Retorna o caminho do arquivo de som atualmente selecionado."""
    nome = _config_som().get("som_ativo", SOM_PADRAO)
    caminho = PASTA_SONS / nome
    if caminho.exists():
        return caminho
    return PASTA_SONS / SOM_PADRAO


def sons_disponiveis() -> list:
    """Lista os arquivos .wav disponíveis na pasta de sons."""
    if not PASTA_SONS.exists():
        return []
    return sorted(p.name for p in PASTA_SONS.iterdir() if p.suffix.lower() == ".wav")


def nome_seguro(nome: str):
    """Valida que o nome de arquivo não contém caminho (evita path traversal)."""
    nome = (nome or "").strip()
    if not nome or "/" in nome or "\\" in nome or nome in (".", ".."):
        return None
    return nome


def definir_som_ativo(arquivo: str) -> dict:
    """Define qual som cadastrado será usado ao tocar o sinal."""
    nome = nome_seguro(arquivo)
    if not nome:
        raise ValueError("Nome de arquivo inválido.")
    if not (PASTA_SONS / nome).exists():
        raise FileNotFoundError("Arquivo de som não encontrado.")

    cfg = _config_som()
    cfg["som_ativo"] = nome
    _salvar_config_som(cfg)
    logging.info(f"[SINAL] Som ativo alterado para: {nome}")
    return {"som_ativo": nome}


def _tocar_arquivo(caminho: Path) -> None:
    if not caminho.exists():
        logging.warning(f"[SINAL] Arquivo de som não encontrado: {caminho}")
        return

    def _play():
        with _tocando:
            try:
                import winsound
                winsound.PlaySound(str(caminho), winsound.SND_FILENAME)
                logging.info(f"[SINAL] Som reproduzido com sucesso: {caminho.name}")
            except Exception as e:
                logging.error(f"[SINAL] Erro ao reproduzir som: {e}")

    threading.Thread(target=_play, daemon=True).start()


def tocar_sinal() -> None:
    """Toca o som atualmente selecionado para o sinal."""
    _tocar_arquivo(arquivo_som_ativo())


def testar_som(arquivo: str) -> str:
    """Toca um som específico (pré-audição, não altera o som ativo)."""
    nome = nome_seguro(arquivo)
    if not nome:
        raise ValueError("Nome de arquivo inválido.")
    caminho = PASTA_SONS / nome
    if not caminho.exists():
        raise FileNotFoundError("Arquivo de som não encontrado.")
    logging.info(f"[SINAL] Teste de som solicitado: {nome}")
    _tocar_arquivo(caminho)
    return nome


# ------------------------------------------------------------- estado

def _estado_inicial() -> dict:
    return {
        "lista_ativa":   "padrao",
        "data_atual":    date.today().isoformat(),
        "cancelamentos": [],
        "tocados_hoje":  [],
    }


def _carregar_estado() -> dict:
    if ESTADO_PATH.exists():
        try:
            with open(ESTADO_PATH, encoding="utf-8") as f:
                estado = json.load(f)
            if estado.get("data_atual") == date.today().isoformat():
                return estado
        except Exception as e:
            logging.warning(f"[SINAL] Estado do dia corrompido/ilegível, reiniciando: {e}")
    estado = _estado_inicial()
    _salvar_estado(estado)
    return estado


def _salvar_estado(estado: dict) -> None:
    estado["data_atual"] = date.today().isoformat()
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def _obter_estado() -> dict:
    global _estado
    if _estado is None:
        _estado = _carregar_estado()
    return _estado


def carregar_horarios(nome_lista: str) -> list:
    """Carrega a lista de horários do JSON correspondente."""
    nomes = {"padrao": "horarios_padrao.json",
             "sabado": "horarios_sabado.json",
             "prova":  "horarios_prova.json"}
    arquivo = BASE_SINAL / nomes.get(nome_lista, "horarios_padrao.json")
    with open(arquivo, encoding="utf-8") as f:
        dados = json.load(f)
    return dados["horarios"]


def obter_status() -> dict:
    """Monta o payload de status consumido pelo painel web."""
    estado = _obter_estado()
    with _lock_estado:
        lista_ativa   = estado["lista_ativa"]
        cancelamentos = set(estado["cancelamentos"])
        tocados       = set(estado["tocados_hoje"])

    horarios = carregar_horarios(lista_ativa)
    agora    = datetime.now().strftime("%H:%M")

    proximo = None
    for h in horarios:
        if h["id"] not in cancelamentos and h["hora"] > agora:
            proximo = h
            break

    for h in horarios:
        hid = h["id"]
        if hid in cancelamentos:
            h["status"] = "cancelado"
        elif hid in tocados:
            h["status"] = "tocado"
        elif h["hora"] == agora:
            h["status"] = "tocando"
        elif h["hora"] < agora:
            h["status"] = "passado"
        else:
            h["status"] = "pendente"

    return {
        "lista_ativa":  lista_ativa,
        "hora_atual":   agora,
        "proximo":      proximo,
        "horarios":     horarios,
        "som_presente": arquivo_som_ativo().exists(),
        "som_ativo":    _config_som().get("som_ativo", SOM_PADRAO),
    }


def cancelar_horario(hid: str) -> None:
    """Cancela um horário futuro pelo ID. Lança ValueError se já tiver tocado."""
    estado = _obter_estado()
    with _lock_estado:
        tocados       = set(estado["tocados_hoje"])
        cancelamentos = estado["cancelamentos"]

        if hid in tocados:
            raise ValueError("Este sinal já foi tocado.")

        if hid not in cancelamentos:
            cancelamentos.append(hid)
            _salvar_estado(estado)
            logging.info(f"[SINAL] Horário {hid} cancelado.")


def restaurar_horario(hid: str) -> None:
    """Restaura um horário cancelado."""
    estado = _obter_estado()
    with _lock_estado:
        if hid in estado["cancelamentos"]:
            estado["cancelamentos"].remove(hid)
            _salvar_estado(estado)
            logging.info(f"[SINAL] Horário {hid} restaurado.")


def trocar_lista(nova_lista: str) -> None:
    """Troca a lista de horários ativa (padrao | sabado | prova)."""
    if nova_lista not in ("padrao", "sabado", "prova"):
        raise ValueError("Lista inválida.")

    estado = _obter_estado()
    with _lock_estado:
        estado["lista_ativa"]   = nova_lista
        estado["cancelamentos"] = []
        estado["tocados_hoje"]  = []
        _salvar_estado(estado)
        logging.info(f"[SINAL] Lista trocada para '{nova_lista}'.")


# ----------------------------------------------------------- whatsapp

def enviar_whatsapp(turmas: list, horario_saida: str, motivo_id: str, nome_escola: str = "Smart Campus") -> dict:
    """
    Envia mensagem de saída antecipada para os grupos WhatsApp configurados.
    Usa pywhatkit (requer WhatsApp Web aberto no navegador da máquina que
    está rodando o motor do sinal). Lança ValueError para erros de validação.
    """
    if not turmas or not horario_saida:
        raise ValueError("Informe turmas e horário de saída.")

    with open(GRUPOS_PATH, encoding="utf-8") as f:
        cfg_wp = json.load(f)

    motivo_texto = cfg_wp.get("motivos", {}).get(motivo_id, motivo_id)
    data_hoje    = date.today().strftime("%d/%m/%Y")
    turmas_str   = ", ".join(turmas)

    mensagem = (
        f"🔔 *Aviso — {nome_escola}*\n\n"
        f"Informamos que as turmas *{turmas_str}* terão "
        f"saída antecipada hoje ({data_hoje}) às *{horario_saida}*.\n\n"
        f"Motivo: {motivo_texto}.\n\n"
        f"_Mensagem automática — Smart Campus_"
    )

    grupos_alvo = []
    for grupo in cfg_wp.get("grupos", []):
        for turma in turmas:
            if turma in grupo["turmas"]:
                grupos_alvo.append(grupo)
                break

    if not grupos_alvo:
        raise ValueError("Nenhum grupo encontrado para as turmas selecionadas.")

    erros    = []
    enviados = []

    for grupo in grupos_alvo:
        numero = grupo.get("numero", "").strip()
        if not numero:
            erros.append(f"Número não configurado para '{grupo['nome']}'.")
            continue

        try:
            import pywhatkit
            pywhatkit.sendwhatmsg(
                f"+{numero}", mensagem,
                time_hour=datetime.now().hour,
                time_min=datetime.now().minute + 1,
                wait_time=15,
                tab_close=True,
                close_time=3,
            )
            enviados.append(grupo["nome"])
            logging.info(f"[SINAL] WhatsApp enviado para {grupo['nome']} ({numero}).")

        except ImportError:
            from urllib.parse import quote
            link = f"https://wa.me/{numero}?text={quote(mensagem)}"
            erros.append(f"pywhatkit não instalado. Link manual para {grupo['nome']}: {link}")
            logging.warning(f"[SINAL] pywhatkit ausente. Link gerado para {grupo['nome']}.")

        except Exception as e:
            erros.append(f"Erro ao enviar para {grupo['nome']}: {e}")
            logging.error(f"[SINAL] Erro WhatsApp {grupo['nome']}: {e}")

    return {"enviados": enviados, "erros": erros, "mensagem": mensagem}


# ----------------------------------------------------------- scheduler

def _loop_scheduler():
    """
    Loop executado em thread separada. Verifica a cada 20 segundos
    se algum sinal deve ser tocado agora.
    """
    logging.info("[SINAL] Scheduler de sinal iniciado.")
    estado = _obter_estado()

    while True:
        try:
            agora = datetime.now()
            hora_atual = agora.strftime("%H:%M")

            with _lock_estado:
                if estado["data_atual"] != date.today().isoformat():
                    estado.update(_estado_inicial())
                    _salvar_estado(estado)
                    logging.info("[SINAL] Novo dia — estado reiniciado.")

                lista_ativa   = estado["lista_ativa"]
                cancelamentos = set(estado["cancelamentos"])
                tocados       = set(estado["tocados_hoje"])

            horarios = carregar_horarios(lista_ativa)

            for h in horarios:
                hid  = h["id"]
                hora = h["hora"]

                if hid in tocados or hid in cancelamentos:
                    continue
                if hora != hora_atual:
                    continue

                logging.info(f"[SINAL] Tocando sinal {hid} — {hora} — {h.get('descricao','')}")
                tocar_sinal()

                with _lock_estado:
                    estado["tocados_hoje"].append(hid)
                    _salvar_estado(estado)

                break

        except Exception as e:
            logging.error(f"[SINAL] Erro no scheduler: {e}")

        time.sleep(20)


def iniciar_scheduler() -> None:
    """
    Inicia a thread do scheduler, se ainda não estiver rodando.
    Idempotente — pode ser chamada várias vezes (ex: em cada import)
    sem duplicar a thread.
    """
    global _scheduler_iniciado
    with _scheduler_lock:
        if _scheduler_iniciado:
            return
        _scheduler_iniciado = True
        t = threading.Thread(target=_loop_scheduler, daemon=True, name="scheduler-sinal")
        t.start()
