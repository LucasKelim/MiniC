"""Testes unitários da Fase 1 — Analisador Léxico."""

import unittest

from compiler.diagnostics import ErrorReporter
from compiler.lexer import Lexer
from compiler.tokens import TokenType


class TestLexer(unittest.TestCase):
    def _lex(self, code: str):
        reporter = ErrorReporter(code)
        tokens = Lexer(code, reporter).tokenize()
        return tokens, reporter

    def test_classic_slide_expression(self):
        tokens, reporter = self._lex("posicao = inicial + taxa * 60;")
        self.assertFalse(reporter.has_errors())
        types = [t.type for t in tokens]
        self.assertEqual(
            types,
            [
                TokenType.ID,
                TokenType.ASSIGN,
                TokenType.ID,
                TokenType.PLUS,
                TokenType.ID,
                TokenType.STAR,
                TokenType.INT_LIT,
                TokenType.SEMICOLON,
                TokenType.EOF,
            ],
        )
        self.assertEqual(tokens[0].value, "posicao")
        self.assertEqual(tokens[6].value, 60)

    def test_keywords_and_literals(self):
        code = 'int float bool string void if else while for return true false print read 42 3.14 "oi\\n"'
        tokens, reporter = self._lex(code)
        self.assertFalse(reporter.has_errors())
        expected = [
            TokenType.INT,
            TokenType.FLOAT,
            TokenType.BOOL,
            TokenType.STRING,
            TokenType.VOID,
            TokenType.IF,
            TokenType.ELSE,
            TokenType.WHILE,
            TokenType.FOR,
            TokenType.RETURN,
            TokenType.TRUE,
            TokenType.FALSE,
            TokenType.PRINT,
            TokenType.READ,
            TokenType.INT_LIT,
            TokenType.FLOAT_LIT,
            TokenType.STRING_LIT,
            TokenType.EOF,
        ]
        self.assertEqual([t.type for t in tokens], expected)
        self.assertEqual(tokens[14].value, 42)
        self.assertAlmostEqual(tokens[15].value, 3.14)
        self.assertEqual(tokens[16].value, "oi\n")

    def test_operators_and_delimiters(self):
        code = "+ - * / % == != < <= > >= && || ! = ( ) { } ; ,"
        tokens, reporter = self._lex(code)
        self.assertFalse(reporter.has_errors())
        expected = [
            TokenType.PLUS,
            TokenType.MINUS,
            TokenType.STAR,
            TokenType.SLASH,
            TokenType.PERCENT,
            TokenType.EQ,
            TokenType.NEQ,
            TokenType.LT,
            TokenType.LTE,
            TokenType.GT,
            TokenType.GTE,
            TokenType.AND,
            TokenType.OR,
            TokenType.NOT,
            TokenType.ASSIGN,
            TokenType.LPAREN,
            TokenType.RPAREN,
            TokenType.LBRACE,
            TokenType.RBRACE,
            TokenType.SEMICOLON,
            TokenType.COMMA,
            TokenType.EOF,
        ]
        self.assertEqual([t.type for t in tokens], expected)

    def test_comments_and_line_tracking(self):
        code = "// linha 1\nint a = 1; /* bloco\nlinha 3 */\nint b = 2;"
        tokens, reporter = self._lex(code)
        self.assertFalse(reporter.has_errors())
        self.assertEqual(tokens[0].line, 2)
        self.assertEqual(tokens[0].column, 1)
        # 'int' da linha 4
        b_int = [t for t in tokens if t.type == TokenType.INT][1]
        self.assertEqual(b_int.line, 4)
        self.assertEqual(b_int.column, 1)

    def test_multiple_lexical_errors_recovery(self):
        code = "int 9abc = 1 @ 2;\nfloat a = 1.2.3;\nbool ok = true & false;"
        tokens, reporter = self._lex(code)
        self.assertEqual(len(reporter.errors), 4)
        # Mesmo com erros, tokens válidos da última linha continuam sendo reconhecidos
        self.assertIn(TokenType.FALSE, [t.type for t in tokens])

    def test_unterminated_block_comment(self):
        _, reporter = self._lex("int x = 1; /* sem fim")
        self.assertEqual(len(reporter.errors), 1)
        self.assertIn("Comentário de bloco", reporter.errors[0].message)


if __name__ == "__main__":
    unittest.main()
