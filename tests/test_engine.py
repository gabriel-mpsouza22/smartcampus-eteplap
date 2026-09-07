"""
Testes do motor de dados (sceds/engine.py).

Foco: as duas garantias que a auditoria de prontidão comercial apontou
como críticas — escrita atômica (sobrevivência a interrupção no meio de
uma escrita) e comportamento correto de CRUD básico. Não é uma suíte
exaustiva de todo o SCEDS, é a rede de segurança mínima para não
regredir os dois pontos que já causaram um achado CRÍTICO na auditoria.
"""
import json
import os

import pytest


def _colunas_basicas():
    return [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome", "tipo": "TEXTO"},
    ]


def test_inserir_e_buscar(engine):
    engine.criar_tabela("t", _colunas_basicas())
    reg = engine.inserir("t", {"nome": "Ana"})
    assert reg["id"] == 1
    assert engine.buscar("t") == [{"nome": "Ana", "id": 1}]


def test_dados_gravados_em_disco_sao_cifrados(engine):
    """
    Garantia central da criptografia em repouso: o arquivo .sceds no
    disco não deve conter o texto puro dos dados gravados.
    """
    engine.criar_tabela("t", _colunas_basicas())
    engine.inserir("t", {"nome": "Segredo Identificavel"})

    conteudo = engine._caminho_tabela("t").read_bytes()
    assert b"Segredo Identificavel" not in conteudo


def test_migra_tabela_legada_em_texto_puro_automaticamente(engine, pasta_tmp):
    """
    Uma tabela criada por uma versão anterior (texto puro, sem
    criptografia) deve continuar sendo lida corretamente, e ser
    re-gravada automaticamente em formato cifrado no processo — sem
    exigir nenhum script de migração manual.
    """
    import json as _json

    engine.criar_tabela("t", _colunas_basicas())
    caminho_tabela = engine._caminho_tabela("t")

    # Simula uma tabela antiga: sobrescreve com JSON puro (formato
    # usado antes desta mudança), sem passar pelo _salvar cifrado.
    dados_legado = {"registros": [{"id": 1, "nome": "Ana Legado"}], "proximo_id": 2}
    caminho_tabela.write_bytes(_json.dumps(dados_legado, ensure_ascii=False).encode("utf-8"))

    # Leitura normal via API pública deve funcionar e disparar a migração.
    registros = engine.buscar("t")
    assert registros == [{"id": 1, "nome": "Ana Legado"}]

    # Depois da leitura, o arquivo em disco já deve estar cifrado.
    conteudo_apos = caminho_tabela.read_bytes()
    assert b"Ana Legado" not in conteudo_apos


def test_tabela_adulterada_e_rejeitada_com_erro_claro(engine):
    """
    Um arquivo .sceds cifrado com 1 bit invertido (adulteração ou
    corrupção de disco) deve ser detectado pela autenticação do Fernet
    e rejeitado com um ValueError claro — nunca lido como se fosse
    dado válido, e nunca vazando um tipo de exceção interno confuso
    (ex.: UnicodeDecodeError) para quem chama.
    """
    engine.criar_tabela("t", _colunas_basicas())
    engine.inserir("t", {"nome": "Confidencial"})

    caminho = engine._caminho_tabela("t")
    bruto = bytearray(caminho.read_bytes())
    bruto[10] ^= 0xFF
    caminho.write_bytes(bytes(bruto))

    with pytest.raises(ValueError):
        engine.buscar("t")


def test_locks_sao_compartilhados_entre_instancias_da_mesma_tabela(pasta_tmp):
    """
    Duas instâncias de SCEDSEngine apontando para a MESMA pasta de
    dados (o padrão real de uso: core/auth.py cria uma instância nova
    a cada chamada via _get_db()) precisam disputar o MESMO lock por
    tabela — caso contrário, a exclusão mútua declarada pelo motor é
    apenas aparente entre requisições concorrentes (achado de pentest,
    corrigido: os locks passaram a viver num registro de nível de
    módulo, chaveado pelo caminho físico do arquivo).
    """
    from sceds.engine import SCEDSEngine

    caminho_dados = pasta_tmp / "dados"
    e1 = SCEDSEngine(caminho_dados)
    e2 = SCEDSEngine(caminho_dados)
    e1.criar_tabela("t", _colunas_basicas())

    assert e1._lock("t") is e2._lock("t")


def test_criacao_concorrente_de_usuario_nao_permite_senha_duplicada(pasta_tmp):
    """
    Reprodução do achado de pentest: N threads tentando criar um
    usuário com a MESMA senha ao mesmo tempo (ex.: dois administradores
    cadastrando contas simultaneamente) devem resultar em exatamente 1
    sucesso — nunca mais que isso, e sem nenhuma exceção inesperada de
    corrupção de arquivo (a versão anterior, sem lock compartilhado
    entre instâncias e sem checagem atômica, permitia N sucessos).
    """
    import threading
    import core.auth as auth
    from sceds import SCEDS

    caminho_dados = pasta_tmp / "dados"
    db_setup = SCEDS(caminho_dados)
    db_setup.criar_tabela("usuarios", [
        {"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
        {"nome": "nome", "tipo": "TEXTO"},
        {"nome": "perfil", "tipo": "TEXTO"},
        {"nome": "senha_hash", "tipo": "TEXTO"},
        {"nome": "ativo", "tipo": "BOOLEANO"},
        {"nome": "criado_em", "tipo": "TEXTO"},
    ])

    original_get_db = auth._get_db
    auth._get_db = lambda: SCEDS(caminho_dados)
    try:
        N = 10
        resultados, erros, excecoes = [], [], []
        barreira = threading.Barrier(N)

        def tentar_criar(i):
            barreira.wait()
            try:
                resultados.append(auth.criar_usuario(f"Usuario {i}", "professor", "SenhaColidida123"))
            except ValueError as e:
                erros.append(str(e))
            except Exception as e:
                excecoes.append(e)

        threads = [threading.Thread(target=tentar_criar, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert excecoes == []
        assert len(resultados) == 1
        assert len(erros) == N - 1
        assert db_setup.contar("usuarios") == 1
    finally:
        auth._get_db = original_get_db


def test_atualizar(engine):
    engine.criar_tabela("t", _colunas_basicas())
    reg = engine.inserir("t", {"nome": "Ana"})
    engine.atualizar("t", {"nome": "Ana Atualizada"}, onde={"id": reg["id"]})
    assert engine.buscar("t")[0]["nome"] == "Ana Atualizada"


def test_escrita_nao_deixa_arquivo_temporario_orfao(engine, pasta_tmp):
    """
    A garantia central da correção de atomicidade: depois de qualquer
    operação de escrita bem-sucedida, não pode sobrar nenhum arquivo
    .tmp* na pasta de dados.
    """
    engine.criar_tabela("t", _colunas_basicas())
    engine.inserir("t", {"nome": "Ana"})
    engine.atualizar("t", {"nome": "Ana2"}, onde={"id": 1})

    pasta_dados = pasta_tmp / "dados"
    orfaos = [f for f in os.listdir(pasta_dados) if ".tmp" in f]
    assert orfaos == []


def test_arquivo_antigo_permanece_intacto_se_escrita_falhar(engine, pasta_tmp, monkeypatch):
    """
    Simula uma falha durante a escrita (ex.: disco cheio, processo morto
    no meio do fsync) e confirma que o arquivo de dados ORIGINAL continua
    válido e legível — a garantia real da escrita atômica: uma escrita
    que falha não pode deixar a tabela pior do que estava antes dela.
    """
    engine.criar_tabela("t", _colunas_basicas())
    engine.inserir("t", {"nome": "Ana"})

    caminho_tabela = engine._caminho_tabela("t")
    conteudo_antes = caminho_tabela.read_bytes()

    def fsync_que_falha(*args, **kwargs):
        raise OSError("Disco cheio (simulado)")

    monkeypatch.setattr(os, "fsync", fsync_que_falha)

    with pytest.raises(OSError):
        engine.inserir("t", {"nome": "Beatriz"})

    # o arquivo real não deve ter sido tocado — a escrita falhou ANTES do
    # os.replace, então o conteúdo antigo precisa estar 100% intacto.
    assert caminho_tabela.read_bytes() == conteudo_antes
    # os dados em disco são cifrados (ver sceds/crypto.py); a garantia de
    # integridade agora é verificada decifrando o conteúdo, não lendo-o
    # como JSON puro.
    from sceds.crypto import decifrar_ou_legado
    dados_decifrados, era_texto_puro = decifrar_ou_legado(conteudo_antes, engine._chave)
    assert not era_texto_puro
    assert dados_decifrados["registros"][0]["nome"] == "Ana"

    # e nenhum .tmp deve ter sobrado
    pasta_dados = pasta_tmp / "dados"
    orfaos = [f for f in os.listdir(pasta_dados) if ".tmp" in f]
    assert orfaos == []


def test_deletar(engine):
    engine.criar_tabela("t", _colunas_basicas())
    engine.inserir("t", {"nome": "Ana"})
    engine.deletar("t", onde={"id": 1})
    assert engine.buscar("t") == []
