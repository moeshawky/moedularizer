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
    """Main entry point for the modularization pipeline.

    Usage:
        config = MoedularizerConfig(
            source_file=Path("monolith.py"),
            output_dir=Path("my_package/"),
            package_name="my_package",
        )
        mod = Moedularizer(config)
        result = mod.modularize(Path("monolith.py").read_text())

        # Access preserved exports (symbols kept in __init__.py):
        for name in sorted(result.preserved_exports):
            print(f"  {name}")

        if not result.errors:
            mod.write(result)
    """

    def __init__(self, config: MoedularizerConfig):
        self.config = config
        errors = self.config.validate()
        if errors:
            raise ValueError(errors)

    def modularize(self, source: str) -> ModularizationResult:
        """Run the full modularization pipeline on source text.

        Returns ModularizationResult with modules, clusters, warnings, errors,
        and preserved_exports (the set of symbols re-exported from __init__.py).
        """
        analyzer = Analyzer()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(self.config.source_file)
        )

        clusterer = Clusterer(self.config)
        clusters = clusterer.cluster(symbols, dependencies)

        symbol_map = {s.name: s for s in symbols}
        cluster_map = {}
        for cluster in clusters:
            for sym in cluster.symbols:
                cluster_map[sym] = cluster.name

        # Convert external_imports from list of tuples to dict
        external_imports_dict: Dict[str, List[str]] = {}
        for module_path, names in external_imports:
            if module_path not in external_imports_dict:
                external_imports_dict[module_path] = []
            for name in names:
                if name not in external_imports_dict[module_path]:
                    external_imports_dict[module_path].append(name)

        generator = CodeGenerator(self.config)
        graph = build_graph(symbols, dependencies)
        modules = generator.generate(
            clusters, symbol_map, cluster_map, external_imports_dict, source,
            dunder_all=dunder_all,
            module_level_code=module_level_code,
            graph=graph,
        )

        original_exports = {s.name for s in symbols if not s.name.startswith('_') and s.kind != SymbolKind.IMPORT}
        if dunder_all:
            original_exports = set(dunder_all) | original_exports
        validator = Validator(original_exports)
        return validator.validate(modules, clusters, graph)

    def write(self, result: ModularizationResult) -> List[Path]:
        """Write generated modules to disk."""
        if self.config.output_dir is None:
            raise ValueError("output_dir is not configured — set MoedularizerConfig.output_dir before calling write()")
        generator = CodeGenerator(self.config)
        return generator.write_modules(result.modules, self.config.output_dir)