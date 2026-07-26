
import sys
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJETO = BASE.parent.parent


def main():
    sys.path.insert(0, str(PROJETO))
    sys.path.insert(0, str(BASE))
    from sceds import SCEDS
    from api_ocorrencias import normalizar_tipo, TIPOS_MAP

    cfg = json.load(open(PROJETO / "core" / "config.json", encoding="utf-8"))
    db = SCEDS(Path(cfg["caminho_base"]) / "sceds" / "data")

    ocorrencias = db.buscar("ocorrencias")
    print(f"\nTotal de ocorrências no banco: {len(ocorrencias)}\n")

    corrigidas = 0
    nao_reconhecidas = 0

    for o in ocorrencias:
        tipo_bruto = o.get("tipo", "")
        tipo_normalizado = normalizar_tipo(tipo_bruto)

        if tipo_normalizado == tipo_bruto:
            continue

        if tipo_normalizado in TIPOS_MAP:
            db.atualizar("ocorrencias", {"tipo": tipo_normalizado}, onde={"numero": o["numero"]})
            print(f"  ✓ Ocorrência #{o['numero']}: '{tipo_bruto}' → '{tipo_normalizado}'")
            corrigidas += 1
        else:
            print(f"  ⚠ Ocorrência #{o['numero']}: tipo '{tipo_bruto}' não reconhecido — mantido como está")
            nao_reconhecidas += 1

    print(f"\nResumo: {corrigidas} ocorrência(s) corrigida(s), "
          f"{nao_reconhecidas} não reconhecida(s) (revisar manualmente se houver).\n")

    if corrigidas == 0 and nao_reconhecidas == 0:
        print("Nenhum problema encontrado — todos os tipos já estão no formato correto!\n")


if __name__ == "__main__":
    main()
