"""
Certificado TLS autoassinado para instalações locais do SmartCampus.

Contexto: cada escola roda uma instância local (appliance), acessada por
IP da rede interna (ex. 192.168.x.x) ou localhost — não por um domínio
público. Isso significa que NÃO é possível obter um certificado de uma
autoridade certificadora pública (Let's Encrypt e similares exigem um
domínio publicamente resolvível e validável). A alternativa correta para
esse cenário é um certificado autoassinado gerado localmente na primeira
execução — o navegador vai mostrar um aviso de "conexão não confiável"
na primeira visita em cada dispositivo, o que é esperado e deve ser
documentado para o cliente, não é um bug.

O que isso resolve mesmo sendo autoassinado: criptografa o tráfego na
rede local (impede sniffing de sessão/senha/token de IoT numa rede Wi-Fi
compartilhada da escola). O que NÃO resolve: identidade verificável do
servidor perante um atacante que já esteja em posição de MITM ativo
(cenário de risco mais raro numa rede escolar do que sniffing passivo).

Uso: `obter_contexto_ssl(pasta_dados)` retorna o par (cert, key) pronto
para `app.run(ssl_context=...)`, gerando o certificado na primeira
chamada se ainda não existir, e reaproveitando-o nas execuções seguintes.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("smartcampus.tls")

VALIDADE_DIAS = 3650  # 10 anos — appliance local, sem processo de renovação automatizado


def _nomes_alternativos(hostname_extra: str | None = None) -> list:
    """Monta a lista de SANs (Subject Alternative Names): localhost, o
    hostname real da máquina e, se descobrível, o IP da rede local —
    para o certificado ser aceito tanto em 'localhost' quanto no IP que
    os outros computadores da escola realmente usam para acessar."""
    from cryptography.x509.oid import NameOID
    from cryptography import x509

    nomes = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]

    try:
        hostname = socket.gethostname()
        if hostname:
            nomes.append(x509.DNSName(hostname))
    except OSError:
        pass

    try:
        # Truque padrão para descobrir o IP de saída da máquina na rede
        # local sem precisar de nenhuma requisição de rede real.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
        nomes.append(x509.IPAddress(ipaddress.ip_address(ip_local)))
    except OSError:
        pass

    if hostname_extra:
        try:
            nomes.append(x509.IPAddress(ipaddress.ip_address(hostname_extra)))
        except ValueError:
            nomes.append(x509.DNSName(hostname_extra))

    # remove duplicatas mantendo ordem
    vistos, unicos = set(), []
    for n in nomes:
        chave = str(n)
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(n)
    return unicos


def _gerar_certificado(caminho_cert: Path, caminho_key: Path, hostname_extra: str | None = None) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    chave_privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assunto = emissor = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SmartCampus"),
        x509.NameAttribute(NameOID.COMMON_NAME, "SmartCampus - Certificado Local"),
    ])

    agora = datetime.now(timezone.utc)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(assunto)
        .issuer_name(emissor)
        .public_key(chave_privada.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=VALIDADE_DIAS))
        .add_extension(x509.SubjectAlternativeName(_nomes_alternativos(hostname_extra)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(chave_privada, hashes.SHA256())
    )

    caminho_cert.parent.mkdir(parents=True, exist_ok=True)

    caminho_cert.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
    caminho_key.write_bytes(
        chave_privada.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    # A chave privada do certificado TLS não deve ser legível por outros
    # usuários do sistema operacional, na medida em que a plataforma
    # permitir (chmod é um no-op inofensivo no Windows via NTFS ACLs
    # padrão, mas tem efeito real em Linux/Mac caso a instalação rode lá).
    try:
        caminho_key.chmod(0o600)
    except OSError:
        pass

    logger.info(f"Certificado TLS autoassinado gerado: {caminho_cert} (válido {VALIDADE_DIAS} dias)")


def obter_contexto_ssl(pasta_dados: Path, hostname_extra: str | None = None) -> tuple[str, str]:
    """
    Garante que existe um certificado autoassinado válido em
    `pasta_dados/tls/` e retorna (caminho_cert, caminho_key) como
    strings, prontos para `app.run(ssl_context=(cert, key))`.

    Gera o certificado apenas se ainda não existir. Não renova
    automaticamente perto do vencimento (10 anos de validade torna isso
    desnecessário para o ciclo de vida esperado de uma instalação) —
    se algum dia for preciso forçar a regeração, basta apagar a pasta
    `tls/` e reiniciar o servidor.
    """
    pasta_tls = Path(pasta_dados) / "tls"
    caminho_cert = pasta_tls / "servidor.crt"
    caminho_key = pasta_tls / "servidor.key"

    if not caminho_cert.exists() or not caminho_key.exists():
        _gerar_certificado(caminho_cert, caminho_key, hostname_extra)

    return str(caminho_cert), str(caminho_key)
