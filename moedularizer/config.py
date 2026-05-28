# moedularizer/config.py
"""
Configuration — depends only on types.

Defines MoedularizerConfig which controls all aspects of the modularization
pipeline: clustering heuristics, naming conventions, validation strictness,
and output formatting.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class MoedularizerConfig:
    """Configuration for the modularization pipeline."""

    # Input
    source_file: Optional[Path] = None    # monolithic file to split (optional for programmatic use)
    output_dir: Optional[Path] = None     # directory for generated modules (optional for dry-run)
    package_name: str = "modularized"     # package name for imports

    # Naming
    module_naming: str = "infer"           # "infer", "snake_case", or "kebab-case"
    init_exports: str = "all"              # "all", "explicit", "none"

    # Clustering
    max_symbols_per_module: int = 10
    min_symbols_per_module: int = 1
    separate_dataclasses: bool = True      # put dataclasses in their own module
    separate_pure_functions: bool = True   # separate pure functions from side-effectful ones
    separate_constants: bool = True         # put constants in their own module
    separate_module_level_code: bool = True  # put module-level code in __init__ or separate module

    # API preservation
    preserve_public_api: bool = True       # re-export everything from __init__.py
    preserve_import_paths: bool = True      # old import paths still work
    respect_dunder_all: bool = True         # use __all__ from original file if present

    # Heuristics
    force_groupings: Dict[str, List[str]] = field(default_factory=dict)
    # e.g. {"key_handling": ["KeyPattern", "DetectedKey", "KeyRegistry"]}

    force_separations: List[Set[str]] = field(default_factory=list)
    # e.g. [{"canonicalize", "ModelCatalog"}] — these MUST be in different modules

    # Style
    use_absolute_imports: bool = True
    add_module_docstrings: bool = True
    add_type_annotations: bool = True
    add_dunder_all: bool = True            # add __all__ to each module

    # Validation
    check_circular_imports: bool = True
    check_api_preservation: bool = True
    max_recursion_depth: int = 500          # limit for cycle detection

    # Safety
    sanitize_module_names: bool = True      # prevent path traversal
    backup_existing: bool = True            # backup files before overwriting
    dry_run: bool = False                   # don't write files

    # Python version
    min_python_version: tuple = (3, 8)     # minimum supported Python version

    def validate(self) -> List[str]:
        """Return list of validation errors.

        Gaps not checked here: output_dir writability (runtime concern),
        max_symbols_per_module <= 0, force_groupings vs force_separations
        conflicts, max_recursion_depth positivity.
        """
        errors: List[str] = []
        if self.source_file and not self.source_file.exists():
            errors.append(f"Source file not found: {self.source_file}")
        if self.max_symbols_per_module < self.min_symbols_per_module:
            errors.append("max_symbols_per_module < min_symbols_per_module")
        if not self.package_name.isidentifier():
            errors.append(f"Invalid package name: {self.package_name!r}")
        if self.min_python_version < (3, 8):
            errors.append("Minimum Python version must be >= 3.8 (for ast.end_lineno)")
        return errors