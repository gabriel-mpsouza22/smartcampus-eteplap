"""
Ponto de entrada do executável final entregue ao cliente.

Em vez de abrir o navegador padrão, sobe o servidor Flask (app.py) numa
thread em segundo plano e abre uma janela nativa (webview) apontando
para ele — para o usuário final não parece "um site", parece um
programa comum do Windows.

Este arquivo é o entrypoint usado pelo PyInstaller (ver
instalador/build_exe.py), não o app.py diretamente.

IMPORTANTE — por que a sincronização abaixo existe:
Um .exe "onefile" do PyInstaller se auto-extrai para uma pasta
temporária (sys._MEIPASS) toda vez que é executado, e essa pasta é
apagada quando o programa fecha. Se o SCEDS (usuários, alunos, tudo)
morasse só ali dentro, os dados da escola sumiriam a cada reinício.
Por isso os dados reais (SCEDS, config.json, .secret_key) vivem numa
pasta persistente entre execuções — hoje %LOCALAPPDATA%\\SmartCampus,
não mais ao lado do próprio .exe (ver _pasta_dados_persistente logo
abaixo para o motivo da mudança) — e a cada início copiamos o
config.json/.secret_key de lá para dentro do bundle temporário, para
que os módulos (que sempre leram `<pasta do projeto>/core/config.json`)
continuem funcionando sem precisar ser alterados um a um.
"""

import os
import sys
import json
import shutil
import socket
import subprocess
import threading
import time
import logging
import traceback
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE))

RODANDO_CONGELADO = getattr(sys, "frozen", False)


def _pasta_dados_persistente() -> Path:
    """
    Pasta onde config.json, .secret_key, sceds/data e a licença
    realmente moram — separada de onde o .exe está.

    Antes, esta função devolvia a pasta do próprio .exe
    (Path(sys.executable).parent). Isso significava que os dados da
    escola iam parar em QUALQUER pasta onde o cliente decidisse colar
    o .exe — inclusive Downloads, como aconteceu na prática. Downloads
    é uma pasta que ferramentas de limpeza, sincronização de nuvem
    (OneDrive/Google Drive apontando para lá) ou o próprio usuário
    arrumando arquivos têm bem mais chance de mexer ou apagar sem
    querer do que uma pasta de dados de aplicativo do Windows.

    Agora usa %LOCALAPPDATA%\\SmartCampus — pasta oficial do Windows
    para dados do usuário atual: fica dentro de AppData (oculta por
    padrão no Explorer), não é sincronizada por padrão por nenhum
    serviço de nuvem comum, e continua funcionando não importa para
    onde o .exe seja movido, copiado de novo ou reinstalado.

    Dados de uma instalação já existente (na pasta antiga, ao lado do
    .exe) são migrados automaticamente na primeira execução com esta
    versão — ver _migrar_dados_antigos_se_necessario().
    """
    if not RODANDO_CONGELADO:
        return BASE

    base_appdata = os.environ.get("LOCALAPPDATA")
    if not base_appdata:
        # Fallback extremamente raro (variável de ambiente ausente ou
        # corrompida) — cai de volta no comportamento antigo em vez de
        # travar o programa por completo.
        logging.warning("[Dados] LOCALAPPDATA não encontrado — usando a pasta do .exe como antes.")
        return Path(sys.executable).resolve().parent

    pasta = Path(base_appdata) / "SmartCampus"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _migrar_dados_antigos_se_necessario(pasta_dados: Path) -> None:
    """
    Instalações feitas com uma versão anterior deste launcher guardavam
    tudo ao lado do .exe. Sem isto, quem já usava o programa "perderia"
    o cadastro da escola inteiro na primeira vez que abrisse a versão
    nova (o programa acharia a pasta %LOCALAPPDATA%\\SmartCampus vazia
    e começaria do zero).

    Só migra quando a pasta antiga tem um config.json (instalação real
    já existente) E a pasta nova ainda não tem um (nunca migrado, nunca
    usado antes) — nunca sobrescreve dados já presentes na pasta nova.
    """
    if not RODANDO_CONGELADO:
        return

    pasta_antiga = Path(sys.executable).resolve().parent
    if pasta_antiga == pasta_dados:
        return  # fallback do LOCALAPPDATA ausente: são a mesma pasta, nada a migrar

    config_novo = pasta_dados / "core" / "config.json"
    config_antigo = pasta_antiga / "core" / "config.json"
    if config_novo.exists() or not config_antigo.exists():
        return  # já migrado antes, ou instalação genuinamente nova (nada pra trazer)

    logging.info(f"[Migração] Instalação antiga detectada em '{pasta_antiga}' — migrando para '{pasta_dados}'.")
    for nome in ("core", "sceds", "backups", "logs"):
        origem = pasta_antiga / nome
        destino = pasta_dados / nome
        if origem.exists() and not destino.exists():
            shutil.copytree(origem, destino)
            logging.info(f"[Migração] Copiado '{origem}' → '{destino}'.")

    origem_licenca = pasta_antiga / "licenca.smc"
    destino_licenca = pasta_dados / "licenca.smc"
    if origem_licenca.exists() and not destino_licenca.exists():
        shutil.copy2(origem_licenca, destino_licenca)
        logging.info("[Migração] Licença copiada para a nova pasta de dados.")

    # Os arquivos antigos NÃO são apagados de propósito: se algo der
    # errado na cópia, o cliente não perde nada — na pior das hipóteses
    # os dados ficam duplicados numa pasta que não é mais usada.
    logging.info("[Migração] Concluída. Os arquivos antigos foram mantidos (não apagados) por segurança.")


def _criar_atalho_area_trabalho_se_necessario() -> None:
    """
    Cria um atalho para o Smart Campus na Área de Trabalho do usuário
    atual, caso ainda não exista.

    O instalador gráfico (instalador_gui/SmartCampus.iss, Inno Setup)
    já oferece essa opção durante a instalação — isto aqui é uma rede
    de segurança para quem recebeu só o .exe solto (ex.: copiado
    manualmente para dentro de Downloads) e não passou pelo instalador:
    sem nenhum atalho, a única forma de reabrir o programa depois de
    fechar a janela seria vasculhar a pasta de novo.

    Só roda no .exe empacotado — em desenvolvimento (python launcher.py)
    não faz sentido nenhum criar atalho. Nunca impede o programa de
    abrir: qualquer falha aqui só é registrada no log.
    """
    if not RODANDO_CONGELADO:
        return
    try:
        area_trabalho = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        if not area_trabalho.is_dir():
            # Em algumas máquinas o OneDrive redireciona a Área de
            # Trabalho para outro caminho — se não achamos a pasta
            # esperada, não arriscamos criar o atalho no lugar errado.
            return

        atalho = area_trabalho / "Smart Campus.lnk"
        if atalho.exists():
            return  # já existe — não sobrescreve (o usuário pode ter movido/personalizado)

        alvo = sys.executable
        comando_ps = (
            "$WshShell = New-Object -ComObject WScript.Shell; "
            f"$Shortcut = $WshShell.CreateShortcut('{atalho}'); "
            f"$Shortcut.TargetPath = '{alvo}'; "
            f"$Shortcut.WorkingDirectory = '{Path(alvo).parent}'; "
            f"$Shortcut.IconLocation = '{alvo}'; "
            f"$Shortcut.Description = 'Smart Campus'; "
            "$Shortcut.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando_ps],
            check=True, capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        logging.info(f"[Atalho] Criado em '{atalho}'.")
    except Exception:
        logging.exception("[Atalho] Falha ao criar atalho na Área de Trabalho (não crítico).")



def _registrar_crash_bruto(mensagem: str) -> Path:
    """
    Grava um log de crash usando só escrita de arquivo pura (open/write),
    sem depender do módulo `logging` já estar configurado — porque um
    crash pode acontecer ANTES de _preparar_log() rodar (ex.: falha ao
    importar `webview`, DLL do sistema faltando como o WebView2 Runtime,
    etc.). Sem isto, esse tipo de falha fecha o programa "no escuro":
    nenhum arquivo, nenhuma pista, só a janela abrindo e fechando.
    """
    caminho = _pasta_dados_persistente() / "smartcampus_erro_fatal.log"
    try:
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.write(mensagem)
            f.write("\n")
    except Exception:
        pass  # se nem isso funcionar, não há mais nada a fazer
    return caminho


try:
    import webview
except Exception:
    # Import de nível de módulo — se falhar aqui (ex.: WebView2 Runtime
    # ausente, DLL do sistema faltando), nada do resto do arquivo roda,
    # e sem isto o processo simplesmente encerra sem deixar rastro.
    _caminho = _registrar_crash_bruto(
        "Falha ao importar o módulo 'webview'. Causas mais comuns no "
        "Windows: WebView2 Runtime da Microsoft não instalado, ou "
        "Visual C++ Redistributable ausente.\n\n" + traceback.format_exc()
    )
    try:
        # Tenta ao menos mostrar ALGO ao usuário via caixa de mensagem
        # nativa do Windows (não depende do próprio webview funcionar).
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "Não foi possível iniciar o Smart Campus.\n\n"
            "É provável que falte o 'Microsoft Edge WebView2 Runtime' "
            "neste computador — baixe em:\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            f"Detalhes técnicos foram salvos em:\n{_caminho}",
            "Smart Campus — Erro ao iniciar",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        pass
    sys.exit(1)


def _sincronizar_dados_persistentes() -> dict:
    """
    Garante que `pasta_dados/core/config.json`, `.secret_key` e
    `sceds/data` existam (copiando do bundle na primeira execução) e
    então espelha o config.json/.secret_key persistentes de volta para
    dentro do bundle temporário, para os módulos lerem normalmente.
    Retorna o config já carregado.
    """
    pasta_dados = _pasta_dados_persistente()

    if not RODANDO_CONGELADO:
        with open(BASE / "core" / "config.json", encoding="utf-8") as f:
            return json.load(f)

    # Migração de instalações antigas já aconteceu em main(), antes até
    # da checagem de licença (ver comentário lá) — chamar de novo aqui
    # seria redundante, mas a função é idempotente, então não há risco
    # em manter caso esta função venha a ser chamada de outro lugar no
    # futuro sem passar por main() primeiro.
    _migrar_dados_antigos_se_necessario(pasta_dados)

    destino_core = pasta_dados / "core"
    destino_core.mkdir(parents=True, exist_ok=True)

    destino_config = destino_core / "config.json"
    if not destino_config.exists():
        with open(BASE / "core" / "config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["caminho_base"] = str(pasta_dados)
        with open(destino_config, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    destino_secret = destino_core / ".secret_key"
    origem_secret = BASE / "core" / ".secret_key"
    if not destino_secret.exists() and origem_secret.exists():
        shutil.copy2(origem_secret, destino_secret)

    destino_sceds = pasta_dados / "sceds" / "data"
    origem_sceds = BASE / "sceds" / "data"
    # IMPORTANTE: não usar "if not destino_sceds.exists(): copytree(...)".
    # Se uma execução anterior foi interrompida (crash, fechada no meio,
    # ou um .exe de teste anterior) a pasta pode ter sido criada mas
    # ficado incompleta — e como ela já "existe", a cópia nunca mais
    # rodaria, deixando a instalação permanentemente sem usuarios.sceds
    # e outras tabelas (o que causa erro 500 ao tentar logar). Por isso
    # copiamos arquivo por arquivo, preenchendo apenas o que faltar,
    # sem nunca sobrescrever dados reais já existentes.
    if origem_sceds.exists():
        destino_sceds.mkdir(parents=True, exist_ok=True)
        for arquivo_origem in origem_sceds.iterdir():
            arquivo_destino = destino_sceds / arquivo_origem.name
            if not arquivo_destino.exists():
                if arquivo_origem.is_dir():
                    shutil.copytree(arquivo_origem, arquivo_destino)
                else:
                    shutil.copy2(arquivo_origem, arquivo_destino)

    # Espelha os dados persistentes de volta para dentro do bundle,
    # sobrescrevendo os iniciais — mantido para compatibilidade com
    # qualquer código legado que ainda monte o caminho na mão em vez
    # de usar core.config_path.resolver_config_path().
    shutil.copy2(destino_config, BASE / "core" / "config.json")
    if destino_secret.exists():
        shutil.copy2(destino_secret, BASE / "core" / ".secret_key")

    # IMPORTANTE: aponta core.config_path.resolver_config_path() (usado
    # por app.py, core/auth.py, core/router.py, wizard/api_wizard.py
    # etc.) diretamente para o config.json persistente ao lado do .exe,
    # em vez da cópia dentro da pasta temporária do PyInstaller
    # (_MEIPASS). Sem isto, qualquer escrita feita DURANTE a execução
    # (ex.: o Wizard salvando os módulos contratados) vai parar só na
    # cópia temporária — que é apagada quando o programa fecha — e
    # some na próxima abertura, quando este sync espelha de volta o
    # config.json antigo (sem a alteração) por cima dela.
    os.environ["SMARTCAMPUS_CONFIG_PATH"] = str(destino_config)

    with open(destino_config, encoding="utf-8") as f:
        return json.load(f)


def _inicializar_dados_demo(pasta_dados: Path) -> None:
    """
    Na primeira abertura do .exe, transforma o SCEDS recém-criado em uma
    instalação demonstrável: cria/valida as tabelas e popula uma massa
    relacional para todos os módulos ativos.

    A operação é idempotente por instalação. O marcador só é escrito pelo
    gerador depois de terminar com sucesso; se a primeira inicialização for
    interrompida, a próxima abertura tenta novamente.
    """
    marcador = pasta_dados / "sceds" / ".mock_initialized"
    if marcador.exists():
        return

    import gerar_mock_data
    logging.info("Primeira execução detectada: gerando dados de demonstração...")
    gerar_mock_data.main(base=pasta_dados)
    marcador.parent.mkdir(parents=True, exist_ok=True)
    marcador.write_text(
        "SmartCampus SCEDS inicializado com dados de demonstração.\n",
        encoding="utf-8",
    )
    logging.info("Dados de demonstração inicializados com sucesso.")


def _preparar_log(pasta_dados: Path) -> Path:
    """
    App é --windowed (sem console), então stderr/print somem no vazio.
    Sem isso não há NENHUMA forma de saber por que o servidor não subiu.
    Grava um log de verdade, em arquivo, ao lado do .exe.
    """
    caminho_log = pasta_dados / "smartcampus_erro.log"
    logging.basicConfig(
        level=logging.INFO,
        filename=str(caminho_log),
        filemode="a",
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    return caminho_log


def _porta_livre(preferida: int) -> int:
    """Usa a porta configurada se estiver livre; senão, pega uma porta livre qualquer."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferida))
            return preferida
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _subir_servidor(porta: int):
    try:
        import app as app_modulo  # importa o Flask app já configurado
        # host 0.0.0.0: aceita conexões de outros dispositivos na rede local
        # (ex.: celular acessando pelo IP do PC), além da própria máquina.
        app_modulo.app.run(host="0.0.0.0", port=porta, debug=False, threaded=True, use_reloader=False)
    except Exception:
        # Essa função roda numa thread em segundo plano: se não
        # capturarmos aqui, a exceção só aparece no stderr (invisível,
        # já que o app é --windowed) e a janela principal fica esperando
        # a porta abrir para sempre, até estourar o timeout — sem
        # nenhuma pista do motivo real. Loga o traceback completo.
        logging.exception("Falha ao iniciar o servidor Flask (thread _subir_servidor)")


def _aguardar_servidor(porta: int, tentativas: int = 60) -> bool:
    for _ in range(tentativas):
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _tela_html_licenca(titulo: str, mensagem: str, fingerprint: str, mostrar_codigo: bool) -> str:
    bloco_codigo = f"""
        <div style="margin-top:20px; padding:16px; background:#F4F4F8; border-radius:10px;">
          <div style="font-size:13px; color:#555;">Código desta máquina (informe ao suporte):</div>
          <div style="font-size:22px; font-weight:700; letter-spacing:1px; margin-top:4px; user-select:all;">{fingerprint}</div>
        </div>
    """ if mostrar_codigo else ""
    return f"""
    <html><body style="font-family:sans-serif; padding:48px; max-width:560px; margin:0 auto; color:#1A1A2E;">
      <h1 style="font-size:22px;">{titulo}</h1>
      <p style="font-size:15px; line-height:1.5; color:#333;">{mensagem}</p>
      {bloco_codigo}
      <p style="margin-top:24px; font-size:13px; color:#777;">
        Depois de obter o arquivo de licença, coloque-o nesta mesma pasta do
        programa com o nome exato <code>licenca.smc</code> e abra o Smart
        Campus novamente.
      </p>
    </body></html>
    """


def _verificar_licenca(pasta_dados: Path):
    """
    Confere se existe uma licença válida para esta instalação/máquina
    antes de subir qualquer coisa. Retorna None se tudo certo, ou uma
    string HTML pronta para exibir na janela caso não possa continuar.
    """
    from core.licenca import verificar_ou_none
    from core.fingerprint import calcular_fingerprint

    caminho_licenca = pasta_dados / "licenca.smc"
    payload, erro = verificar_ou_none(caminho_licenca, pasta_cache=pasta_dados)

    if payload is not None:
        logging.info(f"[Licenca] OK — instituição: {payload.get('instituicao')}")
        return None

    fingerprint = calcular_fingerprint(pasta_dados)

    if erro == "SEM_LICENCA":
        logging.warning(f"[Licenca] Nenhuma licença encontrada. Código da máquina: {fingerprint}")
        return _tela_html_licenca(
            "Ativação necessária",
            "Este computador ainda não possui uma licença ativa do Smart Campus. "
            "Envie o código abaixo ao suporte técnico para receber seu arquivo de licença.",
            fingerprint, mostrar_codigo=True,
        )

    logging.warning(f"[Licenca] Licença inválida: {erro}")
    return _tela_html_licenca("Licença inválida", erro, fingerprint, mostrar_codigo=True)


def main():
    pasta_dados = _pasta_dados_persistente()
    # IMPORTANTE: migrar ANTES de preparar o log e verificar a licença —
    # ambos leem/escrevem dentro de pasta_dados. Se a migração rodasse
    # depois (como acontecia antes), um cliente já licenciado que
    # atualizasse para esta versão veria a tela de "ativação necessária"
    # por engano: a checagem de licença olharia a pasta nova (ainda
    # vazia) antes dos dados antigos serem trazidos para lá.
    _migrar_dados_antigos_se_necessario(pasta_dados)
    caminho_log = _preparar_log(pasta_dados)

    tela_bloqueio = None
    try:
        tela_bloqueio = _verificar_licenca(pasta_dados)
    except Exception:
        logging.exception("Falha ao verificar licença")
        tela_bloqueio = _tela_html_licenca(
            "Erro ao verificar licença",
            "Não foi possível verificar a licença deste computador. "
            "Contate o suporte técnico e envie o arquivo de log.",
            "indisponível", mostrar_codigo=False,
        )

    if tela_bloqueio:
        webview.create_window("Smart Campus — Ativação", html=tela_bloqueio, width=680, height=520)
        webview.start()
        return

    try:
        cfg = _sincronizar_dados_persistentes()
        _criar_atalho_area_trabalho_se_necessario()
        # gerar_mock_data.py (dados fictícios de exemplo) NÃO é chamado
        # automaticamente aqui. Ele é uma ferramenta manual, pra você
        # rodar na sua própria máquina antes de mostrar o sistema pra
        # uma escola ainda decidindo comprar — nunca deve rodar sozinho
        # na instalação de um cliente real. Um cliente novo abre com as
        # tabelas vazias que já vêm prontas em sceds/data/*.sceds, e
        # cadastra os dados reais da escola dele a partir daí.
        #
        # Se precisar gerar uma massa de demonstração na sua própria
        # máquina: python gerar_mock_data.py --confirmo-apagar-dados-reais
        # (sem licença presente na pasta, não precisa nem da flag).
        with open(pasta_dados / "core" / "config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        porta_configurada = int(cfg.get("porta_api", 5000))
        titulo_janela = cfg.get("nome_escola", "Smart Campus")

        porta = _porta_livre(porta_configurada)

        thread = threading.Thread(target=_subir_servidor, args=(porta,), daemon=True)
        thread.start()

        servidor_subiu = _aguardar_servidor(porta)
    except Exception:
        logging.exception("Falha antes de subir o servidor (main/_sincronizar_dados_persistentes)")
        servidor_subiu = False
        titulo_janela = "Smart Campus"

    if not servidor_subiu:
        webview.create_window(
            titulo_janela,
            html=(
                "<h1>Não foi possível iniciar o servidor.</h1>"
                f"<p>Detalhes do erro foram salvos em:<br><code>{caminho_log}</code></p>"
                "<p>Envie esse arquivo para o suporte técnico.</p>"
            ),
        )
    else:
        webview.create_window(
            titulo_janela,
            url=f"http://127.0.0.1:{porta}/",
            width=1280, height=800, min_size=(960, 600),
        )

    webview.start()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Rede de segurança final: qualquer exceção não prevista em
        # nenhum dos blocos internos de main() (ex.: webview.create_window
        # ou webview.start() falhando — hoje não estão em try/except
        # próprio) cai aqui em vez de fechar o programa sem deixar rastro.
        caminho = _registrar_crash_bruto(traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "O Smart Campus encontrou um erro inesperado e precisou "
                "fechar.\n\nDetalhes técnicos foram salvos em:\n"
                f"{caminho}\n\nEnvie este arquivo ao suporte técnico.",
                "Smart Campus — Erro inesperado",
                0x10,
            )
        except Exception:
            pass
        sys.exit(1)
