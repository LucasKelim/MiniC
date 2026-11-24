"""Testes end-to-end para vetores, const, break, continue, ++/-- e +=/-=/*=/=/%."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from compiler.codegen.arm64 import ARM64CodeGenerator
from compiler.codegen.c_backend import CCodeGenerator
from compiler.codegen.x86 import X86CodeGenerator
from compiler.diagnostics import ErrorReporter
from compiler.ir_gen import IRGenerator
from compiler.lexer import Lexer
from compiler.optimizer import IROptimizer
from compiler.parser import Parser
from compiler.semantic import SemanticAnalyzer


def _compile(source: str):
    rep = ErrorReporter(source)
    tokens = Lexer(source, rep).tokenize()
    ast = Parser(tokens, rep).parse()
    symtab = SemanticAnalyzer(rep).analyze(ast)
    return ast, symtab, rep


class TestExtensions(unittest.TestCase):
    def test_arrays_const_break_continue_and_compound_ops_arm64_and_c(self) -> None:
        source = Path("examples/08_vetores_e_controle.mc").read_text(encoding="utf-8")
        ast, symtab, rep = _compile(source)
        self.assertFalse(rep.has_errors(), rep.format_all())

        ir_opt = IROptimizer().optimize(IRGenerator(symtab.classes).generate(ast))

        x86_asm = X86CodeGenerator().generate(ir_opt)
        self.assertIn("[ecx+edx*8+8]", x86_asm)

        arm64_asm = ARM64CodeGenerator().generate(ir_opt)
        c_code = CCodeGenerator().generate(ir_opt)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "prog.s").write_text(arm64_asm, encoding="utf-8")
            (p / "prog.c").write_text(c_code, encoding="utf-8")
            subprocess.run(["clang", str(p / "prog.s"), "-o", str(p / "prog_arm")], check=True)
            subprocess.run(["clang", str(p / "prog.c"), "-o", str(p / "prog_c")], check=True)
            out_arm = subprocess.run([str(p / "prog_arm")], capture_output=True, text=True, check=True).stdout
            out_c = subprocess.run([str(p / "prog_c")], capture_output=True, text=True, check=True).stdout

        expected = (
            "nums[ 0 ] = 3\n"
            "nums[ 2 ] = 19\n"
            "nums[ 3 ] = 25\n"
            "Soma parcial: 47\n"
        )
        self.assertEqual(out_arm, expected)
        self.assertEqual(out_c, expected)

    def test_const_and_break_continue_semantic_errors(self) -> None:
        source = """
        int main() {
            const int X = 10;
            X = 20;
            X++;
            break;
            continue;
            return 0;
        }
        """
        _, _, rep = _compile(source)
        self.assertTrue(rep.has_errors())
        msgs = rep.format_all()
        self.assertIn("Não é possível modificar a constante 'X'", msgs)
        self.assertIn("Comando 'break' só pode ser usado dentro de um laço", msgs)
        self.assertIn("Comando 'continue' só pode ser usado dentro de um laço", msgs)


if __name__ == "__main__":
    unittest.main()
