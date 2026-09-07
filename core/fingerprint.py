"""
Geração do "código da máquina" (fingerprint de hardware) usado para
vincular uma licença a um computador específico.

Este módulo é compartilhado entre a ferramenta interna de emissão de
licenças (licenciamento/emitir_licenca.py) e o app do cliente
(core/licenca.py) — o fingerprint calculado aqui precisa ser
IDENTICO nos dois lados, senão nenhuma licença jamais vai validar.

Não existe fingerprint de hardware 100% à prova de falsificação em
software puro (sempre dá pra rodar em uma VM que finge os mesmos
identificadores). O objetivo aqui é impedir a cópia casual do .exe
para outro computador — não resistir a um atacante que está
deliberadamente tentando clonar hardware.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import uuid
from pathlib import Path


def _uuid_placa_mae_windows() -> str | None:
    """UUID da placa-mãe via WMIC (Windows). Mais estável que o MAC
    (sobrevive a troca de placa de rede, USB, etc.)."""
    if platform.system() != "Windows":
        return None
    try:
        saida = subprocess.check_output(
            ["wmic", "csproduct", "get", "uuid"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode(errors="ignore")
        linhas = [l.strip() for l in saida.splitlines() if l.strip()]
        if len(linhas) >= 2 and linhas[1] and "UUID" not in linhas[1].upper():
            return linhas[1]
    except Exception:
        pass
    # wmic foi removido a partir do Windows 11 24H2 — tenta o
    # equivalente via PowerShell antes de desistir.
    try:
        saida = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
            stderr=subprocess.DEVNULL, timeout=8,
        ).decode(errors="ignore").strip()
        if saida:
            return saida
    except Exception:
        pass
    return None


def _coletar_identificadores_brutos() -> bytes:
    identificadores = [
        _uuid_placa_mae_windows() or "",
        str(uuid.getnode()),          # endereço MAC (fallback multiplataforma)
        platform.node(),               # hostname
    ]
    return "|".join(identificadores).encode("utf-8")


def calcular_fingerprint(pasta_cache: "Path | None" = None) -> str:
    """
    Retorna um código estável de ~16 caracteres identificando esta
    máquina, no formato "XXXX-XXXX-XXXX-XXXX" (fácil de ler por
    telefone/e-mail para o suporte).

    Se `pasta_cache` for informada, os identificadores brutos coletados
    na primeira chamada são persistidos ali e reaproveitados depois —
    necessário porque, em algumas máquinas virtuais/contêineres sem MAC
    real exposto, `uuid.getnode()` pode retornar um valor ALEATÓRIO
    diferente a cada processo (comportamento documentado da biblioteca
    padrão do Python), o que invalidaria a licença de um cliente legítimo
    a cada reinício. Sem essa pasta, o cálculo é sempre feito na hora.
    """
    if pasta_cache is not None:
        cache_path = pasta_cache / ".fingerprint_raw"
        if cache_path.exists():
            base = cache_path.read_bytes()
        else:
            base = _coletar_identificadores_brutos()
            pasta_cache.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(base)
    else:
        base = _coletar_identificadores_brutos()

    digest = hashlib.sha256(base).hexdigest().upper()[:16]
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))
