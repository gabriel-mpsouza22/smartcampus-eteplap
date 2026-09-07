
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from datetime import datetime, date

from .crypto import carregar_ou_criar_chave, cifrar, decifrar_ou_legado

logger = logging.getLogger("smartcampus.sceds")


class SCEDSEngine:
    """
    Motor principal do SCEDS.
    Gerencia leitura, escrita e indexação dos arquivos .sceds (dados
    pessoais cifrados em repouso com Fernet — ver sceds/crypto.py).
    Thread-safe via locks por tabela.

    IMPORTANTE sobre concorrência: o app roda com threaded=True (um
    único processo, múltiplas threads — ver app.py) e código como
    core/auth.py cria uma instância NOVA de SCEDSEngine a cada chamada
    (via _get_db()). Se o lock por tabela vivesse no dicionário de
    instância (self._locks), cada instância nova teria seu próprio
    threading.Lock() e a exclusão mútua entre requisições concorrentes
    seria apenas aparente — duas threads processando duas instâncias
    diferentes nunca disputariam o MESMO objeto Lock, e escritas
    concorrentes na mesma tabela poderiam corromper o arquivo (dado
    perdido, ou pior, uma exceção no meio do os.replace por dois
    processos de escrita pisando no mesmo arquivo .tmp).

    Por isso os locks vivem num registro de nível de MÓDULO
    (_REGISTRO_LOCKS), chaveados pelo caminho absoluto real do arquivo
    da tabela — assim, não importa quantas instâncias de SCEDSEngine
    existam apontando para a mesma pasta de dados, todas elas disputam
    o mesmo Lock físico por tabela. Isto resolve concorrência entre
    THREADS de um mesmo processo; não resolve concorrência entre
    PROCESSOS de sistema operacional diferentes (não é o caso aqui,
    dado o threaded=True de um único processo em app.py — se isso
    mudar no futuro para múltiplos processos/workers, será necessário
    também um lock de arquivo real, ex. via módulo `filelock`).
    """

    TIPOS_VALIDOS = {"INTEIRO", "TEXTO", "DECIMAL", "BOOLEANO", "DATA", "DATA_HORA"}

    # Registro global (por processo), não por instância — ver docstring
    # da classe. `_registro_trava` protege apenas a criação de entradas
    # novas no dicionário; o Lock de cada tabela em si é obtido e usado
    # fora dela.
    _REGISTRO_LOCKS: dict[str, threading.Lock] = {}
    _registro_trava = threading.Lock()

    def __init__(self, caminho_dados: str | Path):
        self.caminho_dados = Path(caminho_dados)
        self.caminho_dados.mkdir(parents=True, exist_ok=True)
        self._schema_cache: dict[str, dict] = {}
        # Carregada/gerada uma única vez por instância do motor — evita
        # reabrir o arquivo de chave a cada leitura/escrita de tabela.
        self._chave = carregar_ou_criar_chave(self.caminho_dados)


    def _lock(self, tabela: str) -> threading.Lock:
        chave = str(self._caminho_tabela(tabela).resolve())
        # Fast path sem lock: se a entrada já existe (caso comum, depois
        # da primeira chamada), evita contenção desnecessária em
        # _registro_trava a cada operação.
        lock = self._REGISTRO_LOCKS.get(chave)
        if lock is not None:
            return lock
        with self._registro_trava:
            if chave not in self._REGISTRO_LOCKS:
                self._REGISTRO_LOCKS[chave] = threading.Lock()
            return self._REGISTRO_LOCKS[chave]


    def _caminho_tabela(self, tabela: str) -> Path:
        return self.caminho_dados / f"{tabela}.sceds"

    def _caminho_schema(self, tabela: str) -> Path:
        return self.caminho_dados / f"{tabela}.schema.json"


    def criar_tabela(self, tabela: str, colunas: list[dict]) -> None:
        """
        Cria uma nova tabela.
        colunas: lista de dicts com chaves: nome, tipo, modificadores (lista)
        Exemplo: [{"nome": "id", "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]}]
        """
        caminho = self._caminho_tabela(tabela)
        caminho_schema = self._caminho_schema(tabela)

        if caminho.exists():
            raise ValueError(f"Tabela '{tabela}' já existe.")

        for col in colunas:
            if col["tipo"] not in self.TIPOS_VALIDOS:
                raise ValueError(f"Tipo inválido '{col['tipo']}' na coluna '{col['nome']}'.")

        schema = {
            "tabela": tabela,
            "colunas": colunas,
            "criada_em": datetime.now().isoformat()
        }

        # O schema (nomes de coluna/tipo, sem dado pessoal nenhum) continua
        # em JSON puro — não há necessidade de cifrar, e mantê-lo legível
        # ajuda diagnóstico/suporte sem abrir mão de proteger o que importa.
        with open(caminho_schema, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)

        self._salvar(tabela, {"registros": [], "proximo_id": 1})
        self._schema_cache[tabela] = schema

    def tabela_existe(self, tabela: str) -> bool:
        return self._caminho_tabela(tabela).exists()


    def _carregar(self, tabela: str) -> dict:
        caminho = self._caminho_tabela(tabela)
        if not caminho.exists():
            raise FileNotFoundError(f"Tabela '{tabela}' não encontrada.")

        conteudo = caminho.read_bytes()
        dados, era_texto_puro = decifrar_ou_legado(conteudo, self._chave)

        if era_texto_puro:
            # Tabela criada antes da criptografia em repouso existir —
            # migra automaticamente para o formato cifrado agora, sem
            # exigir nenhum script manual (mesmo espírito de
            # adicionar_coluna_se_ausente, abaixo).
            logger.warning(
                "Tabela '%s' estava em texto puro (pré-criptografia) — "
                "migrando para formato cifrado agora.", tabela,
            )
            self._salvar(tabela, dados)

        return dados

    def _salvar(self, tabela: str, dados: dict) -> None:
        """
        Escrita atômica: grava em um arquivo temporário no MESMO diretório
        (necessário para que os.replace seja atômico dentro do mesmo
        filesystem) e só substitui o arquivo real depois que a escrita e o
        fsync terminaram com sucesso. Isso garante que uma queda de energia
        ou um kill do processo no meio da operação NUNCA deixa a tabela em
        um estado parcialmente escrito/corrompido: o arquivo antigo
        permanece intacto até o novo estar 100% gravado em disco.

        O conteúdo é cifrado (Fernet) antes de ir para disco — ver
        sceds/crypto.py para o que isso protege e o que não protege.
        """
        caminho = self._caminho_tabela(tabela)
        # O nome do temporário precisa ser único por CHAMADA, não só por
        # processo: com threaded=True, duas threads do mesmo processo têm
        # o mesmo os.getpid() — usar só o PID fazia duas escritas
        # concorrentes colidirem no mesmo arquivo .tmp (uma sobrescrevia/
        # removia o arquivo temporário da outra no meio da operação,
        # gerando FileNotFoundError em os.replace ou, pior, um os.replace
        # "bem-sucedido" com o conteúdo errado). Combinar PID + id da
        # thread + um sufixo aleatório elimina a colisão por completo,
        # tanto entre threads quanto entre processos.
        tmp = caminho.with_suffix(
            caminho.suffix + f".tmp{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
        )
        token = cifrar(dados, self._chave)
        try:
            with open(tmp, "wb") as f:
                f.write(token)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, caminho)  # atômico no mesmo filesystem (POSIX e Windows)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _carregar_schema(self, tabela: str) -> dict:
        if tabela in self._schema_cache:
            return self._schema_cache[tabela]
        caminho = self._caminho_schema(tabela)
        if not caminho.exists():
            raise FileNotFoundError(f"Schema da tabela '{tabela}' não encontrado.")
        with open(caminho, "r", encoding="utf-8") as f:
            schema = json.load(f)
        self._schema_cache[tabela] = schema
        return schema


    def _converter_valor(self, valor, tipo: str):
        """Converte o valor Python para o tipo SCEDS definido no schema."""
        if valor is None:
            return None
        tipo = tipo.upper()
        try:
            if tipo == "INTEIRO":
                return int(valor)
            elif tipo == "DECIMAL":
                return float(valor)
            elif tipo == "BOOLEANO":
                if isinstance(valor, bool):
                    return valor
                return str(valor).lower() in ("true", "verdadeiro", "1", "sim")
            elif tipo == "DATA":
                if isinstance(valor, date):
                    return valor.isoformat()
                return str(valor)
            elif tipo == "DATA_HORA":
                if isinstance(valor, datetime):
                    return valor.isoformat()
                return str(valor)
            else:
                return str(valor)
        except Exception:
            return valor


    def _validar_e_preparar(self, tabela: str, dados: dict, modo: str = "inserir") -> dict:
        """
        Valida tipos, aplica valores padrão e converte os dados.
        modo: 'inserir' ou 'atualizar'
        """
        schema = self._carregar_schema(tabela)
        colunas = {col["nome"]: col for col in schema["colunas"]}
        resultado = {}

        for nome_col, col in colunas.items():
            mods = col.get("modificadores", [])

            if "AUTO" in mods and modo == "inserir":
                continue

            valor = dados.get(nome_col)

            if "NAO_NULO" in mods and valor is None and modo == "inserir":
                padrao = next((m for m in mods if str(m).startswith("PADRAO:")), None)
                if padrao:
                    valor = padrao.split(":", 1)[1].strip()
                else:
                    raise ValueError(f"Campo '{nome_col}' não pode ser nulo.")

            if valor is None and "PADRAO" in col:
                valor = col["PADRAO"]

            if valor is not None:
                resultado[nome_col] = self._converter_valor(valor, col["tipo"])

        return resultado


    def inserir(self, tabela: str, dados: dict) -> dict:
        """Insere um registro e retorna o registro completo (com id gerado)."""
        with self._lock(tabela):
            bd = self._carregar(tabela)
            return self._inserir_bloqueado(tabela, dados, bd)

    def inserir_com_validacao(self, tabela: str, dados: dict, validador) -> dict:
        """
        Como inserir(), mas roda `validador(registros_existentes)` ANTES
        de gravar, sob o MESMO lock que protege a escrita — ou seja,
        checagem e inserção acontecem como uma operação atômica única,
        sem a janela de corrida (TOCTOU) que existiria se o chamador
        fizesse um buscar() separado seguido de um inserir() separado.

        `validador` recebe a lista de registros já existentes na tabela
        (antes da inserção) e deve levantar ValueError para abortar —
        qualquer exceção levantada por ele impede a inserção e se
        propaga normalmente para quem chamou.

        Uso típico: impedir duas requisições concorrentes de criarem,
        cada uma vendo o estado "antes" da outra, dois registros que
        juntos violam uma regra de negócio que depende de TODOS os
        registros (ex.: "esta senha não pode já estar em uso por
        ninguém" em core/auth.py — o modificador de coluna UNICO já
        cobre unicidade de UM campo isolado, mas não uma regra
        arbitrária como essa).
        """
        with self._lock(tabela):
            bd = self._carregar(tabela)
            validador(bd["registros"])
            return self._inserir_bloqueado(tabela, dados, bd)

    def _inserir_bloqueado(self, tabela: str, dados: dict, bd: dict) -> dict:
        """
        Lógica de inserção propriamente dita. Assume que o chamador já
        está de posse do lock da tabela e já carregou `bd` — nunca
        chamar isto fora de uma seção protegida por self._lock(tabela).
        """
        schema = self._carregar_schema(tabela)
        colunas = {col["nome"]: col for col in schema["colunas"]}

        registro = self._validar_e_preparar(tabela, dados, modo="inserir")

        for nome_col, col in colunas.items():
            mods = col.get("modificadores", [])
            if "AUTO" in mods and "CHAVE_PRIMARIA" in mods:
                registro[nome_col] = bd["proximo_id"]
                bd["proximo_id"] += 1

        for nome_col, col in colunas.items():
            mods = col.get("modificadores", [])
            if "UNICO" in mods and nome_col in registro:
                for reg_existente in bd["registros"]:
                    if reg_existente.get(nome_col) == registro[nome_col]:
                        raise ValueError(
                            f"Valor duplicado no campo único '{nome_col}': {registro[nome_col]}"
                        )

        bd["registros"].append(registro)
        self._salvar(tabela, bd)
        return registro

    def buscar(self, tabela: str, onde: dict | None = None,
               ordernar_por: str | None = None, limite: int | None = None) -> list[dict]:
        """
        Retorna lista de registros que atendem aos filtros 'onde'.
        onde: dict de {campo: valor} — todos devem casar (AND implícito)
        """
        with self._lock(tabela):
            bd = self._carregar(tabela)

        registros = bd["registros"]

        if onde:
            def bate(reg):
                for campo, valor in onde.items():
                    if reg.get(campo) != valor:
                        return False
                return True
            registros = [r for r in registros if bate(r)]

        if ordernar_por:
            registros = sorted(registros, key=lambda r: r.get(ordernar_por, ""))

        if limite:
            registros = registros[:limite]

        return [dict(r) for r in registros]

    def buscar_um(self, tabela: str, onde: dict) -> dict | None:
        """Retorna o primeiro registro que casa com os filtros, ou None."""
        resultados = self.buscar(tabela, onde=onde, limite=1)
        return resultados[0] if resultados else None

    def atualizar(self, tabela: str, novos_dados: dict, onde: dict) -> int:
        """
        Atualiza registros que atendem aos filtros 'onde'.
        Retorna a quantidade de registros atualizados.
        """
        with self._lock(tabela):
            bd = self._carregar(tabela)
            return self._atualizar_bloqueado(tabela, novos_dados, onde, bd)

    def atualizar_com_validacao(self, tabela: str, novos_dados: dict, onde: dict, validador) -> int:
        """
        Como atualizar(), mas roda `validador(registros_existentes)`
        ANTES de gravar, sob o MESMO lock — ver inserir_com_validacao
        para a motivação completa (evita TOCTOU quando a regra de
        negócio depende de comparar com outros registros, ex.:
        core/auth.py:redefinir_senha checando se a nova senha já está
        em uso por outro usuário).
        """
        with self._lock(tabela):
            bd = self._carregar(tabela)
            validador(bd["registros"])
            return self._atualizar_bloqueado(tabela, novos_dados, onde, bd)

    def _atualizar_bloqueado(self, tabela: str, novos_dados: dict, onde: dict, bd: dict) -> int:
        atualizados = 0
        for reg in bd["registros"]:
            if all(reg.get(c) == v for c, v in onde.items()):
                dados_convertidos = self._validar_e_preparar(tabela, novos_dados, modo="atualizar")
                reg.update(dados_convertidos)
                atualizados += 1

        if atualizados > 0:
            self._salvar(tabela, bd)

        return atualizados

    def deletar(self, tabela: str, onde: dict) -> int:
        """
        Remove registros que atendem aos filtros 'onde'.
        Retorna a quantidade de registros removidos.
        """
        with self._lock(tabela):
            bd = self._carregar(tabela)
            total_antes = len(bd["registros"])
            bd["registros"] = [
                r for r in bd["registros"]
                if not all(r.get(c) == v for c, v in onde.items())
            ]
            removidos = total_antes - len(bd["registros"])
            if removidos > 0:
                self._salvar(tabela, bd)

        return removidos

    def contar(self, tabela: str, onde: dict | None = None) -> int:
        """Conta registros que atendem ao filtro."""
        return len(self.buscar(tabela, onde=onde))

    def listar_tabelas(self) -> list[str]:
        """Retorna os nomes de todas as tabelas existentes."""
        return [
            p.stem for p in self.caminho_dados.glob("*.sceds")
            if not p.stem.endswith(".schema")
        ]

    def dropar_tabela(self, tabela: str) -> None:
        """Remove uma tabela e seu schema. Use com cuidado."""
        caminho = self._caminho_tabela(tabela)
        caminho_schema = self._caminho_schema(tabela)
        if caminho.exists():
            caminho.unlink()
        if caminho_schema.exists():
            caminho_schema.unlink()
        self._schema_cache.pop(tabela, None)
        self._locks.pop(tabela, None)

    def adicionar_coluna_se_ausente(self, tabela: str, coluna: dict) -> bool:
        """
        Adiciona uma coluna ao schema de uma tabela já existente, caso
        ela ainda não exista — permite uma funcionalidade nova evoluir
        uma tabela antiga sem exigir que o cliente rode nenhum script
        de migração manual (o schema é conferido/corrigido sozinho a
        cada acesso). Registros já salvos não são reescritos: eles
        simplesmente não têm o campo até serem atualizados, e
        buscar()/atualizar() já lidam bem com campos ausentes.
        Retorna True se a coluna foi adicionada agora, False se já existia.
        """
        if coluna["tipo"] not in self.TIPOS_VALIDOS:
            raise ValueError(f"Tipo inválido '{coluna['tipo']}' na coluna '{coluna['nome']}'.")
        with self._lock(tabela):
            if not self._caminho_schema(tabela).exists():
                # Tabela ainda não existe neste banco (instalação muito
                # antiga ou corrompida) — nada a evoluir aqui. Quem
                # chama deve garantir a tabela em si, se for o caso.
                return False
            schema = self._carregar_schema(tabela)
            if any(c["nome"] == coluna["nome"] for c in schema["colunas"]):
                return False
            schema["colunas"].append(coluna)
            with open(self._caminho_schema(tabela), "w", encoding="utf-8") as f:
                json.dump(schema, f, ensure_ascii=False, indent=2)
            self._schema_cache[tabela] = schema
            return True

    def backup_tabela(self, tabela: str, destino: str | Path) -> Path:
        """Copia o arquivo .sceds de uma tabela para a pasta de destino."""
        destino = Path(destino)
        destino.mkdir(parents=True, exist_ok=True)
        origem = self._caminho_tabela(tabela)
        if not origem.exists():
            raise FileNotFoundError(f"Tabela '{tabela}' não encontrada para backup.")
        destino_arquivo = destino / origem.name
        import shutil
        shutil.copy2(origem, destino_arquivo)
        return destino_arquivo
