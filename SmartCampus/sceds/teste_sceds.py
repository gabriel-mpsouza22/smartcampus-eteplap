
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sceds import SCEDS


def titulo(texto):
    print(f"\n{'='*50}")
    print(f"  {texto}")
    print(f"{'='*50}")


def ok(texto):
    print(f"  ✓ {texto}")


def falha(texto):
    print(f"  ✗ FALHA: {texto}")
    sys.exit(1)


def rodar_testes():
    pasta_teste = tempfile.mkdtemp(prefix="sceds_teste_")
    print(f"\nPasta de testes: {pasta_teste}")

    try:
        db = SCEDS(pasta_teste)

        titulo("1. CRIAR TABELA (via linguagem SCEDS)")
        db.executar("""
            CRIAR TABELA usuarios (
                id     INTEIRO CHAVE_PRIMARIA AUTO,
                nome   TEXTO   NAO_NULO,
                senha  TEXTO   NAO_NULO,
                perfil TEXTO   NAO_NULO,
                ativo  BOOLEANO
            )
        """)
        assert db.tabela_existe("usuarios"), "Tabela não foi criada"
        ok("Tabela 'usuarios' criada com sucesso")

        titulo("2. INSERIR EM (via linguagem SCEDS)")
        reg = db.executar("INSERIR EM usuarios (nome, senha, perfil, ativo) VALORES ('Lucas', 'hash123', 'professor', verdadeiro)")
        assert reg["id"] == 1, f"ID esperado 1, obteve {reg['id']}"
        assert reg["nome"] == "Lucas"
        ok(f"Inserido: {reg}")

        titulo("3. Inserir via atalho Python")
        db.inserir("usuarios", {"nome": "Ana", "senha": "hash456", "perfil": "bibliotecaria", "ativo": True})
        db.inserir("usuarios", {"nome": "João", "senha": "hash789", "perfil": "portaria", "ativo": False})
        ok("3 registros inseridos no total")

        titulo("4. BUSCAR * DE usuarios")
        todos = db.buscar("usuarios")
        assert len(todos) == 3, f"Esperado 3, obteve {len(todos)}"
        ok(f"Encontrados {len(todos)} registros")

        titulo("5. BUSCAR com ONDE (via linguagem)")
        profs = db.executar("BUSCAR * DE usuarios ONDE perfil = 'professor'")
        assert len(profs) == 1, f"Esperado 1 professor, obteve {len(profs)}"
        assert profs[0]["nome"] == "Lucas"
        ok(f"Filtro funciona: {profs[0]}")

        titulo("6. Buscar com filtro via atalho Python")
        ativos = db.buscar("usuarios", onde={"ativo": True})
        assert len(ativos) == 2, f"Esperado 2 ativos, obteve {len(ativos)}"
        ok(f"Encontrados {len(ativos)} usuários ativos")

        titulo("7. buscar_um")
        um = db.buscar_um("usuarios", onde={"id": 2})
        assert um is not None and um["nome"] == "Ana"
        ok(f"buscar_um: {um}")

        titulo("8. ATUALIZAR (via linguagem)")
        qtd = db.executar("ATUALIZAR usuarios DEFINIR ativo = falso ONDE id = 1")
        assert qtd == 1
        verificacao = db.buscar_um("usuarios", onde={"id": 1})
        assert verificacao["ativo"] == False
        ok(f"Atualizado: ativo de Lucas = {verificacao['ativo']}")

        titulo("9. Atualizar via atalho Python")
        db.atualizar("usuarios", {"ativo": True}, onde={"id": 3})
        joao = db.buscar_um("usuarios", onde={"id": 3})
        assert joao["ativo"] == True
        ok(f"João ativo agora: {joao['ativo']}")

        titulo("10. contar")
        total = db.contar("usuarios")
        ativos_count = db.contar("usuarios", onde={"ativo": True})
        ok(f"Total: {total} | Ativos: {ativos_count}")

        titulo("11. DELETAR DE (via linguagem)")
        removidos = db.executar("DELETAR DE usuarios ONDE id = 2")
        assert removidos == 1
        assert db.contar("usuarios") == 2
        ok(f"1 registro removido. Total agora: {db.contar('usuarios')}")

        titulo("12. Auto-incremento contínuo")
        novo = db.inserir("usuarios", {"nome": "Maria", "senha": "hash999", "perfil": "secretaria", "ativo": True})
        assert novo["id"] == 4, f"ID esperado 4 (sequencial), obteve {novo['id']}"
        ok(f"Novo registro com id={novo['id']} (correto, sequencial)")

        titulo("13. Backup da tabela")
        import tempfile as _tempfile
        pasta_backup = _tempfile.mkdtemp(prefix="sceds_backup_")
        arquivo_backup = db.backup_tabela("usuarios", pasta_backup)
        assert arquivo_backup.exists()
        ok(f"Backup salvo em: {arquivo_backup}")
        shutil.rmtree(pasta_backup)

        titulo("14. Listar tabelas")
        tabelas = db.listar_tabelas()
        assert "usuarios" in tabelas
        ok(f"Tabelas: {tabelas}")

        titulo("15. Erro em campo UNICO")
        db.executar("""
            CRIAR TABELA emails (
                id    INTEIRO CHAVE_PRIMARIA AUTO,
                email TEXTO   NAO_NULO UNICO
            )
        """)
        db.inserir("emails", {"email": "a@escola.com"})
        try:
            db.inserir("emails", {"email": "a@escola.com"})
            falha("Deveria ter levantado erro de duplicidade")
        except ValueError as e:
            ok(f"Erro de duplicidade corretamente detectado: {e}")

        print("\n" + "="*50)
        print("  TODOS OS TESTES PASSARAM ✓")
        print("="*50 + "\n")

    finally:
        shutil.rmtree(pasta_teste)


if __name__ == "__main__":
    rodar_testes()
