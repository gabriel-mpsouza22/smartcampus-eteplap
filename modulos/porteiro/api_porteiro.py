"""
Painel do Porteiro: reúne Pontualidade, Saídas de Alunos e Visitantes
numa só tela, em abas.

Fica num blueprint PRÓPRIO — de propósito, não dentro do blueprint de
Secretaria/Portaria (modulos/secretaria_portaria/api_sp.py) — porque
"Painel da Portaria" (agenda + chat) é um módulo vendável separado
("secretaria_portaria"). Se esta rota vivesse lá dentro, uma escola
que contratou Pontualidade + Saídas + Visitantes mas NÃO contratou o
módulo de agenda/chat receberia 404 ao tentar abrir o painel unificado
— mesmo o item aparecendo certinho no menu (a lógica de mesclagem em
core/auth.py checa só os 3 módulos certos, não este). Foi exatamente
esse descolamento que causou o 404 relatado.
"""

from datetime import date
from flask import Blueprint, render_template, abort

from core.auth import perfil_obrigatorio, usuario_logado, modulos_do_usuario

blueprint = Blueprint("porteiro", __name__, template_folder="../../templates")


@blueprint.route("/portaria/painel-unificado")
@perfil_obrigatorio("portaria", "admin")
def pagina_portaria_unificada():
    """
    Cada aba só aparece se o usuário logado realmente tem acesso a
    aquele módulo (cruzando cargo específico + módulos contratados —
    mesma checagem de sempre, feita por auth.modulos_do_usuario).
    Isso é decidido no servidor, não confiando em nada vindo do
    cliente: a aba nem chega a ser desenhada se o acesso não existir,
    então não tem como o usuário "ver" uma aba de um módulo que seu
    cargo ou o plano contratado não liberam.
    """
    usuario = usuario_logado()
    # mesclar_porteiro=False é essencial aqui: a versão padrão (mesclada)
    # de modulos_do_usuario() SUBSTITUI pontualidade/saidas_portaria/
    # visitantes_portaria pelo item combinado "porteiro_painel" assim
    # que 2 ou mais desses módulos estão disponíveis — que é exatamente
    # a condição normal para alguém acessar esta página. Usar a versão
    # mesclada aqui fazia os 3 IDs "sumirem" de ids_disponiveis sempre
    # que deveriam aparecer, disparando o abort(403) abaixo mesmo para
    # quem tinha acesso legítimo (ex.: o admin).
    ids_disponiveis = {m["id"] for m in modulos_do_usuario(usuario, mesclar_porteiro=False)}
    abas = {
        "pontualidade": "pontualidade" in ids_disponiveis,
        "saidas": "saidas_portaria" in ids_disponiveis,
        "visitantes": "visitantes_portaria" in ids_disponiveis,
    }
    if not any(abas.values()):
        # Nenhum dos 3 módulos disponível para este cargo/instalação —
        # não faz sentido nenhum mostrar uma tela de abas vazia.
        abort(403)

    turmas = []
    try:
        from core import alunos as cadastro_alunos
        turmas = cadastro_alunos.turmas_no_escopo()
    except Exception:
        pass

    motivos, destinos = [], []
    try:
        from modulos.visitantes.api_visitantes import MOTIVOS, DESTINOS
        motivos, destinos = MOTIVOS, DESTINOS
    except Exception:
        pass

    return render_template(
        "portaria/painel_unificado.html",
        hoje=date.today().isoformat(),
        abas=abas,
        turmas=turmas,
        motivos=motivos,
        destinos=destinos,
    )
