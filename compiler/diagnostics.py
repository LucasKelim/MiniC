"""Sistema de diagnósticos e recuperação de erros do compilador MiniC."""

from dataclasses import dataclass
from typing import List


@dataclass
class CompilerError:
    """Representa um erro detectado em qualquer fase da compilação."""

    phase: str       # "LÉXICO", "SINTÁTICO", "SEMÂNTICO"
    message: str
    line: int
    column: int

    def format(self, source_lines: List[str]) -> str:
        header = f"[ERRO {self.phase}] Linha {self.line}, Coluna {self.column}: {self.message}"
        if 1 <= self.line <= len(source_lines):
            code_line = source_lines[self.line - 1]
            pointer = " " * max(0, self.column - 1) + "^"
            return f"{header}\n  {self.line:4d} | {code_line}\n       | {pointer}"
        return header


class ErrorReporter:
    """Acumula erros sem interromper a compilação no primeiro problema."""

    def __init__(self, source: str) -> None:
        self.source_lines: List[str] = source.splitlines()
        self.errors: List[CompilerError] = []

    def report(self, phase: str, message: str, line: int, column: int) -> None:
        self.errors.append(CompilerError(phase=phase, message=message, line=line, column=column))

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def format_all(self) -> str:
        return "\n".join(err.format(self.source_lines) for err in self.errors)
