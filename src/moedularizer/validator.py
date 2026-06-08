# moedularizer/validator.py
"""
Validation — check for circular imports, API preservation, and other issues.

Runs multiple validation passes:
1. Circular import detection between modules
2. API preservation check (all original exports still accessible)
3. Symbol coverage check (no symbol lost or duplicated)
4. Module size check (no empty or oversized modules)
5. Naming convention check (valid Python identifiers)
"""

from typing import Dict, List, Set, Tuple

from moedularizer.dependency import DependencyGraph
from moedularizer.types import Cluster, ModularizationResult, Module, SymbolKind


class Validator:
    """Validate modularization results."""

    def __init__(self, original_exports: Set[str]):
        """Store the expected public symbols for the top-level __init__.py.

        ``original_exports`` is the set of symbols the generated init module
        should re-export after modularization. The validator later compares
        this set against the init module's actual exports in
        ``_check_api_preservation`` to flag any missing symbols.

        The set is stored as-is — no validation or mutation on construction.
        """
        self.original_exports = original_exports

    def validate(
        self,
        modules: List[Module],
        clusters: List[Cluster],
        graph: DependencyGraph,
    ) -> ModularizationResult:
        """Run all validation checks."""
        result = ModularizationResult(
            modules=modules,
            clusters=clusters,
        )

        # Check for circular imports
        has_cycles = self._check_circular_imports(modules, result)

        # Check API preservation
        self._check_api_preservation(modules, result)

        # Check all symbols are assigned
        self._check_symbol_coverage(modules, result)

        # Check module sizes
        self._check_module_sizes(modules, result)

        # Check naming conventions
        self._check_naming(modules, result)

        # Set overall success — only circular imports are errors
        # Missing exports are warnings, not errors (generator will auto-populate)
        if has_cycles:
            result.errors.append("Circular imports detected — see warnings for details")

        return result

    def _check_circular_imports(
        self,
        modules: List[Module],
        result: ModularizationResult,
    ) -> bool:
        """Check for circular imports between modules using iterative DFS.

        Builds a module dependency graph from init module import
        statements (``from X import Y`` format only). Cycles are
        detected via iterative DFS with per-traversal ``path_index``
        dict — each DFS call maintains its own path tracking, preventing
        false-positive cycles from state bleed between independent
        traversals (RC #4 fix).

        Returns True if any cycles are found, False otherwise.
        Warnings for detected cycles are appended to ``result.warnings``.
        """
        # Build module dependency graph from import statements
        module_deps: Dict[str, Set[str]] = {}

        for module in modules:
            module_deps[module.name] = set()

        # Parse import lines to determine module dependencies
        for module in modules:
            for imp in module.imports_needed:
                # Parse "from pkg.module import X, Y"
                if " from " in imp and " import " in imp:
                    try:
                        parts = imp.split(" from ")[1].split(" import ")[0]
                        module_name = parts.rsplit(".", 1)[-1]
                        module_deps[module.name].add(module_name)
                    except (IndexError, ValueError):
                        result.warnings.append(f"Could not parse import: {imp}")

        # Check for cycles using iterative DFS with per-traversal path tracking.
        # Each DFS traversal maintains its own path_index dict, preventing
        # false-positive cycles from state bleed between independent traversals.
        visited: Set[str] = set()
        has_cycles = False

        def dfs_iterative(start: str) -> bool:
            stack: List[Tuple[str, bool]] = [(start, False)]
            path: List[str] = []
            path_index: Dict[str, int] = {}
            found_cycle = False

            while stack:
                node, processed = stack.pop()
                if processed:
                    path_index.pop(node, None)
                    if path and path[-1] == node:
                        path.pop()
                    continue

                if node in path_index:
                    # Found a cycle — path_index maps node to its position
                    cycle_start = path_index[node]
                    cycle = [*path[cycle_start:], node]
                    result.warnings.append(f"Circular import: {' -> '.join(cycle)}")
                    found_cycle = True
                    continue

                if node in visited:
                    continue

                visited.add(node)
                path_index[node] = len(path)
                path.append(node)
                stack.append((node, True))

                for dep in sorted(module_deps.get(node, set())):
                    if dep not in visited or dep in path_index:
                        stack.append((dep, False))

            return found_cycle

        for module_name in module_deps:
            if module_name not in visited and dfs_iterative(module_name):
                has_cycles = True

        return has_cycles

    def _check_api_preservation(
        self,
        modules: List[Module],
        result: ModularizationResult,
    ) -> bool:
        """Check that all original public symbols are still accessible."""
        # Find __init__.py exports
        init_module = next((m for m in modules if m.is_init), None)
        if not init_module:
            result.warnings.append("No __init__.py module found")
            return False

        # Collect all exported symbols from __init__.py
        exported = set(init_module.all_exports) if init_module.all_exports else set()

        # Also check import lines in __init__.py
        for imp in init_module.imports_needed:
            if " import " in imp:
                imported = imp.split(" import ")[1].split(",")
                for name in imported:
                    exported.add(name.strip())

        # Check all original exports are present
        missing = self.original_exports - exported
        if missing:
            result.warnings.append(f"Missing exports in __init__.py: {sorted(missing)}")
            return False

        result.preserved_exports = exported
        return True

    def _check_symbol_coverage(
        self,
        modules: List[Module],
        result: ModularizationResult,
    ) -> None:
        """Check that all symbols are assigned to exactly one module.

        Returns None — callers must parse result.warnings strings to
        detect duplicate coverage programmatically. No boolean flag returned.
        """
        symbol_counts: Dict[str, int] = {}
        for module in modules:
            if module.is_init:
                continue
            for sym in module.symbols:
                if sym.kind != SymbolKind.IMPORT:
                    symbol_counts[sym.name] = symbol_counts.get(sym.name, 0) + 1

        # Check for duplicates
        for name, count in symbol_counts.items():
            if count > 1:
                result.warnings.append(f"Symbol '{name}' appears in {count} modules")

        # Check for empty modules
        for module in modules:
            if module.is_init:
                continue
            sym_count = len([s for s in module.symbols if s.kind != SymbolKind.IMPORT])
            if sym_count == 0:
                result.warnings.append(f"Module '{module.name}' is empty")

    def _check_module_sizes(
        self,
        modules: List[Module],
        result: ModularizationResult,
    ) -> None:
        """Check module sizes are reasonable."""
        for module in modules:
            if module.is_init:
                continue
            sym_count = len([s for s in module.symbols if s.kind != SymbolKind.IMPORT])
            # Hardcoded threshold 20 differs from config.max_symbols_per_module
            # (default 10). The validator warns at >20 while the clusterer caps
            # at config.max_symbols_per_module. These serve different purposes:
            # config is a hard clustering limit, validator is a warning.
            if sym_count > 20:
                result.warnings.append(
                    f"Module '{module.name}' has {sym_count} symbols — consider splitting"
                )

    def _check_naming(
        self,
        modules: List[Module],
        result: ModularizationResult,
    ) -> None:
        """Check module names are valid Python identifiers."""
        for module in modules:
            if module.is_init:
                continue
            if not module.name.isidentifier():
                result.warnings.append(
                    f"Module name '{module.name}' is not a valid Python identifier"
                )
