# agy-image — Migration Governance

How to evolve this skill without breaking callers (humans, crons, other agents).
The skill's identity surface is its `name` (`agy-image`), its trigger phrases, and
the `scripts/agy_image.py` CLI contract (flags + the stdout JSON shape).

## Rename

- Renaming the skill slug (`agy-image`) or the script changes the public surface.
- Steps: keep the old slug as a thin alias for at least one review cycle; update
  `skill_lifecycle.yaml` `name`, the frontmatter `name`, and every internal path
  reference; announce the new trigger phrases.
- Do not rename the stdout JSON keys (`out`, `requested`, `actual`, `matched`,
  `cropped`, `format`) in the same change as a slug rename — move one surface at a time.

## Deprecate

- Set `skill_lifecycle.yaml` `status: deprecated` and add a deprecation note to
  `SKILL.md` describing the replacement and the removal date.
- Keep the script runnable during the deprecation window so existing crons/agents
  do not break mid-flight.

## Merge

- If a broader image skill absorbs this one, fold agy-specific behavior in as a
  backend/mode rather than deleting it; preserve the exact-pixel + `--crop` contract.
- Migrate the eval set (`assets/evals/evals.json`) into the merged skill so the
  agy trigger and sizing cases keep running.

## Split

- If reference-image identity work grows large, split it into a dedicated
  consistency skill and have this one hand off; keep `--ref/--refs-dir` semantics
  identical across the split so prompts remain portable.

## Compatibility

- Treat the CLI flags and the stdout JSON contract as semver-relevant. Additive
  flags/keys are minor; removing or renaming a flag/key is breaking and requires a
  version bump plus an alias or migration note.
- The `--out` path, `--width`/`--height` semantics, and "exact pixels, no square
  fallback" rule must stay stable; callers depend on them.

## Migration Evidence

- Any rename/deprecate/merge/split must update `references/readiness_report.md` with
  the change, re-run the SkillOps stage gates and `scripts/test_agy_image.py`, and (for
  status past draft) attach a fresh paired benchmark. Record the before/after slug,
  date, and gate results here when a migration actually happens.

## Change log of the CLI contract

### 2026.10.20 (from 2026.5.30, commit 46186a6)

No rename, merge or split; slug and script path unchanged.

Additive (minor): flags `--overwrite`, `--wait-seconds`, `--brain-dir`,
`--allow-agy-permissions`; JSON keys `status` on success, `converted`, `source`,
`brain_source`, `conversation_id`, `elapsed_seconds`, and on failure `error_kind`,
`hint`, `agy_exit_code`, `agy_status`. Existing keys (`out`, `requested`, `actual`,
`matched`, `cropped`, `format`, `agy_report`) keep their meaning.

Behaviour changes callers may notice:

| Change | Why | Caller migration |
|---|---|---|
| An existing `--out` is refused (`error_kind: out_exists`) unless `--overwrite` is passed. | The old script overwrote silently and could report a stale file as the new result. | Crons that reuse one file name add `--overwrite`. |
| The output is re-encoded to the container `--out` names when ffmpeg is present. | agy delivers JPEG bytes; the contract promises a PNG for `.png` paths. | None; `format` now matches the suffix. |
| agy runs from a fresh empty temp folder, not the caller's cwd. | Inside a repo agy opened `.agents/skills` and print mode denied the read. | None. |
| agy is called with `--output-format json`. | The JSON names the conversation whose brain folder holds the image. | Needs agy with `--output-format` (any 1.2.x or later). |
| A run can take up to `--wait-seconds` (240 s) longer before reporting `no_output`. | agy's image subagent often saves after print mode returns. | Raise host timeouts to about 10 minutes, or pass a smaller `--wait-seconds`. |
| The Linux wrapper's implicit `--dangerously-skip-permissions` is no longer assumed. | Windows agy has no wrapper; bypass is now an explicit opt-in. | Pass `--allow-agy-permissions` only with the user's approval. |

Rollback: `git revert` the 2026.10.20 commit, or check out commit `46186a6` in the
skill folder. Compatibility window: none needed for additive keys; the `--overwrite`
requirement is documented here and in `SKILL.md`.
