
from flask import Flask
from pathlib import Path
import json
import sys


def carregar_config() -> dict:
    """Carrega o config.json global do projeto."""
    from core.config_path import resolver_config_path
    config_path = resolver_config_path(Path(__file__).resolve().parent.parent)
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


TODOS_MODULOS_VENDAVEIS = {
    "sinal", "agendamento", "biblioteca", "secretaria_portaria", "iot",
    "ocorrencias", "evasao", "chaves", "chamados", "monitoramento", "alunos",
    "pontualidade", "saidas", "visitantes",
}


def _modulos_da_licenca(config: dict) -> set | None:
    """
    Tenta ler a lista de módulos contratados de dentro da licença
    assinada (licenca.smc), não do config.json.

    Por quê: config.json fica na pasta de dados da instalação e
    qualquer pessoa com acesso ao computador (inclusive o admin da
    escola) pode editá-lo num editor de texto comum — o que permitiria
    "destravar" módulos não pagos só editando um JSON. A licença é
    assinada com Ed25519 (core/licenca.py só consegue VERIFICAR,
    nunca forjar), então colocar a lista de módulos contratados dentro
    dela é a única forma de essa trava não depender de honestidade.

    Retorna None (não None-safe, é um sinal explícito de "não decidiu
    nada aqui, siga para o próximo nível") quando:
      - não há licença instalada (ambiente de desenvolvimento, ou
        instalação ainda não licenciada — nesses casos o próprio
        launcher.py já bloqueia a tela antes de chegar aqui, então
        isto só é alcançado mesmo em dev, rodando `python app.py`);
      - a licença existe mas é de um formato antigo, emitido antes de
        este campo existir (sem "modulos_ativos" no payload) — nesse
        caso o cliente precisa apenas de uma licença nova para ganhar
        o controle granular; até lá, cai no comportamento antigo
        (config.json), sem quebrar quem já tinha licença válida.
    """
    from pathlib import Path
    from core.licenca import verificar_ou_none

    caminho_base = config.get("caminho_base")
    if not caminho_base:
        return None
    pasta = Path(caminho_base)
    payload, _erro = verificar_ou_none(pasta / "licenca.smc", pasta_cache=pasta)
    if payload is None:
        return None
    modulos = payload.get("modulos_ativos")
    if modulos is None:
        return None
    return set(modulos) & TODOS_MODULOS_VENDAVEIS


def modulos_ativos_permitidos(config: dict) -> set:
    """
    Retorna o conjunto de IDs de módulos que devem ser carregados,
    conforme "modulos_ativos" em config.json — decidido no Wizard de
    instalação (ou editável depois, se preciso, sem exigir reemitir
    nenhuma licença). Se a chave não existir (instalação bem antiga,
    de antes deste conceito existir), assume que todos os módulos
    estão ativos.

    'admin' é sempre incluído — é a ferramenta de administração do
    próprio sistema, não um módulo vendável à parte.

    Nota: a licença (licenca.smc) também pode carregar uma lista de
    módulos assinada (ver `_modulos_da_licenca`, mais abaixo neste
    arquivo) — isso existe como opção mais rígida para quem quiser
    travar módulos de um jeito que nem o admin da escola consiga
    editar sozinho, mas NÃO é usado aqui por padrão: exigiria rodar
    `licenciamento/emitir_licenca.py` toda vez que o pacote contratado
    mudar, o que foi decidido não valer a pena — o Wizard já resolve
    isso com muito menos fricção, direto pela interface.
    """
    ativos = config.get("modulos_ativos")
    ativos = set(TODOS_MODULOS_VENDAVEIS) if ativos is None else set(ativos)
    ativos.add("admin")
    return ativos


def registrar_blueprints(app: Flask) -> None:
    """
    Importa e registra todos os blueprints dos módulos no app Flask.
    Cada módulo deve expor uma variável 'blueprint' no seu arquivo de API.
    Apenas os módulos presentes em "modulos_ativos" (config.json) são
    registrados — os demais ficam completamente indisponíveis, inclusive
    por URL direta, já que a rota nem chega a existir no Flask.
    Erros de importação são registrados no log mas não travam o servidor.
    """
    config = carregar_config()
    base = Path(config["caminho_base"])

    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    permitidos = modulos_ativos_permitidos(config)

    modulos = [
        ("sinal",               "Sinal",                  "modulos.sinal.api_sinal",               "/sinal"),
        ("agendamento",         "Agendamento",             "modulos.agendamento.api_agendamento",   "/agendamento"),
        ("biblioteca",          "Biblioteca",              "modulos.biblioteca.api_biblioteca",     "/biblioteca"),
        ("secretaria_portaria", "Secretaria-Portaria",     "modulos.secretaria_portaria.api_sp",    "/"),
        ("iot",                 "IoT",                     "modulos.iot.api_iot",                   "/iot"),
        ("ocorrencias",         "Ocorrencias",              "modulos.ocorrencias.api_ocorrencias",   "/ocorrencias"),
        ("evasao",              "Evasao",                   "modulos.evasao.api_evasao",              "/evasao"),
        ("chaves",              "Chaves",                   "modulos.chaves.api_chaves",              "/chaves"),
        ("chamados",            "Chamados",                 "modulos.chamados.api_chamados",          "/chamados"),
        ("monitoramento",       "Monitoramento",            "modulos.monitoramento.api_monitoramento","/monitoramento"),
        ("alunos",              "Alunos",                   "modulos.alunos.api_alunos",              "/alunos"),
        ("pontualidade",        "Pontualidade",              "modulos.pontualidade.api_pontualidade", "/pontualidade"),
        ("saidas",              "Saidas de Alunos",          "modulos.saidas.api_saidas",              "/saidas"),
        ("visitantes",          "Controle de Visitantes",    "modulos.visitantes.api_visitantes",      "/visitantes"),
        ("admin",               "Admin",                    "admin.api_admin",                        "/admin"),
    ]

    for modulo_id, nome, caminho, prefixo in modulos:
        if modulo_id not in permitidos:
            app.logger.info(f"[Router] Módulo '{nome}' não contratado neste pacote. Não registrado.")
            continue
        try:
            import importlib
            mod = importlib.import_module(caminho)
            bp = getattr(mod, "blueprint", None)
            if bp is None:
                app.logger.warning(f"[Router] Módulo '{nome}' não possui 'blueprint'. Ignorado.")
                continue
            app.register_blueprint(bp, url_prefix=prefixo)
            app.logger.info(f"[Router] ✓ Módulo '{nome}' registrado em '{prefixo}'")
        except ImportError as e:
            app.logger.warning(f"[Router] ⚠ Módulo '{nome}' não pôde ser importado: {e}")
        except Exception as e:
            app.logger.error(f"[Router] ✗ Erro ao registrar '{nome}': {e}")

    # Painel do Porteiro: não é um módulo vendável próprio, é uma tela
    # que junta 3 outros módulos (Pontualidade, Saídas, Visitantes) —
    # por isso não entra na lista acima nem depende de "secretaria_
    # portaria" estar contratado. Registra sempre que pelo menos um
    # dos 3 estiver ativo, pra rota nunca dar 404 pra quem já vê o
    # item no menu (ver core/auth.py -> _mesclar_painel_porteiro).
    if permitidos & {"pontualidade", "saidas", "visitantes"}:
        try:
            import importlib
            mod = importlib.import_module("modulos.porteiro.api_porteiro")
            app.register_blueprint(mod.blueprint)
            app.logger.info("[Router] ✓ Painel do Porteiro registrado em '/portaria/painel-unificado'")
        except Exception as e:
            app.logger.error(f"[Router] ✗ Erro ao registrar Painel do Porteiro: {e}")


def perfil_para_cor(perfil: str) -> str:
    """Retorna a cor associada ao perfil para uso no template."""
    cores = {
        "admin":        "#1A1A2E",
        "professor":    "#2E86AB",
        "portaria":     "#E76F51",
        "bibliotecaria":"#8338EC",
        "coordenadora": "#F4A261",
        "secretaria":   "#457B9D",
        "aluno_chamados": "#3A7CA5",
    }
    return cores.get(perfil, "#4A4A4A")


def perfil_para_label(perfil: str) -> str:
    """Retorna o label legível do perfil."""
    labels = {
        "admin":        "Administrador",
        "professor":    "Professor",
        "portaria":     "Portaria",
        "bibliotecaria":"Bibliotecária",
        "coordenadora": "Coordenadora",
        "secretaria":   "Secretaria",
        "aluno_chamados": "Suporte Técnico (Aluno)",
    }
    return labels.get(perfil, perfil.capitalize())
