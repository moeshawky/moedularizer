# moedularizer/cli.py
"""
Command-line interface for the moedularizer.

Delegates the modularization pipeline to Moedularizer.modularize() and
Moedularizer.write(). Verbose mode runs a lightweight pre-analysis pass
for display purposes; force_groupings typo checking also draws on
pre-analysis symbol names. The rest of the pipeline is the canonical
implementation in __init__.py — no duplicated logic.

Usage:
    python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package
    python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package --dry-run
    python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package --verbose
"""

import argparse
import sys
from pathlib import Path

from moedularizer import Moedularizer
from moedularizer.analyzer import Analyzer
from moedularizer.config import MoedularizerConfig
from moedularizer.generator import CodeGenerator
from moedularizer.types import SymbolKind


def main():
    """Run the full modularization pipeline from CLI, delegating to
    Moedularizer.modularize() and Moedularizer.write() for the core
    pipeline. CLI-specific concerns (argparse, verbose output, dry-run
    rendering, force_groupings typo check) remain in this function."""

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

    # Pre-analysis for verbose output and force_groupings typo check.
    # Moedularizer.modularize() runs Analyzer internally, so this is a
    # lightweight duplicate only when verbose or force_groupings are set.
    if args.verbose or config.force_groupings:
        analyzer = Analyzer()
        try:
            symbols, dependencies, dunder_all_pre, external_imports_pre, _ = analyzer.analyze(
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
            if dunder_all_pre:
                print(f"Found __all__: {dunder_all_pre}")
            if external_imports_pre:
                print(f"Found {len(external_imports_pre)} external import groups:")
                for module_path, names in external_imports_pre:
                    print(f"  from {module_path} import {', '.join(names)}")

        # Force groupings typo check (symbols must exist in source)
        if config.force_groupings:
            symbol_map = {s.name: s for s in symbols}
            for group_name, symbol_names in config.force_groupings.items():
                for sym_name in symbol_names:
                    if sym_name not in symbol_map:
                        print(
                            f"Warning: Symbol '{sym_name}' in "
                            f"force_groupings['{group_name}'] not found in source",
                            file=sys.stderr,
                        )

    # Core pipeline — delegate to Moedularizer
    mod = Moedularizer(config)
    try:
        result = mod.modularize(source)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Report warnings and errors
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
        generator = CodeGenerator(config)
        print("\nDry run — would generate:")
        for module in result.modules:
            non_import_count = len(
                [s for s in module.symbols if s.kind != SymbolKind.IMPORT]
            )
            print(f"\n{'='*60}")
            print(f"  {module.name}.py ({non_import_count} symbols)")
            print(f"{'='*60}")
            content = generator.render_module(module)
            for line in content.splitlines()[:20]:
                print(f"  {line}")
            line_count = len(content.splitlines())
            if line_count > 20:
                print(f"  ... ({line_count - 20} more lines)")
    else:
        try:
            written = mod.write(result)
            print(f"\n✓ Wrote {len(written)} modules to {args.output_dir}/")
            for path in written:
                print(f"  {path}")
        except OSError as e:
            print(f"\nError writing files: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()