# moedularizer — Agents.md

Modular code analysis and dependency resolution tool.
**17 annotation YAMLs in `.annotations/`.**

## Quick Verify

```bash
cd /home/ubuntu/moedularizer
python3 -m moedularizer --help
```

## Commands

```bash
python3 -m moedularizer analyze <path>    # Analyze module dependencies
python3 -m moedularizer generate <path>   # Generate dependency graph
```

## File Structure

```
moedularizer/
├── analyzer.py      # Code analysis engine
├── cli.py           # CLI entry point
├── clusterer.py     # Module clustering
├── config.py        # Configuration
├── dependency.py    # Dependency resolution
├── generator.py     # Output generation
├── types.py         # Type definitions
└── validator.py     # Validation logic
tests/
```

---

## Annotation Protocol (DNA/RNA)

**Full protocol:** `.annotations/ANNOTATION_PROTOCOL.md`
**17 proposal YAMLs.**

### DNA/RNA Split
| Layer | Location | Rule |
|-------|----------|------|
| **DNA** | docstrings (`"""`), `#` comments in source | Precision-validated. Evidence-backed. |
| **RNA** | `.annotations/[file].py.yaml` | Proposals. Never touches source. Human gates. |
| **Bug Queue** | `.annotations/_bugs/` | Separate from doc proposals. Severity: info/warning/error/critical. |

### Key Rules
- **NEVER modify source files.** RNA proposals are `.yaml` only until human-approved.
- **BANNED words:** orchestrates, enables, facilitates, empowers, scalable, robust, architecture, leverages, utilizes, harnesses. Describe MECHANICS.
- **Evidence required.** Descriptive strings with snippets, not bare integers. No evidence = delete.
- **Bugs → `_bugs/`.** Bug reports are separate from annotation proposals. Cite exact mechanism.
- **`no_action` for completeness.** Items already documented get `type: no_action` with evidence pointing to the existing doc line.
- **Rejected proposals → `_do_not/`.** Never removed, only added. Future subagents receive DO_NOT entries as constraints.
- **One file = one YAML.** Mirror source tree in `.annotations/`.

### Include Dirs
`moedularizer/`, `tests/`

### Quality Gates (G1-G6)
G1: Evidence is descriptive (not bare integers). G2: Evidence line numbers match source. G3: Zero banned words. G4: No verbatim DNA duplication. G5: Bugs in `_bugs/` not in proposals. G6: `no_action` proves full coverage.
