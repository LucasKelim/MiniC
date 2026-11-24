"""Testes unitários da Fase 3 — Tabela de Símbolos e Analisador Semântico."""

import unittest

from compiler.ast_nodes import BinaryExpr, IntToFloatExpr, VarDecl
from compiler.diagnostics import ErrorReporter
from compiler.lexer import Lexer
from compiler.parser import Parser
from compiler.semantic import SemanticAnalyzer


class TestSemantic(unittest.TestCase):
    def _analyze(self, code: str):
        reporter = ErrorReporter(code)
        tokens = Lexer(code, reporter).tokenize()
        ast = Parser(tokens, reporter).parse()
        self.assertFalse(reporter.has_errors(), reporter.format_all())
        symtab = SemanticAnalyzer(reporter).analyze(ast)
        return ast, symtab, reporter

    def test_implicit_int_to_float_coercion_like_slides(self):
        # posicao = inicial + taxa * 60 -> 60 deve ser envolvido em IntToFloatExpr
        code = """
        float calc(float inicial, float taxa) {
            float posicao = inicial + taxa * 60;
            return posicao;
        }
        """
        ast, symtab, rep = self._analyze(code)
        self.assertFalse(rep.has_errors(), rep.format_all())

        decl = ast.declarations[0].body.statements[0]
        self.assertIsInstance(decl, VarDecl)
        add_expr = decl.initializer
        self.assertIsInstance(add_expr, BinaryExpr)
        self.assertEqual(add_expr.inferred_type, "float")

        mul_expr = add_expr.right
        self.assertIsInstance(mul_expr, BinaryExpr)
        self.assertEqual(mul_expr.inferred_type, "float")
        self.assertIsInstance(mul_expr.right, IntToFloatExpr)
        self.assertEqual(mul_expr.right.inferred_type, "float")
        self.assertEqual(mul_expr.right.expr.value, 60)

        # Verifica metadados da Tabela de Símbolos
        names = [s.name for s in symtab.all_symbols]
        self.assertEqual(names, ["calc", "inicial", "taxa", "posicao"])
        pos_sym = [s for s in symtab.all_symbols if s.name == "posicao"][0]
        self.assertEqual(pos_sym.scope_level, 1)
        self.assertEqual(pos_sym.size_bytes, 8)
        self.assertEqual(pos_sym.usage_lines, [4])

    def test_nested_scopes_and_shadowing(self):
        # Igual ao exemplo em C do slide 7 do PDF 03 (Tabela de Símbolos)
        code = """
        int g = 1;
        int main() {
            int x = 10;
            {
                float x = 2.5;
                float y = x + g;
            }
            int z = x + 1;
            return z;
        }
        """
        ast, symtab, rep = self._analyze(code)
        self.assertFalse(rep.has_errors(), rep.format_all())
        x_syms = [s for s in symtab.all_symbols if s.name == "x"]
        self.assertEqual(len(x_syms), 2)
        self.assertEqual(x_syms[0].data_type, "int")
        self.assertEqual(x_syms[0].scope_level, 1)
        self.assertEqual(x_syms[1].data_type, "float")
        self.assertEqual(x_syms[1].scope_level, 2)
        self.assertNotEqual(x_syms[0].unique_name, x_syms[1].unique_name)

    def test_recursion_and_forward_function_call(self):
        code = """
        int main() {
            return fat(5);
        }
        int fat(int n) {
            if (n <= 1) return 1;
            return n * fat(n - 1);
        }
        """
        _, _, rep = self._analyze(code)
        self.assertFalse(rep.has_errors(), rep.format_all())

    def test_multiple_semantic_errors_reported(self):
        code = """
        int soma(int a, int b) { return a + b; }
        int main() {
            int x = 10;
            int x = 20;
            int y = naoExiste + 1;
            int n = 3.14;
            int r = soma(1);
            if (x) { print(x); }
            int k = soma + 2;
            return "erro";
        }
        """
        _, _, rep = self._analyze(code)
        self.assertEqual(len(rep.errors), 7, rep.format_all())


if __name__ == "__main__":
    unittest.main()
