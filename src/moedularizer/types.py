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
from typing import List, Optional, Set, Tuple


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

    # `name` and `kind` lack inline comments but are self-explanatory from
    # the class docstring. `docstring: Optional[str] = None` lacks a comment
    # — None means "no docstring found," standard Python convention.
    # Remaining four fields (source, lineno, end_lineno, decorators) each
    # carry inline comments describing non-obvious content invariants: source
    # includes line breaks, lineno/end_lineno are 1-indexed (end_lineno
    # defaults to lineno), decorators are raw source strings not resolved names.
    name: str
    kind: SymbolKind
    source: str  # full source text including line breaks
    lineno: int  # start line (1-indexed)
    end_lineno: int  # end line (1-indexed, inclusive; defaults to lineno if unknown)
    docstring: Optional[str] = None
    decorators: Tuple[str, ...] = ()  # raw decorator source strings (not resolved names)

    # Hash/eq on name only — intentional for the clustering pipeline where
    # cluster.symbols is Set[str]. set(symbols) loses distinct symbols with
    # name collisions, but names are unique within a module.
    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
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

    source: str  # symbol name that has the dependency
    target: str  # symbol name being depended upon
    dep_type: DependencyType
    line: int = 0


@dataclass
class Module:
    """A generated output module."""

    name: str  # e.g. "key_patterns"
    symbols: List[Symbol] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    imports_needed: List[str] = field(
        default_factory=list
    )  # Field comment: 'sorted for determinism; not insertion-ordered'. The
    # comment lives on the dataclass field declaration, but the stored value
    # is NOT sorted — generator.py:91 deduplicates via `list(set(...))`
    # which produces hash-ordered output, not sorted output. The determinism
    # is only achieved downstream at generator.py:242 where
    # `sorted(module.imports_needed)` applies alphabetical order just before
    # writing. The field's actual invariant is "List (for downstream sorting),
    # not Set (to allow duplicates during accumulation that are deduplicated
    # later)."
    external_imports: List[Tuple[str, List[str]]] = field(
        default_factory=list
    )  # (module_path, [names])
    is_init: bool = False
    all_exports: Optional[List[str]] = None  # for __all__, set after module creation

    @property
    def symbol_names(self) -> Set[str]:
        """Computed property extracting {s.name for s in self.symbols}.
        Returns Set[str] of symbol names, not full Symbol objects.
        Downstream code uses this for membership checks without needing
        to construct or reference Symbol instances."""
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
        """Returns True when the cluster has no dependencies crossing its
        boundary: len(self.external_deps) == 0. A self-contained cluster
        can be extracted into a separate module without creating
        cross-module import lines."""
        return len(self.external_deps) == 0


@dataclass
class ModularizationResult:
    """Output of the full modularization pipeline."""

    modules: List[Module] = field(default_factory=list)
    clusters: List[Cluster] = field(default_factory=list)
    preserved_exports: Set[str] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
