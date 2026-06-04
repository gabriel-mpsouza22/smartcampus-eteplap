import customtkinter as ctk
import json
import hashlib
import hmac

ARQUIVO_SENHA = "senha.json"
ITERACOES = 100_000


def verificar_senha():
    senha_digitada = entrada.get()

    try:
        # LER JSON
        with open(ARQUIVO_SENHA, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)

        # PEGAR HASH E SALT SALVOS
        salt_salvo = bytes.fromhex(dados["SALT"])
        hash_salvo = dados["SENHA"]

        # GERAR HASH DA SENHA DIGITADA
        hash_digitado = hashlib.pbkdf2_hmac(
            "sha256",
            senha_digitada.encode("utf-8"),
            salt_salvo,
            ITERACOES
        ).hex()

        # COMPARAR COM SEGURANÇA
        if hmac.compare_digest(hash_digitado, hash_salvo):
            resultado.configure(
                text="Senha correta",
                text_color="green"
            )

        else:
            resultado.configure(
                text="Senha incorreta",
                text_color="red"
            )

    except FileNotFoundError:
        resultado.configure(
            text="Arquivo de senha não encontrado",
            text_color="orange"
        )


# APARÊNCIA
ctk.set_appearance_mode("dark")

# JANELA
app = ctk.CTk()
app.title("SISTEMA DE SINAL ESCOLAR")
app.geometry("800x500")

titulo = ctk.CTkLabel(
    app,
    text="SISTEMA INTELIGENTE DE SIRENE",
    font=("Arial", 24)
)
titulo.pack(pady=20)

entrada = ctk.CTkEntry(
    app,
    placeholder_text="Digite a senha de administrador",
    show="*"  # OCULTA A SENHA
)
entrada.pack(pady=20)

entrar = ctk.CTkButton(
    app,
    text="Entrar",
    command=verificar_senha
)
entrar.pack(pady=20)

resultado = ctk.CTkLabel(app, text="")
resultado.pack(pady=20)

app.mainloop()
