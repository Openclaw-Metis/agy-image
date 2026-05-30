# Troubleshooting — agy image generation

## Output is 1024x1024 square instead of the requested size
- Cause: agy ignored the size for this run (its native canvas is square).
- Fix: re-run with `--crop` so the script center-crops to the target aspect and scales
  to exact pixels with ffmpeg. The composed prompt already forbids the square fallback,
  but a single run can still drift — `--crop` makes the size deterministic.

## Dimensions are close but not exact (e.g. 819x1024 vs 1024x1280)
- Cause: agy produced a near-ratio crop, or ffmpeg rounded to an even dimension.
- Fix: run with `--crop` to force the exact requested `width x height`.

## JSON `format` says "jpeg" but the file is named `.png`
- Expected quirk: agy sometimes writes JPEG bytes under a `.png` name. The image is
  fine; the `format` field reports the true container. Re-encode via ffmpeg/`--crop`
  if you need a real PNG.

## `status: failed` — "agy did not produce the output file"
- Read `agy_stdout_tail` / `agy_stderr_tail` in the JSON.
- Common causes:
  - `agy` not on PATH → ensure `/home/ubuntu/.local/bin` is in PATH, or pass `--agy-bin`.
  - Not authenticated → run agy interactively once to complete local auth.
  - Content moderation → simplify or rephrase the prompt and retry.

## Timeout
- Print mode buffers; image gen can take minutes. Default `--timeout 12m`. Increase it
  (e.g. `--timeout 15m`) for complex prompts. An empty log before timeout is normal.

## Reference image seems ignored (face is generic / wrong)
- Use 1–2 clear front-facing references, not 3+.
- Remove facial descriptors from the prompt so the reference owns the face.
- Confirm the reference paths exist (the script fails fast if any are missing) and that
  their directory was added — pass `--refs-dir`.

## ffmpeg enforce did nothing
- `--crop` needs ffmpeg on PATH. Check `command -v ffmpeg`. Without it, re-run agy with a
  clearer explicit pixel instruction, or crop manually.

## Dry run to inspect before spending quota
- Add `--dry-run` to print the composed prompt, the resolved `--add-dir` list, and the
  command without invoking agy.
