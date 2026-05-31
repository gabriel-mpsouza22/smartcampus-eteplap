import json
import os
from pathlib import Path

#=====================================#
# VARIAVEIS GLOBAIS
#=====================================#

INDICADOR_FINAL = "Digite FIM para terminar"
INDICADOR_FORMATO = "Formato = HH:MM"
EXEMPLO_FORMATO = "Exemplo: 09:10, 15:00"
TURNO_ADICIONADO = "Turno adicionado.\nDeseja criar outro turno: SIM/NAO> "
ESPACO_MARKDOWN = "=" * 15
ARQUIVO_EXISTENTE = "Arquivo de configuração já existe.\nDeseja criar outro arquivo? SIM/NAO> "
PATH_ARQUIVO_JSON = "turnos.json"

#=====================================#
# FUNÇÕES PRINCIPAIS
# FUNCAO_PRINCIPAL() AGE COMO INSTALADOR
# PRIMEIRO_USO() VERIFICA SE JÁ NÃO ESTÁ
# INSTALADO
# SHELL() É UMA FUNÇÃO PRA VERIFICAR SE
# O ARQUIVO .json ESTÁ SALVO MANUALMENTE
#=====================================#

def FUNCAO_PRINCIPAL() -> None:

    TURNOS = {}
    
    print(ESPACO_MARKDOWN)
    print(INDICADOR_FORMATO)
    print(EXEMPLO_FORMATO)
    print(INDICADOR_FINAL)
    print(ESPACO_MARKDOWN)

    INPUT_NOVO_TURNO = bool(True)
    while INPUT_NOVO_TURNO == bool(True):

        TURNO_PRINCIPAL = input("Insira o nome do turno> ").upper()
        TURNOS[TURNO_PRINCIPAL] = []

        INPUT_TURNOS = bool(True)

        while INPUT_TURNOS is bool(True):
            HORARIOS = input(f"Insira os horários do turno {TURNO_PRINCIPAL}> ").upper()

            if HORARIOS == "FIM":
                INPUT_TURNOS = False
                break

            TURNOS[TURNO_PRINCIPAL].append(HORARIOS)

        ADICIONAR_NOVO_TURNO = input(TURNO_ADICIONADO).upper()
        if ADICIONAR_NOVO_TURNO != "SIM":
            INPUT_NOVO_TURNO = bool(False)

        with open("turnos.json", "w", encoding="utf-8") as ARQUIVO: # EXPORTA PRA turnos.json
            json.dump(TURNOS, ARQUIVO, indent=4, ensure_ascii=False)

    for NOME_TURNOS, HORARIOS in TURNOS.items():
        print(ESPACO_MARKDOWN, NOME_TURNOS, ESPACO_MARKDOWN)

        for HORARIO in HORARIOS:
               print(HORARIO)

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
                print("Ok")
                FUNCAO_PRINCIPAL()

    else:
            NAO_RESPONDIDO = bool(False)
            FUNCAO_PRINCIPAL() # SE O ARQUIVO NÃO EXISTIR,         
                               # PROCEDE NORMALMENTE
PRIMEIRO_USO()
SHELL()
