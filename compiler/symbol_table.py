"""Fase 3: Gerenciador da Tabela de Símbolos (Tabela Hash com pilha de escopos)."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


TYPE_SIZES: Dict[str, int] = {
    "int": 4,      # inteiro 32 bits com sinal
    "float": 8,    # ponto flutuante IEEE 754 precisão dupla (64 bits)
    "bool": 1,     # booleano (1 byte)
    "string": 8,   # ponteiro para literal de string (64 bits)
    "void": 0,
}


@dataclass
class FieldInfo:
    name: str
    data_type: str
    access: str
    offset: int         # deslocamento em bytes dentro do objeto (slots de 8 bytes)
    decl_line: int


@dataclass
class MethodInfo:
    name: str
    return_type: str
    param_types: List[str]
    access: str
    is_constructor: bool
    decl_line: int


@dataclass
class ClassInfo:
    """Metadados de uma classe: campos (com layout), métodos e construtor."""

    name: str
    decl_line: int
    fields: Dict[str, FieldInfo] = field(default_factory=dict)
    methods: Dict[str, MethodInfo] = field(default_factory=dict)
    constructor: Optional[MethodInfo] = None

    @property
    def size_bytes(self) -> int:
        return max(8, 8 * len(self.fields))


@dataclass
class Symbol:
    """Metadados de um identificador registrado na Tabela de Símbolos."""

    symbol_id: str          # id1, id2, ...
    name: str               # nome no código-fonte
    unique_name: str        # nome interno desambiguado para escopos aninhados
    category: str           # "var", "param", "func"
    data_type: str          # "int", "float", "bool", "string", "void"
    scope_level: int        # 0 = global, 1 = função, 2+ = blocos internos
    scope_name: str         # ex: "global", "func:main", "block@L10"
    size_bytes: int
    offset: int             # deslocamento relativo em bytes no escopo/frame
    decl_line: int
    usage_lines: List[int] = field(default_factory=list)
    param_types: List[str] = field(default_factory=list)
    is_const: bool = False

    def add_usage(self, line: int) -> None:
        if line not in self.usage_lines:
            self.usage_lines.append(line)


class Scope:
    """Um nível de escopo armazenado em Tabela Hash (dict)."""

    def __init__(self, level: int, name: str, parent: Optional["Scope"] = None) -> None:
        self.level = level
        self.name = name
        self.parent = parent
        self.symbols: Dict[str, Symbol] = {}
        self.next_offset: int = 0 if level <= 1 else (parent.next_offset if parent else 0)

    def define(self, symbol: Symbol) -> None:
        self.symbols[symbol.name] = symbol

    def lookup_local(self, name: str) -> Optional[Symbol]:
        return self.symbols.get(name)

    def lookup(self, name: str) -> Optional[Symbol]:
        scope: Optional[Scope] = self
        while scope is not None:
            sym = scope.symbols.get(name)
            if sym is not None:
                return sym
            scope = scope.parent
        return None


class SymbolTable:
    """Gerenciador hierárquico de Tabelas de Símbolos (escopo estático)."""

    def __init__(self) -> None:
        self.global_scope = Scope(level=0, name="global", parent=None)
        self.current_scope = self.global_scope
        self.all_symbols: List[Symbol] = []
        self.classes: Dict[str, ClassInfo] = {}
        self._id_counter = 0
        self._name_counts: Dict[str, int] = {}

    def enter_scope(self, name: str) -> Scope:
        new_scope = Scope(
            level=self.current_scope.level + 1,
            name=name,
            parent=self.current_scope,
        )
        self.current_scope = new_scope
        return new_scope

    def exit_scope(self) -> None:
        if self.current_scope.parent is not None:
            # Propaga o offset acumulado para o frame da função pai quando sai de bloco interno
            if self.current_scope.level >= 2 and self.current_scope.parent.level >= 1:
                self.current_scope.parent.next_offset = max(
                    self.current_scope.parent.next_offset,
                    self.current_scope.next_offset,
                )
            self.current_scope = self.current_scope.parent

    def declare(
        self,
        name: str,
        category: str,
        data_type: str,
        decl_line: int,
        param_types: Optional[List[str]] = None,
        is_const: bool = False,
    ) -> Optional[Symbol]:
        """Insere um símbolo no escopo atual. Retorna None se já existir no mesmo escopo."""
        if self.current_scope.lookup_local(name) is not None:
            return None

        self._id_counter += 1
        sym_id = f"id{self._id_counter}"
        size = 0 if category in ("func", "class") else TYPE_SIZES.get(data_type, 8)  # objetos = ponteiro (8 B)

        # Alinhamento simples e cálculo de offset relativo dentro do escopo/frame
        offset = self.current_scope.next_offset if category not in ("func", "class") else 0
        if category not in ("func", "class"):
            self.current_scope.next_offset += size

        # Desambiguação para sombreamento (shadowing) em blocos internos e globais
        if category in ("func", "class"):
            unique_name = name
        elif self.current_scope.level == 0:
            unique_name = name
            self._name_counts[name] = self._name_counts.get(name, 0) + 1
        else:
            count = self._name_counts.get(name, 0)
            self._name_counts[name] = count + 1
            unique_name = name if count == 0 else f"{name}_{count}"

        symbol = Symbol(
            symbol_id=sym_id,
            name=name,
            unique_name=unique_name,
            category=category,
            data_type=data_type,
            scope_level=self.current_scope.level,
            scope_name=self.current_scope.name,
            size_bytes=size,
            offset=offset,
            decl_line=decl_line,
            param_types=list(param_types) if param_types else [],
            is_const=is_const,
        )
        self.current_scope.define(symbol)
        self.all_symbols.append(symbol)
        return symbol

    def lookup(self, name: str) -> Optional[Symbol]:
        return self.current_scope.lookup(name)

    def lookup_local(self, name: str) -> Optional[Symbol]:
        return self.current_scope.lookup_local(name)

    def format_table(self) -> str:
        header = (
            f"{'ID':<5}  {'NOME':<16}  {'CAT':<6}  {'TIPO':<8}  "
            f"{'ESC':<3}  {'ESCOPO':<20}  {'TAM':>3}  {'OFF':>4}  {'DECL':>4}  {'USOS / PARAMS'}"
        )
        sep = "-" * 102
        rows = [header, sep]
        for sym in self.all_symbols:
            usos = ",".join(str(ln) for ln in sym.usage_lines) if sym.usage_lines else "-"
            extra = f"usos=[{usos}]"
            if sym.category == "func":
                params = ", ".join(sym.param_types) if sym.param_types else "void"
                extra = f"params=({params}) {extra}"
            rows.append(
                f"{sym.symbol_id:<5}  {sym.name:<16}  {sym.category:<6}  {sym.data_type:<8}  "
                f"{sym.scope_level:<3}  {sym.scope_name:<20}  {sym.size_bytes:>3}  "
                f"{sym.offset:>4}  {sym.decl_line:>4}  {extra}"
            )
        return "\n".join(rows)

    def format_classes(self) -> str:
        """Resumo das classes: layout de campos e assinaturas de métodos."""
        if not self.classes:
            return ""
        rows: List[str] = []
        for cls in self.classes.values():
            rows.append(f"class {cls.name}  (tamanho do objeto: {cls.size_bytes} bytes)")
            for f in cls.fields.values():
                rows.append(f"    campo   {f.access:<7} {f.data_type:<8} {f.name:<14} offset={f.offset}")
            if cls.constructor is not None:
                c = cls.constructor
                rows.append(f"    constr. {c.access:<7} {cls.name}({', '.join(c.param_types)})")
            for m in cls.methods.values():
                rows.append(
                    f"    método  {m.access:<7} {m.return_type:<8} {m.name}({', '.join(m.param_types)})"
                )
        return "\n".join(rows)
