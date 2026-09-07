"""
Log de auditoria de negócio do SmartCampus.

Diferente de logs/servidor.log (log técnico: erros, exceções, requisições),
este módulo registra EVENTOS DE NEGÓCIO que respondem "quem fez o quê, em
qual registro, quando" — a pergunta que qualquer coordenação/direção de
escola eventualmente faz ("quem alterou a ocorrência do aluno X?"), e
também um dos pontos que a LGPD cobra tecnicamente: rastreabilidade de
acesso/alteração de dado pessoal (Lei 13.709/2018).

Formato: JSON Lines (um evento por linha) em logs/auditoria.jsonl — não é
uma tabela SCEDS porque auditoria é essencialmente um log de append: não
precisa de update/delete/schema, só precisa nunca perder uma escrita e
ser rápida de escrever. Cada linha é gravada com append + fsync, então
uma queda de energia no meio de um append no máximo perde a ÚLTIMA linha
incompleta (nunca corrompe as anteriores) — comportamento aceitável para
um log, diferente do motor de dados principal (que exige atomicidade
total, resolvida separadamente em sceds/engine.py).

Uso típico:
    from core.auditoria import registrar
    registrar(usuario, "desativou_usuario", entidade="usuarios", entidade_id=42)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("smartcampus.auditoria")

_lock = threading.Lock()


def _caminho_log() -> Path:
    from core.config_path import resolver_config_path
    base = Path(__file__).resolve().parent.parent
    cfg_path = resolver_config_path(base)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    pasta = Path(cfg["caminho_base"]) / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / "auditoria.jsonl"


def registrar(
    usuario: dict | None,
    acao: str,
    entidade: str | None = None,
    entidade_id: int | str | None = None,
    detalhes: dict | None = None,
    ip: str | None = None,
) -> None:
    """
    Registra um evento de auditoria. Nunca levanta exceção para não
    derrubar a operação de negócio que está sendo auditada — uma falha
    ao gravar o log de auditoria é logada no log técnico, mas não impede
    a ação em si (ex.: se o disco de log estiver cheio, o sistema
    continua funcionando, só perde essa entrada de auditoria).

    `usuario` é o dict retornado por usuario_logado() (ou None para
    eventos que acontecem antes/fora de uma sessão, como uma tentativa
    de login que falhou).
    """
    evento = {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "usuario_id": usuario.get("id") if usuario else None,
        "usuario_nome": usuario.get("nome") if usuario else None,
        "usuario_perfil": usuario.get("perfil") if usuario else None,
        "acao": acao,
        "entidade": entidade,
        "entidade_id": entidade_id,
        "detalhes": detalhes or {},
        "ip": ip,
    }

    try:
        linha = json.dumps(evento, ensure_ascii=False)
        with _lock:
            caminho = _caminho_log()
            with open(caminho, "a", encoding="utf-8") as f:
                f.write(linha + "\n")
                f.flush()
                os.fsync(f.fileno())
    except Exception:
        logger.exception("Falha ao gravar evento de auditoria: %s", acao)


def listar(limite: int = 200, filtro_usuario_id: int | None = None, filtro_acao: str | None = None) -> list[dict]:
    """
    Retorna os eventos de auditoria mais recentes primeiro, opcionalmente
    filtrados por usuário e/ou tipo de ação. Usado pelo painel admin.
    """
    caminho = _caminho_log()
    if not caminho.exists():
        return []

    eventos = []
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                # Uma linha corrompida (ex. escrita interrompida) não
                # deve impedir a leitura de todas as outras.
                continue
            if filtro_usuario_id is not None and evento.get("usuario_id") != filtro_usuario_id:
                continue
            if filtro_acao is not None and evento.get("acao") != filtro_acao:
                continue
            eventos.append(evento)

    eventos.reverse()
    return eventos[:limite]
