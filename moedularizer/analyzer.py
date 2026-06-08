# moedularizer/analyzer.py
"""
AST analysis — extract symbols and their relationships from Python source.

This module provides two AST visitors:
- SymbolExtractor: Walks the AST and extracts all top-level symbols
- DependencyExtractor: Walks the AST and extracts dependency edges between symbols

Both handle Python 3.8+ AST features including end_lineno, type annotations,
and decorators.
"""

import ast
import re
import textwrap
from typing import List, Optional, Set, Tuple

from moedularizer.types import Dependency, DependencyType, Symbol, SymbolKind

if False:  # TYPE_CHECKING forward reference
    from moedularizer.imodent_bridge import ImodentReport


class SymbolExtractor(ast.NodeVisitor):
    """Walk AST and extract all top-level symbols including module-level code."""

    def __init__(self, source: str, filename: str = "<unknown>"):
        """Initialize SymbolExtractor with source text and filename.

        source is the raw source string. source_lines is pre-split for
        line-indexed access. symbols accumulates extracted Symbol
        objects. dunder_all and external_imports are populated by
        dedicated extraction methods after visiting. _current_class
        gates FunctionDef capture to top-level only.
        """
        self.source = source
        self.source_lines = source.splitlines()
        self.filename = filename
        self.symbols: List[Symbol] = []
        self.dunder_all: Optional[List[str]] = None  # extracted from source
        self.external_imports: List[Tuple[str, List[str]]] = []  # (module_path, [names])
        self._current_class: Optional[str] = None


    def _extract_source(self, node: ast.AST) -> str:
        """Extract source text for a node, handling missing end_lineno gracefully."""
        if not hasattr(node, 'lineno') or node.lineno is None:
            return ""
        start = node.lineno
        # end_lineno was added in Python 3.8; fall back to heuristic for older versions
        if hasattr(node, 'end_lineno') and node.end_lineno is not None:
            end = node.end_lineno
        else:
            # Heuristic: find next top-level definition or end of file
            end = self._find_end_of_block(start)
        if start < 1 or end > len(self.source_lines):
            return ""
        lines = self.source_lines[start - 1 : end]
        return textwrap.dedent('\n'.join(lines))

    def _find_end_of_block(self, start_line: int) -> int:
        """Heuristic: find the end of a block when end_lineno is unavailable."""
        # Look for the next top-level definition
        for i in range(start_line, len(self.source_lines)):
            line = self.source_lines[i]
            stripped = line.lstrip()
            if i > start_line and stripped and not stripped.startswith('#') and not stripped.startswith('"""'):
                # Check if this is a top-level definition
                if re.match(r'^(class |def |async def |@|[A-Z_]+\s*=)', stripped):
                    return i  # exclusive end
        return len(self.source_lines)

    def _get_docstring(self, node: ast.AST) -> Optional[str]:
        """Extract docstring from a node."""
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
                return node.body[0].value.value
        return None

    def _get_decorators(self, node: ast.AST) -> Tuple[str, ...]:
        """Extract decorator source strings from a node.

        Falls back to ast.dump() for complex decorators — broad except
        Exception at line 80 swallows failures silently. The ast.dump output
        is raw AST (e.g. "Name(id='dataclass', ctx=Load())"), not valid
        Python decorator syntax, but the clusterer's substring check
        ('dataclass' in dec) still matches.
        """
        decorators = []
        if hasattr(node, 'decorator_list'):
            for dec in node.decorator_list:
                try:
                    dec_source = self._extract_source(dec)
                    decorators.append(dec_source.strip())
                except Exception:
                    # Fallback: use ast.dump for complex decorators
                    decorators.append(ast.dump(dec))
        return tuple(decorators)

    def visit_ClassDef(self, node: ast.ClassDef):
        sym = Symbol(
            name=node.name,
            kind=SymbolKind.CLASS,
            source=self._extract_source(node),
            lineno=node.lineno,
            end_lineno=getattr(node, 'end_lineno', node.lineno) or node.lineno,
            docstring=self._get_docstring(node),
            decorators=self._get_decorators(node),
        )
        self.symbols.append(sym)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Capture top-level FunctionDef as a FUNCTION Symbol.

        Silently skips when _current_class is set (methods inside
        classes). Does not descend into the function body.
        """
        if self._current_class is None:
            sym = Symbol(
                name=node.name,
                kind=SymbolKind.FUNCTION,
                source=self._extract_source(node),
                lineno=node.lineno,
                end_lineno=getattr(node, 'end_lineno', node.lineno) or node.lineno,
                docstring=self._get_docstring(node),
                decorators=self._get_decorators(node),
            )
            self.symbols.append(sym)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Capture top-level AsyncFunctionDef as an ASYNC_FUNCTION Symbol.

        Structurally identical to visit_FunctionDef but produces
        ASYNC_FUNCTION kind. Skips when _current_class is set.
        """
        if self._current_class is None:
            sym = Symbol(
                name=node.name,
                kind=SymbolKind.ASYNC_FUNCTION,
                source=self._extract_source(node),
                lineno=node.lineno,
                end_lineno=getattr(node, 'end_lineno', node.lineno) or node.lineno,
                docstring=self._get_docstring(node),
                decorators=self._get_decorators(node),
            )
            self.symbols.append(sym)

    def visit_Assign(self, node: ast.Assign):
        """Capture ALL top-level assignment targets as CONSTANT symbols.

        Includes non-UPPER_CASE names and multi-target assignments.
        Each ast.Name target gets its own Symbol.
        """
        # Top-level constant assignments
        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id
                # Consider it a constant if UPPER_CASE, or if it's a typed assignment
                # We also capture non-UPPER_CASE assignments that look like config/constants
                sym = Symbol(
                    name=name,
                    kind=SymbolKind.CONSTANT,
                    source=self._extract_source(node),
                    lineno=node.lineno,
                    end_lineno=getattr(node, 'end_lineno', node.lineno) or node.lineno,
                )
                self.symbols.append(sym)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        """Capture typed top-level assignments as CONSTANT symbols.

        Only captures when the target is a simple ast.Name. Attribute
        targets and subscript targets are ignored. Type annotation info
        is not recorded.
        """
        # Typed top-level assignments
        if isinstance(node.target, ast.Name):
            sym = Symbol(
                name=node.target.id,
                kind=SymbolKind.CONSTANT,
                source=self._extract_source(node),
                lineno=node.lineno,
                end_lineno=getattr(node, 'end_lineno', node.lineno) or node.lineno,
            )
            self.symbols.append(sym)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track external imports and create IMPORT Symbols per alias.

        Dual behavior: (1) tracks non-relative (not starting with '.')
        imports in external_imports for downstream resolution;
        (2) creates an IMPORT Symbol for each imported alias.
        """
        # Track imports for re-export analysis
        if node.module and not node.module.startswith('.'):
            # External import (not relative)
            names = [alias.asname or alias.name for alias in node.names]
            self.external_imports.append((node.module, names))
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            sym = Symbol(
                name=name,
                kind=SymbolKind.IMPORT,
                source=self._extract_source(node),
                lineno=node.lineno,
                end_lineno=getattr(node, 'end_lineno', node.lineno) or node.lineno,
            )
            self.symbols.append(sym)

    def visit_Import(self, node: ast.Import):
        """Handle 'import X [as Y]' style imports.

        Stores (alias_name, [original_name]) in external_imports — the
        tuple format differs from visit_ImportFrom's (module_path,
        [names]). Creates an IMPORT Symbol for each alias.
        """
        # Handle "import X" style imports
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.external_imports.append((alias.name, [name]))
            sym = Symbol(
                name=name,
                kind=SymbolKind.IMPORT,
                source=self._extract_source(node),
                lineno=node.lineno,
                end_lineno=getattr(node, 'end_lineno', node.lineno) or node.lineno,
            )
            self.symbols.append(sym)

    def extract_module_level_code(self, tree: ast.Module) -> Optional[Symbol]:
        """
        Extract module-level imperative code (statements that aren't
        class/function/constant definitions or imports).
        """
        module_level_lines = []
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Assign):
                if all(isinstance(t, ast.Name) for t in node.targets):
                    continue
            if isinstance(node, ast.AnnAssign):
                continue
            # This is module-level code we need to preserve
            source = self._extract_source(node)
            if source.strip():
                module_level_lines.append((node.lineno, source))

        if not module_level_lines:
            return None

        # Combine all module-level code into one symbol
        combined_source = '\n\n'.join(src for _, src in module_level_lines)
        first_line = module_level_lines[0][0]
        last_line = module_level_lines[-1][0]

        return Symbol(
            name="__module_level_code__",
            kind=SymbolKind.MODULE_LEVEL_CODE,
            source=combined_source,
            lineno=first_line,
            end_lineno=last_line,
        )

    def extract_dunder_all(self, tree: ast.Module) -> Optional[List[str]]:
        """Extract __all__ definition from source, if present."""
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == '__all__':
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            names = []
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    names.append(elt.value)
                            return names
        return None


class DependencyExtractor(ast.NodeVisitor):
    """Walk AST and extract dependencies between symbols."""

    def __init__(self, symbol_names: Set[str]):
        """Initialize DependencyExtractor with known symbol names.

        symbol_names is the membership gate: only names in this set
        produce dependency edges. dependencies accumulates Dependency
        objects. _current_symbol tracks which top-level symbol is
        being visited.
        """
        self.symbol_names = symbol_names
        self.dependencies: List[Dependency] = []
        self._current_symbol: Optional[str] = None

    def visit_ClassDef(self, node: ast.ClassDef):
        """Extract INHERITS and DECORATOR dependencies from class definitions.

        Saves and restores _current_symbol around the class body.
        Checks base classes for INHERITS edges and decorators for
        DECORATOR edges — each gated by symbol_names membership.
        Descends into the class body via generic_visit for CALLS
        and USES_CONSTANT extraction.
        """
        old = self._current_symbol
        self._current_symbol = node.name

        # Check base classes for inheritance dependencies
        for base in node.bases:
            name = self._get_name(base)
            if name in self.symbol_names and name != node.name:
                self.dependencies.append(Dependency(
                    source=node.name,
                    target=name,
                    dep_type=DependencyType.INHERITS,
                    line=node.lineno,
                ))

        # Check decorators for decorator dependencies
        for dec in node.decorator_list:
            dec_name = self._get_name(dec)
            if dec_name in self.symbol_names and dec_name != node.name:
                self.dependencies.append(Dependency(
                    source=node.name,
                    target=dec_name,
                    dep_type=DependencyType.DECORATOR,
                    line=node.lineno,
                ))

        self.generic_visit(node)
        self._current_symbol = old

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Extract dependencies from top-level function definitions.

        Only fires when _current_symbol is None. Captures four
        dependency types: DECORATOR from decorator_list,
        TYPE_ANNOTATION from argument/return annotations, and
        DEFAULT_ARG from default argument values. Descends into the
        function body for CALLS/USES_CONSTANT extraction.
        """
        if self._current_symbol is None:
            old = self._current_symbol
            self._current_symbol = node.name

            # Check decorators
            for dec in node.decorator_list:
                dec_name = self._get_name(dec)
                if dec_name in self.symbol_names and dec_name != node.name:
                    self.dependencies.append(Dependency(
                        source=node.name,
                        target=dec_name,
                        dep_type=DependencyType.DECORATOR,
                        line=node.lineno,
                    ))

            # Check type annotations
            for arg in node.args.args:
                if arg.annotation:
                    ann_name = self._get_name(arg.annotation)
                    if ann_name in self.symbol_names and ann_name != node.name:
                        self.dependencies.append(Dependency(
                            source=node.name,
                            target=ann_name,
                            dep_type=DependencyType.TYPE_ANNOTATION,
                            line=node.lineno,
                        ))

            # Check return annotation
            if node.returns:
                ret_name = self._get_name(node.returns)
                if ret_name in self.symbol_names and ret_name != node.name:
                    self.dependencies.append(Dependency(
                        source=node.name,
                        target=ret_name,
                        dep_type=DependencyType.TYPE_ANNOTATION,
                        line=node.lineno,
                    ))

            # Check default argument values
            for default in node.args.defaults + node.args.kw_defaults:
                if default:
                    self._extract_names_from_node(default, node.name, DependencyType.DEFAULT_ARG)

            self.generic_visit(node)
            self._current_symbol = old

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Delegate to visit_FunctionDef via duck-typing.

        ast.AsyncFunctionDef shares identical structural attributes
        with ast.FunctionDef but is not a subclass, so delegation
        operates correctly at runtime. # type: ignore silences mypy.
        """
        # Same logic as FunctionDef
        self.visit_FunctionDef(node)  # type: ignore

    def visit_Call(self, node: ast.Call):
        """Capture CALLS dependencies when the call target is a known symbol.

        Extracts the root name from the call target via _get_name
        (unwraps Attribute chains). Skips self-dependencies by
        comparing against _current_symbol. Descends into call
        arguments via generic_visit.
        """
        if self._current_symbol:
            name = self._get_name(node.func)
            if name in self.symbol_names and name != self._current_symbol:
                self.dependencies.append(Dependency(
                    source=self._current_symbol,
                    target=name,
                    dep_type=DependencyType.CALLS,
                    line=node.lineno,
                ))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        """Capture USES_CONSTANT dependencies for bare name references.

        Only fires when _current_symbol is set (inside a tracked
        symbol). Skips self-references. Does not call generic_visit
        since Name is always a leaf node.
        """
        if self._current_symbol and node.id in self.symbol_names:
            if node.id != self._current_symbol:
                self.dependencies.append(Dependency(
                    source=self._current_symbol,
                    target=node.id,
                    dep_type=DependencyType.USES_CONSTANT,
                    line=node.lineno,
                ))

    def _extract_names_from_node(self, node: ast.AST, source: str, dep_type: DependencyType):
        """Extract all Name references from a node (used for default args, etc.)."""
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in self.symbol_names:
                if child.id != source:
                    self.dependencies.append(Dependency(
                        source=source,
                        target=child.id,
                        dep_type=dep_type,
                        line=getattr(node, 'lineno', 0),
                    ))

    def _get_name(self, node: ast.AST) -> str:
        """Extract a name from a node, handling attribute access."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            # For attribute access like module.ClassName, return just the root
            return self._get_name(node.value)
        elif isinstance(node, ast.Call):
            # For decorator calls like @dataclass(), return the function name
            return self._get_name(node.func)
        elif isinstance(node, ast.Subscript):
            # For subscript like List[int], return the root name
            return self._get_name(node.value)
        return ""


class Analyzer:
    """Main analysis interface."""

    def analyze(self, source: str, filename: str = "<unknown>") -> Tuple[List[Symbol], List[Dependency], Optional[List[str]], List[Tuple[str, List[str]]], Optional[Symbol]]:
        """
        Extract symbols and dependencies from Python source.

        Returns:
            (symbols, dependencies, dunder_all, external_imports, module_level_code)
        """
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as e:
            raise ValueError(f"Failed to parse {filename}: {e}") from e

        # Extract symbols
        extractor = SymbolExtractor(source, filename)
        extractor.visit(tree)

        # Extract __all__
        dunder_all = extractor.extract_dunder_all(tree)

        # Extract module-level code
        module_level_code = extractor.extract_module_level_code(tree)

        # Get symbol names for dependency analysis
        symbol_names = {s.name for s in extractor.symbols if s.kind != SymbolKind.IMPORT}

        # Extract dependencies
        dep_extractor = DependencyExtractor(symbol_names)
        dep_extractor.visit(tree)

        return (
            extractor.symbols,
            dep_extractor.dependencies,
            dunder_all,
            extractor.external_imports,
            module_level_code,
        )