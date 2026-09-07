"""
Gera o executável final do Smart Campus com PyInstaller.

Trocamos de Nuitka para PyInstaller pela simplicidade: PyInstaller não
tem plugins que tomam decisões próprias sobre quais módulos incluir
(o que causava os erros de "conflict between user and plugin decision"
que vínhamos vendo). Em troca, o código Python fica mais fácil de
extrair do .exe do que ficaria com Nuitka — se em algum momento a
proteção do código-fonte contra engenharia reversa voltar a ser
prioridade, vale reconsiderar o Nuitka. Por ora, o objetivo é ter um
.exe que simplesmente funciona de forma confiável.

USO (rodar numa máquina Windows, com o Python do projeto ativo — ou
simplesmente dar dois cliques em build.bat, que já faz tudo isto):

    pip install -r requirements.txt
    pip install pyinstaller
    python build_exe.py

Também dá pra gerar o .exe sem usar seu PC pra nada: veja
.github/workflows/build.yml (roda numa máquina Windows na nuvem, de
graça, toda vez que você envia código — o .exe fica pronto pra baixar
na aba "Actions" do repositório).

IMPORTANTE — antes de rodar isto para gerar o build de um cliente:
  1. Confirme que core/licenca_publica.pem existe (copiado de
     licenciamento/chave_publica.pem — veja licenciamento/gerar_chaves.py).
  2. NUNCA inclua a pasta licenciamento/ no build do cliente — ela não
     é referenciada por nenhum import do app e não deve, sob nenhuma
     circunstância, viajar com o .exe (contém, ou pode conter, a chave
     privada de assinatura de licenças).

O que você NÃO precisa mais fazer manualmente (o build já cuida
sozinho, sempre, em toda execução):
  - Limpar sceds/data/*.sceds ou dados de teste — o build gera as
    tabelas vazias do zero a cada vez, sempre a partir de
    _dados_semente/, nunca da sua pasta de trabalho local. Testar com
    `python app.py` ou demonstrar o sistema não contamina o próximo
    build, não importa o que ficou sujo na sua pasta local — ver
    _dados_semente/LEIA-ME.md.
  - core/.secret_key nunca entra no build de propósito — cada
    instalação gera a própria sozinha.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

# --------------------------------------------------------------------
# DETALHES DA INSTALAÇÃO / DO EXECUTÁVEL — edite só aqui.
# NÃO precisa mexer em mais nada abaixo neste arquivo para trocar
# nome ou ícone do executável.
# --------------------------------------------------------------------
NOME_EXECUTAVEL = "SmartCampus"  # PyInstaller adiciona o .exe sozinho
# Caminho de um arquivo .ico (256x256 recomendado). Se o arquivo não
# existir, o build segue sem ícone customizado (usa o padrão do
# Windows) — não precisa remover esta linha se você ainda não tem um.
ICONE = BASE / "static" / "icone.ico"

# Módulos/pacotes carregados dinamicamente via importlib em
# core/router.py — o PyInstaller não enxerga essas strings na análise
# estática, então cada um precisa ser listado aqui explicitamente. Se
# um módulo novo for adicionado a core/router.py, adicione o pacote
# correspondente aqui também (senão o build final vai simplesmente
# faltar aquele módulo, silenciosamente).
PACOTES_CARREGADOS_DINAMICAMENTE = [
    "modulos.sinal",
    "modulos.agendamento",
    "modulos.biblioteca",
    "modulos.secretaria_portaria",
    "modulos.iot",
    "modulos.ocorrencias",
    "modulos.evasao",
    "modulos.chaves",
    "modulos.chamados",
    "modulos.monitoramento",
    "modulos.alunos",
    "modulos.pontualidade",
    "modulos.saidas",
    "modulos.visitantes",
    "modulos.porteiro",
    "admin",
    "wizard",
    "core",
    "sceds",
    # pywebview escolhe o backend de janela (edgechromium/WebView2,
    # winforms, mshtml) em tempo de execução dentro de webview/guilib.py
    # usando import condicional. Diferente do Nuitka, o PyInstaller não
    # tem um plugin dedicado que resolve isso sozinho — então aqui
    # forçamos o pacote inteiro, sem risco de conflito (PyInstaller não
    # tem uma segunda "opinião" própria sobre esses módulos).
    "webview",
]

ARQUIVOS_DE_DADOS = [
    # (origem relativa ao projeto, destino dentro do bundle)
    # Só código/assets estáticos aqui — templates, static e o certificado
    # de licença nunca são modificados por python app.py/wizard rodando
    # localmente, então tanto faz ler da pasta de trabalho para eles.
    #
    # config.json, turmas.json, configs de módulo e schemas .sceds NÃO
    # aparecem aqui de propósito — ver _dados_semente/LEIA-ME.md. Eles
    # vêm de _dados_semente/ (ver _montar_semente logo abaixo), nunca da
    # pasta de trabalho, porque testar/demonstrar localmente modifica
    # esses arquivos de verdade — foi isso que causou a instituição e as
    # turmas de um teste antigo aparecendo num build novo, e o erro 500
    # no cadastro de alunos (caminho_base desatualizado em config.json).
    ("templates", "templates"),
    ("static", "static"),
    ("core/licenca_publica.pem", "core/licenca_publica.pem"),
]

# Arquivos de configuração/estado que vêm de _dados_semente/ (nunca da
# pasta de trabalho normal) — ver _dados_semente/LEIA-ME.md.
ARQUIVOS_SEMENTE = [
    "core/config.json",
    "core/turmas.json",
    "modulos/agendamento/recursos.json",
    "modulos/iot/dispositivos.json",
    "modulos/iot/estado_ac.json",
    "modulos/iot/estado_portoes.json",
    "modulos/sinal/config_sinal.json",
    "modulos/sinal/estado_sinal.json",
    "modulos/sinal/horarios_padrao.json",
    "modulos/sinal/horarios_prova.json",
    "modulos/sinal/horarios_sabado.json",
    "modulos/sinal/whatsapp_grupos.json",
]

ARQUIVOS_DE_DADOS.append(("sceds/manifest.json", "sceds/manifest.json"))
# "sceds/data" também não entra em ARQUIVOS_DE_DADOS — ver
# TABELAS_SCEDS_VAZIAS mais abaixo e a função `_montar_tabelas_sceds_vazias`.

# Tabelas que todo cliente novo precisa ter presentes, mas vazias, no
# primeiro boot (o wizard de instalação cria o admin e a config; o
# resto o próprio cliente cadastra depois).
TABELAS_SCEDS_VAZIAS = [
    "alunos", "usuarios", "livros", "emprestimos", "ocorrencias",
    "evasao_frequencia", "reservas", "chaves", "chaves_movimentos",
    "compromissos", "mensagens_chat", "chamados", "leituras_iot",
]


def _checar_pre_requisitos() -> None:
    publica = BASE / "core" / "licenca_publica.pem"
    if not publica.exists():
        raise SystemExit(
            "core/licenca_publica.pem não encontrado.\n"
            "Rode licenciamento/gerar_chaves.py (uma vez) e copie "
            "chave_publica.pem para core/licenca_publica.pem antes de "
            "gerar o executável."
        )

    semente = BASE / "_dados_semente"
    faltando = [a for a in ARQUIVOS_SEMENTE if not (semente / a).exists()]
    if faltando:
        raise SystemExit(
            "_dados_semente/ está incompleta — faltando: " + ", ".join(faltando) +
            "\nVeja _dados_semente/LEIA-ME.md."
        )
    for tabela in TABELAS_SCEDS_VAZIAS:
        if not (semente / "sceds" / "data" / f"{tabela}.schema.json").exists():
            raise SystemExit(
                f"_dados_semente/sceds/data/{tabela}.schema.json não encontrado.\n"
                "Veja _dados_semente/LEIA-ME.md."
            )
    # core/.secret_key NÃO é incluído no build (não está em
    # ARQUIVOS_DE_DADOS nem em ARQUIVOS_SEMENTE) — cada instalação
    # gera a própria sozinha na primeira execução (ver app.py). Isso
    # só avisa se ele existir aqui na pasta de trabalho local, pra você
    # saber que é normal e não precisa se preocupar — ele não viaja
    # pro cliente de jeito nenhum.
    if (BASE / "core" / ".secret_key").exists():
        print(
            "Nota: core/.secret_key existe na sua pasta de trabalho local "
            "(gerado por python app.py rodando aqui). Ele NÃO entra no "
            "build — cada instalação gera a própria."
        )

    if sys.platform == "win32":
        try:
            import clr  # noqa: F401 — fornecido pelo pacote 'pythonnet'
        except ImportError:
            raise SystemExit(
                "O pacote 'pythonnet' não está instalado neste ambiente.\n"
                "O pywebview (usado pelo launcher.py para abrir a janela do "
                "programa) depende dele no Windows — inclusive o backend "
                "WebView2/edgechromium, que é o que o Smart Campus usa de "
                "verdade, não só o backend antigo Windows Forms.\n\n"
                "Corrija com: pip install -r requirements.txt\n"
                "(pythonnet já está listado lá, condicionado a Windows)."
            )

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "O pacote 'pyinstaller' não está instalado neste ambiente.\n"
            "Corrija com: pip install pyinstaller"
        )


def _montar_tabelas_sceds_vazias(montagem: Path) -> None:
    """
    Gera sceds/data/*.sceds vazios (em texto puro, sem criptografia)
    direto na pasta de montagem do build — nunca copia
    sceds/data/*.sceds da sua pasta local do projeto.

    Por quê: sceds/crypto.py cifra qualquer tabela .sceds gravada por
    save_json (gerar_mock_data.py, resetar_ambiente_demo.py, ou o
    próprio app.py rodando localmente), usando uma chave criada em
    sceds/.chave_data — chave que fica só na SUA máquina de propósito
    (cada instalação de cliente deve ter a própria). Se copiássemos
    sceds/data/ direto da sua pasta local depois de qualquer teste/
    demonstração, o build ia empacotar arquivos cifrados com a SUA
    chave, sem a chave junto — o programa então cria uma chave nova no
    primeiro boot do cliente, tenta abrir os arquivos antigos com ela,
    e falha com "Arquivo de dados corrompido: não é um token cifrado
    válido nem um JSON legado reconhecível." — foi exatamente esse
    erro visto na etapa "Configurando módulos" do wizard.
    Gerando os vazios aqui, direto em texto puro, elimina esse risco
    de vez: não existe chave envolvida, não importa o que sobrou de
    teste na sua pasta local.

    Os .schema.json (não têm dado pessoal, não são cifrados) vêm de
    _dados_semente/sceds/data/ — mesma razão dos outros arquivos de
    configuração, ver _dados_semente/LEIA-ME.md: python app.py rodando
    localmente pode adicionar colunas num schema (migração automática,
    ver adicionar_coluna_se_ausente em core/alunos.py e outros) antes
    de você ter certeza de que quer aquilo em todo build novo.
    """
    origem_schemas = BASE / "_dados_semente" / "sceds" / "data"
    destino = montagem / "sceds" / "data"
    destino.mkdir(parents=True, exist_ok=True)

    for tabela in TABELAS_SCEDS_VAZIAS:
        schema_origem = origem_schemas / f"{tabela}.schema.json"
        if not schema_origem.exists():
            raise SystemExit(
                f"_dados_semente/sceds/data/{tabela}.schema.json não encontrado — "
                "o build não pode continuar sem o schema de cada tabela."
            )
        shutil.copy2(schema_origem, destino / f"{tabela}.schema.json")

        with open(destino / f"{tabela}.sceds", "w", encoding="utf-8") as f:
            json.dump({"registros": [], "proximo_id": 1}, f, ensure_ascii=False, indent=2)

    print(f"✓ {len(TABELAS_SCEDS_VAZIAS)} tabelas SCEDS vazias geradas (texto puro, sem criptografia) em {destino}")


def main():
    _checar_pre_requisitos()

    saida = BASE / "dist_exe"
    build_tmp = BASE / "build_tmp"
    montagem = BASE / "_dados_montagem"  # pasta temporária, apagada no final
    if saida.exists():
        shutil.rmtree(saida)
    saida.mkdir()
    if montagem.exists():
        shutil.rmtree(montagem)
    montagem.mkdir()

    # Em vez de passar cada arquivo pro PyInstaller com --add-data
    # individual (o "destino" desse parâmetro é sempre uma PASTA, nunca
    # o caminho completo do arquivo final — passar
    # "core/licenca_publica.pem" como destino faz o PyInstaller criar
    # uma PASTA com esse nome e botar o arquivo original dentro dela,
    # gerando "arquivo" e "pasta" com o mesmo nome e caminho — o
    # programa tenta abrir isso como arquivo, encontra uma pasta, e no
    # Windows isso aparece como PermissionError, não como um erro óbvio
    # de "é um diretório"), montamos a estrutura final EXATA numa pasta
    # temporária primeiro e mandamos o PyInstaller copiar essa pasta
    # inteira de uma vez. Copiar pasta-para-pasta é isento dessa
    # ambiguidade.
    for origem, destino in ARQUIVOS_DE_DADOS:
        caminho_origem = BASE / origem
        if not caminho_origem.exists():
            print(f"AVISO: '{origem}' não encontrado, pulando.")
            continue
        caminho_destino = montagem / destino
        caminho_destino.parent.mkdir(parents=True, exist_ok=True)
        if caminho_origem.is_dir():
            shutil.copytree(caminho_origem, caminho_destino, dirs_exist_ok=True)
        else:
            shutil.copy2(caminho_origem, caminho_destino)

    _montar_tabelas_sceds_vazias(montagem)

    for caminho_relativo in ARQUIVOS_SEMENTE:
        caminho_origem = BASE / "_dados_semente" / caminho_relativo
        caminho_destino = montagem / caminho_relativo
        caminho_destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(caminho_origem, caminho_destino)
    print(f"✓ {len(ARQUIVOS_SEMENTE)} arquivos de configuração vindos de _dados_semente/ (não da pasta de trabalho)")

    separador = ";" if sys.platform == "win32" else ":"

    comando = [
        sys.executable, "-m", "PyInstaller",
        # --onedir (não --onefile): o .exe roda direto dos arquivos já
        # extraídos, sem se autoextrair para uma pasta temporária nova
        # a cada abertura. --onefile causava PermissionError
        # intermitente (Windows Defender escaneando/travando arquivos
        # recém-extraídos no exato instante em que o programa tentava
        # lê-los) — como cada execução usa uma pasta temp diferente, o
        # problema não é sempre reproduzível, só aparece "às vezes".
        # --onedir elimina essa classe inteira de erro por não extrair
        # nada em tempo de execução. O resultado final vira uma PASTA
        # com SmartCampus.exe dentro, em vez de um único arquivo — o
        # cliente continua só clicando no .exe normalmente.
        "--onedir",
        "--windowed",  # sem console — equivalente ao --windows-console-mode=disable do Nuitka
        "--noconfirm",
        "--name", NOME_EXECUTAVEL,
        "--distpath", str(saida),
        "--workpath", str(build_tmp),
        "--specpath", str(build_tmp),
        # Uma única entrada: copia a pasta de montagem inteira,
        # preservando a estrutura de subpastas exatamente como está
        # nela, para a raiz do bundle (o "." de destino).
        "--add-data", f"{montagem}{separador}.",
    ]

    if ICONE.exists():
        comando += ["--icon", str(ICONE)]

    for pacote in PACOTES_CARREGADOS_DINAMICAMENTE:
        comando += ["--hidden-import", pacote]
        comando += ["--collect-submodules", pacote]

    comando.append(str(BASE / "launcher.py"))

    print("Executando PyInstaller (isso pode levar alguns minutos)...\n")
    print(" ".join(comando), "\n")
    resultado = subprocess.run(comando, cwd=BASE)

    if build_tmp.exists():
        shutil.rmtree(build_tmp, ignore_errors=True)
    if montagem.exists():
        shutil.rmtree(montagem, ignore_errors=True)

    if resultado.returncode != 0:
        raise SystemExit(
            "\nFalha na compilação. Leia a saída do PyInstaller acima — "
            "mensagens 'ModuleNotFoundError' geralmente significam que "
            "falta adicionar o pacote em PACOTES_CARREGADOS_DINAMICAMENTE."
        )

    pasta_final = saida / NOME_EXECUTAVEL
    print(f"\n✓ Executável gerado em: {pasta_final / (NOME_EXECUTAVEL + '.exe')}")
    print(
        f"\nPara entregar ao cliente: copie/zip a pasta inteira "
        f"'{pasta_final}' (não só o .exe — ele precisa dos arquivos "
        "ao lado dele para funcionar) e mande o cliente rodar o .exe "
        "de dentro dela."
    )
    print(
        "\nLembrete: o .exe sozinho não roda sem uma licença válida. "
        "Use licenciamento/emitir_licenca.py para gerar o arquivo "
        "'licenca.smc' de cada cliente."
    )


if __name__ == "__main__":
    main()
