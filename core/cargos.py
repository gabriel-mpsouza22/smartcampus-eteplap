"""
Cargos e Permissões
--------------------
Um "cargo" é uma variação nomeada e configurável de um dos perfis básicos
do sistema (secretaria, coordenadora, portaria, bibliotecária, professor,
admin, aluno_chamados). Pela tela de Administração > Cargos, o admin pode:

  - dar um nome próprio ao cargo (ex: "Coordenadora do Integral");
  - escolher, dentre os módulos que o perfil-base normalmente acessa,
    quais este cargo específico realmente vê no menu (um SUBCONJUNTO —
    nunca mais do que o perfil-base já permitiria);
  - restringir o cargo a um ou mais turnos (ex.: só "Integral"). Nos
    módulos que giram em torno de alunos (Alunos, Ocorrências,
    Pontualidade, Evasão, Saídas, Monitoramento), quem tem esse cargo
    simplesmente não vê alunos, turmas ou números de outros turnos.

Por que "herdar de um perfil-base" em vez de permissão 100% livre?
Cada rota do sistema já é protegida por @perfil_obrigatorio(...) com um
conjunto fixo de perfis (ex.: só 'secretaria', 'coordenadora' e 'admin'
podem editar o cadastro de alunos) — são dezenas de checagens espalhadas
pelos módulos. Um cargo herda essas checagens do seu perfil-base (o
usuário do cargo tem usuarios.perfil = cargo.perfil_base), então tudo
que já funciona continua funcionando sem tocar em cada módulo. Cargos
dão nome, curadoria de menu e escopo de turno "por cima" disso.

Os 7 cargos "de sistema" (um por perfil-base) são criados automaticamente
na primeira vez que a tabela é usada e não podem ser excluídos — só
editados (é possível, por exemplo, restringir o próprio cargo padrão
"Coordenadora" a um turno, se a escola só tiver uma coordenadora no
total). Cargos novos, criados pelo admin, podem ser livremente criados,
editados e excluídos (com a proteção de não remover um cargo que ainda
tenha usuários vinculados).
"""

import json
from pathlib import Path

BASE_CORE = Path(__file__).resolve().parent

TURNO_TODOS = "todos"


def _carregar_config() -> dict:
    from core.config_path import carregar_config
    return carregar_config(BASE_CORE.parent)


def _get_db():
    import sys
    sys.path.insert(0, str(BASE_CORE.parent))
    from sceds import SCEDS
    cfg = _carregar_config()
    db = SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")
    _garantir_tabela(db)
    return db


def _schema_cargos() -> list[dict]:
    return [
        {"nome": "id",           "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome",         "tipo": "TEXTO",    "modificadores": ["NAO_NULO"]},
        {"nome": "perfil_base",  "tipo": "TEXTO",    "modificadores": ["NAO_NULO"]},
        # JSON-encoded manualmente (o motor SCEDS não tem tipo lista) —
        # ver _serializar/_deserializar abaixo. Nunca gravar/ler estes
        # dois campos sem passar por eles.
        {"nome": "modulos",       "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "escopo_turno",  "tipo": "TEXTO", "modificadores": ["NAO_NULO"]},
        {"nome": "sistema",       "tipo": "BOOLEANO", "modificadores": []},
    ]


def _garantir_tabela(db) -> None:
    if not db.tabela_existe("cargos"):
        db.criar_tabela("cargos", _schema_cargos())
        for base in _perfis_base_disponiveis():
            _inserir_cargo_padrao(db, base)


def _perfis_base_disponiveis() -> list[str]:
    from core.auth import MODULOS_POR_PERFIL
    return list(MODULOS_POR_PERFIL.keys())


def _modulos_do_perfil_base(perfil_base: str) -> list[str]:
    return [item["id"] for item in modulos_disponiveis(perfil_base)]


def _inserir_cargo_padrao(db, perfil_base: str) -> dict:
    from core.router import perfil_para_label
    return db.inserir("cargos", {
        "nome":         perfil_para_label(perfil_base),
        "perfil_base":  perfil_base,
        "modulos":      _serializar(_modulos_do_perfil_base(perfil_base)),
        "escopo_turno": _serializar([TURNO_TODOS]),
        "sistema":      True,
    })


def _serializar(lista: list[str]) -> str:
    return json.dumps(lista, ensure_ascii=False)


def _deserializar(texto: str | None) -> list[str]:
    if not texto:
        return []
    try:
        valor = json.loads(texto)
        return valor if isinstance(valor, list) else []
    except (TypeError, ValueError):
        return []


def _formatar(registro: dict) -> dict:
    return {
        "id":           registro["id"],
        "nome":         registro["nome"],
        "perfil_base":  registro["perfil_base"],
        "modulos":      _deserializar(registro.get("modulos")),
        "escopo_turno": _deserializar(registro.get("escopo_turno")) or [TURNO_TODOS],
        "sistema":      bool(registro.get("sistema")),
    }


def turnos_existentes() -> list[str]:
    """Turnos distintos definidos em core/turmas.json, na ordem em que aparecem."""
    from core.alunos import carregar_turmas
    vistos = []
    for t in carregar_turmas():
        turno = t.get("turno")
        if turno and turno not in vistos:
            vistos.append(turno)
    return vistos


def listar_cargos(db=None) -> list[dict]:
    db = db or _get_db()
    _garantir_tabela(db)
    return [_formatar(c) for c in db.buscar("cargos", ordenar_por="perfil_base")]


def cargo_por_id(cargo_id: int, db=None) -> dict | None:
    db = db or _get_db()
    _garantir_tabela(db)
    registro = db.buscar_um("cargos", onde={"id": cargo_id})
    return _formatar(registro) if registro else None


def cargo_padrao_do_perfil(perfil_base: str, db=None) -> dict | None:
    """O cargo 'de sistema' correspondente a um perfil-base — usado como
    resolução automática para usuários antigos que ainda não têm cargo_id."""
    db = db or _get_db()
    _garantir_tabela(db)
    for c in db.buscar("cargos", onde={"perfil_base": perfil_base, "sistema": True}):
        return _formatar(c)
    return None


def modulos_disponiveis(perfil_base: str) -> list[dict]:
    """
    Módulos que o perfil-base normalmente acessa E que estão realmente
    contratados nesta instalação (config.json → modulos_ativos) — o teto
    do que um cargo baseado nele pode ter marcado.

    Isso é deliberado: quem decide os módulos contratados é a equipe que
    instala o sistema, pelo Wizard, de acordo com o que a escola está
    pagando — não o admin da escola depois. Um módulo fora do pacote
    contratado nunca deve aparecer nem como opção marcável aqui, senão o
    admin teria a falsa impressão de poder "ligar" algo que não foi
    vendido pra escola dele.

    Usada por _validar_modulos como allowlist de segurança — nunca
    misture com módulos não contratados. Para exibição na tela (com os
    não contratados aparecendo travados, ver `modulos_com_status_contrato`).
    """
    from core.auth import MODULOS_POR_PERFIL, MENU_ID_PARA_MODULO
    from core.router import modulos_ativos_permitidos
    contratados = modulos_ativos_permitidos(_carregar_config())
    return [
        {"id": item["id"], "nome": item["nome"]}
        for item in MODULOS_POR_PERFIL.get(perfil_base, [])
        if MENU_ID_PARA_MODULO.get(item["id"], item["id"]) in contratados
    ]


def modulos_com_status_contrato(perfil_base: str) -> list[dict]:
    """
    Igual a `modulos_disponiveis`, mas para EXIBIÇÃO na tela de Cargos:
    devolve TODOS os módulos que o perfil-base normalmente acessaria,
    contratados ou não, cada um marcado com "contratado": True/False.

    Por quê existe separado da função acima: sem isso, um módulo fora do
    pacote contratado (ex.: a escola não comprou Pontualidade) some da
    tela sem deixar rastro — o admin não tem como distinguir "esse
    módulo não existe no produto" de "isso é um bug do meu sistema" (foi
    exatamente essa confusão que gerou um chamado de suporte). Mostrar o
    módulo travado, com o motivo, resolve a ambiguidade e ainda comunica
    que aquele módulo existe e pode ser contratado.

    NUNCA use o retorno desta função para validar o que um cargo pode
    salvar — isso continua sendo trabalho de `modulos_disponiveis`
    (contratados) via `_validar_modulos`. Esta função é só leitura, para
    montar a tela.
    """
    from core.auth import MODULOS_POR_PERFIL, MENU_ID_PARA_MODULO
    from core.router import modulos_ativos_permitidos
    contratados = modulos_ativos_permitidos(_carregar_config())
    return [
        {
            "id": item["id"],
            "nome": item["nome"],
            "contratado": MENU_ID_PARA_MODULO.get(item["id"], item["id"]) in contratados,
        }
        for item in MODULOS_POR_PERFIL.get(perfil_base, [])
    ]


def _validar_modulos(perfil_base: str, modulos: list[str]) -> list[str]:
    permitidos = {m["id"] for m in modulos_disponiveis(perfil_base)}
    invalidos = set(modulos) - permitidos
    if invalidos:
        raise ValueError(
            f"Módulo(s) fora do alcance do perfil-base '{perfil_base}': {', '.join(sorted(invalidos))}."
        )
    return [m for m in modulos if m in permitidos]


def _validar_escopo_turno(escopo: list[str]) -> list[str]:
    escopo = [e.strip() for e in (escopo or []) if e and e.strip()]
    if not escopo or TURNO_TODOS in escopo:
        return [TURNO_TODOS]
    validos = set(turnos_existentes())
    invalidos = set(escopo) - validos
    if invalidos:
        raise ValueError(f"Turno(s) desconhecido(s): {', '.join(sorted(invalidos))}.")
    return escopo


def criar_cargo(nome: str, perfil_base: str, modulos: list[str], escopo_turno: list[str], db=None) -> dict:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Dê um nome ao cargo.")
    if perfil_base not in _perfis_base_disponiveis():
        raise ValueError(f"Perfil-base inválido: '{perfil_base}'.")

    db = db or _get_db()
    _garantir_tabela(db)
    modulos = _validar_modulos(perfil_base, modulos)
    escopo_turno = _validar_escopo_turno(escopo_turno)

    registro = db.inserir("cargos", {
        "nome":         nome,
        "perfil_base":  perfil_base,
        "modulos":      _serializar(modulos),
        "escopo_turno": _serializar(escopo_turno),
        "sistema":      False,
    })
    return _formatar(registro)


def atualizar_cargo(cargo_id: int, nome: str | None = None, modulos: list[str] | None = None,
                     escopo_turno: list[str] | None = None, db=None) -> dict:
    """Atualiza nome/módulos/escopo de um cargo já existente. perfil_base
    nunca muda depois de criado — se a escola precisa de outra base,
    é mais seguro criar um cargo novo e migrar os usuários pra ele."""
    db = db or _get_db()
    _garantir_tabela(db)
    atual = db.buscar_um("cargos", onde={"id": cargo_id})
    if not atual:
        raise ValueError("Cargo não encontrado.")

    novos: dict = {}
    if nome is not None:
        nome = nome.strip()
        if not nome:
            raise ValueError("O nome do cargo não pode ficar vazio.")
        novos["nome"] = nome
    if modulos is not None:
        novos["modulos"] = _serializar(_validar_modulos(atual["perfil_base"], modulos))
    if escopo_turno is not None:
        novos["escopo_turno"] = _serializar(_validar_escopo_turno(escopo_turno))

    if novos:
        db.atualizar("cargos", novos, onde={"id": cargo_id})
    return cargo_por_id(cargo_id, db=db)


def remover_cargo(cargo_id: int, db=None) -> bool:
    db = db or _get_db()
    _garantir_tabela(db)
    atual = db.buscar_um("cargos", onde={"id": cargo_id})
    if not atual:
        return False
    if atual.get("sistema"):
        raise ValueError("Cargos de sistema não podem ser excluídos — apenas editados.")
    em_uso = db.buscar("usuarios", onde={"cargo_id": cargo_id})
    if em_uso:
        nomes = ", ".join(u["nome"] for u in em_uso[:5])
        raise ValueError(f"Este cargo está em uso por {len(em_uso)} usuário(s) ({nomes}...). "
                          "Mude o cargo desses usuários antes de excluir.")
    db.deletar("cargos", onde={"id": cargo_id})
    return True


def resolver_efetivo(usuario_registro: dict, db=None) -> dict:
    """
    Dado um registro cru da tabela 'usuarios', resolve o cargo efetivo:
    {cargo_id, cargo_nome, perfil_base, modulos: [...], escopo_turno: [...]}.
    Se o usuário não tem cargo_id válido (conta antiga, pré-cargos, ou
    cargo removido), cai automaticamente no cargo padrão do seu perfil —
    nunca fica sem menu por causa de uma migração incompleta.
    """
    db = db or _get_db()
    cargo_id = usuario_registro.get("cargo_id")
    cargo = cargo_por_id(cargo_id, db=db) if cargo_id else None
    if not cargo:
        cargo = cargo_padrao_do_perfil(usuario_registro.get("perfil", ""), db=db)
    if not cargo:
        # Perfil desconhecido (dado corrompido) — sem módulos, sem turno.
        return {"cargo_id": None, "cargo_nome": None, "perfil_base": usuario_registro.get("perfil"),
                "modulos": [], "escopo_turno": [TURNO_TODOS]}
    return {
        "cargo_id":     cargo["id"],
        "cargo_nome":   cargo["nome"],
        "perfil_base":  cargo["perfil_base"],
        "modulos":      cargo["modulos"],
        "escopo_turno": cargo["escopo_turno"],
    }
