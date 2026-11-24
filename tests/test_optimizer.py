"""Testes unitários da Fase 5 — Otimizador de Código Intermediário (TAC)."""

import unittest

from compiler.diagnostics import ErrorReporter
from compiler.ir_gen import IRGenerator
from compiler.lexer import Lexer
from compiler.optimizer import IROptimizer
from compiler.parser import Parser
from compiler.semantic import SemanticAnalyzer


class TestOptimizer(unittest.TestCase):
    def _optimize(self, code: str):
        rep = ErrorReporter(code)
        tokens = Lexer(code, rep).tokenize()
        ast = Parser(tokens, rep).parse()
        self.assertFalse(rep.has_errors(), rep.format_all())
        SemanticAnalyzer(rep).analyze(ast)
        self.assertFalse(rep.has_errors(), rep.format_all())
        raw_ir = IRGenerator().generate(ast)
        opt = IROptimizer()
        opt_ir = opt.optimize(raw_ir)
        return raw_ir, opt_ir, opt.stats

    def test_classic_slide_optimization(self):
        # Deve otimizar:
        #   t1 = intToFloat(60); t2 = taxa * t1; t3 = inicial + t2; posicao = t3; return posicao
        # para:
        #   t2 = taxa * 60.0; posicao = inicial + t2; return posicao
        code = """
        float calc(float inicial, float taxa) {
            float posicao = inicial + taxa * 60;
            return posicao;
        }
        """
        raw, opt, stats = self._optimize(code)
        lines = [ins.format().strip() for ins in opt.functions[0].instructions]
        self.assertEqual(
            lines,
            [
                "t2 = taxa * 60.0",
                "posicao = inicial + t2",
                "return posicao",
            ],
        )
        self.assertLess(stats.instructions_after, stats.instructions_before)
        self.assertGreater(stats.constants_folded, 0)
        self.assertGreater(stats.peephole_fusions, 0)

    def test_constant_folding_and_propagation(self):
        code = """
        int main() {
            int a = 2 + 3 * 4;
            int b = a * 2;
            return b;
        }
        """
        _, opt, _ = self._optimize(code)
        lines = [ins.format().strip() for ins in opt.functions[0].instructions]
        self.assertIn("return 28", lines)

    def test_algebraic_simplifications(self):
        code = """
        int calc(int x) {
            int a = x + 0;
            int b = a * 1;
            int c = b * 0;
            return b + c;
        }
        """
        _, opt, stats = self._optimize(code)
        self.assertGreaterEqual(stats.algebraic_simplifications, 3)
        text = opt.format()
        self.assertNotIn(" * 1", text)
        self.assertNotIn(" + 0", text)

    def test_dead_branch_and_unreachable_code(self):
        code = """
        int main() {
            if (10 < 5) {
                print("morto");
            }
            return 0;
            int x = 42;
            print(x);
        }
        """
        _, opt, stats = self._optimize(code)
        text = opt.format()
        self.assertNotIn("morto", text)
        self.assertNotIn("42", text)
        self.assertGreater(stats.dead_instructions_removed, 0)

    def test_loop_variable_is_not_corrupted_by_const_prop(self):
        code = """
        int main() {
            int i = 0;
            while (i < 5) {
                i = i + 1;
            }
            return i;
        }
        """
        _, opt, _ = self._optimize(code)
        text = opt.format()
        # Dentro do laço (após label), 'i < 5' NÃO pode ser dobrado para '0 < 5'
        self.assertIn("i < 5", text)
        self.assertIn("return i", text)


if __name__ == "__main__":
    unittest.main()
