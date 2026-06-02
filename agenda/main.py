import json
import os
import hashlib
import getpass
from pathlib import Path

#=====================================#
# VARIAVEIS GLOBAIS
#=====================================#
ESPACO_MARKDOWN       = "=" * 36
INDICADOR_FORMATO     = "  CADASTRO DE TURNOS E HORÁRIOS"
EXEMPLO_FORMATO       = "  Formato obrigatório: HH:MM  (hora : minuto)"
EXEMPLO_HORARIOS      = "  Exemplos válidos:  09:10  |  15:00  |  23:45"
INDICADOR_FINAL       = "  Quando terminar de adicionar horários, digite FIM"
PROMPT_NOME_TURNO     = "  Nome do turno (ex: MANHÃ, TARDE, NOITE)> "
TURNO_ADICIONADO      = "\n  Turno salvo! Deseja cadastrar mais um turno? SIM/NAO> "
RESUMO_TURNOS         = "\n  RESUMO DOS TURNOS CADASTRADOS:"
ARQUIVO_EXISTENTE     = (
    "Já existe uma configuração salva.\n"
    "Deseja apagá-la e começar do zero? SIM/NAO> "
)
PATH_ARQUIVO_JSON     = "turnos.json"
#=====================================#
# VARIAVEIS DE SENHA
#=====================================#
SENHA_CABECALHO       = "  CONFIGURAÇÃO DE SENHA"
SENHA_INSTRUCAO       = "  Crie uma senha para proteger o acesso a esta configuração."
SENHA_DICA            = "  Dica: misture letras maiúsculas, minúsculas, números e símbolos."
SENHA_AVISO_TELA      = "  O que você digitar não aparecerá na tela — isso é normal e esperado."
PROMPT_SENHA          = "  Nova senha> "
PROMPT_CONFIRMAR_SENHA = "  Confirme a senha> "
SENHA_NAO_CONFERE     = "\n  As senhas não são iguais. Tente novamente.\n"
SENHA_SALVA_MSG       = "  Senha configurada e salva com sucesso!"
ITERACOES_HASH        = 100_000                # DIFICULTA ATAQUES DE FORÇA BRUTA
#=====================================#
# FUNÇÕES PRINCIPAIS
# FUNCAO_PRINCIPAL() AGE COMO INSTALADOR
# PRIMEIRO_USO() VERIFICA SE JÁ NÃO ESTÁ
# INSTALADO
# SHELL() É UMA FUNÇÃO PRA VERIFICAR SE
# O ARQUIVO .json ESTÁ SALVO MANUALMENTE
# SOLICITAR_SENHA() PEDE, CRIPTOGRAFA E
# SALVA A SENHA NO ARQUIVO JSON
#=====================================#
def FUNCAO_PRINCIPAL() -> None:
    TURNOS = {}
    
    print(ESPACO_MARKDOWN)
    print(INDICADOR_FORMATO)
    print(ESPACO_MARKDOWN)
    print(EXEMPLO_FORMATO)
    print(EXEMPLO_HORARIOS)
    print(INDICADOR_FINAL)
    print(ESPACO_MARKDOWN)
    INPUT_NOVO_TURNO = bool(True)
    while INPUT_NOVO_TURNO == bool(True):
        TURNO_PRINCIPAL = input(PROMPT_NOME_TURNO).upper()
        TURNOS[TURNO_PRINCIPAL] = []
        INPUT_TURNOS = bool(True)
        while INPUT_TURNOS is bool(True):
            HORARIOS = input(f"  Horário para {TURNO_PRINCIPAL} (ou FIM para encerrar)> ").upper()
            if HORARIOS == "FIM":
                INPUT_TURNOS = False
                break
            TURNOS[TURNO_PRINCIPAL].append(HORARIOS)
        ADICIONAR_NOVO_TURNO = input(TURNO_ADICIONADO).upper()
        if ADICIONAR_NOVO_TURNO != "SIM":
            INPUT_NOVO_TURNO = bool(False)
        with open("turnos.json", "w", encoding="utf-8") as ARQUIVO: # EXPORTA PRA turnos.json
            json.dump(TURNOS, ARQUIVO, indent=4, ensure_ascii=False)
    print(RESUMO_TURNOS)
    for NOME_TURNOS, HORARIOS in TURNOS.items():
        print(ESPACO_MARKDOWN, NOME_TURNOS, ESPACO_MARKDOWN)
        for HORARIO in HORARIOS:
               print(HORARIO)

def SOLICITAR_SENHA() -> None:
    #=====================================#
    # getpass() OCULTA O QUE É DIGITADO
    # NO TERMINAL — NÃO USAR .upper()
    # EM SENHAS (CASE SENSITIVE)
    # ALGORITMO: PBKDF2 + SHA-256
    # SALT ALEATÓRIO GERADO A CADA CHAMADA
    #=====================================#
    print(ESPACO_MARKDOWN)
    print(SENHA_CABECALHO)
    print(ESPACO_MARKDOWN)
    print(SENHA_INSTRUCAO)
    print(SENHA_DICA)
    print(SENHA_AVISO_TELA)
    print(ESPACO_MARKDOWN)
    SENHAS_CONFEREM = bool(False)
    while SENHAS_CONFEREM == bool(False):
        SENHA_DIGITADA = getpass.getpass(PROMPT_SENHA)
        SENHA_CONFIRMADA = getpass.getpass(PROMPT_CONFIRMAR_SENHA)
        if SENHA_DIGITADA == SENHA_CONFIRMADA:
            SENHAS_CONFEREM = bool(True)
        else:
            print(SENHA_NAO_CONFERE)

    SALT = os.urandom(32)                      # SALT ALEATÓRIO DE 32 BYTES
    SENHA_HASH = hashlib.pbkdf2_hmac(          # PBKDF2 COM SHA-256
        "sha256",
        SENHA_DIGITADA.encode("utf-8"),        # SENHA CONVERTIDA PRA BYTES
        SALT,
        ITERACOES_HASH                         # 100K ITERAÇÕES
    )

    if Path(PATH_ARQUIVO_JSON).is_file() is True:  # LÊ O JSON SE JÁ EXISTIR
        with open(PATH_ARQUIVO_JSON, "r", encoding="utf-8") as ARQUIVO:
            DADOS_JSON = json.load(ARQUIVO)
    else:
        DADOS_JSON = {}                            # CRIA DICT VAZIO SE NÃO EXISTIR

    DADOS_JSON["SALT"] = SALT.hex()                # .hex() CONVERTE BYTES → STRING
    DADOS_JSON["SENHA"] = SENHA_HASH.hex()         # PARA PODER SALVAR NO JSON

    with open(PATH_ARQUIVO_JSON, "w", encoding="utf-8") as ARQUIVO:
        json.dump(DADOS_JSON, ARQUIVO, indent=4, ensure_ascii=False)

    print(SENHA_SALVA_MSG)

def SHELL() -> None:
    PROMPT_STR = "Shell> "
    PROMPT_PROCEED = bool(True)
    while PROMPT_PROCEED == bool(True):
        PROMPT_INPUT = input(PROMPT_STR) # COMO É LINHA DE COMANDO,
        if PROMPT_INPUT == str("EXIT"):  # NÃO POSSO COLOCAR .upper()
            PROMPT_PROCEED = bool(True)
            break
        else:
            os.system(PROMPT_INPUT)

def PRIMEIRO_USO() -> None:
    NAO_RESPONDIDO = bool(True) # SÓ SERVE PARA SE A RESPOSTA
                                # NÃO FOR A ESPERADA, REPETE ATÉ
                                # QUE SEJA
    if Path(PATH_ARQUIVO_JSON).is_file() is True:
        while NAO_RESPONDIDO is bool(True):
            NEW_FILE = input(ARQUIVO_EXISTENTE).upper()
            if NEW_FILE == "SIM":
                NAO_RESPONDIDO = bool(False)
                print("  Ok, iniciando nova configuração...\n")
                FUNCAO_PRINCIPAL()
                SOLICITAR_SENHA()  # ADICIONA SENHA AO JSON DOS TURNOS
    else:
            NAO_RESPONDIDO = bool(False)
            FUNCAO_PRINCIPAL()     # SE O ARQUIVO NÃO EXISTIR,         
                                   # PROCEDE NORMALMENTE
            SOLICITAR_SENHA()      # ADICIONA SENHA AO JSON DOS TURNOS

PRIMEIRO_USO()
SHELL()
