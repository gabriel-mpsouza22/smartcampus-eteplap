"""
Resolve o caminho de core/config.json em um único lugar.

Por padrão é `<pasta do projeto>/core/config.json`, como sempre foi.
Mas quando rodando como o .exe empacotado (PyInstaller onefile), o
código roda a partir de uma pasta temporária que é apagada ao fechar
o programa — nesse caso, launcher.py define a variável de ambiente
SMARTCAMPUS_CONFIG_PATH apontando para o config.json real, que fica
ao lado do .exe (persistente entre execuções).

IMPORTANTE: todo módulo que precisa ler config.json deve usar
`carregar_config()` deste arquivo — nunca montar o caminho na mão
(`BASE / "core" / "config.json"`). Um caminho montado na mão ignora
silenciosamente o SMARTCAMPUS_CONFIG_PATH e, no .exe empacotado, acaba
lendo o config.json de dentro da pasta temporária do PyInstaller em
vez do config.json persistente ao lado do executável.
"""

import json
import os
from pathlib import Path


def resolver_config_path(base_projeto: Path) -> Path:
    override = os.environ.get("SMARTCAMPUS_CONFIG_PATH")
    if override:
        return Path(override)
    return base_projeto / "core" / "config.json"


def carregar_config(base_projeto: Path) -> dict:
    """Lê e retorna o config.json correto para esta instalação,
    respeitando SMARTCAMPUS_CONFIG_PATH quando definido."""
    with open(resolver_config_path(base_projeto), encoding="utf-8") as f:
        return json.load(f)
