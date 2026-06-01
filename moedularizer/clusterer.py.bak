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

import re
from collections import defaultdict
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
        self.config = config

    def cluster(
        self,
        symbols: List[Symbol],
        dependencies: List[Dependency],
    ) -> List[Cluster]:
        """Main clustering entry point."""
        if not symbols:
            return []

        # Filter out IMPORT symbols — they are not code to modularize
        code_symbols = [s for s in symbols if s.kind != SymbolKind.IMPORT]
        code_deps = [d for d in dependencies
                     if d.source in {s.name for s in code_symbols}
                     and d.target in {s.name for s in code_symbols}]

        graph = build_graph(code_symbols, code_deps)
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
        """Create clusters from user-specified groupings."""
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
                    pass  # Will be caught by validation

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
        """Apply heuristic-based clustering."""
        clusters = []
        used: Set[str] = set()

        # Separate dataclasses if configured
        if self.config.separate_dataclasses:
            dataclass_symbols = set()
            for name in remaining:
                if name in used:
                    continue
                sym = symbol_map.get(name)
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
                sym = symbol_map.get(name)
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
                sym = symbol_map.get(name)
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
                sym = symbol_map.get(name)
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
        """Cluster remaining symbols by dependency density."""
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
        """Ensure forced-separated symbols are in different clusters."""
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
        """Infer a module name from cluster contents."""
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

        return f"module_{abs(hash(frozenset(cluster.symbols))) % 10000}"

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
        CodeGenerator._sanitize_name at generator.py:274 — update both
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