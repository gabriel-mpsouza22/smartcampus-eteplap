import os
import zipfile

import pytest

from core.backup import executar_backup, restaurar, _aplicar_retencao


def test_backup_completo_e_restore_na_mesma_instalacao(engine, pasta_tmp):
    """
    Caso comum: restaurar um backup antigo na MESMA instalação (a chave
    de criptografia, que fica ao lado da pasta de dados, não é tocada
    pelo restore e continua sendo a mesma) — não precisa informar
    `caminho_chave_origem`.
    """
    engine.criar_tabela("t", [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome", "tipo": "TEXTO"},
    ])
    engine.inserir("t", {"nome": "Ana"})

    pasta_dados = pasta_tmp / "dados"
    pasta_backups = pasta_tmp / "backups"

    zip_path = executar_backup(pasta_dados, pasta_backups)
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as zf:
        assert "t.sceds" in zf.namelist()

    # Restaura por cima da MESMA pasta de dados (cenário: "desfazer"
    # alterações recentes na própria instalação) — a chave ao lado dela
    # já existe e não precisa ser informada de novo.
    restaurar(zip_path, pasta_dados)

    from sceds.engine import SCEDSEngine
    e2 = SCEDSEngine(pasta_dados)
    assert e2.buscar("t") == [{"nome": "Ana", "id": 1}]


def test_restore_em_maquina_nova_exige_a_chave(engine, pasta_tmp):
    """
    Recuperação de desastre de verdade: pasta de dados nova, sem a
    chave que criptografou o backup original ao lado dela. Sem informar
    `caminho_chave_origem`, os dados restaurados devem ficar ilegíveis
    (comportamento esperado e documentado — não um bug).
    """
    from sceds.crypto import caminho_chave

    engine.criar_tabela("t", [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome", "tipo": "TEXTO"},
    ])
    engine.inserir("t", {"nome": "Ana"})

    pasta_dados = pasta_tmp / "dados"
    pasta_backups = pasta_tmp / "backups"
    zip_path = executar_backup(pasta_dados, pasta_backups)

    destino_sem_chave = pasta_tmp / "maquina_nova_sem_chave"
    restaurar(zip_path, destino_sem_chave)

    from sceds.engine import SCEDSEngine
    e_sem_chave = SCEDSEngine(destino_sem_chave)
    with pytest.raises(ValueError):
        e_sem_chave.buscar("t")

    # Com a chave original (recuperada de onde a equipe a guardou
    # separadamente, por exemplo um cofre de senhas) informada no
    # restore, os dados voltam a ser legíveis normalmente.
    destino_com_chave = pasta_tmp / "maquina_nova_com_chave"
    restaurar(zip_path, destino_com_chave, caminho_chave_origem=caminho_chave(pasta_dados))

    e_com_chave = SCEDSEngine(destino_com_chave)
    assert e_com_chave.buscar("t") == [{"nome": "Ana", "id": 1}]


def test_retencao_mantem_apenas_os_mais_recentes(pasta_tmp):
    pasta_backups = pasta_tmp / "backups"
    pasta_backups.mkdir()

    for i in range(5):
        (pasta_backups / f"backup_{i:03d}.zip").write_text("x")

    _aplicar_retencao(pasta_backups, retencao=2)

    restantes = sorted(os.listdir(pasta_backups))
    assert len(restantes) == 2
