"""Testes end-to-end para Orientação a Objetos (OOP) em MiniC."""

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


def _compile_pipeline(source: str):
    reporter = ErrorReporter(source)
    tokens = Lexer(source, reporter).tokenize()
    ast = Parser(tokens, reporter).parse()
    symtab = SemanticAnalyzer(reporter).analyze(ast)
    return ast, symtab, reporter


class TestOOP(unittest.TestCase):
    def test_oop_arm64_and_c_match_output(self) -> None:
        source = """
        class Ponto {
            public float x;
            public float y;

            public Ponto(float px, float py) {
                this.x = px;
                this.y = py;
            }

            public float soma() {
                return this.x + this.y;
            }
        }

        class Retangulo {
            private Ponto origem;
            private float largura;
            private float altura;

            public Retangulo(Ponto p, float l, float a) {
                this.origem = p;
                this.largura = l;
                this.altura = a;
            }

            private float calcularArea() {
                return this.largura * this.altura;
            }

            public float area() {
                return this.calcularArea();
            }

            public float origemSoma() {
                return this.origem.soma();
            }
        }

        int main() {
            Ponto p = new Ponto(2.5, 3.5);
            Retangulo r = new Retangulo(p, 4, 5.5);
            Retangulo vazio = null;
            print("null:", vazio == null, r != null);
            print("origem:", r.origemSoma());
            print("area:", r.area());
            p.x = 10.0;
            print("nova origem:", r.origemSoma());
            return 0;
        }
        """
        ast, symtab, reporter = _compile_pipeline(source)
        self.assertFalse(reporter.has_errors(), reporter.format_all())

        ir_opt = IROptimizer().optimize(IRGenerator(symtab.classes).generate(ast))

        # Back-end x86
        x86_asm = X86CodeGenerator().generate(ir_opt)
        self.assertIn("extern calloc", x86_asm)
        self.assertIn("call calloc", x86_asm)

        # Back-end ARM64 vs Back-end C
        arm64_asm = ARM64CodeGenerator().generate(ir_opt)
        c_code = CCodeGenerator().generate(ir_opt)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            asm_file = tmp_path / "oop.s"
            arm_bin = tmp_path / "oop_arm64"
            c_file = tmp_path / "oop.c"
            c_bin = tmp_path / "oop_c"

            asm_file.write_text(arm64_asm, encoding="utf-8")
            c_file.write_text(c_code, encoding="utf-8")

            subprocess.run(["clang", str(asm_file), "-o", str(arm_bin)], check=True)
            subprocess.run(["clang", str(c_file), "-o", str(c_bin)], check=True)

            out_arm = subprocess.run([str(arm_bin)], capture_output=True, text=True, check=True).stdout
            out_c = subprocess.run([str(c_bin)], capture_output=True, text=True, check=True).stdout

        expected = "null: true true\norigem: 6\narea: 22\nnova origem: 13.5\n"
        self.assertEqual(out_arm, expected)
        self.assertEqual(out_c, expected)

    def test_private_field_and_method_errors(self) -> None:
        source = """
        class Cofre {
            private int senha;
            public Cofre(int s) {
                this.senha = s;
            }
            private int revelar() {
                return this.senha;
            }
        }
        int main() {
            Cofre c = new Cofre(1234);
            int x = c.senha;
            int y = c.revelar();
            return 0;
        }
        """
        _, _, reporter = _compile_pipeline(source)
        self.assertTrue(reporter.has_errors())
        msgs = reporter.format_all()
        self.assertIn("privado", msgs)
        self.assertEqual(len(reporter.errors), 2)

    def test_this_outside_class_and_wrong_ctor_args(self) -> None:
        source = """
        class Pessoa {
            public int idade;
            public Pessoa(int i) {
                this.idade = i;
            }
        }
        int main() {
            Pessoa p = new Pessoa();
            int x = this.idade;
            print(p);
            return 0;
        }
        """
        _, _, reporter = _compile_pipeline(source)
        self.assertTrue(reporter.has_errors())
        msgs = reporter.format_all()
        self.assertIn("Construtor de 'Pessoa' espera 1 argumento(s)", msgs)
        self.assertIn("'this' só pode ser utilizado dentro de um método ou construtor", msgs)
        self.assertIn("Não é possível imprimir diretamente um objeto", msgs)


if __name__ == "__main__":
    unittest.main()
