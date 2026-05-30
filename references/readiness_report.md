# agy-image — Readiness Report (release evidence)

Skill version: 2026.5.30
Audit date: 2026-05-30
Author: built via skill-creator-advanced.

## Mechanical gate results

`release_gate.py agy-image --stage draft` → **PASS** (all checks; benchmark skipped). Individual gates:

| Gate | Result |
|------|--------|
| format | PASS (0 errors, 0 warnings) |
| openclaw frontmatter | PASS (0 issues) |
| structure (semantic blocks) | PASS |
| workflow_contract | PASS |
| semantics / semantic_rules | PASS |
| lifecycle | PASS (date-based version, benchmark metadata declared) |
| lifecycle_state (`skill_lifecycle.yaml`) | PASS (status: draft) |
| eval_coverage | PASS (7 coverage tags, zh/en/mixed) |
| eval_quality | PASS |
| golden_trigger_set | PASS (direct=3, indirect=2, negative=3) |
| wrapper_drift / surface_drift | PASS |
| migration_governance | PASS |
| skill_references / unreferenced_files | PASS |
| healthcheck | PASS |
| script compiles (`py_compile`) | PASS |
| benchmark | SKIPPED (live paired run pending) |

Re-run from `/home/ubuntu/.claude/skills/skill-creator-advanced/scripts/` against
`/home/ubuntu/.openclaw/skills/agy-image`.

## Requirement / policy checks

| Check | Status | Notes |
|-------|--------|-------|
| Auth / permissions documented | PASS | No API key; local auth; wrapper injects `--dangerously-skip-permissions`. |
| Output contract specifies format | PASS | Verified size + inline attachment; required response shape. |
| Negative boundary present | PASS | Scoped to agy only; editing/analysis and non-agy generation are out of scope. |
| Default follow-through policy | PASS | Direct vs ask-first vs stop-and-report defined. |
| Sizing policy (exact pixels, not ratio) | PASS | Encoded in prompt composition + presets table. |
| High-risk actions gated | PASS | Publishing / overwriting / large batches require approval. |

## Common error checks

| Check | Status | Notes |
|-------|--------|-------|
| Square (1024x1024) fallback | PASS | `--crop` enforces exact size; troubleshooting documents it. |
| Wrong / near-ratio size | PASS | ffmpeg center-crop + scale to exact pixels. |
| JPEG bytes under `.png` name | PASS | Detector reports true container in `format`. |
| agy not found / unauthenticated | PASS | `failed` status surfaces stdout/stderr tail. |
| Timeout | PASS | `--timeout` (default 12m); buffered output explained. |
| Reference ignored / face drift | PASS | 1–2 front-facing refs; remove facial descriptors. |

## Functional verification (this session)

| Check | Evidence |
|-------|----------|
| Prompt composition | `--dry-run` emits size-lock + reference block + correct deduped `--add-dir` list (output dir + refs dir). |
| Dimension detector (no PIL) | Correctly read 576x1024 PNG, 1024x1536 PNG, 818x1024 PNG, and detected the **JPEG-bytes-under-.png** case (1024x1024 jpeg). |
| ffmpeg size enforce | 1024x1024 jpeg → exact **1024x1280** png via center-crop + scale. |
| End-to-end agy run | Not re-run inside the skill, but the underlying flow (explicit `1024x1536` pixels → native 1024x1536 output) was validated live this session before the skill was authored. |

## Structure / scope

- Single primary job: generate one image via the agy CLI at an exact pixel size,
  optionally identity-locked. Editing/analysis and non-agy image generation are out of
  scope (negative boundary in description + decision_boundary).
- Wrapper is thin: it composes the prompt, runs `agy --print`, verifies, and (optionally)
  enforces size. No new backend, no hidden state in the skill folder.

## Design provenance (why the rules exist)

- agy's image tool defaults to a 1024x1024 square and honours ratio shorthand
  inconsistently; explicit pixel dimensions are reliable. This is the core rule the
  skill encodes (see `agy-cli.md`).
- agy may write JPEG bytes under a `.png` name → detector reports the real container.
- PIL is absent on this host → header-only dimension parsing + ffmpeg for cropping.

## Known limitations / residual risk

- agy is an LLM agent; a single run can still drift on size. `--crop` makes the final
  size deterministic; without it, verify `matched` and re-run if needed.
- A trigger + functional eval set is bundled (`assets/evals/evals.json`, 8 cases). The
  remaining gap is a **live paired benchmark** (with-skill vs baseline) — required to
  promote lifecycle status past `draft`; gated by `assets/evals/regression_gates.json`.
- Live generation depends on local Antigravity auth and account quota; failures surface
  via the script JSON `status: failed` with the agy output tail.

## Final gate

| Gate | Result |
|------|--------|
| `release_gate --stage draft` | PASS |
| Blockers | 0 |
| Stage | draft — publish pending a live paired benchmark |
