
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJETO = BASE.parent.parent


def main():
    sys.path.insert(0, str(PROJETO))
    from sceds import SCEDS

    cfg = json.load(open(PROJETO / "core" / "config.json", encoding="utf-8"))
    db = SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

    with open(BASE / "turmas.json", encoding="utf-8") as f:
        turmas_validas = {t["turma"]: t for t in json.load(f)["turmas"]}

    alunos = db.buscar("alunos_ocorrencias")
    print(f"\nTotal de alunos cadastrados: {len(alunos)}\n")

    corrigidos = 0
    marcados_manual = 0

    for aluno in alunos:
        campos_faltando = [c for c in ("serie", "turma", "curso") if not aluno.get(c)]
        if not campos_faltando:
            continue

        nome = aluno.get("nome", f"(id {aluno['id']})")
        turma_atual = aluno.get("turma", "")
        info = turmas_validas.get(turma_atual)

        if info:
            novos_dados = {"serie": info["serie"], "turma": info["turma"], "curso": info["curso"]}
            db.atualizar("alunos_ocorrencias", novos_dados, onde={"id": aluno["id"]})
            print(f"  ✓ {nome}: completado automaticamente a partir da turma '{turma_atual}'")
            corrigidos += 1
        else:
            novos_dados = {}
            for c in ("serie", "turma", "curso"):
                if not aluno.get(c):
                    novos_dados[c] = "(a definir)"
            db.atualizar("alunos_ocorrencias", novos_dados, onde={"id": aluno["id"]})
            print(f"  ⚠ {nome}: campos {campos_faltando} preenchidos com '(a definir)' — "
                  f"corrija manualmente pelo cadastro de aluno.")
            marcados_manual += 1

    print(f"\nResumo: {corrigidos} corrigido(s) automaticamente, "
          f"{marcados_manual} marcado(s) para revisão manual.\n")

    if corrigidos == 0 and marcados_manual == 0:
        print("Nenhum problema encontrado — todos os alunos já estão completos!\n")


if __name__ == "__main__":
    main()
