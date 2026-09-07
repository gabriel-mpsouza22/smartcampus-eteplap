"""
Migração: cadastro único de alunos
------------------------------------
Rode este script UMA VEZ ao atualizar uma instalação existente do Smart
Campus para a versão com cadastro único de alunos.

O que ele faz:

  1. Se a tabela antiga 'alunos_ocorrencias' existir e a nova 'alunos'
     ainda não existir, copia todos os alunos para a tabela nova
     (mesmos IDs, para não quebrar o vínculo com as ocorrências) e
     renomeia o arquivo antigo para .bak.

  2. Nos empréstimos da Biblioteca já registrados (que guardavam só
     nome/turma/curso em texto livre, sem ligação com nenhum cadastro),
     tenta encontrar o aluno correspondente no cadastro único por nome
     e turma, e preenche o campo aluno_id — sem isso, empréstimos
     antigos continuam aparecendo normalmente, mas não contam nos
     números de "alunos cadastrados" nem no score de evasão.

Nada é apagado: qualquer coisa que não puder ser migrada automaticamente
fica registrada no resumo final para revisão manual.

Uso:
    python core/migrar_cadastro_unico.py
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJETO = BASE.parent


def main():
    sys.path.insert(0, str(PROJETO))
    from sceds import SCEDS

    cfg = json.load(open(PROJETO / "core" / "config.json", encoding="utf-8"))
    caminho_dados = Path(cfg["caminho_base"]) / "sceds" / "data"
    db = SCEDS(caminho_dados)

    print("\n=== Migração: cadastro único de alunos ===\n")

    # ── Etapa 1: migrar tabela alunos_ocorrencias → alunos ──────────────
    caminho_antigo = caminho_dados / "alunos_ocorrencias.sceds"
    caminho_antigo_schema = caminho_dados / "alunos_ocorrencias.schema.json"
    tabela_nova_existe = db.tabela_existe("alunos")

    if caminho_antigo.exists() and not tabela_nova_existe:
        print("Encontrada tabela antiga 'alunos_ocorrencias'. Migrando para 'alunos'...")

        db.criar_tabela("alunos", [
            {"nome": "id",    "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
            {"nome": "nome",  "tipo": "TEXTO",   "modificadores": ["NAO_NULO"]},
            {"nome": "serie", "tipo": "TEXTO",   "modificadores": []},
            {"nome": "turma", "tipo": "TEXTO",   "modificadores": []},
            {"nome": "curso", "tipo": "TEXTO",   "modificadores": []},
        ])

        # Os arquivos .sceds são cifrados em repouso (ver sceds/crypto.py) —
        # decifrar_ou_legado também aceita o formato antigo em texto puro,
        # então isto funciona tanto migrando de uma instalação bem antiga
        # (pré-criptografia) quanto de uma já cifrada.
        from sceds.crypto import carregar_ou_criar_chave, cifrar, decifrar_ou_legado
        chave = carregar_ou_criar_chave(caminho_dados)
        dados_antigos, _ = decifrar_ou_legado(caminho_antigo.read_bytes(), chave)

        # Grava direto no arquivo para preservar os IDs originais
        # (inserir() geraria novos IDs, quebrando o vínculo com ocorrências).
        caminho_novo = caminho_dados / "alunos.sceds"
        caminho_novo.write_bytes(cifrar(dados_antigos, chave))

        caminho_antigo.rename(caminho_dados / "alunos_ocorrencias.sceds.bak")
        if caminho_antigo_schema.exists():
            caminho_antigo_schema.rename(caminho_dados / "alunos_ocorrencias.schema.json.bak")

        print(f"  ✓ {len(dados_antigos.get('registros', []))} aluno(s) migrado(s) para a tabela 'alunos'.")
        print("  ✓ Arquivos antigos preservados com sufixo '.bak', por segurança.\n")
    elif tabela_nova_existe:
        print("Tabela 'alunos' já existe — nada a migrar nesta etapa.\n")
    else:
        print("Nenhuma tabela antiga encontrada — instalação nova, nada a migrar nesta etapa.\n")

    if not db.tabela_existe("alunos"):
        print("⚠ Tabela 'alunos' não existe e não havia dados antigos para migrar.")
        print("  Rode o instalador (instalar.py) para criá-la vazia, ou cadastre um aluno")
        print("  pela interface (Ocorrências ou Biblioteca) para que ela seja criada.\n")
        return

    # ── Etapa 2: religar empréstimos antigos ao cadastro único ──────────
    if not db.tabela_existe("emprestimos"):
        print("Tabela 'emprestimos' não encontrada — pulando etapa de religação.\n")
        return

    print("Religando empréstimos antigos da Biblioteca ao cadastro único...")

    alunos = db.buscar("alunos")
    indice = {}
    for a in alunos:
        chave = (a.get("nome", "").strip().lower(), a.get("turma", "").strip().lower())
        indice[chave] = a["id"]

    emprestimos = db.buscar("emprestimos")
    religados = 0
    sem_correspondencia = []

    for e in emprestimos:
        if e.get("aluno_id"):
            continue  # já migrado / já criado pelo fluxo novo

        chave = (e.get("aluno_nome", "").strip().lower(), e.get("aluno_turma", "").strip().lower())
        aluno_id = indice.get(chave)

        if aluno_id:
            db.atualizar("emprestimos", {"aluno_id": aluno_id}, onde={"id": e["id"]})
            religados += 1
        else:
            sem_correspondencia.append(e)

    print(f"  ✓ {religados} empréstimo(s) religado(s) automaticamente ao cadastro único.")

    if sem_correspondencia:
        print(f"\n  ⚠ {len(sem_correspondencia)} empréstimo(s) sem correspondência exata "
              f"de nome+turma no cadastro único:\n")
        for e in sem_correspondencia[:20]:
            print(f"     - {e.get('aluno_nome','?')} ({e.get('aluno_turma','?')}) "
                  f"— empréstimo #{e['id']}")
        if len(sem_correspondencia) > 20:
            print(f"     ... e mais {len(sem_correspondencia) - 20}.")
        print("\n    Esses empréstimos continuam funcionando normalmente (mostram o nome")
        print("    salvo na época), mas não contam para o cadastro único nem para o score")
        print("    de evasão até que o aluno correspondente seja cadastrado e o empréstimo")
        print("    seja recriado, ou corrigido manualmente no arquivo emprestimos.sceds.")
    else:
        print("  ✓ Todos os empréstimos já estão ligados ao cadastro único.")

    print("\n=== Migração concluída ===\n")


if __name__ == "__main__":
    main()
