
import sys
import json
import time
import random
import threading
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    print("Instale a biblioteca requests: pip install requests")
    raise SystemExit(1)

BASE = Path(__file__).resolve().parent
CONFIG_PATH_PADRAO = BASE / "dispositivos.json"

INTERVALO_AGUA_S     = 15
INTERVALO_POLL_S     = 5
TEMPO_CURSO_PORTAO_S = 4
TEMPO_ENVIO_IR_S     = 1
CHANCE_NIVEL_BAIXO   = 0.08

_encerrar = threading.Event()
_lock_print = threading.Lock()


def log(origem: str, mensagem: str):
    agora = datetime.now().strftime("%H:%M:%S")
    with _lock_print:
        print(f"[{agora}] [{origem}] {mensagem}")


def carregar_config() -> dict:
    with open(CONFIG_PATH_PADRAO, encoding="utf-8") as f:
        return json.load(f)


def obter_endereco_servidor() -> str:
    print("Informe o endereço do servidor Smart Campus.")
    print("Exemplo: http://192.168.0.108  (ou http://localhost:80)")
    endereco = input("Endereço [http://localhost:80]: ").strip().rstrip("/")
    if not endereco:
        endereco = "http://localhost:80"
    if not endereco.startswith("http"):
        endereco = "http://" + endereco
    return endereco


def thread_sensor_agua(base_url: str, sensor: dict):
    sensor_id = sensor["id"]
    token = sensor["token"]
    limite_min = sensor["limite_minimo"]

    nivel_atual = min(95.0, limite_min + 40)

    log(sensor_id, f"Dispositivo iniciado. Limite mínimo configurado: {limite_min}%")

    while not _encerrar.is_set():
        variacao = random.uniform(-3, 2)
        nivel_atual += variacao

        if random.random() < CHANCE_NIVEL_BAIXO:
            nivel_atual = max(0, limite_min - random.uniform(2, 8))
            log(sensor_id, "⚠ Simulando evento de nível baixo...")

        nivel_atual = max(0.0, min(100.0, nivel_atual))

        try:
            resp = requests.post(
                f"{base_url}/iot/agua/{sensor_id}",
                json={"nivel": round(nivel_atual, 1)},
                headers={"X-Device-Token": token},
                timeout=8,
            )
            if resp.status_code == 201:
                alerta = resp.json().get("alerta", False)
                tag = " 🔴 ALERTA" if alerta else ""
                log(sensor_id, f"Nível enviado: {nivel_atual:.1f}%{tag}")
            else:
                log(sensor_id, f"✗ Servidor respondeu {resp.status_code}: {resp.text[:120]}")
        except requests.exceptions.RequestException as e:
            log(sensor_id, f"✗ Falha de conexão: {e}")

        _encerrar.wait(INTERVALO_AGUA_S)


def thread_controlador_portoes(base_url: str, cfg_portoes: dict):
    token = cfg_portoes["token"]
    portoes = cfg_portoes["lista"]

    estado_fisico = {p["id"]: "fechado" for p in portoes}
    ultimo_reportado = {p["id"]: None for p in portoes}

    log("portoes", f"Controlador iniciado. Portões: {[p['id'] for p in portoes]}")

    while not _encerrar.is_set():
        for portao in portoes:
            pid = portao["id"]
            try:
                resp = requests.get(
                    f"{base_url}/iot/portao/{pid}/comando",
                    headers={"X-Device-Token": token},
                    timeout=8,
                )
                if resp.status_code != 200:
                    log("portoes", f"✗ Consultar comando de {pid}: HTTP {resp.status_code}")
                    continue

                desejado = resp.json().get("estado_desejado")

            except requests.exceptions.RequestException as e:
                log("portoes", f"✗ Falha de conexão consultando {pid}: {e}")
                continue

            if desejado == estado_fisico[pid]:
                if ultimo_reportado[pid] != desejado:
                    _reportar_status_portao(base_url, token, pid, desejado)
                    ultimo_reportado[pid] = desejado
                continue

            log("portoes", f"{pid}: comando recebido = '{desejado}' (atual = '{estado_fisico[pid]}'). "
                            f"Acionando motor...")
            _encerrar.wait(TEMPO_CURSO_PORTAO_S)

            estado_fisico[pid] = desejado
            _reportar_status_portao(base_url, token, pid, desejado)
            ultimo_reportado[pid] = desejado
            log("portoes", f"{pid}: motor concluído. Estado físico agora = '{desejado}'.")

        _encerrar.wait(INTERVALO_POLL_S)


def _reportar_status_portao(base_url: str, token: str, pid: str, estado: str):
    try:
        resp = requests.post(
            f"{base_url}/iot/portao/{pid}/status",
            json={"estado": estado},
            headers={"X-Device-Token": token},
            timeout=8,
        )
        if resp.status_code != 200:
            log("portoes", f"✗ Reportar status de {pid}: HTTP {resp.status_code}")
    except requests.exceptions.RequestException as e:
        log("portoes", f"✗ Falha ao reportar status de {pid}: {e}")


def thread_controlador_ac(base_url: str, cfg_ac: dict):
    token = cfg_ac["token"]
    quantidade_salas = cfg_ac.get("quantidade", 10)

    estado_fisico = "desligado"
    ultimo_reportado = None

    log("ac", f"Controlador iniciado. Salas atendidas: {quantidade_salas}")

    while not _encerrar.is_set():
        try:
            resp = requests.get(
                f"{base_url}/iot/ac/comando",
                headers={"X-Device-Token": token},
                timeout=8,
            )
            if resp.status_code != 200:
                log("ac", f"✗ Consultar comando: HTTP {resp.status_code}")
                _encerrar.wait(INTERVALO_POLL_S)
                continue

            desejado = resp.json().get("estado_desejado")

        except requests.exceptions.RequestException as e:
            log("ac", f"✗ Falha de conexão: {e}")
            _encerrar.wait(INTERVALO_POLL_S)
            continue

        if desejado != estado_fisico:
            log("ac", f"Comando recebido = '{desejado}'. Disparando infravermelho "
                       f"nas {quantidade_salas} salas...")
            _encerrar.wait(TEMPO_ENVIO_IR_S)
            estado_fisico = desejado
            log("ac", f"Infravermelho disparado em todas as salas. Estado = '{desejado}'.")

        if ultimo_reportado != estado_fisico:
            try:
                resp = requests.post(
                    f"{base_url}/iot/ac/status",
                    json={"estado": estado_fisico},
                    headers={"X-Device-Token": token},
                    timeout=8,
                )
                if resp.status_code == 200:
                    ultimo_reportado = estado_fisico
                else:
                    log("ac", f"✗ Reportar status: HTTP {resp.status_code}")
            except requests.exceptions.RequestException as e:
                log("ac", f"✗ Falha ao reportar status: {e}")

        _encerrar.wait(INTERVALO_POLL_S)


def login_admin(sessao: requests.Session, base_url: str) -> dict | None:
    print("\nPara usar os comandos manuais (abrir/fechar/ligar/desligar), "
          "informe a senha de um usuário com perfil portaria ou admin.")
    senha = input("Senha (ou Enter para pular e só observar a simulação): ").strip()
    if not senha:
        return None

    try:
        sessao.post(f"{base_url}/login", data={"senha": senha}, timeout=8)
        r = sessao.get(f"{base_url}/api/eu", timeout=8)
        if r.status_code == 200:
            usuario = r.json()
            print(f"✓ Login OK: {usuario['nome']} ({usuario['perfil']})\n")
            return usuario
    except requests.exceptions.RequestException as e:
        print(f"✗ Falha ao conectar para login: {e}")

    print("✗ Login falhou — comandos manuais indisponíveis nesta sessão.\n")
    return None


def console_interativo(base_url: str, cfg: dict):
    sessao = requests.Session()
    usuario = login_admin(sessao, base_url)

    print("Comandos disponíveis (digite e pressione Enter):")
    print("  abrir principal | fechar principal")
    print("  abrir secundario | fechar secundario")
    print("  ligar ac | desligar ac")
    print("  sair")
    print()

    while not _encerrar.is_set():
        try:
            cmd = input("> ").strip().lower()
        except EOFError:
            break

        if cmd in ("sair", "exit", "quit"):
            _encerrar.set()
            break

        if not usuario:
            print("Nenhum usuário logado — não é possível enviar comandos manuais.")
            continue

        rota = None
        if cmd == "abrir principal":   rota = "/iot/portao/principal/abrir"
        elif cmd == "fechar principal":  rota = "/iot/portao/principal/fechar"
        elif cmd == "abrir secundario":  rota = "/iot/portao/secundario/abrir"
        elif cmd == "fechar secundario": rota = "/iot/portao/secundario/fechar"
        elif cmd == "ligar ac":          rota = "/iot/ac/ligar"
        elif cmd == "desligar ac":       rota = "/iot/ac/desligar"
        else:
            print("Comando não reconhecido.")
            continue

        try:
            r = sessao.post(f"{base_url}{rota}", timeout=8)
            if r.status_code == 200:
                print(f"✓ {r.json().get('mensagem', 'Comando enviado.')}")
            else:
                print(f"✗ Servidor respondeu {r.status_code}: {r.text[:150]}")
        except requests.exceptions.RequestException as e:
            print(f"✗ Falha de conexão: {e}")


def main():
    print("=" * 60)
    print("  Smart Campus ETEPLAP — Simulador de Dispositivos IoT")
    print("=" * 60)

    cfg = carregar_config()
    base_url = obter_endereco_servidor()

    threads = []

    for sensor in cfg["agua"]["sensores"]:
        t = threading.Thread(target=thread_sensor_agua, args=(base_url, sensor),
                             daemon=True, name=f"agua-{sensor['id']}")
        threads.append(t)

    t_portoes = threading.Thread(target=thread_controlador_portoes,
                                 args=(base_url, cfg["portoes"]),
                                 daemon=True, name="portoes")
    threads.append(t_portoes)

    t_ac = threading.Thread(target=thread_controlador_ac,
                            args=(base_url, cfg["ar_condicionado"]),
                            daemon=True, name="ac")
    threads.append(t_ac)

    for t in threads:
        t.start()

    print(f"\n{len(threads)} dispositivo(s) simulado(s) rodando em segundo plano.\n")

    try:
        console_interativo(base_url, cfg)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nEncerrando simulação...")
        _encerrar.set()
        time.sleep(1)


if __name__ == "__main__":
    main()
