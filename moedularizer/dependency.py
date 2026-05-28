# moedularizer/dependency.py
"""
Dependency graph construction and analysis.

Provides DependencyGraph for representing symbol dependencies and
detecting cycles, performing topological sorts, and extracting subgraphs.
"""

import sys
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from moedularizer.types import Dependency, DependencyType, Symbol


class DependencyGraph:
    """
    Directed graph of symbol dependencies.
    Nodes are symbol names, edges are dependency relationships.
    """

    def __init__(self, max_depth: int = 500):
        self._edges: Dict[str, Set[str]] = defaultdict(set)
        self._edge_types: Dict[Tuple[str, str], DependencyType] = {}
        self._reverse: Dict[str, Set[str]] = defaultdict(set)
        self.max_depth = max_depth  # prevent stack overflow in cycle detection

    def add_dependency(self, dep: Dependency):
        self._edges[dep.source].add(dep.target)
        self._edge_types[(dep.source, dep.target)] = dep.dep_type
        self._reverse[dep.target].add(dep.source)

    def depends_on(self, symbol: str) -> Set[str]:
        """What does this symbol depend on?"""
        return self._edges.get(symbol, set()).copy()

    def depended_by(self, symbol: str) -> Set[str]:
        """What depends on this symbol?"""
        return self._reverse.get(symbol, set()).copy()

    def has_dependency(self, source: str, target: str) -> bool:
        return target in self._edges.get(source, set())

    def all_symbols(self) -> Set[str]:
        nodes = set()
        for s in self._edges:
            nodes.add(s)
            nodes.update(self._edges[s])
        return nodes

    def find_cycles(self) -> List[List[str]]:
        """Find all cycles in the dependency graph using iterative DFS.

        Known limitations:
        - rec_stack is shared across all paths — if A→B→A and C→B both
          reach B, C's traversal may report a false positive cycle.
        - Cycle construction duplicates the node when node == path[cycle_start].
        - Depth limit breaks only the inner for loop; outer DFS continues
          with inconsistent coverage.
        """
        cycles = []
        visited = set()
        rec_stack = set()
        path = []

        def dfs_iterative(start: str):
            stack = [(start, False)]
            while stack:
                node, processed = stack.pop()
                if processed:
                    # Post-order: remove from path and rec_stack
                    rec_stack.discard(node)
                    if path and path[-1] == node:
                        path.pop()
                    continue

                if node in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(node)
                    cycle = path[cycle_start:] + [node]
                    cycles.append(cycle)
                    continue

                if node in visited:
                    continue

                visited.add(node)
                rec_stack.add(node)
                path.append(node)

                # Push post-order marker
                stack.append((node, True))

                # Push neighbors
                for neighbor in sorted(self._edges.get(node, set()), reverse=True):
                    if neighbor not in visited or neighbor in rec_stack:
                        stack.append((neighbor, False))

                # Check depth limit
                if len(path) > self.max_depth:
                    cycles.append(list(path) + ["... (depth limit reached)"])
                    break

        for node in self.all_symbols():
            if node not in visited:
                dfs_iterative(node)

        return cycles

    def topological_sort(self) -> List[str]:
        """
        Topological sort of symbols using Kahn's algorithm.
        Raises ValueError if cycles exist.

        queue.pop(0) is O(n) on Python lists — each pop shifts remaining
        elements. Use collections.deque for O(1) popleft. Currently
        acceptable for typical module counts (<50).
        """
        in_degree: Dict[str, int] = defaultdict(int)
        all_nodes = self.all_symbols()

        # Initialize in-degree for all nodes
        for node in all_nodes:
            in_degree[node] = 0

        # Count incoming edges
        for source in all_nodes:
            for target in self._edges.get(source, set()):
                in_degree[target] += 1

        # Start with nodes that have no incoming edges
        queue = [s for s in all_nodes if in_degree[s] == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in self._edges.get(node, set()):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(all_nodes):
            remaining = all_nodes - set(result)
            raise ValueError(f"Graph has cycles, cannot topologically sort. "
                           f"Remaining nodes: {remaining}")

        return result

    def subgraph(self, symbols: Set[str]) -> "DependencyGraph":
        """Extract subgraph containing only specified symbols."""
        sub = DependencyGraph(max_depth=self.max_depth)
        for source in symbols:
            for target in self._edges.get(source, set()):
                if target in symbols:
                    dep_type = self._edge_types.get((source, target), DependencyType.CALLS)
                    sub.add_dependency(Dependency(
                        source=source,
                        target=target,
                        dep_type=dep_type,
                    ))
        return sub

    def symbol_order(self, symbols: List[str]) -> List[str]:
        """
        Return symbols in dependency order (dependencies first).
        Falls back to original order if cycles prevent topological sort.
        """
        sub = self.subgraph(set(symbols))
        try:
            ordered = sub.topological_sort()
            # Preserve original order for symbols not in the subgraph
            result = []
            seen = set()
            for s in ordered:
                if s in symbols and s not in seen:
                    result.append(s)
                    seen.add(s)
            for s in symbols:
                if s not in seen:
                    result.append(s)
                    seen.add(s)
            return result
        except ValueError:
            # Cycles exist; fall back to original order
            return list(symbols)


def build_graph(symbols: List[Symbol], dependencies: List[Dependency]) -> DependencyGraph:
    """Build a dependency graph from extracted symbols and dependencies.

    The `symbols` parameter is currently unused — only `dependencies`
    populate the graph. Reserved for future validation of symbol coverage.
    """
    graph = DependencyGraph()
    for dep in dependencies:
        graph.add_dependency(dep)
    return graph