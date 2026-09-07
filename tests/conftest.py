import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture
def pasta_tmp(tmp_path):
    """Pasta temporária isolada por teste — nunca toca nos dados reais."""
    return tmp_path


@pytest.fixture
def engine(pasta_tmp):
    from sceds.engine import SCEDSEngine
    return SCEDSEngine(pasta_tmp / "dados")
