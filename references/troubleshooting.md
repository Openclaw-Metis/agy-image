# Troubleshooting — agy image generation

Failures arrive as `status: "failed"` with an `error_kind`, a `hint`, and the agy
output tails (`agy_stdout_tail`, `agy_stderr_tail`). Start from the `error_kind`.

## `no_output` — "agy did not produce the output file"
- The script already polled `--out` and the brain folder for `--wait-seconds`
  (default 240 s). If you know agy is slow today, retry once with `--wait-seconds 420`.
- Check the brain folder by hand: `~/.gemini/antigravity-cli/brain/<conversation_id>/`
  (the id is in the JSON) and its `.tempmediaStorage/`. A file there that is newer than
  the run means the stem or timing did not match; copy it and report.
- Content moderation: simplify or rephrase the prompt and retry once.

## `quota_exhausted`
- The native image quota is used up (about ten images, reset roughly 4h40m later).
  Retrying burns time and fails the same way. Stop, tell the user, and give the reset
  time if agy printed one. `agy -p "/quota" --output-format json` shows the model
  quota only, not the image quota.

## `permission_denied`
- Print mode soft-denied a tool call and named the allow-rule on stderr (quoted in
  `agy_stderr_tail`). With `--ref`, the usual cause is agy trying to read the reference.
- Options, all needing the user's approval: add that allow-rule to agy's
  `settings.json` permissions; or pass `--allow-agy-permissions` for this one run; or
  retry without `--ref`.

## `timeout`
- agy did not finish within `--timeout` plus a 60 s grace and was stopped. Retry once
  with a longer `--timeout` (e.g. `20m`). Repeated timeouts usually mean quota or
  service trouble: check `/quota`.

## `agy_error`, `auth_required`, `agy_missing`
- `agy_error`: agy exited non-zero; read `agy_stderr_tail`.
- `auth_required`: run `agy` interactively once to sign in.
- `agy_missing`: install agy, or pass `--agy-bin` with the full path
  (Windows: `%LOCALAPPDATA%\agy\bin\agy.exe`).

## `out_exists`
- The target file is already there. Ask the user before replacing it, then re-run with
  `--overwrite`, or choose another `--out`. A stale file is never reported as a result:
  only files written after the run started count.

## `reentry`
- The script was started inside an agy run (`AGY_IMAGE_DEPTH` set). The inner agent must
  use its native image tool instead of calling the wrapper again.

## Output is 1024x1024 square, or close but not exact (e.g. 1376x768 for 1920x1080)
- agy ignored the size or used its native canvas. Re-run with `--crop` (and
  `--overwrite`): the script center-crops to the target aspect and scales to exact pixels.

## JSON `format` is "jpeg" for a `.png` path, or `warning` mentions ffmpeg
- ffmpeg is missing, so the JPEG bytes were kept. Install ffmpeg (or put it on PATH)
  and re-run; with ffmpeg the file is re-encoded and `converted` is true.

## Reference image seems ignored (face is generic / wrong)
- Use 1–2 clear front-facing references, not 3+.
- Remove facial descriptors from the prompt so the reference owns the face.
- Confirm the reference paths exist (the script fails fast with `refs_missing`) and pass
  `--refs-dir` so their folder is in agy's workspace.

## Windows console shows garbled characters
- The script writes UTF-8 to stdout/stderr itself. If a caller still decodes with the
  ANSI code page, read the output as UTF-8 or run Python with `-X utf8`.

## Dry run to inspect before spending quota
- Add `--dry-run` to print the composed prompt, the resolved `--add-dir` list, and the
  command without invoking agy.
