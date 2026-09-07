"""
Validação de licença no lado do cliente.

Este módulo só consegue VERIFICAR uma licença (usa a chave pública
Ed25519, embarcada em core/licenca_publica.pem) — ele não tem
nenhuma forma de emitir ou forjar uma licença nova, mesmo que o .exe
inteiro seja descompilado. Só quem tem chave_privada.pem (que nunca
sai do computador da equipe do Smart Campus) consegue gerar uma
licença que passe em `validar()`.
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from core.fingerprint import calcular_fingerprint

_BASE = Path(__file__).resolve().parent
_CAMINHO_CHAVE_PUBLICA = _BASE / "licenca_publica.pem"


class LicencaInvalida(Exception):
    """Levantada com uma mensagem já pronta para mostrar ao usuário final."""


def _carregar_chave_publica() -> Ed25519PublicKey:
    if not _CAMINHO_CHAVE_PUBLICA.exists():
        raise LicencaInvalida(
            "Este pacote de instalação está incompleto (chave de licença "
            "ausente). Contate o suporte técnico do Smart Campus."
        )
    return serialization.load_pem_public_key(_CAMINHO_CHAVE_PUBLICA.read_bytes())


def _ler_arquivo_licenca(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LicencaInvalida("SEM_LICENCA")
    except Exception as e:
        raise LicencaInvalida(f"Arquivo de licença corrompido ou ilegível ({e}).")


def validar(caminho_licenca: Path, pasta_cache: Path | None = None) -> dict:
    """
    Valida o arquivo de licença. Em caso de sucesso, retorna o payload
    (fingerprint, instituicao, emitido_em, validade). Em qualquer
    problema, levanta LicencaInvalida com uma mensagem adequada para
    exibir na tela — nunca detalhes técnicos de criptografia.

    `pasta_cache` deve ser a pasta de dados persistente da instalação —
    veja o motivo em core.fingerprint.calcular_fingerprint.
    """
    licenca = _ler_arquivo_licenca(caminho_licenca)

    try:
        payload_bytes = base64.b64decode(licenca["payload"])
        assinatura = base64.b64decode(licenca["assinatura"])
    except (KeyError, ValueError):
        raise LicencaInvalida("Arquivo de licença em formato inválido.")

    chave_publica = _carregar_chave_publica()
    try:
        chave_publica.verify(assinatura, payload_bytes)
    except InvalidSignature:
        raise LicencaInvalida(
            "Esta licença não é válida para este programa (assinatura não "
            "reconhecida). Ela pode ter sido alterada ou não foi emitida "
            "pelo Smart Campus."
        )

    payload = json.loads(payload_bytes)

    fingerprint_atual = calcular_fingerprint(pasta_cache)
    if payload.get("fingerprint", "").upper() != fingerprint_atual.upper():
        raise LicencaInvalida(
            "Esta licença pertence a outro computador. Se você trocou de "
            "máquina ou reinstalou o sistema operacional, contate o "
            "suporte informando o novo código da máquina."
        )

    validade = payload.get("validade")
    if validade:
        try:
            data_limite = datetime.strptime(validade, "%Y-%m-%d").date()
        except ValueError:
            raise LicencaInvalida("Data de validade da licença em formato inválido.")
        if date.today() > data_limite:
            raise LicencaInvalida(
                f"A licença deste sistema expirou em {data_limite.strftime('%d/%m/%Y')}. "
                "Contate o suporte para renovação."
            )

    return payload


def verificar_ou_none(caminho_licenca: Path, pasta_cache: Path | None = None) -> tuple[dict | None, str | None]:
    """
    Versão que nunca levanta exceção — retorna (payload, None) em caso
    de sucesso, ou (None, mensagem_amigavel) em caso de falha. Feita
    para ser chamada direto do launcher, antes de qualquer UI existir.
    """
    try:
        return validar(caminho_licenca, pasta_cache), None
    except LicencaInvalida as e:
        msg = str(e)
        if msg == "SEM_LICENCA":
            return None, "SEM_LICENCA"
        return None, msg
