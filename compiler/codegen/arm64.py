"""Back-end ARM64 (AArch64 macOS / Apple Silicon) nativo e executável via clang.

Convenções respeitadas (Apple Darwin AArch64 ABI):
- Símbolos globais/C com prefixo '_' (_main, _printf, _scanf, _strcmp, _mc_<func>).
- Pilha (sp) sempre alinhada em múltiplos de 16 bytes.
- Argumentos de funções do usuário em x0..x7 (int/bool/string) e d0..d7 (float IEEE 754 64-bit).
- Argumentos variádicos de _printf e _scanf passados na pilha ([sp, #0]).
- Otimização peephole final removendo recargas redundantes str/ldr consecutivas.
"""

import re
import struct
from typing import Dict, List, Optional, Tuple

from ..ir import BINARY_OPS, IRFunction, IRInstruction, IRProgram, Operand


class ARM64CodeGenerator:
    """Traduz TAC otimizado para Assembly ARM64 (macOS Apple Silicon)."""

    def __init__(self) -> None:
        self._strings: List[Tuple[str, str]] = []
        self._floats: List[Tuple[str, float]] = []
        self._str_map: Dict[str, str] = {}
        self._flt_map: Dict[float, str] = {}
        self._local_lbl = 0

    def generate(self, program: IRProgram) -> str:
        self._strings.clear()
        self._floats.clear()
        self._str_map.clear()
        self._flt_map.clear()
        self._local_lbl = 0

        # Registra formatos padrão de E/S na tabela de strings
        self._fmt_int = self._intern_string("%lld")
        self._fmt_flt = self._intern_string("%g")
        self._fmt_str = self._intern_string("%s")
        self._fmt_nl = self._intern_string("\n")
        self._fmt_in_i = self._intern_string("%lld")
        self._fmt_in_f = self._intern_string("%lf")
        self._str_true = self._intern_string("true")
        self._str_false = self._intern_string("false")

        global_types: Dict[str, str] = {name: dtype for name, dtype, _ in program.globals}

        text_lines: List[str] = []
        for fn in program.functions:
            text_lines.extend(self._gen_function(fn, global_types))
            text_lines.append("")

        # Peephole ARM64 (elimina str x0, [sp, #k]; ldr x0, [sp, #k])
        text_lines = self._peephole_arm64(text_lines)

        out: List[str] = [
            "// Assembly ARM64 (AArch64 macOS) gerado pelo Compilador MiniC",
            ".section __TEXT,__text,regular,pure_instructions",
            ".globl _main",
            "",
        ]
        out.extend(text_lines)

        # Constantes IEEE 754 (64-bit double)
        if self._floats:
            out.append(".section __TEXT,__const")
            out.append(".p2align 3")
            for lbl, fval in self._floats:
                bits = struct.unpack("<Q", struct.pack("<d", fval))[0]
                out.append(f"{lbl}:")
                out.append(f"    .quad 0x{bits:016x}    // {fval!r}")
            out.append("")

        # Literais de string
        if self._strings:
            out.append(".section __TEXT,__cstring,cstring_literals")
            for lbl, sval in self._strings:
                out.append(f"{lbl}:")
                out.append(f'    .asciz "{self._escape_asm_string(sval)}"')
            out.append("")

        # Variáveis globais
        if program.globals:
            out.append(".section __DATA,__data")
            out.append(".p2align 3")
            for name, dtype, val in program.globals:
                out.append(f"_g_{name}:")
                if dtype == "float":
                    bits = struct.unpack("<Q", struct.pack("<d", float(val)))[0]
                    out.append(f"    .quad 0x{bits:016x}    // {float(val)!r}")
                elif dtype == "string":
                    lbl = self._intern_string(str(val))
                    out.append(f"    .quad {lbl}")
                elif dtype == "bool":
                    out.append(f"    .quad {1 if val else 0}")
                else:
                    out.append(f"    .quad {int(val)}")
            out.append("")

        return "\n".join(out)

    # ------------------------------------------------------------------
    # Funções e layout de pilha
    # ------------------------------------------------------------------

    def _fn_symbol(self, name: str) -> str:
        return "_main" if name == "main" else f"_mc_{name}"

    def _gen_function(self, fn: IRFunction, global_types: Dict[str, str]) -> List[str]:
        sym = self._fn_symbol(fn.name)
        lines: List[str] = [".p2align 2", f"{sym}:"]

        # [sp, #0..15] reservado para argumentos variádicos de _printf/_scanf (Darwin ABI)
        # Variáveis locais, parâmetros e temporárias ficam em [sp, #16], [sp, #24], ...
        slots: Dict[str, int] = {}
        offset = 16

        for pname, _ in fn.params:
            slots[pname] = offset
            offset += 8

        for lname in sorted(fn.locals.keys()):
            if lname not in slots and lname not in global_types:
                slots[lname] = offset
                offset += 8

        # Alinha tamanho do frame a múltiplo de 16 bytes
        frame_size = (offset + 15) & ~15

        # Prólogo
        lines.append("    stp x29, x30, [sp, #-16]!")
        lines.append("    mov x29, sp")
        lines.extend(self._sub_sp(frame_size))

        # Salva parâmetros recebidos em x0..x7 e d0..d7 nos respectivos slots locais
        int_idx = 0
        flt_idx = 0
        for pname, ptype in fn.params:
            slot_off = slots[pname]
            if ptype == "float":
                lines.extend(self._store_slot_f(f"d{flt_idx}", slot_off))
                flt_idx += 1
            else:
                lines.extend(self._store_slot_i(f"x{int_idx}", slot_off))
                int_idx += 1

        pending_params: List[Operand] = []

        for instr in fn.instructions:
            if instr.op == "param" and instr.arg1 is not None:
                pending_params.append(instr.arg1)
                continue

            lines.append(f"    // TAC: {instr.format().strip()}")
            lines.extend(self._gen_instruction(instr, fn, slots, global_types, pending_params))
            if instr.op == "call":
                pending_params.clear()

        # Epílogo
        lines.append(f"L_{fn.name}_epilogue:")
        lines.extend(self._add_sp(frame_size))
        lines.append("    ldp x29, x30, [sp], #16")
        lines.append("    ret")
        return lines

    # ------------------------------------------------------------------
    # Instruções TAC -> ARM64
    # ------------------------------------------------------------------

    def _gen_instruction(
        self,
        instr: IRInstruction,
        fn: IRFunction,
        slots: Dict[str, int],
        global_types: Dict[str, str],
        pending_params: List[Operand],
    ) -> List[str]:
        op = instr.op

        if op == "label":
            return [f"L_{fn.name}_{instr.result.value}:"]
        if op == "goto":
            return [f"    b L_{fn.name}_{instr.result.value}"]
        if op == "ifFalse":
            return self._load_int(instr.arg1, "x0", slots, global_types) + [
                f"    cbz x0, L_{fn.name}_{instr.result.value}"
            ]
        if op == "ifTrue":
            return self._load_int(instr.arg1, "x0", slots, global_types) + [
                f"    cbnz x0, L_{fn.name}_{instr.result.value}"
            ]
        if op == "assign":
            if instr.data_type == "float":
                return (
                    self._load_float(instr.arg1, "d0", slots, global_types)
                    + self._store_float(instr.result, "d0", slots, global_types)
                )
            return (
                self._load_int(instr.arg1, "x0", slots, global_types)
                + self._store_int(instr.result, "x0", slots, global_types)
            )
        if op == "intToFloat":
            return (
                self._load_int(instr.arg1, "x0", slots, global_types)
                + ["    scvtf d0, x0"]
                + self._store_float(instr.result, "d0", slots, global_types)
            )
        if op == "neg":
            if instr.data_type == "float":
                return (
                    self._load_float(instr.arg1, "d0", slots, global_types)
                    + ["    fneg d0, d0"]
                    + self._store_float(instr.result, "d0", slots, global_types)
                )
            return (
                self._load_int(instr.arg1, "x0", slots, global_types)
                + ["    neg x0, x0"]
                + self._store_int(instr.result, "x0", slots, global_types)
            )
        if op == "not":
            return (
                self._load_int(instr.arg1, "x0", slots, global_types)
                + ["    cmp x0, #0", "    cset x0, eq"]
                + self._store_int(instr.result, "x0", slots, global_types)
            )
        if op in BINARY_OPS:
            return self._gen_binary(instr, slots, global_types)
        if op == "call":
            lines: List[str] = []
            int_idx = 0
            flt_idx = 0
            for arg in pending_params:
                if arg.data_type == "float":
                    lines.extend(self._load_float(arg, f"d{flt_idx}", slots, global_types))
                    flt_idx += 1
                else:
                    lines.extend(self._load_int(arg, f"x{int_idx}", slots, global_types))
                    int_idx += 1
            lines.append(f"    bl {self._fn_symbol(instr.arg1.value)}")
            if instr.result is not None:
                if instr.data_type == "float":
                    lines.extend(self._store_float(instr.result, "d0", slots, global_types))
                else:
                    lines.extend(self._store_int(instr.result, "x0", slots, global_types))
            return lines
        if op == "return":
            lines = []
            if instr.arg1 is not None:
                if instr.arg1.data_type == "float":
                    lines.extend(self._load_float(instr.arg1, "d0", slots, global_types))
                else:
                    lines.extend(self._load_int(instr.arg1, "x0", slots, global_types))
            lines.append(f"    b L_{fn.name}_epilogue")
            return lines
        if op == "print":
            return self._gen_print(instr.arg1, slots, global_types)
        if op == "println":
            return self._load_addr(self._fmt_nl, "x0") + ["    bl _printf"]
        if op == "read":
            return self._gen_read(instr.result, slots, global_types)
        if op == "alloc":
            return (
                ["    mov x0, #1"]
                + self._load_int(instr.arg1, "x1", slots, global_types)
                + ["    bl _calloc"]
                + self._store_int(instr.result, "x0", slots, global_types)
            )
        if op == "load_field":
            off = int(instr.arg2.value)
            lines = self._load_int(instr.arg1, "x10", slots, global_types)
            if instr.data_type == "float":
                lines.append(f"    ldr d0, [x10, #{off}]")
                lines.extend(self._store_float(instr.result, "d0", slots, global_types))
            else:
                lines.append(f"    ldr x0, [x10, #{off}]")
                lines.extend(self._store_int(instr.result, "x0", slots, global_types))
            return lines
        if op == "store_field":
            off = int(instr.arg1.value)
            lines = self._load_int(instr.result, "x10", slots, global_types)
            if instr.data_type == "float":
                lines.extend(self._load_float(instr.arg2, "d0", slots, global_types))
                lines.append(f"    str d0, [x10, #{off}]")
            else:
                lines.extend(self._load_int(instr.arg2, "x0", slots, global_types))
                lines.append(f"    str x0, [x10, #{off}]")
            return lines
        if op == "load_index":
            lines = (
                self._load_int(instr.arg1, "x10", slots, global_types)
                + self._load_int(instr.arg2, "x11", slots, global_types)
                + ["    add x11, x11, #1", "    lsl x11, x11, #3", "    add x10, x10, x11"]
            )
            if instr.data_type == "float":
                lines.append("    ldr d0, [x10]")
                lines.extend(self._store_float(instr.result, "d0", slots, global_types))
            else:
                lines.append("    ldr x0, [x10]")
                lines.extend(self._store_int(instr.result, "x0", slots, global_types))
            return lines
        if op == "store_index":
            lines = (
                self._load_int(instr.result, "x10", slots, global_types)
                + self._load_int(instr.arg1, "x11", slots, global_types)
                + ["    add x11, x11, #1", "    lsl x11, x11, #3", "    add x10, x10, x11"]
            )
            if instr.data_type == "float":
                lines.extend(self._load_float(instr.arg2, "d0", slots, global_types))
                lines.append("    str d0, [x10]")
            else:
                lines.extend(self._load_int(instr.arg2, "x0", slots, global_types))
                lines.append("    str x0, [x10]")
            return lines
        return []

    def _gen_binary(
        self, instr: IRInstruction, slots: Dict[str, int], global_types: Dict[str, str]
    ) -> List[str]:
        op = instr.op
        ltype = instr.arg1.data_type if instr.arg1 else "int"

        # Comparação de strings via _strcmp
        if ltype == "string" and op in ("==", "!="):
            cond = "eq" if op == "==" else "ne"
            return (
                self._load_int(instr.arg1, "x0", slots, global_types)
                + self._load_int(instr.arg2, "x1", slots, global_types)
                + ["    bl _strcmp", "    cmp w0, #0", f"    cset x0, {cond}"]
                + self._store_int(instr.result, "x0", slots, global_types)
            )

        # Operações em ponto flutuante (IEEE 754 double em d0, d1)
        if ltype == "float":
            lines = (
                self._load_float(instr.arg1, "d0", slots, global_types)
                + self._load_float(instr.arg2, "d1", slots, global_types)
            )
            if op in ("+", "-", "*", "/"):
                arm_op = {"+": "fadd", "-": "fsub", "*": "fmul", "/": "fdiv"}[op]
                lines.append(f"    {arm_op} d0, d0, d1")
                lines.extend(self._store_float(instr.result, "d0", slots, global_types))
                return lines
            cond = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}[op]
            lines.extend(["    fcmp d0, d1", f"    cset x0, {cond}"])
            lines.extend(self._store_int(instr.result, "x0", slots, global_types))
            return lines

        # Operações inteiras / booleanas (64-bit x0, x1)
        lines = (
            self._load_int(instr.arg1, "x0", slots, global_types)
            + self._load_int(instr.arg2, "x1", slots, global_types)
        )
        if op == "+":
            lines.append("    add x0, x0, x1")
        elif op == "-":
            lines.append("    sub x0, x0, x1")
        elif op == "*":
            lines.append("    mul x0, x0, x1")
        elif op == "/":
            lines.append("    sdiv x0, x0, x1")
        elif op == "%":
            lines.append("    sdiv x2, x0, x1")
            lines.append("    msub x0, x2, x1, x0")
        else:
            cond = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}[op]
            lines.extend(["    cmp x0, x1", f"    cset x0, {cond}"])

        lines.extend(self._store_int(instr.result, "x0", slots, global_types))
        return lines

    def _gen_print(self, arg: Operand, slots: Dict[str, int], global_types: Dict[str, str]) -> List[str]:
        dtype = arg.data_type
        if dtype == "float":
            return (
                self._load_float(arg, "d0", slots, global_types)
                + self._load_addr(self._fmt_flt, "x0")
                + ["    str d0, [sp, #0]", "    bl _printf"]
            )
        if dtype == "bool":
            lbl_f = self._next_lbl("bfalse")
            lbl_e = self._next_lbl("bend")
            return (
                self._load_int(arg, "x1", slots, global_types)
                + [f"    cbz x1, {lbl_f}"]
                + self._load_addr(self._str_true, "x1")
                + [f"    b {lbl_e}", f"{lbl_f}:"]
                + self._load_addr(self._str_false, "x1")
                + [f"{lbl_e}:"]
                + self._load_addr(self._fmt_str, "x0")
                + ["    str x1, [sp, #0]", "    bl _printf"]
            )
        fmt = self._fmt_str if dtype == "string" else self._fmt_int
        return (
            self._load_int(arg, "x1", slots, global_types)
            + self._load_addr(fmt, "x0")
            + ["    str x1, [sp, #0]", "    bl _printf"]
        )

    def _gen_read(self, target: Operand, slots: Dict[str, int], global_types: Dict[str, str]) -> List[str]:
        lines: List[str] = []
        # Endereço do destino em x1
        if target.kind == "var" and target.value in global_types:
            lines.extend(self._load_addr(f"_g_{target.value}", "x1"))
        else:
            off = slots[target.value]
            lines.extend(self._addr_slot("x1", off))

        fmt = self._fmt_in_f if target.data_type == "float" else self._fmt_in_i
        lines.extend(self._load_addr(fmt, "x0"))
        lines.extend(["    str x1, [sp, #0]", "    bl _scanf"])

        if target.data_type == "bool":
            lines.extend(
                self._load_int(target, "x0", slots, global_types)
                + ["    cmp x0, #0", "    cset x0, ne"]
                + self._store_int(target, "x0", slots, global_types)
            )
        return lines

    # ------------------------------------------------------------------
    # Utilitários de carga/armazenamento ARM64
    # ------------------------------------------------------------------

    def _load_int(
        self, op: Operand, reg: str, slots: Dict[str, int], global_types: Dict[str, str]
    ) -> List[str]:
        if op.kind == "const":
            if op.data_type == "null" or op.value is None:
                return [f"    mov {reg}, #0"]
            if op.data_type == "string":
                lbl = self._intern_string(str(op.value))
                return self._load_addr(lbl, reg)
            ival = (1 if op.value else 0) if op.data_type == "bool" else int(op.value)
            return self._load_imm64(reg, ival)
        if op.kind == "var" and op.value in global_types:
            return self._load_addr(f"_g_{op.value}", "x9") + [f"    ldr {reg}, [x9]"]
        return self._load_slot_i(reg, slots[op.value])

    def _store_int(
        self, op: Operand, reg: str, slots: Dict[str, int], global_types: Dict[str, str]
    ) -> List[str]:
        if op.kind == "var" and op.value in global_types:
            return self._load_addr(f"_g_{op.value}", "x9") + [f"    str {reg}, [x9]"]
        return self._store_slot_i(reg, slots[op.value])

    def _load_float(
        self, op: Operand, reg: str, slots: Dict[str, int], global_types: Dict[str, str]
    ) -> List[str]:
        if op.kind == "const":
            lbl = self._intern_float(float(op.value))
            return [f"    adrp x9, {lbl}@PAGE", f"    ldr {reg}, [x9, {lbl}@PAGEOFF]"]
        if op.kind == "var" and op.value in global_types:
            return self._load_addr(f"_g_{op.value}", "x9") + [f"    ldr {reg}, [x9]"]
        return self._load_slot_f(reg, slots[op.value])

    def _store_float(
        self, op: Operand, reg: str, slots: Dict[str, int], global_types: Dict[str, str]
    ) -> List[str]:
        if op.kind == "var" and op.value in global_types:
            return self._load_addr(f"_g_{op.value}", "x9") + [f"    str {reg}, [x9]"]
        return self._store_slot_f(reg, slots[op.value])

    def _load_addr(self, symbol: str, reg: str) -> List[str]:
        return [f"    adrp {reg}, {symbol}@PAGE", f"    add {reg}, {reg}, {symbol}@PAGEOFF"]

    def _load_imm64(self, reg: str, val: int) -> List[str]:
        if 0 <= val <= 65535:
            return [f"    mov {reg}, #{val}"]
        if -65536 <= val < 0:
            return [f"    mov {reg}, #{val}"]
        # Constrói inteiro de 64 bits com movz + movk
        uval = val & 0xFFFFFFFFFFFFFFFF
        lines = [f"    movz {reg}, #{uval & 0xFFFF}"]
        for shift in (16, 32, 48):
            chunk = (uval >> shift) & 0xFFFF
            if chunk != 0:
                lines.append(f"    movk {reg}, #{chunk}, lsl #{shift}")
        return lines

    def _sub_sp(self, size: int) -> List[str]:
        if size <= 4095:
            return [f"    sub sp, sp, #{size}"]
        return self._load_imm64("x9", size) + ["    sub sp, sp, x9"]

    def _add_sp(self, size: int) -> List[str]:
        if size <= 4095:
            return [f"    add sp, sp, #{size}"]
        return self._load_imm64("x9", size) + ["    add sp, sp, x9"]

    def _addr_slot(self, reg: str, off: int) -> List[str]:
        if off <= 4095:
            return [f"    add {reg}, sp, #{off}"]
        return self._load_imm64("x9", off) + [f"    add {reg}, sp, x9"]

    def _load_slot_i(self, reg: str, off: int) -> List[str]:
        if off <= 32760:
            return [f"    ldr {reg}, [sp, #{off}]"]
        return self._load_imm64("x9", off) + [f"    ldr {reg}, [sp, x9]"]

    def _store_slot_i(self, reg: str, off: int) -> List[str]:
        if off <= 32760:
            return [f"    str {reg}, [sp, #{off}]"]
        return self._load_imm64("x9", off) + [f"    str {reg}, [sp, x9]"]

    def _load_slot_f(self, reg: str, off: int) -> List[str]:
        if off <= 32760:
            return [f"    ldr {reg}, [sp, #{off}]"]
        return self._load_imm64("x9", off) + [f"    ldr {reg}, [sp, x9]"]

    def _store_slot_f(self, reg: str, off: int) -> List[str]:
        if off <= 32760:
            return [f"    str {reg}, [sp, #{off}]"]
        return self._load_imm64("x9", off) + [f"    str {reg}, [sp, x9]"]

    # ------------------------------------------------------------------
    # Peephole ARM64 (elimina str reg, [sp, #k] seguido de ldr reg, [sp, #k])
    # ------------------------------------------------------------------

    def _peephole_arm64(self, lines: List[str]) -> List[str]:
        result: List[str] = []
        last_store: Optional[Tuple[str, str]] = None
        str_re = re.compile(r"^\s+str\s+([xd]\d+),\s+(\[sp,\s+#\d+\])$")
        ldr_re = re.compile(r"^\s+ldr\s+([xd]\d+),\s+(\[sp,\s+#\d+\])$")

        for line in lines:
            s = line.strip()
            if not s or s.startswith("//"):
                result.append(line)
                continue
            if s.endswith(":"):
                last_store = None
                result.append(line)
                continue
            m_ldr = ldr_re.match(line)
            if m_ldr and last_store == (m_ldr.group(1), m_ldr.group(2)):
                continue
            m_str = str_re.match(line)
            if m_str:
                last_store = (m_str.group(1), m_str.group(2))
            else:
                last_store = None
            result.append(line)
        return result

    def _intern_string(self, text: str) -> str:
        if text not in self._str_map:
            lbl = f"Lstr_{len(self._strings)}"
            self._str_map[text] = lbl
            self._strings.append((lbl, text))
        return self._str_map[text]

    def _intern_float(self, val: float) -> str:
        if val not in self._flt_map:
            lbl = f"Lflt_{len(self._floats)}"
            self._flt_map[val] = lbl
            self._floats.append((lbl, val))
        return self._flt_map[val]

    def _next_lbl(self, prefix: str) -> str:
        self._local_lbl += 1
        return f"L_{prefix}_{self._local_lbl}"

    def _escape_asm_string(self, text: str) -> str:
        return (
            text.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace('"', '\\"')
        )
