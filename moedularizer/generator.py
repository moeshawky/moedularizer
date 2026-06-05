"""Converts Cluster groupings into Module objects with cross-module
import resolution, renders them to Python source strings, and
writes to disk. CodeGenerator is the sole class: generate() builds
Module objects from clusters (8 params, produces List[Module] with
guaranteed __init__); render_module() assembles source strings from
docstring + imports + symbol bodies + __all__; three private
helpers handle docstring templating (_generate_docstring), import
classification via hardcoded stdlib set (_add_imports), and
import filtering via regex with string-literal stripping
(_filter_imports_for_module); write_modules() commits rendered
source to disk with backup. Imports types.py symbols, config.py
(MoedularizerConfig), and dependency.py (DependencyGraph)."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from moedularizer.config import MoedularizerConfig
from moedularizer.dependency import DependencyGraph
from moedularizer.types import (
    Cluster,
    Module,
    Symbol,
    SymbolKind,
)


class CodeGenerator:
    """Generate modularized Python files from clusters."""

    def __init__(self, config: MoedularizerConfig):
        """Stores the MoedularizerConfig reference as self.config. No
        validation, no derived state computation — config fields are
        read lazily by downstream methods: package_name in generate()
        (lines 78, 119), add_dunder_all in render_module() (line 154),
        dry_run and backup_existing in write_modules() (lines 247, 258).
        """
        self.config = config

    def generate(
        self,
        clusters: List[Cluster],
        symbol_map: Dict[str, Symbol],
        cluster_map: Dict[str, str],
        external_imports: Dict[str, List[str]],
        source: str,
        dunder_all: Optional[List[str]] = None,
        module_level_code: Optional[str] = None,  # Reserved: module-level imperative code placement, not yet implemented
        graph: Optional[DependencyGraph] = None,
    ) -> List[Module]:
        """Generate modules from clusters.

        Parameters:
            clusters: Symbol groupings from Clusterer.
            symbol_map: Dict mapping symbol names to Symbol objects.
            cluster_map: Dict mapping symbol names to cluster names, used
                at line 70 to resolve cross-module dependency targets.
            external_imports: Dict of module_path -> [imported names].
            source: Original source text (for filtering imports).
            dunder_all: Explicit __all__ from the original source file,
                takes precedence over auto-detected exports.
            module_level_code: Imperative code extracted from module level.
            graph: DependencyGraph, used at lines 67-68 to verify import
                targets exist via graph.all_symbols().

        Returns:
            List[Module] with guaranteed __init__ module appended as the
            final element.
        """
        modules = []

        # Group symbols by cluster
        for cluster in clusters:
            symbols = [symbol_map[s] for s in cluster.symbols if s in symbol_map]
            if not symbols:
                continue

            # Determine module name
            module_name = self._sanitize_name(cluster.name)
            is_init = module_name == "__init__"

            # Get imports for this module from cross-module (external) dependencies
            imports_needed = []
            if graph is not None:
                all_symbols = graph.all_symbols()
                for dep in cluster.external_deps:
                    target_cluster_name = cluster_map.get(dep.target)
                    if target_cluster_name is None:
                        continue
                    target_module_name = self._sanitize_name(target_cluster_name)
                    if target_module_name == module_name:
                        continue
                    if dep.target in all_symbols:
                        imports_needed.append(
                            f"from {self.config.package_name}.{target_module_name} import {dep.target}"
                        )

            # Only include external imports actually used by this module's symbols
            module_ext_imports = self._filter_imports_for_module(
                symbols, external_imports, source
            )

            modules.append(
                Module(
                    name=module_name,
                    symbols=symbols,
                    dependencies=[],
                    imports_needed=list(set(imports_needed)),
                    external_imports=module_ext_imports,
                    is_init=is_init,
                    all_exports=None,  # Set later when init is finalized
                )
            )

        # Compute auto-exports: all public non-IMPORT symbols across all clusters
        auto_exports_set: Set[str] = {
            s.name for s in symbol_map.values()
            if not s.name.startswith('_') and s.kind != SymbolKind.IMPORT
        }
        auto_exports = list(auto_exports_set)

        # Determine init exports: explicit __all__ takes precedence, else auto
        init_exports = dunder_all if dunder_all is not None else sorted(auto_exports)

        # Update existing init module or add one
        init_module = next((m for m in modules if m.is_init), None)
        if init_module:
            init_module.all_exports = init_exports
        else:
            # Build import lines for init module
            init_imports = []
            for m in modules:
                if not m.is_init:
                    for s in m.symbols:
                        if not s.name.startswith('_') and s.kind != SymbolKind.IMPORT:
                            init_imports.append(
                                f"from {self.config.package_name}.{m.name} import {s.name}"
                            )
            modules.append(
                Module(
                    name="__init__",
                    symbols=[],
                    dependencies=[],
                    imports_needed=sorted(set(init_imports)),
                    external_imports=[],
                    is_init=True,
                    all_exports=init_exports,
                )
            )

        return modules

    def render_module(self, module: Module) -> str:
        """Render a Module to Python source string."""
        lines = []

        # Docstring
        docstring = self._generate_docstring(module)
        if docstring:
            lines.append(f'"""{docstring}"""')

        # Imports
        self._add_imports(module, lines)

        # Symbol source code
        for sym in module.symbols:
            if sym.kind != SymbolKind.IMPORT and sym.source.strip():
                lines.append("")
                lines.append(sym.source.rstrip())

        # __all__
        if self.config.add_dunder_all and module.all_exports:
            lines.append("")
            lines.append("__all__ = [")
            for name in sorted(module.all_exports):
                lines.append(f'    "{name}",')
            lines.append("]")

        return "\n".join(lines)

    def _generate_docstring(self, module: Module) -> str:
        """Generate module docstring."""
        if module.is_init:
            return f"{self.config.package_name} — auto-modularized package."

        symbol_kinds = set(s.kind for s in module.symbols)
        kind_names = {
            SymbolKind.FUNCTION: "functions",
            SymbolKind.ASYNC_FUNCTION: "async functions",
            SymbolKind.CLASS: "classes",
            SymbolKind.CONSTANT: "constants",
        }
        parts = [kind_names.get(k, "symbols") for k in symbol_kinds]

        if parts:
            return f"Module {module.name} — {', '.join(parts)}."
        return f"Module {module.name}."

    def _add_imports(self, module: Module, lines: List[str]) -> None:
        """Add import statements.

        stdlib_modules is a hardcoded set — only checks the first component
        of a dotted import path (set at 189, check at 213). Missing some stdlib modules
        (e.g. contextlib, csv, xml) and may false-positive on same-named
        third-party packages.
        """
        stdlib_modules = {
            "abc", "argparse", "ast", "asyncio", "collections", "copy",
            "dataclasses", "datetime", "enum", "functools", "glob", "hashlib",
            "io", "itertools", "json", "logging", "math", "os", "pathlib",
            "pickle", "re", "shutil", "signal", "socket", "sqlite3", "sys",
            "tempfile", "textwrap", "threading", "time", "traceback", "typing",
            "unittest", "urllib", "uuid", "warnings", "weakref",
        }

        stdlib_imports = []
        third_party_imports = []

        for imp in module.external_imports:
            # Handle tuple format: (module_path, [names])
            if isinstance(imp, tuple):
                module_path, _ = imp
            elif isinstance(imp, str):
                if imp.startswith("from "):
                    module_path = imp.split(" from ")[1].split(" import ")[0].split(".")[0]
                else:
                    module_path = imp.split(" import ")[1].split(".")[0] if " import " in imp else imp.split()[1].split(".")[0]
            else:
                continue

            if module_path in stdlib_modules:
                stdlib_imports.append(imp)
            else:
                third_party_imports.append(imp)

        # Add stdlib imports
        if stdlib_imports:
            for imp in sorted(stdlib_imports):
                if isinstance(imp, tuple):
                    module_path, names = imp
                    lines.append(f"from {module_path} import {', '.join(names)}")
                else:
                    lines.append(imp)

        # Add third-party imports
        if third_party_imports:
            if stdlib_imports:
                lines.append("")
            for imp in sorted(third_party_imports):
                if isinstance(imp, tuple):
                    module_path, names = imp
                    lines.append(f"from {module_path} import {', '.join(names)}")
                else:
                    lines.append(imp)

        # Add internal imports
        if module.imports_needed:
            if stdlib_imports or third_party_imports:
                lines.append("")
            for imp in sorted(module.imports_needed):
                lines.append(imp)

    def write_modules(self, modules: List[Module], output_dir: Path) -> List[Path]:
        """Write all modules to disk."""
        if self.config.dry_run:
            return []
        written = []
        output_dir.mkdir(parents=True, exist_ok=True)

        for module in modules:
            content = self.render_module(module)
            filename = f"{module.name}.py" if not module.is_init else "__init__.py"
            filepath = output_dir / filename

            # Backup existing file if needed
            if filepath.exists() and self.config.backup_existing:
                backup_path = filepath.with_suffix(filepath.suffix + ".bak")
                backup_path.write_text(filepath.read_text())

            filepath.write_text(content)
            written.append(filepath)

        return written

    def _filter_imports_for_module(
        self,
        symbols: List[Symbol],
        external_imports: Dict[str, List[str]],
        source: str,
    ) -> List[Tuple[str, List[str]]]:
        """Filter external imports to only those used by this module's symbols.

        String literal stripping at lines 282-285 uses regex that does not
        handle escaped quotes inside strings or nested triple-quoted strings.
        """
        symbol_source = "\n".join(s.source for s in symbols if s.source)

        # Strip string literals to avoid false positive matches
        # e.g. "json" inside ".json" file extension
        stripped = re.sub(r'""".*?"""', '', symbol_source, flags=re.DOTALL)
        stripped = re.sub(r"'''.*?'''", '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'"[^"]*"', '""', stripped)
        stripped = re.sub(r"'[^']*'", "''", stripped)

        used_names = set()
        for module_path, names in external_imports.items():
            for name in names:
                # Match whole words only, on code (not string literals)
                pattern = r'(?<![a-zA-Z0-9_])' + re.escape(name) + r'(?![a-zA-Z0-9_])'
                if re.search(pattern, stripped):
                    used_names.add((module_path, name))

        # Rebuild dict grouped by module_path
        filtered: Dict[str, List[str]] = {}
        for module_path, name in used_names:
            filtered.setdefault(module_path, []).append(name)

        return list(filtered.items())

    def _sanitize_name(self, name: str) -> str:
        """Sanitize name to valid Python identifier.

        Duplicate of Clusterer._sanitize_name at clusterer.py:417 — update
        both if changing. Re-sanitization is safe (already-sanitized names
        produce the same result), but divergence is a maintenance risk.
        """
        name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
        name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        if not name or not name.isidentifier():
            name = "module"
        return name.lower()
