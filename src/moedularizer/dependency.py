# moedularizer/dependency.py
"""
Dependency graph construction and analysis.

Provides DependencyGraph for representing symbol dependencies and
detecting cycles, performing topological sorts, and extracting subgraphs.
"""

from collections import defaultdict, deque

from moedularizer.types import Dependency, DependencyType


class DependencyGraph:
    """
    Directed graph of symbol dependencies.
    Nodes are symbol names, edges are dependency relationships.
    """

    def __init__(self, max_depth: int = 500):
        """Constructs an empty dependency graph. Allocates three internal
        data structures: _edges (forward adjacency via defaultdict(set)),
        _edge_types (source,target → DependencyType label map), and
        _reverse (reverse adjacency for O(1) depended_by queries).
        `max_depth` caps cycle-detection path length; defaults to 500
        to prevent unbounded recursion on dense graphs."""
        self._edges: dict[str, set[str]] = defaultdict(set)
        self._edge_types: dict[tuple[str, str], DependencyType] = {}
        self._reverse: dict[str, set[str]] = defaultdict(set)
        self.max_depth = max_depth

    def add_dependency(self, dep: Dependency) -> None:
        """Registers a Dependency edge in the graph. Updates three data
        structures atomically: forward adjacency (_edges), edge-type
        map (_edge_types), and reverse adjacency (_reverse). Edge-type
        is recorded by (source, target) tuple key to allow O(1) type
        lookup in subgraph() when copying edges."""
        self._edges[dep.source].add(dep.target)
        self._edge_types[(dep.source, dep.target)] = dep.dep_type
        self._reverse[dep.target].add(dep.source)

    def depends_on(self, symbol: str) -> set[str]:
        """What does this symbol depend on?"""
        return self._edges.get(symbol, set()).copy()

    def depended_by(self, symbol: str) -> set[str]:
        """What depends on this symbol?"""
        return self._reverse.get(symbol, set()).copy()

    def has_dependency(self, source: str, target: str) -> bool:
        """Edge existence check. Returns True when `target` is in the forward
        adjacency set of `source`. O(1) average via set membership on dict
        lookup. Returns False when either node is absent from the graph
        (defaultdict supplies empty set for missing keys)."""
        return target in self._edges.get(source, set())

    def all_symbols(self) -> set[str]:
        """Collects the union of all source nodes and all target nodes from
        the forward adjacency dict. Returns Set[str] covering every symbol
        that either depends on something or is depended upon. Symbols that
        are only targets (no outgoing edges) are captured because they
        appear as values in _edges[s] sets. Time complexity: O(|V|+|E|)
        where V is vertex count and E is edge count."""
        nodes = set()
        for s in self._edges:
            nodes.add(s)
            nodes.update(self._edges[s])
        return nodes

    def find_cycles(self) -> list[list[str]]:
        """Find all cycles in the dependency graph using iterative DFS.

        Each DFS traversal maintains its own path and path-set, preventing
        false-positive cycles from state bleed between independent traversals.
        Depth-limit hits terminate the current traversal cleanly rather than
        leaving the outer loop with inconsistent state.
        """
        cycles: list[list[str]] = []
        visited: set[str] = set()

        def dfs_iterative(start: str) -> None:
            stack: list[tuple[str, bool]] = [(start, False)]
            path: list[str] = []
            path_index: dict[str, int] = {}

            while stack:
                node, processed = stack.pop()
                if processed:
                    path_index.pop(node, None)
                    if path and path[-1] == node:
                        path.pop()
                    continue

                if node in path_index:
                    cycle_start = path_index[node]
                    cycle = path[cycle_start:]
                    cycles.append(cycle)
                    continue

                if node in visited:
                    continue

                visited.add(node)
                path_index[node] = len(path)
                path.append(node)

                stack.append((node, True))

                for neighbor in sorted(self._edges.get(node, set()), reverse=True):
                    if neighbor not in visited or neighbor in path_index:
                        stack.append((neighbor, False))

                if len(path) > self.max_depth:
                    cycles.append([*list(path), "... (depth limit reached)"])
                    stack.clear()
                    path.clear()
                    path_index.clear()
                    break

        for node in self.all_symbols():
            if node not in visited:
                dfs_iterative(node)

        return cycles

    def topological_sort(self) -> list[str]:
        """
        Topological sort of symbols using Kahn's algorithm.
        Raises ValueError if cycles exist.

        Uses collections.deque for O(1) popleft instead of O(n) list.pop(0).
        """
        in_degree: dict[str, int] = defaultdict(int)
        all_nodes = self.all_symbols()

        for node in all_nodes:
            in_degree[node] = 0

        for source in all_nodes:
            for target in self._edges.get(source, set()):
                in_degree[target] += 1

        queue = deque([s for s in all_nodes if in_degree[s] == 0])
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in self._edges.get(node, set()):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(all_nodes):
            remaining = all_nodes - set(result)
            raise ValueError(
                f"Graph has cycles, cannot topologically sort. Remaining nodes: {remaining}"
            )

        return result

    def subgraph(self, symbols: set[str]) -> "DependencyGraph":
        """Extract subgraph containing only specified symbols."""
        sub = DependencyGraph(max_depth=self.max_depth)
        for source in symbols:
            for target in self._edges.get(source, set()):
                if target in symbols:
                    dep_type = self._edge_types.get((source, target), DependencyType.CALLS)
                    sub.add_dependency(
                        Dependency(
                            source=source,
                            target=target,
                            dep_type=dep_type,
                        )
                    )
        return sub

    def symbol_order(self, symbols: list[str]) -> list[str]:
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


def build_graph(dependencies: list[Dependency]) -> DependencyGraph:
    """Build a dependency graph from extracted dependencies.

    Populates the graph from ``dependencies`` only. Returns a
    DependencyGraph instance with all edges registered.

    Returns:
        DependencyGraph: Graph with all dependency edges populated.
    """
    graph = DependencyGraph()
    for dep in dependencies:
        graph.add_dependency(dep)
    return graph
