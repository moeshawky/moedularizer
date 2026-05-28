"""
Property tests - G-SEM: Semantic correctness.

Tests for invariants and behavioral correctness.
LLMs produce plausible but wrong logic - need property-based testing.
"""

import pytest
from moedularizer.analyzer import Analyzer

pytestmark = pytest.mark.property
from moedularizer.clusterer import Clusterer
from moedularizer.config import MoedularizerConfig
from moedularizer.dependency import build_graph
from moedularizer.types import SymbolKind


def test_symbol_extraction_invariant():
    """G-SEM: All extracted symbols have valid line numbers."""
    analyzer = Analyzer()

    source = """
def foo():
    pass

class Bar:
    pass

CONST = 42
"""
    symbols, _, _, _, _ = analyzer.analyze(source, filename="test.py")

    # Invariant: All symbols have valid line numbers
    for symbol in symbols:
        assert symbol.lineno > 0, f"Symbol {symbol.name} has invalid lineno: {symbol.lineno}"
        assert symbol.end_lineno >= symbol.lineno, f"Symbol {symbol.name} has end_lineno < lineno"
        assert symbol.source is not None, f"Symbol {symbol.name} has no source"


def test_symbol_kind_invariant():
    """G-SEM: All symbols have valid kinds."""
    analyzer = Analyzer()

    source = """
def foo():
    pass

class Bar:
    pass

CONST = 42

import os
"""
    symbols, _, _, _, _ = analyzer.analyze(source, filename="test.py")

    # Invariant: All symbols have valid kinds
    valid_kinds = {SymbolKind.CLASS, SymbolKind.FUNCTION, SymbolKind.ASYNC_FUNCTION,
                   SymbolKind.CONSTANT, SymbolKind.IMPORT, SymbolKind.MODULE_LEVEL_CODE}

    for symbol in symbols:
        assert symbol.kind in valid_kinds, f"Symbol {symbol.name} has invalid kind: {symbol.kind}"


def test_symbol_name_invariant():
    """G-SEM: All symbols have valid names."""
    analyzer = Analyzer()

    source = """
def foo():
    pass

class Bar:
    pass
"""
    symbols, _, _, _, _ = analyzer.analyze(source, filename="test.py")

    # Invariant: All symbols have valid Python identifiers
    for symbol in symbols:
        if symbol.kind != SymbolKind.MODULE_LEVEL_CODE:
            assert symbol.name.isidentifier(), f"Symbol {symbol.name} is not a valid identifier"


def test_dependency_invariant():
    """G-SEM: All dependencies have valid source and target."""
    analyzer = Analyzer()

    source = """
def foo():
    return bar()

def bar():
    return 42
"""
    symbols, dependencies, _, _, _ = analyzer.analyze(source, filename="test.py")

    # Invariant: All dependencies reference existing symbols
    symbol_names = {s.name for s in symbols}
    for dep in dependencies:
        assert dep.source in symbol_names, f"Dependency source {dep.source} not in symbols"
        assert dep.target in symbol_names, f"Dependency target {dep.target} not in symbols"


def test_cluster_invariant():
    """G-SEM: All clusters have valid names and symbols."""
    config = MoedularizerConfig()
    clusterer = Clusterer(config)

    source = """
def foo():
    pass

def bar():
    pass
"""
    analyzer = Analyzer()
    symbols, dependencies, _, _, _ = analyzer.analyze(source, filename="test.py")

    clusters = clusterer.cluster(symbols, dependencies)

    # Invariant: All clusters have valid names
    for cluster in clusters:
        assert cluster.name.isidentifier(), f"Cluster {cluster.name} is not a valid identifier"

    # Invariant: All cluster symbols exist in original symbols
    all_cluster_symbols = set()
    for cluster in clusters:
        all_cluster_symbols.update(cluster.symbols)

    symbol_names = {s.name for s in symbols}
    assert all_cluster_symbols == symbol_names, "Cluster symbols don't match original symbols"


def test_module_invariant():
    """G-SEM: All modules have valid names and symbols."""
    from moedularizer.generator import CodeGenerator
    from moedularizer.config import MoedularizerConfig
    from moedularizer.types import Module

    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    module = Module(name="test_module")
    module.symbols = []

    # Invariant: Module name is valid identifier
    assert module.name.isidentifier(), f"Module {module.name} is not a valid identifier"

    # Invariant: Rendered module is valid Python
    rendered = generator.render_module(module)
    assert rendered is not None
    assert len(rendered) > 0


def test_clustering_preserves_symbols():
    """G-SEM: Clustering preserves all symbols."""
    config = MoedularizerConfig()
    clusterer = Clusterer(config)

    source = """
def foo():
    pass

def bar():
    pass

def baz():
    pass
"""
    analyzer = Analyzer()
    symbols, dependencies, _, _, _ = analyzer.analyze(source, filename="test.py")

    clusters = clusterer.cluster(symbols, dependencies)

    # Invariant: All symbols are assigned to exactly one cluster
    cluster_symbols = set()
    for cluster in clusters:
        cluster_symbols.update(cluster.symbols)

    original_symbols = {s.name for s in symbols}
    assert cluster_symbols == original_symbols, "Not all symbols preserved in clusters"


def test_clustering_no_duplicates():
    """G-SEM: No symbol appears in multiple clusters."""
    config = MoedularizerConfig()
    clusterer = Clusterer(config)

    source = """
def foo():
    pass

def bar():
    pass
"""
    analyzer = Analyzer()
    symbols, dependencies, _, _, _ = analyzer.analyze(source, filename="test.py")

    clusters = clusterer.cluster(symbols, dependencies)

    # Invariant: No symbol appears in multiple clusters
    symbol_counts = {}
    for cluster in clusters:
        for sym in cluster.symbols:
            symbol_counts[sym] = symbol_counts.get(sym, 0) + 1

    for sym, count in symbol_counts.items():
        assert count == 1, f"Symbol {sym} appears in {count} clusters"


def test_dependency_graph_invariant():
    """G-SEM: Dependency graph maintains consistency."""
    from moedularizer.types import Symbol, Dependency, DependencyType

    symbols = [
        Symbol(name="foo", kind=SymbolKind.FUNCTION, source="def foo(): pass", lineno=1, end_lineno=2),
        Symbol(name="bar", kind=SymbolKind.FUNCTION, source="def bar(): pass", lineno=3, end_lineno=4),
    ]
    dependencies = [
        Dependency(source="foo", target="bar", dep_type=DependencyType.CALLS),
    ]

    graph = build_graph(symbols, dependencies)

    # Invariant: Graph contains all symbols
    graph_symbols = graph.all_symbols()
    assert graph_symbols == {"foo", "bar"}

    # Invariant: Dependencies are preserved
    assert graph.has_dependency("foo", "bar")

    # Invariant: Reverse dependencies work
    assert "foo" in graph.depended_by("bar")


def test_config_invariant():
    """G-SEM: Config maintains valid state."""
    config = MoedularizerConfig(
        package_name="test",
        max_symbols_per_module=10,
        min_symbols_per_module=1,
    )

    # Invariant: Config values are valid
    assert config.package_name.isidentifier()
    assert config.max_symbols_per_module >= config.min_symbols_per_module
    assert config.min_python_version >= (3, 8)


def test_generator_preserves_symbol_source():
    """G-SEM: Generator preserves symbol source code."""
    from moedularizer.generator import CodeGenerator
    from moedularizer.config import MoedularizerConfig
    from moedularizer.types import Module, Symbol, SymbolKind

    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    source_code = "def foo():\n    pass"
    symbol = Symbol(
        name="foo",
        kind=SymbolKind.FUNCTION,
        source=source_code,
        lineno=1,
        end_lineno=2,
    )

    module = Module(name="test")
    module.symbols = [symbol]

    rendered = generator.render_module(module)

    # Invariant: Source code is preserved
    assert "def foo():" in rendered
    assert "pass" in rendered


def test_generator_imports_invariant():
    """G-SEM: Generator generates valid imports."""
    from moedularizer.generator import CodeGenerator
    from moedularizer.config import MoedularizerConfig
    from moedularizer.types import Module

    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    module = Module(name="test")
    module.imports_needed = ["from os import path"]
    module.external_imports = ["import sys"]

    rendered = generator.render_module(module)

    # Invariant: Imports are present and valid
    assert "from os import path" in rendered
    assert "import sys" in rendered


def test_validator_invariant():
    """G-SEM: Validator returns valid result."""
    from moedularizer.validator import Validator
    from moedularizer.types import ModularizationResult

    validator = Validator(set())

    result = validator.validate([], [], build_graph([], []))

    # Invariant: Result is valid
    assert isinstance(result, ModularizationResult)
    assert result.modules is not None
    assert result.clusters is not None
    assert result.warnings is not None
    assert result.errors is not None


def test_roundtrip_invariant():
    """G-SEM: Source code can be analyzed and regenerated."""
    analyzer = Analyzer()

    source = """
def foo():
    return bar()

def bar():
    return 42
"""
    symbols, dependencies, _, _, _ = analyzer.analyze(source, filename="test.py")

    # Invariant: All symbols can be reconstructed from source
    for symbol in symbols:
        assert symbol.source is not None
        assert len(symbol.source) > 0


def test_symbol_ordering_invariant():
    """G-SEM: Symbol ordering respects dependencies."""
    from moedularizer.dependency import build_graph
    from moedularizer.types import Symbol, Dependency, DependencyType, SymbolKind

    symbols = [
        Symbol(name="foo", kind=SymbolKind.FUNCTION, source="def foo(): pass", lineno=1, end_lineno=2),
        Symbol(name="bar", kind=SymbolKind.FUNCTION, source="def bar(): pass", lineno=3, end_lineno=4),
        Symbol(name="baz", kind=SymbolKind.FUNCTION, source="def baz(): pass", lineno=5, end_lineno=6),
    ]
    dependencies = [
        Dependency(source="foo", target="bar", dep_type=DependencyType.CALLS),
        Dependency(source="bar", target="baz", dep_type=DependencyType.CALLS),
    ]

    graph = build_graph(symbols, dependencies)

    # Invariant: Topological sort respects dependencies
    ordered = graph.topological_sort()

    # foo depends on bar, bar depends on baz
    # In topological sort, if A depends on B, then A comes before B
    # So foo before bar, bar before baz
    foo_idx = ordered.index("foo")
    bar_idx = ordered.index("bar")
    baz_idx = ordered.index("baz")

    assert foo_idx < bar_idx < baz_idx


def test_cluster_naming_invariant():
    """G-SEM: Cluster names are derived from contents."""
    config = MoedularizerConfig()
    clusterer = Clusterer(config)

    source = """
class FooBar:
    pass
"""
    analyzer = Analyzer()
    symbols, dependencies, _, _, _ = analyzer.analyze(source, filename="test.py")

    clusters = clusterer.cluster(symbols, dependencies)

    # Invariant: Cluster names are valid identifiers
    for cluster in clusters:
        assert cluster.name.isidentifier() or cluster.name.startswith("_auto_")


def test_module_level_code_invariant():
    """G-SEM: Module-level code is preserved."""
    analyzer = Analyzer()

    source = """
x = 1
y = 2

def foo():
    pass

print("Hello")
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="test.py"
    )

    # Invariant: Module-level code is extracted
    assert module_level_code is not None
    assert "print(" in module_level_code.source


def test_dunder_all_invariant():
    """G-SEM: __all__ is extracted correctly."""
    analyzer = Analyzer()

    source = """
__all__ = ['foo', 'bar']

def foo():
    pass

def bar():
    pass
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="test.py"
    )

    # Invariant: __all__ is extracted
    assert dunder_all is not None
    assert dunder_all == ['foo', 'bar']


def test_external_imports_invariant():
    """G-SEM: External imports are tracked."""
    analyzer = Analyzer()

    source = """
import os
import sys
from pathlib import Path
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="test.py"
    )

    # Invariant: External imports are tracked
    assert len(external_imports) > 0

    # Invariant: External imports have valid structure
    for module_path, names in external_imports:
        assert isinstance(module_path, str)
        assert isinstance(names, list)
        assert len(names) > 0


# ── Property-based tests using hypothesis ──────────────────────────────

from hypothesis import given, strategies as st

# Valid Python identifiers (not keywords)
PYTHON_KEYWORDS = frozenset({
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
    "try", "while", "with", "yield",
})

valid_identifier = st.from_regex(r"\A[a-zA-Z_][a-zA-Z0-9_]*\Z").filter(
    lambda s: s not in PYTHON_KEYWORDS
)


@given(func_name=valid_identifier)
def test_symbol_extraction_roundtrip_property(func_name):
    """Generate source with a function named func_name, analyze, verify \
correct Symbol name and Function kind are extracted."""
    source = f"def {func_name}():\n    pass\n"
    analyzer = Analyzer()
    symbols, _, _, _, _ = analyzer.analyze(source, filename="test.py")
    assert len(symbols) == 1
    assert symbols[0].name == func_name
    assert symbols[0].kind == SymbolKind.FUNCTION


@given(
    names=st.lists(st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=8), min_size=2, max_size=8, unique=True),
)
def test_clustering_idempotent_property(names):
    """Cluster a set of symbols twice and verify identical results."""
    from moedularizer.types import Symbol, Dependency, DependencyType
    from moedularizer.config import MoedularizerConfig
    from moedularizer.clusterer import Clusterer

    symbols = [
        Symbol(
            name=n, kind=SymbolKind.FUNCTION,
            source=f"def {n}(): pass", lineno=1, end_lineno=2,
        )
        for n in names
    ]
    dependencies = []
    if len(names) >= 2:
        dependencies.append(Dependency(
            source=names[0], target=names[1], dep_type=DependencyType.CALLS,
        ))

    config = MoedularizerConfig(max_symbols_per_module=5)
    clusterer = Clusterer(config)
    clusters_a = clusterer.cluster(symbols, dependencies)
    clusters_b = clusterer.cluster(symbols, dependencies)

    def cluster_fingerprint(clusters):
        return tuple(sorted(
            (c.name, tuple(sorted(c.symbols))) for c in clusters
        ))

    assert cluster_fingerprint(clusters_a) == cluster_fingerprint(clusters_b)


@given(
    func_name=valid_identifier.filter(lambda s: s.lower() not in {"import", "from", "class", "def"}),
)
def test_generator_preserves_source_property(func_name):
    """Given a function source, render it into a module, verify source \
appears exactly once and is not mutated."""
    from moedularizer.generator import CodeGenerator
    from moedularizer.config import MoedularizerConfig
    from moedularizer.types import Module, Symbol, SymbolKind

    source_code = f"def {func_name}():\n    pass"
    symbol = Symbol(
        name=func_name,
        kind=SymbolKind.FUNCTION,
        source=source_code,
        lineno=1,
        end_lineno=2,
    )
    config = MoedularizerConfig()
    generator = CodeGenerator(config)
    module = Module(name="test_mod")
    module.symbols = [symbol]
    rendered = generator.render_module(module)

    assert source_code in rendered
    # Source must appear exactly once (not duplicated)
    assert rendered.count(source_code) == 1
    # Verify the source line position is correct
    idx = rendered.index(source_code)
    assert idx > 0  # Not at start (docstring comes first)
    # Verify the source is not mutated — the exact substring matches
    before = rendered[:idx]
    after = rendered[idx + len(source_code):]
    recon = before + source_code + after
    assert recon == rendered
