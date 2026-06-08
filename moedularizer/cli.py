# moedularizer/cli.py
"""
Command-line interface for the moedularizer.

Usage:
    python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package
    python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package --dry-run
    python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package --verbose
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from moedularizer.analyzer import Analyzer
from moedularizer.clusterer import Clusterer
from moedularizer.config import MoedularizerConfig
from moedularizer.dependency import build_graph
from moedularizer.generator import CodeGenerator
from moedularizer.imodent_bridge import ImodentBridge, ImodentReport
from moedularizer.types import SymbolKind
from moedularizer.validator import Validator


def main():
    """Run the full modularization pipeline from CLI.

    Currently assembles the pipeline inline (analyze → cluster → generate →
    validate → write). Moedularizer.modularize() and Moedularizer.write()
    (__init__.py:72, :116) provide the canonical pipeline — main() should
    delegate to Moedularizer instead of inlining all components.
    """
    parser = argparse.ArgumentParser(
        description="Modularize a monolithic Python file into a package.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package

  # Dry run (show plan without writing)
  python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package --dry-run

  # Verbose output
  python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package --verbose

  # Custom clustering
  python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package \\
      --force-groupings key_handling=KeyPattern,DetectedKey,KeyRegistry
        """
    )
    parser.add_argument(
        "source_file",
        type=Path,
        help="Path to the monolithic Python file to split"
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory for the generated package"
    )
    parser.add_argument(
        "--package-name",
        required=True,
        help="Package name for imports (e.g. 'providers.registry')"
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=10,
        help="Maximum symbols per module (default: 10)"
    )
    parser.add_argument(
        "--separate-dataclasses",
        action="store_true",
        default=True,
        help="Put dataclasses in their own module (default: True)"
    )
    parser.add_argument(
        "--no-separate-dataclasses",
        action="store_false",
        dest="separate_dataclasses",
        help="Don't separate dataclasses"
    )
    parser.add_argument(
        "--separate-constants",
        action="store_true",
        default=True,
        help="Put constants in their own module (default: True)"
    )
    parser.add_argument(
        "--no-separate-constants",
        action="store_false",
        dest="separate_constants",
        help="Don't separate constants"
    )
    parser.add_argument(
        "--absolute-imports",
        action="store_true",
        default=True,
        help="Use absolute imports (default: True)"
    )
    parser.add_argument(
        "--relative-imports",
        action="store_false",
        dest="absolute_imports",
        help="Use relative imports"
    )
    parser.add_argument(
        "--force-groupings",
        action="append",
        default=[],
        help="Force symbols to be grouped together (format: name=Sym1,Sym2,Sym3)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan without writing files"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed information"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't backup existing files before overwriting"
    )
    parser.add_argument(
        "--imodent",
        action="store_true",
        dest="use_imodent",
        help="Enable imodent-powered import analysis and unused import filtering"
    )
    parser.add_argument(
        "--imodent-paths",
        nargs="*",
        default=[],
        help="Additional directories for imodent to scan for cross-file context"
    )
    parser.add_argument(
        "--imodent-lint",
        action="store_true",
        dest="imodent_check_lint",
        help="Enable Ruff-backed lint checks in imodent (slower)"
    )
    parser.add_argument(
        "--no-imodent-strict",
        action="store_false",
        dest="imodent_strict_imports",
        help="Report unused imports but don't remove them from generated modules"
    )

    args = parser.parse_args()

    # Parse force groupings
    force_groupings = {}
    for grouping in args.force_groupings:
        try:
            name, symbols_str = grouping.split("=", 1)
            symbols = [s.strip() for s in symbols_str.split(",")]
            force_groupings[name] = symbols
        except ValueError:
            print(f"Error: Invalid force-grouping format: {grouping}", file=sys.stderr)
            print("Expected format: name=Sym1,Sym2,Sym3", file=sys.stderr)
            sys.exit(1)

    # Read source
    try:
        source = args.source_file.read_text()
    except OSError as e:
        print(f"Error: Failed to read source file: {e}", file=sys.stderr)
        sys.exit(1)

    # Configure
    config = MoedularizerConfig(
        source_file=args.source_file,
        output_dir=args.output_dir,
        package_name=args.package_name,
        max_symbols_per_module=args.max_symbols,
        separate_dataclasses=args.separate_dataclasses,
        separate_constants=args.separate_constants,
        use_absolute_imports=args.absolute_imports,
        force_groupings=force_groupings,
        dry_run=args.dry_run,
        backup_existing=not args.no_backup,
        use_imodent=args.use_imodent,
        imodent_project_paths=args.imodent_paths,
        imodent_check_lint=args.imodent_check_lint,
        imodent_strict_imports=args.imodent_strict_imports,
    )

    # Validate config
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Analyze
    analyzer = Analyzer()
    try:
        symbols, dependencies, dunder_all, external_imports, module_level_code = analyzer.analyze(
            source, filename=str(args.source_file)
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Found {len(symbols)} symbols:")
        for sym in symbols:
            print(f"  {sym.kind.value}: {sym.name} (line {sym.lineno})")
        print(f"Found {len(dependencies)} dependencies:")
        for dep in dependencies:
            print(f"  {dep.source} -> {dep.target} ({dep.dep_type.value})")
        if dunder_all:
            print(f"Found __all__: {dunder_all}")
        if external_imports:
            print(f"Found {len(external_imports)} external import groups:")
            for module_path, names in external_imports:
                print(f"  from {module_path} import {', '.join(names)}")

    # Cluster
    clusterer = Clusterer(config)
    clusters = clusterer.cluster(symbols, dependencies)

    if args.verbose:
        print(f"\nGenerated {len(clusters)} clusters:")
        for cluster in clusters:
            print(f"  {cluster.name}: {sorted(cluster.symbols)}")
            if cluster.external_deps:
                ext_targets = [d.target for d in cluster.external_deps]
                print(f"    External deps: {sorted(ext_targets)}")

    # Build symbol -> cluster map
    symbol_map = {s.name: s for s in symbols}
    cluster_map = {}
    for cluster in clusters:
        for sym in cluster.symbols:
            cluster_map[sym] = cluster.name

    # Check for config typos
    for group_name, symbol_names in config.force_groupings.items():
        for sym_name in symbol_names:
            if sym_name not in symbol_map:
                print(f"Warning: Symbol '{sym_name}' in force_groupings['{group_name}'] not found in source", file=sys.stderr)

    # Convert external_imports from list of tuples to dict
    # This conversion is duplicated in Moedularizer.modularize()
    # (__init__.py:93-99) and 5 integration tests. If main() delegates
    # to Moedularizer, this copy goes away.
    external_imports_dict = {}
    for module_path, names in external_imports:
        if module_path not in external_imports_dict:
            external_imports_dict[module_path] = []
        for name in names:
            if name not in external_imports_dict[module_path]:
                external_imports_dict[module_path].append(name)

    # Run imodent project-wide import analysis if enabled
    imodent_report: Optional[ImodentReport] = None
    if config.use_imodent:
        try:
            bridge = ImodentBridge()
            project_paths = (
                [Path(p) for p in config.imodent_project_paths]
                if config.imodent_project_paths
                else [args.source_file.parent]
            )
            imodent_report = bridge.analyze_project(
                project_paths,
                check_lint=config.imodent_check_lint,
            )
        except Exception as e:
            if args.verbose:
                print(f"imodent analysis skipped: {e}", file=sys.stderr)

    # Generate
    generator = CodeGenerator(config)
    graph = build_graph(symbols, dependencies)
    modules = generator.generate(
        clusters, symbol_map, cluster_map, external_imports_dict, source,
        dunder_all=dunder_all,
        module_level_code=module_level_code,
        graph=graph,
        imodent_report=imodent_report,
    )

    # Validate
    original_exports = {s.name for s in symbols if not s.name.startswith('_') and s.kind != SymbolKind.IMPORT}
    if dunder_all:
        original_exports = set(dunder_all) | original_exports
    validator = Validator(original_exports)
    result = validator.validate(modules, clusters, graph)

    # Merge imodent warnings
    if imodent_report is not None and imodent_report.warnings:
        result.warnings.extend(imodent_report.warnings)

    # Report
    if result.warnings:
        print("\nWarnings:")
        for w in result.warnings:
            print(f"  ⚠ {w}")

    if result.errors:
        print("\nErrors:")
        for e in result.errors:
            print(f"  ✗ {e}")
        if not args.dry_run:
            sys.exit(1)

    # Preserved exports
    if result.preserved_exports:
        count = len(result.preserved_exports)
        if args.verbose:
            print(f"\nPreserved exports ({count}):")
            for name in sorted(result.preserved_exports):
                print(f"  {name}")
        else:
            print(f"\nPreserved exports: {count}")

    # Write or dry-run
    if args.dry_run:
        print("\nDry run — would generate:")
        for module in modules:
            print(f"\n{'='*60}")
            print(f"  {module.name}.py ({len([s for s in module.symbols if s.kind != SymbolKind.IMPORT])} symbols)")
            print(f"{'='*60}")
            content = generator.render_module(module)
            lines = content.splitlines()
            for line in lines[:20]:
                print(f"  {line}")
            if len(lines) > 20:
                print(f"  ... ({len(lines) - 20} more lines)")
    else:
        try:
            written = generator.write_modules(modules, args.output_dir)
            print(f"\n✓ Wrote {len(written)} modules to {args.output_dir}/")
            for path in written:
                print(f"  {path}")
        except OSError as e:
            print(f"\nError writing files: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()