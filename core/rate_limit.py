"""
Proteção simples contra força bruta no login.

O Smart Campus roda como processo único (Flask embutido + webview),
então um contador em memória, protegido por lock, é suficiente — não
precisa de Redis nem de tabela no SCEDS para isso. O estado não
sobrevive a um restart do processo, o que é aceitável: um restart do
aplicativo já é uma barreira física considerável para quem está
tentando adivinhar a senha.

Política: após MAX_TENTATIVAS falhas seguidas de um mesmo IP dentro de
JANELA_SEGUNDOS, o IP fica bloqueado por BLOQUEIO_SEGUNDOS. Uma
autenticação bem-sucedida zera o contador daquele IP.
"""

from __future__ import annotations

import threading
import time

MAX_TENTATIVAS = 5
JANELA_SEGUNDOS = 5 * 60
BLOQUEIO_SEGUNDOS = 5 * 60

_lock = threading.Lock()
# chave -> {"falhas": [timestamps], "bloqueado_ate": timestamp | None}
_estado: dict[str, dict] = {}


def _agora() -> float:
    return time.time()


def esta_bloqueado(chave: str) -> tuple[bool, int]:
    """Retorna (bloqueado, segundos_restantes)."""
    with _lock:
        registro = _estado.get(chave)
        if not registro or not registro.get("bloqueado_ate"):
            return False, 0
        restante = registro["bloqueado_ate"] - _agora()
        if restante <= 0:
            registro["bloqueado_ate"] = None
            registro["falhas"] = []
            return False, 0
        return True, int(restante) + 1


def registrar_falha(chave: str) -> None:
    with _lock:
        registro = _estado.setdefault(chave, {"falhas": [], "bloqueado_ate": None})
        agora = _agora()
        registro["falhas"] = [t for t in registro["falhas"] if agora - t < JANELA_SEGUNDOS]
        registro["falhas"].append(agora)
        if len(registro["falhas"]) >= MAX_TENTATIVAS:
            registro["bloqueado_ate"] = agora + BLOQUEIO_SEGUNDOS


def registrar_sucesso(chave: str) -> None:
    with _lock:
        _estado.pop(chave, None)
