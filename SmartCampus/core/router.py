
from flask import Flask
from pathlib import Path
import json
import sys


def carregar_config() -> dict:
    """Carrega o config.json global do projeto."""
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def registrar_blueprints(app: Flask) -> None:
    """
    Importa e registra todos os blueprints dos módulos no app Flask.
    Cada módulo deve expor uma variável 'blueprint' no seu arquivo de API.
    Erros de importação são registrados no log mas não travam o servidor.
    """
    config = carregar_config()
    base = Path(config["caminho_base"])

    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    modulos = [
        ("Sinal",                  "modulos.sinal.api_sinal",               "/sinal"),
        ("Agendamento",            "modulos.agendamento.api_agendamento",   "/agendamento"),
        ("Biblioteca",             "modulos.biblioteca.api_biblioteca",     "/biblioteca"),
        ("Secretaria-Portaria",    "modulos.secretaria_portaria.api_sp",    "/"),
        ("IoT",                    "modulos.iot.api_iot",                   "/iot"),
        ("Ocorrencias",            "modulos.ocorrencias.api_ocorrencias",   "/ocorrencias"),
        ("Monitoramento",          "modulos.monitoramento.api_monitoramento","/monitoramento"),
        ("Admin",                  "admin.api_admin",                        "/admin"),
    ]

    for nome, caminho, prefixo in modulos:
        try:
            import importlib
            mod = importlib.import_module(caminho)
            bp = getattr(mod, "blueprint", None)
            if bp is None:
                app.logger.warning(f"[Router] Módulo '{nome}' não possui 'blueprint'. Ignorado.")
                continue
            app.register_blueprint(bp, url_prefix=prefixo)
            app.logger.info(f"[Router] ✓ Módulo '{nome}' registrado em '{prefixo}'")
        except ImportError as e:
            app.logger.warning(f"[Router] ⚠ Módulo '{nome}' não pôde ser importado: {e}")
        except Exception as e:
            app.logger.error(f"[Router] ✗ Erro ao registrar '{nome}': {e}")


def perfil_para_cor(perfil: str) -> str:
    """Retorna a cor associada ao perfil para uso no template."""
    cores = {
        "admin":        "#1A1A2E",
        "professor":    "#2E86AB",
        "portaria":     "#E76F51",
        "bibliotecaria":"#8338EC",
        "coordenadora": "#F4A261",
        "secretaria":   "#457B9D",
    }
    return cores.get(perfil, "#4A4A4A")


def perfil_para_label(perfil: str) -> str:
    """Retorna o label legível do perfil."""
    labels = {
        "admin":        "Administrador",
        "professor":    "Professor",
        "portaria":     "Portaria",
        "bibliotecaria":"Bibliotecária",
        "coordenadora": "Coordenadora",
        "secretaria":   "Secretaria",
    }
    return labels.get(perfil, perfil.capitalize())
