"""
DESATIVADO — este script foi substituído pelo fluxo de recuperação de
acesso embutido no produto (rota /recuperar-acesso, restrita ao próprio
computador do servidor). Ver core/auth.py:
    gerar_token_recuperacao_admin()
    redefinir_senha_admin_via_token()

Motivo da substituição: este script definia uma senha fixa e previsível
("Admin@2026") sem deixar qualquer registro de que foi usado. O novo
fluxo gera um token aleatório de uso único, expira em 15 minutos, fica
registrado em log quando é gerado e quando é usado, e só pode ser
acionado a partir do próprio servidor (nunca pela rede da escola).

Mantido apenas como referência; não deve mais ser executado em produção.
"""
raise SystemExit(
    "Este script foi desativado. Acesse http://127.0.0.1:<porta>/recuperar-acesso "
    "diretamente no computador do servidor para redefinir a senha do administrador."
)
