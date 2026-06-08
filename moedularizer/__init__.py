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
from moedularizer.imodent_bridge import ImodentBridge, ImodentReport
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

__all__ = [
    # Core API
    "Moedularizer",
    "MoedularizerConfig",
    # Pipeline components
    "Analyzer",
    "Clusterer",
    "CodeGenerator",
    "Validator",
    # imodent bridge
    "ImodentBridge",
    "ImodentReport",
    # Graph
    "DependencyGraph",
    "build_graph",
    # Types (re-exported for annotation use)
    "Cluster",
    "Dependency",
    "DependencyType",
    "ModularizationResult",
    "Module",
    "Symbol",
    "SymbolKind",
    # Typing (re-exported for annotation use)
    "Dict",
    "List",
    "Optional",
    "Set",
    "Path",
]


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
        """Stores the MoedularizerConfig reference and runs eager validation.

        Calls config.validate() immediately — this is NOT deferred to
        modularize() or write(). If validate() returns a non-empty list
        of error strings, raises ValueError with those errors. Validation
        checks: source_file existence (when truthy), max/min symbol ordering,
        package_name.isidentifier(). Three additional gaps are documented
        in config.validate()'s own docstring but not enforced here
        (output_dir writability, max_symbols <= 0, force_groupings vs
        force_separations conflicts). No other initialization — this
        instance is reusable across multiple modularize()/write() calls
        because config is the only stored state.
        """
        self.config = config
        errors = self.config.validate()
        if errors:
            raise ValueError(errors)

    def modularize(self, source: str) -> ModularizationResult:
        """Runs the full modularization pipeline in five stages:

        1. AST Analysis (Analyzer). Parses `source` via ast.parse, extracts
           symbols and dependencies as a 5-tuple: symbols, dependencies,
           dunder_all, external_imports, module_level_code. Uses
           str(self.config.source_file) as filename; when source_file is
           None (programmatic use), filename resolves to "None" — cosmetic
           only, affects SyntaxError messages.

        2. Imodent analysis (optional). When config.use_imodent is True,
           runs ImodentBridge.analyze_project() on the project directory
           (source_file.parent if source_file is set, else current
           directory). Produces an ImodentReport with unused import
           detection and cross-file dependency data.

        3. Clustering (Clusterer). Groups symbols into Cluster objects
           via the 7-pass clustering pipeline gated by config thresholds
           and boolean flags.

        4. Mapping construction. Builds `symbol_map` (name → Symbol) for
           code generation lookups and `cluster_map` (symbol name →
           cluster name) for cross-module import resolution. Converts
           `external_imports` from List[Tuple] to Dict[str, List[str]]
           (merging duplicate module_path entries).

        5. Code generation (CodeGenerator). Builds a DependencyGraph via
           build_graph(), then calls generate() with 9 parameters (8
           original + optional imodent_report) to produce List[Module]
           with cross-module imports resolved and unused imports pruned.

        6. Export computation + validation (Validator). Computes
           `original_exports` as the union of auto-detected non-underscore
           non-IMPORT symbols and explicit __all__ entries. Constructs a
           Validator and returns a validated ModularizationResult with
           imodent warnings merged in.

        Note: `module_level_code` is extracted from the AST and passed
        through to generator.generate() but is never consumed there
        (see _bugs/__init__.py.yaml). `respect_dunder_all` config flag
        (config.py:39) is defined but never consulted — dunder_all is
        always respected unconditionally (see _bugs/).
        """
        analyzer = Analyzer()
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(self.config.source_file) if self.config.source_file else '<string>'
        )

        imodent_report: Optional[ImodentReport] = None
        if self.config.use_imodent:
            try:
                bridge = ImodentBridge()
                project_paths = (
                    [Path(p) for p in self.config.imodent_project_paths]
                    if self.config.imodent_project_paths
                    else [self.config.source_file.parent]
                    if self.config.source_file
                    else [Path.cwd()]
                )
                imodent_report = bridge.analyze_project(
                    project_paths,
                    check_lint=self.config.imodent_check_lint,
                )
            except Exception as e:
                imodent_report = None

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
            imodent_report=imodent_report,
        )

        original_exports = {s.name for s in symbols if not s.name.startswith('_') and s.kind != SymbolKind.IMPORT}
        if self.config.respect_dunder_all and dunder_all is not None:
            original_exports = set(dunder_all) | original_exports
        validator = Validator(original_exports)
        result = validator.validate(modules, clusters, graph)

        if imodent_report is not None and imodent_report.warnings:
            result.warnings.extend(imodent_report.warnings)

        return result

    def write(self, result: ModularizationResult) -> List[Path]:
        """Renders generated Module objects to source files and writes them to
        config.output_dir. Raises ValueError if output_dir is None — callers
        must ensure output_dir is set before calling write().

        Creates a fresh CodeGenerator(self.config) instance on each call.
        This means write() does not reuse any generator state from a prior
        modularize() call — the two methods are independently callable
        as long as the caller provides a ModularizationResult.

        Under dry_run (config.dry_run=True), returns an empty list without
        touching the filesystem. Under backup_existing, copies pre-existing
        .py files to .py.bak before overwriting.

        Returns List[Path] of written file paths (empty under dry_run).
        """
        if self.config.output_dir is None:
            raise ValueError("output_dir is not configured — set MoedularizerConfig.output_dir before calling write()")
        generator = CodeGenerator(self.config)
        return generator.write_modules(result.modules, self.config.output_dir)