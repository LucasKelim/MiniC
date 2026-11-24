"""Back-end C: traduz TAC (Código de Três Endereços) para código C portável."""

from typing import Dict, List, Set

from ..ir import BINARY_OPS, IRFunction, IRInstruction, IRProgram, Operand


C_TYPES: Dict[str, str] = {
    "int": "long long",
    "float": "double",
    "bool": "int",
    "string": "const char*",
    "void": "void",
}


class CCodeGenerator:
    """Gera código C99 estruturado diretamente a partir do TAC otimizado."""

    def generate(self, program: IRProgram) -> str:
        lines: List[str] = [
            "/* Código C gerado automaticamente pelo Compilador MiniC (Back-end C) */",
            "#include <stdio.h>",
            "#include <stdlib.h>",
            "#include <string.h>",
            "",
        ]

        global_names: Set[str] = {name for name, _, _ in program.globals}

        # 1. Variáveis globais
        if program.globals:
            lines.append("/* Variáveis globais */")
            for name, dtype, val in program.globals:
                ctype = self._ctype(dtype)
                cval = self._format_const(val, dtype)
                lines.append(f"static {ctype} g_{name} = {cval};")
            lines.append("")

        # 2. Protótipos de funções (permite chamadas em qualquer ordem)
        for fn in program.functions:
            if fn.name == "main":
                continue
            lines.append(self._func_signature(fn) + ";")
        if any(fn.name != "main" for fn in program.functions):
            lines.append("")

        # 3. Definições de funções
        for fn in program.functions:
            lines.extend(self._gen_function(fn, global_names))
            lines.append("")

        return "\n".join(lines)

    def _ctype(self, dtype: str) -> str:
        return C_TYPES.get(dtype, "void*")

    def _func_name(self, name: str) -> str:
        return "main" if name == "main" else f"mc_{name}"

    def _func_signature(self, fn: IRFunction) -> str:
        ret = "int" if fn.name == "main" else self._ctype(fn.return_type)
        if not fn.params:
            params_str = "void"
        else:
            params_str = ", ".join(f"{self._ctype(t)} v_{n}" for n, t in fn.params)
        return f"{ret} {self._func_name(fn.name)}({params_str})"

    def _gen_function(self, fn: IRFunction, global_names: Set[str]) -> List[str]:
        lines: List[str] = [self._func_signature(fn) + " {"]
        param_names = {n for n, _ in fn.params}

        # Declaração de variáveis locais e temporárias
        for name, dtype in sorted(fn.locals.items()):
            if name in param_names or name in global_names:
                continue
            default = self._format_const(self._default_for(dtype), dtype)
            lines.append(f"    {self._ctype(dtype)} v_{name} = {default};")

        if fn.locals:
            lines.append("")

        pending_params: List[Operand] = []

        for instr in fn.instructions:
            if instr.op == "param" and instr.arg1 is not None:
                pending_params.append(instr.arg1)
                continue

            lines.extend(self._gen_instruction(instr, global_names, pending_params))
            if instr.op == "call":
                pending_params.clear()

        lines.append("}")
        return lines

    def _gen_instruction(
        self,
        instr: IRInstruction,
        global_names: Set[str],
        pending_params: List[Operand],
    ) -> List[str]:
        op = instr.op
        if op == "label":
            return [f"{instr.result.value}: ;"]
        if op == "goto":
            return [f"    goto {instr.result.value};"]
        if op == "ifFalse":
            cond = self._op(instr.arg1, global_names)
            return [f"    if (!({cond})) goto {instr.result.value};"]
        if op == "ifTrue":
            cond = self._op(instr.arg1, global_names)
            return [f"    if ({cond}) goto {instr.result.value};"]
        if op == "assign":
            dst = self._op(instr.result, global_names)
            src = self._op(instr.arg1, global_names)
            return [f"    {dst} = {src};"]
        if op == "intToFloat":
            dst = self._op(instr.result, global_names)
            src = self._op(instr.arg1, global_names)
            return [f"    {dst} = (double)({src});"]
        if op == "neg":
            dst = self._op(instr.result, global_names)
            src = self._op(instr.arg1, global_names)
            return [f"    {dst} = -({src});"]
        if op == "not":
            dst = self._op(instr.result, global_names)
            src = self._op(instr.arg1, global_names)
            return [f"    {dst} = !({src});"]
        if op in BINARY_OPS:
            dst = self._op(instr.result, global_names)
            lhs = self._op(instr.arg1, global_names)
            rhs = self._op(instr.arg2, global_names)
            if op in ("==", "!=") and instr.arg1 and instr.arg1.data_type == "string":
                cmp_op = "==" if op == "==" else "!="
                return [f"    {dst} = (strcmp({lhs}, {rhs}) {cmp_op} 0);"]
            return [f"    {dst} = ({lhs} {op} {rhs});"]
        if op == "call":
            args_str = ", ".join(self._op(p, global_names) for p in pending_params)
            callee = self._func_name(instr.arg1.value)
            if instr.result is not None:
                dst = self._op(instr.result, global_names)
                return [f"    {dst} = {callee}({args_str});"]
            return [f"    {callee}({args_str});"]
        if op == "return":
            if instr.arg1 is not None:
                val = self._op(instr.arg1, global_names)
                return [f"    return {val};"]
            return ["    return;"]
        if op == "print":
            val = self._op(instr.arg1, global_names)
            dtype = instr.arg1.data_type if instr.arg1 else "int"
            if dtype == "int":
                return [f'    printf("%lld", (long long)({val}));']
            if dtype == "float":
                return [f'    printf("%g", (double)({val}));']
            if dtype == "bool":
                return [f'    printf("%s", ({val}) ? "true" : "false");']
            return [f'    printf("%s", {val});']
        if op == "println":
            return ['    printf("\\n");']
        if op == "read":
            dst = self._op(instr.result, global_names)
            dtype = instr.result.data_type if instr.result else "int"
            if dtype == "float":
                return [f'    scanf("%lf", &{dst});']
            if dtype == "bool":
                return [f'    {{ long long _b = 0; scanf("%lld", &_b); {dst} = (_b != 0); }}']
            return [f'    scanf("%lld", &{dst});']
        if op == "alloc":
            dst = self._op(instr.result, global_names)
            size = self._op(instr.arg1, global_names)
            return [f"    {dst} = calloc(1, (size_t)({size}));"]
        if op == "load_field":
            dst = self._op(instr.result, global_names)
            obj = self._op(instr.arg1, global_names)
            off = self._op(instr.arg2, global_names)
            ctype = self._ctype(instr.data_type or "int")
            return [f"    {dst} = *({ctype}*)((unsigned char*)({obj}) + (size_t)({off}));"]
        if op == "store_field":
            obj = self._op(instr.result, global_names)
            off = self._op(instr.arg1, global_names)
            val = self._op(instr.arg2, global_names)
            ctype = self._ctype(instr.data_type or "int")
            return [f"    *({ctype}*)((unsigned char*)({obj}) + (size_t)({off})) = {val};"]
        if op == "load_index":
            dst = self._op(instr.result, global_names)
            arr = self._op(instr.arg1, global_names)
            idx = self._op(instr.arg2, global_names)
            ctype = self._ctype(instr.data_type or "int")
            return [f"    {dst} = *({ctype}*)((unsigned char*)({arr}) + 8 + (size_t)({idx}) * 8);"]
        if op == "store_index":
            arr = self._op(instr.result, global_names)
            idx = self._op(instr.arg1, global_names)
            val = self._op(instr.arg2, global_names)
            ctype = self._ctype(instr.data_type or "int")
            return [f"    *({ctype}*)((unsigned char*)({arr}) + 8 + (size_t)({idx}) * 8) = {val};"]
        return [f"    /* instrução desconhecida: {op} */"]

    def _op(self, operand: Operand, global_names: Set[str]) -> str:
        if operand.kind == "const":
            return self._format_const(operand.value, operand.data_type)
        if operand.kind == "var" and operand.value in global_names:
            return f"g_{operand.value}"
        return f"v_{operand.value}"

    def _format_const(self, value, dtype: str) -> str:
        if dtype == "null" or dtype not in C_TYPES:
            return "NULL"
        if dtype == "string":
            escaped = (
                str(value)
                .replace("\\", "\\\\")
                .replace("\n", "\\n")
                .replace("\t", "\\t")
                .replace('"', '\\"')
            )
            return f'"{escaped}"'
        if dtype == "bool":
            return "1" if value else "0"
        if dtype == "float":
            return repr(float(value))
        return f"{int(value)}LL"

    def _default_for(self, dtype: str):
        return {"int": 0, "float": 0.0, "bool": False, "string": ""}.get(dtype, None)
