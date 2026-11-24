"""Fase 1: Analisador Léxico (Scanner) baseado em Autômato Finito Determinístico (AFD)."""

from typing import List, Optional

from .diagnostics import ErrorReporter
from .tokens import KEYWORDS, Token, TokenType


class Lexer:
    """Converte o código-fonte em uma sequência de tokens.

    Responsabilidades:
    - Ler o fluxo de caracteres da esquerda para a direita.
    - Eliminar espaços em branco e comentários (// e /* ... */).
    - Reconhecer lexemas (identificadores, palavras-chave, números, strings, operadores).
    - Rastrear linha e coluna para diagnósticos precisos.
    - Recuperar-se de erros léxicos para reportar todos os problemas de uma só vez.
    """

    def __init__(self, source: str, reporter: Optional[ErrorReporter] = None) -> None:
        self.source = source
        self.length = len(source)
        self.pos = 0
        self.line = 1
        self.column = 1
        self.reporter = reporter if reporter is not None else ErrorReporter(source)

    def _is_at_end(self) -> bool:
        return self.pos >= self.length

    def _peek(self) -> str:
        if self._is_at_end():
            return "\0"
        return self.source[self.pos]

    def _peek_next(self) -> str:
        if self.pos + 1 >= self.length:
            return "\0"
        return self.source[self.pos + 1]

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _match(self, expected: str) -> bool:
        if self._is_at_end() or self.source[self.pos] != expected:
            return False
        self._advance()
        return True

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        while not self._is_at_end():
            self._skip_whitespace_and_comments()
            if self._is_at_end():
                break

            token = self._scan_token()
            if token is not None:
                tokens.append(token)

        tokens.append(Token(TokenType.EOF, "", None, self.line, self.column))
        return tokens

    def _skip_whitespace_and_comments(self) -> None:
        while not self._is_at_end():
            ch = self._peek()
            if ch in (" ", "\t", "\r", "\n"):
                self._advance()
            elif ch == "/" and self._peek_next() == "/":
                # Comentário de linha: ignora até '\n'
                while not self._is_at_end() and self._peek() != "\n":
                    self._advance()
            elif ch == "/" and self._peek_next() == "*":
                # Comentário de bloco: /* ... */
                start_line, start_col = self.line, self.column
                self._advance()  # '/'
                self._advance()  # '*'
                closed = False
                while not self._is_at_end():
                    if self._peek() == "*" and self._peek_next() == "/":
                        self._advance()
                        self._advance()
                        closed = True
                        break
                    self._advance()
                if not closed:
                    self.reporter.report(
                        "LÉXICO",
                        "Comentário de bloco '/*' não foi fechado antes do fim do arquivo.",
                        start_line,
                        start_col,
                    )
            else:
                break

    def _scan_token(self) -> Optional[Token]:
        start_line = self.line
        start_col = self.column
        ch = self._advance()

        # 1. Identificadores e palavras reservadas: [a-zA-Z_][a-zA-Z0-9_]*
        if ch.isalpha() or ch == "_":
            return self._scan_identifier(ch, start_line, start_col)

        # 2. Números inteiros e reais: [0-9]+ ('.' [0-9]+)?
        if ch.isdigit():
            return self._scan_number(ch, start_line, start_col)

        # 3. Literais de string: "..."
        if ch == '"':
            return self._scan_string(start_line, start_col)

        # 4. Operadores de 1 ou 2 caracteres (lookahead de 1 caractere)
        if ch == "+":
            if self._match("+"):
                return Token(TokenType.PLUS_PLUS, "++", None, start_line, start_col)
            if self._match("="):
                return Token(TokenType.PLUS_EQ, "+=", None, start_line, start_col)
            return Token(TokenType.PLUS, "+", None, start_line, start_col)
        if ch == "-":
            if self._match("-"):
                return Token(TokenType.MINUS_MINUS, "--", None, start_line, start_col)
            if self._match("="):
                return Token(TokenType.MINUS_EQ, "-=", None, start_line, start_col)
            return Token(TokenType.MINUS, "-", None, start_line, start_col)
        if ch == "*":
            if self._match("="):
                return Token(TokenType.STAR_EQ, "*=", None, start_line, start_col)
            return Token(TokenType.STAR, "*", None, start_line, start_col)
        if ch == "/":
            if self._match("="):
                return Token(TokenType.SLASH_EQ, "/=", None, start_line, start_col)
            return Token(TokenType.SLASH, "/", None, start_line, start_col)
        if ch == "%":
            if self._match("="):
                return Token(TokenType.PERCENT_EQ, "%=", None, start_line, start_col)
            return Token(TokenType.PERCENT, "%", None, start_line, start_col)
        if ch == "(":
            return Token(TokenType.LPAREN, "(", None, start_line, start_col)
        if ch == ")":
            return Token(TokenType.RPAREN, ")", None, start_line, start_col)
        if ch == "{":
            return Token(TokenType.LBRACE, "{", None, start_line, start_col)
        if ch == "}":
            return Token(TokenType.RBRACE, "}", None, start_line, start_col)
        if ch == "[":
            return Token(TokenType.LBRACKET, "[", None, start_line, start_col)
        if ch == "]":
            return Token(TokenType.RBRACKET, "]", None, start_line, start_col)
        if ch == ";":
            return Token(TokenType.SEMICOLON, ";", None, start_line, start_col)
        if ch == ",":
            return Token(TokenType.COMMA, ",", None, start_line, start_col)

        if ch == "=":
            if self._match("="):
                return Token(TokenType.EQ, "==", None, start_line, start_col)
            return Token(TokenType.ASSIGN, "=", None, start_line, start_col)

        if ch == "!":
            if self._match("="):
                return Token(TokenType.NEQ, "!=", None, start_line, start_col)
            return Token(TokenType.NOT, "!", None, start_line, start_col)

        if ch == "<":
            if self._match("="):
                return Token(TokenType.LTE, "<=", None, start_line, start_col)
            return Token(TokenType.LT, "<", None, start_line, start_col)

        if ch == ">":
            if self._match("="):
                return Token(TokenType.GTE, ">=", None, start_line, start_col)
            return Token(TokenType.GT, ">", None, start_line, start_col)

        if ch == "&":
            if self._match("&"):
                return Token(TokenType.AND, "&&", None, start_line, start_col)
            self.reporter.report(
                "LÉXICO",
                "Operador '&' isolado não suportado; você quis dizer '&&'?",
                start_line,
                start_col,
            )
            return None

        if ch == "|":
            if self._match("|"):
                return Token(TokenType.OR, "||", None, start_line, start_col)
            self.reporter.report(
                "LÉXICO",
                "Operador '|' isolado não suportado; você quis dizer '||'?",
                start_line,
                start_col,
            )
            return None

        if ch == ".":
            return Token(TokenType.DOT, ".", None, start_line, start_col)

        # Caractere fora do alfabeto da linguagem — reporta e segue adiante
        self.reporter.report(
            "LÉXICO",
            f"Caractere inválido '{ch}'.",
            start_line,
            start_col,
        )
        return None

    def _scan_identifier(self, first: str, start_line: int, start_col: int) -> Token:
        chars = [first]
        while not self._is_at_end() and (self._peek().isalnum() or self._peek() == "_"):
            chars.append(self._advance())
        lexeme = "".join(chars)

        token_type = KEYWORDS.get(lexeme, TokenType.ID)
        if token_type == TokenType.TRUE:
            return Token(token_type, lexeme, True, start_line, start_col)
        if token_type == TokenType.FALSE:
            return Token(token_type, lexeme, False, start_line, start_col)
        if token_type == TokenType.ID:
            return Token(TokenType.ID, lexeme, lexeme, start_line, start_col)
        return Token(token_type, lexeme, None, start_line, start_col)

    def _scan_number(self, first: str, start_line: int, start_col: int) -> Optional[Token]:
        chars = [first]
        while not self._is_at_end() and self._peek().isdigit():
            chars.append(self._advance())

        is_float = False
        if self._peek() == ".":
            is_float = True
            chars.append(self._advance())  # consome '.'
            if not self._peek().isdigit():
                # Ex: "10." sem dígitos após o ponto
                lexeme = "".join(chars)
                self.reporter.report(
                    "LÉXICO",
                    f"Número real malformado '{lexeme}': esperado dígito após o ponto decimal.",
                    start_line,
                    start_col,
                )
                return None
            while not self._is_at_end() and self._peek().isdigit():
                chars.append(self._advance())

            # Detecta segundo ponto indevido (ex: 10.5.2)
            if self._peek() == ".":
                while not self._is_at_end() and (self._peek().isdigit() or self._peek() == "."):
                    chars.append(self._advance())
                lexeme = "".join(chars)
                self.reporter.report(
                    "LÉXICO",
                    f"Número real malformado '{lexeme}': múltiplos pontos decimais.",
                    start_line,
                    start_col,
                )
                return None

        # Detecta identificador colado ao número (ex: 123abc)
        if self._peek().isalpha() or self._peek() == "_":
            while not self._is_at_end() and (self._peek().isalnum() or self._peek() == "_"):
                chars.append(self._advance())
            lexeme = "".join(chars)
            self.reporter.report(
                "LÉXICO",
                f"Identificador ou número inválido '{lexeme}': identificadores não podem começar com dígito.",
                start_line,
                start_col,
            )
            return None

        lexeme = "".join(chars)
        if is_float:
            return Token(TokenType.FLOAT_LIT, lexeme, float(lexeme), start_line, start_col)
        return Token(TokenType.INT_LIT, lexeme, int(lexeme), start_line, start_col)

    def _scan_string(self, start_line: int, start_col: int) -> Optional[Token]:
        raw_chars = ['"']
        value_chars: List[str] = []
        escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}

        while not self._is_at_end() and self._peek() != '"':
            ch = self._peek()
            if ch == "\n":
                self.reporter.report(
                    "LÉXICO",
                    "Literal de string não fechado antes do fim da linha.",
                    start_line,
                    start_col,
                )
                return None
            if ch == "\\":
                raw_chars.append(self._advance())
                if self._is_at_end():
                    break
                esc = self._advance()
                raw_chars.append(esc)
                if esc in escapes:
                    value_chars.append(escapes[esc])
                else:
                    self.reporter.report(
                        "LÉXICO",
                        f"Sequência de escape desconhecida '\\{esc}'.",
                        self.line,
                        self.column - 1,
                    )
                    value_chars.append(esc)
            else:
                ch = self._advance()
                raw_chars.append(ch)
                value_chars.append(ch)

        if self._is_at_end():
            self.reporter.report(
                "LÉXICO",
                "Literal de string não fechado antes do fim do arquivo.",
                start_line,
                start_col,
            )
            return None

        raw_chars.append(self._advance())  # consome '"' final
        return Token(
            TokenType.STRING_LIT,
            "".join(raw_chars),
            "".join(value_chars),
            start_line,
            start_col,
        )
