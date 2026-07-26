
import json
import os
import threading
from pathlib import Path
from datetime import datetime, date


class SCEDSEngine:
    """
    Motor principal do SCEDS.
    Gerencia leitura, escrita e indexação dos arquivos .sceds (JSON).
    Thread-safe via locks por tabela.
    """

    TIPOS_VALIDOS = {"INTEIRO", "TEXTO", "DECIMAL", "BOOLEANO", "DATA", "DATA_HORA"}

    def __init__(self, caminho_dados: str | Path):
        self.caminho_dados = Path(caminho_dados)
        self.caminho_dados.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._schema_cache: dict[str, dict] = {}


    def _lock(self, tabela: str) -> threading.Lock:
        if tabela not in self._locks:
            self._locks[tabela] = threading.Lock()
        return self._locks[tabela]


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

        with open(caminho_schema, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)

        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"registros": [], "proximo_id": 1}, f, ensure_ascii=False, indent=2)

        self._schema_cache[tabela] = schema

    def tabela_existe(self, tabela: str) -> bool:
        return self._caminho_tabela(tabela).exists()


    def _carregar(self, tabela: str) -> dict:
        caminho = self._caminho_tabela(tabela)
        if not caminho.exists():
            raise FileNotFoundError(f"Tabela '{tabela}' não encontrada.")
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)

    def _salvar(self, tabela: str, dados: dict) -> None:
        caminho = self._caminho_tabela(tabela)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)

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
