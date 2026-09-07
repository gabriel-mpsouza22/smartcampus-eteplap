"""
SmartCampus - Gerador de Mock Data ETEPLAP

Uso:
    python gerar_mock_data.py

O script não usa config.json de mock nem seed. Ele localiza a instalação do
SmartCampus, lê os schemas SCEDS existentes e recria os dados de demonstração
para os módulos contratados. O objetivo é produzir dados relacionais e
coerentes entre alunos, frequência, pontualidade, ocorrências, biblioteca,
reservas, chaves e secretaria/portaria.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

START = date(2026, 2, 2)
END = date(2026, 8, 26)
SCHOOL_START = "07:30"

# Dias sem aulas usados para evitar eventos obviamente irreais.
FERIADOS = {
    date(2026, 2, 16), date(2026, 2, 17),  # Carnaval
    date(2026, 4, 3),                       # Sexta-feira Santa
    date(2026, 4, 21),                      # Tiradentes
    date(2026, 5, 1),                       # Dia do Trabalho
    date(2026, 6, 24),                      # São João
}

FIRST_NAMES_M = [
    "João", "Pedro", "Gabriel", "Lucas", "Matheus", "Rafael", "Guilherme", "Felipe",
    "Miguel", "Arthur", "Heitor", "Davi", "Bernardo", "Samuel", "Enzo", "Nicolas",
    "Vinícius", "Caio", "Bruno", "Gustavo", "Henrique", "Leonardo", "Daniel", "André",
    "Thiago", "Eduardo", "Vitor", "Diego", "Carlos", "Luiz", "José", "Marcelo",
]
FIRST_NAMES_F = [
    "Maria", "Ana", "Júlia", "Mariana", "Beatriz", "Larissa", "Camila", "Letícia",
    "Isabela", "Sofia", "Laura", "Manuela", "Valentina", "Helena", "Alice", "Clara",
    "Luiza", "Gabriela", "Eduarda", "Yasmin", "Vitória", "Amanda", "Carolina", "Bianca",
    "Rafaela", "Giovanna", "Nicole", "Emanuelle", "Lívia", "Cecília", "Fernanda", "Brenda",
]
MIDDLE = ["Pedro", "Henrique", "Gabriel", "Eduardo", "Miguel", "Luiz", "Rafael", "Augusto", "Maria", "Clara", "Eduarda", "Vitória"]
LAST_NAMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Costa", "Ferreira", "Alves",
    "Rodrigues", "Martins", "Gomes", "Barbosa", "Ribeiro", "Carvalho", "Almeida", "Nascimento",
    "Araújo", "Melo", "Teixeira", "Moreira", "Correia", "Moura", "Freitas", "Cardoso", "Nunes",
    "Vieira", "Cavalcanti", "Rocha", "Dias", "Monteiro", "Mendes", "Barros", "Bezerra", "Campos",
]

TEACHERS = [
    ("Marcos Vinícius Almeida", "professor"),
    ("Renata Cristina Souza", "professor"),
    ("André Luiz Cavalcanti", "professor"),
    ("Juliana Maria Ferreira", "professor"),
    ("Carlos Eduardo Nascimento", "professor"),
    ("Patrícia Helena Gomes", "professor"),
    ("Rodrigo Henrique Santos", "professor"),
    ("Fernanda Alves da Silva", "professor"),
    ("Thiago Rafael Oliveira", "professor"),
    ("Camila Beatriz Moura", "professor"),
]

STAFF = [
    ("Ana Paula Ribeiro", "secretaria"),
    ("José Roberto Lima", "portaria"),
    ("Luciana Maria Costa", "bibliotecaria"),
    ("Daniela Cristina Barbosa", "coordenadora"),
]

RESOURCES = [
    {"id": "lab_redes", "nome": "Laboratório de Redes", "tipo": "laboratorio", "icone": "i-monitor"},
    {"id": "lab_info_01", "nome": "Laboratório de Informática 01", "tipo": "laboratorio", "icone": "i-monitor"},
    {"id": "lab_info_02", "nome": "Laboratório de Informática 02", "tipo": "laboratorio", "icone": "i-monitor"},
    {"id": "lab_admin", "nome": "Laboratório de Administração", "tipo": "laboratorio", "icone": "i-monitor"},
    {"id": "sala_multimidia", "nome": "Sala Multimídia", "tipo": "sala", "icone": "i-projector"},
    {"id": "auditorio", "nome": "Auditório ETEPLAP", "tipo": "espaco", "icone": "i-building"},
    {"id": "sala_reunioes", "nome": "Sala de Reuniões", "tipo": "sala", "icone": "i-building"},
    {"id": "projetor_01", "nome": "Projetor 01", "tipo": "equipamento", "icone": "i-projector"},
    {"id": "projetor_02", "nome": "Projetor 02", "tipo": "equipamento", "icone": "i-projector"},
    {"id": "notebook_01", "nome": "Notebook 01", "tipo": "equipamento", "icone": "i-monitor"},
    {"id": "notebook_02", "nome": "Notebook 02", "tipo": "equipamento", "icone": "i-monitor"},
    {"id": "caixa_som",   "nome": "Caixa de Som",       "tipo": "equipamento", "icone": "i-box"},
    {"id": "microfone",   "nome": "Microfone Sem Fio",  "tipo": "equipamento", "icone": "i-mic"},
    {"id": "kit_rede",    "nome": "Kit de Cabos de Rede","tipo": "equipamento", "icone": "i-antenna"},
]

KEY_LOCATIONS = [
    "Laboratório de Redes", "Laboratório de Informática 01", "Laboratório de Informática 02",
    "Laboratório de Administração", "Sala Multimídia", "Auditório ETEPLAP", "Sala dos Professores",
    "Coordenação", "Secretaria", "Almoxarifado",
]

BOOKS = [
    ("Redes de Computadores", "James F. Kurose; Keith W. Ross", "Redes de Computadores"),
    ("Comunicação de Dados e Redes de Computadores", "Behrouz A. Forouzan", "Redes de Computadores"),
    ("Redes de Computadores e a Internet", "Douglas E. Comer", "Redes de Computadores"),
    ("Cabeamento Estruturado", "Marin Paulo", "Redes de Computadores"),
    ("TCP/IP Illustrated", "W. Richard Stevens", "Redes de Computadores"),
    ("Linux - A Bíblia", "Christopher Negus", "Sistemas Operacionais"),
    ("Sistemas Operacionais Modernos", "Andrew S. Tanenbaum", "Sistemas Operacionais"),
    ("Python Fluente", "Luciano Ramalho", "Programação"),
    ("Automatize Tarefas Maçantes com Python", "Al Sweigart", "Programação"),
    ("Código Limpo", "Robert C. Martin", "Programação"),
    ("Entendendo Algoritmos", "Aditya Bhargava", "Programação"),
    ("Estruturas de Dados e Algoritmos", "Michael T. Goodrich", "Programação"),
    ("Banco de Dados", "Abraham Silberschatz", "Banco de Dados"),
    ("Sistemas de Banco de Dados", "Ramez Elmasri; Shamkant Navathe", "Banco de Dados"),
    ("SQL para Análise de Dados", "Cathy Tanimura", "Banco de Dados"),
    ("Segurança de Redes", "William Stallings", "Segurança da Informação"),
    ("Criptografia e Segurança de Redes", "William Stallings", "Segurança da Informação"),
    ("Engenharia de Software", "Ian Sommerville", "Engenharia de Software"),
    ("Eletrônica Básica", "Thomas L. Floyd", "Eletrônica"),
    ("Arquitetura e Organização de Computadores", "William Stallings", "Hardware"),
    ("Organização Estruturada de Computadores", "Andrew S. Tanenbaum", "Hardware"),
    ("Matemática Básica", "Manuel Paiva", "Matemática"),
    ("Fundamentos de Matemática", "Gelson Iezzi", "Matemática"),
    ("Física", "Hugh D. Young", "Física"),
    ("Química Geral", "John C. Kotz", "Química"),
    ("Gramática da Língua Portuguesa", "Pasquale Cipro Neto", "Português"),
    ("Redação para Concursos e Vestibulares", "Dad Squarisi", "Português"),
    ("Dom Casmurro", "Machado de Assis", "Literatura Brasileira"),
    ("Memórias Póstumas de Brás Cubas", "Machado de Assis", "Literatura Brasileira"),
    ("Vidas Secas", "Graciliano Ramos", "Literatura Brasileira"),
    ("Capitães da Areia", "Jorge Amado", "Literatura Brasileira"),
    ("O Cortiço", "Aluísio Azevedo", "Literatura Brasileira"),
    ("Grande Sertão: Veredas", "João Guimarães Rosa", "Literatura Brasileira"),
    ("1984", "George Orwell", "Literatura Estrangeira"),
    ("Admirável Mundo Novo", "Aldous Huxley", "Literatura Estrangeira"),
    ("O Pequeno Príncipe", "Antoine de Saint-Exupéry", "Literatura Estrangeira"),
    ("História do Brasil", "Boris Fausto", "História"),
    ("História Geral", "Cláudio Vicentino", "História"),
    ("Geografia Geral e do Brasil", "João Carlos Moreira", "Geografia"),
    ("Fundamentos de Administração", "Idalberto Chiavenato", "Administração"),
    ("Teoria Geral da Administração", "Idalberto Chiavenato", "Administração"),
    ("Administração Financeira", "Alexandre Assaf Neto", "Administração"),
    ("Gestão de Pessoas", "Idalberto Chiavenato", "Gestão"),
    ("Marketing", "Philip Kotler", "Marketing"),
    ("Contabilidade Básica", "José Carlos Marion", "Contabilidade"),
    ("Economia", "Paul Krugman", "Economia"),
    ("Empreendedorismo", "José Dornelas", "Empreendedorismo"),
    ("Comunicação Empresarial", "Margarida Kunsch", "Comunicação"),
    ("Inglês Técnico para Informática", "Antônio Carlos dos Santos", "Inglês Técnico"),
]


def log(msg: str):
    print(f"[SmartCampus Mock] {msg}", flush=True)


def localizar_base() -> Path:
    candidatos = [ROOT]
    if Path.cwd() not in candidatos:
        candidatos.append(Path.cwd())
    env = os.getenv("SMARTCAMPUS_HOME")
    if env:
        candidatos.insert(0, Path(env))
    for base in candidatos:
        if (base / "sceds" / "data").is_dir() and (base / "core" / "config.json").exists():
            return base
    raise FileNotFoundError("Não encontrei uma instalação SmartCampus. Rode este script dentro da pasta SmartCampus ou defina SMARTCAMPUS_HOME.")


def load_json(path: Path, default=None):
    """
    Lê um arquivo JSON. Tabelas de dados (.sceds) são cifradas em
    repouso (ver sceds/crypto.py) — este helper decifra
    transparentemente nesse caso, e também aceita tabelas legadas em
    texto puro (migração automática, mesma lógica do motor SCEDS).
    Schemas (.schema.json) continuam em texto puro, sem dado pessoal.
    """
    if not path.exists():
        return default

    if path.suffix == ".sceds":
        from sceds.crypto import carregar_ou_criar_chave, decifrar_ou_legado
        chave = carregar_ou_criar_chave(path.parent)
        dados, era_texto_puro = decifrar_ou_legado(path.read_bytes(), chave)
        if era_texto_puro:
            save_json(path, dados)  # migra para o formato cifrado já na leitura
        return dados

    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    """Contraparte de load_json — cifra tabelas .sceds antes de gravar
    (escrita atômica: grava em .tmp e substitui só no final)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    if path.suffix == ".sceds":
        from sceds.crypto import carregar_ou_criar_chave, cifrar
        chave = carregar_ou_criar_chave(path.parent)
        tmp.write_bytes(cifrar(data, chave))
    else:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    tmp.replace(path)


def schema_columns(data_dir: Path, table: str):
    schema = load_json(data_dir / f"{table}.schema.json", {})
    return {c["nome"]: c for c in schema.get("colunas", [])}


def ensure_table(data_dir: Path, table: str, columns: list[dict]):
    schema_path = data_dir / f"{table}.schema.json"
    data_path = data_dir / f"{table}.sceds"
    if not schema_path.exists():
        save_json(schema_path, {"tabela": table, "colunas": columns, "criada_em": datetime.now().isoformat()})
    if not data_path.exists():
        save_json(data_path, {"registros": [], "proximo_id": 1})


def ensure_columns(data_dir: Path, table: str, additions: list[dict]):
    path = data_dir / f"{table}.schema.json"
    schema = load_json(path, {"tabela": table, "colunas": [], "criada_em": datetime.now().isoformat()})
    names = {c.get("nome") for c in schema.get("colunas", [])}
    changed = False
    for col in additions:
        if col["nome"] not in names:
            schema.setdefault("colunas", []).append(col)
            names.add(col["nome"])
            changed = True
    if changed:
        save_json(path, schema)


def table_rows(data_dir: Path, table: str):
    return load_json(data_dir / f"{table}.sceds", {"registros": [], "proximo_id": 1})


def batch_replace(data_dir: Path, table: str, rows: list[dict], pk="id"):
    """Escreve um lote de uma vez, respeitando o formato SCEDS."""
    path = data_dir / f"{table}.sceds"
    current = table_rows(data_dir, table)
    start = int(current.get("proximo_id", 1))
    cols = schema_columns(data_dir, table)
    out = []
    next_id = start
    for row in rows:
        r = {}
        for name in cols:
            if name == pk and "AUTO" in cols[name].get("modificadores", []):
                if name in row and row[name] is not None:
                    # Linha já tem um id (ex.: admin preservado de antes
                    # de a tabela ser recriada) — mantém o id original em
                    # vez de trocar por um novo, senão a sessão de login
                    # dessa pessoa (que guarda esse id) vira inválida.
                    r[name] = row[name]
                    next_id = max(next_id, row[name] + 1)
                else:
                    r[name] = next_id
                    next_id += 1
            elif name in row:
                r[name] = row[name]
        # Alguns schemas antigos têm colunas opcionais adicionadas depois.
        for name, value in row.items():
            if name in cols and name not in r:
                r[name] = value
        out.append(r)
    save_json(path, {"registros": out, "proximo_id": next_id})
    return len(out)


def clear_table(data_dir: Path, table: str):
    path = data_dir / f"{table}.sceds"
    if path.exists():
        current = load_json(path, {})
        save_json(path, {"registros": [], "proximo_id": 1})


def days_between(start=START, end=END):
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in FERIADOS:
            yield d
        d += timedelta(days=1)


def random_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(100):
        first_pool = FIRST_NAMES_M if rng.random() < 0.48 else FIRST_NAMES_F
        first = rng.choice(first_pool)
        if rng.random() < 0.28:
            first += " " + rng.choice(MIDDLE)
        name = f"{first} {rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}"
        if name not in used:
            used.add(name)
            return name
    name = f"Aluno {len(used)+1:04d}"
    used.add(name)
    return name


def hash_demo_password(password="SmartCampus@2026"):
    # Compatível com o fallback SHA-256 do core.auth.
    salt = hashlib.sha256(f"{password}-salt".encode()).hexdigest()[:16]
    digest = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"sha256:{salt}:{digest}"


def make_students(rng):
    """Gera alunos para todas as turmas configuradas no pacote instalado."""
    students = []
    used = set()
    idx = 1
    turmas_cfg = load_json(ROOT / "core" / "turmas.json", {"turmas": []}).get("turmas", [])
    if not turmas_cfg:
        turmas_cfg = [
            {"turma": f"{serie}º Ano {letra} — {curso}", "serie": serie, "curso": curso}
            for serie in ("1", "2", "3")
            for curso in ("Redes de Computadores", "Administração")
            for letra in ("A", "B")
        ]

    for info in turmas_cfg:
        turma = info["turma"]
        serie = str(info.get("serie", ""))
        curso = info.get("curso", "")
        n = rng.randint(35, 40)
        for _ in range(n):
            name = random_name(rng, used)
            students.append({
                "nome": name,
                "serie": serie,
                "turma": turma,
                "curso": curso,
                "tecnico_ti": False,
                "matricula": f"2026{idx:05d}",
                "status": "ativo",
            })
            idx += 1
    return students

def profiles(rng, students):
    # Perfil latente usado por todos os módulos para manter histórias coerentes.
    rng.shuffle(students)
    n = len(students)
    counts = {
        "excelente": round(n * 0.32),
        "bom": round(n * 0.38),
        "regular": round(n * 0.18),
        "dificuldade": round(n * 0.08),
        "critico": n,
    }
    counts["critico"] = n - sum(counts[k] for k in ("excelente", "bom", "regular", "dificuldade"))
    prof = {}
    i = 0
    for kind, count in counts.items():
        for s in students[i:i+count]:
            prof[s["matricula"]] = kind
        i += count
    return prof


def generate_users(data_dir, existing_admin_name):
    rows = []
    existing = table_rows(data_dir, "usuarios")["registros"]
    # preserva administradores existentes criados pelo instalador.
    for u in existing:
        if u.get("perfil") == "admin":
            rows.append(u)
    now = datetime(2026, 2, 2, 7, 0).isoformat()
    for name, perfil in TEACHERS + STAFF:
        rows.append({"nome": name, "perfil": perfil, "senha_hash": hash_demo_password(), "ativo": True, "criado_em": now})
    return batch_replace(data_dir, "usuarios", rows)


def user_maps(data_dir):
    users = table_rows(data_dir, "usuarios")["registros"]
    return {u["nome"]: u for u in users}, [u for u in users if u.get("perfil") == "professor"]


def generate_books(data_dir, rng):
    rows = []
    shelves = ["A-01", "A-02", "A-03", "B-01", "B-02", "B-03", "C-01", "C-02", "D-01", "D-02", "E-01"]
    for title, author, genre in BOOKS:
        copies = rng.randint(9, 15)
        for i in range(1, copies + 1):
            rows.append({"nome": f"{title} — Ex. {i:02d}", "autor": author, "genero": genre, "prateleira": rng.choice(shelves)})
    return batch_replace(data_dir, "livros", rows)


def generate_loans(data_dir, students, profiles_map, rng):
    books = table_rows(data_dir, "livros")["registros"]
    if not books:
        return 0
    rng.shuffle(books)
    # 150 ativos: 90 no prazo + 60 atrasados; 90 históricos devolvidos.
    active_count = min(150, len(books))
    overdue_count = min(60, active_count // 2)
    ontime_count = active_count - overdue_count
    loan_books = books[:active_count + 90]
    students_by_quality = sorted(students, key=lambda s: {"excelente":0,"bom":1,"regular":2,"dificuldade":3,"critico":4}[profiles_map[s["matricula"]]])
    rows = []
    for idx, book in enumerate(loan_books):
        student = rng.choice(students_by_quality)
        start = START + timedelta(days=rng.randint(0, 190))
        if start > END:
            start = END - timedelta(days=rng.randint(0, 5))
        if idx < overdue_count:
            due = min(END, start + timedelta(days=rng.randint(10, 35)))
            if due >= END:
                due = END - timedelta(days=rng.randint(1, 20))
            returned = False
            ret = None
        elif idx < active_count:
            due = min(END + timedelta(days=7), start + timedelta(days=rng.randint(3, 7)))
            returned = False
            ret = None
        else:
            due = start + timedelta(days=rng.randint(5, 10))
            ret = min(END, due + timedelta(days=rng.randint(-2, 8)))
            if ret < start:
                ret = start + timedelta(days=2)
            returned = True
        rows.append({
            "livro_id": book["id"], "aluno_id": student["id"], "aluno_nome": student["nome"],
            "aluno_turma": student["turma"], "aluno_curso": student["curso"],
            "data_emprestimo": start.isoformat(), "data_prevista_devolucao": due.isoformat(),
            "devolvido": returned, "data_devolucao": ret.isoformat() if ret else None,
        })
    return batch_replace(data_dir, "emprestimos", rows)


def generate_occurrences(data_dir, students, profiles_map, rng):
    rows = []
    types = ["elogio", "advertencia_verbal", "advertencia_escrita", "comunicado_pais", "suspensao", "outro"]
    # A maioria sem ocorrência; casos de dificuldade concentram histórico.
    weights = {"excelente": 0.10, "bom": 0.45, "regular": 1.0, "dificuldade": 2.5, "critico": 4.0}
    target = max(80, round(len(students) * 0.38))
    for _ in range(target):
        s = rng.choices(students, weights=[weights[profiles_map[x["matricula"]]] for x in students], k=1)[0]
        profile = profiles_map[s["matricula"]]
        if profile in ("excelente", "bom") and rng.random() < 0.18:
            typ = "elogio"
        elif profile == "critico":
            typ = rng.choices(types[1:], weights=[30, 20, 25, 12, 8])[0]
        else:
            typ = rng.choices(types, weights=[10, 35, 15, 15, 3, 12])[0]
        day = START + timedelta(days=rng.randint(0, (END - START).days))
        if day.weekday() >= 5:
            day -= timedelta(days=day.weekday() - 4)
        hour = rng.choice(["08:05", "09:15", "10:40", "11:20", "13:10", "14:30"])
        descriptions = {
            "elogio": "Reconhecimento por participação, colaboração e bom desempenho em atividade escolar.",
            "advertencia_verbal": "Orientação registrada após ocorrência disciplinar de baixa gravidade.",
            "advertencia_escrita": "Advertência registrada após reincidência de comportamento inadequado.",
            "comunicado_pais": "Registro de comunicação à família para acompanhamento da situação.",
            "suspensao": "Ocorrência grave com encaminhamento para acompanhamento da coordenação.",
            "outro": "Registro administrativo relacionado à rotina escolar.",
        }
        rows.append({"aluno_id": s["id"], "tipo": typ, "envolvido_2": "", "descricao": descriptions[typ], "data_hora": datetime.combine(day, datetime.strptime(hour, "%H:%M").time()).isoformat()})
    rows.sort(key=lambda x: x["data_hora"])
    return batch_replace(data_dir, "ocorrencias", rows, pk="numero")


def generate_evasao(data_dir, students, profiles_map, rng):
    rows = []
    periods = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    bases = {"excelente": (94, 99), "bom": (86, 95), "regular": (76, 89), "dificuldade": (58, 76), "critico": (35, 62)}
    for s in students:
        kind = profiles_map[s["matricula"]]
        current = rng.uniform(*bases[kind])
        for p in periods:
            # tendência: bons ficam estáveis; críticos tendem a cair.
            if kind == "excelente": current += rng.uniform(-0.5, 0.6)
            elif kind == "bom": current += rng.uniform(-1.2, 0.8)
            elif kind == "regular": current += rng.uniform(-2.0, 1.0)
            elif kind == "dificuldade": current += rng.uniform(-3.5, 0.8)
            else: current += rng.uniform(-5.0, 0.5)
            current = max(32.0, min(99.0, current))
            rows.append({"aluno_id": s["id"], "percentual": round(current, 1), "periodo_referencia": p, "registrado_por": "Sistema de acompanhamento escolar", "registrado_em": f"{p}-25T16:30:00"})
    return batch_replace(data_dir, "evasao_frequencia", rows)


def ensure_pontualidade_table(data_dir):
    ensure_table(data_dir, "entradas_pontualidade", [
        {"nome":"id","tipo":"INTEIRO","modificadores":["CHAVE_PRIMARIA","AUTO"]},
        {"nome":"aluno_id","tipo":"INTEIRO","modificadores":["NAO_NULO"]},
        {"nome":"aluno_nome","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"aluno_turma","tipo":"TEXTO","modificadores":[]},
        {"nome":"data","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"horario","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"status","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"status_label","tipo":"TEXTO","modificadores":[]},
        {"nome":"operador","tipo":"TEXTO","modificadores":[]},
        {"nome":"observacoes","tipo":"TEXTO","modificadores":[]},
        {"nome":"criado_em","tipo":"DATA_HORA","modificadores":["NAO_NULO"]},
    ])


def generate_punctuality(data_dir, students, profiles_map, rng):
    ensure_pontualidade_table(data_dir)
    rows = []
    weights = {"excelente": 0.03, "bom": 0.07, "regular": 0.13, "dificuldade": 0.24, "critico": 0.38}
    for day in days_between():
        for s in students:
            kind = profiles_map[s["matricula"]]
            p_late = weights[kind]
            if rng.random() < p_late:
                minute = rng.choices(range(4, 95), weights=[max(1, 100-i) for i in range(91)], k=1)[0]
                # 80% dos atrasos são leves/moderados; poucos são graves.
                status = "atraso" if minute < 50 else ("atraso_leve" if minute < 55 else "atraso_grave")
                hour = 7 + (30 + minute) // 60
                minute2 = (30 + minute) % 60
                horario = f"{hour:02d}:{minute2:02d}"
                label = {"atraso":"Atraso — perdeu a 1ª aula", "atraso_leve":"Entrada permitida na 2ª aula", "atraso_grave":"Atraso — entrada após o início das atividades"}[status]
                obs = "Atraso registrado na entrada."
            else:
                # Pequena variação antes de 07:30 para não parecer artificial.
                early = rng.randint(2, 20)
                total = 7 * 60 + 30 - early
                horario = f"{total//60:02d}:{total%60:02d}"
                status, label, obs = "normal", "Entrada normal", "Entrada registrada no horário." 
            dt = datetime.combine(day, datetime.strptime(horario, "%H:%M").time())
            rows.append({"aluno_id":s["id"],"aluno_nome":s["nome"],"aluno_turma":s["turma"],"data":day.isoformat(),"horario":horario,"status":status,"status_label":label,"operador":"José Roberto Lima","observacoes":obs,"criado_em":dt.isoformat()})
    return batch_replace(data_dir, "entradas_pontualidade", rows)


def generate_reservations(data_dir, professors, rng):
    rows = []
    school_days = list(days_between())
    # ~5 reservas/professor/mês, com histórico suficiente para gráficos.
    for p in professors:
        for _ in range(18):
            day = rng.choice(school_days)
            start_hour = rng.choice([8, 9, 10, 11, 13, 14, 15])
            duration = rng.choice([1, 1, 1, 2])
            start = f"{start_hour:02d}:00"
            end_hour = min(17, start_hour + duration)
            end = f"{end_hour:02d}:00"
            resource = rng.choice(RESOURCES)
            past = day < date(2026, 8, 26)
            returned = past and rng.random() < 0.88
            rows.append({"professor_id":p["id"],"professor_nome":p["nome"],"recurso_tipo":resource["tipo"],"recurso_nome":resource["nome"],"recurso_id":resource["id"],"data_reserva":day.isoformat(),"hora_inicio":start,"hora_fim":end,"devolvido":returned,"data_devolucao":(datetime.combine(day, datetime.strptime(end, "%H:%M").time()) + timedelta(minutes=rng.randint(5,30))).isoformat() if returned else None})
    return batch_replace(data_dir, "reservas", rows)


def generate_keys(data_dir, professors, rng):
    keys = [{"nome":f"Chave — {loc}","local":loc,"icone":"i-key","observacoes":"Controle interno de acesso.","ativa":True,"criada_em":"2026-02-02T07:00:00"} for loc in KEY_LOCATIONS]
    nkeys = batch_replace(data_dir, "chaves", keys)
    key_rows = table_rows(data_dir, "chaves")["registros"]
    moves = []
    school_days = list(days_between())
    for _ in range(95):
        key = rng.choice(key_rows)
        p = rng.choice(professors)
        day = rng.choice(school_days)
        h = rng.choice([7,8,9,10,11,13,14,15])
        retired = datetime(day.year, day.month, day.day, h, rng.randint(0,50))
        due = retired + timedelta(hours=rng.choice([1,2,3]))
        returned = rng.random() < 0.83
        ret = due + timedelta(minutes=rng.randint(-30,120)) if returned else None
        moves.append({"chave_id":key["id"],"chave_nome":key["nome"],"professor_id":p["id"],"professor_nome":p["nome"],"registrado_por":"José Roberto Lima","retirado_em":retired.isoformat(),"devolucao_prevista":due.isoformat(),"observacao":"Retirada para atividade pedagógica." if returned else "Chave ainda não devolvida; acompanhamento pela portaria.","devolvido_em":ret.isoformat() if ret else None,"devolvido_por":p["nome"] if ret else None})
    nmoves = batch_replace(data_dir, "chaves_movimentos", moves)
    return nkeys, nmoves


def generate_secretaria(data_dir, rng):
    rows = []
    reasons = ["Atendimento de responsável", "Reunião pedagógica", "Entrega de documentação", "Orientação de matrícula", "Atendimento da coordenação", "Reunião com professor"]
    school_days = list(days_between())
    for _ in range(55):
        d = rng.choice(school_days)
        rows.append({"data":d.isoformat(),"hora":rng.choice(["08:00","09:00","10:00","11:00","13:30","14:30","15:30"]),"responsavel":rng.choice(["Ana Paula Ribeiro","Daniela Cristina Barbosa","Marcos Vinícius Almeida"]),"motivo":rng.choice(reasons),"criado_em":datetime.combine(d, datetime.strptime("07:45", "%H:%M").time()).isoformat()})
    n1 = batch_replace(data_dir, "compromissos", rows)
    # Conversas curtas e plausíveis entre secretaria/portaria.
    scripts = [
        [("Ana Paula Ribeiro","Bom dia. Pode verificar se o responsável do aluno chegou?"),("José Roberto Lima","Bom dia. Sim, ele está aguardando na recepção."),("Ana Paula Ribeiro","Perfeito, vou chamá-lo para a secretaria.")],
        [("José Roberto Lima","A coordenação solicitou a liberação da sala multimídia às 13h."),("Ana Paula Ribeiro","Certo. Vou registrar o compromisso e avisar a coordenação."),("José Roberto Lima","Obrigado.")],
        [("Ana Paula Ribeiro","A professora Renata deixou uma documentação para entrega."),("José Roberto Lima","Vou encaminhar para a sala dos professores."),("Ana Paula Ribeiro","Obrigada!")],
    ]
    messages = []
    for i in range(22):
        script = rng.choice(scripts)
        base = datetime(2026, 2, 2, 8, 0) + timedelta(days=rng.randint(0,190), minutes=rng.randint(0,500))
        for j, (sender, text) in enumerate(script):
            dt = base + timedelta(minutes=j * rng.randint(2,5))
            messages.append({"remetente":sender,"texto":text,"data_hora":dt.isoformat()})
    messages.sort(key=lambda x: x["data_hora"])
    n2 = batch_replace(data_dir, "mensagens_chat", messages)
    return n1, n2


def update_resources(base: Path):
    path = base / "modulos" / "agendamento" / "recursos.json"
    save_json(path, {"recursos": RESOURCES})



# ---------------------------------------------------------------------------
# Massa adicional: módulos que criam suas tabelas sob demanda.
# O instalador entrega os schemas básicos; estes schemas são criados aqui
# para que uma instalação nova já saia navegável em todos os módulos.

SCHEMAS_EXTRAS = {
    "saidas_autorizacoes": [
        {"nome":"id","tipo":"INTEIRO","modificadores":["CHAVE_PRIMARIA","AUTO"]},
        {"nome":"aluno_id","tipo":"INTEIRO","modificadores":["NAO_NULO"]},
        {"nome":"aluno_nome","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"aluno_turma","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"data","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"horario_previsto","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"motivo","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"observacao","tipo":"TEXTO","modificadores":[]},
        {"nome":"responsavel_nome","tipo":"TEXTO","modificadores":[]},
        {"nome":"responsavel_relacao","tipo":"TEXTO","modificadores":[]},
        {"nome":"origem","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"solicitante","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"requer_coordenacao","tipo":"BOOLEANO","modificadores":["NAO_NULO"]},
        {"nome":"status","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"autorizado_por","tipo":"TEXTO","modificadores":[]},
        {"nome":"autorizado_em","tipo":"DATA_HORA","modificadores":[]},
        {"nome":"motivo_rejeicao","tipo":"TEXTO","modificadores":[]},
        {"nome":"motivo_revogacao","tipo":"TEXTO","modificadores":[]},
        {"nome":"revogado_por","tipo":"TEXTO","modificadores":[]},
        {"nome":"revogado_em","tipo":"DATA_HORA","modificadores":[]},
        {"nome":"saida_registrada_em","tipo":"DATA_HORA","modificadores":[]},
        {"nome":"saida_registrada_por","tipo":"TEXTO","modificadores":[]},
        {"nome":"criado_em","tipo":"DATA_HORA","modificadores":["NAO_NULO"]},
    ],
    "saidas_eventos": [
        {"nome":"id","tipo":"INTEIRO","modificadores":["CHAVE_PRIMARIA","AUTO"]},
        {"nome":"autorizacao_id","tipo":"INTEIRO","modificadores":["NAO_NULO"]},
        {"nome":"tipo","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"autor","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"estado_anterior","tipo":"TEXTO","modificadores":[]},
        {"nome":"estado_novo","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"detalhe","tipo":"TEXTO","modificadores":[]},
        {"nome":"criado_em","tipo":"DATA_HORA","modificadores":["NAO_NULO"]},
    ],
    "visitantes_visitas": [
        {"nome":"id","tipo":"INTEIRO","modificadores":["CHAVE_PRIMARIA","AUTO"]},
        {"nome":"visitante_nome","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"visitante_documento","tipo":"TEXTO","modificadores":[]},
        {"nome":"destino","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"motivo","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"motivo_detalhe","tipo":"TEXTO","modificadores":[]},
        {"nome":"observacao","tipo":"TEXTO","modificadores":[]},
        {"nome":"status","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"entrada_em","tipo":"DATA_HORA","modificadores":["NAO_NULO"]},
        {"nome":"saida_em","tipo":"DATA_HORA","modificadores":[]},
        {"nome":"registrado_por","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"saida_registrada_por","tipo":"TEXTO","modificadores":[]},
        {"nome":"criado_em","tipo":"DATA_HORA","modificadores":["NAO_NULO"]},
    ],
    "visitantes_eventos": [
        {"nome":"id","tipo":"INTEIRO","modificadores":["CHAVE_PRIMARIA","AUTO"]},
        {"nome":"visita_id","tipo":"INTEIRO","modificadores":["NAO_NULO"]},
        {"nome":"tipo","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"autor","tipo":"TEXTO","modificadores":["NAO_NULO"]},
        {"nome":"detalhe","tipo":"TEXTO","modificadores":[]},
        {"nome":"criado_em","tipo":"DATA_HORA","modificadores":["NAO_NULO"]},
    ],
}

def ensure_extra_tables(data_dir):
    for table, columns in SCHEMAS_EXTRAS.items():
        if not (data_dir / f"{table}.sceds").exists():
            ensure_table(data_dir, table, columns)

def generate_saidas(data_dir, students, rng):
    ensure_extra_tables(data_dir)
    motivos = ["consulta médica", "compromisso familiar", "atividade externa", "saída antecipada", "outro"]
    responsaveis = [
        ("Ana Paula Ribeiro", "mãe"), ("Carlos Eduardo Silva", "pai"),
        ("Mariana Oliveira", "responsável"), ("João Pereira", "avô"),
    ]
    rows, events = [], []
    dias = list(days_between())
    for _ in range(65):
        s = rng.choice(students)
        d = rng.choice(dias)
        h = rng.choice(["09:10","10:30","11:20","13:40","14:30","15:20","16:10"])
        motivo = rng.choice(motivos)
        resp, rel = rng.choice(responsaveis)
        status = rng.choices(
            ["finalizada","autorizada","pendente","rejeitada","revogada"],
            weights=[48,20,15,9,8], k=1
        )[0]
        criado = datetime.combine(d, datetime.strptime("07:45","%H:%M").time())
        autorizado = criado + timedelta(minutes=rng.randint(5,120))
        rows.append({
            "aluno_id":s["id"], "aluno_nome":s["nome"], "aluno_turma":s["turma"],
            "data":d.isoformat(), "horario_previsto":h, "motivo":motivo,
            "observacao":"Registro de demonstração do fluxo de saída.",
            "responsavel_nome":resp, "responsavel_relacao":rel, "origem":"secretaria",
            "solicitante":"Ana Paula Ribeiro", "requer_coordenacao":motivo in ("atividade externa","outro"),
            "status":status,
            "autorizado_por":"Daniela Cristina Barbosa" if status in ("finalizada","autorizada") else None,
            "autorizado_em":autorizado.isoformat() if status in ("finalizada","autorizada") else None,
            "motivo_rejeicao":"Documentação incompleta." if status=="rejeitada" else None,
            "motivo_revogacao":"Solicitação cancelada pela coordenação." if status=="revogada" else None,
            "revogado_por":"Daniela Cristina Barbosa" if status=="revogada" else None,
            "revogado_em":(autorizado + timedelta(minutes=40)).isoformat() if status=="revogada" else None,
            "saida_registrada_em":(autorizado + timedelta(minutes=rng.randint(20,180))).isoformat() if status=="finalizada" else None,
            "saida_registrada_por":"José Roberto Lima" if status=="finalizada" else None,
            "criado_em":criado.isoformat(),
        })
    n = batch_replace(data_dir, "saidas_autorizacoes", rows)
    auths = table_rows(data_dir, "saidas_autorizacoes")["registros"]
    for a in auths:
        eventos = [("criada", None, "pendente", "Solicitação criada.")]
        if a["status"] == "finalizada":
            eventos += [("autorizada","pendente","autorizada","Autorizada pela coordenação."),
                        ("saida_registrada","autorizada","finalizada","Saída registrada na portaria.")]
        elif a["status"] == "autorizada":
            eventos += [("autorizada","pendente","autorizada","Autorizada; aguardando registro de saída.")]
        elif a["status"] == "rejeitada":
            eventos += [("rejeitada","pendente","rejeitada","Solicitação rejeitada.")]
        elif a["status"] == "revogada":
            eventos += [("autorizada","pendente","autorizada","Autorização concedida."),
                        ("revogada","autorizada","revogada","Autorização revogada.")]
        for typ, prev, new, detail in eventos:
            events.append({"autorizacao_id":a["id"],"tipo":typ,"autor":"Daniela Cristina Barbosa" if typ!="criada" else "Ana Paula Ribeiro",
                           "estado_anterior":prev,"estado_novo":new,"detalhe":detail,"criado_em":a["criado_em"]})
    ne = batch_replace(data_dir, "saidas_eventos", events)
    return n, ne

def generate_visitantes(data_dir, rng):
    ensure_extra_tables(data_dir)
    nomes = [
        "Ricardo Mendes","Paulo Henrique Souza","Márcia Cristina Lima","Roberto Almeida",
        "Aline Carvalho","Juliana Santos","Eduardo Ferreira","Camila Rocha",
        "Marcelo Nunes","Patrícia Gomes","Anderson Bezerra","Carolina Freitas",
    ]
    destinos = ["Secretaria","Coordenação","Sala dos Professores","Laboratório de Redes","Direção"]
    motivos = ["Reunião","Entrega de documentação","Atendimento","Manutenção","Visita agendada"]
    dias = list(days_between())
    rows, events = [], []
    for _ in range(75):
        d = rng.choice(dias)
        entrada = datetime.combine(d, datetime.strptime(rng.choice(["07:45","08:20","09:10","10:30","13:20","14:40","15:30"]), "%H:%M").time())
        no_campus = rng.random() < 0.16
        saida = None if no_campus else entrada + timedelta(minutes=rng.randint(20,240))
        rows.append({
            "visitante_nome":rng.choice(nomes), "visitante_documento":f"***.***.***-{rng.randint(10,99)}",
            "destino":rng.choice(destinos), "motivo":rng.choice(motivos), "motivo_detalhe":"",
            "observacao":"Registro de visitante de demonstração.",
            "status":"no_campus" if no_campus else "finalizada", "entrada_em":entrada.isoformat(),
            "saida_em":saida.isoformat() if saida else None, "registrado_por":"José Roberto Lima",
            "saida_registrada_por":"José Roberto Lima" if saida else None, "criado_em":entrada.isoformat(),
        })
    n = batch_replace(data_dir, "visitantes_visitas", rows)
    visitas = table_rows(data_dir, "visitantes_visitas")["registros"]
    for v in visitas:
        events.append({"visita_id":v["id"],"tipo":"entrada","autor":"José Roberto Lima",
                       "detalhe":"Entrada registrada na portaria." ,"criado_em":v["entrada_em"]})
        if v["saida_em"]:
            events.append({"visita_id":v["id"],"tipo":"saida","autor":"José Roberto Lima",
                           "detalhe":"Saída registrada.","criado_em":v["saida_em"]})
    ne = batch_replace(data_dir, "visitantes_eventos", events)
    return n, ne

def generate_chamados(data_dir, rng):
    rows = []
    categorias = ["computador","rede","software","audio_video","outro"]
    prioridades = ["baixa","media","alta"]
    statuses = ["aberto","em_atendimento","resolvido","cancelado"]
    tech = "Aluno TI — Suporte"
    professores = [(u["id"],u["nome"]) for u in table_rows(data_dir,"usuarios")["registros"] if u.get("perfil")=="professor"]
    for i in range(55):
        aberto_id, aberto_nome = rng.choice(professores) if professores else (1,"Professor Demo")
        status = rng.choices(statuses, weights=[20,18,50,12], k=1)[0]
        d = rng.choice(list(days_between()))
        aberto = datetime.combine(d, datetime.strptime(rng.choice(["08:00","09:15","10:40","13:30","15:00"]),"%H:%M").time())
        categoria = rng.choice(categorias)
        titulo = {
            "computador":"Computador não inicia", "rede":"Sem acesso à rede",
            "software":"Sistema/aplicativo com erro", "audio_video":"Projetor sem imagem",
            "outro":"Solicitação de suporte técnico"
        }[categoria]
        rows.append({
            "titulo":titulo, "descricao":"Chamado de demonstração para validar o fluxo de suporte.",
            "categoria":categoria, "local":rng.choice(KEY_LOCATIONS), "prioridade":rng.choice(prioridades),
            "status":status, "aberto_por_id":aberto_id, "aberto_por_nome":aberto_nome,
            "aberto_em":aberto.isoformat(), "atribuido_a_id":999 if status in ("em_atendimento","resolvido") else None,
            "atribuido_a_nome":tech if status in ("em_atendimento","resolvido") else None,
            "assumido_em":(aberto+timedelta(minutes=rng.randint(10,180))).isoformat() if status in ("em_atendimento","resolvido") else None,
            "resolucao":"Ajuste realizado e equipamento testado." if status=="resolvido" else None,
            "resolvido_em":(aberto+timedelta(hours=rng.randint(1,48))).isoformat() if status=="resolvido" else None,
            "cancelado_em":(aberto+timedelta(hours=2)).isoformat() if status=="cancelado" else None,
            "motivo_cancelamento":"Chamado aberto em duplicidade." if status=="cancelado" else None,
        })
    return batch_replace(data_dir,"chamados",rows)

def generate_iot(data_dir, rng):
    sensors = ["bebedouro_1","bebedouro_2","cisterna"]
    rows = []
    # Histórico de leituras de água: suficiente para gráficos e alertas.
    for sensor in sensors:
        base = {"bebedouro_1":55,"bebedouro_2":68,"cisterna":74}[sensor]
        for d in list(days_between())[::2]:
            for h in (8,11,14,17):
                value = max(5, min(95, base + rng.uniform(-18,18)))
                rows.append({"sensor_id":sensor,"tipo":"nivel_agua","valor":round(value,1),
                             "data_hora":datetime(d.year,d.month,d.day,h,0).isoformat()})
    # Estados recentes de portões e ar-condicionado.
    for d in list(days_between())[-30:]:
        for h in (7,12,18):
            rows.append({"sensor_id":"portao_principal","tipo":"portao_status",
                         "valor":1 if h in (7,12) else 0,
                         "data_hora":datetime(d.year,d.month,d.day,h,0).isoformat()})
            rows.append({"sensor_id":"portao_secundario","tipo":"portao_status",
                         "valor":1 if h == 7 else 0,
                         "data_hora":datetime(d.year,d.month,d.day,h,5).isoformat()})
            rows.append({"sensor_id":"ar_condicionado","tipo":"ac_status",
                         "valor":1 if h in (7,12) else 0,
                         "data_hora":datetime(d.year,d.month,d.day,h,10).isoformat()})
    return batch_replace(data_dir,"leituras_iot",rows)

def generate_all_active_module_data(base: Path, data_dir: Path, students, professors, rng):
    """Gera dados para todos os módulos que possuem persistência SCEDS."""
    cfg = load_json(base / "core" / "config.json", {})
    ativos = set(cfg.get("modulos_ativos", []))
    counts = {}

    # A instalação demonstrativa é completa: mesmo que um módulo não esteja
    # no pacote atual, seus dados ficam prontos no SCEDS para que a equipe
    # possa habilitá-lo/testá-lo sem precisar criar uma massa manualmente.
    counts["saidas_autorizacoes"], counts["saidas_eventos"] = generate_saidas(data_dir, students, rng)
    counts["visitantes_visitas"], counts["visitantes_eventos"] = generate_visitantes(data_dir, rng)
    counts["chamados"] = generate_chamados(data_dir, rng)
    counts["leituras_iot"] = generate_iot(data_dir, rng)
    return counts

def main(base: Path | None = None, forcar: bool = False):
    rng = random.Random()  # intencionalmente sem seed.
    base = Path(base).resolve() if base is not None else localizar_base()
    data_dir = base / "sceds" / "data"
    log(f"Instalação encontrada: {base}")

    # --------------------------------------------------------------
    # Trava de segurança: este script APAGA e recria alunos, ocorrências,
    # empréstimos etc. Rodar isso sem querer numa instalação com licença
    # ativa (ou seja, um cliente real) destruiria dados de uma escola de
    # verdade. Por isso, se houver um arquivo de licença presente — ativa
    # ou não — o script se recusa a continuar a menos que seja chamado
    # explicitamente com --confirmo-apagar-dados-reais.
    # --------------------------------------------------------------
    caminho_licenca = base / "licenca.smc"
    if caminho_licenca.exists() and not forcar:
        raise RuntimeError(
            "Foi encontrado um arquivo de licença nesta instalação "
            f"({caminho_licenca}), o que indica que esta pode ser uma "
            "instalação de um CLIENTE REAL, não um ambiente de demonstração. "
            "Este script apaga e recria dados de alunos, ocorrências, "
            "empréstimos e outros — rodar isso aqui destruiria dados reais. "
            "Se você tem certeza absoluta de que quer prosseguir mesmo assim "
            "(ex.: ambiente de homologação com uma licença de teste), rode "
            "novamente com a flag --confirmo-apagar-dados-reais."
        )

    required = ["alunos","usuarios","livros","emprestimos","ocorrencias","evasao_frequencia",
                "reservas","chaves","chaves_movimentos","compromissos","mensagens_chat"]
    missing = [t for t in required if not (data_dir / f"{t}.sceds").exists()]
    if missing:
        raise RuntimeError("A instalação não possui as tabelas SCEDS necessárias: " + ", ".join(missing))

    # Evita duplicação ao executar novamente: dados de demonstração são reconstruídos.
    # "usuarios" fica de fora deste laço de propósito: generate_users(), logo abaixo,
    # já lê o conteúdo atual da tabela para preservar os administradores criados
    # pelo wizard antes de recriar o resto — mas só funciona se a tabela ainda tiver
    # esse conteúdo quando ela lê. Limpar "usuarios" aqui primeiro apagaria o admin
    # antes de generate_users() ter a chance de preservá-lo.
    for table in [t for t in required if t != "usuarios"]:
        clear_table(data_dir, table)
    ensure_pontualidade_table(data_dir)
    clear_table(data_dir, "entradas_pontualidade")

    ensure_columns(data_dir, "alunos", [
        {"nome":"matricula","tipo":"TEXTO","modificadores":[]},
        {"nome":"status","tipo":"TEXTO","modificadores":[]},
    ])
    students = make_students(rng)
    profiles_map = profiles(rng, students)
    # Ordena por turma/nome apenas no fim; ids são a referência estável entre tabelas.
    n_students = batch_replace(data_dir, "alunos", students)
    students = table_rows(data_dir, "alunos")["registros"]

    generate_users(data_dir, "")
    _, professors = user_maps(data_dir)
    log(f"Alunos: {n_students} | Professores: {len(professors)}")

    n_books = generate_books(data_dir, rng)
    n_loans = generate_loans(data_dir, students, profiles_map, rng)
    n_occ = generate_occurrences(data_dir, students, profiles_map, rng)
    n_freq = generate_evasao(data_dir, students, profiles_map, rng)
    n_pont = generate_punctuality(data_dir, students, profiles_map, rng)
    n_res = generate_reservations(data_dir, professors, rng)
    n_keys, n_moves = generate_keys(data_dir, professors, rng)
    n_comp, n_chat = generate_secretaria(data_dir, rng)
    n_extra = generate_all_active_module_data(base, data_dir, students, professors, rng)
    update_resources(base)

    # Relatório para conferência humana.
    counts = {}
    for table in required + ["entradas_pontualidade"] + list(n_extra.keys()):
        counts[table] = len(table_rows(data_dir, table)["registros"])
    report = {
        "gerado_em": datetime.now().isoformat(),
        "periodo": {"inicio": START.isoformat(), "fim": END.isoformat()},
        "instituicao": "Escola Técnica Estadual Professor Lucilo Ávila Pessoa (ETEPLAP)",
        "sem_seed": True,
        "perfil": "medio",
        "modulos": [
            "alunos","pontualidade","agendamento","biblioteca","secretaria_portaria",
            "ocorrencias","evasao","chaves","monitoramento","chamados","iot",
            "saidas","visitantes","sinal"
        ],
        "contagens": counts,
        "observacao": "Os dados foram reconstruídos com relações entre alunos, frequência, pontualidade, ocorrências, biblioteca, reservas, chaves e secretaria.",
    }
    save_json(base / "mock_data_report.json", report)
    save_json(base / "sceds" / "manifest.json", {
        "sistema": "SmartCampus",
        "tipo": "dados locais SCEDS",
        "gerado_por": "gerar_mock_data.py",
        "gerado_em": report["gerado_em"],
        "periodo_demo": report["periodo"],
        "tabelas": counts,
        "observacao": "Arquivo de controle da inicialização local. Não contém credenciais.",
    })

    log("Mock data gerado com sucesso.")
    for k, v in counts.items():
        log(f"  {k}: {v}")
    log(f"Relatório: {base / 'mock_data_report.json'}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gerador de dados de demonstração do SmartCampus")
    parser.add_argument(
        "--confirmo-apagar-dados-reais",
        action="store_true",
        dest="forcar",
        help="Necessário apenas se a instalação já tiver um arquivo de licença "
             "(licenca.smc) presente — sinal de que pode ser uma instalação real.",
    )
    args = parser.parse_args()

    try:
        main(forcar=args.forcar)
    except KeyboardInterrupt:
        print("\nOperação cancelada.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
