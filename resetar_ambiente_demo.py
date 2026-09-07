"""
Reseta o ambiente local (quando você roda `python app.py` direto, sem
passar pelo .exe) para o estado "de fábrica" guardado em
_dados_semente/ — mesmo estado que um cliente novo recebe. Use antes
de cada demonstração, e sempre antes de gerar um build para um cliente
real (build_exe.py já usa _dados_semente/ direto e ignora sua pasta de
trabalho para esses arquivos, mas rodar isto localmente também deixa
o app.py, se você for testar antes do build, num estado igualmente
limpo).

POR QUE ISSO EXISTE:
`python app.py` lê e grava direto nos arquivos reais do projeto
(core/config.json, core/turmas.json, sceds/data/*.sceds, configs de
módulo) — é assim que a instalação de um cliente real funciona também.
Sem isso, qualquer coisa criada testando localmente (um admin do
wizard, a instituição de um teste antigo, dados fictícios) fica
gravada ali e contamina a próxima demonstração. Ver
_dados_semente/LEIA-ME.md para o quadro completo.

USO:
    python resetar_ambiente_demo.py            # restaura tudo, fica vazio
    python resetar_ambiente_demo.py --com-mock # restaura e já gera dados fictícios

Roda sempre a partir da pasta raiz do projeto.
"""

import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SEMENTE = BASE / "_dados_semente"

# Mesma lista que build_exe.py usa para montar o build — mantidas
# juntas de propósito (ver ARQUIVOS_SEMENTE em build_exe.py).
ARQUIVOS_SEMENTE = [
    "core/config.json",
    "core/turmas.json",
    "modulos/agendamento/recursos.json",
    "modulos/iot/dispositivos.json",
    "modulos/iot/estado_ac.json",
    "modulos/iot/estado_portoes.json",
    "modulos/sinal/config_sinal.json",
    "modulos/sinal/estado_sinal.json",
    "modulos/sinal/horarios_padrao.json",
    "modulos/sinal/horarios_prova.json",
    "modulos/sinal/horarios_sabado.json",
    "modulos/sinal/whatsapp_grupos.json",
]

TABELAS_SCEDS_VAZIAS = [
    "alunos", "usuarios", "livros", "emprestimos", "ocorrencias",
    "evasao_frequencia", "reservas", "chaves", "chaves_movimentos",
    "compromissos", "mensagens_chat", "chamados", "leituras_iot",
]


def main():
    if not SEMENTE.exists():
        raise SystemExit(
            "_dados_semente/ não encontrada. Este script precisa dela — "
            "veja _dados_semente/LEIA-ME.md."
        )

    com_mock = "--com-mock" in sys.argv

    licenca = BASE / "licenca.smc"
    if licenca.exists():
        licenca.unlink()
        print("✓ licenca.smc removido (senão o login/wizard fica bloqueado "
              "e o gerar_mock_data.py se recusa a rodar).")

    for rel in ARQUIVOS_SEMENTE:
        origem = SEMENTE / rel
        destino = BASE / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, destino)
    print(f"✓ {len(ARQUIVOS_SEMENTE)} arquivos de configuração restaurados a partir de _dados_semente/.")

    data_dir = BASE / "sceds" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    import json
    for tabela in TABELAS_SCEDS_VAZIAS:
        schema_origem = SEMENTE / "sceds" / "data" / f"{tabela}.schema.json"
        shutil.copy2(schema_origem, data_dir / f"{tabela}.schema.json")
        with open(data_dir / f"{tabela}.sceds", "w", encoding="utf-8") as f:
            json.dump({"registros": [], "proximo_id": 1}, f, ensure_ascii=False, indent=2)
    print(f"✓ {len(TABELAS_SCEDS_VAZIAS)} tabelas restauradas vazias, em texto puro (sem criptografia).")

    chave_local = BASE / "sceds" / ".chave_data"
    if chave_local.exists():
        chave_local.unlink()
        print("✓ sceds/.chave_data (chave de criptografia local) removida — "
              "uma nova é criada sozinha na próxima leitura/escrita.")

    if com_mock:
        print("\nGerando dados fictícios...")
        import gerar_mock_data as gm
        gm.main(base=BASE, forcar=True)
        print("✓ Dados fictícios gerados. Rode 'python app.py' e faça login "
              "com o admin de demonstração de sempre.")
    else:
        print("\nAmbiente restaurado ao estado de fábrica. Rode 'python "
              "app.py' — vai abrir no wizard de instalação (nenhum admin "
              "existe ainda), igual um cliente novo abrindo o .exe pela "
              "primeira vez.")


if __name__ == "__main__":
    main()
