"""Fase 4: Estruturas da Representação Intermediária — Código de Três Endereços (TAC)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Operand:
    """Representa um operando em uma instrução TAC."""

    kind: str       # "var", "temp", "const", "label", "func"
    value: Any
    data_type: str  # "int", "float", "bool", "string", "void", "label"

    def __str__(self) -> str:
        if self.kind == "const":
            if self.data_type == "string":
                escaped = (
                    str(self.value)
                    .replace("\\", "\\\\")
                    .replace("\n", "\\n")
                    .replace("\t", "\\t")
                    .replace('"', '\\"')
                )
                return f'"{escaped}"'
            if self.data_type == "bool":
                return "true" if self.value else "false"
            if self.data_type == "null":
                return "null"
            return str(self.value)
        return str(self.value)


BINARY_OPS = {
    "+", "-", "*", "/", "%",
    "==", "!=", "<", "<=", ">", ">=",
}


@dataclass
class IRInstruction:
    """Instrução de Código de Três Endereços (TAC).

    Exemplos de formato textual:
      t1 = intToFloat(60)
      t2 = taxa * t1
      posicao = t3
      ifFalse t4 goto L1
      goto L2
      L1:
      param p
      t5 = call calcularPosicao, 2
      return t5
      print t5
      read x
    """

    op: str
    result: Optional[Operand] = None
    arg1: Optional[Operand] = None
    arg2: Optional[Operand] = None
    data_type: Optional[str] = None

    def format(self) -> str:
        if self.op == "label":
            return f"{self.result}:"
        if self.op == "goto":
            return f"    goto {self.result}"
        if self.op == "ifFalse":
            return f"    ifFalse {self.arg1} goto {self.result}"
        if self.op == "ifTrue":
            return f"    ifTrue {self.arg1} goto {self.result}"
        if self.op == "assign":
            return f"    {self.result} = {self.arg1}"
        if self.op == "intToFloat":
            return f"    {self.result} = intToFloat({self.arg1})"
        if self.op == "neg":
            return f"    {self.result} = -{self.arg1}"
        if self.op == "not":
            return f"    {self.result} = !{self.arg1}"
        if self.op in BINARY_OPS:
            return f"    {self.result} = {self.arg1} {self.op} {self.arg2}"
        if self.op == "param":
            return f"    param {self.arg1}"
        if self.op == "call":
            if self.result is not None:
                return f"    {self.result} = call {self.arg1}, {self.arg2}"
            return f"    call {self.arg1}, {self.arg2}"
        if self.op == "return":
            if self.arg1 is not None:
                return f"    return {self.arg1}"
            return "    return"
        if self.op == "print":
            return f"    print {self.arg1}"
        if self.op == "println":
            return "    println"
        if self.op == "read":
            return f"    read {self.result}"
        if self.op == "alloc":
            return f"    {self.result} = alloc {self.arg1}"
        if self.op == "load_field":
            return f"    {self.result} = {self.arg1}[{self.arg2}]"
        if self.op == "store_field":
            return f"    {self.result}[{self.arg1}] = {self.arg2}"
        if self.op == "load_index":
            return f"    {self.result} = {self.arg1}[{self.arg2}]"
        if self.op == "store_index":
            return f"    {self.result}[{self.arg1}] = {self.arg2}"
        return f"    {self.op} {self.result} {self.arg1} {self.arg2}"


@dataclass
class IRFunction:
    """Representação TAC de uma função compilada."""

    name: str
    return_type: str
    params: List[Tuple[str, str]]               # [(unique_name, data_type), ...]
    locals: Dict[str, str] = field(default_factory=dict)  # {name_or_temp: data_type}
    instructions: List[IRInstruction] = field(default_factory=list)

    def format(self) -> str:
        params_str = ", ".join(f"{t} {n}" for n, t in self.params)
        lines = [f"func {self.name}({params_str}) -> {self.return_type}:"]
        for instr in self.instructions:
            lines.append(instr.format())
        lines.append(f"endfunc {self.name}")
        return "\n".join(lines)


@dataclass
class IRProgram:
    """Programa completo em Código de Três Endereços (TAC)."""

    globals: List[Tuple[str, str, Any]] = field(default_factory=list)  # [(name, type, default_val)]
    global_inits: List[IRInstruction] = field(default_factory=list)
    functions: List[IRFunction] = field(default_factory=list)

    def instruction_count(self) -> int:
        total = len(self.global_inits)
        for fn in self.functions:
            total += len(fn.instructions)
        return total

    def temp_count(self) -> int:
        temps = set()
        for fn in self.functions:
            for instr in fn.instructions:
                for op in (instr.result, instr.arg1, instr.arg2):
                    if op is not None and op.kind == "temp":
                        temps.add((fn.name, op.value))
        return len(temps)

    def format(self) -> str:
        sections: List[str] = []
        if self.globals:
            g_lines = ["; Variáveis globais"]
            for name, dtype, val in self.globals:
                g_lines.append(f"global {dtype} {name} = {val!r}")
            sections.append("\n".join(g_lines))
        if self.global_inits:
            init_lines = ["; Inicialização global"]
            for instr in self.global_inits:
                init_lines.append(instr.format())
            sections.append("\n".join(init_lines))
        for fn in self.functions:
            sections.append(fn.format())
        return "\n\n".join(sections)
