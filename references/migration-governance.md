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
  the change, re-run the skill-creator gates, and (for status past draft) attach a
  fresh paired benchmark. Record the before/after slug, date, and gate results here
  when a migration actually happens.
