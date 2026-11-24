"""Testes ponta-a-ponta da Fase 6 — Back-ends ARM64, C e x86 (IA-32)."""

import platform
import subprocess
import tempfile
import unittest
from pathlib import Path

from compiler.codegen import ARM64CodeGenerator, CCodeGenerator, X86CodeGenerator
from compiler.diagnostics import ErrorReporter
from compiler.ir_gen import IRGenerator
from compiler.lexer import Lexer
from compiler.optimizer import IROptimizer
from compiler.parser import Parser
from compiler.semantic import SemanticAnalyzer


class TestCodegenEndToEnd(unittest.TestCase):
    def _compile_ir(self, code: str, optimize: bool = True):
        rep = ErrorReporter(code)
        tokens = Lexer(code, rep).tokenize()
        ast = Parser(tokens, rep).parse()
        self.assertFalse(rep.has_errors(), rep.format_all())
        SemanticAnalyzer(rep).analyze(ast)
        self.assertFalse(rep.has_errors(), rep.format_all())
        ir = IRGenerator().generate(ast)
        if optimize:
            ir = IROptimizer().optimize(ir)
        return ir

    def _run_native(self, target: str, ir, stdin_text: str = "") -> str:
        ext = ".s" if target == "arm64" else ".c"
        code = ARM64CodeGenerator().generate(ir) if target == "arm64" else CCodeGenerator().generate(ir)
        with tempfile.TemporaryDirectory(prefix="minic_test_") as tmpdir:
            src = Path(tmpdir) / f"prog{ext}"
            exe = Path(tmpdir) / "prog"
            src.write_text(code, encoding="utf-8")
            build = subprocess.run(["clang", str(src), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, f"Clang falhou ({target}):\n{build.stderr}\n{code}")
            res = subprocess.run([str(exe)], input=stdin_text, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Execução falhou ({target}): {res.stderr}")
            return res.stdout

    def test_arm64_and_c_produce_identical_output_classic_and_recursion(self):
        code = """
        float calcularPosicao(float inicial, float taxa) {
            float posicao = inicial + taxa * 60;
            return posicao;
        }

        int fatorial(int n) {
            if (n <= 1) {
                return 1;
            }
            return n * fatorial(n - 1);
        }

        int main() {
            float p = calcularPosicao(10.5, 2.5);
            print("pos =", p);
            print("fat5 =", fatorial(5));
            int soma = 0;
            for (int i = 1; i <= 5; i = i + 1) {
                soma = soma + i;
            }
            print("soma =", soma);
            print("mod =", 17 % 5, "neg =", -7 / 2);
            print("bool =", p > 100.0 && true, false || false);
            return 0;
        }
        """
        expected = (
            "pos = 160.5\n"
            "fat5 = 120\n"
            "soma = 15\n"
            "mod = 2 neg = -3\n"
            "bool = true false\n"
        )
        ir_opt = self._compile_ir(code, optimize=True)
        ir_raw = self._compile_ir(code, optimize=False)

        out_c_opt = self._run_native("c", ir_opt)
        out_c_raw = self._run_native("c", ir_raw)
        self.assertEqual(out_c_opt, expected)
        self.assertEqual(out_c_raw, expected)

        if platform.machine() == "arm64" and platform.system() == "Darwin":
            out_arm_opt = self._run_native("arm64", ir_opt)
            out_arm_raw = self._run_native("arm64", ir_raw)
            self.assertEqual(out_arm_opt, expected)
            self.assertEqual(out_arm_raw, expected)

    def test_globals_shadowing_and_read_io(self):
        code = """
        int fator = 10;

        int main() {
            int entrada = 0;
            float real_in = 0.0;
            read(entrada);
            read(real_in);
            {
                int fator = 2;
                print("interno =", entrada * fator);
            }
            print("global =", entrada * fator, real_in + 0.5);
            return 0;
        }
        """
        ir = self._compile_ir(code)
        expected = "interno = 14\nglobal = 70 3\n"
        self.assertEqual(self._run_native("c", ir, stdin_text="7 2.5\n"), expected)
        if platform.machine() == "arm64" and platform.system() == "Darwin":
            self.assertEqual(self._run_native("arm64", ir, stdin_text="7 2.5\n"), expected)

    def test_x86_didactic_generation_and_peephole_cost(self):
        code = """
        float calcularPosicao(float inicial, float taxa) {
            float posicao = inicial + taxa * 60;
            return posicao;
        }
        int main() {
            int a = 10;
            int b = a + 5;
            print(b);
            return 0;
        }
        """
        ir = self._compile_ir(code, optimize=True)
        gen = X86CodeGenerator()
        asm = gen.generate(ir)
        self.assertIn("section .data", asm)
        self.assertIn("section .text", asm)
        self.assertIn("fmulp st1, st0", asm)
        self.assertIn("faddp st1, st0", asm)
        self.assertIn("push ebp", asm)
        self.assertLessEqual(gen.cost_report.cost_after, gen.cost_report.cost_before)


if __name__ == "__main__":
    unittest.main()
