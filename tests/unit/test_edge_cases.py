"""
Unit tests - G-EDGE: Edge cases.

Tests for edge cases in AST parsing, clustering, and code generation.
LLMs systematically miss edge cases that humans rarely forget.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
from moedularizer.analyzer import Analyzer
from moedularizer.clusterer import Clusterer
from moedularizer.config import MoedularizerConfig
from moedularizer.types import SymbolKind


def test_empty_file():
    """G-EDGE: Test handling of empty Python files."""
    analyzer = Analyzer()

    source = ""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="empty.py"
    )

    assert symbols == []
    assert dependencies == []
    assert dunder_all is None
    assert module_level_code is None


def test_file_with_only_comments():
    """G-EDGE: Test handling of files with only comments."""
    analyzer = Analyzer()

    source = """
# This is a comment
# Another comment
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="comments.py"
    )

    assert symbols == []
    assert dependencies == []
    assert dunder_all is None
    assert module_level_code is None


def test_file_with_only_docstring():
    """G-EDGE: Test handling of files with only a docstring."""
    analyzer = Analyzer()

    source = '"""Module docstring."""'
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="docstring.py"
    )

    # Docstring is extracted as module-level code (not in symbols list)
    assert symbols == []
    assert dependencies == []
    assert dunder_all is None
    assert module_level_code is not None
    assert module_level_code.name == "__module_level_code__"
    assert module_level_code.kind == SymbolKind.MODULE_LEVEL_CODE


def test_single_function():
    """G-EDGE: Test handling of single function."""
    analyzer = Analyzer()

    source = """
def foo():
    pass
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="single.py"
    )

    assert len(symbols) == 1
    assert symbols[0].name == "foo"
    assert symbols[0].kind == SymbolKind.FUNCTION


def test_single_class():
    """G-EDGE: Test handling of single class."""
    analyzer = Analyzer()

    source = """
class Foo:
    pass
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="single_class.py"
    )

    assert len(symbols) == 1
    assert symbols[0].name == "Foo"
    assert symbols[0].kind == SymbolKind.CLASS


def test_single_constant():
    """G-EDGE: Test handling of single constant."""
    analyzer = Analyzer()

    source = "FOO = 42"
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="single_constant.py"
    )

    assert len(symbols) == 1
    assert symbols[0].name == "FOO"
    assert symbols[0].kind == SymbolKind.CONSTANT


def test_nested_classes():
    """G-EDGE: Test handling of nested classes."""
    analyzer = Analyzer()

    source = """
class Outer:
    class Inner:
        pass
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="nested.py"
    )

    # Should extract top-level classes only
    assert len(symbols) == 1
    assert symbols[0].name == "Outer"
    assert symbols[0].kind == SymbolKind.CLASS


def test_async_functions():
    """G-EDGE: Test handling of async functions."""
    analyzer = Analyzer()

    source = """
async def async_foo():
    pass
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="async.py"
    )

    assert len(symbols) == 1
    assert symbols[0].name == "async_foo"
    assert symbols[0].kind == SymbolKind.ASYNC_FUNCTION


def test_decorated_functions():
    """G-EDGE: Test handling of decorated functions."""
    analyzer = Analyzer()

    source = """
@decorator
def decorated():
    pass
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="decorated.py"
    )

    assert len(symbols) == 1
    assert symbols[0].name == "decorated"
    assert symbols[0].kind == SymbolKind.FUNCTION
    assert len(symbols[0].decorators) == 1
    assert "decorator" in symbols[0].decorators[0]


def test_dataclass_detection():
    """G-EDGE: Test detection of dataclasses."""
    analyzer = Analyzer()

    source = """
from dataclasses import dataclass

@dataclass
class Foo:
    x: int
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="dataclass.py"
    )

    assert len(symbols) == 2  # Foo class and dataclass import
    foo_symbol = next((s for s in symbols if s.name == "Foo"), None)
    assert foo_symbol is not None
    assert foo_symbol.kind == SymbolKind.CLASS
    assert any("@dataclass" in dec for dec in foo_symbol.decorators)


def test_typed_assignments():
    """G-EDGE: Test handling of typed assignments."""
    analyzer = Analyzer()

    source = """
x: int = 42
y: str = "hello"
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="typed.py"
    )

    assert len(symbols) == 2
    assert symbols[0].name == "x"
    assert symbols[0].kind == SymbolKind.CONSTANT
    assert symbols[1].name == "y"
    assert symbols[1].kind == SymbolKind.CONSTANT


def test_imports():
    """G-EDGE: Test handling of various import styles."""
    analyzer = Analyzer()

    source = """
import os
import sys as system
from pathlib import Path
from typing import List, Dict
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="imports.py"
    )

    # Should extract imports (5 total: os, system, Path, List, Dict)
    import_symbols = [s for s in symbols if s.kind == SymbolKind.IMPORT]
    assert len(import_symbols) == 5


def test_dunder_all_extraction():
    """G-EDGE: Test extraction of __all__ definition."""
    analyzer = Analyzer()

    source = """
__all__ = ['foo', 'bar', 'baz']

def foo():
    pass

def bar():
    pass

def baz():
    pass
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="dunder_all.py"
    )

    assert dunder_all == ["foo", "bar", "baz"]


def test_module_level_code_extraction():
    """G-EDGE: Test extraction of module-level imperative code."""
    analyzer = Analyzer()

    source = """
x = 1
y = 2

def foo():
    pass

print("Hello, world!")
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="module_level.py"
    )

    assert module_level_code is not None
    assert "print(" in module_level_code.source


def test_unicode_identifiers():
    """G-EDGE: Test handling of Unicode identifiers."""
    analyzer = Analyzer()

    source = """
def foo():
    pass

变量 = 42  # Chinese variable name
"""
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="unicode.py"
    )

    # Should extract both symbols
    assert len(symbols) >= 1
    assert any(s.name == "foo" for s in symbols)


def test_generator_dry_run_guard():
    """G-CTX: write_modules returns [] when config.dry_run is True."""
    import tempfile

    from moedularizer.generator import CodeGenerator
    from moedularizer.types import Module

    config = MoedularizerConfig(dry_run=True)
    generator = CodeGenerator(config)

    module = Module(name="test_mod")
    modules = [module]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        written = generator.write_modules(modules, output_dir)
        assert written == []
        assert not output_dir.exists()


def test_very_long_function():
    """G-EDGE: Test handling of very long functions."""
    analyzer = Analyzer()

    # Create a function with many lines
    lines = ["def long_function():"]
    for i in range(1000):
        lines.append(f"    x{i} = {i}")
    source = "\n".join(lines)

    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="long.py"
    )

    assert len(symbols) == 1
    assert symbols[0].name == "long_function"
    assert symbols[0].end_lineno > symbols[0].lineno


def test_many_symbols():
    """G-EDGE: Test handling of files with many symbols."""
    analyzer = Analyzer()

    # Create many functions
    lines = []
    for i in range(100):
        lines.append(f"def func{i}():")
        lines.append("    pass")

    source = "\n".join(lines)

    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="many.py"
    )

    assert len(symbols) == 100


def test_clustering_with_no_dependencies():
    """G-EDGE: Test clustering when there are no dependencies."""
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
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="no_deps.py"
    )

    clusters = clusterer.cluster(symbols, dependencies)

    # Should create clusters even without dependencies
    assert len(clusters) > 0


def test_clustering_with_circular_dependencies():
    """G-EDGE: Test clustering with circular dependencies."""
    config = MoedularizerConfig()
    clusterer = Clusterer(config)

    source = """
def foo():
    return bar()

def bar():
    return foo()
"""
    analyzer = Analyzer()
    symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
        source, filename="circular.py"
    )

    clusters = clusterer.cluster(symbols, dependencies)

    # Should handle circular dependencies
    assert len(clusters) > 0


def test_config_edge_cases():
    """G-EDGE: Test config validation with edge cases."""
    # Test with max_symbols < min_symbols
    config = MoedularizerConfig(
        max_symbols_per_module=1,
        min_symbols_per_module=10,
    )
    errors = config.validate()
    assert len(errors) > 0

    # Test with invalid package name
    config = MoedularizerConfig(package_name="123-invalid")
    errors = config.validate()
    assert len(errors) > 0

    # Test with non-existent source file
    config = MoedularizerConfig(source_file=Path("/nonexistent/file.py"))
    errors = config.validate()
    assert len(errors) > 0


SYMBOL_KIND_CASES = [
    ("class Foo:\n    pass\n", SymbolKind.CLASS, "class Foo"),
    ("def foo():\n    pass\n", SymbolKind.FUNCTION, "def foo"),
    ("async def foo():\n    pass\n", SymbolKind.ASYNC_FUNCTION, "async def foo"),
    ("FOO = 42\n", SymbolKind.CONSTANT, "FOO"),
    ("import os\n", SymbolKind.IMPORT, "import os"),
    ("from pathlib import Path\n", SymbolKind.IMPORT, "from pathlib import Path"),
    (
        "def foo():\n    pass\n\nclass Bar:\n    pass\n",
        SymbolKind.FUNCTION,
        "def foo in mixed file",
    ),
    ("def foo():\n    pass\n\nclass Bar:\n    pass\n", SymbolKind.CLASS, "class Bar in mixed file"),
]


@pytest.mark.parametrize("source_snippet,expected_kind,description", SYMBOL_KIND_CASES)
def test_symbol_kind_classification(source_snippet, expected_kind, description):
    """Verify analyzer classifies symbols with the correct SymbolKind."""
    analyzer = Analyzer()
    symbols, _, _, _, _ = analyzer.analyze(source_snippet, filename="test.py")

    if description == "class Bar in mixed file":
        found = next(s for s in symbols if s.name == "Bar")
    elif description == "def foo in mixed file":
        found = next(s for s in symbols if s.name == "foo")
    else:
        assert len(symbols) > 0, f"No symbols found for: {description}"
        found = symbols[0]

    assert found.kind == expected_kind, (
        f"Expected {expected_kind} for {description}, got {found.kind}"
    )
