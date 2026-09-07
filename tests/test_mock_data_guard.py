import pytest


def test_gerar_mock_data_bloqueia_com_licenca_presente(pasta_tmp):
    import gerar_mock_data as g

    (pasta_tmp / "licenca.smc").write_text("qualquer coisa")

    with pytest.raises(RuntimeError, match="CLIENTE REAL"):
        g.main(base=pasta_tmp, forcar=False)
