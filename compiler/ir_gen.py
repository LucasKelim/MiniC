"""Fase 4: Gerador de Código Intermediário (AST anotada -> TAC de 3 endereços)."""

from typing import Dict, List, Optional, Tuple

from .ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BlockStmt,
    BreakStmt,
    CallExpr,
    ClassDecl,
    ContinueStmt,
    Expr,
    ExprStmt,
    ForStmt,
    FuncDecl,
    IfStmt,
    IndexAssignExpr,
    IndexExpr,
    IntToFloatExpr,
    LiteralExpr,
    MemberAssignExpr,
    MemberExpr,
    MethodCallExpr,
    MethodDecl,
    NewArrayExpr,
    NewExpr,
    PrintStmt,
    Program,
    ReadStmt,
    ReturnStmt,
    Stmt,
    ThisExpr,
    UnaryExpr,
    VarDecl,
    VarExpr,
    WhileStmt,
)
from .ir import IRFunction, IRInstruction, IRProgram, Operand
from .symbol_table import ClassInfo


DEFAULT_VALUES = {
    "int": 0,
    "float": 0.0,
    "bool": False,
    "string": "",
}


class IRGenerator:
    """Traduz a AST tipada (Fase 3) para Código de Três Endereços (TAC)."""

    def __init__(self, classes: Optional[Dict[str, ClassInfo]] = None) -> None:
        self._temp_counter = 0
        self._label_counter = 0
        self._current_func: Optional[IRFunction] = None
        self._global_names: Dict[str, str] = {}
        self._classes: Dict[str, ClassInfo] = classes or {}
        self._loop_stack: List[Tuple[Operand, Operand]] = []

    def generate(self, program: Program) -> IRProgram:
        ir_prog = IRProgram()

        # 1. Variáveis globais
        for decl in program.declarations:
            if isinstance(decl, VarDecl):
                var_name = decl.resolved_name or decl.name
                self._global_names[var_name] = decl.var_type
                default_val = DEFAULT_VALUES.get(decl.var_type, None)

                if isinstance(decl.initializer, LiteralExpr):
                    ir_prog.globals.append((var_name, decl.var_type, decl.initializer.value))
                elif (
                    isinstance(decl.initializer, IntToFloatExpr)
                    and isinstance(decl.initializer.expr, LiteralExpr)
                ):
                    ir_prog.globals.append(
                        (var_name, decl.var_type, float(decl.initializer.expr.value))
                    )
                else:
                    ir_prog.globals.append((var_name, decl.var_type, default_val))
                    if decl.initializer is not None:
                        # Inicialização dinâmica será executada no início de main()
                        temp_fn = IRFunction("__global_init__", "void", [])
                        self._current_func = temp_fn
                        val_op = self._gen_expr(decl.initializer)
                        target = Operand("var", var_name, decl.var_type)
                        self._emit(IRInstruction("assign", result=target, arg1=val_op, data_type=decl.var_type))
                        ir_prog.global_inits.extend(temp_fn.instructions)
                        self._current_func = None

        # 2. Métodos e construtores de classes (lowered para funções Class__metodo)
        for decl in program.declarations:
            if isinstance(decl, ClassDecl):
                for method in decl.methods:
                    ir_prog.functions.append(self._gen_method(decl.name, method))

        # 3. Funções globais
        for decl in program.declarations:
            if isinstance(decl, FuncDecl):
                ir_fn = self._gen_func(decl)
                # Injeta inicializações globais dinâmicas no prólogo de main()
                if decl.name == "main" and ir_prog.global_inits:
                    ir_fn.instructions = list(ir_prog.global_inits) + ir_fn.instructions
                    for instr in ir_prog.global_inits:
                        for op in (instr.result, instr.arg1, instr.arg2):
                            if op is not None and op.kind == "temp":
                                ir_fn.locals[op.value] = op.data_type
                ir_prog.functions.append(ir_fn)

        return ir_prog

    # ------------------------------------------------------------------
    # Utilitários internos
    # ------------------------------------------------------------------

    def _new_temp(self, data_type: str) -> Operand:
        self._temp_counter += 1
        name = f"t{self._temp_counter}"
        if self._current_func is not None:
            self._current_func.locals[name] = data_type
        return Operand("temp", name, data_type)

    def _new_label(self) -> Operand:
        self._label_counter += 1
        return Operand("label", f"L{self._label_counter}", "label")

    def _emit(self, instr: IRInstruction) -> None:
        assert self._current_func is not None
        self._current_func.instructions.append(instr)

    # ------------------------------------------------------------------
    # Funções e comandos
    # ------------------------------------------------------------------

    def _gen_func(self, func: FuncDecl) -> IRFunction:
        self._temp_counter = 0
        params = [(p.resolved_name or p.name, p.param_type) for p in func.params]
        ir_fn = IRFunction(
            name=func.name,
            return_type=func.return_type,
            params=params,
            locals={name: dtype for name, dtype in params},
        )
        self._current_func = ir_fn

        for stmt in func.body.statements:
            self._gen_stmt(stmt)

        # Garante instrução return ao final de funções void
        if func.return_type == "void":
            if not ir_fn.instructions or ir_fn.instructions[-1].op != "return":
                self._emit(IRInstruction("return", data_type="void"))

        self._current_func = None
        return ir_fn

    def _gen_method(self, class_name: str, method: MethodDecl) -> IRFunction:
        self._temp_counter = 0
        fn_name = f"{class_name}__init" if method.is_constructor else f"{class_name}__{method.name}"
        ret_type = "void" if method.is_constructor else method.return_type
        params = [("this", class_name)] + [(p.resolved_name or p.name, p.param_type) for p in method.params]
        ir_fn = IRFunction(
            name=fn_name,
            return_type=ret_type,
            params=params,
            locals={name: dtype for name, dtype in params},
        )
        self._current_func = ir_fn

        for stmt in method.body.statements:
            self._gen_stmt(stmt)

        if ret_type == "void":
            if not ir_fn.instructions or ir_fn.instructions[-1].op != "return":
                self._emit(IRInstruction("return", data_type="void"))

        self._current_func = None
        return ir_fn

    def _gen_stmt(self, stmt: Stmt) -> None:
        assert self._current_func is not None

        if isinstance(stmt, BlockStmt):
            for s in stmt.statements:
                self._gen_stmt(s)
            return

        if isinstance(stmt, VarDecl):
            var_name = stmt.resolved_name or stmt.name
            self._current_func.locals[var_name] = stmt.var_type
            target = Operand("var", var_name, stmt.var_type)
            if stmt.initializer is not None:
                val_op = self._gen_expr(stmt.initializer)
            elif stmt.var_type in DEFAULT_VALUES:
                val_op = Operand("const", DEFAULT_VALUES[stmt.var_type], stmt.var_type)
            else:
                val_op = Operand("const", None, "null")
            self._emit(IRInstruction("assign", result=target, arg1=val_op, data_type=stmt.var_type))
            return

        if isinstance(stmt, ExprStmt):
            self._gen_expr(stmt.expr)
            return

        if isinstance(stmt, IfStmt):
            cond_op = self._gen_expr(stmt.condition)
            if stmt.else_branch is None:
                label_end = self._new_label()
                self._emit(IRInstruction("ifFalse", result=label_end, arg1=cond_op, data_type="bool"))
                self._gen_stmt(stmt.then_branch)
                self._emit(IRInstruction("label", result=label_end))
            else:
                label_else = self._new_label()
                label_end = self._new_label()
                self._emit(IRInstruction("ifFalse", result=label_else, arg1=cond_op, data_type="bool"))
                self._gen_stmt(stmt.then_branch)
                self._emit(IRInstruction("goto", result=label_end))
                self._emit(IRInstruction("label", result=label_else))
                self._gen_stmt(stmt.else_branch)
                self._emit(IRInstruction("label", result=label_end))
            return

        if isinstance(stmt, WhileStmt):
            label_start = self._new_label()
            label_end = self._new_label()
            self._emit(IRInstruction("label", result=label_start))
            cond_op = self._gen_expr(stmt.condition)
            self._emit(IRInstruction("ifFalse", result=label_end, arg1=cond_op, data_type="bool"))
            self._loop_stack.append((label_start, label_end))
            self._gen_stmt(stmt.body)
            self._loop_stack.pop()
            self._emit(IRInstruction("goto", result=label_start))
            self._emit(IRInstruction("label", result=label_end))
            return

        if isinstance(stmt, ForStmt):
            if stmt.init is not None:
                self._gen_stmt(stmt.init)
            label_start = self._new_label()
            label_update = self._new_label()
            label_end = self._new_label()
            self._emit(IRInstruction("label", result=label_start))
            if stmt.condition is not None:
                cond_op = self._gen_expr(stmt.condition)
                self._emit(IRInstruction("ifFalse", result=label_end, arg1=cond_op, data_type="bool"))
            self._loop_stack.append((label_update, label_end))
            self._gen_stmt(stmt.body)
            self._loop_stack.pop()
            self._emit(IRInstruction("label", result=label_update))
            if stmt.update is not None:
                self._gen_expr(stmt.update)
            self._emit(IRInstruction("goto", result=label_start))
            self._emit(IRInstruction("label", result=label_end))
            return

        if isinstance(stmt, BreakStmt):
            _, break_label = self._loop_stack[-1]
            self._emit(IRInstruction("goto", result=break_label))
            return

        if isinstance(stmt, ContinueStmt):
            continue_label, _ = self._loop_stack[-1]
            self._emit(IRInstruction("goto", result=continue_label))
            return

        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                val_op = self._gen_expr(stmt.value)
                self._emit(IRInstruction("return", arg1=val_op, data_type=val_op.data_type))
            else:
                self._emit(IRInstruction("return", data_type="void"))
            return

        if isinstance(stmt, PrintStmt):
            space = Operand("const", " ", "string")
            for idx, arg in enumerate(stmt.args):
                if idx > 0:
                    self._emit(IRInstruction("print", arg1=space, data_type="string"))
                arg_op = self._gen_expr(arg)
                self._emit(IRInstruction("print", arg1=arg_op, data_type=arg_op.data_type))
            self._emit(IRInstruction("println"))
            return

        if isinstance(stmt, ReadStmt):
            var_name = stmt.resolved_name or stmt.target_name
            dtype = stmt.target_type or "int"
            target = Operand("var", var_name, dtype)
            self._emit(IRInstruction("read", result=target, data_type=dtype))
            return

    # ------------------------------------------------------------------
    # Expressões
    # ------------------------------------------------------------------

    def _gen_expr(self, expr: Expr) -> Operand:
        if isinstance(expr, LiteralExpr):
            return Operand("const", expr.value, expr.literal_type)

        if isinstance(expr, VarExpr):
            var_name = expr.resolved_name or expr.name
            return Operand("var", var_name, expr.inferred_type or "int")

        if isinstance(expr, IntToFloatExpr):
            inner = self._gen_expr(expr.expr)
            temp = self._new_temp("float")
            self._emit(IRInstruction("intToFloat", result=temp, arg1=inner, data_type="float"))
            return temp

        if isinstance(expr, AssignExpr):
            val_op = self._gen_expr(expr.value)
            var_name = expr.resolved_name or expr.name
            dtype = expr.inferred_type or val_op.data_type
            target = Operand("var", var_name, dtype)
            self._emit(IRInstruction("assign", result=target, arg1=val_op, data_type=dtype))
            return target

        if isinstance(expr, UnaryExpr):
            operand = self._gen_expr(expr.operand)
            dtype = expr.inferred_type or operand.data_type
            temp = self._new_temp(dtype)
            op_name = "neg" if expr.operator == "-" else "not"
            self._emit(IRInstruction(op_name, result=temp, arg1=operand, data_type=dtype))
            return temp

        if isinstance(expr, BinaryExpr):
            # Avaliação em curto-circuito para && e ||
            if expr.operator == "&&":
                result_temp = self._new_temp("bool")
                label_end = self._new_label()
                self._emit(
                    IRInstruction(
                        "assign",
                        result=result_temp,
                        arg1=Operand("const", False, "bool"),
                        data_type="bool",
                    )
                )
                left_op = self._gen_expr(expr.left)
                self._emit(IRInstruction("ifFalse", result=label_end, arg1=left_op, data_type="bool"))
                right_op = self._gen_expr(expr.right)
                self._emit(IRInstruction("assign", result=result_temp, arg1=right_op, data_type="bool"))
                self._emit(IRInstruction("label", result=label_end))
                return result_temp

            if expr.operator == "||":
                result_temp = self._new_temp("bool")
                label_end = self._new_label()
                self._emit(
                    IRInstruction(
                        "assign",
                        result=result_temp,
                        arg1=Operand("const", True, "bool"),
                        data_type="bool",
                    )
                )
                left_op = self._gen_expr(expr.left)
                self._emit(IRInstruction("ifTrue", result=label_end, arg1=left_op, data_type="bool"))
                right_op = self._gen_expr(expr.right)
                self._emit(IRInstruction("assign", result=result_temp, arg1=right_op, data_type="bool"))
                self._emit(IRInstruction("label", result=label_end))
                return result_temp

            left_op = self._gen_expr(expr.left)
            right_op = self._gen_expr(expr.right)
            dtype = expr.inferred_type or left_op.data_type
            temp = self._new_temp(dtype)
            self._emit(
                IRInstruction(
                    op=expr.operator,
                    result=temp,
                    arg1=left_op,
                    arg2=right_op,
                    data_type=dtype,
                )
            )
            return temp

        if isinstance(expr, CallExpr):
            arg_ops: List[Operand] = [self._gen_expr(a) for a in expr.args]
            for op in arg_ops:
                self._emit(IRInstruction("param", arg1=op, data_type=op.data_type))
            func_op = Operand("func", expr.callee, expr.inferred_type or "void")
            argc_op = Operand("const", len(arg_ops), "int")
            ret_type = expr.inferred_type or "void"
            if ret_type == "void":
                self._emit(IRInstruction("call", result=None, arg1=func_op, arg2=argc_op, data_type="void"))
                return Operand("const", None, "void")
            temp = self._new_temp(ret_type)
            self._emit(IRInstruction("call", result=temp, arg1=func_op, arg2=argc_op, data_type=ret_type))
            return temp

        if isinstance(expr, ThisExpr):
            return Operand("var", "this", expr.inferred_type or "int")

        if isinstance(expr, NewExpr):
            cls_info = self._classes.get(expr.class_name)
            size_bytes = cls_info.size_bytes if cls_info is not None else 8
            obj_temp = self._new_temp(expr.class_name)
            self._emit(
                IRInstruction(
                    "alloc",
                    result=obj_temp,
                    arg1=Operand("const", size_bytes, "int"),
                    data_type=expr.class_name,
                )
            )
            if cls_info is not None and cls_info.constructor is not None:
                arg_ops = [obj_temp] + [self._gen_expr(a) for a in expr.args]
                for op in arg_ops:
                    self._emit(IRInstruction("param", arg1=op, data_type=op.data_type))
                ctor_op = Operand("func", f"{expr.class_name}__init", "void")
                argc_op = Operand("const", len(arg_ops), "int")
                self._emit(IRInstruction("call", result=None, arg1=ctor_op, arg2=argc_op, data_type="void"))
            return obj_temp

        if isinstance(expr, MemberExpr):
            obj_op = self._gen_expr(expr.obj)
            dtype = expr.inferred_type or "int"
            offset_op = Operand("const", expr.field_offset or 0, "int")
            temp = self._new_temp(dtype)
            self._emit(
                IRInstruction(
                    "load_field",
                    result=temp,
                    arg1=obj_op,
                    arg2=offset_op,
                    data_type=dtype,
                )
            )
            return temp

        if isinstance(expr, MemberAssignExpr):
            obj_op = self._gen_expr(expr.obj)
            val_op = self._gen_expr(expr.value)
            dtype = expr.inferred_type or val_op.data_type
            offset_op = Operand("const", expr.field_offset or 0, "int")
            self._emit(
                IRInstruction(
                    "store_field",
                    result=obj_op,
                    arg1=offset_op,
                    arg2=val_op,
                    data_type=dtype,
                )
            )
            return val_op

        if isinstance(expr, MethodCallExpr):
            obj_op = self._gen_expr(expr.obj)
            arg_ops = [obj_op] + [self._gen_expr(a) for a in expr.args]
            for op in arg_ops:
                self._emit(IRInstruction("param", arg1=op, data_type=op.data_type))
            cls_name = expr.obj_class or obj_op.data_type
            ret_type = expr.inferred_type or "void"
            func_op = Operand("func", f"{cls_name}__{expr.method}", ret_type)
            argc_op = Operand("const", len(arg_ops), "int")
            if ret_type == "void":
                self._emit(IRInstruction("call", result=None, arg1=func_op, arg2=argc_op, data_type="void"))
                return Operand("const", None, "void")
            temp = self._new_temp(ret_type)
            self._emit(IRInstruction("call", result=temp, arg1=func_op, arg2=argc_op, data_type=ret_type))
            return temp

        if isinstance(expr, NewArrayExpr):
            size_op = self._gen_expr(expr.size)
            slots_temp = self._new_temp("int")
            self._emit(
                IRInstruction(
                    "+",
                    result=slots_temp,
                    arg1=size_op,
                    arg2=Operand("const", 1, "int"),
                    data_type="int",
                )
            )
            bytes_temp = self._new_temp("int")
            self._emit(
                IRInstruction(
                    "*",
                    result=bytes_temp,
                    arg1=slots_temp,
                    arg2=Operand("const", 8, "int"),
                    data_type="int",
                )
            )
            arr_type = expr.inferred_type or f"{expr.elem_type}[]"
            arr_temp = self._new_temp(arr_type)
            self._emit(IRInstruction("alloc", result=arr_temp, arg1=bytes_temp, data_type=arr_type))
            # Armazena .length no cabeçalho (offset 0)
            self._emit(
                IRInstruction(
                    "store_field",
                    result=arr_temp,
                    arg1=Operand("const", 0, "int"),
                    arg2=size_op,
                    data_type="int",
                )
            )
            return arr_temp

        if isinstance(expr, IndexExpr):
            arr_op = self._gen_expr(expr.array)
            idx_op = self._gen_expr(expr.index)
            dtype = expr.inferred_type or "int"
            temp = self._new_temp(dtype)
            self._emit(IRInstruction("load_index", result=temp, arg1=arr_op, arg2=idx_op, data_type=dtype))
            return temp

        if isinstance(expr, IndexAssignExpr):
            arr_op = self._gen_expr(expr.array)
            idx_op = self._gen_expr(expr.index)
            val_op = self._gen_expr(expr.value)
            dtype = expr.inferred_type or val_op.data_type
            self._emit(IRInstruction("store_index", result=arr_op, arg1=idx_op, arg2=val_op, data_type=dtype))
            return val_op

        raise RuntimeError(f"Nó de expressão inesperado na geração de IR: {type(expr).__name__}")
