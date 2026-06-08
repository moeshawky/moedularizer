"""
Regression tests - G-DRIFT: Model version drift.

Tests for regression against golden files.
LLM output drifts over time - need golden file comparison.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
from moedularizer.analyzer import Analyzer
from moedularizer.clusterer import Clusterer
from moedularizer.config import MoedularizerConfig
from moedularizer.dependency import build_graph
from moedularizer.generator import CodeGenerator


def load_golden_file(name: str) -> str:
    """Load a golden file from the regression/golden directory."""
    golden_dir = Path(__file__).parent / "golden"
    golden_file = golden_dir / name
    return golden_file.read_text()


def normalize_output(text: str) -> str:
    """Normalize output for comparison (remove whitespace variations)."""
    # Remove trailing whitespace
    lines = [line.rstrip() for line in text.splitlines()]
    # Remove empty lines at end
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def test_golden_simple_function():
    """G-DRIFT: Test against golden file for simple function."""
    analyzer = Analyzer()

    source = """
def foo():
    return 42
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="simple.py"
    )

    # Get golden output
    golden = load_golden_file("simple_function.txt")

    # Normalize and compare
    actual = f"Symbols: {len(symbols)}\n"
    for sym in symbols:
        actual += f"  {sym.name}: {sym.kind.value}\n"

    actual = normalize_output(actual)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )


def test_golden_class_with_methods():
    """G-DRIFT: Test against golden file for class with methods."""
    analyzer = Analyzer()

    source = """
class Foo:
    def bar(self):
        pass

    def baz(self):
        return 42
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="class.py"
    )

    # Get golden output
    golden = load_golden_file("class_with_methods.txt")

    # Normalize and compare
    actual = f"Symbols: {len(symbols)}\n"
    for sym in symbols:
        actual += f"  {sym.name}: {sym.kind.value}\n"

    actual = normalize_output(actual)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )


def test_golden_dependencies():
    """G-DRIFT: Test against golden file for dependencies."""
    analyzer = Analyzer()

    source = """
def foo():
    return bar()

def bar():
    return baz()

def baz():
    return 42
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="deps.py"
    )

    # Get golden output
    golden = load_golden_file("dependencies.txt")

    # Normalize and compare
    actual = f"Dependencies: {len(dependencies)}\n"
    for dep in dependencies:
        actual += f"  {dep.source} -> {dep.target} ({dep.dep_type.value})\n"

    actual = normalize_output(actual)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )


def test_golden_clustering():
    """G-DRIFT: Test against golden file for clustering."""
    config = MoedularizerConfig(
        max_symbols_per_module=2,
    )
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
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="cluster.py"
    )

    clusters = clusterer.cluster(symbols, dependencies)

    # Get golden output
    golden = load_golden_file("clustering.txt")

    # Normalize and compare
    actual = f"Clusters: {len(clusters)}\n"
    for cluster in clusters:
        actual += f"  {cluster.name}: {sorted(cluster.symbols)}\n"

    actual = normalize_output(actual)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )


def test_golden_module_generation():
    """G-DRIFT: Test against golden file for module generation."""
    config = MoedularizerConfig(
        package_name="test_package",
    )
    generator = CodeGenerator(config)

    from moedularizer.types import Module, Symbol, SymbolKind

    module = Module(name="test_module")
    module.symbols = [
        Symbol(
            name="foo",
            kind=SymbolKind.FUNCTION,
            source="def foo():\n    pass",
            lineno=1,
            end_lineno=2,
        ),
    ]

    rendered = generator.render_module(module)

    # Get golden output
    golden = load_golden_file("module_generation.txt")

    # Normalize and compare
    actual = normalize_output(rendered)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )


def test_golden_init_generation():
    """G-DRIFT: Test against golden file for __init__.py generation."""
    config = MoedularizerConfig(
        package_name="test_package",
    )
    generator = CodeGenerator(config)

    from moedularizer.types import Module

    init = Module(name="__init__", is_init=True)
    init.imports_needed = ["from test_package.foo import foo", "from test_package.bar import bar"]
    init.all_exports = ["foo", "bar"]

    rendered = generator.render_module(init)

    # Get golden output
    golden = load_golden_file("init_generation.txt")

    # Normalize and compare
    actual = normalize_output(rendered)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )


def test_golden_full_pipeline():
    """G-DRIFT: Test against golden file for full pipeline."""
    config = MoedularizerConfig(
        package_name="test_package",
        max_symbols_per_module=2,
    )

    source = """
def foo():
    return bar()

def bar():
    return 42

class Baz:
    pass
"""
    analyzer = Analyzer()
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="full.py"
    )

    clusterer = Clusterer(config)
    clusters = clusterer.cluster(symbols, dependencies)

    generator = CodeGenerator(config)
    graph = build_graph(dependencies)

    symbol_map = {s.name: s for s in symbols}
    cluster_map = {}
    for cluster in clusters:
        for sym in cluster.symbols:
            cluster_map[sym] = cluster.name

    external_imports_dict = {}
    for module_path, names in external_imports:
        if module_path not in external_imports_dict:
            external_imports_dict[module_path] = []
        for name in names:
            if name not in external_imports_dict[module_path]:
                external_imports_dict[module_path].append(name)

    modules = generator.generate(
        clusters,
        symbol_map,
        cluster_map,
        external_imports_dict,
        source,
        dunder_all=dunder_all,
        graph=graph,
    )

    # Get golden output
    golden = load_golden_file("full_pipeline.txt")

    # Normalize and compare
    actual = f"Modules: {len(modules)}\n"
    for module in modules:
        actual += f"  {module.name}: {len(module.symbols)} symbols\n"

    actual = normalize_output(actual)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )


def test_golden_config_defaults():
    """G-DRIFT: Test against golden file for config defaults."""
    config = MoedularizerConfig()

    # Get golden output
    golden = load_golden_file("config_defaults.txt")

    # Normalize and compare
    actual = f"package_name: {config.package_name}\n"
    actual += f"max_symbols_per_module: {config.max_symbols_per_module}\n"
    actual += f"min_symbols_per_module: {config.min_symbols_per_module}\n"
    actual += f"use_absolute_imports: {config.use_absolute_imports}\n"
    actual += f"dry_run: {config.dry_run}\n"

    actual = normalize_output(actual)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )


def test_golden_dependency_graph():
    """G-DRIFT: Test against golden file for dependency graph."""
    from moedularizer.types import Dependency, DependencyType, Symbol, SymbolKind

    [
        Symbol(
            name="foo", kind=SymbolKind.FUNCTION, source="def foo(): pass", lineno=1, end_lineno=2
        ),
        Symbol(
            name="bar", kind=SymbolKind.FUNCTION, source="def bar(): pass", lineno=3, end_lineno=4
        ),
    ]
    dependencies = [
        Dependency(source="foo", target="bar", dep_type=DependencyType.CALLS),
    ]

    graph = build_graph(dependencies)

    # Get golden output
    golden = load_golden_file("dependency_graph.txt")

    # Read dependencies from graph object, not the input list
    graph_deps = []
    for sym in sorted(graph.all_symbols()):
        for target in sorted(graph.depends_on(sym)):
            graph_deps.append((sym, target))

    # Normalize and compare
    actual = f"Symbols: {sorted(graph.all_symbols())}\n"
    actual += f"Dependencies: {graph_deps}\n"

    actual = normalize_output(actual)
    golden = normalize_output(golden)

    assert actual == golden, (
        f"Output drifted from golden file.\nExpected:\n{golden}\n\nActual:\n{actual}"
    )
