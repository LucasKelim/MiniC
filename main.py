#!/usr/bin/env python3
"""Interface de linha de comando (CLI) do compilador MiniC."""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict

from compiler.ast_nodes import format_ast
from compiler.codegen import ARM64CodeGenerator, CCodeGenerator, X86CodeGenerator
from compiler.diagnostics import ErrorReporter
from compiler.ir_gen import IRGenerator
from compiler.lexer import Lexer
from compiler.optimizer import IROptimizer
from compiler.parser import Parser
from compiler.semantic import SemanticAnalyzer


TARGET_EXTENSIONS: Dict[str, str] = {
    "arm64": "_arm64.s",
    "x86": "_x86.asm",
    "c": ".c",
}


def format_tokens_table(tokens) -> str:
    header = f"{'#':>4}  {'LIN:COL':<8}  {'TOKEN':<14}  {'LEXEMA':<18}  VALOR"
    sep = "-" * len(header) + "------------"
    rows = [header, sep]
    for idx, tok in enumerate(tokens, start=1):
        pos = f"{tok.line}:{tok.column}"
        val = "" if tok.value is None else repr(tok.value)
        rows.append(f"{idx:>4}  {pos:<8}  {tok.type.name:<14}  {tok.lexeme!r:<18}  {val}")
    return "\n".join(rows)


def generate_for_target(target: str, ir_program) -> str:
    if target == "arm64":
        return ARM64CodeGenerator().generate(ir_program)
    if target == "x86":
        return X86CodeGenerator().generate(ir_program)
    return CCodeGenerator().generate(ir_program)


def compile_and_run(target: str, src_path: Path, bin_path: Path) -> int:
    """Monta/compila com clang salvando o executável em build/ e executa no host."""
    if target == "x86":
        print(
            "Nota: o alvo 'x86' (IA-32) é didático e alinhado aos slides; "
            "para executar nativamente neste Mac, use '--target arm64 --run' ou '--target c --run'.",
            file=sys.stderr,
        )
        return 1

    cmd = ["clang", str(src_path), "-o", str(bin_path)]
    build = subprocess.run(cmd, capture_output=True, text=True)
    if build.returncode != 0:
        print(f"Erro ao montar/compilar código gerado ({target}):", file=sys.stderr)
        print(build.stderr, file=sys.stderr)
        return build.returncode

    print(f"Executável ({target}) gerado em: {bin_path}")
    print("--- Saída da execução ---")
    run_proc = subprocess.run([str(bin_path)])
    return run_proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compilador MiniC — Inspeção por fases e geração de código multi-alvo."
    )
    parser.add_argument("source", type=Path, help="Arquivo fonte .mc")
    parser.add_argument("--tokens", action="store_true", help="Exibe os tokens (Fase 1).")
    parser.add_argument("--ast", action="store_true", help="Exibe a AST anotada (Fases 2/3).")
    parser.add_argument("--symtab", action="store_true", help="Exibe a Tabela de Símbolos (Fase 3).")
    parser.add_argument("--ir", action="store_true", help="Exibe o TAC original (Fase 4).")
    parser.add_argument("--ir-opt", action="store_true", help="Exibe o TAC otimizado + métricas (Fase 5).")
    parser.add_argument("--asm", action="store_true", help="Exibe o código alvo gerado no terminal (Fase 6).")
    parser.add_argument("--all", action="store_true", help="Exibe todas as fases do compilador.")
    parser.add_argument("--no-opt", action="store_true", help="Desativa otimizações da Fase 5.")
    parser.add_argument(
        "--target",
        choices=("arm64", "x86", "c"),
        default="arm64",
        help="Arquitetura/linguagem alvo do back-end (padrão: arm64).",
    )
    parser.add_argument(
        "--all-targets",
        action="store_true",
        help="Gera e salva os 3 alvos (ARM64, x86 e C) de uma só vez na pasta de saída.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("build"),
        help="Pasta onde os arquivos gerados são salvos (padrão: build/).",
    )
    parser.add_argument("-o", "--output", type=Path, help="Caminho exato para salvar o código gerado.")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compila com clang (salva o binário em build/) e executa o programa gerado.",
    )
    args = parser.parse_args()

    if args.all:
        args.tokens = args.ast = args.symtab = args.ir = args.ir_opt = args.asm = True

    if not args.source.exists():
        print(f"Erro: arquivo '{args.source}' não encontrado.", file=sys.stderr)
        return 1

    code = args.source.read_text(encoding="utf-8")
    reporter = ErrorReporter(code)

    # Fase 1: Análise Léxica
    tokens = Lexer(code, reporter).tokenize()
    if args.tokens:
        print("=== FASE 1: ANÁLISE LÉXICA (TOKENS) ===")
        print(format_tokens_table(tokens))
        print()

    # Fase 2: Análise Sintática
    ast = Parser(tokens, reporter).parse()

    # Fase 3: Análise Semântica
    symtab = None
    if not reporter.has_errors():
        symtab = SemanticAnalyzer(reporter).analyze(ast)

    if args.ast:
        titulo = "=== FASE 2/3: AST ANOTADA (TIPOS E COERÇÕES) ===" if symtab else "=== FASE 2: AST ==="
        print(titulo)
        print(format_ast(ast))
        print()

    if args.symtab and symtab is not None:
        print("=== FASE 3: TABELA DE SÍMBOLOS ===")
        print(symtab.format_table())
        if symtab.classes:
            print()
            print("=== TABELA DE CLASSES (LAYOUT DE OBJETOS) ===")
            print(symtab.format_classes())
        print()

    if reporter.has_errors():
        print(f"=== ERROS ENCONTRADOS ({len(reporter.errors)}) ===", file=sys.stderr)
        print(reporter.format_all(), file=sys.stderr)
        return 1

    # Fase 4: Geração de Código Intermediário (TAC)
    ir_raw = IRGenerator(symtab.classes if symtab is not None else None).generate(ast)
    if args.ir:
        print("=== FASE 4: CÓDIGO INTERMEDIÁRIO (TAC ORIGINAL) ===")
        print(ir_raw.format())
        print(
            f"\n[Estatísticas TAC Original] {ir_raw.instruction_count()} instruções, "
            f"{ir_raw.temp_count()} temporárias."
        )
        print()

    # Fase 5: Otimização de Código Intermediário
    if args.no_opt:
        ir_final = ir_raw
        opt_stats = None
    else:
        optimizer = IROptimizer()
        ir_final = optimizer.optimize(ir_raw)
        opt_stats = optimizer.stats

    if args.ir_opt:
        print("=== FASE 5: CÓDIGO INTERMEDIÁRIO (TAC OTIMIZADO) ===")
        print(ir_final.format())
        if opt_stats is not None:
            print("\n" + opt_stats.format_report())
        print()

    # Fase 6: Geração de Código Alvo (salva automaticamente em build/ ou -o)
    targets = ("arm64", "x86", "c") if args.all_targets else (args.target,)
    saved_paths: Dict[str, Path] = {}

    for tgt in targets:
        generated = generate_for_target(tgt, ir_final)

        if args.output and not args.all_targets:
            out_path = args.output
        else:
            out_path = args.out_dir / f"{args.source.stem}{TARGET_EXTENSIONS[tgt]}"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(generated, encoding="utf-8")
        saved_paths[tgt] = out_path

        if args.asm:
            print(f"=== FASE 6: GERAÇÃO DE CÓDIGO ALVO ({tgt.upper()}) ===")
            print(generated)
            print()

        print(f"Código alvo ({tgt}) salvo em: {out_path}")

    if args.run:
        run_target = args.target
        src_path = saved_paths[run_target]
        bin_path = src_path.parent / f"{args.source.stem}_{run_target}"
        return compile_and_run(run_target, src_path, bin_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
