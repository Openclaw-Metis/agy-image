# agy-image — Readiness Report (release evidence)

Skill version: 0.1.0
Audit date: 2026-05-30
Author: built via skill-creator-advanced, modeled on `krea-nano-banana-2`.

## Mechanical gate results

| Gate | Command | Result |
|------|---------|--------|
| Format lint | `format_check.py agy-image` | PASS (0 errors, 0 warnings) |
| OpenClaw frontmatter | `audit_openclaw_frontmatter.py agy-image` | PASS (0 issues) |
| Semantic structure | `audit_structure.py agy-image --json` | PASS |
| Reference integrity | `audit_skill_references.py agy-image --json` | PASS (all local paths resolve) |
| Unreferenced files | `audit_unreferenced_files.py agy-image --json` | PASS (4 source / 4 referenced) |
| Script compiles | `python3 -m py_compile scripts/agy_image.py` | PASS |

Re-run from `/home/ubuntu/.claude/skills/skill-creator-advanced/scripts/` against
`/home/ubuntu/.openclaw/skills/agy-image`.

## Requirement / policy checks

| Check | Status | Notes |
|-------|--------|-------|
| Auth / permissions documented | PASS | No API key; local auth; wrapper injects `--dangerously-skip-permissions`. |
| Output contract specifies format | PASS | Verified size + inline attachment; required response shape. |
| Negative boundary present | PASS | Hands off Krea generation to `krea-nano-banana-2` / `krea-z-image`. |
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
  optionally identity-locked. Krea generation is explicitly handed off to
  `krea-nano-banana-2` / `krea-z-image` (negative boundary in description + decision_boundary).
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
- No automated trigger/functional eval set is bundled yet (`assets/evals/`). Add paired
  with-skill/baseline trigger evals before promoting past draft.
- Live generation depends on local Antigravity auth and account quota; failures surface
  via the script JSON `status: failed` with the agy output tail.

## Final gate

| Gate | Result |
|------|--------|
| Format / frontmatter / structure / references / unreferenced | PASS |
| Blockers | 0 |
| Stage | draft (eval set pending for publish) |
