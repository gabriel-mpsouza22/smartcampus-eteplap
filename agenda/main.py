import json
import os

#==================
# VARIAVEIS GLOBAIS
#==================

INDICADOR_FINAL = "Digite FIM para terminar"
INDICADOR_FORMATO = "Formato = HH:MM"
EXEMPLO_FORMATO = "Exemplo: 09:10, 15:00"
TURNO_ADICIONADO = "Turno adicionado.\nDeseja criar outro turno: SIM/NAO> "
ESPACO_MARKDOWN = "=" * 15

def FUNCAO_PRINCIPAL() -> None:

    TURNOS = {}
    print(INDICADOR_FINAL)
    print(INDICADOR_FORMATO)
    print(EXEMPLO_FORMATO)

    INPUT_NOVO_TURNO = bool(True)
    while INPUT_NOVO_TURNO == bool(True):

        TURNO_PRINCIPAL = input("Insira o nome do turno> ")
        TURNOS[TURNO_PRINCIPAL] = []

        INPUT_TURNOS = bool(True)

        while INPUT_TURNOS is bool(True):
            HORARIOS = input(f"Insira os horários do turno {TURNO_PRINCIPAL}> ")

            if HORARIOS == "FIM":
                INPUT_TURNOS = False
                break

            TURNOS[TURNO_PRINCIPAL].append(HORARIOS)

        ADICIONAR_NOVO_TURNO = input(TURNO_ADICIONADO)
        if ADICIONAR_NOVO_TURNO != "SIM":
            INPUT_NOVO_TURNO = bool(False)

        with open("turnos.json", "w", encoding="utf-8") as ARQUIVO:
            json.dump(TURNOS, ARQUIVO, indent=4, ensure_ascii=False)

    for NOME_TURNOS, HORARIOS in TURNOS.items():
        print(ESPACO_MARKDOWN, NOME_TURNOS, ESPACO_MARKDOWN)

        for HORARIO in HORARIOS:
               print(HORARIO)

# FUNÇÃO DE SHELL PARA VERIFICAR O ARQUIVO turnos.json
# CHAME SE NECESSÁRIA

def shell():
    PROMPT_STR = "Shell> "
    PROMPT_PROCEED = bool(True)

    while PROMPT_PROCEED == bool(True):
        PROMPT_INPUT = input(PROMPT_STR)

        if PROMPT_INPUT == str("EXIT"):
            PROMPT_PROCEED = bool(True)
            break
        else:
            os.system(PROMPT_INPUT)

FUNCAO_PRINCIPAL()
shell()
