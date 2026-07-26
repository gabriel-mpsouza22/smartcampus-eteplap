
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJETO = BASE.parent.parent

def carregar_turmas_validas() -> set[str]:
    with open(BASE / "turmas.json", encoding="utf-8") as f:
        return {t["turma"] for t in json.load(f)["turmas"]}

def main():
    sys.path.insert(0, str(PROJETO))
    from sceds import SCEDS

    cfg = json.load(open(PROJETO / "core" / "config.json", encoding="utf-8"))
    db = SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

    turmas_validas = carregar_turmas_validas()
    alunos = db.buscar("alunos_ocorrencias")

    print(f"\nTotal de alunos cadastrados: {len(alunos)}")
    print(f"Turmas válidas no novo padrão: {len(turmas_validas)}\n")

    fora_do_padrao = [a for a in alunos if a.get("turma") not in turmas_validas]

    if not fora_do_padrao:
        print("✓ Todos os alunos já estão com turmas dentro do novo padrão. Nada a fazer!\n")
        return

    print(f"⚠ {len(fora_do_padrao)} aluno(s) com turma fora do padrão novo:\n")
    print(f"{'ID':<5} {'Nome':<30} {'Turma atual (antiga)':<25} {'Curso atual':<15}")
    print("-" * 78)
    for a in fora_do_padrao:
        print(f"{a['id']:<5} {a['nome']:<30} {a.get('turma',''):<25} {a.get('curso',''):<15}")

    print("""
Para corrigir, você tem duas opções:

  1. Pelo próprio sistema: abra o painel de Ocorrências, cadastre o aluno
     novamente com a turma correta (ele passa a ter um novo ID), e depois
     remova o cadastro antigo pela Administração > Usuários (perfil admin).

  2. Diretamente no banco: edite o arquivo
     sceds/data/alunos_ocorrencias.sceds
     e corrija manualmente os campos "turma", "serie" e "curso" de cada
     aluno listado acima, usando exatamente os valores do arquivo
     modulos/ocorrencias/turmas.json (respeitando maiúsculas/minúsculas).
""")

if __name__ == "__main__":
    main()
