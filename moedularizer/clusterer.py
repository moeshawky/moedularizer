# moedularizer/clusterer.py
"""
Clustering algorithm — group symbols into modules based on dependencies.

Uses a multi-pass approach:
1. Apply forced groupings from configuration
2. Apply heuristic separations (dataclasses, constants, pure functions)
3. Cluster remaining symbols by dependency density
4. Apply forced separations from configuration
5. Compute internal/external dependencies for each cluster
6. Infer cluster names from contents
"""

import hashlib
import re
from typing import Dict, List, Optional, Set

from moedularizer.config import MoedularizerConfig
from moedularizer.dependency import DependencyGraph, build_graph
from moedularizer.types import Cluster, Dependency, DependencyType, Symbol, SymbolKind


class Clusterer:
    """
    Groups symbols into clusters (future modules) based on:
    1. Dependency density — symbols that depend on each other stay together
    2. Heuristics — dataclasses separate, pure functions separate, etc.
    3. User overrides — force_groupings and force_separations
    """

    def __init__(self, config: MoedularizerConfig):
        """
        Stores the MoedularizerConfig reference. All clustering operations read
        thresholds and toggles from self.config. No other initialization needed —
        the cluster() method is the single entry point and builds fresh state
        on each call.
        """
        self.config = config

    def cluster(
        self,
        symbols: List[Symbol],
        dependencies: List[Dependency],
    ) -> List[Cluster]:
        """Seven-pass clustering pipeline plus pre-processing:

        — Pre-processing: filter IMPORT symbols from code_symbols and code_deps
          (names, not Symbol refs), build DependencyGraph
        — Pass 1: _apply_forced_groupings — create clusters from
          config.force_groupings
        — Pass 2: _apply_heuristics — isolate dataclasses, constants, pure
          functions, and module-level code into auto-named clusters (gated by
          config flags)
        — Pass 3: _cluster_by_dependencies — greedy single-pass clustering on
          remaining symbols; for each seed symbol (sorted), absorb its direct
          deps and dependents up to max_symbols_per_module
        — Pass 4: _apply_forced_separations — split clusters that co-locate
          symbols from config.force_separations groups
        — Pass 5: _compute_dependencies — populate Cluster.internal_deps and
          Cluster.external_deps (all edges tagged DependencyType.CALLS —
          clustering only needs edge existence, not type precision)
        — Pass 6: _infer_name — assign module names to clusters lacking
          user-provided names or carrying _auto_ prefix
        — Pass 7: _sanitize_name — sanitize against path traversal, gated on
          config.sanitize_module_names"""
        if not symbols:
            return []

        # Filter out IMPORT symbols — they are not code to modularize
        code_symbols = [s for s in symbols if s.kind != SymbolKind.IMPORT]
        code_deps = [d for d in dependencies
                     if d.source in {s.name for s in code_symbols}
                     and d.target in {s.name for s in code_symbols}]

        graph = build_graph(code_deps)
        symbol_map = {s.name: s for s in code_symbols}

        # Step 1: Apply forced groupings
        clusters = self._apply_forced_groupings(code_symbols, graph)

        # Step 2: Apply heuristic separations
        remaining = self._get_remaining_symbols(code_symbols, clusters)
        heuristic_clusters = self._apply_heuristics(remaining, symbol_map, graph)
        clusters.extend(heuristic_clusters)

        # Step 3: Cluster remaining by dependency density
        remaining = self._get_remaining_symbols(code_symbols, clusters)
        if remaining:
            dep_clusters = self._cluster_by_dependencies(remaining, graph)
            clusters.extend(dep_clusters)

        # Step 4: Apply forced separations
        clusters = self._apply_forced_separations(clusters, graph)

        # Step 5: Compute internal vs external dependencies for each cluster
        for cluster in clusters:
            self._compute_dependencies(cluster, graph)

        # Step 6: Name clusters
        for cluster in clusters:
            if not cluster.name or cluster.name.startswith("_auto_"):
                cluster.name = self._infer_name(cluster, symbol_map)

        # Step 7: Sanitize cluster names
        if self.config.sanitize_module_names:
            for cluster in clusters:
                cluster.name = self._sanitize_name(cluster.name)

        return clusters

    def _apply_forced_groupings(
        self,
        symbols: List[Symbol],
        graph: DependencyGraph,
    ) -> List[Cluster]:
        """Iterates config.force_groupings (Dict[str, List[str]]) and creates one
        Cluster per named group whose symbols exist in the code_symbols set.
        Unresolved symbol names (typos, stale references) are silently skipped
        — the pass at line 103 defers to an unspecified validation step that
        does not exist in config.validate(). Used_symbols tracking prevents a
        symbol from appearing in multiple forced groups (first-claimed wins)."""
        clusters = []
        used_symbols: Set[str] = set()
        all_symbol_names = {s.name for s in symbols}

        for group_name, symbol_names in self.config.force_groupings.items():
            cluster_symbols = set()
            for name in symbol_names:
                if name in all_symbol_names and name not in used_symbols:
                    cluster_symbols.add(name)
                    used_symbols.add(name)
                elif name not in all_symbol_names:
                    # Warn about typos in config
                    pass  # Silently skipped — not validated by config.validate()

            if cluster_symbols:
                clusters.append(Cluster(
                    name=group_name,
                    symbols=cluster_symbols,
                ))

        return clusters

    def _apply_heuristics(
        self,
        remaining: Set[str],
        symbol_map: Dict[str, Symbol],
        graph: DependencyGraph,
    ) -> List[Cluster]:
        """Applies four clustering strategies gated by config boolean flags, each
        creating a single auto-named cluster for a homogenous symbol category:

        1. Dataclass isolation (config.separate_dataclasses): collects CLASS
           symbols whose decorators match '@dataclass' or 'dataclass' substring.
           Substring match at line 135 produces false positives on decorators
           like @not_a_dataclass or @dataclass_factory — the existing inline
           comment acknowledges this trade-off.

        2. Constant isolation (config.separate_constants): collects all
           SymbolKind.CONSTANT symbols.

        3. Pure function isolation (config.separate_pure_functions): collects
           functions with <= 2 outgoing dependencies and >= 1 incoming
           dependents (a local utility heuristic).

        4. Module-level code isolation (config.separate_module_level_code):
           collects SymbolKind.MODULE_LEVEL_CODE symbols (imperative statements
           at module scope outside classes/functions).

        Each strategy respects the `used` set — symbols claimed by an earlier
        strategy are excluded from later ones (first-match wins, strategies
        tested in the order listed above)."""
        clusters = []
        used: Set[str] = set()

        # Separate dataclasses if configured
        if self.config.separate_dataclasses:
            dataclass_symbols = set()
            for name in remaining:
                if name in used:
                    continue
                sym: Optional[Symbol] = symbol_map.get(name)
                if sym and sym.kind == SymbolKind.CLASS:
                    # Check if it's a dataclass by looking for @dataclass decorator
                    # Substring check: 'dataclass' in dec produces false positives
                    # (e.g. @not_a_dataclass) and the ast.dump fallback from
                    # analyzer.py:82 still matches thanks to the substring.
                    if any("@dataclass" in dec or "dataclass" in dec for dec in sym.decorators):
                        dataclass_symbols.add(name)
                        used.add(name)

            if dataclass_symbols:
                clusters.append(Cluster(
                    name="_auto_dataclasses",
                    symbols=dataclass_symbols,
                ))

        # Separate constants if configured
        if self.config.separate_constants:
            constant_symbols = set()
            for name in remaining:
                if name in used:
                    continue
                sym: Optional[Symbol] = symbol_map.get(name)
                if sym and sym.kind == SymbolKind.CONSTANT:
                    constant_symbols.add(name)
                    used.add(name)

            if constant_symbols:
                clusters.append(Cluster(
                    name="_auto_constants",
                    symbols=constant_symbols,
                ))

        # Separate pure functions if configured
        if self.config.separate_pure_functions:
            pure_functions = set()
            for name in remaining:
                if name in used:
                    continue
                sym: Optional[Symbol] = symbol_map.get(name)
                if sym and sym.kind in (SymbolKind.FUNCTION, SymbolKind.ASYNC_FUNCTION):
                    # Heuristic: pure functions have few dependencies and are depended upon by many
                    deps = graph.depends_on(name)
                    dep_by = graph.depended_by(name)
                    # A function is "pure" if it doesn't depend on many other symbols
                    # and is used as a utility by others
                    if len(deps) <= 2 and len(dep_by) >= 1:
                        pure_functions.add(name)
                        used.add(name)

            if pure_functions:
                clusters.append(Cluster(
                    name="_auto_utils",
                    symbols=pure_functions,
                ))

        # Separate module-level code if configured
        if self.config.separate_module_level_code:
            mlc_symbols = set()
            for name in remaining:
                if name in used:
                    continue
                sym: Optional[Symbol] = symbol_map.get(name)
                if sym and sym.kind == SymbolKind.MODULE_LEVEL_CODE:
                    mlc_symbols.add(name)
                    used.add(name)

            if mlc_symbols:
                clusters.append(Cluster(
                    name="_auto_init",
                    symbols=mlc_symbols,
                ))

        return clusters

    def _cluster_by_dependencies(
        self,
        remaining: Set[str],
        graph: DependencyGraph,
    ) -> List[Cluster]:
        """Greedy single-pass clustering on remaining unassigned symbols. Symbols
        are processed in sorted order for determinism. For each seed symbol:
        1. Absorb the seed's direct dependency targets (graph.depends_on) that
           are still remaining and unassigned, up to max_symbols_per_module.
        2. Absorb the seed's direct dependents (graph.depended_by) under the
           same size cap.
        3. Create a new Cluster named _auto_group_N.

        This is NOT transitive — after absorbing deps, it does not recurse into
        the newly added symbols' dependencies. Only direct neighbors of the seed
        are considered. Symbols at 2+ hops from the seed end up in their own
        clusters on subsequent iterations."""
        clusters = []
        assigned: Set[str] = set()

        for symbol in sorted(remaining):  # Sort for determinism
            if symbol in assigned:
                continue

            # Start a new cluster with this symbol
            cluster_symbols = {symbol}
            assigned.add(symbol)

            # Add symbols that this one depends on (respecting max size)
            deps = graph.depends_on(symbol)
            for dep in sorted(deps):  # Sort for determinism
                if dep in remaining and dep not in assigned:
                    if len(cluster_symbols) < self.config.max_symbols_per_module:
                        cluster_symbols.add(dep)
                        assigned.add(dep)

            # Add symbols that depend on this one (respecting max size)
            dep_by = graph.depended_by(symbol)
            for db in sorted(dep_by):  # Sort for determinism
                if db in remaining and db not in assigned:
                    if len(cluster_symbols) < self.config.max_symbols_per_module:
                        cluster_symbols.add(db)
                        assigned.add(db)

            clusters.append(Cluster(
                name=f"_auto_group_{len(clusters)}",
                symbols=cluster_symbols,
            ))

        return clusters

    def _apply_forced_separations(
        self,
        clusters: List[Cluster],
        graph: DependencyGraph,
    ) -> List[Cluster]:
        """Scans clusters for any that co-locate multiple symbols from the same
        config.force_separations group. When found: removes the overlapping
        symbols from the cluster (in-place mutation via set subtraction) and
        creates separate single-symbol clusters for each. Short-circuits at
        line 250 if force_separations is empty.

        Contains a data-loss bug: when a cluster is modified (line 272),
        the modified cluster is excluded from the result (line 281).
        If the cluster had non-overlapping symbols besides the separated
        ones, those remaining symbols are silently dropped. See
        _bugs/clusterer.py.yaml for full analysis."""
        if not self.config.force_separations:
            return clusters

        for separation_group in self.config.force_separations:
            separation_set = set(separation_group)
            # Find clusters containing multiple forced-separated symbols
            new_clusters_to_add = []
            clusters_to_modify = []

            for i, cluster in enumerate(clusters):
                overlap = cluster.symbols & separation_set
                if len(overlap) > 1:
                    # Remove overlapping symbols from this cluster
                    clusters_to_modify.append((i, cluster, overlap))

            # Apply modifications
            result = []
            for i, cluster in enumerate(clusters):
                modified = False
                for mi, mcluster, overlap in clusters_to_modify:
                    if i == mi:
                        # Remove overlapping symbols
                        cluster.symbols -= overlap
                        # Create separate clusters for each forced-separated symbol
                        for sym in overlap:
                            new_clusters_to_add.append(Cluster(
                                name=f"_separated_{sym}",
                                symbols={sym},
                            ))
                        modified = True
                        break
                if not modified:
                    result.append(cluster)
                elif cluster.symbols:
                    result.append(cluster)

            result.extend(new_clusters_to_add)
            clusters = result

        return clusters

    def _get_remaining_symbols(
        self,
        symbols: List[Symbol],
        clusters: List[Cluster],
    ) -> Set[str]:
        """Get symbols not yet assigned to any cluster."""
        assigned = set()
        for cluster in clusters:
            assigned.update(cluster.symbols)
        return {s.name for s in symbols} - assigned

    def _compute_dependencies(
        self,
        cluster: Cluster,
        graph: DependencyGraph,
    ) -> None:
        """Compute internal and external dependencies for a cluster.

        All dependencies are tagged as DependencyType.CALLS (line 311:
        '# simplified'). This is intentional — clustering only needs
        dependency existence, not type precision. The validator uses the
        full graph separately with preserved types.
        """
        cluster.internal_deps = []
        cluster.external_deps = []

        for sym in cluster.symbols:
            for dep_target in graph.depends_on(sym):
                dep = Dependency(
                    source=sym,
                    target=dep_target,
                    dep_type=DependencyType.CALLS,  # simplified
                )
                if dep_target in cluster.symbols:
                    cluster.internal_deps.append(dep)
                else:
                    cluster.external_deps.append(dep)

    def _infer_name(
        self,
        cluster: Cluster,
        symbol_map: Dict[str, Symbol],
    ) -> str:
        """Heuristic cascade for naming clusters, tested in order:
        1. Single-class cluster → snake_case of class name (line 337)
        2. Multiple functions with common underscore-bounded prefix > 3 chars
           (line 343); prefix measured BEFORE stripping trailing underscores
           so 'get_' (len 4) passes > 3 while stripped 'get' (len 3) would not
        3. Multiple constants with common underscore-bounded prefix > 2 chars
           (line 351); names lowercased before prefix computation
        4. Fallback → snake_case of first symbol's name (line 359)
        5. Empty-symbols fallback → hash-based name (line 364). WARNING:
           Python's hash() is randomized by PYTHONHASHSEED, making this
           fallback non-deterministic across process invocations. See
           _bugs/clusterer.py.yaml."""
        symbols = [symbol_map.get(s) for s in cluster.symbols if s in symbol_map]
        symbols = [s for s in symbols if s is not None]

        # Heuristic: if cluster has one main class, name after it
        classes = [s for s in symbols if s.kind == SymbolKind.CLASS]
        if len(classes) == 1:
            name = classes[0].name
            return self._to_snake_case(name)

        # If cluster has functions, look for common prefix
        functions = [s for s in symbols if s.kind in (SymbolKind.FUNCTION, SymbolKind.ASYNC_FUNCTION)]
        if functions:
            names = [f.name for f in functions]
            prefix = self._common_prefix(names)
            if prefix and len(prefix) > 3:
                return prefix.rstrip('_')

        # If cluster has constants, look for common prefix
        constants = [s for s in symbols if s.kind == SymbolKind.CONSTANT]
        if constants:
            names = [c.name.lower() for c in constants]
            # Remove common suffixes like _PATTERN, _REGEX, etc.
            common = self._common_prefix(names)
            if common and len(common) > 2:
                return common.rstrip('_')

        # Fallback: name after first symbol
        if symbols:
            name = symbols[0].name
            return self._to_snake_case(name)

        return f"module_{hashlib.md5(str(sorted(cluster.symbols)).encode()).hexdigest()[:4]}"

    def _to_snake_case(self, name: str) -> str:
        """
        Convert CamelCase to snake_case, handling acronyms correctly.
        
        Examples:
            KeyPattern -> key_pattern
            APIKey -> api_key
            HTTPResponse -> http_response
            NVIDIAProvider -> nvidia_provider
        """
        # Handle all-uppercase acronyms first
        # Insert underscore before transitions from lowercase to uppercase
        # and before transitions from uppercase to uppercase followed by lowercase
        result = []
        for i, c in enumerate(name):
            if i == 0:
                result.append(c.lower())
            elif c.isupper():
                prev = name[i - 1]
                # Insert underscore before uppercase if:
                # 1. Previous char is lowercase (camelCase boundary)
                # 2. Next char exists and is lowercase (end of acronym)
                if prev.islower():
                    result.append('_')
                    result.append(c.lower())
                elif i + 1 < len(name) and name[i + 1].islower():
                    result.append('_')
                    result.append(c.lower())
                else:
                    result.append(c.lower())
            else:
                result.append(c)
        return ''.join(result)

    def _common_prefix(self, strings: List[str]) -> str:
        """Find common prefix among strings, stopping at underscore boundaries."""
        if not strings:
            return ""
        prefix = strings[0]
        for s in strings[1:]:
            while not s.startswith(prefix):
                # Remove last component (after underscore or last char)
                last_underscore = prefix.rfind('_')
                if last_underscore > 0:
                    prefix = prefix[:last_underscore]
                else:
                    prefix = prefix[:-1]
                if not prefix:
                    return ""
        return prefix

    def _sanitize_name(self, name: str) -> str:
        """
        Sanitize a module name to prevent path traversal and ensure
        it's a valid Python identifier.

        Converts to lowercase (PEP 8 module naming). Duplicate of
        CodeGenerator._sanitize_name at generator.py:302 — update both
        if changing.
        """
        # Remove any path separators or traversal attempts
        name = name.replace('/', '_').replace('\\', '_').replace('..', '_')
        # Remove non-identifier characters
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        # Remove leading digits
        name = re.sub(r'^[0-9]+', '', name)
        # Ensure not empty
        if not name:
            name = 'module'
        # Ensure valid Python identifier
        if not name.isidentifier():
            name = f'module_{name}'
        return name.lower()