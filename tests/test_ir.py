"""Testes unitários da Fase 4 — Gerador de Código Intermediário (TAC)."""

import unittest

from compiler.diagnostics import ErrorReporter
from compiler.ir_gen import IRGenerator
from compiler.lexer import Lexer
from compiler.parser import Parser
from compiler.semantic import SemanticAnalyzer


class TestIRGen(unittest.TestCase):
    def _compile_ir(self, code: str):
        rep = ErrorReporter(code)
        tokens = Lexer(code, rep).tokenize()
        ast = Parser(tokens, rep).parse()
        self.assertFalse(rep.has_errors(), rep.format_all())
        SemanticAnalyzer(rep).analyze(ast)
        self.assertFalse(rep.has_errors(), rep.format_all())
        return IRGenerator().generate(ast)

    def test_classic_slide_tac_generation(self):
        # posicao = inicial + taxa * 60 deve gerar intToFloat(60), *, +, =
        code = """
        float calc(float inicial, float taxa) {
            float posicao = inicial + taxa * 60;
            return posicao;
        }
        """
        ir = self._compile_ir(code)
        fn = ir.functions[0]
        lines = [ins.format().strip() for ins in fn.instructions]
        self.assertEqual(
            lines,
            [
                "t1 = intToFloat(60)",
                "t2 = taxa * t1",
                "t3 = inicial + t2",
                "posicao = t3",
                "return posicao",
            ],
        )

    def test_if_else_and_while_control_flow(self):
        code = """
        int main() {
            int i = 0;
            while (i < 3) {
                if (i == 1) {
                    print(i);
                } else {
                    i = i + 1;
                }
                i = i + 1;
            }
            return i;
        }
        """
        ir = self._compile_ir(code)
        ops = [ins.op for ins in ir.functions[0].instructions]
        self.assertIn("label", ops)
        self.assertIn("ifFalse", ops)
        self.assertIn("goto", ops)
        self.assertIn("print", ops)
        self.assertIn("println", ops)

    def test_short_circuit_and_or(self):
        code = """
        int main() {
            bool a = true;
            bool b = false;
            bool r1 = a && b;
            bool r2 = a || b;
            return 0;
        }
        """
        ir = self._compile_ir(code)
        ops = [ins.op for ins in ir.functions[0].instructions]
        self.assertIn("ifFalse", ops)
        self.assertIn("ifTrue", ops)

    def test_recursive_function_call_tac(self):
        code = """
        int fat(int n) {
            if (n <= 1) return 1;
            return n * fat(n - 1);
        }
        """
        ir = self._compile_ir(code)
        text = ir.format()
        self.assertIn("param t", text)
        self.assertIn("call fat, 1", text)


if __name__ == "__main__":
    unittest.main()
