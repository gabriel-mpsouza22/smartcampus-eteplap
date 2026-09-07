
import re
from typing import Any


class SCEDSParser:
    """
    Interpreta a linguagem de consulta SCEDS escrita em português.

    Sintaxe suportada:
        CRIAR TABELA nome (campo TIPO [modificadores], ...)
        INSERIR EM tabela (campos) VALORES (valores)
        BUSCAR * DE tabela [ONDE campo = valor [E campo = valor ...]]
        ATUALIZAR tabela DEFINIR campo = valor [, campo = valor] ONDE campo = valor
        DELETAR DE tabela ONDE campo = valor
    """

    CMD_CRIAR    = "CRIAR"
    CMD_INSERIR  = "INSERIR"
    CMD_BUSCAR   = "BUSCAR"
    CMD_ATUALIZAR = "ATUALIZAR"
    CMD_DELETAR  = "DELETAR"

    def parse(self, comando: str) -> dict:
        """
        Analisa o comando SCEDS e retorna um dict com:
            {
              "operacao": str,       # criar | inserir | buscar | atualizar | deletar
              "tabela": str,
              ...campos específicos de cada operação...
            }
        Lança SyntaxError em caso de comando inválido.
        """
        linhas = [l for l in comando.strip().splitlines() if not l.strip().startswith("#")]
        comando = " ".join(linhas).strip()
        comando = re.sub(r"\s+", " ", comando)

        primeira_palavra = comando.split()[0].upper()

        if primeira_palavra == self.CMD_CRIAR:
            return self._parse_criar(comando)
        elif primeira_palavra == self.CMD_INSERIR:
            return self._parse_inserir(comando)
        elif primeira_palavra == self.CMD_BUSCAR:
            return self._parse_buscar(comando)
        elif primeira_palavra == self.CMD_ATUALIZAR:
            return self._parse_atualizar(comando)
        elif primeira_palavra == self.CMD_DELETAR:
            return self._parse_deletar(comando)
        else:
            raise SyntaxError(f"Comando SCEDS desconhecido: '{primeira_palavra}'")


    def _parse_criar(self, cmd: str) -> dict:
        """
        CRIAR TABELA nome (
          campo TIPO [CHAVE_PRIMARIA] [AUTO] [NAO_NULO] [UNICO] [PADRAO valor],
          ...
        )
        """
        padrao = re.compile(
            r"CRIAR\s+TABELA\s+(\w+)\s*\((.+)\)\s*$",
            re.IGNORECASE | re.DOTALL
        )
        m = padrao.match(cmd)
        if not m:
            raise SyntaxError(f"Sintaxe inválida para CRIAR TABELA:\n{cmd}")

        tabela = m.group(1)
        corpo = m.group(2)

        colunas = []
        for linha in self._dividir_colunas(corpo):
            linha = linha.strip()
            if not linha:
                continue
            colunas.append(self._parse_coluna(linha))

        return {"operacao": "criar", "tabela": tabela, "colunas": colunas}

    def _dividir_colunas(self, corpo: str) -> list[str]:
        """Divide a definição de colunas por vírgula, respeitando parênteses."""
        partes = []
        profundidade = 0
        atual = []
        for ch in corpo:
            if ch == "(":
                profundidade += 1
                atual.append(ch)
            elif ch == ")":
                profundidade -= 1
                atual.append(ch)
            elif ch == "," and profundidade == 0:
                partes.append("".join(atual).strip())
                atual = []
            else:
                atual.append(ch)
        if atual:
            partes.append("".join(atual).strip())
        return partes

    def _parse_coluna(self, definicao: str) -> dict:
        """
        Analisa a definição de uma coluna:
        nome TIPO [modificadores...]
        """
        tokens = definicao.split()
        if len(tokens) < 2:
            raise SyntaxError(f"Definição de coluna inválida: '{definicao}'")

        nome = tokens[0]
        tipo = tokens[1].upper()

        tipos_validos = {"INTEIRO", "TEXTO", "DECIMAL", "BOOLEANO", "DATA", "DATA_HORA"}
        if tipo not in tipos_validos:
            raise SyntaxError(f"Tipo inválido '{tipo}' na coluna '{nome}'.")

        modificadores = []
        i = 2
        while i < len(tokens):
            tok = tokens[i].upper()
            if tok == "PADRAO" and i + 1 < len(tokens):
                modificadores.append(f"PADRAO:{tokens[i + 1]}")
                i += 2
            elif tok in {"CHAVE_PRIMARIA", "AUTO", "NAO_NULO", "UNICO"}:
                modificadores.append(tok)
                i += 1
            else:
                i += 1

        return {"nome": nome, "tipo": tipo, "modificadores": modificadores}


    def _parse_inserir(self, cmd: str) -> dict:
        """
        INSERIR EM tabela (campo1, campo2, ...) VALORES (val1, val2, ...)
        """
        padrao = re.compile(
            r"INSERIR\s+EM\s+(\w+)\s*\(([^)]+)\)\s+VALORES\s*\((.+)\)\s*$",
            re.IGNORECASE
        )
        m = padrao.match(cmd)
        if not m:
            raise SyntaxError(f"Sintaxe inválida para INSERIR EM:\n{cmd}")

        tabela = m.group(1)
        campos = [c.strip() for c in m.group(2).split(",")]
        valores_raw = m.group(3)
        valores = self._parse_lista_valores(valores_raw)

        if len(campos) != len(valores):
            raise SyntaxError(
                f"Número de campos ({len(campos)}) difere do número de valores ({len(valores)})."
            )

        dados = dict(zip(campos, valores))
        return {"operacao": "inserir", "tabela": tabela, "dados": dados}

    def _parse_lista_valores(self, texto: str) -> list:
        """
        Divide a lista de valores, respeitando strings com aspas simples.
        Ex: "'Lucas', 'hash...', 'professor'" → ['Lucas', 'hash...', 'professor']
        """
        valores = []
        i = 0
        atual = []
        dentro_string = False

        while i < len(texto):
            ch = texto[i]
            if ch == "'" and not dentro_string:
                dentro_string = True
                i += 1
                continue
            elif ch == "'" and dentro_string:
                dentro_string = False
                valores.append("".join(atual).strip())
                atual = []
                i += 1
                continue
            elif ch == "," and not dentro_string:
                valor_str = "".join(atual).strip()
                if valor_str:
                    valores.append(self._converter_literal(valor_str))
                atual = []
                i += 1
                continue
            atual.append(ch)
            i += 1

        resto = "".join(atual).strip()
        if resto:
            valores.append(self._converter_literal(resto))

        return valores

    def _converter_literal(self, texto: str) -> Any:
        """Converte literais SCEDS para valores Python."""
        texto = texto.strip()
        lower = texto.lower()
        if lower in ("verdadeiro", "true"):
            return True
        if lower in ("falso", "false"):
            return False
        if lower == "nulo" or lower == "null":
            return None
        try:
            return int(texto)
        except ValueError:
            pass
        try:
            return float(texto)
        except ValueError:
            pass
        return texto


    def _parse_buscar(self, cmd: str) -> dict:
        """
        BUSCAR * DE tabela [ONDE campo = valor [E campo = valor ...]]
        """
        padrao = re.compile(
            r"BUSCAR\s+\*\s+DE\s+(\w+)(?:\s+ONDE\s+(.+))?$",
            re.IGNORECASE
        )
        m = padrao.match(cmd)
        if not m:
            raise SyntaxError(f"Sintaxe inválida para BUSCAR:\n{cmd}")

        tabela = m.group(1)
        onde = {}
        if m.group(2):
            onde = self._parse_condicoes(m.group(2))

        return {"operacao": "buscar", "tabela": tabela, "onde": onde}

    def _parse_condicoes(self, texto: str) -> dict:
        """
        Analisa a cláusula ONDE com múltiplas condições unidas por 'E'.
        Suporta apenas igualdade (campo = valor) por ora.
        """
        condicoes = {}
        partes = re.split(r"\bE\b", texto, flags=re.IGNORECASE)
        for parte in partes:
            parte = parte.strip()
            m = re.match(r"(\w+)\s*=\s*(.+)", parte)
            if not m:
                raise SyntaxError(f"Condição inválida: '{parte}'")
            campo = m.group(1).strip()
            valor_str = m.group(2).strip().strip("'")
            condicoes[campo] = self._converter_literal(valor_str)
        return condicoes


    def _parse_atualizar(self, cmd: str) -> dict:
        """
        ATUALIZAR tabela DEFINIR campo = valor [, campo = valor] ONDE campo = valor
        """
        padrao = re.compile(
            r"ATUALIZAR\s+(\w+)\s+DEFINIR\s+(.+?)\s+ONDE\s+(.+)$",
            re.IGNORECASE
        )
        m = padrao.match(cmd)
        if not m:
            raise SyntaxError(f"Sintaxe inválida para ATUALIZAR:\n{cmd}")

        tabela = m.group(1)
        atribuicoes_raw = m.group(2)
        onde_raw = m.group(3)

        novos_dados = self._parse_atribuicoes(atribuicoes_raw)
        onde = self._parse_condicoes(onde_raw)

        return {"operacao": "atualizar", "tabela": tabela, "novos_dados": novos_dados, "onde": onde}

    def _parse_atribuicoes(self, texto: str) -> dict:
        """campo1 = val1, campo2 = val2 → dict"""
        resultado = {}
        for parte in texto.split(","):
            parte = parte.strip()
            m = re.match(r"(\w+)\s*=\s*(.+)", parte)
            if not m:
                raise SyntaxError(f"Atribuição inválida: '{parte}'")
            campo = m.group(1).strip()
            valor_str = m.group(2).strip().strip("'")
            resultado[campo] = self._converter_literal(valor_str)
        return resultado


    def _parse_deletar(self, cmd: str) -> dict:
        """
        DELETAR DE tabela ONDE campo = valor
        """
        padrao = re.compile(
            r"DELETAR\s+DE\s+(\w+)\s+ONDE\s+(.+)$",
            re.IGNORECASE
        )
        m = padrao.match(cmd)
        if not m:
            raise SyntaxError(f"Sintaxe inválida para DELETAR:\n{cmd}")

        tabela = m.group(1)
        onde = self._parse_condicoes(m.group(2))

        return {"operacao": "deletar", "tabela": tabela, "onde": onde}
