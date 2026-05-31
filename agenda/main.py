import json
import os
from pathlib import Path

#=====================================#
# VARIAVEIS GLOBAIS
# (CONFIGURAÇÕES E TEXTOS FIXOS)
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
#
# FUNCAO_PRINCIPAL() -> CRIA E SALVA TURNOS
# PRIMEIRO_USO() -> VERIFICA SE O JSON JÁ EXISTE
# shell() -> EXECUTA COMANDOS DO SISTEMA
#
# FLUXO:
# PRIMEIRO_USO -> FUNCAO_PRINCIPAL -> SALVA JSON
# SHELL -> TERMINAL SIMPLES DO USUÁRIO
#=====================================#


def FUNCAO_PRINCIPAL() -> None:
    # DICIONÁRIO PRINCIPAL ONDE OS TURNOS SÃO ARMAZENADOS EM MEMÓRIA
    TURNOS = {}

    print(ESPACO_MARKDOWN)
    print(INDICADOR_FORMATO)
    print(EXEMPLO_FORMATO)
    print(INDICADOR_FINAL)
    print(ESPACO_MARKDOWN)

    #=====================================#
    # LOOP PRINCIPAL DE CRIAÇÃO DE TURNOS
    #=====================================#

    INPUT_NOVO_TURNO = True

    while INPUT_NOVO_TURNO is True:

        # NOME DO TURNO (CHAVE DO DICIONÁRIO)
        TURNO_PRINCIPAL = input("Insira o nome do turno> ").upper()
        TURNOS[TURNO_PRINCIPAL] = []

        #=====================================#
        # LOOP DE HORÁRIOS DO TURNO ATUAL
        #=====================================#

        INPUT_TURNOS = True

        while INPUT_TURNOS is True:
            HORARIOS = input(f"Insira os horários do turno {TURNO_PRINCIPAL}> ").upper()

            # CONDIÇÃO DE SAÍDA DO LOOP INTERNO
            if HORARIOS == "FIM":
                INPUT_TURNOS = False
                break

            # ADICIONA HORÁRIO NA LISTA DO TURNO
            TURNOS[TURNO_PRINCIPAL].append(HORARIOS)

        #=====================================#
        # DECISÃO DE CONTINUAR OU PARAR
        #=====================================#

        ADICIONAR_NOVO_TURNO = input(TURNO_ADICIONADO).upper()

        if ADICIONAR_NOVO_TURNO != "SIM":
            INPUT_NOVO_TURNO = False

        #=====================================#
        # SALVAMENTO DO JSON (A CADA ITERAÇÃO)
        #=====================================#

        with open(PATH_ARQUIVO_JSON, "w", encoding="utf-8") as ARQUIVO:
            json.dump(TURNOS, ARQUIVO, indent=4, ensure_ascii=False)

    #=====================================#
    # SAÍDA FINAL - EXIBE TURNOS CRIADOS
    #=====================================#

    for NOME_TURNOS, HORARIOS in TURNOS.items():
        print(ESPACO_MARKDOWN, NOME_TURNOS, ESPACO_MARKDOWN)

        for HORARIO in HORARIOS:
            print(HORARIO)


def SHELL() -> None:
    # SHELL SIMPLES PARA EXECUTAR COMANDOS DO SISTEMA
    PROMPT_STR = "Shell> "

    PROMPT_PROCEED = True

    while PROMPT_PROCEED is True:

        # INPUT DO USUÁRIO (COMANDO DO SISTEMA)
        PROMPT_INPUT = input(PROMPT_STR)

        # COMANDO DE SAÍDA DO SHELL
        if PROMPT_INPUT == "EXIT":
            PROMPT_PROCEED = False
            break

        # EXECUTA O COMANDO DIRETAMENTE NO SISTEMA
        os.system(PROMPT_INPUT)


def PRIMEIRO_USO() -> None:

    # FLAG PARA CONTROLAR REPETIÇÃO CASO USUÁRIO NÃO RESPONDA CORRETAMENTE
    NAO_RESPONDIDO = True

    #=====================================#
    # VERIFICA SE O ARQUIVO JÁ EXISTE
    #=====================================#

    if Path(PATH_ARQUIVO_JSON).is_file() is True:

        while NAO_RESPONDIDO is True:

            NEW_FILE = input(ARQUIVO_EXISTENTE).upper()

            if NEW_FILE == "SIM":
                NAO_RESPONDIDO = False
                print("Ok")
                FUNCAO_PRINCIPAL()

    else:
        # SE NÃO EXISTIR ARQUIVO, EXECUTA NORMALMENTE
        NAO_RESPONDIDO = False
        FUNCAO_PRINCIPAL()


#=====================================#
# INICIALIZAÇÃO DO PROGRAMA
#=====================================#

PRIMEIRO_USO()
SHELL()
