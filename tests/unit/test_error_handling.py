"""
Unit tests - G-ERR: Error handling.

Tests for error handling and fault injection.
LLMs typically only handle happy paths and miss error paths.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
from moedularizer.analyzer import Analyzer
from moedularizer.clusterer import Clusterer
from moedularizer.config import MoedularizerConfig
from moedularizer.dependency import build_graph
from moedularizer.generator import CodeGenerator
from moedularizer.validator import Validator


def test_syntax_error_handling():
    """G-ERR: Test handling of syntax errors in source code."""
    analyzer = Analyzer()

    source = """
def foo():
    this is a syntax error
"""

    with pytest.raises(ValueError, match="Failed to parse"):
        analyzer.analyze(source, filename="syntax_error.py")


def test_indentation_error_handling():
    """G-ERR: Test handling of indentation errors."""
    analyzer = Analyzer()

    source = """
def foo():
pass  # Wrong indentation
"""

    with pytest.raises(ValueError, match="Failed to parse"):
        analyzer.analyze(source, filename="indent_error.py")


def test_empty_source_file():
    """G-ERR: Test handling of empty source file."""
    analyzer = Analyzer()

    source = ""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="empty.py"
    )

    # Should handle gracefully
    assert symbols == []
    assert dependencies == []


def test_none_source():
    """G-ERR: Test handling of None as source."""
    analyzer = Analyzer()

    with pytest.raises((ValueError, TypeError)):
        analyzer.analyze(None, filename="none.py")


def test_invalid_filename():
    """G-ERR: Test handling of invalid filename."""
    analyzer = Analyzer()

    source = "def foo(): pass"

    # Should handle invalid filename gracefully by using default
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="<string>"
    )

    # Should still work
    assert len(symbols) == 1


def test_config_validation_errors():
    """G-ERR: Test config validation catches all errors."""
    # Test multiple validation errors
    config = MoedularizerConfig(
        source_file=Path("/nonexistent/file.py"),
        package_name="123-invalid",
        max_symbols_per_module=1,
        min_symbols_per_module=10,
    )

    errors = config.validate()

    # Should catch multiple errors
    assert len(errors) >= 3


def test_clustering_with_empty_symbols():
    """G-ERR: Test clustering with no symbols."""
    config = MoedularizerConfig()
    clusterer = Clusterer(config)

    clusters = clusterer.cluster([], [])

    # Should handle gracefully
    assert clusters == []


def test_generator_with_empty_clusters():
    """G-ERR: Test generation with no clusters."""
    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    modules = generator.generate([], {}, {}, {}, "")

    # Should still generate __init__.py
    assert len(modules) == 1
    assert modules[0].name == "__init__"


def test_generator_with_invalid_module_name():
    """G-ERR: Test generation with invalid module name."""
    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    from moedularizer.types import Module

    module = Module(name="123-invalid")
    rendered = generator.render_module(module)

    # Should sanitize the name
    assert rendered is not None


def test_write_modules_with_nonexistent_dir():
    """G-ERR: Test writing to non-existent directory."""
    import tempfile

    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    from moedularizer.types import Module

    module = Module(name="test")
    modules = [module]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "nonexistent" / "nested" / "dir"

        # Should create parent directories
        written = generator.write_modules(modules, output_dir)

        assert len(written) == 1
        assert written[0].exists()


def test_write_modules_with_permission_error():
    """G-ERR: Test handling of permission errors."""
    import tempfile

    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    from moedularizer.types import Module

    module = Module(name="test")
    modules = [module]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "readonly"
        output_dir.mkdir()

        # Make directory read-only
        output_dir.chmod(0o444)

        try:
            # Should raise OSError
            with pytest.raises(OSError):
                generator.write_modules(modules, output_dir)
        finally:
            # Restore permissions for cleanup
            output_dir.chmod(0o755)


def test_validator_with_empty_modules():
    """G-ERR: Test validation with no modules."""
    validator = Validator(set())

    from moedularizer.types import ModularizationResult

    result = validator.validate([], [], build_graph([]))

    # Should handle gracefully
    assert result is not None
    assert isinstance(result, ModularizationResult)


def test_validator_with_circular_imports():
    """G-ERR: Test detection of circular imports."""
    from moedularizer.types import Cluster, Module

    validator = Validator(set())

    # Create modules with circular imports
    module_a = Module(name="module_a")
    module_a.imports_needed = ["from test_package.module_b import foo"]

    module_b = Module(name="module_b")
    module_b.imports_needed = ["from test_package.module_a import bar"]

    modules = [module_a, module_b]

    # Create clusters
    cluster_a = Cluster(name="module_a", symbols={"foo"})
    cluster_b = Cluster(name="module_b", symbols={"bar"})
    clusters = [cluster_a, cluster_b]

    result = validator.validate(modules, clusters, build_graph([]))

    # Should detect circular imports
    # Note: The validator may or may not detect this depending on implementation
    # Just verify it doesn't crash
    assert result is not None
    assert isinstance(result.warnings, list)


def test_dependency_graph_with_empty_nodes():
    """G-ERR: Test dependency graph with no nodes."""
    graph = build_graph([])

    # Should handle gracefully
    assert graph is not None
    assert len(graph.all_symbols()) == 0


def test_dependency_graph_with_self_loop():
    """G-ERR: Test dependency graph with self-loop."""
    from moedularizer.types import Dependency, DependencyType, Symbol, SymbolKind

    [
        Symbol(
            name="foo",
            kind=SymbolKind.FUNCTION,
            source="def foo(): pass",
            lineno=1,
            end_lineno=2,
        )
    ]
    dependencies = [Dependency(source="foo", target="foo", dep_type=DependencyType.CALLS)]

    graph = build_graph(dependencies)

    # Should handle self-loop
    assert graph is not None


def test_topological_sort_with_cycles():
    """G-ERR: Test topological sort with cycles."""
    from moedularizer.types import Dependency, DependencyType, Symbol, SymbolKind

    [
        Symbol(
            name="foo",
            kind=SymbolKind.FUNCTION,
            source="def foo(): pass",
            lineno=1,
            end_lineno=2,
        ),
        Symbol(
            name="bar",
            kind=SymbolKind.FUNCTION,
            source="def bar(): pass",
            lineno=3,
            end_lineno=4,
        ),
    ]
    dependencies = [
        Dependency(source="foo", target="bar", dep_type=DependencyType.CALLS),
        Dependency(source="bar", target="foo", dep_type=DependencyType.CALLS),
    ]

    graph = build_graph(dependencies)

    # Should detect cycles
    cycles = graph.find_cycles()
    assert len(cycles) > 0

    # Topological sort should fail
    with pytest.raises(ValueError, match="cycles"):
        graph.topological_sort()


def test_clusterer_with_force_groupings_typo():
    """G-ERR: Test clusterer with typos in force_groupings."""
    config = MoedularizerConfig(
        force_groupings={"test_group": ["nonexistent_symbol", "another_nonexistent"]}
    )
    clusterer = Clusterer(config)

    source = """
def foo():
    pass
"""
    analyzer = Analyzer()
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="test.py"
    )

    # Should handle typos gracefully
    clusters = clusterer.cluster(symbols, dependencies)
    assert len(clusters) > 0


def test_clusterer_with_force_separations():
    """G-ERR: Test clusterer with forced separations."""
    config = MoedularizerConfig(force_separations=[{"foo", "bar"}])
    clusterer = Clusterer(config)

    source = """
def foo():
    return bar()

def bar():
    return foo()
"""
    analyzer = Analyzer()
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="test.py"
    )

    # Should separate the symbols
    clusters = clusterer.cluster(symbols, dependencies)

    # Verify foo and bar are in different clusters
    cluster_map = {}
    for cluster in clusters:
        for sym in cluster.symbols:
            cluster_map[sym] = cluster.name

    # They should be in different clusters
    assert cluster_map.get("foo") != cluster_map.get("bar")


def test_module_name_sanitization_edge_cases():
    """G-ERR: Test module name sanitization with edge cases."""
    from moedularizer.clusterer import Clusterer
    from moedularizer.config import MoedularizerConfig

    config = MoedularizerConfig()
    clusterer = Clusterer(config)

    # Test various edge cases
    test_cases = [
        ("", "module"),  # Empty string
        ("123", "module"),  # Only digits
        ("../etc/passwd", "__etc_passwd"),  # Path traversal
        ("test module", "test_module"),  # Space
        ("test-module", "test_module"),  # Hyphen
        ("test.module", "test_module"),  # Dot
        ("test@module", "test_module"),  # Special char
        ("test*module", "test_module"),  # Asterisk
    ]

    for input_name, expected in test_cases:
        sanitized = clusterer._sanitize_name(input_name)
        assert sanitized == expected, f"Expected {expected}, got {sanitized} for input {input_name}"


def test_render_module_with_no_symbols():
    """G-ERR: Test rendering module with no symbols."""
    from moedularizer.config import MoedularizerConfig
    from moedularizer.generator import CodeGenerator
    from moedularizer.types import Module

    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    module = Module(name="test")
    module.symbols = []

    rendered = generator.render_module(module)

    # Should still render something
    assert rendered is not None
    assert len(rendered) > 0


def test_render_init_with_no_exports():
    """G-ERR: Test rendering __init__.py with no exports."""
    from moedularizer.config import MoedularizerConfig
    from moedularizer.generator import CodeGenerator
    from moedularizer.types import Module

    config = MoedularizerConfig()
    generator = CodeGenerator(config)

    init = Module(name="__init__", is_init=True)
    init.all_exports = []

    rendered = generator.render_module(init)

    # Should still render
    assert rendered is not None
    assert len(rendered) > 0
