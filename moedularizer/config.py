# moedularizer/config.py
"""
Configuration dataclass controlling the modularization pipeline.

Declares MoedularizerConfig with fields across categories:
input paths, clustering thresholds, force groupings/separations, code style,
validation checks, safety flags, and minimum Python version.
Imports only stdlib (dataclasses, pathlib, typing) — no internal
moedularizer dependencies.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class MoedularizerConfig:
    """
    Dataclass holding all pipeline control parameters across categories.
    Fields control: source/output paths and package name; clustering
    symbol-per-module bounds and separate/merge toggles; force-grouping
    and force-separation constraints; import style, __all__ generation;
    path sanitization, backups, and dry-run mode; minimum Python version
    floor. The validate() method checks structural invariants (source file
    existence, threshold ordering, package name validity, version floor)
    and documents intentionally unchecked gaps.
    """

    # Input
    source_file: Optional[Path] = None    # monolithic file to split (optional for programmatic use)
    output_dir: Optional[Path] = None     # directory for generated modules (optional for dry-run)
    package_name: str = "modularized"     # package name for imports

    # Clustering
    max_symbols_per_module: int = 10       # Maximum symbols in a single output module — clusterer splits clusters exceeding this threshold
    min_symbols_per_module: int = 1        # Minimum symbols per output module; enforced only in validate() as a relational check against max_symbols_per_module
    separate_dataclasses: bool = True      # put dataclasses in their own module
    separate_pure_functions: bool = True   # separate pure functions from side-effectful ones
    separate_constants: bool = True         # put constants in their own module
    separate_module_level_code: bool = True  # put module-level code in __init__ or separate module

    # Heuristics
    force_groupings: Dict[str, List[str]] = field(default_factory=dict)
    # e.g. {"key_handling": ["KeyPattern", "DetectedKey", "KeyRegistry"]}

    force_separations: List[Set[str]] = field(default_factory=list)
    # e.g. [{"canonicalize", "ModelCatalog"}] — these MUST be in different modules

    # Style
    use_absolute_imports: bool = True       # Use 'from package.module import X' absolute imports instead of relative imports in generated modules
    add_dunder_all: bool = True            # add __all__ to each module

    # Import handling
    respect_dunder_all: bool = True         # use __all__ from original file if present

    # Safety
    sanitize_module_names: bool = True      # prevent path traversal
    backup_existing: bool = True            # backup files before overwriting
    dry_run: bool = False                   # don't write files

    def validate(self) -> List[str]:
        """Return list of validation errors.

        Gaps not checked here: output_dir writability (runtime concern),
        max_symbols_per_module <= 0, force_groupings vs force_separations
        conflicts.
        """
        errors: List[str] = []
        if self.source_file and not self.source_file.exists():
            errors.append(f"Source file not found: {self.source_file}")
        if self.max_symbols_per_module < self.min_symbols_per_module:
            errors.append("max_symbols_per_module < min_symbols_per_module")
        if not self.package_name.isidentifier():
            errors.append(f"Invalid package name: {self.package_name!r}")
        return errors
