"""
Criptografia em repouso dos arquivos de dados do SCEDS (*.sceds).

Contexto / o que isto resolve:
Antes desta mudança, cada tabela era gravada em texto puro (JSON) dentro
de sceds/data/*.sceds — auditoria de segurança apontou isso como um
achado CRÍTICO (LGPD art. 46 exige medida técnica adequada contra acesso
não autorizado a dado pessoal). Este módulo cifra o CONTEÚDO de cada
tabela com Fernet (AES-128-CBC + HMAC-SHA256, autenticado — qualquer
adulteração do arquivo é detectada na leitura, não passa silenciosamente).

O que isto NÃO resolve (documentado deliberadamente, mesmo espírito de
core/backup.py e core/tls.py): se o disco inteiro do servidor for
roubado, o invasor provavelmente também tem acesso ao arquivo de chave
(sceds/.chave_dados) que fica ao lado da pasta de dados — cenário de
disco físico comprometido continua exigindo criptografia de disco a
nível de SO (BitLocker/LUKS), fora do escopo de uma aplicação Python.
O que isto protege de verdade: cópias parciais dos arquivos de dados
saindo do lugar sem a chave junto — um backup .zip esquecido num
pendrive/e-mail, uma pasta compartilhada mal configurada, um técnico de
suporte remoto que só copiou sceds/data/ para analisar um problema, etc.
Nesses cenários (mais prováveis no dia a dia que o roubo do HD inteiro),
os arquivos .sceds sozinhos são inúteis sem a chave.

IMPORTANTE para quem for planejar recuperação de desastre: um backup
gerado por core/backup.py contém só sceds/data/ (os arquivos
*.sceds, já cifrados). Para restaurar em uma máquina NOVA (não a
mesma que gerou o backup), é preciso também copiar manualmente
sceds/.chave_dados — sem ela, o backup restaurado é ilegível (por
design: é exatamente essa separação que dá a proteção acima). Isso deve
constar no runbook de recuperação de desastre da equipe de suporte.

Formato do arquivo de chave (sceds/.chave_dados): 32 bytes aleatórios,
codificados em base64 urlsafe (formato que o Fernet exige), gerados na
primeira vez que qualquer tabela precisa ser lida ou escrita.

Migração automática e transparente: uma tabela .sceds já existente em
texto puro (instalações criadas antes desta mudança) é detectada na
leitura (não decifra / não é um token Fernet válido, mas é JSON válido)
e automaticamente re-gravada em formato cifrado no processo — não é
necessário nenhum script de migração manual, no mesmo espírito de
`adicionar_coluna_se_ausente` em engine.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def caminho_chave(caminho_dados: Path) -> Path:
    """
    A chave fica ao lado da pasta de dados (não dentro dela), justamente
    para não ser incluída sem querer em um backup que zipa só o conteúdo
    de sceds/data/ — ver docstring do módulo. Exposta (não prefixada com
    "_") porque core/backup.py precisa dela para restaurar corretamente
    uma instalação em uma máquina nova — ver `restaurar()` em
    core/backup.py e a seção sobre recuperação de desastre acima.
    """
    return Path(caminho_dados).resolve().parent / f".chave_{Path(caminho_dados).name}"


def carregar_ou_criar_chave(caminho_dados: Path) -> bytes:
    """
    Retorna a chave Fernet (bytes) desta instalação, gerando-a e
    persistindo-a na primeira chamada. Chamadas seguintes reaproveitam
    o mesmo arquivo — trocar a chave sem migrar os dados antigos torna
    todas as tabelas já cifradas ilegíveis (mesma natureza de risco que
    core/.secret_key ou licenciamento/chave_privada.pem).
    """
    caminho = caminho_chave(caminho_dados)
    if caminho.exists():
        return caminho.read_bytes()

    caminho.parent.mkdir(parents=True, exist_ok=True)
    chave = Fernet.generate_key()
    caminho.write_bytes(chave)
    try:
        # Melhor esforço, mesma justificativa de app.py:.secret_key —
        # restringe ao dono do arquivo. Não é uma segunda camada de
        # criptografia; é reduzir quem consegue nem tentar ler a chave.
        caminho.chmod(0o600)
    except OSError:
        pass
    return chave


def cifrar(dados: dict, chave: bytes) -> bytes:
    """Serializa `dados` em JSON e retorna o token Fernet (bytes) cifrado."""
    bruto = json.dumps(dados, ensure_ascii=False).encode("utf-8")
    return Fernet(chave).encrypt(bruto)


def decifrar_ou_legado(conteudo: bytes, chave: bytes) -> tuple[dict, bool]:
    """
    Tenta decifrar `conteudo` como um token Fernet. Se não for um token
    válido, assume que é uma tabela antiga em JSON puro (formato usado
    antes desta mudança) e retorna o conteúdo interpretado como JSON.

    Retorna (dados, era_texto_puro) — o chamador usa `era_texto_puro`
    para decidir se deve re-gravar a tabela já cifrada (migração).

    Levanta ValueError se o conteúdo não for nem um token Fernet válido
    nem JSON válido — arquivo genuinamente corrompido.
    """
    try:
        bruto = Fernet(chave).decrypt(conteudo)
        return json.loads(bruto), False
    except InvalidToken:
        try:
            return json.loads(conteudo), True
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(
                "Arquivo de dados corrompido: não é um token cifrado válido "
                "nem um JSON legado reconhecível."
            )
