"""Fase 3: Analisador Semântico (verificação de tipos, escopos e coerção implícita)."""

from typing import Optional, Tuple

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
    FieldDecl,
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
from .diagnostics import ErrorReporter
from .symbol_table import ClassInfo, FieldInfo, MethodInfo, SymbolTable

ERROR_TYPE = "error"
NUMERIC_TYPES = ("int", "float")
PRIMITIVE_TYPES = ("int", "float", "bool", "string", "void")


class SemanticAnalyzer:
    """Percorre a AST para validar regras semânticas e anotar tipos/coerções.

    - Constrói a Tabela de Símbolos com escopos aninhados.
    - Verifica declaração prévia, unicidade no escopo, compatibilidade de tipos,
      assinaturas de chamadas de função, condições booleanas e retornos.
    - Insere nós explícitos IntToFloatExpr quando ocorre promoção implícita int -> float.
    """

    def __init__(self, reporter: ErrorReporter) -> None:
        self.reporter = reporter
        self.symtab = SymbolTable()
        self._current_func_return_type: Optional[str] = None
        self._current_func_name: Optional[str] = None
        self._current_class_name: Optional[str] = None
        self._loop_depth: int = 0

    def _is_valid_type(self, type_name: str, allow_void: bool = False) -> bool:
        if type_name.endswith("[]"):
            base = type_name[:-2]
            return self._is_valid_type(base, allow_void=False)
        if type_name == "void":
            return allow_void
        return type_name in PRIMITIVE_TYPES or type_name in self.symtab.classes

    def _is_reference_type(self, type_name: str) -> bool:
        return type_name in self.symtab.classes or type_name.endswith("[]")

    def analyze(self, program: Program) -> SymbolTable:
        # Passagem 1a: registra nomes de todas as classes (permite referências cruzadas)
        for decl in program.declarations:
            if isinstance(decl, ClassDecl):
                sym = self.symtab.declare(
                    name=decl.name,
                    category="class",
                    data_type=decl.name,
                    decl_line=decl.line,
                )
                if sym is None:
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Classe '{decl.name}' já foi declarada neste escopo.",
                        decl.line,
                        decl.column,
                    )
                else:
                    self.symtab.classes[decl.name] = ClassInfo(name=decl.name, decl_line=decl.line)

        # Passagem 1b: registra membros de classes e cabeçalhos de funções globais
        for decl in program.declarations:
            if isinstance(decl, ClassDecl):
                self._register_class_members(decl)
            elif isinstance(decl, FuncDecl):
                if not self._is_valid_type(decl.return_type, allow_void=True):
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Tipo de retorno desconhecido '{decl.return_type}' na função '{decl.name}'.",
                        decl.line,
                        decl.column,
                    )
                for p in decl.params:
                    if not self._is_valid_type(p.param_type, allow_void=False):
                        self.reporter.report(
                            "SEMÂNTICO",
                            f"Tipo de parâmetro desconhecido '{p.param_type}' na função '{decl.name}'.",
                            p.line,
                            p.column,
                        )
                param_types = [p.param_type for p in decl.params]
                sym = self.symtab.declare(
                    name=decl.name,
                    category="func",
                    data_type=decl.return_type,
                    decl_line=decl.line,
                    param_types=param_types,
                )
                if sym is None:
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Função '{decl.name}' já foi declarada neste escopo.",
                        decl.line,
                        decl.column,
                    )

        # Passagem 2: analisa variáveis globais, funções globais e corpos de classes
        for decl in program.declarations:
            if isinstance(decl, VarDecl):
                self._analyze_var_decl(decl)
            elif isinstance(decl, FuncDecl):
                self._analyze_func_decl(decl)
            elif isinstance(decl, ClassDecl):
                self._analyze_class_decl(decl)

        return self.symtab

    def _register_class_members(self, cls_decl: ClassDecl) -> None:
        cls_info = self.symtab.classes.get(cls_decl.name)
        if cls_info is None:
            return

        # Registra campos com offsets de 8 bytes
        offset = 0
        for field in cls_decl.fields:
            if not self._is_valid_type(field.field_type, allow_void=False):
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Tipo desconhecido '{field.field_type}' para o campo '{field.name}' da classe '{cls_decl.name}'.",
                    field.line,
                    field.column,
                )
            if field.name in cls_info.fields:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Campo duplicado '{field.name}' na classe '{cls_decl.name}'.",
                    field.line,
                    field.column,
                )
                continue
            cls_info.fields[field.name] = FieldInfo(
                name=field.name,
                data_type=field.field_type,
                access=field.access,
                offset=offset,
                decl_line=field.line,
            )
            offset += 8

        # Registra construtores e métodos
        for method in cls_decl.methods:
            for p in method.params:
                if not self._is_valid_type(p.param_type, allow_void=False):
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Tipo de parâmetro desconhecido '{p.param_type}' em '{cls_decl.name}.{method.name}'.",
                        p.line,
                        p.column,
                    )
            param_types = [p.param_type for p in method.params]
            if method.is_constructor:
                if method.name != cls_decl.name:
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Construtor '{method.name}' deve ter o mesmo nome da classe '{cls_decl.name}'.",
                        method.line,
                        method.column,
                    )
                if cls_info.constructor is not None:
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Classe '{cls_decl.name}' já possui um construtor definido.",
                        method.line,
                        method.column,
                    )
                else:
                    cls_info.constructor = MethodInfo(
                        name=method.name,
                        return_type="void",
                        param_types=param_types,
                        access=method.access,
                        is_constructor=True,
                        decl_line=method.line,
                    )
            else:
                if not self._is_valid_type(method.return_type, allow_void=True):
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Tipo de retorno desconhecido '{method.return_type}' no método '{cls_decl.name}.{method.name}'.",
                        method.line,
                        method.column,
                    )
                if method.name in cls_info.methods:
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Método duplicado '{method.name}' na classe '{cls_decl.name}'.",
                        method.line,
                        method.column,
                    )
                else:
                    cls_info.methods[method.name] = MethodInfo(
                        name=method.name,
                        return_type=method.return_type,
                        param_types=param_types,
                        access=method.access,
                        is_constructor=False,
                        decl_line=method.line,
                    )

    def _analyze_class_decl(self, cls_decl: ClassDecl) -> None:
        prev_class = self._current_class_name
        self._current_class_name = cls_decl.name
        for method in cls_decl.methods:
            self._analyze_method_decl(cls_decl.name, method)
        self._current_class_name = prev_class

    def _analyze_method_decl(self, class_name: str, method: MethodDecl) -> None:
        prev_ret = self._current_func_return_type
        prev_name = self._current_func_name
        self._current_func_return_type = "void" if method.is_constructor else method.return_type
        self._current_func_name = f"{class_name}.{method.name}"

        self.symtab.enter_scope(f"method:{class_name}.{method.name}")
        # Declara parâmetro implícito 'this'
        self.symtab.declare(
            name="this",
            category="param",
            data_type=class_name,
            decl_line=method.line,
        )

        for param in method.params:
            sym = self.symtab.declare(
                name=param.name,
                category="param",
                data_type=param.param_type,
                decl_line=param.line,
            )
            if sym is None:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Parâmetro duplicado '{param.name}' no método '{class_name}.{method.name}'.",
                    param.line,
                    param.column,
                )
            else:
                param.resolved_name = sym.unique_name

        for stmt in method.body.statements:
            self._analyze_stmt(stmt)

        self.symtab.exit_scope()
        self._current_func_return_type = prev_ret
        self._current_func_name = prev_name

    # ------------------------------------------------------------------
    # Declarações e blocos
    # ------------------------------------------------------------------

    def _analyze_func_decl(self, func: FuncDecl) -> None:
        prev_ret = self._current_func_return_type
        prev_name = self._current_func_name
        self._current_func_return_type = func.return_type
        self._current_func_name = func.name

        self.symtab.enter_scope(f"func:{func.name}")

        for param in func.params:
            sym = self.symtab.declare(
                name=param.name,
                category="param",
                data_type=param.param_type,
                decl_line=param.line,
            )
            if sym is None:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Parâmetro duplicado '{param.name}' na função '{func.name}'.",
                    param.line,
                    param.column,
                )
            else:
                param.resolved_name = sym.unique_name

        # O corpo da função compartilha o escopo nível 1 dos parâmetros (como em C)
        for stmt in func.body.statements:
            self._analyze_stmt(stmt)

        self.symtab.exit_scope()
        self._current_func_return_type = prev_ret
        self._current_func_name = prev_name

    def _analyze_var_decl(self, decl: VarDecl) -> None:
        if not self._is_valid_type(decl.var_type, allow_void=False):
            self.reporter.report(
                "SEMÂNTICO",
                f"Tipo desconhecido '{decl.var_type}' na declaração de '{decl.name}'.",
                decl.line,
                decl.column,
            )
        if decl.is_const and decl.initializer is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Constante '{decl.name}' deve ser inicializada na declaração.",
                decl.line,
                decl.column,
            )
        if decl.initializer is not None:
            init_expr, init_type = self._analyze_expr(decl.initializer)
            coerced = self._coerce_assign(
                target_type=decl.var_type,
                expr=init_expr,
                expr_type=init_type,
                line=decl.line,
                column=decl.column,
                context=f"inicialização da variável '{decl.name}'",
            )
            decl.initializer = coerced

        sym = self.symtab.declare(
            name=decl.name,
            category="var",
            data_type=decl.var_type,
            decl_line=decl.line,
            is_const=decl.is_const,
        )
        if sym is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Identificador '{decl.name}' já foi declarado neste escopo.",
                decl.line,
                decl.column,
            )
        else:
            decl.resolved_name = sym.unique_name

    def _analyze_block(self, block: BlockStmt, label: Optional[str] = None) -> None:
        scope_label = label or f"block@L{block.line}"
        self.symtab.enter_scope(scope_label)
        for stmt in block.statements:
            self._analyze_stmt(stmt)
        self.symtab.exit_scope()

    # ------------------------------------------------------------------
    # Comandos (Statements)
    # ------------------------------------------------------------------

    def _analyze_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, VarDecl):
            self._analyze_var_decl(stmt)
        elif isinstance(stmt, BlockStmt):
            self._analyze_block(stmt)
        elif isinstance(stmt, IfStmt):
            stmt.condition, cond_type = self._analyze_expr(stmt.condition)
            self._require_bool(cond_type, stmt.condition.line, stmt.condition.column, "comando 'if'")
            self._analyze_stmt(stmt.then_branch)
            if stmt.else_branch is not None:
                self._analyze_stmt(stmt.else_branch)
        elif isinstance(stmt, WhileStmt):
            stmt.condition, cond_type = self._analyze_expr(stmt.condition)
            self._require_bool(cond_type, stmt.condition.line, stmt.condition.column, "laço 'while'")
            self._loop_depth += 1
            self._analyze_stmt(stmt.body)
            self._loop_depth -= 1
        elif isinstance(stmt, ForStmt):
            self.symtab.enter_scope(f"for@L{stmt.line}")
            if stmt.init is not None:
                self._analyze_stmt(stmt.init)
            if stmt.condition is not None:
                stmt.condition, cond_type = self._analyze_expr(stmt.condition)
                self._require_bool(cond_type, stmt.condition.line, stmt.condition.column, "laço 'for'")
            if stmt.update is not None:
                stmt.update, _ = self._analyze_expr(stmt.update)
            self._loop_depth += 1
            self._analyze_stmt(stmt.body)
            self._loop_depth -= 1
            self.symtab.exit_scope()
        elif isinstance(stmt, BreakStmt):
            if self._loop_depth <= 0:
                self.reporter.report(
                    "SEMÂNTICO",
                    "Comando 'break' só pode ser usado dentro de um laço ('while' ou 'for').",
                    stmt.line,
                    stmt.column,
                )
        elif isinstance(stmt, ContinueStmt):
            if self._loop_depth <= 0:
                self.reporter.report(
                    "SEMÂNTICO",
                    "Comando 'continue' só pode ser usado dentro de um laço ('while' ou 'for').",
                    stmt.line,
                    stmt.column,
                )
        elif isinstance(stmt, ReturnStmt):
            self._analyze_return(stmt)
        elif isinstance(stmt, PrintStmt):
            new_args = []
            for arg in stmt.args:
                analyzed, arg_type = self._analyze_expr(arg)
                if arg_type == "void":
                    self.reporter.report(
                        "SEMÂNTICO",
                        "Não é possível imprimir uma expressão do tipo 'void'.",
                        arg.line,
                        arg.column,
                    )
                elif self._is_reference_type(arg_type) or arg_type == "null":
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Não é possível imprimir diretamente um objeto/vetor do tipo '{arg_type}'; acesse um campo ou elemento.",
                        arg.line,
                        arg.column,
                    )
                new_args.append(analyzed)
            stmt.args = new_args
        elif isinstance(stmt, ReadStmt):
            sym = self.symtab.lookup(stmt.target_name)
            if sym is None:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Variável '{stmt.target_name}' não foi declarada.",
                    stmt.target_line,
                    stmt.target_column,
                )
            elif sym.category in ("func", "class"):
                self.reporter.report(
                    "SEMÂNTICO",
                    f"'{stmt.target_name}' não é uma variável e não pode ser usada em 'read'.",
                    stmt.target_line,
                    stmt.target_column,
                )
            elif sym.is_const:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Não é possível modificar a constante '{stmt.target_name}' com 'read'.",
                    stmt.target_line,
                    stmt.target_column,
                )
            elif sym.data_type not in ("int", "float", "bool"):
                self.reporter.report(
                    "SEMÂNTICO",
                    f"'read' não suporta leitura direta para o tipo '{sym.data_type}'.",
                    stmt.target_line,
                    stmt.target_column,
                )
            else:
                sym.add_usage(stmt.target_line)
                stmt.target_type = sym.data_type
                stmt.resolved_name = sym.unique_name
        elif isinstance(stmt, ExprStmt):
            stmt.expr, _ = self._analyze_expr(stmt.expr)

    def _analyze_return(self, stmt: ReturnStmt) -> None:
        expected = self._current_func_return_type
        if expected is None:
            self.reporter.report(
                "SEMÂNTICO",
                "Comando 'return' fora de uma função.",
                stmt.line,
                stmt.column,
            )
            return

        if expected == "void":
            if stmt.value is not None:
                stmt.value, _ = self._analyze_expr(stmt.value)
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Função '{self._current_func_name}' é 'void' e não deve retornar valor.",
                    stmt.line,
                    stmt.column,
                )
            return

        if stmt.value is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Função '{self._current_func_name}' deve retornar um valor do tipo '{expected}'.",
                stmt.line,
                stmt.column,
            )
            return

        val_expr, val_type = self._analyze_expr(stmt.value)
        stmt.value = self._coerce_assign(
            target_type=expected,
            expr=val_expr,
            expr_type=val_type,
            line=stmt.line,
            column=stmt.column,
            context=f"retorno da função '{self._current_func_name}'",
        )

    # ------------------------------------------------------------------
    # Expressões (retornam tupla (Expr possivelmente envolta em IntToFloat, tipo))
    # ------------------------------------------------------------------

    def _analyze_expr(self, expr: Expr) -> Tuple[Expr, str]:
        if isinstance(expr, LiteralExpr):
            expr.inferred_type = expr.literal_type
            return expr, expr.literal_type

        if isinstance(expr, VarExpr):
            sym = self.symtab.lookup(expr.name)
            if sym is None:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Variável '{expr.name}' utilizada sem declaração prévia.",
                    expr.line,
                    expr.column,
                )
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            if sym.category == "func":
                self.reporter.report(
                    "SEMÂNTICO",
                    f"'{expr.name}' é uma função e deve ser chamada com '()'.",
                    expr.line,
                    expr.column,
                )
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            if sym.category == "class":
                self.reporter.report(
                    "SEMÂNTICO",
                    f"'{expr.name}' é uma classe; use 'new {expr.name}(...)' para instanciar.",
                    expr.line,
                    expr.column,
                )
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            sym.add_usage(expr.line)
            expr.resolved_name = sym.unique_name
            expr.inferred_type = sym.data_type
            return expr, sym.data_type

        if isinstance(expr, AssignExpr):
            val_expr, val_type = self._analyze_expr(expr.value)
            sym = self.symtab.lookup(expr.name)
            if sym is None:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Variável '{expr.name}' não declarada antes da atribuição.",
                    expr.line,
                    expr.column,
                )
                expr.value = val_expr
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            if sym.category in ("func", "class"):
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Não é possível atribuir valor a '{expr.name}'.",
                    expr.line,
                    expr.column,
                )
                expr.value = val_expr
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            if sym.is_const:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Não é possível modificar a constante '{expr.name}'.",
                    expr.line,
                    expr.column,
                )
                expr.value = val_expr
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE

            sym.add_usage(expr.line)
            expr.resolved_name = sym.unique_name
            expr.value = self._coerce_assign(
                target_type=sym.data_type,
                expr=val_expr,
                expr_type=val_type,
                line=expr.line,
                column=expr.column,
                context=f"atribuição à variável '{expr.name}'",
            )
            expr.inferred_type = sym.data_type
            return expr, sym.data_type

        if isinstance(expr, UnaryExpr):
            operand, op_type = self._analyze_expr(expr.operand)
            expr.operand = operand
            if op_type == ERROR_TYPE:
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE

            if expr.operator == "!":
                if op_type != "bool":
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Operador lógico '!' requer operando 'bool', encontrado '{op_type}'.",
                        expr.line,
                        expr.column,
                    )
                    expr.inferred_type = ERROR_TYPE
                    return expr, ERROR_TYPE
                expr.inferred_type = "bool"
                return expr, "bool"

            if expr.operator == "-":
                if op_type not in NUMERIC_TYPES:
                    self.reporter.report(
                        "SEMÂNTICO",
                        f"Operador unário '-' requer operando numérico ('int' ou 'float'), encontrado '{op_type}'.",
                        expr.line,
                        expr.column,
                    )
                    expr.inferred_type = ERROR_TYPE
                    return expr, ERROR_TYPE
                expr.inferred_type = op_type
                return expr, op_type

        if isinstance(expr, BinaryExpr):
            return self._analyze_binary(expr)

        if isinstance(expr, CallExpr):
            return self._analyze_call(expr)

        if isinstance(expr, ThisExpr):
            if self._current_class_name is None:
                self.reporter.report(
                    "SEMÂNTICO",
                    "'this' só pode ser utilizado dentro de um método ou construtor de classe.",
                    expr.line,
                    expr.column,
                )
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            expr.inferred_type = self._current_class_name
            return expr, self._current_class_name

        if isinstance(expr, NewExpr):
            return self._analyze_new(expr)

        if isinstance(expr, MemberExpr):
            return self._analyze_member(expr)

        if isinstance(expr, MemberAssignExpr):
            return self._analyze_member_assign(expr)

        if isinstance(expr, MethodCallExpr):
            return self._analyze_method_call(expr)

        if isinstance(expr, NewArrayExpr):
            return self._analyze_new_array(expr)

        if isinstance(expr, IndexExpr):
            return self._analyze_index(expr)

        if isinstance(expr, IndexAssignExpr):
            return self._analyze_index_assign(expr)

        expr.inferred_type = ERROR_TYPE
        return expr, ERROR_TYPE

    def _analyze_binary(self, expr: BinaryExpr) -> Tuple[Expr, str]:
        left, ltype = self._analyze_expr(expr.left)
        right, rtype = self._analyze_expr(expr.right)
        expr.left = left
        expr.right = right

        if ltype == ERROR_TYPE or rtype == ERROR_TYPE:
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        op = expr.operator

        # Aritméticos: +, -, *, /
        if op in ("+", "-", "*", "/"):
            if ltype not in NUMERIC_TYPES or rtype not in NUMERIC_TYPES:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Operador aritmético '{op}' incompatível com tipos '{ltype}' e '{rtype}'.",
                    expr.line,
                    expr.column,
                )
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            if ltype == "float" or rtype == "float":
                if ltype == "int":
                    expr.left = self._wrap_int_to_float(expr.left)
                if rtype == "int":
                    expr.right = self._wrap_int_to_float(expr.right)
                expr.inferred_type = "float"
                return expr, "float"
            expr.inferred_type = "int"
            return expr, "int"

        # Módulo: %
        if op == "%":
            if ltype != "int" or rtype != "int":
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Operador '%' requer dois operandos 'int', encontrados '{ltype}' e '{rtype}'.",
                    expr.line,
                    expr.column,
                )
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            expr.inferred_type = "int"
            return expr, "int"

        # Relacionais: <, <=, >, >=
        if op in ("<", "<=", ">", ">="):
            if ltype not in NUMERIC_TYPES or rtype not in NUMERIC_TYPES:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Operador relacional '{op}' requer operandos numéricos, encontrados '{ltype}' e '{rtype}'.",
                    expr.line,
                    expr.column,
                )
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            if ltype == "float" and rtype == "int":
                expr.right = self._wrap_int_to_float(expr.right)
            elif ltype == "int" and rtype == "float":
                expr.left = self._wrap_int_to_float(expr.left)
            expr.inferred_type = "bool"
            return expr, "bool"

        # Igualdade: ==, !=
        if op in ("==", "!="):
            if ltype == rtype and ltype != "void":
                expr.inferred_type = "bool"
                return expr, "bool"
            if (self._is_reference_type(ltype) and rtype == "null") or (
                self._is_reference_type(rtype) and ltype == "null"
            ):
                expr.inferred_type = "bool"
                return expr, "bool"
            if ltype in NUMERIC_TYPES and rtype in NUMERIC_TYPES:
                if ltype == "int":
                    expr.left = self._wrap_int_to_float(expr.left)
                else:
                    expr.right = self._wrap_int_to_float(expr.right)
                expr.inferred_type = "bool"
                return expr, "bool"
            self.reporter.report(
                "SEMÂNTICO",
                f"Operador '{op}' não pode comparar tipos incompatíveis '{ltype}' e '{rtype}'.",
                expr.line,
                expr.column,
            )
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        # Lógicos: &&, ||
        if op in ("&&", "||"):
            if ltype != "bool" or rtype != "bool":
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Operador lógico '{op}' requer operandos 'bool', encontrados '{ltype}' e '{rtype}'.",
                    expr.line,
                    expr.column,
                )
                expr.inferred_type = ERROR_TYPE
                return expr, ERROR_TYPE
            expr.inferred_type = "bool"
            return expr, "bool"

        expr.inferred_type = ERROR_TYPE
        return expr, ERROR_TYPE

    def _analyze_call(self, call: CallExpr) -> Tuple[Expr, str]:
        analyzed_args = [self._analyze_expr(a) for a in call.args]
        sym = self.symtab.lookup(call.callee)

        if sym is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Função '{call.callee}' não foi declarada.",
                call.line,
                call.column,
            )
            call.args = [e for e, _ in analyzed_args]
            call.inferred_type = ERROR_TYPE
            return call, ERROR_TYPE

        if sym.category != "func":
            self.reporter.report(
                "SEMÂNTICO",
                f"'{call.callee}' não é uma função e não pode ser invocada.",
                call.line,
                call.column,
            )
            call.args = [e for e, _ in analyzed_args]
            call.inferred_type = ERROR_TYPE
            return call, ERROR_TYPE

        sym.add_usage(call.line)

        if len(analyzed_args) != len(sym.param_types):
            self.reporter.report(
                "SEMÂNTICO",
                f"Função '{call.callee}' espera {len(sym.param_types)} argumento(s), "
                f"mas recebeu {len(analyzed_args)}.",
                call.line,
                call.column,
            )
            call.args = [e for e, _ in analyzed_args]
        else:
            coerced_args = []
            for idx, ((arg_expr, arg_type), expected_type) in enumerate(
                zip(analyzed_args, sym.param_types), start=1
            ):
                coerced_args.append(
                    self._coerce_assign(
                        target_type=expected_type,
                        expr=arg_expr,
                        expr_type=arg_type,
                        line=arg_expr.line,
                        column=arg_expr.column,
                        context=f"argumento {idx} da chamada '{call.callee}'",
                    )
                )
            call.args = coerced_args

        call.inferred_type = sym.data_type
        return call, sym.data_type

    def _analyze_new(self, expr: NewExpr) -> Tuple[Expr, str]:
        analyzed_args = [self._analyze_expr(a) for a in expr.args]
        cls_info = self.symtab.classes.get(expr.class_name)
        if cls_info is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Classe '{expr.class_name}' não foi declarada.",
                expr.line,
                expr.column,
            )
            expr.args = [e for e, _ in analyzed_args]
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        ctor = cls_info.constructor
        if ctor is None:
            if analyzed_args:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Classe '{expr.class_name}' não possui construtor com parâmetros (esperados 0 argumentos, recebidos {len(analyzed_args)}).",
                    expr.line,
                    expr.column,
                )
            expr.args = [e for e, _ in analyzed_args]
        else:
            if ctor.access == "private" and self._current_class_name != expr.class_name:
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Construtor da classe '{expr.class_name}' é privado e não pode ser acessado fora da classe.",
                    expr.line,
                    expr.column,
                )
            if len(analyzed_args) != len(ctor.param_types):
                self.reporter.report(
                    "SEMÂNTICO",
                    f"Construtor de '{expr.class_name}' espera {len(ctor.param_types)} argumento(s), "
                    f"mas recebeu {len(analyzed_args)}.",
                    expr.line,
                    expr.column,
                )
                expr.args = [e for e, _ in analyzed_args]
            else:
                coerced_args = []
                for idx, ((arg_expr, arg_type), expected_type) in enumerate(
                    zip(analyzed_args, ctor.param_types), start=1
                ):
                    coerced_args.append(
                        self._coerce_assign(
                            target_type=expected_type,
                            expr=arg_expr,
                            expr_type=arg_type,
                            line=arg_expr.line,
                            column=arg_expr.column,
                            context=f"argumento {idx} do construtor '{expr.class_name}'",
                        )
                    )
                expr.args = coerced_args

        expr.inferred_type = expr.class_name
        return expr, expr.class_name

    def _analyze_member(self, expr: MemberExpr) -> Tuple[Expr, str]:
        obj_expr, obj_type = self._analyze_expr(expr.obj)
        expr.obj = obj_expr
        if obj_type == ERROR_TYPE:
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        # Propriedade nativa .length de vetores (armazenada no cabeçalho offset 0)
        if obj_type.endswith("[]"):
            if expr.member == "length":
                expr.obj_class = obj_type
                expr.field_offset = 0
                expr.inferred_type = "int"
                return expr, "int"
            self.reporter.report(
                "SEMÂNTICO",
                f"Vetor do tipo '{obj_type}' não possui propriedade '.{expr.member}' (use '.length').",
                expr.line,
                expr.column,
            )
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        cls_info = self.symtab.classes.get(obj_type)
        if cls_info is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Não é possível acessar campo '.{expr.member}' em expressão do tipo primitivo '{obj_type}'.",
                expr.line,
                expr.column,
            )
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        field = cls_info.fields.get(expr.member)
        if field is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Classe '{obj_type}' não possui campo '{expr.member}'.",
                expr.line,
                expr.column,
            )
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        if field.access == "private" and self._current_class_name != obj_type:
            self.reporter.report(
                "SEMÂNTICO",
                f"Campo '{expr.member}' da classe '{obj_type}' é privado e não pode ser acessado fora da classe.",
                expr.line,
                expr.column,
            )

        expr.obj_class = obj_type
        expr.field_offset = field.offset
        expr.inferred_type = field.data_type
        return expr, field.data_type

    def _analyze_member_assign(self, expr: MemberAssignExpr) -> Tuple[Expr, str]:
        obj_expr, obj_type = self._analyze_expr(expr.obj)
        expr.obj = obj_expr
        val_expr, val_type = self._analyze_expr(expr.value)
        if obj_type == ERROR_TYPE:
            expr.value = val_expr
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        cls_info = self.symtab.classes.get(obj_type)
        if cls_info is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Não é possível atribuir ao campo '.{expr.member}' em expressão do tipo '{obj_type}'.",
                expr.line,
                expr.column,
            )
            expr.value = val_expr
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        field = cls_info.fields.get(expr.member)
        if field is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Classe '{obj_type}' não possui campo '{expr.member}'.",
                expr.line,
                expr.column,
            )
            expr.value = val_expr
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        if field.access == "private" and self._current_class_name != obj_type:
            self.reporter.report(
                "SEMÂNTICO",
                f"Campo '{expr.member}' da classe '{obj_type}' é privado e não pode ser modificado fora da classe.",
                expr.line,
                expr.column,
            )

        expr.obj_class = obj_type
        expr.field_offset = field.offset
        expr.value = self._coerce_assign(
            target_type=field.data_type,
            expr=val_expr,
            expr_type=val_type,
            line=expr.line,
            column=expr.column,
            context=f"atribuição ao campo '{obj_type}.{expr.member}'",
        )
        expr.inferred_type = field.data_type
        return expr, field.data_type

    def _analyze_method_call(self, expr: MethodCallExpr) -> Tuple[Expr, str]:
        obj_expr, obj_type = self._analyze_expr(expr.obj)
        expr.obj = obj_expr
        analyzed_args = [self._analyze_expr(a) for a in expr.args]

        if obj_type == ERROR_TYPE:
            expr.args = [e for e, _ in analyzed_args]
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        cls_info = self.symtab.classes.get(obj_type)
        if cls_info is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Não é possível invocar método '.{expr.method}()' em expressão do tipo '{obj_type}'.",
                expr.line,
                expr.column,
            )
            expr.args = [e for e, _ in analyzed_args]
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        method = cls_info.methods.get(expr.method)
        if method is None:
            self.reporter.report(
                "SEMÂNTICO",
                f"Classe '{obj_type}' não possui método '{expr.method}'.",
                expr.line,
                expr.column,
            )
            expr.args = [e for e, _ in analyzed_args]
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE

        if method.access == "private" and self._current_class_name != obj_type:
            self.reporter.report(
                "SEMÂNTICO",
                f"Método '{expr.method}' da classe '{obj_type}' é privado e não pode ser chamado fora da classe.",
                expr.line,
                expr.column,
            )

        if len(analyzed_args) != len(method.param_types):
            self.reporter.report(
                "SEMÂNTICO",
                f"Método '{obj_type}.{expr.method}' espera {len(method.param_types)} argumento(s), "
                f"mas recebeu {len(analyzed_args)}.",
                expr.line,
                expr.column,
            )
            expr.args = [e for e, _ in analyzed_args]
        else:
            coerced_args = []
            for idx, ((arg_expr, arg_type), expected_type) in enumerate(
                zip(analyzed_args, method.param_types), start=1
            ):
                coerced_args.append(
                    self._coerce_assign(
                        target_type=expected_type,
                        expr=arg_expr,
                        expr_type=arg_type,
                        line=arg_expr.line,
                        column=arg_expr.column,
                        context=f"argumento {idx} do método '{obj_type}.{expr.method}'",
                    )
                )
            expr.args = coerced_args

        expr.obj_class = obj_type
        expr.inferred_type = method.return_type
        return expr, method.return_type

    def _analyze_new_array(self, expr: NewArrayExpr) -> Tuple[Expr, str]:
        size_expr, size_type = self._analyze_expr(expr.size)
        expr.size = size_expr
        if not self._is_valid_type(expr.elem_type, allow_void=False):
            self.reporter.report(
                "SEMÂNTICO",
                f"Tipo de elemento desconhecido '{expr.elem_type}' na alocação de vetor.",
                expr.line,
                expr.column,
            )
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE
        if size_type not in ("int", ERROR_TYPE):
            self.reporter.report(
                "SEMÂNTICO",
                f"Tamanho do vetor deve ser do tipo 'int', encontrado '{size_type}'.",
                size_expr.line,
                size_expr.column,
            )
        arr_type = f"{expr.elem_type}[]"
        expr.inferred_type = arr_type
        return expr, arr_type

    def _analyze_index(self, expr: IndexExpr) -> Tuple[Expr, str]:
        arr_expr, arr_type = self._analyze_expr(expr.array)
        idx_expr, idx_type = self._analyze_expr(expr.index)
        expr.array = arr_expr
        expr.index = idx_expr
        if arr_type == ERROR_TYPE:
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE
        if not arr_type.endswith("[]"):
            self.reporter.report(
                "SEMÂNTICO",
                f"Não é possível indexar expressão do tipo '{arr_type}' (não é um vetor).",
                expr.line,
                expr.column,
            )
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE
        if idx_type not in ("int", ERROR_TYPE):
            self.reporter.report(
                "SEMÂNTICO",
                f"Índice do vetor deve ser do tipo 'int', encontrado '{idx_type}'.",
                idx_expr.line,
                idx_expr.column,
            )
        elem_type = arr_type[:-2]
        expr.inferred_type = elem_type
        return expr, elem_type

    def _analyze_index_assign(self, expr: IndexAssignExpr) -> Tuple[Expr, str]:
        arr_expr, arr_type = self._analyze_expr(expr.array)
        idx_expr, idx_type = self._analyze_expr(expr.index)
        val_expr, val_type = self._analyze_expr(expr.value)
        expr.array = arr_expr
        expr.index = idx_expr
        if arr_type == ERROR_TYPE:
            expr.value = val_expr
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE
        if not arr_type.endswith("[]"):
            self.reporter.report(
                "SEMÂNTICO",
                f"Não é possível atribuir por índice em expressão do tipo '{arr_type}' (não é um vetor).",
                expr.line,
                expr.column,
            )
            expr.value = val_expr
            expr.inferred_type = ERROR_TYPE
            return expr, ERROR_TYPE
        if idx_type not in ("int", ERROR_TYPE):
            self.reporter.report(
                "SEMÂNTICO",
                f"Índice do vetor deve ser do tipo 'int', encontrado '{idx_type}'.",
                idx_expr.line,
                idx_expr.column,
            )
        elem_type = arr_type[:-2]
        expr.value = self._coerce_assign(
            target_type=elem_type,
            expr=val_expr,
            expr_type=val_type,
            line=expr.line,
            column=expr.column,
            context=f"atribuição a elemento de '{arr_type}'",
        )
        expr.inferred_type = elem_type
        return expr, elem_type

    # ------------------------------------------------------------------
    # Auxiliares de tipo e coerção implícita (int -> float)
    # ------------------------------------------------------------------

    def _wrap_int_to_float(self, expr: Expr) -> IntToFloatExpr:
        node = IntToFloatExpr(line=expr.line, column=expr.column, expr=expr)
        node.inferred_type = "float"
        return node

    def _coerce_assign(
        self,
        target_type: str,
        expr: Expr,
        expr_type: str,
        line: int,
        column: int,
        context: str,
    ) -> Expr:
        if expr_type == ERROR_TYPE or target_type == expr_type:
            return expr
        if self._is_reference_type(target_type) and expr_type == "null":
            return expr
        if target_type == "float" and expr_type == "int":
            return self._wrap_int_to_float(expr)
        self.reporter.report(
            "SEMÂNTICO",
            f"Tipos incompatíveis em {context}: esperado '{target_type}', encontrado '{expr_type}'.",
            line,
            column,
        )
        return expr

    def _require_bool(self, cond_type: str, line: int, column: int, context: str) -> None:
        if cond_type not in ("bool", ERROR_TYPE):
            self.reporter.report(
                "SEMÂNTICO",
                f"Condição do {context} deve ser do tipo 'bool', encontrado '{cond_type}'.",
                line,
                column,
            )
