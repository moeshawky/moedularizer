"""
Smoke tests - G-HALL: Import validation.

Tests that all imports exist and the package can be imported without errors.
This is the first gate - if imports fail, nothing else matters.
"""

import pytest

pytestmark = pytest.mark.smoke


def test_imports_exist():
    """G-HALL: Verify all imports exist (no hallucinated packages)."""
    # Test main package import
    import moedularizer

    assert moedularizer is not None

    # Test all module imports
    from moedularizer import (
        Moedularizer,
        MoedularizerConfig,
    )

    assert Moedularizer is not None
    assert MoedularizerConfig is not None

    # Test submodules
    from moedularizer import analyzer, clusterer, config, dependency, generator, types, validator

    assert analyzer is not None
    assert clusterer is not None
    assert config is not None
    assert dependency is not None
    assert generator is not None
    assert types is not None
    assert validator is not None


def test_stdlib_imports_only():
    """G-HALL: Verify package only uses stdlib imports (no hallucinated external deps)."""
    import moedularizer.analyzer
    import moedularizer.clusterer
    import moedularizer.config
    import moedularizer.dependency
    import moedularizer.generator
    import moedularizer.types
    import moedularizer.validator

    # Get all imported modules
    modules = [
        moedularizer.analyzer,
        moedularizer.clusterer,
        moedularizer.config,
        moedularizer.dependency,
        moedularizer.generator,
        moedularizer.types,
        moedularizer.validator,
    ]

    # Verify no external dependencies (only stdlib)
    stdlib_modules = {
        "ast",
        "re",
        "textwrap",
        "pathlib",
        "argparse",
        "sys",
        "collections",
        "dataclasses",
        "enum",
        "typing",
        "defaultdict",
    }

    for module in modules:
        # Check module's __dict__ for imports
        for name in dir(module):
            if name.startswith("_"):
                continue
            obj = getattr(module, name)
            if isinstance(obj, type):
                # Check if it's from stdlib
                module_name = obj.__module__.split(".")[0]
                if module_name not in stdlib_modules and module_name != "moedularizer":
                    # Allow builtins
                    if module_name != "builtins":
                        pytest.fail(f"Non-stdlib import detected: {module_name}")


def test_cli_import():
    """G-HALL: Verify CLI module can be imported."""
    from moedularizer.cli import main

    assert main is not None
    assert callable(main)


def test_types_exist():
    """G-HALL: Verify all type definitions exist."""
    from moedularizer.types import (
        Cluster,
        Dependency,
        DependencyType,
        ModularizationResult,
        Module,
        Symbol,
        SymbolKind,
    )

    assert Symbol is not None
    assert SymbolKind is not None
    assert Dependency is not None
    assert DependencyType is not None
    assert Module is not None
    assert Cluster is not None
    assert ModularizationResult is not None


def test_config_class_exists():
    """G-HALL: Verify config class exists and is instantiable."""
    from moedularizer.config import MoedularizerConfig

    config = MoedularizerConfig()
    assert config is not None
    assert config.package_name == "modularized"  # default value
    assert config.max_symbols_per_module == 10  # default value


def test_analyzer_class_exists():
    """G-HALL: Verify analyzer class exists and is instantiable."""
    from moedularizer.analyzer import Analyzer

    analyzer = Analyzer()
    assert analyzer is not None


def test_clusterer_class_exists():
    """G-HALL: Verify clusterer class exists and is instantiable."""
    from moedularizer.clusterer import Clusterer
    from moedularizer.config import MoedularizerConfig

    config = MoedularizerConfig()
    clusterer = Clusterer(config)
    assert clusterer is not None


def test_generator_class_exists():
    """G-HALL: Verify generator class exists and is instantiable."""
    from moedularizer.config import MoedularizerConfig
    from moedularizer.generator import CodeGenerator

    config = MoedularizerConfig()
    generator = CodeGenerator(config)
    assert generator is not None


def test_validator_class_exists():
    """G-HALL: Verify validator class exists and is instantiable."""
    from moedularizer.validator import Validator

    validator = Validator(set())
    assert validator is not None
