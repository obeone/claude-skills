# Canonical form and the hash contract

> Target ≤ 150 lines. Loaded when an agent needs to reason about the byte-level contract behind `--approved-canonical-hash`, the `--show-drift` flag, or the round-trip property tests.

## Why a canonical form exists

The skill writes `~/.claude/settings.json` only after the user (or calling agent) approves a specific `sha256` over the **bytes** the skill is about to commit. Without a canonical form, two equivalent JSON objects produce different hashes (key order, whitespace, escape choices), and the gate degenerates into "trust me, the file is the same".

The canonical form is the single source of truth for **what the user approved**. The critique output is shown verbatim alongside, but it is not what the gate hashes — the gate hashes the settings bytes.

## The canonical serializer

`scripts/_canonical.py` exposes `canonicalize(obj) -> bytes`. Its contract:

```python
def canonicalize(obj) -> bytes:
    text = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")
```

Concretely:

- **Sort keys** at every depth — order-independence is the whole point.
- **Two-space indent** — human-readable, line-diffable.
- **`ensure_ascii=False`** — UTF-8 strings keep their characters; the on-disk file matches what the user reads in their editor.
- **LF endings + trailing newline** — POSIX-clean; identical bytes on every host.

The CLI form `python _canonical.py < input.json > out.json` reads a JSON object on stdin and writes canonical bytes on stdout. Acceptance criterion #1 (round-trip byte-equal across 50 fixtures) lives directly on top of this CLI.

## The round-trip property

For any well-formed JSON `x`:

```
canonical(load(canonical(load(x)))) == canonical(load(x))
```

byte-for-byte. The 50 fixtures in `tests/fixtures/canonical/in_*.json` and `out_*.json` exercise this: 10 hand-curated edge cases (unicode keys, deep nesting, top-level scalars and arrays, mixed types, escaped characters) and 40 generated with a pinned seed. `tests/test_canonical.py` adds a hypothesis-style property test as a third layer.

If the round-trip ever breaks, the gate breaks: the user would approve hash `H1` but the apply phase would see `H2` after canonicalising the same object again. The skill refuses on hash mismatch with exit code `8` (`HashMismatchError`), which is precisely how this failure mode surfaces.

## Where the hash sits in the workflow

```
┌─ phase 1: build proposal in memory ──────────────────────────────┐
│   read settings.json → apply migrate / additions → strip examples │
│   → canonicalize → sha256                                         │
└──────────────┬───────────────────────────────────────────────────┘
               │  print:  canonical_sha256: <hex>
               ▼
            user re-runs with --approved-canonical-hash <hex>
               │
┌─ phase 2: critique gate ─────────────────────────────────────────┐
│   run `claude auto-mode critique` on proposal → exit 0?           │
│   structure matches fixture (## Major / ## Smaller)?              │
│   → print verbatim Markdown                                       │
└──────────────┬───────────────────────────────────────────────────┘
               │
┌─ phase 3: gate predicate ────────────────────────────────────────┐
│   gate_passes = (critique_exit == 0)                              │
│              AND (sha256(canonicalize(proposal)) == approved_hash)│
└──────────────┬───────────────────────────────────────────────────┘
               │ true
               ▼
┌─ phase 4: atomic write ──────────────────────────────────────────┐
│   backup → tmpfile + fsync → os.replace → update approved cache   │
└──────────────────────────────────────────────────────────────────┘
```

The cache lives at `~/.claude/.auto_mode_approved.json` (mode 0600). It records the canonical bytes the user last approved. `inspect_automode.py --show-drift` diffs the current canonical against this cache via `difflib.unified_diff` and exits `6` on drift (informational, non-fatal).

## The flat YAML walker

`canonicalize` is the JSON half. The YAML half lives in `parse_flat_yaml(text) -> dict[str, str]`, used to read `assets/heuristics.yaml` and `assets/dropped_rules.yaml`. It is intentionally minimal:

- Accepts only top-level `key: value` pairs (colon + space).
- Refuses indentation, lists, nested mappings, and empty values with a clear error.
- **Quoted values are read verbatim** — no YAML escape processing. `"a\\.b"` in the file becomes the literal string `a\.b`.
- Bare values that contain ` #` must be quoted; otherwise the walker treats `#` as the start of a comment.

Implication for anyone editing the asset YAMLs: write regex patterns with **single backslashes** as bare values, or quote them and write them verbatim. Two backslashes inside a quoted string ship a literal double backslash, which is almost never what you want. The walker's strictness is a feature: the asset files are configuration, not Turing-complete YAML.

## Why bytes, not prose, are the gate

`claude auto-mode critique` emits freeform Markdown. There is no `severity` field, no `--json` flag, and the binary returns exit `0` regardless of finding count. Inferring severity from prose ("`## Major issues`" vs "`## Smaller issues`") is observation, not contract. Anchoring the gate to that prose would make the skill's safety boundary depend on a string format Anthropic does not promise to preserve.

The bytes are the contract. The user reads the verbatim critique output, decides whether to proceed, and their `--approved-canonical-hash` is the irrevocable signal. Path (b) — see `references/critique_workflow.md` for the full rationale.

## See also

- `references/critique_workflow.md` — Path (b), swap-file mechanism, contract-drift detection.
- `references/recovery.md` — what to do when `--show-drift` reports drift, when a backup needs restoring, when a stranded `.preview-orig.<pid>` file is found.
- `tests/test_canonical.py` — the property test ground truth.
