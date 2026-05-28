# Moedularizer

Automatically modularize monolithic Python files into packages.

Given a single Python file, moedularizer analyzes symbol dependencies, clusters related code, and generates a proper package structure with cross-module imports and a re-exporting `__init__.py`.

## Install

```bash
pip install moedularizer
```

Zero dependencies beyond the Python standard library.

## Quick Start

```bash
# Command line
python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package

# Dry run (preview without writing)
python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package --dry-run

# Verbose output
python -m moedularizer.cli monolith.py ./my_package/ --package-name my_package --verbose
```

```python
# Programmatic API
from moedularizer import Moedularizer, MoedularizerConfig
from pathlib import Path

config = MoedularizerConfig(
    source_file=Path("monolith.py"),
    output_dir=Path("my_package/"),
    package_name="my_package",
)

mod = Moedularizer(config)
result = mod.modularize(Path("monolith.py").read_text())

print(f"Generated {len(result.modules)} modules")
print(f"Preserved exports: {len(result.preserved_exports)}")

for warning in result.warnings:
    print(f"Warning: {warning}")

if not result.errors:
    mod.write(result)
```

## How It Works

1. **Analyze** — Parse Python source via `ast`, extract symbols (classes, functions, constants) and their dependencies
2. **Cluster** — Group symbols by dependency density, respecting configurable heuristics (separate dataclasses, constants, pure functions)
3. **Generate** — Produce module files with proper `from pkg.mod import sym` cross-references
4. **Validate** — Check for circular imports, API preservation, module naming, symbol coverage

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--max-symbols` | 10 | Max symbols per generated module |
| `--separate-dataclasses` | True | Put dataclasses in their own module |
| `--separate-constants` | True | Put constants in their own module |
| `--absolute-imports` | True | Use absolute imports |
| `--dry-run` | False | Preview without writing files |
| `--no-backup` | False | Skip backing up existing files |
| `--verbose` | False | Detailed symbol/dependency/cluster output |
| `--force-groupings` | — | Force symbols together: `name=Sym1,Sym2` |

## License

MIT
