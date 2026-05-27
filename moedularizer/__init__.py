# moedularizer/__init__.py
"""
Moedularizer — split monolithic Python files into packages.

Usage:
    from moedularizer import Moedularizer, MoedularizerConfig
    from pathlib import Path

    config = MoedularizerConfig(
        source_file=Path("monolith.py"),
        output_dir=Path("my_package/"),
        package_name="my_package",
    )

    mod = Moedularizer(config)
    result = mod.modularize(Path("monolith.py").read_text())

    if result.errors:
        for e in result.errors:
            print(f"ERROR: {e}")
    else:
        mod.write(result)
        print(f"Created {len(result.modules)} modules")
"""

from pathlib import Path
from typing import Dict, List, Optional, Set

from moedularizer.analyzer import Analyzer
from moedularizer.clusterer import Clusterer
from moedularizer.config import MoedularizerConfig
from moedularizer.dependency import DependencyGraph, build_graph
from moedularizer.generator import CodeGenerator
from moedularizer.types import (
    Cluster,
    Dependency,
    DependencyType,
    ModularizationResult,
    Module,
    Symbol,
    SymbolKind,
)
from moedularizer.validator import Validator


class Moedularizer:
    """Main entry point for the modularization pipeline."""

    def __init__(self, config: MoedularizerConfig):
        self.config = config
        # Validate config
       