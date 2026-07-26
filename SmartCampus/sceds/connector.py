
from pathlib import Path
from .engine import SCEDSEngine
from .parser import SCEDSParser


class SCEDS:
    """
    Conector principal do SCEDS.
    Os módulos importam esta classe e usam seus métodos Python
    ou o método executar() para rodar a linguagem SCEDS em português.

    Exemplo de uso:
        from sceds import SCEDS
        db = SCEDS(r"C:\\SmartCampus\\sceds\\data")

        # Via linguagem SCEDS
        db.executar("BUSCAR * DE usuarios ONDE perfil = 'professor'")

        # Via atalhos Python
        db.buscar("usuarios", onde={"perfil": "professor"})
        db.inserir("usuarios", {"nome": "Ana", "senha": "hash", "perfil": "bibliotecaria"})
        db.atualizar("usuarios", {"ativo": False}, onde={"id": 3})
        db.deletar("usuarios", onde={"id": 3})
    """

    def __init__(self, caminho_dados: str | Path):
        self._engine = SCEDSEngine(caminho_dados)
        self._parser = SCEDSParser()


    def executar(self, comando: str):
        """
        Executa um comando escrito na linguagem SCEDS em português.
        Retorna:
            - list[dict] para BUSCAR
            - dict para INSERIR (registro inserido)
            - int para ATUALIZAR e DELETAR (quantidade afetada)
            - None para CRIAR TABELA
        """
        ast = self._parser.parse(comando)
        op = ast["operacao"]

        if op == "criar":
            self._engine.criar_tabela(ast["tabela"], ast["colunas"])
            return None

        elif op == "inserir":
            return self._engine.inserir(ast["tabela"], ast["dados"])

        elif op == "buscar":
            return self._engine.buscar(ast["tabela"], onde=ast.get("onde"))

        elif op == "atualizar":
            return self._engine.atualizar(
                ast["tabela"], ast["novos_dados"], ast["onde"]
            )

        elif op == "deletar":
            return self._engine.deletar(ast["tabela"], ast["onde"])

        else:
            raise ValueError(f"Operação desconhecida: '{op}'")


    def criar_tabela(self, tabela: str, colunas: list[dict]) -> None:
        """
        Cria uma tabela com a definição passada diretamente em Python.
        Exemplo:
            db.criar_tabela("usuarios", [
                {"nome": "id",    "tipo": "INTEIRO", "modificadores": ["CHAVE_PRIMARIA", "AUTO"]},
                {"nome": "nome",  "tipo": "TEXTO",   "modificadores": ["NAO_NULO"]},
                {"nome": "senha", "tipo": "TEXTO",   "modificadores": ["NAO_NULO"]},
                {"nome": "perfil","tipo": "TEXTO",   "modificadores": ["NAO_NULO"]},
                {"nome": "ativo", "tipo": "BOOLEANO","modificadores": [], "PADRAO": True},
            ])
        """
        self._engine.criar_tabela(tabela, colunas)

    def buscar(self, tabela: str, onde: dict | None = None,
               ordenar_por: str | None = None, limite: int | None = None) -> list[dict]:
        """
        Retorna registros da tabela que atendem aos filtros.
        onde: dict com campos e valores exatos (AND implícito)
        """
        return self._engine.buscar(tabela, onde=onde, ordernar_por=ordenar_por, limite=limite)

    def buscar_um(self, tabela: str, onde: dict) -> dict | None:
        """Retorna o primeiro registro que casa com os filtros, ou None."""
        return self._engine.buscar_um(tabela, onde)

    def inserir(self, tabela: str, dados: dict) -> dict:
        """Insere um registro e retorna o registro completo (com id gerado)."""
        return self._engine.inserir(tabela, dados)

    def atualizar(self, tabela: str, novos_dados: dict, onde: dict) -> int:
        """
        Atualiza campos dos registros que casam com 'onde'.
        Retorna a quantidade de registros atualizados.
        """
        return self._engine.atualizar(tabela, novos_dados, onde)

    def deletar(self, tabela: str, onde: dict) -> int:
        """
        Remove registros que casam com 'onde'.
        Retorna a quantidade de registros removidos.
        """
        return self._engine.deletar(tabela, onde)

    def contar(self, tabela: str, onde: dict | None = None) -> int:
        """Conta registros que atendem ao filtro."""
        return self._engine.contar(tabela, onde)

    def tabela_existe(self, tabela: str) -> bool:
        """Verifica se a tabela existe."""
        return self._engine.tabela_existe(tabela)

    def listar_tabelas(self) -> list[str]:
        """Lista todas as tabelas existentes."""
        return self._engine.listar_tabelas()

    def dropar_tabela(self, tabela: str) -> None:
        """Remove uma tabela e todos os seus dados. Use com cautela."""
        self._engine.dropar_tabela(tabela)

    def backup_tabela(self, tabela: str, destino: str | Path) -> Path:
        """Copia o arquivo .sceds de uma tabela para a pasta de destino."""
        return self._engine.backup_tabela(tabela, destino)

    def backup_completo(self, destino: str | Path) -> list[Path]:
        """Copia todos os arquivos .sceds para a pasta de destino."""
        arquivos = []
        for tabela in self._engine.listar_tabelas():
            arquivos.append(self._engine.backup_tabela(tabela, destino))
        return arquivos
