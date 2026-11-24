"""Definição dos nós da Árvore Sintática Abstrata (AST) e visualizador em texto."""

from dataclasses import dataclass, field
from typing import Any, List, Optional


# ---------------------------------------------------------------------------
# Classes Base
# ---------------------------------------------------------------------------

@dataclass
class ASTNode:
    line: int
    column: int


@dataclass
class Stmt(ASTNode):
    """Classe base para comandos e declarações."""


@dataclass
class Expr(ASTNode):
    """Classe base para expressões."""

    inferred_type: Optional[str] = field(default=None, init=False, repr=False)


# ---------------------------------------------------------------------------
# Programa, Funções e Declarações
# ---------------------------------------------------------------------------

@dataclass
class Param(ASTNode):
    param_type: str
    name: str
    resolved_name: Optional[str] = field(default=None, init=False, repr=False)


@dataclass
class BlockStmt(Stmt):
    statements: List[Stmt]


@dataclass
class VarDecl(Stmt):
    var_type: str
    name: str
    initializer: Optional[Expr]
    is_const: bool = False
    resolved_name: Optional[str] = field(default=None, init=False, repr=False)


@dataclass
class FuncDecl(Stmt):
    return_type: str
    name: str
    params: List[Param]
    body: BlockStmt


@dataclass
class FieldDecl(ASTNode):
    field_type: str
    name: str
    access: str = "public"  # "public" | "private"


@dataclass
class MethodDecl(Stmt):
    """Método (ou construtor) de uma classe. 'this' é um parâmetro implícito."""

    return_type: str
    name: str
    params: List[Param]
    body: BlockStmt
    class_name: str
    access: str = "public"
    is_constructor: bool = False


@dataclass
class ClassDecl(Stmt):
    name: str
    fields: List[FieldDecl]
    methods: List[MethodDecl]


@dataclass
class Program(ASTNode):
    declarations: List[Stmt]  # FuncDecl, VarDecl ou ClassDecl globais


# ---------------------------------------------------------------------------
# Comandos (Statements)
# ---------------------------------------------------------------------------

@dataclass
class IfStmt(Stmt):
    condition: Expr
    then_branch: Stmt
    else_branch: Optional[Stmt]


@dataclass
class WhileStmt(Stmt):
    condition: Expr
    body: Stmt


@dataclass
class ForStmt(Stmt):
    init: Optional[Stmt]        # VarDecl ou ExprStmt (ou None)
    condition: Optional[Expr]
    update: Optional[Expr]
    body: Stmt


@dataclass
class ReturnStmt(Stmt):
    value: Optional[Expr]


@dataclass
class PrintStmt(Stmt):
    args: List[Expr]


@dataclass
class ReadStmt(Stmt):
    target_name: str
    target_line: int
    target_column: int
    target_type: Optional[str] = field(default=None, init=False, repr=False)
    resolved_name: Optional[str] = field(default=None, init=False, repr=False)


@dataclass
class ExprStmt(Stmt):
    expr: Expr


# ---------------------------------------------------------------------------
# Expressões (Expressions)
# ---------------------------------------------------------------------------

@dataclass
class LiteralExpr(Expr):
    value: Any
    literal_type: str  # "int", "float", "bool", "string"


@dataclass
class VarExpr(Expr):
    name: str
    resolved_name: Optional[str] = field(default=None, init=False, repr=False)


@dataclass
class AssignExpr(Expr):
    name: str
    value: Expr
    resolved_name: Optional[str] = field(default=None, init=False, repr=False)


@dataclass
class UnaryExpr(Expr):
    operator: str
    operand: Expr


@dataclass
class BinaryExpr(Expr):
    operator: str
    left: Expr
    right: Expr


@dataclass
class CallExpr(Expr):
    callee: str
    args: List[Expr]


@dataclass
class NewExpr(Expr):
    class_name: str
    args: List[Expr]


@dataclass
class ThisExpr(Expr):
    pass


@dataclass
class MemberExpr(Expr):
    """Acesso a campo: obj.campo"""

    obj: Expr
    member: str


@dataclass
class MemberAssignExpr(Expr):
    """Atribuição a campo: obj.campo = valor"""

    obj: Expr
    member: str
    value: Expr


@dataclass
class MethodCallExpr(Expr):
    """Chamada de método: obj.metodo(args)"""

    obj: Expr
    method: str
    args: List[Expr]


@dataclass
class BreakStmt(Stmt):
    """Comando break: encerra o laço mais interno."""


@dataclass
class ContinueStmt(Stmt):
    """Comando continue: avança para a próxima iteração do laço mais interno."""


@dataclass
class NewArrayExpr(Expr):
    """Alocação de vetor: new int[n]"""

    elem_type: str
    size: Expr


@dataclass
class IndexExpr(Expr):
    """Leitura de elemento de vetor: arr[i]"""

    array: Expr
    index: Expr


@dataclass
class IndexAssignExpr(Expr):
    """Escrita em elemento de vetor: arr[i] = val"""

    array: Expr
    index: Expr
    value: Expr


@dataclass
class IntToFloatExpr(Expr):
    """Nó de coerção implícita inserido na Fase 3 (Análise Semântica)."""

    expr: Expr


# ---------------------------------------------------------------------------
# Visualizador de AST em formato de árvore
# ---------------------------------------------------------------------------

def format_ast(node: ASTNode) -> str:
    """Retorna uma representação visual em árvore da AST para inspeção."""
    lines: List[str] = []
    _build_tree_lines(node, "", True, lines, is_root=True)
    return "\n".join(lines)


def _node_label(node: ASTNode) -> str:
    type_tag = ""
    if isinstance(node, Expr) and node.inferred_type is not None:
        type_tag = f" : {node.inferred_type}"

    if isinstance(node, Program):
        return "Program"
    if isinstance(node, FuncDecl):
        params = ", ".join(f"{p.param_type} {p.name}" for p in node.params)
        return f"FuncDecl({node.return_type} {node.name}({params}))"
    if isinstance(node, VarDecl):
        return f"VarDecl({node.var_type} {node.name})"
    if isinstance(node, BlockStmt):
        return "Block"
    if isinstance(node, IfStmt):
        return "IfStmt"
    if isinstance(node, WhileStmt):
        return "WhileStmt"
    if isinstance(node, ForStmt):
        return "ForStmt"
    if isinstance(node, ReturnStmt):
        return "ReturnStmt"
    if isinstance(node, PrintStmt):
        return "PrintStmt"
    if isinstance(node, ReadStmt):
        return f"ReadStmt({node.target_name})"
    if isinstance(node, ExprStmt):
        return "ExprStmt"
    if isinstance(node, LiteralExpr):
        return f"Literal({node.value!r}, {node.literal_type}){type_tag}"
    if isinstance(node, VarExpr):
        return f"Var({node.name}){type_tag}"
    if isinstance(node, AssignExpr):
        return f"Assign({node.name} =){type_tag}"
    if isinstance(node, UnaryExpr):
        return f"UnaryOp({node.operator!r}){type_tag}"
    if isinstance(node, BinaryExpr):
        return f"BinaryOp({node.operator!r}){type_tag}"
    if isinstance(node, CallExpr):
        return f"Call({node.callee}){type_tag}"
    if isinstance(node, IntToFloatExpr):
        return f"IntToFloat{type_tag}"
    if isinstance(node, ClassDecl):
        return f"ClassDecl({node.name})"
    if isinstance(node, FieldDecl):
        return f"FieldDecl({node.access} {node.field_type} {node.name})"
    if isinstance(node, MethodDecl):
        params = ", ".join(f"{p.param_type} {p.name}" for p in node.params)
        if node.is_constructor:
            return f"Constructor({node.access} {node.class_name}({params}))"
        return f"MethodDecl({node.access} {node.return_type} {node.name}({params}))"
    if isinstance(node, NewExpr):
        return f"New({node.class_name}){type_tag}"
    if isinstance(node, ThisExpr):
        return f"This{type_tag}"
    if isinstance(node, MemberExpr):
        return f"Member(.{node.member}){type_tag}"
    if isinstance(node, MemberAssignExpr):
        return f"MemberAssign(.{node.member} =){type_tag}"
    if isinstance(node, MethodCallExpr):
        return f"MethodCall(.{node.method}){type_tag}"
    return node.__class__.__name__


def _node_children(node: ASTNode) -> List[tuple]:
    """Retorna pares (rótulo_opcional, nó_filho)."""
    if isinstance(node, Program):
        return [(None, d) for d in node.declarations]
    if isinstance(node, FuncDecl):
        return [("body", node.body)]
    if isinstance(node, VarDecl):
        return [("init", node.initializer)] if node.initializer is not None else []
    if isinstance(node, BlockStmt):
        return [(None, s) for s in node.statements]
    if isinstance(node, IfStmt):
        children = [("cond", node.condition), ("then", node.then_branch)]
        if node.else_branch is not None:
            children.append(("else", node.else_branch))
        return children
    if isinstance(node, WhileStmt):
        return [("cond", node.condition), ("body", node.body)]
    if isinstance(node, ForStmt):
        children = []
        if node.init is not None:
            children.append(("init", node.init))
        if node.condition is not None:
            children.append(("cond", node.condition))
        if node.update is not None:
            children.append(("update", node.update))
        children.append(("body", node.body))
        return children
    if isinstance(node, ReturnStmt):
        return [("value", node.value)] if node.value is not None else []
    if isinstance(node, PrintStmt):
        return [(f"arg[{i}]", arg) for i, arg in enumerate(node.args)]
    if isinstance(node, ExprStmt):
        return [(None, node.expr)]
    if isinstance(node, AssignExpr):
        return [("value", node.value)]
    if isinstance(node, UnaryExpr):
        return [(None, node.operand)]
    if isinstance(node, BinaryExpr):
        return [("left", node.left), ("right", node.right)]
    if isinstance(node, CallExpr):
        return [(f"arg[{i}]", arg) for i, arg in enumerate(node.args)]
    if isinstance(node, IntToFloatExpr):
        return [(None, node.expr)]
    if isinstance(node, ClassDecl):
        return [("field", f) for f in node.fields] + [("method", m) for m in node.methods]
    if isinstance(node, MethodDecl):
        return [("body", node.body)]
    if isinstance(node, NewExpr):
        return [(f"arg[{i}]", arg) for i, arg in enumerate(node.args)]
    if isinstance(node, MemberExpr):
        return [("obj", node.obj)]
    if isinstance(node, MemberAssignExpr):
        return [("obj", node.obj), ("value", node.value)]
    if isinstance(node, MethodCallExpr):
        return [("obj", node.obj)] + [(f"arg[{i}]", arg) for i, arg in enumerate(node.args)]
    if isinstance(node, NewArrayExpr):
        return [("size", node.size)]
    if isinstance(node, IndexExpr):
        return [("array", node.array), ("index", node.index)]
    if isinstance(node, IndexAssignExpr):
        return [("array", node.array), ("index", node.index), ("value", node.value)]
    return []


def _build_tree_lines(
    node: ASTNode,
    prefix: str,
    is_last: bool,
    lines: List[str],
    is_root: bool = False,
    edge_label: Optional[str] = None,
) -> None:
    connector = "" if is_root else ("└── " if is_last else "├── ")
    edge = f"{edge_label}: " if edge_label else ""
    lines.append(f"{prefix}{connector}{edge}{_node_label(node)}")

    children = _node_children(node)
    child_prefix = "" if is_root else (prefix + ("    " if is_last else "│   "))
    for idx, (label, child) in enumerate(children):
        _build_tree_lines(
            child,
            child_prefix,
            idx == len(children) - 1,
            lines,
            is_root=False,
            edge_label=label,
        )
