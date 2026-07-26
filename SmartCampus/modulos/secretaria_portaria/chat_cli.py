
import sys
import time
import json
import threading
from pathlib import Path

try:
    import requests
except ImportError:
    print("A biblioteca 'requests' não está instalada.")
    print("Instale com: pip install requests")
    sys.exit(1)

CONFIG_PATH = Path(__file__).resolve().parent / "chat_cli_config.json"
INTERVALO_POLL = 3


def carregar_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def salvar_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def obter_endereco_servidor() -> str:
    cfg = carregar_config()
    endereco = cfg.get("endereco_servidor")

    if endereco:
        usar = input(f"Usar servidor salvo ({endereco})? [S/n] ").strip().lower()
        if usar in ("", "s", "sim"):
            return endereco

    print("\nInforme o endereço do servidor Smart Campus.")
    print("Exemplo: http://192.168.0.108  (ou http://192.168.0.108:80)")
    endereco = input("Endereço: ").strip().rstrip("/")
    if not endereco.startswith("http"):
        endereco = "http://" + endereco

    cfg["endereco_servidor"] = endereco
    salvar_config(cfg)
    return endereco


def login(sessao: requests.Session, base_url: str) -> dict | None:
    """Faz login e retorna os dados do usuário (via /api/eu), ou None se falhar."""
    for _ in range(3):
        senha = input("\nSua senha de acesso: ").strip()
        try:
            resp = sessao.post(f"{base_url}/login", data={"senha": senha}, timeout=8)
        except requests.exceptions.ConnectionError:
            print(f"✗ Não foi possível conectar em {base_url}. Verifique o endereço e tente novamente.")
            return None
        except requests.exceptions.Timeout:
            print("✗ O servidor demorou para responder.")
            continue

        r_eu = sessao.get(f"{base_url}/api/eu", timeout=8)
        if r_eu.status_code == 200:
            return r_eu.json()

        print("✗ Senha incorreta. Tente novamente.")

    print("Número máximo de tentativas excedido.")
    return None


def limpar_tela():
    print("\033c", end="")


def loop_poll(sessao: requests.Session, base_url: str, meu_nome: str, estado: dict):
    """Thread em segundo plano: busca novas mensagens periodicamente."""
    while not estado["encerrar"]:
        try:
            r = sessao.get(
                f"{base_url}/api/chat/mensagens",
                params={"desde_id": estado["ultimo_id"]},
                timeout=8,
            )
            if r.status_code == 200:
                novas = r.json()
                for m in novas:
                    exibir_mensagem(m, meu_nome)
                    estado["ultimo_id"] = m["id"]
        except requests.exceptions.RequestException:
            pass

        time.sleep(INTERVALO_POLL)


def exibir_mensagem(msg: dict, meu_nome: str):
    hora = msg["data_hora"][11:16] if len(msg["data_hora"]) >= 16 else ""
    if msg["remetente"] == meu_nome:
        print(f"\r[{hora}] Você: {msg['texto']}")
    else:
        print(f"\r[{hora}] {msg['remetente']}: {msg['texto']}")
    print("Mensagem > ", end="", flush=True)


def main():
    print("=" * 50)
    print("  Smart Campus ETEPLAP — Chat da Portaria (CLI)")
    print("=" * 50)

    base_url = obter_endereco_servidor()
    sessao = requests.Session()

    usuario = login(sessao, base_url)
    if not usuario:
        input("\nPressione Enter para sair...")
        return

    if usuario["perfil"] not in ("portaria", "secretaria", "admin"):
        print(f"\n✗ Seu perfil ({usuario['perfil']}) não tem acesso a este chat.")
        input("Pressione Enter para sair...")
        return

    print(f"\n✓ Conectado como {usuario['nome']} ({usuario['perfil']})")
    print("Digite sua mensagem e pressione Enter. Digite /sair para encerrar.\n")

    estado = {"ultimo_id": 0, "encerrar": False}
    try:
        r = sessao.get(f"{base_url}/api/chat/mensagens", timeout=8)
        if r.status_code == 200:
            historico = r.json()
            for m in historico[-15:]:
                exibir_mensagem(m, usuario["nome"])
            if historico:
                estado["ultimo_id"] = historico[-1]["id"]
    except requests.exceptions.RequestException:
        print("(Não foi possível carregar o histórico agora.)")

    t = threading.Thread(target=loop_poll, args=(sessao, base_url, usuario["nome"], estado), daemon=True)
    t.start()

    try:
        while True:
            texto = input("Mensagem > ").strip()
            if not texto:
                continue
            if texto.lower() in ("/sair", "/exit", "/quit"):
                break

            try:
                r = sessao.post(f"{base_url}/api/chat/enviar", json={"texto": texto}, timeout=8)
                if r.status_code != 201:
                    erro = r.json().get("erro", "erro desconhecido")
                    print(f"✗ Não foi possível enviar: {erro}")
            except requests.exceptions.RequestException:
                print("✗ Falha de conexão ao enviar mensagem.")

    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        estado["encerrar"] = True
        print("\nEncerrando chat. Até logo!")


if __name__ == "__main__":
    main()
