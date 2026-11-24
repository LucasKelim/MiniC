"""Definição dos tipos de tokens e palavras reservadas da linguagem MiniC."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict


class TokenType(Enum):
    # Palavras reservadas (tipos)
    INT = auto()
    FLOAT = auto()
    BOOL = auto()
    STRING = auto()
    VOID = auto()

    # Palavras reservadas (controle de fluxo e funções)
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    FOR = auto()
    RETURN = auto()

    # Palavras reservadas (literais booleanos e E/S nativa)
    TRUE = auto()
    FALSE = auto()
    PRINT = auto()
    READ = auto()

    # Identificadores e literais
    ID = auto()
    INT_LIT = auto()
    FLOAT_LIT = auto()
    STRING_LIT = auto()

    # Operadores aritméticos
    PLUS = auto()       # +
    MINUS = auto()      # -
    STAR = auto()       # *
    SLASH = auto()      # /
    PERCENT = auto()    # %

    # Operadores relacionais
    EQ = auto()         # ==
    NEQ = auto()        # !=
    LT = auto()         # <
    LTE = auto()        # <=
    GT = auto()         # >
    GTE = auto()        # >=

    # Operadores lógicos
    AND = auto()        # &&
    OR = auto()         # ||
    NOT = auto()        # !

    # Atribuição e operadores compostos
    ASSIGN = auto()       # =
    PLUS_EQ = auto()      # +=
    MINUS_EQ = auto()     # -=
    STAR_EQ = auto()      # *=
    SLASH_EQ = auto()     # /=
    PERCENT_EQ = auto()   # %=
    PLUS_PLUS = auto()    # ++
    MINUS_MINUS = auto()  # --

    # Delimitadores e pontuação
    LPAREN = auto()     # (
    RPAREN = auto()     # )
    LBRACE = auto()     # {
    RBRACE = auto()     # }
    LBRACKET = auto()   # [
    RBRACKET = auto()   # ]
    SEMICOLON = auto()  # ;
    COMMA = auto()      # ,

    # Controle de fluxo extra e constantes
    BREAK = auto()
    CONTINUE = auto()
    CONST = auto()

    # Orientação a objetos
    CLASS = auto()
    NEW = auto()
    THIS = auto()
    PUBLIC = auto()
    PRIVATE = auto()
    NULL = auto()
    DOT = auto()        # .

    # Fim de arquivo
    EOF = auto()


KEYWORDS: Dict[str, TokenType] = {
    "int": TokenType.INT,
    "float": TokenType.FLOAT,
    "bool": TokenType.BOOL,
    "string": TokenType.STRING,
    "void": TokenType.VOID,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "const": TokenType.CONST,
    "return": TokenType.RETURN,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "print": TokenType.PRINT,
    "read": TokenType.READ,
    "class": TokenType.CLASS,
    "new": TokenType.NEW,
    "this": TokenType.THIS,
    "public": TokenType.PUBLIC,
    "private": TokenType.PRIVATE,
    "null": TokenType.NULL,
}


@dataclass(frozen=True)
class Token:
    """Representa um token no formato <tipo, lexema, valor, posição>."""

    type: TokenType
    lexeme: str
    value: Any
    line: int
    column: int

    def __str__(self) -> str:
        if self.type in (TokenType.ID, TokenType.INT_LIT, TokenType.FLOAT_LIT, TokenType.STRING_LIT):
            return f"<{self.type.name}, {self.value!r}> ({self.line}:{self.column})"
        return f"<{self.type.name}, {self.lexeme!r}> ({self.line}:{self.column})"
