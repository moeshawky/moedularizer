# moedularizer/types.py
"""
Core data structures — no internal dependencies, leaf module.

Defines the fundamental types used throughout the moedularizer pipeline:
- Symbol: A named entity in Python source (class, function, constant, etc.)
- Dependency: An edge between symbols (calls, inherits, uses)
- Module: A generated output file
- Cluster: A group of symbols destined for the same module
- ModularizationResult: Pipeline output with modules, clusters, and diagnostics
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


class SymbolKind(Enum):
    """Classification of Python source symbols."""
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    CONSTANT = "constant"
    IMPORT = "import"
    MODULE_LEVEL_CODE = "module_level_code"  # imperative statements at module level


@dataclass(frozen=True)
class Symbol:
    """A named symbol in a Python module."""
    name: str
    kind: SymbolKind
    source: str           # full source text
    lineno: int           # start line (1-indexed)
    end_lineno: int       # end line (1-indexed, inclusive)
    docstring: Optional[str] = None
    decorators: Tuple[str, ...] = ()  # decorator source strings

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, Symbol) and self.name == other.name


class DependencyType(Enum):
    """Classification of dependency edges."""
    CALLS = "calls"
    INHERITS = "inherits"
    USES_CONSTANT = "uses_constant"
    TYPE_ANNOTATION = "type_annotation"
    IMPORTS = "imports"
    DECORATOR = "decorator"
    DEFAULT_ARG = "default_arg"


@dataclass
class Dependency:
    """An edge: source symbol depends on target symbol."""
    source: str           # symbol name that has the dependency
    target: str           # symbol name being depended upon
    dep_type: DependencyType
    line: int = 0


@dataclass
class Module:
    """A generated output module."""
    name: str             # e.g. "key_patterns"
    symbols: List[Symbol] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    imports_needed: List[str] = field(default_factory=list)  # ordered, not a set
    external_imports: List[str] = field(default_factory=list)  # stdlib/third-party
    is_init: bool = False
    all_exports: List[str] = field(default_factory=list)  # for __all__

    @property
    def symbol_names(self) -> Set[str]:
        return {s.name for s in self.symbols}


@dataclass
class Cluster:
    """A group of symbols that should live together."""
    name: str
    symbols: Set[str] = field(default_factory=set)
    internal_deps: List[Dependency] = field(default_factory=list)
    external_deps: List[Dependency] = field(default_factory=list)

    @property
    def is_self_contained(self) -> bool:
        return len(self.external_deps) == 0


@dataclass
class ModularizationResult:
    """Output of the full modularization pipeline."""
    modules: List[Module] = field(default_factory=list)
    clusters: List[Cluster] = field(default_factory=list)
    preserved_exports: Set[str] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)