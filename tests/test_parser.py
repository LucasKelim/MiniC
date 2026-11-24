"""Testes unitários da Fase 2 — Analisador Sintático (Parser) e AST."""

import unittest

from compiler.ast_nodes import (
    AssignExpr,
    BinaryExpr,
    CallExpr,
    ExprStmt,
    ForStmt,
    FuncDecl,
    IfStmt,
    LiteralExpr,
    PrintStmt,
    ReadStmt,
    ReturnStmt,
    UnaryExpr,
    VarDecl,
    VarExpr,
    WhileStmt,
    format_ast,
)
from compiler.diagnostics import ErrorReporter
from compiler.lexer import Lexer
from compiler.parser import Parser


class TestParser(unittest.TestCase):
    def _parse(self, code: str):
        reporter = ErrorReporter(code)
        tokens = Lexer(code, reporter).tokenize()
        program = Parser(tokens, reporter).parse()
        return program, reporter

    def test_operator_precedence_mul_over_add(self):
        # 1 + 2 * 3 deve gerar +(1, *(2, 3))
        prog, rep = self._parse("int main() { int x = 1 + 2 * 3; return x; }")
        self.assertFalse(rep.has_errors())
        func = prog.declarations[0]
        self.assertIsInstance(func, FuncDecl)
        decl = func.body.statements[0]
        self.assertIsInstance(decl, VarDecl)
        expr = decl.initializer
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.operator, "+")
        self.assertIsInstance(expr.left, LiteralExpr)
        self.assertEqual(expr.left.value, 1)
        self.assertIsInstance(expr.right, BinaryExpr)
        self.assertEqual(expr.right.operator, "*")
        self.assertEqual(expr.right.left.value, 2)
        self.assertEqual(expr.right.right.value, 3)

    def test_left_associativity_subtraction_addition(self):
        # 9 - 5 + 2 (exemplo clássico do PDF 05) deve gerar +(-(9, 5), 2) = 6
        prog, rep = self._parse("int main() { int r = 9 - 5 + 2; }")
        self.assertFalse(rep.has_errors())
        expr = prog.declarations[0].body.statements[0].initializer
        self.assertEqual(expr.operator, "+")
        self.assertEqual(expr.left.operator, "-")
        self.assertEqual(expr.left.left.value, 9)
        self.assertEqual(expr.left.right.value, 5)
        self.assertEqual(expr.right.value, 2)

    def test_right_associativity_assignment(self):
        # a = b = 10 deve gerar a = (b = 10)
        prog, rep = self._parse("int main() { a = b = 10; }")
        self.assertFalse(rep.has_errors())
        stmt = prog.declarations[0].body.statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        self.assertIsInstance(stmt.expr, AssignExpr)
        self.assertEqual(stmt.expr.name, "a")
        self.assertIsInstance(stmt.expr.value, AssignExpr)
        self.assertEqual(stmt.expr.value.name, "b")
        self.assertEqual(stmt.expr.value.value.value, 10)

    def test_control_flow_and_io(self):
        code = """
        int g = 5;
        void teste(int n) {
            int i = 0;
            read(n);
            if (n > 0 && !false) {
                while (i < n) {
                    print("i =", i);
                    i = i + 1;
                }
            } else {
                for (int k = 0; k < 3; k = k + 1) {
                    print(-k);
                }
            }
            return;
        }
        """
        prog, rep = self._parse(code)
        self.assertFalse(rep.has_errors(), rep.format_all())
        self.assertEqual(len(prog.declarations), 2)
        self.assertIsInstance(prog.declarations[0], VarDecl)
        func = prog.declarations[1]
        self.assertIsInstance(func, FuncDecl)
        stmts = func.body.statements
        self.assertIsInstance(stmts[0], VarDecl)
        self.assertIsInstance(stmts[1], ReadStmt)
        self.assertIsInstance(stmts[2], IfStmt)
        self.assertIsInstance(stmts[2].then_branch.statements[0], WhileStmt)
        self.assertIsInstance(stmts[2].else_branch.statements[0], ForStmt)
        for_body_print = stmts[2].else_branch.statements[0].body.statements[0]
        self.assertIsInstance(for_body_print, PrintStmt)
        self.assertIsInstance(for_body_print.args[0], UnaryExpr)
        self.assertIsInstance(stmts[3], ReturnStmt)
        self.assertIsNone(stmts[3].value)

    def test_function_call_and_ast_formatting(self):
        prog, rep = self._parse("int main() { int x = soma(1, 2 + 3); }")
        self.assertFalse(rep.has_errors())
        call = prog.declarations[0].body.statements[0].initializer
        self.assertIsInstance(call, CallExpr)
        self.assertEqual(call.callee, "soma")
        self.assertEqual(len(call.args), 2)
        rendered = format_ast(prog)
        self.assertIn("FuncDecl(int main())", rendered)
        self.assertIn("Call(soma)", rendered)

    def test_multiple_syntax_errors_recovery(self):
        code = """
        int main() {
            int x = 10
            if x > 5) {
                print(x);
            }
            return 0;
        }
        """
        prog, rep = self._parse(code)
        self.assertGreaterEqual(len(rep.errors), 2)
        # Mesmo com erros anteriores, o parser se recuperou e reconheceu o 'return 0;'
        func = prog.declarations[0]
        self.assertTrue(any(isinstance(s, ReturnStmt) for s in func.body.statements))


if __name__ == "__main__":
    unittest.main()
