# agy-image — Readiness Report (release evidence)

Skill version: 2026.10.20
Audit date: 2026-10-20
Previous version: 2026.5.30 (commit `46186a6`)
Change type: failure-driven revision (SkillOps Studio `evolve`), evidence level E2.
Host for this round: Windows 11, agy 1.4.1, Python 3.13, ffmpeg 9.0.1.

## Common errors fixed in this revision (failure records)

| ID | Class | Observed (source, date) | Fix in 2026.10.20 |
|----|-------|-------------------------|-------------------|
| F1 | tool_contract | Since agy 1.2.16 the image lands in `~/.gemini/antigravity-cli/brain/<conv>/` and print mode can return first; the wrapper printed "agy did not produce the output file" for images that existed (OpenMontage runs 2026-10-10, -12, -13; agy changelog 1.2.16). | `--output-format json` for the conversation id, bounded polling (`--wait-seconds`), brain recovery into `--out`. |
| F2 | resource | agy 1.3.3 started inside a repo opened `.agents/skills`, print mode denied the read, no image (2026-10-12). | agy runs from a fresh empty temp folder. |
| F3 | safety | `--ref` prompt told agy to read the reference; print mode denied `read_file` (2026-10-14). | Reference paths go straight to the image tool; `permission_denied` is classified; bypass is an explicit opt-in. |
| F4 | performance | Native image quota ran out after about ten images; retries burned time (2026-10-14). | `quota_exhausted` classified, short poll budget, stop rule in SKILL.md. |
| F5 | tool_contract | Callers had to set `PYTHONUTF8=1` on Windows (2026-10-10). | The script decodes agy output and writes its own stdout as UTF-8. |
| F6 | tool_contract | No wrapper-side timeout; `--print-timeout` expiry exits 0 (agy changelog). | Subprocess timeout = `--timeout` + 60 s; `timeout` classified. |
| F7 | instruction | Stale `--out` from an earlier run reported as the new result; silent overwrite despite the ask-first policy (code inspection). | `--out` is no-clobber unless `--overwrite`; only files newer than the run count. |
| F8 | instruction | SKILL.md hard-coded `/home/ubuntu` paths and the Linux wrapper's permission injection. | Portable paths; per-host install table in `agy-cli.md`. |

## Commands run and results

| Command | Result |
|---------|--------|
| `python scripts/test_agy_image.py` (2026.10.20) | **18/18 PASS** (fake agy, no quota). |
| `AGY_IMAGE_SCRIPT=<46186a6 agy_image.py> python scripts/test_agy_image.py` | 16 FAIL + 1 ERROR, 1 PASS (re-entry guard): the suite reproduces F1–F7 on the previous version. |
| Live: 1024x1280 portrait, `--crop` (intermediate build) | completed, `source: brain`, agy wrote 896x1200 JPEG and did not write `--out`; cropped to 1024x1280 PNG; 151 s. |
| Live: same size with `--ref` of the first image (intermediate build) | completed, `source: brain`, no permission denial on agy 1.4.1; 896x1200 → 1024x1280 PNG; 203 s. Identity looked consistent by eye (not measured). |
| Live: 1920x1080 plate, `--crop` (final build) | completed, `source: brain` (file named by agy `taiwan_tea_plantation_sunrise_<ts>.jpg`), 1376x768 → 1920x1080 PNG; 79 s; agy's reply claimed 1792x1024, the header said 1376x768. No temp run folder left behind. |
| SkillOps `stage_gate.py --stage evolve --require-security` | PASS |
| SkillOps `stage_gate.py --stage revise --require-security` | PASS |
| SkillOps `release_gate.py --stage publish` | PASS |

Gate details (2026.10.20): format, skill_references, unreferenced_files,
skill_consistency, eval_assets (12 cases; direct/indirect/negative; zh/en/mixed) and
skill_security PASS. Advisory only: instruction_control (no blocking findings);
security warning `output_workspace_boundary_missing` accepted, because the output path
is chosen by the user by design and replacing a file needs `--overwrite` plus approval.
`benchmark` SKIPPED: no frozen live paired benchmark exists.

## Rollback

- Repository: `git revert` the 2026.10.20 commit, or check out `46186a6`.
- Installed copy: before syncing, the installed folder was compared with `46186a6` and
  matched it (line endings aside), so checking out that commit into the skill folder
  returns the old behaviour.
- Contract changes and caller migration are listed in `migration-governance.md`.

## Known limitations / residual risk

- No live paired benchmark (with-skill vs ad-hoc agy), so no quality-improvement claim is
  made and lifecycle stays `draft`.
- `quota_exhausted`, `permission_denied` and `auth_required` are keyword classifications;
  the exact agy wording for an exhausted image quota was not captured this round.
- The permission-denial path for `--ref` was reproduced only with the fake agy; on
  agy 1.4.1 the reference run was not denied.
- agy's main agent can keep running after the image exists; the wrapper waits for it
  instead of stopping it early, because the image-generator may still be retrying.
- agy inherits the caller's full environment (it needs the user's local sign-in).
- This round ran on Windows only; the Linux path is unchanged in design but was not re-run.
