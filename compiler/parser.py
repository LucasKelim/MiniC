"""Fase 2: Analisador Sintático (Parser Recursive Descent Top-Down) + construção da AST."""

from typing import List, Optional, Tuple, Tuple

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
    LiteralExpr,
    MemberAssignExpr,
    MemberExpr,
    MethodCallExpr,
    MethodDecl,
    NewArrayExpr,
    NewExpr,
    Param,
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
from .tokens import Token, TokenType


TYPE_TOKENS = (
    TokenType.INT,
    TokenType.FLOAT,
    TokenType.BOOL,
    TokenType.STRING,
    TokenType.VOID,
)

VAR_TYPE_TOKENS = (
    TokenType.INT,
    TokenType.FLOAT,
    TokenType.BOOL,
    TokenType.STRING,
)


class _ParseError(Exception):
    """Exceção interna usada para acionar recuperação em modo pânico."""


class Parser:
    """Analisador sintático Top-Down Preditivo (Recursive Descent).

    - Cada método corresponde a um não-terminal da gramática em docs/GRAMATICA_BNF.md.
    - Utiliza laços while para operadores associativos à esquerda (eliminando recursão à esquerda).
    - Em caso de erro sintático, registra o diagnóstico e sincroniza até um ponto seguro
      (modo pânico), permitindo detectar múltiplos erros em uma única compilação.
    """

    def __init__(self, tokens: List[Token], reporter: ErrorReporter) -> None:
        self.tokens = tokens
        self.reporter = reporter
        self.current = 0

    # ------------------------------------------------------------------
    # Utilitários de navegação pelos tokens (lookahead)
    # ------------------------------------------------------------------

    def _peek(self, offset: int = 0) -> Token:
        idx = self.current + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def _previous(self) -> Token:
        return self.tokens[self.current - 1]

    def _is_at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _advance(self) -> Token:
        if not self._is_at_end():
            self.current += 1
        return self._previous()

    def _check(self, token_type: TokenType, offset: int = 0) -> bool:
        return self._peek(offset).type == token_type

    def _check_any(self, types: Tuple[TokenType, ...], offset: int = 0) -> bool:
        return self._peek(offset).type in types

    def _match(self, *types: TokenType) -> bool:
        for t in types:
            if self._check(t):
                self._advance()
                return True
        return False

    def _consume(self, expected: TokenType, message: str) -> Token:
        if self._check(expected):
            return self._advance()
        raise self._error(self._peek(), message)

    def _error(self, token: Token, message: str) -> _ParseError:
        found = "fim de arquivo" if token.type == TokenType.EOF else f"'{token.lexeme}'"
        self.reporter.report("SINTÁTICO", f"{message} (encontrado {found}).", token.line, token.column)
        return _ParseError()

    def _synchronize(self, stop_at_rbrace: bool = True, force_advance: bool = False) -> None:
        """Recuperação em modo pânico: sincroniza até um ponto seguro sem entrar em loop."""
        if force_advance and not self._is_at_end():
            self._advance()

        sync_starters = (
            TokenType.INT,
            TokenType.FLOAT,
            TokenType.BOOL,
            TokenType.STRING,
            TokenType.VOID,
            TokenType.IF,
            TokenType.WHILE,
            TokenType.FOR,
            TokenType.RETURN,
            TokenType.PRINT,
            TokenType.READ,
            TokenType.CLASS,
            TokenType.LBRACE,
        )

        while not self._is_at_end():
            if self._previous().type == TokenType.SEMICOLON:
                return
            if stop_at_rbrace and self._peek().type == TokenType.RBRACE:
                return
            if self._peek().type in sync_starters:
                return
            self._advance()

    # ------------------------------------------------------------------
    # Ponto de entrada: program -> declaration* EOF
    # ------------------------------------------------------------------

    def parse(self) -> Program:
        start_tok = self._peek()
        declarations: List[Stmt] = []

        while not self._is_at_end():
            start_pos = self.current
            try:
                decl = self._declaration()
                if decl is not None:
                    declarations.append(decl)
            except _ParseError:
                self._synchronize(stop_at_rbrace=False, force_advance=(self.current == start_pos))
                if self._check(TokenType.RBRACE):
                    self._advance()

        return Program(line=start_tok.line, column=start_tok.column, declarations=declarations)

    # ------------------------------------------------------------------
    # Declarações globais: func_decl | var_decl
    # ------------------------------------------------------------------

    def _parse_type(self) -> Tuple[str, Token]:
        """Lê um tipo primitivo ou nome de classe, opcionalmente seguido de '[]'."""
        type_tok = self._advance()
        type_name = type_tok.lexeme
        if self._check(TokenType.LBRACKET) and self._check(TokenType.RBRACKET, offset=1):
            self._advance()
            self._advance()
            type_name += "[]"
        return type_name, type_tok

    def _declaration(self) -> Stmt:
        if self._check(TokenType.CLASS):
            return self._class_decl()

        is_const = self._match(TokenType.CONST)

        if not (self._check_any(TYPE_TOKENS) or self._check(TokenType.ID)):
            raise self._error(
                self._peek(),
                "Esperada declaração de classe, função ou variável global começando com um tipo",
            )

        type_name, type_tok = self._parse_type()
        name_tok = self._consume(TokenType.ID, "Esperado identificador após o tipo")

        # Lookahead: '(' indica declaração de função; caso contrário, variável global
        if not is_const and self._match(TokenType.LPAREN):
            return self._finish_func_decl(type_name, type_tok, name_tok)

        if type_name == "void":
            raise self._error(type_tok, "Variável não pode ser declarada com tipo 'void'")

        return self._finish_var_decl(type_name, type_tok, name_tok, consume_semicolon=True, is_const=is_const)

    def _is_var_decl_start(self) -> bool:
        """Reconhece 'const ...', 'tipo nome', 'tipo[] nome' ou 'Classe nome' / 'Classe[] nome'."""
        if self._check(TokenType.CONST):
            return True
        if self._check_any(VAR_TYPE_TOKENS):
            return True
        if self._check(TokenType.ID):
            if self._check(TokenType.ID, offset=1):
                return True
            if (
                self._check(TokenType.LBRACKET, offset=1)
                and self._check(TokenType.RBRACKET, offset=2)
                and self._check(TokenType.ID, offset=3)
            ):
                return True
        return False

    def _parse_params(self) -> List[Param]:
        """Lê 'tipo nome (, tipo nome)* )' — o '(' já foi consumido."""
        params: List[Param] = []
        if not self._check(TokenType.RPAREN):
            while True:
                if not (self._check_any(VAR_TYPE_TOKENS) or self._check(TokenType.ID)):
                    raise self._error(
                        self._peek(),
                        "Esperado tipo válido para parâmetro ('int', 'float', 'bool', 'string' ou nome de classe)",
                    )
                p_type_name, p_type = self._parse_type()
                p_name = self._consume(TokenType.ID, "Esperado nome do parâmetro")
                params.append(Param(p_type.line, p_type.column, p_type_name, p_name.lexeme))
                if not self._match(TokenType.COMMA):
                    break
        self._consume(TokenType.RPAREN, "Esperado ')' após a lista de parâmetros")
        return params

    def _finish_func_decl(self, return_type: str, type_tok: Token, name_tok: Token) -> FuncDecl:
        params = self._parse_params()
        body = self._block()
        return FuncDecl(
            line=type_tok.line,
            column=type_tok.column,
            return_type=return_type,
            name=name_tok.lexeme,
            params=params,
            body=body,
        )

    # ------------------------------------------------------------------
    # Classes: class ID '{' (campo | método | construtor)* '}'
    # ------------------------------------------------------------------

    def _class_decl(self) -> ClassDecl:
        class_tok = self._advance()
        name_tok = self._consume(TokenType.ID, "Esperado nome da classe após 'class'")
        self._consume(TokenType.LBRACE, "Esperado '{' para iniciar o corpo da classe")

        fields: List[FieldDecl] = []
        methods: List[MethodDecl] = []
        while not self._check(TokenType.RBRACE) and not self._is_at_end():
            start_pos = self.current
            try:
                self._class_member(name_tok.lexeme, fields, methods)
            except _ParseError:
                self._synchronize(stop_at_rbrace=True, force_advance=(self.current == start_pos))

        self._consume(TokenType.RBRACE, "Esperado '}' para fechar a classe")
        return ClassDecl(
            line=class_tok.line,
            column=class_tok.column,
            name=name_tok.lexeme,
            fields=fields,
            methods=methods,
        )

    def _class_member(self, class_name: str, fields: List[FieldDecl], methods: List[MethodDecl]) -> None:
        access = "public"
        if self._match(TokenType.PUBLIC):
            access = "public"
        elif self._match(TokenType.PRIVATE):
            access = "private"

        # Construtor: NomeDaClasse '(' ... ')' bloco
        if (
            self._check(TokenType.ID)
            and self._peek().lexeme == class_name
            and self._check(TokenType.LPAREN, offset=1)
        ):
            ctor_tok = self._advance()
            self._advance()  # '('
            params = self._parse_params()
            body = self._block()
            methods.append(
                MethodDecl(
                    line=ctor_tok.line,
                    column=ctor_tok.column,
                    return_type="void",
                    name=class_name,
                    params=params,
                    body=body,
                    class_name=class_name,
                    access=access,
                    is_constructor=True,
                )
            )
            return

        if not (self._check_any(TYPE_TOKENS) or self._check(TokenType.ID)):
            raise self._error(self._peek(), "Esperado tipo de campo, método ou construtor na classe")

        type_name, type_tok = self._parse_type()
        name_tok = self._consume(TokenType.ID, "Esperado nome do campo ou método")

        if self._match(TokenType.LPAREN):
            params = self._parse_params()
            body = self._block()
            methods.append(
                MethodDecl(
                    line=type_tok.line,
                    column=type_tok.column,
                    return_type=type_name,
                    name=name_tok.lexeme,
                    params=params,
                    body=body,
                    class_name=class_name,
                    access=access,
                )
            )
            return

        if type_name == "void":
            raise self._error(type_tok, "Campo não pode ser declarado com tipo 'void'")
        self._consume(TokenType.SEMICOLON, "Esperado ';' após declaração de campo")
        fields.append(
            FieldDecl(
                line=type_tok.line,
                column=type_tok.column,
                field_type=type_name,
                name=name_tok.lexeme,
                access=access,
            )
        )

    def _finish_var_decl(
        self,
        var_type: str,
        type_tok: Token,
        name_tok: Token,
        consume_semicolon: bool = True,
        is_const: bool = False,
    ) -> VarDecl:
        initializer: Optional[Expr] = None
        if self._match(TokenType.ASSIGN):
            initializer = self._expr()
        if consume_semicolon:
            self._consume(TokenType.SEMICOLON, "Esperado ';' após declaração de variável")
        return VarDecl(
            line=type_tok.line,
            column=type_tok.column,
            var_type=var_type,
            name=name_tok.lexeme,
            initializer=initializer,
            is_const=is_const,
        )

    def _var_decl(self, consume_semicolon: bool = True) -> VarDecl:
        is_const = self._match(TokenType.CONST)
        type_name, type_tok = self._parse_type()
        name_tok = self._consume(TokenType.ID, "Esperado nome da variável após o tipo")
        return self._finish_var_decl(
            type_name, type_tok, name_tok, consume_semicolon=consume_semicolon, is_const=is_const
        )

    # ------------------------------------------------------------------
    # Blocos e comandos (Statements)
    # ------------------------------------------------------------------

    def _block(self) -> BlockStmt:
        lbrace = self._consume(TokenType.LBRACE, "Esperado '{' para iniciar bloco")
        statements: List[Stmt] = []

        while not self._check(TokenType.RBRACE) and not self._is_at_end():
            start_pos = self.current
            try:
                statements.append(self._stmt())
            except _ParseError:
                self._synchronize(stop_at_rbrace=True, force_advance=(self.current == start_pos))

        self._consume(TokenType.RBRACE, "Esperado '}' para fechar bloco")
        return BlockStmt(line=lbrace.line, column=lbrace.column, statements=statements)

    def _stmt(self) -> Stmt:
        if self._is_var_decl_start():
            return self._var_decl(consume_semicolon=True)
        if self._check(TokenType.VOID):
            raise self._error(self._peek(), "Variável local não pode ter tipo 'void'")
        if self._check(TokenType.IF):
            return self._if_stmt()
        if self._check(TokenType.WHILE):
            return self._while_stmt()
        if self._check(TokenType.FOR):
            return self._for_stmt()
        if self._check(TokenType.BREAK):
            tok = self._advance()
            self._consume(TokenType.SEMICOLON, "Esperado ';' após 'break'")
            return BreakStmt(line=tok.line, column=tok.column)
        if self._check(TokenType.CONTINUE):
            tok = self._advance()
            self._consume(TokenType.SEMICOLON, "Esperado ';' após 'continue'")
            return ContinueStmt(line=tok.line, column=tok.column)
        if self._check(TokenType.RETURN):
            return self._return_stmt()
        if self._check(TokenType.PRINT):
            return self._print_stmt()
        if self._check(TokenType.READ):
            return self._read_stmt()
        if self._check(TokenType.LBRACE):
            return self._block()
        return self._expr_stmt()

    def _if_stmt(self) -> IfStmt:
        if_tok = self._advance()
        self._consume(TokenType.LPAREN, "Esperado '(' após 'if'")
        condition = self._expr()
        self._consume(TokenType.RPAREN, "Esperado ')' após condição do 'if'")
        then_branch = self._stmt()
        else_branch: Optional[Stmt] = None
        if self._match(TokenType.ELSE):
            else_branch = self._stmt()
        return IfStmt(
            line=if_tok.line,
            column=if_tok.column,
            condition=condition,
            then_branch=then_branch,
            else_branch=else_branch,
        )

    def _while_stmt(self) -> WhileStmt:
        while_tok = self._advance()
        self._consume(TokenType.LPAREN, "Esperado '(' após 'while'")
        condition = self._expr()
        self._consume(TokenType.RPAREN, "Esperado ')' após condição do 'while'")
        body = self._stmt()
        return WhileStmt(line=while_tok.line, column=while_tok.column, condition=condition, body=body)

    def _for_stmt(self) -> ForStmt:
        for_tok = self._advance()
        self._consume(TokenType.LPAREN, "Esperado '(' após 'for'")

        init: Optional[Stmt] = None
        if not self._check(TokenType.SEMICOLON):
            if self._is_var_decl_start():
                init = self._var_decl(consume_semicolon=False)
            else:
                init_expr = self._expr()
                init = ExprStmt(init_expr.line, init_expr.column, init_expr)
        self._consume(TokenType.SEMICOLON, "Esperado ';' após inicialização do 'for'")

        condition: Optional[Expr] = None
        if not self._check(TokenType.SEMICOLON):
            condition = self._expr()
        self._consume(TokenType.SEMICOLON, "Esperado ';' após condição do 'for'")

        update: Optional[Expr] = None
        if not self._check(TokenType.RPAREN):
            update = self._expr()
        self._consume(TokenType.RPAREN, "Esperado ')' após cabeçalho do 'for'")

        body = self._stmt()
        return ForStmt(
            line=for_tok.line,
            column=for_tok.column,
            init=init,
            condition=condition,
            update=update,
            body=body,
        )

    def _return_stmt(self) -> ReturnStmt:
        ret_tok = self._advance()
        value: Optional[Expr] = None
        if not self._check(TokenType.SEMICOLON):
            value = self._expr()
        self._consume(TokenType.SEMICOLON, "Esperado ';' após comando 'return'")
        return ReturnStmt(line=ret_tok.line, column=ret_tok.column, value=value)

    def _print_stmt(self) -> PrintStmt:
        print_tok = self._advance()
        self._consume(TokenType.LPAREN, "Esperado '(' após 'print'")
        args: List[Expr] = []
        if not self._check(TokenType.RPAREN):
            args = self._arg_list()
        self._consume(TokenType.RPAREN, "Esperado ')' após argumentos de 'print'")
        self._consume(TokenType.SEMICOLON, "Esperado ';' após comando 'print'")
        return PrintStmt(line=print_tok.line, column=print_tok.column, args=args)

    def _read_stmt(self) -> ReadStmt:
        read_tok = self._advance()
        self._consume(TokenType.LPAREN, "Esperado '(' após 'read'")
        target = self._consume(TokenType.ID, "Esperado identificador de variável em 'read'")
        self._consume(TokenType.RPAREN, "Esperado ')' após variável em 'read'")
        self._consume(TokenType.SEMICOLON, "Esperado ';' após comando 'read'")
        return ReadStmt(
            line=read_tok.line,
            column=read_tok.column,
            target_name=target.lexeme,
            target_line=target.line,
            target_column=target.column,
        )

    def _expr_stmt(self) -> ExprStmt:
        expr = self._expr()
        self._consume(TokenType.SEMICOLON, "Esperado ';' após expressão")
        return ExprStmt(line=expr.line, column=expr.column, expr=expr)

    # ------------------------------------------------------------------
    # Expressões (hierarquia de precedência)
    # ------------------------------------------------------------------

    def _expr(self) -> Expr:
        return self._assignment()

    def _assignment(self) -> Expr:
        # Atribuição associativa à direita; suporta =, +=, -=, *=, /=, %=
        expr = self._logic_or()
        compound_map = {
            TokenType.PLUS_EQ: "+",
            TokenType.MINUS_EQ: "-",
            TokenType.STAR_EQ: "*",
            TokenType.SLASH_EQ: "/",
            TokenType.PERCENT_EQ: "%",
        }
        if self._check(TokenType.ASSIGN) or self._check_any(tuple(compound_map.keys())):
            eq_tok = self._advance()
            rhs = self._assignment()
            if eq_tok.type in compound_map:
                op = compound_map[eq_tok.type]
                rhs = BinaryExpr(line=eq_tok.line, column=eq_tok.column, operator=op, left=expr, right=rhs)
            if isinstance(expr, VarExpr):
                return AssignExpr(line=expr.line, column=expr.column, name=expr.name, value=rhs)
            if isinstance(expr, MemberExpr):
                return MemberAssignExpr(
                    line=expr.line, column=expr.column, obj=expr.obj, member=expr.member, value=rhs
                )
            if isinstance(expr, IndexExpr):
                return IndexAssignExpr(
                    line=expr.line, column=expr.column, array=expr.array, index=expr.index, value=rhs
                )
            raise self._error(eq_tok, "Alvo de atribuição inválido (use variável, obj.campo ou arr[i])")
        return expr

    def _logic_or(self) -> Expr:
        expr = self._logic_and()
        while self._match(TokenType.OR):
            op = self._previous()
            right = self._logic_and()
            expr = BinaryExpr(line=op.line, column=op.column, operator=op.lexeme, left=expr, right=right)
        return expr

    def _logic_and(self) -> Expr:
        expr = self._equality()
        while self._match(TokenType.AND):
            op = self._previous()
            right = self._equality()
            expr = BinaryExpr(line=op.line, column=op.column, operator=op.lexeme, left=expr, right=right)
        return expr

    def _equality(self) -> Expr:
        expr = self._relational()
        while self._match(TokenType.EQ, TokenType.NEQ):
            op = self._previous()
            right = self._relational()
            expr = BinaryExpr(line=op.line, column=op.column, operator=op.lexeme, left=expr, right=right)
        return expr

    def _relational(self) -> Expr:
        expr = self._additive()
        while self._match(TokenType.LT, TokenType.LTE, TokenType.GT, TokenType.GTE):
            op = self._previous()
            right = self._additive()
            expr = BinaryExpr(line=op.line, column=op.column, operator=op.lexeme, left=expr, right=right)
        return expr

    def _additive(self) -> Expr:
        expr = self._multiplicative()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            op = self._previous()
            right = self._multiplicative()
            expr = BinaryExpr(line=op.line, column=op.column, operator=op.lexeme, left=expr, right=right)
        return expr

    def _multiplicative(self) -> Expr:
        expr = self._unary()
        while self._match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op = self._previous()
            right = self._unary()
            expr = BinaryExpr(line=op.line, column=op.column, operator=op.lexeme, left=expr, right=right)
        return expr

    def _unary(self) -> Expr:
        if self._match(TokenType.NOT, TokenType.MINUS):
            op = self._previous()
            operand = self._unary()
            return UnaryExpr(line=op.line, column=op.column, operator=op.lexeme, operand=operand)
        return self._postfix()

    def _postfix(self) -> Expr:
        """primary ( '.' ID ( '(' args ')' )? | '[' expr ']' | '++' | '--' )*"""
        expr = self._primary()
        while True:
            if self._match(TokenType.DOT):
                member = self._consume(TokenType.ID, "Esperado nome de campo ou método após '.'")
                if self._match(TokenType.LPAREN):
                    args: List[Expr] = []
                    if not self._check(TokenType.RPAREN):
                        args = self._arg_list()
                    self._consume(TokenType.RPAREN, f"Esperado ')' após argumentos do método '{member.lexeme}'")
                    expr = MethodCallExpr(
                        line=member.line, column=member.column, obj=expr, method=member.lexeme, args=args
                    )
                else:
                    expr = MemberExpr(line=member.line, column=member.column, obj=expr, member=member.lexeme)
            elif self._match(TokenType.LBRACKET):
                lbr = self._previous()
                idx_expr = self._expr()
                self._consume(TokenType.RBRACKET, "Esperado ']' após índice do vetor")
                expr = IndexExpr(line=lbr.line, column=lbr.column, array=expr, index=idx_expr)
            elif self._match(TokenType.PLUS_PLUS, TokenType.MINUS_MINUS):
                op_tok = self._previous()
                op = "+" if op_tok.type == TokenType.PLUS_PLUS else "-"
                one = LiteralExpr(op_tok.line, op_tok.column, 1, "int")
                rhs = BinaryExpr(op_tok.line, op_tok.column, op, expr, one)
                if isinstance(expr, VarExpr):
                    expr = AssignExpr(expr.line, expr.column, expr.name, rhs)
                elif isinstance(expr, MemberExpr):
                    expr = MemberAssignExpr(expr.line, expr.column, expr.obj, expr.member, rhs)
                elif isinstance(expr, IndexExpr):
                    expr = IndexAssignExpr(expr.line, expr.column, expr.array, expr.index, rhs)
                else:
                    raise self._error(op_tok, f"Operador '{op_tok.lexeme}' requer variável, campo ou elemento de vetor")
            else:
                break
        return expr

    def _primary(self) -> Expr:
        tok = self._peek()

        if self._match(TokenType.INT_LIT):
            return LiteralExpr(tok.line, tok.column, tok.value, "int")
        if self._match(TokenType.FLOAT_LIT):
            return LiteralExpr(tok.line, tok.column, tok.value, "float")
        if self._match(TokenType.STRING_LIT):
            return LiteralExpr(tok.line, tok.column, tok.value, "string")
        if self._match(TokenType.TRUE, TokenType.FALSE):
            return LiteralExpr(tok.line, tok.column, tok.value, "bool")
        if self._match(TokenType.NULL):
            return LiteralExpr(tok.line, tok.column, None, "null")
        if self._match(TokenType.THIS):
            return ThisExpr(tok.line, tok.column)
        if self._match(TokenType.NEW):
            if self._check_any(VAR_TYPE_TOKENS) or self._check(TokenType.ID):
                type_tok = self._advance()
                # Alocação de vetor: new tipo[tamanho]
                if self._match(TokenType.LBRACKET):
                    size_expr = self._expr()
                    self._consume(TokenType.RBRACKET, "Esperado ']' após tamanho do vetor em 'new'")
                    return NewArrayExpr(tok.line, tok.column, type_tok.lexeme, size_expr)
                # Instanciação de objeto: new Classe(args)
                if type_tok.type != TokenType.ID:
                    raise self._error(type_tok, "Esperado '[' após tipo primitivo em 'new' ou nome de classe")
                self._consume(TokenType.LPAREN, "Esperado '(' após o nome da classe em 'new'")
                new_args: List[Expr] = []
                if not self._check(TokenType.RPAREN):
                    new_args = self._arg_list()
                self._consume(TokenType.RPAREN, "Esperado ')' após argumentos do construtor")
                return NewExpr(tok.line, tok.column, type_tok.lexeme, new_args)
            raise self._error(self._peek(), "Esperado tipo ou nome de classe após 'new'")

        if self._match(TokenType.ID):
            if self._match(TokenType.LPAREN):
                args: List[Expr] = []
                if not self._check(TokenType.RPAREN):
                    args = self._arg_list()
                self._consume(TokenType.RPAREN, f"Esperado ')' após argumentos da chamada '{tok.lexeme}'")
                return CallExpr(tok.line, tok.column, tok.lexeme, args)
            return VarExpr(tok.line, tok.column, tok.lexeme)

        if self._match(TokenType.LPAREN):
            expr = self._expr()
            self._consume(TokenType.RPAREN, "Esperado ')' para fechar expressão entre parênteses")
            return expr

        raise self._error(tok, "Esperada expressão (literal, variável, chamada ou '(')")

    def _arg_list(self) -> List[Expr]:
        args = [self._expr()]
        while self._match(TokenType.COMMA):
            args.append(self._expr())
        return args
