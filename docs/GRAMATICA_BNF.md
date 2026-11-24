# Gramática Formal da Linguagem MiniC (EBNF)

A gramática abaixo foi projetada como uma **Gramática Livre de Contexto (GLC)** não-ambígua e livre de recursão à esquerda, adequada para análise sintática *Top-Down* Preditiva (*Recursive Descent*).

## Produções

```ebnf
program        ::= declaration* EOF

declaration    ::= func_decl
                 | var_decl

func_decl      ::= type_spec ID '(' param_list? ')' block
param_list     ::= param ( ',' param )*
param          ::= var_type ID

var_decl       ::= var_type ID ( '=' expr )? ';'
type_spec      ::= 'int' | 'float' | 'bool' | 'string' | 'void'
var_type       ::= 'int' | 'float' | 'bool' | 'string'

block          ::= '{' stmt* '}'

stmt           ::= var_decl
                 | if_stmt
                 | while_stmt
                 | for_stmt
                 | return_stmt
                 | print_stmt
                 | read_stmt
                 | block
                 | expr_stmt

if_stmt        ::= 'if' '(' expr ')' stmt ( 'else' stmt )?
while_stmt     ::= 'while' '(' expr ')' stmt
for_stmt       ::= 'for' '(' for_init? ';' expr? ';' expr? ')' stmt
for_init       ::= var_type ID ( '=' expr )?
                 | expr
return_stmt    ::= 'return' expr? ';'
print_stmt     ::= 'print' '(' arg_list? ')' ';'
read_stmt      ::= 'read' '(' ID ')' ';'
expr_stmt      ::= expr ';'

expr           ::= assignment
assignment     ::= ID '=' assignment
                 | logic_or
logic_or       ::= logic_and ( '||' logic_and )*
logic_and      ::= equality ( '&&' equality )*
equality       ::= relational ( ( '==' | '!=' ) relational )*
relational     ::= additive ( ( '<' | '<=' | '>' | '>=' ) additive )*
additive       ::= multiplicative ( ( '+' | '-' ) multiplicative )*
multiplicative ::= unary ( ( '*' | '/' | '%' ) unary )*
unary          ::= ( '!' | '-' ) unary
                 | primary
primary        ::= INT_LIT
                 | FLOAT_LIT
                 | STRING_LIT
                 | 'true'
                 | 'false'
                 | ID '(' arg_list? ')'
                 | ID
                 | '(' expr ')'

arg_list       ::= expr ( ',' expr )*
```

## Tabela de Precedência e Associatividade

| Nível (menor → maior) | Operadores | Associatividade |
| :---: | :--- | :--- |
| 1 | `=` (atribuição) | Direita (`a = b = 1` ≡ `a = (b = 1)`) |
| 2 | `\|\|` (OU lógico) | Esquerda |
| 3 | `&&` (E lógico) | Esquerda |
| 4 | `==`, `!=` (igualdade) | Esquerda |
| 5 | `<`, `<=`, `>`, `>=` (relacionais) | Esquerda |
| 6 | `+`, `-` (adição/subtração) | Esquerda (`9 - 5 + 2` ≡ `(9 - 5) + 2`) |
| 7 | `*`, `/`, `%` (multiplicação/divisão/módulo) | Esquerda |
| 8 | `!`, `-` (unários) | Direita |
| 9 | `( ... )`, chamadas `f(...)`, literais, variáveis | — |
