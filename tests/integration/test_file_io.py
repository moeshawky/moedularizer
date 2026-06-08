"""
Integration tests - G-CTX: Context dependencies.

Tests for file I/O, state management, and integration with the environment.
LLMs typically work in isolation but fail when integrated.
"""

import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
from moedularizer import Moedularizer, MoedularizerConfig
from moedularizer.analyzer import Analyzer
from moedularizer.clusterer import Clusterer
from moedularizer.dependency import build_graph
from moedularizer.generator import CodeGenerator
from moedularizer.validator import Validator


def test_full_pipeline_integration():
    """G-CTX: Test the full modularization pipeline end-to-end."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create source file
        source_file = Path(tmpdir) / "monolith.py"
        source_file.write_text("""
def foo():
    return bar()

def bar():
    return 42

class Baz:
    pass

CONSTANT = "hello"
""")

        # Create output directory
        output_dir = Path(tmpdir) / "output"

        # Configure
        config = MoedularizerConfig(
            source_file=source_file,
            output_dir=output_dir,
            package_name="test_package",
        )

        # Run full pipeline
        Moedularizer(config)
        source = source_file.read_text()

        # Analyze
        analyzer = Analyzer()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(source_file)
        )

        # Cluster
        clusterer = Clusterer(config)
        clusters = clusterer.cluster(symbols, dependencies)

        # Generate
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

        # Write
        written = generator.write_modules(modules, output_dir)

        # Verify files were written
        assert len(written) > 0
        for path in written:
            assert path.exists()

        # Verify __init__.py exists
        init_file = output_dir / "__init__.py"
        assert init_file.exists()

        # Verify __init__.py has content
        init_content = init_file.read_text()
        assert len(init_content) > 0


def test_file_io_with_large_file():
    """G-CTX: Test file I/O with large source file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create large source file
        source_file = Path(tmpdir) / "large.py"
        lines = ["# Large file\n"]
        for i in range(1000):
            lines.append(f"def func{i}():\n")
            lines.append("    pass\n")
        source_file.write_text("".join(lines))

        output_dir = Path(tmpdir) / "output"

        MoedularizerConfig(
            source_file=source_file,
            output_dir=output_dir,
            package_name="large_package",
        )

        # Analyze
        analyzer = Analyzer()
        source = source_file.read_text()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(source_file)
        )

        # Should handle large file
        assert len(symbols) == 1000


def test_file_io_with_unicode():
    """G-CTX: Test file I/O with Unicode content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create source file with Unicode
        source_file = Path(tmpdir) / "unicode.py"
        source_file.write_text("""
# Unicode test
def foo():
    # Chinese comment: 你好世界
    return "Hello 世界"

变量 = 42  # Chinese variable
""")

        output_dir = Path(tmpdir) / "output"

        MoedularizerConfig(
            source_file=source_file,
            output_dir=output_dir,
            package_name="unicode_package",
        )

        # Analyze
        analyzer = Analyzer()
        source = source_file.read_text()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(source_file)
        )

        # Should handle Unicode
        assert len(symbols) >= 1


def test_file_io_with_special_characters():
    """G-CTX: Test file I/O with special characters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create source file with special characters
        source_file = Path(tmpdir) / "special.py"
        source_file.write_text("""
def foo():
    # Special chars: @#$%^&*()
    return "test\\n\\t\\r"
""")

        output_dir = Path(tmpdir) / "output"

        MoedularizerConfig(
            source_file=source_file,
            output_dir=output_dir,
            package_name="special_package",
        )

        # Analyze
        analyzer = Analyzer()
        source = source_file.read_text()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(source_file)
        )

        # Should handle special characters
        assert len(symbols) >= 1


def test_state_management_with_config():
    """G-CTX: Test state management across pipeline stages."""
    config = MoedularizerConfig(
        package_name="test",
        max_symbols_per_module=5,
        min_symbols_per_module=1,
    )

    # Verify config state is preserved
    assert config.package_name == "test"
    assert config.max_symbols_per_module == 5
    assert config.min_symbols_per_module == 1


def test_backup_existing_files():
    """G-CTX: Test backup of existing files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create output directory with existing file
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        # Create a file that will be overwritten
        existing_file = output_dir / "__init__.py"
        existing_file.write_text("original content")

        source_file = Path(tmpdir) / "source.py"
        source_file.write_text("def foo(): pass")

        config = MoedularizerConfig(
            source_file=source_file,
            output_dir=output_dir,
            package_name="test",
            backup_existing=True,
        )

        # Run pipeline
        analyzer = Analyzer()
        source = source_file.read_text()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(source_file)
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

        # Write (should create backup)
        generator.write_modules(modules, output_dir)

        # Verify backup was created
        backup_file = existing_file.with_suffix(".py.bak")
        assert backup_file.exists()

        # Verify backup contains original content
        assert backup_file.read_text() == "original content"


def test_dry_run_does_not_modify_files():
    """G-CTX: Test dry-run mode doesn't modify files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        source_file = Path(tmpdir) / "source.py"
        source_file.write_text("def foo(): pass")

        config = MoedularizerConfig(
            source_file=source_file,
            output_dir=output_dir,
            package_name="test",
            dry_run=True,
        )

        # Run pipeline
        analyzer = Analyzer()
        source = source_file.read_text()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(source_file)
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

        # In dry-run mode, write_modules should return empty list
        # and NOT create any files on disk
        written = generator.write_modules(modules, output_dir)
        assert written == []

        # Verify no files were created in the output directory
        output_contents = list(output_dir.iterdir())
        assert len(output_contents) == 0, f"Expected no files, found: {output_contents}"


def test_circular_import_detection_integration():
    """G-CTX: Test circular import detection in full pipeline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = Path(tmpdir) / "circular.py"
        source_file.write_text("""
def foo():
    return bar()

def bar():
    return foo()
""")

        output_dir = Path(tmpdir) / "output"

        config = MoedularizerConfig(
            source_file=source_file,
            output_dir=output_dir,
            package_name="circular",
        )

        # Run pipeline
        analyzer = Analyzer()
        source = source_file.read_text()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(source_file)
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

        # Validate
        original_exports = {s.name for s in symbols if not s.name.startswith("_")}
        validator = Validator(original_exports)
        result = validator.validate(modules, clusters, graph)

        # Note: Circular dependencies within a single module are fine
        # Only circular imports between modules are problematic
        # This test verifies the pipeline doesn't crash
        assert result is not None


def test_api_preservation_integration():
    """G-CTX: Test API preservation in full pipeline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = Path(tmpdir) / "api.py"
        source_file.write_text("""
__all__ = ['foo', 'bar', 'baz']

def foo():
    pass

def bar():
    pass

def baz():
    pass
""")

        output_dir = Path(tmpdir) / "output"

        config = MoedularizerConfig(
            source_file=source_file,
            output_dir=output_dir,
            package_name="api",
        )

        # Run pipeline
        analyzer = Analyzer()
        source = source_file.read_text()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(source_file)
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

        # Validate
        original_exports = set(dunder_all) if dunder_all else set()
        validator = Validator(original_exports)
        result = validator.validate(modules, clusters, graph)

        # Should preserve API
        assert len(result.errors) == 0


def test_generator_cross_module_imports():
    """G-CTX: Cross-module imports are generated for external_deps."""
    from moedularizer.types import Cluster, Dependency, DependencyType, Symbol, SymbolKind

    cluster_a = Cluster(name="module_a", symbols={"foo"})
    cluster_a.external_deps = [
        Dependency(source="foo", target="bar", dep_type=DependencyType.CALLS)
    ]
    cluster_b = Cluster(name="module_b", symbols={"bar"})
    cluster_b.external_deps = []

    symbol_map = {
        "foo": Symbol(
            name="foo",
            kind=SymbolKind.FUNCTION,
            source="def foo():\n    return bar()",
            lineno=1,
            end_lineno=2,
        ),
        "bar": Symbol(
            name="bar",
            kind=SymbolKind.FUNCTION,
            source="def bar():\n    return 42",
            lineno=3,
            end_lineno=4,
        ),
    }
    cluster_map = {"foo": "module_a", "bar": "module_b"}

    config = MoedularizerConfig(package_name="cross_pkg")
    generator = CodeGenerator(config)

    list(symbol_map.values())
    deps = [
        Dependency(source="foo", target="bar", dep_type=DependencyType.CALLS),
    ]
    graph = build_graph(deps)

    source = "def foo():\n    return bar()\n\ndef bar():\n    return 42\n"
    modules = generator.generate(
        [cluster_a, cluster_b], symbol_map, cluster_map, {}, source, graph=graph
    )

    module_a = next(m for m in modules if m.name == "module_a")
    module_b = next(m for m in modules if m.name == "module_b")

    assert "from cross_pkg.module_b import bar" in module_a.imports_needed, (
        f"Expected cross-module import, got: {module_a.imports_needed}"
    )
    assert module_b.imports_needed == []


def test_writer_output_dir_validation():
    """G-ERR: Moedularizer.write() raises ValueError when output_dir is None."""
    from moedularizer.types import ModularizationResult

    config = MoedularizerConfig()
    mod = Moedularizer(config)
    result = ModularizationResult(modules=[], clusters=[])

    with pytest.raises(ValueError, match="output_dir is not configured"):
        mod.write(result)


def test_modularize_programmatic_api():
    """G-CTX: Moedularizer.modularize() produces correct ModularizationResult."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = Path(tmpdir) / "input.py"
        source_file.write_text("""
def foo():
    return bar()

def bar():
    return 42
""")
        config = MoedularizerConfig(
            source_file=source_file,
            output_dir=Path(tmpdir) / "output",
            package_name="prog",
        )
        mod = Moedularizer(config)
        result = mod.modularize(source_file.read_text())

        assert len(result.modules) > 0, "Should have generated modules"
        assert len(result.clusters) > 0, "Should have clusters"
        assert len(result.errors) == 0, f"Unexpected errors: {result.errors}"
        assert len(result.preserved_exports) > 0, "Should have preserved exports"


def test_cli_main_end_to_end():
    """Invoke cli.main() with patched sys.argv, verify pipeline runs and \
produces output files."""
    import sys

    from moedularizer.cli import main

    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = Path(tmpdir) / "monolith.py"
        source_file.write_text("""
def hello():
    return world()

def world():
    return 42
""")
        output_dir = Path(tmpdir) / "output"

        original_argv = sys.argv
        try:
            sys.argv = [
                "moedularizer",
                str(source_file),
                str(output_dir),
                "--package-name",
                "e2e_pkg",
                "--max-symbols",
                "2",
            ]
            main()
        finally:
            sys.argv = original_argv

        assert output_dir.exists()
        init_file = output_dir / "__init__.py"
        assert init_file.exists()
        init_content = init_file.read_text()
        assert len(init_content) > 0
        assert "e2e_pkg" in init_content
