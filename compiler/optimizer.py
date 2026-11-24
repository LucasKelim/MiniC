"""Fase 5: Otimizador de Código Intermediário (TAC).

Passagens aplicadas iterativamente até atingir ponto fixo:
1. Dobra de constantes (Constant Folding) e simplificações algébricas.
2. Propagação de constantes dentro de blocos básicos.
3. Otimizações Peephole (fusão de temporárias de uso único, saltos redundantes, x = x).
4. Eliminação de código morto (DCE: código inalcançável, temporárias não lidas e rótulos órfãos).
"""

import copy
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .ir import BINARY_OPS, IRFunction, IRInstruction, IRProgram, Operand


@dataclass
class OptimizationStats:
    """Métricas quantitativas do processo de otimização (antes vs. depois)."""

    instructions_before: int = 0
    instructions_after: int = 0
    temps_before: int = 0
    temps_after: int = 0
    constants_folded: int = 0
    constants_propagated: int = 0
    algebraic_simplifications: int = 0
    peephole_fusions: int = 0
    dead_instructions_removed: int = 0
    iterations: int = 0

    @property
    def reduction_pct(self) -> float:
        if self.instructions_before == 0:
            return 0.0
        return (1.0 - self.instructions_after / self.instructions_before) * 100.0

    def format_report(self) -> str:
        return (
            f"[Relatório de Otimização]\n"
            f"  Instruções TAC : {self.instructions_before} -> {self.instructions_after} "
            f"(-{self.instructions_before - self.instructions_after}, {self.reduction_pct:.1f}% de redução)\n"
            f"  Temporárias    : {self.temps_before} -> {self.temps_after}\n"
            f"  Detalhes       : dobras={self.constants_folded}, "
            f"propagações={self.constants_propagated}, "
            f"algébricas={self.algebraic_simplifications}, "
            f"peephole={self.peephole_fusions}, "
            f"código_morto={self.dead_instructions_removed} "
            f"(em {self.iterations} iteração(ões))"
        )


class IROptimizer:
    """Otimizador independente de máquina operando sobre Código de Três Endereços."""

    def __init__(self, max_iterations: int = 10) -> None:
        self.max_iterations = max_iterations
        self.stats = OptimizationStats()

    def optimize(self, program: IRProgram) -> IRProgram:
        opt_prog = copy.deepcopy(program)
        global_names = {name for name, _, _ in opt_prog.globals}

        self.stats = OptimizationStats(
            instructions_before=opt_prog.instruction_count(),
            temps_before=opt_prog.temp_count(),
        )

        max_iters_used = 0
        for fn in opt_prog.functions:
            iters = self._optimize_function(fn, global_names)
            max_iters_used = max(max_iters_used, iters)

        self.stats.instructions_after = opt_prog.instruction_count()
        self.stats.temps_after = opt_prog.temp_count()
        self.stats.iterations = max_iters_used
        return opt_prog

    def _optimize_function(self, fn: IRFunction, global_names: Set[str]) -> int:
        iterations = 0
        for _ in range(self.max_iterations):
            iterations += 1
            changed = False
            changed |= self._pass_constant_folding_and_algebra(fn)
            changed |= self._pass_constant_propagation(fn, global_names)
            changed |= self._pass_peephole(fn)
            changed |= self._pass_dead_code_elimination(fn)
            if not changed:
                break

        # Limpa temporárias eliminadas da tabela de locais da função
        used_names: Set[str] = {name for name, _ in fn.params}
        for instr in fn.instructions:
            for op in (instr.result, instr.arg1, instr.arg2):
                if op is not None and op.kind in ("var", "temp"):
                    used_names.add(op.value)
        fn.locals = {k: v for k, v in fn.locals.items() if k in used_names}
        return iterations

    # ------------------------------------------------------------------
    # Passagem 1: Dobra de Constantes e Simplificações Algébricas
    # ------------------------------------------------------------------

    def _pass_constant_folding_and_algebra(self, fn: IRFunction) -> bool:
        changed = False
        new_instrs: List[IRInstruction] = []

        for instr in fn.instructions:
            # 1a. Dobra de intToFloat(const) -> float const
            if instr.op == "intToFloat" and instr.arg1 and instr.arg1.kind == "const":
                val = float(instr.arg1.value)
                new_instrs.append(
                    IRInstruction(
                        op="assign",
                        result=instr.result,
                        arg1=Operand("const", val, "float"),
                        data_type="float",
                    )
                )
                self.stats.constants_folded += 1
                changed = True
                continue

            # 1b. Dobra de operadores unários em constantes
            if instr.op == "neg" and instr.arg1 and instr.arg1.kind == "const":
                val = -instr.arg1.value
                dtype = instr.arg1.data_type
                new_instrs.append(
                    IRInstruction(
                        op="assign",
                        result=instr.result,
                        arg1=Operand("const", val, dtype),
                        data_type=dtype,
                    )
                )
                self.stats.constants_folded += 1
                changed = True
                continue

            if instr.op == "not" and instr.arg1 and instr.arg1.kind == "const":
                val = not bool(instr.arg1.value)
                new_instrs.append(
                    IRInstruction(
                        op="assign",
                        result=instr.result,
                        arg1=Operand("const", val, "bool"),
                        data_type="bool",
                    )
                )
                self.stats.constants_folded += 1
                changed = True
                continue

            # 1c. Dobra de operadores binários com ambos operandos constantes
            if (
                instr.op in BINARY_OPS
                and instr.arg1 is not None
                and instr.arg2 is not None
                and instr.arg1.kind == "const"
                and instr.arg2.kind == "const"
            ):
                folded = self._eval_binary_const(instr.op, instr.arg1, instr.arg2)
                if folded is not None:
                    new_instrs.append(
                        IRInstruction(
                            op="assign",
                            result=instr.result,
                            arg1=folded,
                            data_type=folded.data_type,
                        )
                    )
                    self.stats.constants_folded += 1
                    changed = True
                    continue

            # 1d. Simplificações algébricas (x + 0, x * 1, x * 0, x - 0, x / 1, x - x)
            if instr.op in ("+", "-", "*", "/") and instr.arg1 and instr.arg2:
                simplified = self._simplify_algebraic(instr)
                if simplified is not None:
                    new_instrs.append(simplified)
                    self.stats.algebraic_simplifications += 1
                    changed = True
                    continue

            # 1e. Desvios condicionais com condição constante
            if instr.op == "ifFalse" and instr.arg1 and instr.arg1.kind == "const":
                self.stats.constants_folded += 1
                changed = True
                if not bool(instr.arg1.value):
                    new_instrs.append(IRInstruction("goto", result=instr.result))
                # Se condição é True, ifFalse nunca salta -> instrução removida
                continue

            if instr.op == "ifTrue" and instr.arg1 and instr.arg1.kind == "const":
                self.stats.constants_folded += 1
                changed = True
                if bool(instr.arg1.value):
                    new_instrs.append(IRInstruction("goto", result=instr.result))
                # Se condição é False, ifTrue nunca salta -> instrução removida
                continue

            new_instrs.append(instr)

        fn.instructions = new_instrs
        return changed

    def _eval_binary_const(self, op: str, left: Operand, right: Operand) -> Optional[Operand]:
        a, b = left.value, right.value
        dtype = left.data_type
        if op == "+":
            return Operand("const", a + b, dtype)
        if op == "-":
            return Operand("const", a - b, dtype)
        if op == "*":
            return Operand("const", a * b, dtype)
        if op == "/":
            if b == 0:
                return None  # Evita erro em tempo de compilação para divisão por zero
            if dtype == "int":
                # Divisão inteira truncada em direção a zero (padrão C / ARM64 / x86)
                return Operand("const", int(a / b), "int")
            return Operand("const", a / b, "float")
        if op == "%":
            if b == 0:
                return None
            q = int(a / b)
            return Operand("const", a - q * b, "int")
        if op == "==":
            return Operand("const", a == b, "bool")
        if op == "!=":
            return Operand("const", a != b, "bool")
        if op == "<":
            return Operand("const", a < b, "bool")
        if op == "<=":
            return Operand("const", a <= b, "bool")
        if op == ">":
            return Operand("const", a > b, "bool")
        if op == ">=":
            return Operand("const", a >= b, "bool")
        return None

    def _simplify_algebraic(self, instr: IRInstruction) -> Optional[IRInstruction]:
        op = instr.op
        a1, a2 = instr.arg1, instr.arg2
        assert a1 is not None and a2 is not None
        dtype = instr.data_type or a1.data_type

        def is_zero(operand: Operand) -> bool:
            return operand.kind == "const" and operand.data_type in ("int", "float") and operand.value == 0

        def is_one(operand: Operand) -> bool:
            return operand.kind == "const" and operand.data_type in ("int", "float") and operand.value == 1

        if op == "+":
            if is_zero(a2):
                return IRInstruction("assign", result=instr.result, arg1=a1, data_type=dtype)
            if is_zero(a1):
                return IRInstruction("assign", result=instr.result, arg1=a2, data_type=dtype)
        elif op == "-":
            if is_zero(a2):
                return IRInstruction("assign", result=instr.result, arg1=a1, data_type=dtype)
            if dtype == "int" and a1 == a2:
                return IRInstruction("assign", result=instr.result, arg1=Operand("const", 0, "int"), data_type="int")
        elif op == "*":
            if is_one(a2):
                return IRInstruction("assign", result=instr.result, arg1=a1, data_type=dtype)
            if is_one(a1):
                return IRInstruction("assign", result=instr.result, arg1=a2, data_type=dtype)
            if dtype == "int" and (is_zero(a1) or is_zero(a2)):
                return IRInstruction("assign", result=instr.result, arg1=Operand("const", 0, "int"), data_type="int")
        elif op == "/":
            if is_one(a2):
                return IRInstruction("assign", result=instr.result, arg1=a1, data_type=dtype)
        return None

    # ------------------------------------------------------------------
    # Passagem 2: Propagação de Constantes por Bloco Básico
    # ------------------------------------------------------------------

    def _pass_constant_propagation(self, fn: IRFunction, global_names: Set[str]) -> bool:
        changed = False
        const_env: Dict[str, Operand] = {}

        def substitute(op: Optional[Operand]) -> Optional[Operand]:
            nonlocal changed
            if op is not None and op.kind in ("var", "temp") and op.value in const_env:
                self.stats.constants_propagated += 1
                changed = True
                return const_env[op.value]
            return op

        for instr in fn.instructions:
            # Início de novo bloco básico: limpa conhecimento anterior
            if instr.op == "label":
                const_env.clear()
                continue

            # Substitui operandos de leitura conhecidos como constantes
            if instr.op in BINARY_OPS:
                instr.arg1 = substitute(instr.arg1)
                instr.arg2 = substitute(instr.arg2)
            elif instr.op in ("assign", "neg", "not", "intToFloat", "param", "print", "ifFalse", "ifTrue"):
                instr.arg1 = substitute(instr.arg1)
            elif instr.op == "return" and instr.arg1 is not None:
                instr.arg1 = substitute(instr.arg1)
            elif instr.op == "alloc":
                instr.arg1 = substitute(instr.arg1)
            elif instr.op == "store_field":
                instr.arg2 = substitute(instr.arg2)
            elif instr.op == "load_index":
                instr.arg2 = substitute(instr.arg2)
            elif instr.op == "store_index":
                instr.arg1 = substitute(instr.arg1)
                instr.arg2 = substitute(instr.arg2)

            # Atualiza ambiente de constantes após a instrução
            if instr.op == "assign" and instr.result and instr.result.kind in ("var", "temp"):
                if instr.arg1 and instr.arg1.kind == "const":
                    const_env[instr.result.value] = instr.arg1
                else:
                    const_env.pop(instr.result.value, None)
            elif instr.op == "call":
                # Uma função pode modificar variáveis globais
                for g in global_names:
                    const_env.pop(g, None)
                if instr.result and instr.result.kind in ("var", "temp"):
                    const_env.pop(instr.result.value, None)
            elif instr.op == "read":
                if instr.result and instr.result.kind in ("var", "temp"):
                    const_env.pop(instr.result.value, None)
            elif instr.result and instr.result.kind in ("var", "temp"):
                const_env.pop(instr.result.value, None)

            # Fim de bloco básico após desvios/retorno
            if instr.op in ("goto", "ifFalse", "ifTrue", "return"):
                const_env.clear()

        return changed

    # ------------------------------------------------------------------
    # Passagem 3: Otimização Peephole
    # ------------------------------------------------------------------

    def _pass_peephole(self, fn: IRFunction) -> bool:
        changed = False
        read_counts = self._count_reads(fn.instructions)
        instrs = fn.instructions
        new_instrs: List[IRInstruction] = []
        i = 0

        while i < len(instrs):
            curr = instrs[i]

            # 3a. Elimina autoatribuição (x = x)
            if curr.op == "assign" and curr.result == curr.arg1:
                self.stats.peephole_fusions += 1
                changed = True
                i += 1
                continue

            # 3b. Elimina salto para o rótulo imediatamente seguinte (goto L1; L1:)
            if (
                curr.op == "goto"
                and i + 1 < len(instrs)
                and instrs[i + 1].op == "label"
                and instrs[i + 1].result == curr.result
            ):
                self.stats.peephole_fusions += 1
                changed = True
                i += 1
                continue

            # 3c. Fusão de temporária de uso único:
            #     tK = <expr>
            #     dest = tK   -->   dest = <expr>
            if (
                i + 1 < len(instrs)
                and curr.result is not None
                and curr.result.kind == "temp"
                and curr.op in (BINARY_OPS | {"assign", "neg", "not", "intToFloat", "call"})
            ):
                nxt = instrs[i + 1]
                temp_name = curr.result.value
                if (
                    nxt.op == "assign"
                    and nxt.arg1 == curr.result
                    and nxt.result is not None
                    and read_counts.get(temp_name, 0) == 1
                ):
                    fused = copy.copy(curr)
                    fused.result = nxt.result
                    new_instrs.append(fused)
                    self.stats.peephole_fusions += 1
                    changed = True
                    i += 2
                    continue

            new_instrs.append(curr)
            i += 1

        fn.instructions = new_instrs
        return changed

    # ------------------------------------------------------------------
    # Passagem 4: Eliminação de Código Morto (DCE)
    # ------------------------------------------------------------------

    def _pass_dead_code_elimination(self, fn: IRFunction) -> bool:
        changed = False

        # 4a. Remove código inalcançável após goto ou return até o próximo rótulo
        reachable: List[IRInstruction] = []
        unreachable = False
        for instr in fn.instructions:
            if instr.op == "label":
                unreachable = False
                reachable.append(instr)
                continue
            if unreachable:
                self.stats.dead_instructions_removed += 1
                changed = True
                continue
            reachable.append(instr)
            if instr.op in ("goto", "return"):
                unreachable = True

        # 4b. Remove rótulos nunca referenciados por nenhum desvio
        referenced_labels: Set[str] = set()
        for instr in reachable:
            if instr.op in ("goto", "ifFalse", "ifTrue") and instr.result is not None:
                referenced_labels.add(instr.result.value)

        without_dead_labels: List[IRInstruction] = []
        for instr in reachable:
            if instr.op == "label" and instr.result is not None and instr.result.value not in referenced_labels:
                self.stats.dead_instructions_removed += 1
                changed = True
                continue
            without_dead_labels.append(instr)

        # 4c. Remove instruções puras cujo destino é uma temporária nunca lida
        read_counts = self._count_reads(without_dead_labels)
        cleaned: List[IRInstruction] = []
        pure_ops = BINARY_OPS | {"assign", "neg", "not", "intToFloat"}

        for instr in without_dead_labels:
            if (
                instr.op in pure_ops
                and instr.result is not None
                and instr.result.kind == "temp"
                and read_counts.get(instr.result.value, 0) == 0
            ):
                self.stats.dead_instructions_removed += 1
                changed = True
                continue
            cleaned.append(instr)

        fn.instructions = cleaned
        return changed

    def _count_reads(self, instrs: List[IRInstruction]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for instr in instrs:
            read_ops = [instr.arg1, instr.arg2]
            if instr.op in ("store_field", "store_index"):
                read_ops.append(instr.result)
            for op in read_ops:
                if op is not None and op.kind in ("var", "temp"):
                    counts[op.value] = counts.get(op.value, 0) + 1
        return counts
