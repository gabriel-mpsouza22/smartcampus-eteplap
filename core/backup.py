"""
Backup automático do banco SCEDS.

Modelo do produto: cada escola roda uma instância local única (appliance
desktop), então não há infraestrutura externa (cron, S3, etc.) disponível
por padrão. Este módulo resolve isso rodando o próprio agendamento DENTRO
do processo da aplicação, sem dependências novas.

O que ele faz:
- A cada intervalo configurável (padrão: 6 horas) e sempre na inicialização
  do processo, compacta a pasta inteira de dados (sceds/data/*.sceds e
  *.schema.json) num .zip com timestamp, dentro de uma pasta `backups/`
  ao lado dos dados.
- Mantém as N cópias mais recentes (padrão: 30) e apaga as mais antigas —
  retenção simples baseada em contagem, não em calendário, para não
  precisar de configuração adicional.
- Cada backup é escrito primeiro com sufixo `.tmp` e só renomeado para
  `.zip` no final (os.replace), pelo mesmo motivo da escrita atômica do
  engine: um backup interrompido no meio não deve aparecer como um
  backup "concluído" que na verdade está corrompido.

O que ele NÃO faz (documentado deliberadamente, não esquecido):
- Não envia o backup para fora da máquina/disco físico da escola. Isso
  protege contra corrupção de arquivo e erro humano, mas NÃO contra perda
  do disco/computador inteiro (incêndio, roubo, falha de HD). Para essa
  proteção, o backup precisa ser copiado periodicamente para um destino
  externo (pendrive, nuvem, outro computador da rede) — isso é uma
  decisão operacional de cada instalação, fora do escopo deste módulo.
- Não testa o restore automaticamente. Ver `restaurar()` abaixo, que deve
  ser testada manualmente pela equipe antes de confiar no produto.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("smartcampus.backup")

INTERVALO_PADRAO_SEGUNDOS = 6 * 60 * 60   # 6 horas
RETENCAO_PADRAO = 30                       # mantém os 30 backups mais recentes

_thread: threading.Thread | None = None
_parar = threading.Event()


def executar_backup(pasta_dados: Path, pasta_backups: Path, retencao: int = RETENCAO_PADRAO) -> Path:
    """
    Executa um backup completo agora e aplica a política de retenção.
    Retorna o caminho do arquivo .zip criado.
    Pode ser chamada manualmente (ex.: botão "Fazer backup agora" no
    painel de admin) ou pelo agendador em `iniciar_agendador`.
    """
    pasta_dados = Path(pasta_dados)
    pasta_backups = Path(pasta_backups)
    pasta_backups.mkdir(parents=True, exist_ok=True)

    # Microssegundos no carimbo: evita colisão de nome de arquivo quando o
    # backup é disparado manualmente mais de uma vez dentro do mesmo
    # segundo (ex.: botão "Fazer backup agora" clicado repetidamente).
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino_final = pasta_backups / f"backup_{carimbo}.zip"
    destino_tmp = pasta_backups / f"backup_{carimbo}.zip.tmp"

    try:
        with zipfile.ZipFile(destino_tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for arquivo in pasta_dados.rglob("*"):
                if arquivo.is_file():
                    zf.write(arquivo, arquivo.relative_to(pasta_dados))
        os.replace(destino_tmp, destino_final)
        logger.info("Backup criado: %s", destino_final)
    except Exception:
        logger.exception("Falha ao criar backup de %s", pasta_dados)
        if destino_tmp.exists():
            destino_tmp.unlink(missing_ok=True)
        raise

    _aplicar_retencao(pasta_backups, retencao)
    return destino_final


def _aplicar_retencao(pasta_backups: Path, retencao: int) -> None:
    backups = sorted(
        (p for p in pasta_backups.glob("backup_*.zip") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for antigo in backups[retencao:]:
        try:
            antigo.unlink()
            logger.info("Backup antigo removido pela retenção: %s", antigo)
        except OSError:
            logger.exception("Não foi possível remover backup antigo: %s", antigo)


def restaurar(
    arquivo_backup: Path,
    pasta_dados_destino: Path,
    caminho_chave_origem: Path | None = None,
) -> None:
    """
    Restaura um backup .zip para a pasta de dados informada.

    ATENÇÃO: isto SOBRESCREVE o conteúdo atual de pasta_dados_destino.
    Antes de chamar isto sobre uma pasta de dados em uso, o processo da
    aplicação deve estar parado (o SCEDS não foi projetado para ter seus
    arquivos trocados por baixo dele enquanto está rodando).

    Esta função não é chamada automaticamente por nenhum fluxo do
    produto — ela existe para ser usada manualmente pelo suporte/equipe
    de implantação em caso de recuperação de desastre, e deveria ser
    testada em um ambiente de homologação antes de qualquer cliente
    real precisar dela de verdade.

    SOBRE A CHAVE DE CRIPTOGRAFIA (ver sceds/crypto.py):
    O backup contém apenas os arquivos *.sceds (já cifrados) — nunca a
    chave que os decifra, de propósito (é essa separação que protege um
    backup perdido/copiado indevidamente). Isso tem uma consequência
    direta na hora de restaurar:

    - Restauração NA MESMA MÁQUINA/instalação que gerou o backup: não
      precisa informar `caminho_chave_origem` — a chave já existe ao
      lado da pasta de dados e continua sendo a mesma.
    - Restauração em uma MÁQUINA NOVA (disaster recovery de verdade):
      é *obrigatório* informar `caminho_chave_origem` apontando para a
      cópia da chave que a equipe guardou separadamente (fora do disco
      que falhou) no momento do backup. Sem isso, os dados restaurados
      ficam ilegíveis — não corrompidos, apenas cifrados sem a chave
      correspondente. Por isso o runbook de recuperação de desastre da
      equipe precisa incluir, desde já, guardar uma cópia de
      sceds/.chave_dados em local seguro e separado do servidor
      (mesmo espírito de como licenciamento/chave_privada.pem nunca
      fica só num lugar).
    """
    arquivo_backup = Path(arquivo_backup)
    pasta_dados_destino = Path(pasta_dados_destino)
    if not arquivo_backup.exists():
        raise FileNotFoundError(f"Arquivo de backup não encontrado: {arquivo_backup}")

    pasta_dados_destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arquivo_backup, "r") as zf:
        zf.extractall(pasta_dados_destino)

    if caminho_chave_origem is not None:
        from sceds.crypto import caminho_chave as _caminho_chave_destino

        caminho_chave_origem = Path(caminho_chave_origem)
        if not caminho_chave_origem.exists():
            raise FileNotFoundError(
                f"Chave de criptografia informada não encontrada: {caminho_chave_origem}"
            )
        destino_chave = _caminho_chave_destino(pasta_dados_destino)
        destino_chave.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(caminho_chave_origem, destino_chave)
        logger.info("Chave de criptografia restaurada junto com os dados em %s", destino_chave)

    logger.info("Backup restaurado de %s para %s", arquivo_backup, pasta_dados_destino)


def iniciar_agendador(
    pasta_dados: Path,
    pasta_backups: Path,
    intervalo_segundos: int = INTERVALO_PADRAO_SEGUNDOS,
    retencao: int = RETENCAO_PADRAO,
) -> None:
    """
    Inicia uma thread de background que roda `executar_backup` uma vez
    imediatamente (garante que toda instalação tem pelo menos um backup
    desde o primeiro dia) e depois a cada `intervalo_segundos`.

    Idempotente: chamar mais de uma vez não inicia threads duplicadas.
    """
    global _thread
    if _thread is not None and _thread.is_alive():
        return

    def _loop():
        while not _parar.is_set():
            try:
                executar_backup(pasta_dados, pasta_backups, retencao)
            except Exception:
                # Uma falha de backup não pode derrubar o servidor —
                # já logamos o erro dentro de executar_backup.
                pass
            _parar.wait(intervalo_segundos)

    _thread = threading.Thread(target=_loop, name="backup-agendado", daemon=True)
    _thread.start()
    logger.info(
        "Agendador de backup iniciado (intervalo=%ss, retenção=%d cópias)",
        intervalo_segundos, retencao,
    )


def parar_agendador() -> None:
    """Sinaliza para a thread de backup parar no próximo ciclo. Usado em testes."""
    _parar.set()
