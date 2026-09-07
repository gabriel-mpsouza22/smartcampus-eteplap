"""
Tipos de Ocorrência (régua disciplinar da escola)
---------------------------------------------------
Antes, a lista de tipos de ocorrência (advertência verbal, escrita,
suspensão...) era uma constante fixa no código — mudar exigia editar
Python. Agora ela mora numa tabela (`tipos_ocorrencia`), editável pela
Coordenação/Admin em Ocorrências → Configurar tipos: cada escola tem sua
própria régua disciplinar, e não tem por que a nossa estar "certa" pra
todo mundo.

Dois tipos são "protegidos" e não podem ser excluídos (só renomeados,
recoloridos, ter a severidade ajustada):

  - "elogio"  — o sistema trata elogio como reforço positivo em vários
                lugares (nunca conta pra alerta de comportamento, nunca
                entra no score de risco de evasão). Sem ele, esse
                tratamento especial não teria o que enxergar.
  - "outro"   — é o tipo de reserva usado quando uma ocorrência antiga
                tem um texto de tipo que não bate com nada conhecido
                (ver normalizar_tipo). Removê-lo quebraria esse
                fallback.

Qualquer outro tipo — incluindo os que vêm de fábrica (advertência
verbal, escrita, comunicado aos pais, suspensão) — pode ser livremente
editado, reordenado ou excluído (com a trava de não excluir um tipo que
ainda tem ocorrências registradas, pra não deixar histórico órfão).
"""

from pathlib import Path

BASE_CORE = Path(__file__).resolve().parent

TIPOS_PADRAO = [
    {"tipo_id": "elogio",              "nome": "Elogio",                "cor": "verde",    "severidade": 0, "protegido": True},
    {"tipo_id": "advertencia_verbal",  "nome": "Advertência Verbal",    "cor": "amarelo",  "severidade": 1, "protegido": False},
    {"tipo_id": "advertencia_escrita", "nome": "Advertência Escrita",   "cor": "laranja",  "severidade": 2, "protegido": False},
    {"tipo_id": "comunicado_pais",     "nome": "Comunicado aos Pais",   "cor": "azul",     "severidade": 2, "protegido": False},
    {"tipo_id": "suspensao",           "nome": "Suspensão",             "cor": "vermelho", "severidade": 3, "protegido": False},
    {"tipo_id": "outro",               "nome": "Outro",                 "cor": "cinza",    "severidade": 1, "protegido": True},
]

# Normalização de texto livre legado (ocorrências antigas gravadas antes
# de existir uma lista fechada de tipos, ou importadas de outro sistema).
# Isso é sobre RECONHECER grafias antigas — não sobre a régua da escola,
# por isso continua fixo no código mesmo com tipos customizáveis.
ALIASES_TEXTO_LIVRE = {
    "advertencia verbal":    "advertencia_verbal",
    "advertência verbal":    "advertencia_verbal",
    "advertencia escrita":   "advertencia_escrita",
    "advertência escrita":   "advertencia_escrita",
    "comunicado aos pais":   "comunicado_pais",
    "comunicado pais":       "comunicado_pais",
    "suspensão":             "suspensao",
}

CORES_VALIDAS = {"verde", "amarelo", "laranja", "vermelho", "azul", "cinza", "roxo"}


def _carregar_config() -> dict:
    from core.config_path import carregar_config
    return carregar_config(BASE_CORE.parent)


def _get_db():
    import sys
    sys.path.insert(0, str(BASE_CORE.parent))
    from sceds import SCEDS
    cfg = _carregar_config()
    from pathlib import Path as _P
    db = SCEDS(_P(cfg["caminho_base"]) / "sceds" / "data")
    _garantir_tabela(db)
    return db


def _schema() -> list[dict]:
    return [
        {"nome": "id",         "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "tipo_id",    "tipo": "TEXTO",    "modificadores": ["NAO_NULO"]},
        {"nome": "nome",       "tipo": "TEXTO",    "modificadores": ["NAO_NULO"]},
        {"nome": "cor",        "tipo": "TEXTO",    "modificadores": ["NAO_NULO"]},
        {"nome": "severidade", "tipo": "INTEIRO",  "modificadores": ["NAO_NULO"]},
        {"nome": "protegido",  "tipo": "BOOLEANO", "modificadores": []},
        {"nome": "ordem",      "tipo": "INTEIRO",  "modificadores": ["NAO_NULO"]},
    ]


def _garantir_tabela(db) -> None:
    if not db.tabela_existe("tipos_ocorrencia"):
        db.criar_tabela("tipos_ocorrencia", _schema())
        for i, t in enumerate(TIPOS_PADRAO):
            db.inserir("tipos_ocorrencia", {**t, "ordem": i})


def _formatar(registro: dict) -> dict:
    return {
        "id":         registro["tipo_id"],
        "nome":       registro["nome"],
        "cor":        registro["cor"],
        "severidade": registro["severidade"],
        "protegido":  bool(registro.get("protegido")),
        "ordem":      registro.get("ordem", 0),
    }


def listar(db=None) -> list[dict]:
    """Tipos de ocorrência desta escola, na ordem definida pelo admin."""
    db = db or _get_db()
    _garantir_tabela(db)
    tipos = [_formatar(t) for t in db.buscar("tipos_ocorrencia")]
    tipos.sort(key=lambda t: t["ordem"])
    return tipos


def mapa(db=None) -> dict[str, dict]:
    """tipo_id -> tipo, para lookup rápido (equivalente ao antigo TIPOS_MAP)."""
    return {t["id"]: t for t in listar(db=db)}


def tipo_info(tipo_id: str, db=None) -> dict:
    """Info de um tipo pelo id, ou o tipo de reserva 'outro' se não existir
    (uma ocorrência com um tipo_id desconhecido nunca deve quebrar a tela —
    ela só aparece com a cor/nome neutros de 'outro')."""
    m = mapa(db=db)
    return m.get(tipo_id) or m.get("outro") or {"nome": tipo_id, "cor": "cinza", "severidade": 1}


def normalizar_tipo(tipo_bruto: str, db=None) -> str:
    """
    Recebe o texto de tipo gravado numa ocorrência (pode ser um tipo_id
    válido, um texto livre antigo, ou algo desconhecido) e devolve um
    tipo_id que com certeza existe na régua atual da escola.
    """
    bruto = (tipo_bruto or "").strip()
    ids_validos = {t["id"] for t in listar(db=db)}
    if bruto in ids_validos:
        return bruto
    alias = ALIASES_TEXTO_LIVRE.get(bruto.lower())
    if alias in ids_validos:
        return alias
    return "outro"


def e_elogio(tipo_bruto: str, db=None) -> bool:
    return normalizar_tipo(tipo_bruto, db=db) == "elogio"


def _validar_cor(cor: str) -> str:
    cor = (cor or "").strip().lower()
    if cor not in CORES_VALIDAS:
        raise ValueError(f"Cor inválida: '{cor}'. Use uma de: {', '.join(sorted(CORES_VALIDAS))}.")
    return cor


def _slugificar(nome: str) -> str:
    import re
    import unicodedata
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")
    return slug or "tipo"


def criar(nome: str, cor: str, severidade: int, db=None) -> dict:
    db = db or _get_db()
    _garantir_tabela(db)
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Dê um nome ao tipo de ocorrência.")
    cor = _validar_cor(cor)
    try:
        severidade = int(severidade)
    except (TypeError, ValueError):
        raise ValueError("Severidade deve ser um número (0 a 3).")
    if not (0 <= severidade <= 3):
        raise ValueError("Severidade deve estar entre 0 (positivo) e 3 (grave).")

    existentes = {t["id"] for t in listar(db=db)}
    base_slug = _slugificar(nome)
    tipo_id = base_slug
    sufixo = 2
    while tipo_id in existentes:
        tipo_id = f"{base_slug}_{sufixo}"
        sufixo += 1

    maior_ordem = max([t["ordem"] for t in listar(db=db)], default=-1)
    registro = db.inserir("tipos_ocorrencia", {
        "tipo_id": tipo_id, "nome": nome, "cor": cor, "severidade": severidade,
        "protegido": False, "ordem": maior_ordem + 1,
    })
    return _formatar(registro)


def atualizar(tipo_id: str, nome: str | None = None, cor: str | None = None,
              severidade: int | None = None, ordem: int | None = None, db=None) -> dict:
    """nome/cor/severidade/ordem são editáveis mesmo em tipos protegidos
    (elogio e outro) — só o tipo_id e a exclusão são travados."""
    db = db or _get_db()
    _garantir_tabela(db)
    atual = db.buscar_um("tipos_ocorrencia", onde={"tipo_id": tipo_id})
    if not atual:
        raise ValueError("Tipo de ocorrência não encontrado.")

    novos: dict = {}
    if nome is not None:
        nome = nome.strip()
        if not nome:
            raise ValueError("O nome não pode ficar vazio.")
        novos["nome"] = nome
    if cor is not None:
        novos["cor"] = _validar_cor(cor)
    if severidade is not None:
        try:
            severidade = int(severidade)
        except (TypeError, ValueError):
            raise ValueError("Severidade deve ser um número (0 a 3).")
        if not (0 <= severidade <= 3):
            raise ValueError("Severidade deve estar entre 0 (positivo) e 3 (grave).")
        novos["severidade"] = severidade
    if ordem is not None:
        novos["ordem"] = int(ordem)

    if novos:
        db.atualizar("tipos_ocorrencia", novos, onde={"tipo_id": tipo_id})
    return _formatar(db.buscar_um("tipos_ocorrencia", onde={"tipo_id": tipo_id}))


def remover(tipo_id: str, db=None) -> bool:
    db = db or _get_db()
    _garantir_tabela(db)
    atual = db.buscar_um("tipos_ocorrencia", onde={"tipo_id": tipo_id})
    if not atual:
        return False
    if atual.get("protegido"):
        raise ValueError(f"O tipo \"{atual['nome']}\" é usado internamente pelo sistema e não pode ser excluído "
                          "— mas pode ser renomeado, recolorido ou ter a severidade ajustada.")
    em_uso = db.buscar("ocorrencias", onde={"tipo": tipo_id})
    if em_uso:
        raise ValueError(f"Existem {len(em_uso)} ocorrência(s) registrada(s) com este tipo — "
                          "não é possível excluir um tipo em uso. Edite as ocorrências antigas primeiro, se necessário.")
    db.deletar("tipos_ocorrencia", onde={"tipo_id": tipo_id})
    return True
