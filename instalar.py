#!/usr/bin/env python3
# instalar.py — Instalador do Smart Campus
#
# Copia todos os arquivos do projeto para C:\SmartCampus, coleta as
# informações específicas desta escola (identidade, servidor, recursos de
# agendamento, dispositivos IoT) e cadastra APENAS o usuário administrador.
# Todos os demais usuários (professores, portaria, biblioteca, secretaria,
# coordenação) são cadastrados depois, pela própria interface web, em
# Administração > Usuários — o administrador é o único login definido aqui.
#
# Como usar:
#   1. Coloque este arquivo na MESMA pasta que a pasta "SmartCampus" extraída
#   2. Execute: python instalar.py

import os
import sys
import json
import shutil
import string
import random
import secrets
import hashlib
import platform
import subprocess
from pathlib import Path
from datetime import datetime

VERSAO = "2.0.0"
DESTINO_PADRAO = Path(r"C:\SmartCampus")
ENCODING = "utf-8"

DEPENDENCIAS = ["flask", "bcrypt", "requests", "pywhatkit", "pywin32"]

PASTAS_IGNORADAS = {"__pycache__", ".git", "backup", "logs"}
ARQUIVOS_IGNORADOS = {".secret_key"}

VERDE, AMARELO, VERMELHO, AZUL, RESET, NEGRITO = (
    "\033[92m", "\033[93m", "\033[91m", "\033[94m", "\033[0m", "\033[1m"
)

def ok(t):      print(f"  {VERDE}✓{RESET} {t}")
def info(t):    print(f"  {AMARELO}→{RESET} {t}")
def erro(t):    print(f"  {VERMELHO}✗ ERRO: {t}{RESET}")
def secao(t):   print(f"\n{AZUL}{NEGRITO}{'─'*58}\n  {t}\n{'─'*58}{RESET}")
def cabecalho():
    print(f"\n{AZUL}{NEGRITO}")
    print("╔════════════════════════════════════════════════════════╗")
    print("║              Smart Campus — Instalador                 ║")
    print(f"║                      v{VERSAO}                            ║")
    print("╚════════════════════════════════════════════════════════╝")
    print(RESET)

def perguntar(texto, padrao=""):
    if padrao:
        r = input(f"  {texto} [{padrao}]: ").strip()
        return r if r else padrao
    return input(f"  {texto}: ").strip()

def perguntar_inteiro(texto, padrao):
    while True:
        r = perguntar(texto, str(padrao))
        try:
            return int(r)
        except ValueError:
            print(f"  {VERMELHO}Digite um número válido.{RESET}")

def confirmar(texto, padrao_sim=True):
    sufixo = "[S/n]" if padrao_sim else "[s/N]"
    r = input(f"  {texto} {sufixo}: ").strip().lower()
    if not r:
        return padrao_sim
    return r in ("s", "sim", "y", "yes")

# ─── Geração de senha e tokens ────────────────────────────────────────────────

def gerar_senha(nome=""):
    sufixo = "".join(random.choices(string.digits, k=4))
    especial = random.choice("@#$!")
    if nome:
        base = "".join(ch for ch in nome if ch.isalnum())[:6].capitalize() or "Admin"
        return f"{base}{especial}{sufixo}"
    return "".join(random.choices(string.ascii_letters + string.digits + "@#$!", k=10))

def gerar_token():
    return secrets.token_hex(12)

def hash_senha(senha):
    try:
        import bcrypt
        return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    except ImportError:
        salt = os.urandom(16).hex()
        h = hashlib.sha256(f"{salt}{senha}".encode()).hexdigest()
        return f"sha256:{salt}:{h}"

# ─── Verificações de ambiente ─────────────────────────────────────────────────

def verificar_python():
    v = sys.version_info
    if v < (3, 10):
        erro(f"Python 3.10+ é necessário (atual: {v.major}.{v.minor}).")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")

def verificar_pip():
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, check=True)
        ok("pip disponível")
    except subprocess.CalledProcessError:
        erro("pip não encontrado.")
        sys.exit(1)

# ─── Cópia recursiva dos arquivos do projeto ─────────────────────────────────

def copiar_projeto(origem: Path, destino: Path):
    secao("Copiando arquivos do projeto")
    destino.mkdir(parents=True, exist_ok=True)

    copiados = 0
    for raiz, pastas, arquivos in os.walk(origem):
        pastas[:] = [p for p in pastas if p not in PASTAS_IGNORADAS]
        raiz_rel = Path(raiz).relative_to(origem)

        for nome_arquivo in arquivos:
            if nome_arquivo in ARQUIVOS_IGNORADOS or nome_arquivo.endswith(".pyc"):
                continue
            src = Path(raiz) / nome_arquivo
            dst = destino / raiz_rel / nome_arquivo
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copiados += 1

    # Garante que as pastas de runtime existem, mesmo vazias
    for pasta in ("backup", "logs", "sceds/data"):
        (destino / pasta).mkdir(parents=True, exist_ok=True)

    ok(f"{copiados} arquivo(s) copiado(s) para {destino}")

# ─── Dependências ──────────────────────────────────────────────────────────────

def instalar_dependencias():
    secao("Instalando dependências Python")
    for dep in DEPENDENCIAS:
        r = subprocess.run([sys.executable, "-m", "pip", "install", dep, "--quiet"],
                           capture_output=True)
        if r.returncode == 0:
            ok(dep)
        else:
            info(f"{dep} — falhou, instale manualmente depois: pip install {dep}")

# ─── Identidade da escola ──────────────────────────────────────────────────────

def coletar_identidade_escola() -> dict:
    secao("Identidade da escola")
    print("  Essas informações aparecem na tela de login e no menu lateral.\n")

    nome_escola = perguntar("Nome completo da escola",
                            "Escola Técnica Estadual")
    sigla_escola = perguntar("Sigla/nome curto (aparece no título das páginas)",
                             "".join(p[0] for p in nome_escola.split() if p[0].isupper())[:8] or "ESCOLA")
    bairro_cidade = perguntar("Bairro/cidade (aparece no menu lateral)", "")

    return {
        "nome_escola": nome_escola,
        "sigla_escola": sigla_escola,
        "bairro_cidade": bairro_cidade,
    }

# ─── Configuração do servidor ──────────────────────────────────────────────────

def coletar_config_servidor(destino: Path) -> dict:
    secao("Configuração do servidor")
    porta = perguntar_inteiro("Porta do servidor web (80 = padrão, não precisa digitar :porta no navegador)", 80)
    host = perguntar("Endereço de escuta (0.0.0.0 = aceita acesso de toda a rede)", "0.0.0.0")

    if porta < 1024 and platform.system() == "Windows":
        info("Portas abaixo de 1024 exigem executar o servidor como Administrador.")

    return {
        "caminho_base": str(destino),
        "porta_api": porta,
        "host_api": host,
        "encoding": "utf-8",
        "versao": VERSAO,
    }

# ─── Cadastro do administrador ────────────────────────────────────────────────

def cadastrar_admin(db) -> dict:
    secao("Cadastro do administrador")
    print("  Este é o ÚNICO login criado pelo instalador.")
    print("  Todos os outros usuários (professores, portaria, biblioteca,")
    print("  secretaria, coordenação) devem ser cadastrados depois, já pela")
    print("  interface web, em Administração > Usuários.\n")

    nome_admin = perguntar("Nome do administrador", "Administrador")

    while True:
        senha = perguntar("Senha do administrador (Enter para gerar uma automaticamente)")
        if not senha:
            senha = gerar_senha(nome_admin)
            print(f"  {AMARELO}Senha gerada: {senha}{RESET}")
            break
        if len(senha) < 6:
            print(f"  {VERMELHO}Senha muito curta (mínimo 6 caracteres).{RESET}")
            continue
        break

    db.inserir("usuarios", {
        "nome": nome_admin,
        "perfil": "admin",
        "senha_hash": hash_senha(senha),
        "ativo": True,
        "criado_em": datetime.now().isoformat(),
    })
    ok(f"Administrador '{nome_admin}' cadastrado")

    return {"nome": nome_admin, "senha": senha}

# ─── Recursos do Agendamento ───────────────────────────────────────────────────

def coletar_recursos_agendamento(destino: Path):
    secao("Recursos do Agendamento")
    print("  Cadastre aqui os laboratórios, datashows, salas e espaços que")
    print("  poderão ser reservados pelos professores. Deixe o nome em branco")
    print("  quando terminar.\n")

    icones_por_tipo = {
        "laboratorio": "🖥️", "sala": "📽️", "espaco": "⚽", "equipamento": "📊",
    }

    recursos = []
    while True:
        nome = perguntar(f"Nome do recurso #{len(recursos)+1} (Enter para terminar)")
        if not nome:
            break

        print("    Tipos: laboratorio, sala, espaco, equipamento")
        tipo = perguntar("    Tipo", "equipamento").strip().lower()
        if tipo not in icones_por_tipo:
            tipo = "equipamento"

        quantidade = perguntar_inteiro("    Quantas unidades? (ex: 5 datashows)", 1)
        quantidade = max(1, min(quantidade, 100))
        icone = icones_por_tipo[tipo]

        if quantidade == 1:
            recursos.append({"id": _slug(nome), "nome": nome, "tipo": tipo, "icone": icone})
            ok(f"{nome} ({tipo})")
        else:
            for i in range(1, quantidade + 1):
                nome_num = f"{nome} {i:02d}"
                recursos.append({"id": _slug(nome_num), "nome": nome_num, "tipo": tipo, "icone": icone})
            ok(f"{quantidade}x {nome} ({tipo}), numerados de 01 a {quantidade:02d}")
        print()

    if not recursos:
        info("Nenhum recurso cadastrado — usando um conjunto padrão de exemplo.")
        recursos = [
            {"id": "lab1", "nome": "Laboratório de Informática 1", "tipo": "laboratorio", "icone": "🖥️"},
            {"id": "sala_video", "nome": "Sala de Vídeo", "tipo": "sala", "icone": "📽️"},
            {"id": "quadra", "nome": "Quadra Poliesportiva", "tipo": "espaco", "icone": "⚽"},
        ]

    caminho = destino / "modulos" / "agendamento" / "recursos.json"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"recursos": recursos}, f, ensure_ascii=False, indent=2)

    ok(f"{len(recursos)} recurso(s) salvos em recursos.json")

def _slug(texto: str) -> str:
    import unicodedata
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = texto.lower().strip()
    texto = "".join(c if c.isalnum() else "_" for c in texto)
    while "__" in texto:
        texto = texto.replace("__", "_")
    return texto.strip("_")

# ─── Dispositivos IoT ──────────────────────────────────────────────────────────

def coletar_dispositivos_iot(destino: Path):
    secao("Dispositivos IoT (Arduino/ESP32)")

    if not confirmar("Configurar os dispositivos IoT agora?", padrao_sim=True):
        info("Pulado — o arquivo dispositivos.json padrão (3 sensores de água, "
             "2 portões, 10 salas de A/C) será mantido. Edite manualmente depois "
             "se precisar.")
        return

    # ── Água ──
    print(f"\n  {NEGRITO}Sensores de nível de água{RESET} (ESP32 + JSN-SR04T)")
    qtd_agua = perguntar_inteiro("  Quantos sensores de água existem?", 3)
    sensores_agua = []
    for i in range(1, qtd_agua + 1):
        nome = perguntar(f"    Nome/local do sensor #{i}", f"Reservatório {i}")
        limite = perguntar_inteiro("    Nível mínimo de alerta (%)", 20)
        sensores_agua.append({
            "id": _slug(nome), "nome": nome, "hardware": "ESP32 + JSN-SR04T",
            "limite_minimo": limite, "token": gerar_token(),
        })
        ok(f"{nome}: token gerado")

    # ── Portões ──
    print(f"\n  {NEGRITO}Portões automáticos{RESET} (ESP32 + atuador)")
    qtd_portoes = perguntar_inteiro("  Quantos portões existem?", 2)
    lista_portoes = []
    for i in range(1, qtd_portoes + 1):
        nome = perguntar(f"    Nome do portão #{i}", f"Portão {i}")
        lista_portoes.append({"id": _slug(nome), "nome": nome})
    horario_abertura = perguntar("  Horário de abertura automática", "07:20")
    horario_fechamento = perguntar("  Horário de fechamento automático", "21:00")
    token_portoes = gerar_token()
    ok(f"{qtd_portoes} portão(ões) configurado(s), token gerado")

    # ── Ar-condicionado ──
    print(f"\n  {NEGRITO}Ar-condicionado{RESET} (ESP32 + infravermelho)")
    qtd_salas_ac = perguntar_inteiro("  Quantas salas têm ar-condicionado controlado?", 10)
    horario_ligar = perguntar("  Horário de ligar automático (dias úteis)", "07:00")
    token_ac = gerar_token()
    ok(f"{qtd_salas_ac} sala(s) configurada(s), token gerado")

    dispositivos = {
        "observacao": "Cada dispositivo físico tem seu próprio token. Configure o firmware do ESP32 para enviar esse token no header X-Device-Token.",
        "agua": {"sensores": sensores_agua},
        "portoes": {
            "token": token_portoes,
            "hardware": f"ESP32 + atuador ({qtd_portoes} portão(ões))",
            "horario_abertura": horario_abertura,
            "horario_fechamento": horario_fechamento,
            "lista": lista_portoes,
        },
        "ar_condicionado": {
            "token": token_ac,
            "hardware": f"ESP32 + módulo IR ({qtd_salas_ac} sala(s))",
            "nome": "Ar-condicionados das Salas",
            "quantidade": qtd_salas_ac,
            "horario_ligar": horario_ligar,
            "dias_semana_automacao": [0, 1, 2, 3, 4],
        },
    }

    caminho = destino / "modulos" / "iot" / "dispositivos.json"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dispositivos, f, ensure_ascii=False, indent=2)

    ok("dispositivos.json salvo com todos os tokens gerados")
    print(f"\n  {AMARELO}Anote os tokens — eles vão para o firmware de cada ESP32.")
    print(f"  Estão salvos em: {caminho}{RESET}")

# ─── Banco de dados ────────────────────────────────────────────────────────────

TABELAS = {
    "usuarios": [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "perfil", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "senha_hash", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "ativo", "tipo": "BOOLEANO", "modificadores": []},
        {"nome": "criado_em", "tipo": "DATA_HORA", "modificadores": []},
    ],
    "reservas": [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "professor_id", "tipo": "INTEIRO", "modificadores": ["NAO_NULO"]},
        {"nome": "professor_nome", "tipo": "TEXTO", "modificadores": []},
        {"nome": "recurso_tipo", "tipo": "TEXTO", "modificadores": []},
        {"nome": "recurso_nome", "tipo": "TEXTO", "modificadores": []},
        {"nome": "recurso_id", "tipo": "TEXTO", "modificadores": []},
        {"nome": "data_reserva", "tipo": "DATA", "modificadores": ["NAO_NULO"]},
        {"nome": "hora_inicio", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "hora_fim", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "devolvido", "tipo": "BOOLEANO", "modificadores": []},
        {"nome": "data_devolucao", "tipo": "DATA_HORA", "modificadores": []},
    ],
    "livros": [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "autor", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "genero", "tipo": "TEXTO", "modificadores": []},
        {"nome": "prateleira", "tipo": "TEXTO", "modificadores": []},
    ],
    "emprestimos": [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "livro_id", "tipo": "INTEIRO", "modificadores": ["NAO_NULO"]},
        {"nome": "aluno_nome", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "aluno_turma", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "aluno_curso", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "data_emprestimo", "tipo": "DATA", "modificadores": ["NAO_NULO"]},
        {"nome": "data_prevista_devolucao", "tipo": "DATA", "modificadores": ["NAO_NULO"]},
        {"nome": "devolvido", "tipo": "BOOLEANO", "modificadores": []},
        {"nome": "data_devolucao", "tipo": "DATA", "modificadores": []},
    ],
    "compromissos": [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "data", "tipo": "DATA", "modificadores": ["NAO_NULO"]},
        {"nome": "hora", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "responsavel", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "motivo", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "criado_em", "tipo": "DATA_HORA", "modificadores": []},
    ],
    "mensagens_chat": [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "remetente", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "texto", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "data_hora", "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
    ],
    "leituras_iot": [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "sensor_id", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "tipo", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "valor", "tipo": "DECIMAL", "modificadores": []},
        {"nome": "data_hora", "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
    ],
    "alunos_ocorrencias": [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "serie", "tipo": "TEXTO", "modificadores": []},
        {"nome": "turma", "tipo": "TEXTO", "modificadores": []},
        {"nome": "curso", "tipo": "TEXTO", "modificadores": []},
    ],
    "ocorrencias": [
        {"nome": "numero", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "aluno_id", "tipo": "INTEIRO", "modificadores": ["NAO_NULO"]},
        {"nome": "tipo", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "envolvido_2", "tipo": "TEXTO", "modificadores": []},
        {"nome": "descricao", "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "data_hora", "tipo": "DATA_HORA", "modificadores": ["NAO_NULO"]},
    ],
}

def inicializar_banco(destino: Path):
    secao("Inicializando banco de dados")
    sys.path.insert(0, str(destino))
    from sceds import SCEDS
    db = SCEDS(destino / "sceds" / "data")

    for nome_tabela, colunas in TABELAS.items():
        if not db.tabela_existe(nome_tabela):
            db.criar_tabela(nome_tabela, colunas)
            ok(f"Tabela '{nome_tabela}' criada")
        else:
            info(f"Tabela '{nome_tabela}' já existe — mantida")

    return db

# ─── Agendador de Tarefas do Windows ────────────────────────────────────────────

def configurar_task_scheduler(destino: Path):
    secao("Inicialização automática (Agendador de Tarefas do Windows)")

    if platform.system() != "Windows":
        info("Disponível apenas no Windows. Pulando.")
        return
    if not confirmar("Configurar para iniciar automaticamente com o Windows?"):
        return

    python_exe = sys.executable
    tarefas = [
        ("SmartCampus_Servidor", f'"{python_exe}" "{destino / "app.py"}"'),
        ("SmartCampus_Sinal", f'"{python_exe}" "{destino / "modulos" / "sinal" / "sinal.pyw"}"'),
    ]

    for nome_tarefa, comando in tarefas:
        xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><Hidden>false</Hidden></Settings>
  <Actions><Exec>
    <Command>{comando.split()[0].strip(chr(34))}</Command>
    <Arguments>{' '.join(comando.split()[1:])}</Arguments>
    <WorkingDirectory>{destino}</WorkingDirectory>
  </Exec></Actions>
</Task>"""
        xml_path = destino / "backup" / f"task_{nome_tarefa}.xml"
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(xml, encoding="utf-16")

        r = subprocess.run(["schtasks", "/Create", "/TN", nome_tarefa, "/XML", str(xml_path), "/F"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            ok(f"Tarefa '{nome_tarefa}' registrada")
        else:
            info(f"Não foi possível registrar '{nome_tarefa}' automaticamente. "
                 f"Execute manualmente: schtasks /Create /TN {nome_tarefa} /XML \"{xml_path}\" /F")

# ─── Relatório final ────────────────────────────────────────────────────────────

def imprimir_relatorio(admin: dict, destino: Path, config: dict):
    secao("Instalação concluída!")

    print(f"\n{NEGRITO}  Endereço do sistema:{RESET}")
    print(f"  {VERDE}http://[IP-deste-computador]:{config['porta_api']}{RESET}")
    print(f"  {AMARELO}(descubra o IP com 'ipconfig' no Prompt de Comando){RESET}")

    print(f"\n{NEGRITO}  Login do administrador:{RESET}")
    print(f"  Usuário: {admin['nome']}")
    print(f"  Senha:   {VERDE}{admin['senha']}{RESET}")
    print(f"\n  {VERMELHO}Anote esta senha agora — ela não pode ser recuperada depois.{RESET}")
    print(f"  Após entrar, use Administração > Usuários para cadastrar todos")
    print(f"  os demais professores/funcionários.")

    relatorio = destino / "logs" / "instalacao.txt"
    relatorio.parent.mkdir(parents=True, exist_ok=True)
    relatorio.write_text(
        f"Smart Campus — Relatório de Instalação\n"
        f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
        f"{'='*50}\n\n"
        f"Administrador: {admin['nome']}\n"
        f"Senha: {admin['senha']}\n\n"
        f"Apague este arquivo após anotar a senha em local seguro.\n",
        encoding="utf-8"
    )
    print(f"\n  {AMARELO}Relatório também salvo em: {relatorio}")
    print(f"  Apague esse arquivo depois de anotar a senha!{RESET}")

    print(f"\n{VERDE}{NEGRITO}  Para iniciar o servidor manualmente:{RESET}")
    print(f"  cd {destino}")
    print(f"  python app.py\n")

# ─── Fluxo principal ────────────────────────────────────────────────────────────

def main():
    cabecalho()

    origem = Path(__file__).resolve().parent / "SmartCampus"
    if not origem.exists():
        erro(f"Pasta 'SmartCampus' não encontrada ao lado deste instalador ({origem}).")
        input("\nPressione Enter para sair...")
        return

    e_windows = platform.system() == "Windows"
    if e_windows:
        destino_str = perguntar("Pasta de instalação", str(DESTINO_PADRAO))
    else:
        info(f"Sistema não-Windows detectado ({platform.system()}) — modo de teste.")
        destino_str = perguntar("Pasta de instalação", str(Path.home() / "SmartCampus"))
    destino = Path(destino_str)

    if destino.exists() and any(destino.iterdir()):
        if not confirmar(f"A pasta {destino} já existe e não está vazia. Continuar mesmo assim?",
                         padrao_sim=False):
            print("  Instalação cancelada.")
            return

    secao("Verificando requisitos")
    verificar_python()
    verificar_pip()

    copiar_projeto(origem, destino)

    identidade = coletar_identidade_escola()
    config_servidor = coletar_config_servidor(destino)
    config_final = {**config_servidor, **identidade}

    caminho_config = destino / "core" / "config.json"
    caminho_config.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho_config, "w", encoding="utf-8") as f:
        json.dump(config_final, f, ensure_ascii=False, indent=2)
    ok("config.json salvo")

    if confirmar("\n  Instalar dependências Python agora? (recomendado)"):
        instalar_dependencias()

    db = inicializar_banco(destino)
    admin = cadastrar_admin(db)

    coletar_recursos_agendamento(destino)
    coletar_dispositivos_iot(destino)

    if e_windows:
        configurar_task_scheduler(destino)

    imprimir_relatorio(admin, destino, config_final)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {AMARELO}Instalação interrompida pelo usuário.{RESET}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n  {VERMELHO}Erro inesperado: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
