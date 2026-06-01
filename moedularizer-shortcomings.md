# moedularizer Shortcomings Report

**Tool:** moedularizer (CLI v1.0)
**Tested:** 2026-06-01
**Context:** Modularized `gates.py` (1313 lines) and `steward.py` (1701 lines)
**Measured by:** Generated output comparison, import tests, 168+103 unit tests

---

## Summary

moedularizer correctly identifies dependency clusters — the structural analysis is sound. But its code generation introduces 6 classes of bugs that require manual repair. In the steward session, it produced 12 modules with zero correct imports and two dropped `@dataclass` decorators. Zero of 12 generated files worked on first import.

---

## Findings

### 1. Rejects dotted package names (severity: critical)

**Measured:**
```
$ moedularizer src.py out/ --package-name hive_mind.steward
Error: Invalid package name: 'hive_mind.steward'
```

Only flat names (`steward`, `gates`) are accepted. Every non-trivial Python project uses dotted package paths. The generated files use `from steward.xxx import ...` which fails because `steward` is not a top-level module:

```
ModuleNotFoundError: No module named 'steward'
```

**Fix required:** Post-generation `sed` pass to replace `from steward.` with `from hive_mind.steward.` in every file.

**Impact:** Every cross-module import in the generated package is broken out of the box for any project deeper than one directory.

### 2. Invalid stdlib import generation (severity: critical)

**Measured across 7 of 12 generated files:** moedularizer converts standard `import` statements to invalid `from X import X` forms:

| Original (correct) | Generated (broken) | Files affected |
|---|---|---|
| `import logging` | `from logging import logging` | `hint.py`, `edit_tool_names.py`, `sync_steward_scratchpad.py` |
| `import re` | `from re import re` | `session_detectors.py`, `hint_encoder.py`, `_score_line.py`, `edit_tool_names.py`, `steward_state.py` |
| `import hashlib` | `from hashlib import hashlib` | `steward_state.py` |
| `import json` | `from json import json` | `steward_state.py`, `steward_decision_loop.py` |
| `import time` | `from time import time` | `steward_state.py` |

All produce `ImportError: cannot import name 'logging' from 'logging'` at runtime.

**Root cause:** moedularizer treats `import X` and `from X import Y` as interchangeable. For modules (`logging`, `re`, `hashlib`, `json`, `time`), they are not. `from logging import logging` attempts to import the attribute `logging` from module `logging` — no such attribute exists.

### 3. Dataclass integrity not preserved (severity: critical)

**Measured:** In `steward.py`, two classes use `@dataclass`:

```python
@dataclass
class Hint:          # → generated as plain `class Hint:` (no decorator)
    source: str
    ...

@dataclass  
class StewardState:   # → generated as plain `class StewardState:` (no decorator)
    session_id: str
    ...
```

The `from dataclasses import dataclass, field` import was also reduced to `from dataclasses import field`. The `--no-separate-dataclasses` flag exists but addresses separating dataclasses into a different module, not preserving the decorator.

**Symptoms at runtime:**
- `Hint()` — `TypeError: Hint() takes no arguments`
- `StewardState.recent_tools` — returns `Field` object, not list
- `StewardState.__dataclass_fields__` — `AttributeError`, attribute does not exist
- 16/168 steward tests fail with `TypeError: 'Field' object does not support item assignment`

### 4. Missing cross-module imports (severity: high)

**Measured in steward_state.py:** The generated 535-line `steward_state.py` uses 6 symbols from other generated modules but imports none of them:

| Symbol | Used on lines | Defined in | Import generated? |
|--------|--------------|------------|-------------------|
| `ReasoningState` | 36, 111, 115, 432, 433, 471 | `reasoning_state.py` (or duplicate in same file) | ✗ |
| `_extract_structural` | 374 | `_extract_structural.py` | ✗ |
| `_score_line` | 385 | `_score_line.py` | ✗ |
| `EDIT_TOOL_NAMES` | 412 | `edit_tool_names.py` | ✗ |
| `SEARCH_TOOL_NAMES` | 421 | `edit_tool_names.py` | ✗ |
| `REASONING_TOOL_NAMES` | 424 | `edit_tool_names.py` | ✗ |
| `_BASH_FAILURE_MARKERS` | 441 | `edit_tool_names.py` | ✗ |

Also `session_detectors.py` uses `EDIT_TOOL_NAMES` (lines 68, 124) but moedularizer generated no import for it.

**Root cause:** The dependency cluster analysis correctly identifies which symbols belong together, but the import generation pass does not emit `from ./neighbor_module import symbol` for symbols that cross cluster boundaries.

### 5. Circular imports introduced (severity: high)

**Measured:** The generated package creates a circular import that did not exist in the monolith:

```
hint.py (imports HintEncoder from hint_encoder.py)
   ↓
hint_encoder.py (imports Hint from hint.py for type annotations)
   ↓ back to hint.py
```

The original file defined both classes together, so no circular dependency existed. Splitting them introduced one.

**Fix required:** `from __future__ import annotations` in `hint_encoder.py` to defer type annotation evaluation. moedularizer does not emit `from __future__ import annotations` in any file — it was stripped during generation.

### 6. Duplicate symbol placement (severity: medium)

**Measured across 2 runs on the same input:** moedularizer is non-deterministic about which module gets a symbol:

| Symbol | Dry run #1 | Dry run #2 (different flags) | Production run |
|--------|-----------|------------------------------|----------------|
| `ReasoningState` | Own file `reasoning_state.py` | — | Duplicated at bottom of `steward_state.py` |
| `build_steward_hints` | In `hint_encoder.py` | — | In `hint.py` |
| `METAPHOR_LIBRARY` | In `hint_encoder.py` | — | In `edit_tool_names.py` |

The clustering algorithm is sensitive to `--max-symbols` changes, producing different splits. The duplicate placement (ReasoningState appeared in both `reasoning_state.py` and at the bottom of `steward_state.py` in the same run) required manual cleanup.

### 7. Module naming from most-connected symbol (severity: low)

**Measured:** Module names are chosen by the most-connected symbol in each cluster, producing names like:

| File | Contains | Better name |
|------|----------|-------------|
| `edit_tool_names.py` | 7 constant sets, METAPHOR_LIBRARY, regex patterns | `_constants.py` |
| `_bash_failure_markers.py` | EDIT_TOOL_NAMES, MULTI_STEP_KEYWORDS (1st run) | `_constants.py` |

These are cosmetic but make package structure harder to reason about. The `--force-groupings` flag could help but requires advance knowledge of the cluster contents.

---

## What Works

| Feature | Status | Notes |
|---------|--------|-------|
| Symbol discovery (69 symbols from 1701 lines) | ✓ | Complete |
| Dependency graph (160 edges tracked) | ✓ | Used to guide manual rebuild of gates/ |
| Cluster identification (10-12 clusters per file) | ✓ | Sound grouping logic |
| Public API preservation (15 symbols re-exported) | ✓ | `__init__.py` correctly re-exports |
| `--dry-run` flag | ✓ | Useful for planning before execution |
| `--force-groupings` | ✓ | Lets user override clustering |

The core analysis — dependency graph construction and community detection — is correct. The code generator is where bugs accumulate.

---

## Recommended Fixes

| Bug | Priority | Fix approach |
|-----|----------|--------------|
| Dotted package names | P0 | Accept `--package-name hive_mind.steward` and emit correct import prefixes |
| Invalid stdlib imports | P0 | Preserve original import form; never convert `import X` to `from X import X` |
| Dropped decorators | P0 | Preserve `@dataclass`, `@staticmethod`, `@classmethod`, `@property` on every class/function |
| Missing cross-module imports | P1 | After clustering, scan each module for unresolved references and emit imports |
| Circular imports | P1 | Detect cycles in the generated module graph; merge modules that form cycles |
| Duplicate symbols | P1 | Deduplicate before writing — a symbol appears in exactly one module |
| No `from __future__` | P2 | Emit `from __future__ import annotations` in every generated module |

---

## Verdict

moedularizer is a competent dependency analyzer with a broken code generator. The output requires a 5-pass manual repair pipeline:

```
1. sed: `from steward.` → `from hive_mind.steward.`
2. sed: `from logging import logging` → `import logging`, etc.
3. Manual: restore `@dataclass` decorators on Hint, StewardState, etc.
4. Manual: add 7+ missing cross-module imports
5. Manual: add `from __future__ import annotations`, fix circular imports, deduplicate
```

After these fixes, it produces a working package. Without them, the output does not import.

---

*Generated 2026-06-01. Evidence: complete trace of steward.py and gates.py modularization, all moedularizer output, all test failures, all manual fixes applied.*
