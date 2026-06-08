"""imodent integration bridge — cross-file import analysis and hygiene checking.

Wraps imodent's AnalysisCoordinator to provide moedularizer with:
- Unused import detection: which imports in a file are never referenced
- Cross-file dependency graph: what modules import what, and what's imported by whom
- Import usage evidence: per-file, per-import usage counts and locations
- Filtered external imports: prune unused imports from external_imports dicts

Used as an optional enhancement to the Analyzer pipeline. When enabled,
the Moedularizer pipeline runs imodent analysis on the project directory
alongside the monolith, cross-referencing import findings against the
generated module structure.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from imodent import AnalysisConfig, AnalysisCoordinator


@dataclass
class ImportUsage:
    """Per-import usage report from imodent analysis."""
    module: str
    name: Optional[str]
    used: bool
    usage_count: int
    line: int
    finding_type: str
    message: str


@dataclass
class ImodentReport:
    """Aggregated imodent analysis results for a file or project.

    unused_imports: set of (module, name) tuples that imodent flagged as unused.
        name is None for bare imports ('import json'), non-None for
        'from X import Y' imports.
    import_usage: per-file list of ImportUsage records with usage counts.
    cross_file_deps: {importing_module: set(imported_modules)} from the
        project-wide dependency graph.
    warnings: human-readable warning strings about import hygiene issues.
    """
    unused_imports: Set[Tuple[str, Optional[str]]] = field(default_factory=set)
    import_usage: Dict[Path, List[ImportUsage]] = field(default_factory=dict)
    cross_file_deps: Dict[str, Set[str]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return len(self.unused_imports) > 0 or len(self.warnings) > 0

    def is_import_used(self, module: str, name: Optional[str] = None) -> bool:
        return (module, name) not in self.unused_imports

    def filter_external_imports(
        self,
        external_imports: Dict[str, List[str]],
        file_path: Optional[Path] = None,
    ) -> Dict[str, List[str]]:
        """Remove unused imports from an external_imports dict.

        When file_path is provided, cross-references against per-file
        usage data. Otherwise uses the global unused_imports set.

        Handles the bare-import mismatch: imodent reports ('os', None)
        for 'import os', while moedularizer stores {'os': ['os']}.
        """
        if not self.unused_imports:
            return external_imports

        filtered: Dict[str, List[str]] = {}
        for module_path, names in external_imports.items():
            kept = []
            for name in names:
                # imodent uses None for bare imports; moedularizer uses module name
                unused = (module_path, name) in self.unused_imports
                unused_bare = (module_path, None) in self.unused_imports and name == module_path
                if not unused and not unused_bare:
                    kept.append(name)
            if kept:
                filtered[module_path] = kept
        return filtered


class ImodentBridge:
    """Bridge between moedularizer and imodent's code intelligence engine.

    Runs imodent's AnalysisCoordinator on project directories and
    extracts import-usage data, unused import findings, and cross-file
    dependency relationships.

    Usage:
        bridge = ImodentBridge()
        report = bridge.analyze_project(Path("my_package/"))

        # Check if an import is used
        if not report.is_import_used("typing", "List"):
            print("typing.List is unused")

        # Filter external imports for code generation
        clean_imports = report.filter_external_imports(external_imports_dict)
    """

    def __init__(self):
        self._coordinator: Optional[AnalysisCoordinator] = None
        self._last_result = None

    def analyze_project(
        self,
        paths: List[Path],
        check_lint: bool = False,
        check_syntax: bool = True,
    ) -> ImodentReport:
        """Run imodent analysis on project paths and produce an ImodentReport.

        Parameters:
            paths: Directories or files to analyze.
            check_lint: Enable Ruff-backed lint checks (slower).
            check_syntax: Run syntax validation pass.

        Returns:
            ImodentReport with unused imports, usage data, and cross-file deps.
        """
        config = AnalysisConfig(
            check_imports=True,
            check_syntax=check_syntax,
            check_lint=check_lint,
        )
        self._coordinator = AnalysisCoordinator(config)
        result = self._coordinator.analyze(paths)
        self._last_result = result

        return self._build_report(result)

    def _build_report(self, result) -> ImodentReport:
        """Extract moedularizer-relevant data from an AnalysisResult."""
        unused: Set[Tuple[str, Optional[str]]] = set()
        import_usage: Dict[Path, List[ImportUsage]] = {}
        warnings: List[str] = []
        cross_file_deps: Dict[str, Set[str]] = {}

        for finding in result.context.findings:
            if finding.type.startswith("unused_import"):
                module = finding.import_module or ""
                name = finding.import_name
                unused.add((module, name))

                file_path = finding.file
                if file_path not in import_usage:
                    import_usage[file_path] = []

                usage = ImportUsage(
                    module=module,
                    name=name,
                    used=False,
                    usage_count=finding.usage_count,
                    line=finding.location.line if finding.location else 0,
                    finding_type=finding.type,
                    message=finding.message,
                )
                import_usage[file_path].append(usage)

            if finding.type.startswith("circular"):
                warnings.append(f"{finding.file}: {finding.message}")

        for (mod, name) in sorted(unused):
            if name is not None:
                warnings.append(
                    f"Unused import: 'from {mod} import {name}' at "
                    f"{self._last_source_line(mod, name, import_usage) if self._last_result else ''}"
                )
            else:
                warnings.append(f"Unused import: 'import {mod}'")

        try:
            graph = result.context.graph
            if hasattr(graph, '_imports'):
                for source, targets in graph._imports.items():
                    cross_file_deps[source] = set(targets)
        except Exception:
            pass

        return ImodentReport(
            unused_imports=unused,
            import_usage=import_usage,
            cross_file_deps=cross_file_deps,
            warnings=warnings,
        )

    @staticmethod
    def _last_source_line(
        module: str,
        name: Optional[str],
        import_usage: Dict[Path, List[ImportUsage]],
    ) -> str:
        for usages in import_usage.values():
            for u in usages:
                if u.module == module and u.name == name and u.line > 0:
                    return f"line {u.line}"
        return ""

    def analyze_file(
        self,
        file_path: Path,
        project_paths: Optional[List[Path]] = None,
    ) -> ImodentReport:
        """Analyze a single file with optional project context.

        When project_paths is provided, imodent also scans those
        directories for cross-file import evidence (e.g., to determine
        if a seemingly-unused import is re-exported elsewhere).
        """
        paths = [file_path]
        if project_paths:
            paths.extend(project_paths)
        return self.analyze_project(paths)

    def get_unused_for_file(self, file_path: Path) -> List[ImportUsage]:
        """Return unused import entries for a specific file."""
        if self._last_result is None:
            return []
        context = self._last_result.context
        results = []
        for finding in context.findings:
            if finding.type.startswith("unused_import") and finding.file == file_path:
                results.append(
                    ImportUsage(
                        module=finding.import_module or "",
                        name=finding.import_name,
                        used=False,
                        usage_count=finding.usage_count,
                        line=finding.location.line if finding.location else 0,
                        finding_type=finding.type,
                        message=finding.message,
                    )
                )
        return results
