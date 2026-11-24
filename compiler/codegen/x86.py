"""Back-end x86 (IA-32, sintaxe Intel) didático alinhado aos slides da disciplina.

Referências dos PDFs da matéria:
- 04 - ASSEMBLY Basico.pdf (seções .data/.bss/.text, EAX..EDX, EBP/ESP, push/pop, cmp/jcc)
- 06 - Ponto flutuante.pdf (IEEE 754, pilha FPU x87: FLD, FILD, FADD, FSUB, FMUL, FDIV, FCOMI, FSTP)
- 08 gercod-UFPE Prof. Rangel.pdf (otimização peephole Store/Load e modelo de custo)
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ..ir import BINARY_OPS, IRFunction, IRInstruction, IRProgram, Operand


@dataclass
class X86CostReport:
    """Modelo de custo baseado no PDF 08 (1 + nº de acessos a memória por instrução)."""

    instructions_before_peephole: int = 0
    instructions_after_peephole: int = 0
    peephole_removed: int = 0
    cost_before: int = 0
    cost_after: int = 0


class X86CodeGenerator:
    """Gera Assembly x86 (IA-32) sintaxe Intel a partir do TAC, com peephole e análise de custo."""

    def __init__(self) -> None:
        self._strings: List[Tuple[str, str]] = []
        self._floats: List[Tuple[str, float]] = []
        self._str_map: Dict[str, str] = {}
        self._flt_map: Dict[float, str] = {}
        self._local_label_counter = 0
        self.cost_report = X86CostReport()

    def generate(self, program: IRProgram) -> str:
        self._strings.clear()
        self._floats.clear()
        self._str_map.clear()
        self._flt_map.clear()
        self._local_label_counter = 0

        global_types: Dict[str, str] = {name: dtype for name, dtype, _ in program.globals}
        text_lines: List[str] = []

        for fn in program.functions:
            text_lines.extend(self._gen_function(fn, global_types))
            text_lines.append("")

        # Otimização Peephole no código alvo x86 (PDF 08: elimina mov [slot], eax; mov eax, [slot])
        self.cost_report.instructions_before_peephole = self._count_instructions(text_lines)
        self.cost_report.cost_before = self._compute_cost(text_lines)
        text_lines = self._peephole_x86(text_lines)
        self.cost_report.instructions_after_peephole = self._count_instructions(text_lines)
        self.cost_report.cost_after = self._compute_cost(text_lines)
        self.cost_report.peephole_removed = (
            self.cost_report.instructions_before_peephole
            - self.cost_report.instructions_after_peephole
        )

        # Montagem das seções Intel/NASM (.data, .bss, .text)
        out: List[str] = [
            "; Assembly x86 (IA-32, sintaxe Intel) — Compilador MiniC",
            "; Alinhado aos slides: EAX..EDX, EBP/ESP e FPU x87 (ST(0)..ST(7))",
            f"; Peephole x86: {self.cost_report.instructions_before_peephole} -> "
            f"{self.cost_report.instructions_after_peephole} instruções "
            f"(custo modelo Rangel: {self.cost_report.cost_before} -> {self.cost_report.cost_after})",
            "",
            "extern printf",
            "extern scanf",
            "extern calloc",
            "",
            "section .data",
            '    fmt_int:   db "%d", 0',
            '    fmt_flt:   db "%g", 0',
            '    fmt_str:   db "%s", 0',
            '    fmt_nl:    db 10, 0',
            '    fmt_in_i:  db "%d", 0',
            '    fmt_in_f:  db "%lf", 0',
            '    str_true:  db "true", 0',
            '    str_false: db "false", 0',
        ]

        # Globais inicializadas
        for name, dtype, val in program.globals:
            if dtype == "float":
                out.append(f"    g_{name}: dq {float(val)!r}")
            elif dtype == "string":
                lbl = self._intern_string(str(val))
                out.append(f"    g_{name}: dd {lbl}")
            else:
                ival = (1 if val else 0) if dtype == "bool" else int(val)
                out.append(f"    g_{name}: dd {ival}")

        # Constantes de ponto flutuante (IEEE 754 64-bit)
        for lbl, fval in self._floats:
            out.append(f"    {lbl}: dq {fval!r}")

        # Constantes de string
        for lbl, sval in self._strings:
            out.append(f"    {lbl}: db {self._format_nasm_string(sval)}")

        out.extend([
            "",
            "section .bss",
            "    tmp_i32: resd 1",
            "",
            "section .text",
            "    global main",
            "",
        ])
        out.extend(text_lines)
        return "\n".join(out)

    # ------------------------------------------------------------------
    # Geração por função (convenção cdecl IA-32)
    # ------------------------------------------------------------------

    def _gen_function(self, fn: IRFunction, global_types: Dict[str, str]) -> List[str]:
        fname = "main" if fn.name == "main" else f"mc_{fn.name}"
        lines: List[str] = [f"{fname}:"]

        # Mapeia parâmetros acima de EBP ([ebp+8], [ebp+12], ...) e locais abaixo ([ebp-4], ...)
        slots: Dict[str, str] = {}
        param_offset = 8
        for pname, ptype in fn.params:
            size = 8 if ptype == "float" else 4
            prefix = "qword" if ptype == "float" else "dword"
            slots[pname] = f"{prefix} [ebp+{param_offset}]"
            param_offset += size

        local_offset = 0
        param_names = {p for p, _ in fn.params}
        for lname, ltype in sorted(fn.locals.items()):
            if lname in param_names or lname in global_types:
                continue
            size = 8 if ltype == "float" else 4
            local_offset += size
            prefix = "qword" if ltype == "float" else "dword"
            slots[lname] = f"{prefix} [ebp-{local_offset}]"

        # Prólogo padrão x86 (IA-32)
        lines.append("    push ebp")
        lines.append("    mov ebp, esp")
        if local_offset > 0:
            lines.append(f"    sub esp, {local_offset}")

        pending_params: List[Operand] = []

        for instr in fn.instructions:
            if instr.op == "param" and instr.arg1 is not None:
                pending_params.append(instr.arg1)
                continue

            lines.append(f"    ; TAC: {instr.format().strip()}")
            lines.extend(self._gen_instruction(instr, fn, slots, global_types, pending_params))
            if instr.op == "call":
                pending_params.clear()

        # Epílogo
        lines.append(f".L_{fname}_epilogue:")
        lines.append("    mov esp, ebp")
        lines.append("    pop ebp")
        lines.append("    ret")
        return lines

    def _slot(self, op: Operand, slots: Dict[str, str], global_types: Dict[str, str]) -> str:
        if op.kind == "var" and op.value in global_types:
            prefix = "qword" if op.data_type == "float" else "dword"
            return f"{prefix} [g_{op.value}]"
        return slots[op.value]

    def _load_int(self, op: Operand, reg: str, slots: Dict[str, str], global_types: Dict[str, str]) -> str:
        if op.kind == "const":
            if op.data_type == "null" or op.value is None:
                return f"    mov {reg}, 0"
            if op.data_type == "bool":
                return f"    mov {reg}, {1 if op.value else 0}"
            if op.data_type == "string":
                lbl = self._intern_string(str(op.value))
                return f"    mov {reg}, {lbl}"
            return f"    mov {reg}, {int(op.value)}"
        return f"    mov {reg}, {self._slot(op, slots, global_types)}"

    def _load_float(self, op: Operand, slots: Dict[str, str], global_types: Dict[str, str]) -> str:
        if op.kind == "const":
            lbl = self._intern_float(float(op.value))
            return f"    fld qword [{lbl}]"
        return f"    fld {self._slot(op, slots, global_types)}"

    def _gen_instruction(
        self,
        instr: IRInstruction,
        fn: IRFunction,
        slots: Dict[str, str],
        global_types: Dict[str, str],
        pending_params: List[Operand],
    ) -> List[str]:
        op = instr.op
        fname = "main" if fn.name == "main" else f"mc_{fn.name}"

        if op == "label":
            return [f".{instr.result.value}:"]
        if op == "goto":
            return [f"    jmp .{instr.result.value}"]
        if op == "ifFalse":
            return [
                self._load_int(instr.arg1, "eax", slots, global_types),
                "    cmp eax, 0",
                f"    je .{instr.result.value}",
            ]
        if op == "ifTrue":
            return [
                self._load_int(instr.arg1, "eax", slots, global_types),
                "    cmp eax, 0",
                f"    jne .{instr.result.value}",
            ]
        if op == "assign":
            if instr.data_type == "float":
                return [
                    self._load_float(instr.arg1, slots, global_types),
                    f"    fstp {self._slot(instr.result, slots, global_types)}",
                ]
            return [
                self._load_int(instr.arg1, "eax", slots, global_types),
                f"    mov {self._slot(instr.result, slots, global_types)}, eax",
            ]
        if op == "intToFloat":
            # FILD carrega inteiro da memória na pilha FPU x87 (PDF 06 slide 48!)
            if instr.arg1.kind == "const":
                return [
                    f"    mov dword [tmp_i32], {int(instr.arg1.value)}",
                    "    fild dword [tmp_i32]",
                    f"    fstp {self._slot(instr.result, slots, global_types)}",
                ]
            return [
                f"    fild {self._slot(instr.arg1, slots, global_types)}",
                f"    fstp {self._slot(instr.result, slots, global_types)}",
            ]
        if op == "neg":
            if instr.data_type == "float":
                return [
                    self._load_float(instr.arg1, slots, global_types),
                    "    fchs",
                    f"    fstp {self._slot(instr.result, slots, global_types)}",
                ]
            return [
                self._load_int(instr.arg1, "eax", slots, global_types),
                "    neg eax",
                f"    mov {self._slot(instr.result, slots, global_types)}, eax",
            ]
        if op == "not":
            return [
                self._load_int(instr.arg1, "eax", slots, global_types),
                "    cmp eax, 0",
                "    sete al",
                "    movzx eax, al",
                f"    mov {self._slot(instr.result, slots, global_types)}, eax",
            ]
        if op in BINARY_OPS:
            return self._gen_binary(instr, slots, global_types)
        if op == "call":
            lines: List[str] = []
            bytes_pushed = 0
            # Convenção cdecl: empilha argumentos da direita para a esquerda
            for arg in reversed(pending_params):
                if arg.data_type == "float":
                    lines.append("    sub esp, 8")
                    lines.append(self._load_float(arg, slots, global_types))
                    lines.append("    fstp qword [esp]")
                    bytes_pushed += 8
                else:
                    lines.append(self._load_int(arg, "eax", slots, global_types))
                    lines.append("    push eax")
                    bytes_pushed += 4
            callee = "main" if instr.arg1.value == "main" else f"mc_{instr.arg1.value}"
            lines.append(f"    call {callee}")
            if bytes_pushed > 0:
                lines.append(f"    add esp, {bytes_pushed}")
            if instr.result is not None:
                if instr.data_type == "float":
                    lines.append(f"    fstp {self._slot(instr.result, slots, global_types)}")
                else:
                    lines.append(f"    mov {self._slot(instr.result, slots, global_types)}, eax")
            return lines
        if op == "return":
            lines = []
            if instr.arg1 is not None:
                if instr.arg1.data_type == "float":
                    lines.append(self._load_float(instr.arg1, slots, global_types))
                else:
                    lines.append(self._load_int(instr.arg1, "eax", slots, global_types))
            lines.append(f"    jmp .L_{fname}_epilogue")
            return lines
        if op == "print":
            dtype = instr.arg1.data_type if instr.arg1 else "int"
            if dtype == "float":
                return [
                    "    sub esp, 8",
                    self._load_float(instr.arg1, slots, global_types),
                    "    fstp qword [esp]",
                    "    push fmt_flt",
                    "    call printf",
                    "    add esp, 12",
                ]
            if dtype == "bool":
                lbl_f = self._next_lbl("b_false")
                lbl_e = self._next_lbl("b_end")
                return [
                    self._load_int(instr.arg1, "eax", slots, global_types),
                    "    cmp eax, 0",
                    f"    je .{lbl_f}",
                    "    mov eax, str_true",
                    f"    jmp .{lbl_e}",
                    f".{lbl_f}:",
                    "    mov eax, str_false",
                    f".{lbl_e}:",
                    "    push eax",
                    "    push fmt_str",
                    "    call printf",
                    "    add esp, 8",
                ]
            fmt = "fmt_str" if dtype == "string" else "fmt_int"
            return [
                self._load_int(instr.arg1, "eax", slots, global_types),
                "    push eax",
                f"    push {fmt}",
                "    call printf",
                "    add esp, 8",
            ]
        if op == "println":
            return ["    push fmt_nl", "    call printf", "    add esp, 4"]
        if op == "read":
            dst_slot = self._slot(instr.result, slots, global_types)
            addr_expr = dst_slot.replace("qword ", "").replace("dword ", "")
            fmt = "fmt_in_f" if instr.data_type == "float" else "fmt_in_i"
            return [
                f"    lea eax, {addr_expr}",
                "    push eax",
                f"    push {fmt}",
                "    call scanf",
                "    add esp, 8",
            ]
        if op == "alloc":
            return [
                self._load_int(instr.arg1, "eax", slots, global_types),
                "    push eax",
                "    push 1",
                "    call calloc",
                "    add esp, 8",
                f"    mov {self._slot(instr.result, slots, global_types)}, eax",
            ]
        if op == "load_field":
            off = int(instr.arg2.value)
            lines = [self._load_int(instr.arg1, "ecx", slots, global_types)]
            if instr.data_type == "float":
                lines.append(f"    fld qword [ecx+{off}]")
                lines.append(f"    fstp {self._slot(instr.result, slots, global_types)}")
            else:
                lines.append(f"    mov eax, dword [ecx+{off}]")
                lines.append(f"    mov {self._slot(instr.result, slots, global_types)}, eax")
            return lines
        if op == "store_field":
            off = int(instr.arg1.value)
            lines = [self._load_int(instr.result, "ecx", slots, global_types)]
            if instr.data_type == "float":
                lines.append(self._load_float(instr.arg2, slots, global_types))
                lines.append(f"    fstp qword [ecx+{off}]")
            else:
                lines.append(self._load_int(instr.arg2, "eax", slots, global_types))
                lines.append(f"    mov dword [ecx+{off}], eax")
            return lines
        if op == "load_index":
            lines = [
                self._load_int(instr.arg1, "ecx", slots, global_types),
                self._load_int(instr.arg2, "edx", slots, global_types),
            ]
            if instr.data_type == "float":
                lines.append("    fld qword [ecx+edx*8+8]")
                lines.append(f"    fstp {self._slot(instr.result, slots, global_types)}")
            else:
                lines.append("    mov eax, dword [ecx+edx*8+8]")
                lines.append(f"    mov {self._slot(instr.result, slots, global_types)}, eax")
            return lines
        if op == "store_index":
            lines = [
                self._load_int(instr.result, "ecx", slots, global_types),
                self._load_int(instr.arg1, "edx", slots, global_types),
            ]
            if instr.data_type == "float":
                lines.append(self._load_float(instr.arg2, slots, global_types))
                lines.append("    fstp qword [ecx+edx*8+8]")
            else:
                lines.append(self._load_int(instr.arg2, "eax", slots, global_types))
                lines.append("    mov dword [ecx+edx*8+8], eax")
            return lines
        return []

    def _gen_binary(
        self, instr: IRInstruction, slots: Dict[str, str], global_types: Dict[str, str]
    ) -> List[str]:
        op = instr.op
        is_float = instr.arg1 is not None and instr.arg1.data_type == "float"

        if is_float:
            lines = [
                self._load_float(instr.arg1, slots, global_types),
                self._load_float(instr.arg2, slots, global_types),
            ]
            # Na pilha FPU: ST(1) = arg1, ST(0) = arg2
            if op in ("+", "-", "*", "/"):
                fpu_op = {"+": "faddp", "-": "fsubp", "*": "fmulp", "/": "fdivp"}[op]
                lines.append(f"    {fpu_op} st1, st0")
                lines.append(f"    fstp {self._slot(instr.result, slots, global_types)}")
                return lines
            # Comparação FPU via FCOMIP (PDF 06 slides 41-42)
            # Inverte ordem para comparar ST(0)=arg1 com ST(1)=arg2
            lines = [
                self._load_float(instr.arg2, slots, global_types),
                self._load_float(instr.arg1, slots, global_types),
                "    fcomip st0, st1",
                "    fstp st0",
            ]
            setcc = {"==": "sete", "!=": "setne", "<": "setb", "<=": "setbe", ">": "seta", ">=": "setae"}[op]
            lines.extend([
                f"    {setcc} al",
                "    movzx eax, al",
                f"    mov {self._slot(instr.result, slots, global_types)}, eax",
            ])
            return lines

        # Operações inteiras em EAX / EBX
        lines = [
            self._load_int(instr.arg1, "eax", slots, global_types),
            self._load_int(instr.arg2, "ebx", slots, global_types),
        ]
        if op == "+":
            lines.append("    add eax, ebx")
        elif op == "-":
            lines.append("    sub eax, ebx")
        elif op == "*":
            lines.append("    imul eax, ebx")
        elif op == "/":
            lines.extend(["    cdq", "    idiv ebx"])
        elif op == "%":
            lines.extend(["    cdq", "    idiv ebx", "    mov eax, edx"])
        else:
            setcc = {"==": "sete", "!=": "setne", "<": "setl", "<=": "setle", ">": "setg", ">=": "setge"}[op]
            lines.extend(["    cmp eax, ebx", f"    {setcc} al", "    movzx eax, al"])

        lines.append(f"    mov {self._slot(instr.result, slots, global_types)}, eax")
        return lines

    # ------------------------------------------------------------------
    # Peephole x86 e modelo de custo (PDF 08 — Prof. Rangel)
    # ------------------------------------------------------------------

    def _peephole_x86(self, lines: List[str]) -> List[str]:
        """Elimina recargas redundantes: mov [slot], eax; (comentários); mov eax, [slot]."""
        result: List[str] = []
        last_store: Optional[Tuple[str, str]] = None  # (slot, reg)

        store_re = re.compile(r"^\s+mov\s+((?:dword|qword)\s+\[[^\]]+\]),\s+(eax|ebx|ecx|edx)$")
        load_re = re.compile(r"^\s+mov\s+(eax|ebx|ecx|edx),\s+((?:dword|qword)\s+\[[^\]]+\])$")

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                result.append(line)
                continue
            if stripped.endswith(":"):
                last_store = None
                result.append(line)
                continue

            m_load = load_re.match(line)
            if m_load and last_store is not None:
                reg, slot = m_load.group(1), m_load.group(2)
                if (slot, reg) == last_store:
                    # Redundante! O registrador já contém o valor recém-salvo
                    continue

            m_store = store_re.match(line)
            if m_store:
                last_store = (m_store.group(1), m_store.group(2))
            else:
                last_store = None
            result.append(line)

        return result

    def _count_instructions(self, lines: List[str]) -> int:
        count = 0
        for line in lines:
            s = line.strip()
            if s and not s.startswith(";") and not s.endswith(":"):
                count += 1
        return count

    def _compute_cost(self, lines: List[str]) -> int:
        """Custo = 1 + nº de referências à memória na instrução (PDF 08, pág. 4)."""
        cost = 0
        for line in lines:
            s = line.strip()
            if not s or s.startswith(";") or s.endswith(":"):
                continue
            mem_refs = s.count("[")
            cost += 1 + mem_refs
        return cost

    def _intern_string(self, text: str) -> str:
        if text not in self._str_map:
            lbl = f"str_{len(self._strings)}"
            self._str_map[text] = lbl
            self._strings.append((lbl, text))
        return self._str_map[text]

    def _intern_float(self, val: float) -> str:
        if val not in self._flt_map:
            lbl = f"flt_{len(self._floats)}"
            self._flt_map[val] = lbl
            self._floats.append((lbl, val))
        return self._flt_map[val]

    def _next_lbl(self, prefix: str) -> str:
        self._local_label_counter += 1
        return f"L_{prefix}_{self._local_label_counter}"

    def _format_nasm_string(self, text: str) -> str:
        parts: List[str] = []
        buf: List[str] = []
        for ch in text:
            code = ord(ch)
            if 32 <= code <= 126 and ch not in ('"', "\\"):
                buf.append(ch)
            else:
                if buf:
                    parts.append('"' + "".join(buf) + '"')
                    buf.clear()
                parts.append(str(code))
        if buf:
            parts.append('"' + "".join(buf) + '"')
        parts.append("0")
        return ", ".join(parts)
