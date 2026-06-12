# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Diagnostic warnings accumulator (`get_warnings()`) across all pipeline stages
- Unified `force_groupings` validation in `modularize()` entry point
- `min_symbols_per_module` wired to post-clustering dependency check
- Trusted Publisher OIDC CI workflow for PyPI publishing
- Backslash-aware regex in generator for escaped-quote patterns
- `import` and `AnnAssign` statement support in analyzer symbol extraction
- Python 3.13 to CI matrix

### Changed
- `max_symbols_per_module` threshold parameterized via constructor instead of hardcoded
- Type hints modernized: `Dict→dict`, `List→list`, `Set→set`, `Tuple→tuple`
- Exception handling narrowed in analyzer to `AttributeError`, `TypeError`, `IndexError`
- Ruff linter rules expanded: `UP` (pyupgrade) and `FA` (future-annotations)
- Coverage threshold lowered to 75% with `imodent_bridge.py` and `__main__.py` excluded

### Fixed
- Dead `min_symbols_per_module` field in config now consumed by dependency resolution
- `force_separations` guard in clusterer when grouping list is empty
- MD5 fallback for unsupported hashlib algorithms in dependency resolution
- Stale annotation line numbers in 29 YAML proposals
- 36 bugs marked resolved across annotation YAMLs
- 9 obsoleted annotation proposals archived to `_do_not/`

## [0.1.0] - 2026-06-12

### Added
- Initial release: automatic modularization of monolithic Python files into packages
- AST-based symbol extraction, dependency resolution, and module clustering
- Configurable heuristics: separate dataclasses, constants, pure functions
- Python 3.9–3.12 support
- CLI and programmatic API
- Zero runtime dependencies beyond Python standard library
