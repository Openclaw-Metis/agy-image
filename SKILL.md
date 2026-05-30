---
name: agy-image
description: "Generate images locally with the agy (Antigravity) CLI in print mode — reliable exact-pixel sizing plus optional character-reference consistency. Use when the user asks to make an image with agy or Antigravity — 觸發: 'agy 生圖', '用 agy 生成圖片', '用 antigravity cli 生圖', 'agy 畫一張圖', 'antigravity 出圖', '用 agy 跑張圖'. Not for: editing or analysing an existing image, or non-agy image generation. Output: a PNG at the exact requested pixel size, dimensions verified, attached inline."
version: 2026.5.30
homepage: https://antigravity.google
license: MIT
metadata: { "openclaw": { "primaryEnv": "" } }
---

# Agy Image (Antigravity CLI)

Generate images on the local machine by driving the **agy (Antigravity) CLI** in
print mode. No API key and no usage credits — agy authenticates locally and uses
the Antigravity/Gemini account quota.

<role>
You are an image-generation operator for the agy (Antigravity) CLI. Your job is to
turn a creative brief into a correctly sized, optionally identity-consistent PNG by
composing a disciplined agy prompt, running it through the wrapper script, and
verifying the real output before delivery. You own sizing reliability and dimension
verification; you do not invent new generation backends.
</role>

<decision_boundary>
Use when:
- The user asks to generate an image *with agy / Antigravity* (e.g. "用 agy 生圖", "agy 畫一張").
- The user wants on-machine generation with an exact pixel size, or character
  consistency from local reference images, via agy.

Do not use when:
- The task is editing or analysing an existing image, or any non-agy image
  generation (a different/dedicated image backend should handle those).

Inputs:
- A scene/subject prompt; target pixel size (or a ratio to translate to pixels);
  optional local reference image paths for identity lock; output path.

Successful output:
- A PNG saved at the requested path whose verified dimensions equal the request
  (after ffmpeg enforcement if needed), presented inline with its actual size.
</decision_boundary>

## Quick start

```bash
python3 {baseDir}/scripts/agy_image.py \
  --prompt "a young woman soaking in a Japanese open-air onsen at night, folded towel on her head, steam rising, stone lantern, maple leaves, ryokan glow, photorealistic, shallow depth of field" \
  --width 1024 --height 1536 \
  --out /home/ubuntu/agy_images/out.png \
  --crop
```

The script composes a size-locked agy prompt, runs `agy --print` (adding the output
and reference directories to the workspace), then verifies the real dimensions.
Stdout is a single JSON object: `{ out, requested, actual, matched, cropped, format, agy_report }`.

## Why this skill exists — the sizing trap

agy's image tool defaults to a **1024x1024 square** canvas. Aspect-ratio shorthand
in the prompt ("ar 4:5", "9:16", "比例 4:5") is honoured **inconsistently** — one run
self-cropped to 576x1024 (9:16), another ignored "ar 4:5" and returned a 1024x1024
square. The reliable lever is to demand **exact pixel dimensions** and explicitly
forbid the square fallback. The script bakes this into every prompt and then verifies.
See `references/agy-cli.md`.

## Sizing presets (translate a ratio to exact pixels)

agy is reliable with explicit `--width`/`--height`, not ratios. Common targets:

| Ratio | Use case | Pixels (`--width --height`) |
|-------|----------|------------------------------|
| 9:16  | Stories / reels, full-screen portrait | `1024 1536` (or `576 1024`) |
| 4:5   | IG feed portrait (recommended)        | `1024 1280` |
| 2:3   | Tall portrait                          | `1024 1536` |
| 1:1   | Square feed post                       | `1024 1024` |
| 3:4   | Portrait                               | `1024 1365` |
| 16:9  | Landscape / banner                     | `1536 864` |

If the user gives only a ratio, pick the matching row, state the pixels you chose,
then generate.

<workflow>
Step 0: Confirm request and resolve sizing
- Action: Confirm the brief is an agy image job; resolve the target to exact
  `--width`/`--height` pixels using the presets table; pick an output path under a
  writable dir (default `/home/ubuntu/agy_images/`).
- Input: User prompt, any ratio or size, optional reference image paths.
- Output: Concrete width, height, out path, and the list of reference paths (if any).
- Validation: Width and height are positive integers; if the user gave only a ratio,
  state the chosen pixels back before running.

Step 1: Compose the prompt and references
- Action: Pass the creative brief as `--prompt`; for identity lock add each local
  reference with `--ref` (and `--refs-dir` for the folder) and an optional
  `--subject-anchor`. The script forbids the square fallback and tells agy the
  reference owns the face while the prompt owns scene, wardrobe, lighting, and pose.
- Input: Scene description, reference image paths, subject anchor.
- Output: A ready script invocation; optionally inspect it first with `--dry-run`.
- Validation: With references, the prompt must not restate facial features, ethnicity,
  skin tone, or existing hair details (let the reference own them) —
  see `references/prompt-guide.md`.

Step 2: Generate via the wrapper script
- Action: Run `scripts/agy_image.py` with the resolved flags; add `--crop` to guarantee
  exact size. Print mode buffers output, so allow several minutes (`--timeout`, default 12m).
- Input: The composed invocation from Step 1.
- Output: A single JSON object on stdout and a PNG at `--out`.
- Validation: JSON `status` is `completed` and the out file exists; on `failed`, **stop and
  report** the agy tail (`agy_stdout_tail` / `agy_stderr_tail`) instead of fabricating an
  image, and consult `references/troubleshooting.md`.

Step 3: Verify dimensions and enforce size
- Action: Read JSON `actual` vs `requested`. If `matched` is false and `--crop` was not
  used, either re-run with `--crop` or center-crop manually; the script reports the real
  container in `format` (agy sometimes writes JPEG bytes under a `.png` name).
- Input: The script's JSON result.
- Output: A confirmed file whose dimensions equal the request.
- Validation: `matched` is true (directly, or after `cropped` is true).

Step 4: Present the result
- Action: Deliver per the Output contract — attach the file inline and state the actual
  pixel size; if delivering on Discord, @mention the requester.
- Input: The verified PNG and its actual dimensions.
- Output: An inline image plus a one-line size/consistency summary.
- Validation: The attachment renders and the stated size matches the file on disk.
</workflow>

## Output contract

When the script completes, always do **both**:

1. **State the actual pixel size** (`{actual.width}x{actual.height}`) and whether it was
   cropped to fit.
2. **Attach the PNG inline** so it renders in chat (Discord reply `files`, etc.). If the
   surface cannot attach files, give the absolute path and say so.

Required response shape:

```
Image generated with agy.
- Size: {actual.width}x{actual.height} (requested {requested.width}x{requested.height})
- Reference-locked: yes/no
[attached: /home/ubuntu/agy_images/out.png]
```

Never claim a size you did not verify from the JSON `actual` field.

<output_contract>
Deliverables, in order:
1. Result line: completed / failed.
2. Size line: actual `WxH` vs requested `WxH`, and whether it was cropped.
3. The inline attachment (or absolute path + reason if attachment is unsupported).
4. One line on identity consistency when references were used.

Rules: report only the verified `actual` size from the script JSON; never assert an
unverified dimension; if `status` is `failed`, say so and quote the agy tail, do not
fabricate an image.
</output_contract>

<default_follow_through_policy>
- Directly do: compose the prompt, run `scripts/agy_image.py`, verify dimensions, crop to
  exact size with ffmpeg, and attach the result. These are local, reversible, no external
  side effects.
- Ask first: publishing the image anywhere (Instagram, posting to a channel the user did
  not ask for), overwriting an existing user file, or generating large batches that burn
  significant quota.
- Stop and report: agy missing or unauthenticated, repeated `failed` status, references
  not found, or output that cannot be sized even after ffmpeg.
</default_follow_through_policy>

## Character consistency (reference images)

Pass one or two clear, front-facing local references via `--ref` (repeatable) plus
`--refs-dir` for the folder. The reference owns the face; the prompt owns scene, wardrobe,
lighting, mood, and pose. Keep `--subject-anchor` short and identical across a series, and
vary only scene/wardrobe/lighting. Full rules and failure modes: `references/prompt-guide.md`.

## Error handling

If `status` is `failed`, or the size never matches, consult
`references/troubleshooting.md` (square output, wrong size, JPEG-under-png, agy not found,
auth, timeout, reference ignored).

<examples>
Example 1 — exact-size portrait
Input: "用 agy 生一張 9:16 的夜景人像。"
Output:
- Resolve 9:16 to `--width 1024 --height 1536`, out `/home/ubuntu/agy_images/portrait.png`.
- Run `agy_image.py --prompt "…night street portrait…" --width 1024 --height 1536 --out … --crop`.
- Report: "Size: 1024x1536 (requested 1024x1536), reference-locked: no" + inline attachment.

Example 2 — identity-locked scene
Input: "用 agy 參考我存的角色圖，生成她在京都和服散步，4:5。"
Output:
- Resolve 4:5 to `1024 1280`; pass `--ref id_shot.png --ref full_body.png --refs-dir <refs>`
  and `--subject-anchor "a young woman"`; prompt describes only scene/wardrobe/lighting.
- Verify `matched: true`; report size + "reference-locked: yes" + inline attachment.
</examples>

## Scripts

- `scripts/agy_image.py` — composes a size-locked agy prompt, runs `agy --print` with
  `--add-dir` for output + reference dirs, verifies dimensions, and optionally enforces
  exact size with ffmpeg. Stdout is a single JSON object.

## References

- `references/agy-cli.md` — agy print-mode flags, `--add-dir`, the danger-flag wrapper,
  the aspect-ratio trap, JPEG-under-png note, and where generation reports land.
- `references/prompt-guide.md` — prompt writing and identity-lock rules for reference images.
- `references/troubleshooting.md` — failure modes and fixes.
- `references/readiness_report.md` — release evidence for this skill.
- `references/migration-governance.md` — rename / deprecate / merge / split governance.

## Evals & lifecycle

- `assets/evals/evals.json` — trigger + functional eval set (direct / indirect / negative,
  zh / en / mixed) used to check routing and behavior across revisions.
- `assets/evals/regression_gates.json` — benchmark regression gates for promotion past draft.
- Lifecycle state (status, owner, review cadence, dependencies) is tracked in
  `skill_lifecycle.yaml` — currently `draft`.
