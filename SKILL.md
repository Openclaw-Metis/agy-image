---
name: agy-image
description: "Generate images locally with the agy (Antigravity) CLI in print mode — reliable exact-pixel sizing, recovery of images agy leaves in its brain folder, and optional character-reference consistency. Use when the user asks to make an image with agy or Antigravity — 觸發: 'agy 生圖', '用 agy 生成圖片', '用 antigravity cli 生圖', 'agy 畫一張圖', 'antigravity 出圖', '用 agy 跑張圖'. Not for: editing or analysing an existing image, or non-agy image generation. Output: a PNG at the exact requested pixel size, dimensions verified, attached inline."
version: 2026.10.20
homepage: https://github.com/Openclaw-Metis/agy-image
license: MIT
metadata: {"author":"Openclaw-Metis","language":"en","category":"image-generation","short-description":"Exact-pixel image generation through the local agy (Antigravity) CLI, with brain-folder recovery","openclaw":{"requires":{"bins":["agy"]}}}
---

# Agy Image (Antigravity CLI)

Generate images on the local machine by driving the **agy (Antigravity) CLI** in
print mode. No API key and no usage credits — agy authenticates locally and uses
the Antigravity/Gemini account quota.

<role>
You are an image-generation operator for the agy (Antigravity) CLI. Turn a creative
brief into a correctly sized, optionally identity-consistent PNG: resolve exact pixels,
run the wrapper script, read its JSON, and deliver only the verified file; when the run
fails, report the failure kind and next step instead of an image. You own sizing
reliability, output recovery and dimension verification; for any other image backend,
hand the request back to the user or to that backend's skill.
</role>

<decision_boundary>
Use when:
- The user asks to generate an image *with agy / Antigravity* (e.g. "用 agy 生圖", "agy 畫一張").
- The user wants on-machine generation with an exact pixel size, or character
  consistency from local reference images, via agy.

Route elsewhere when:
- The task is editing or analysing an existing image, or image generation with a
  different tool (Midjourney, Codex, Krea, …): leave this skill unused and let the
  matching skill or tool handle it.

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
  --out ~/agy_images/onsen.png \
  --crop
```

On Windows call `python` instead of `python3`. The script composes a size-locked
prompt, runs `agy --print --output-format json` from a fresh empty folder, waits for
the image (agy's `image-generator` subagent often finishes after print mode returns
and saves into `~/.gemini/antigravity-cli/brain/`), copies it to `--out`, re-encodes it
to the container `--out` names, verifies the pixels, and prints one JSON object:
`{ status, out, requested, actual, matched, cropped, converted, format, source, brain_source, conversation_id, agy_report }`.

## Why this skill exists — the sizing trap and the brain folder

agy's image tool defaults to a **1024x1024 square** canvas, and aspect-ratio shorthand
in the prompt ("ar 4:5", "9:16") is honoured inconsistently. The reliable lever is to
demand **exact pixel dimensions**, forbid the square fallback, and verify. Since agy
1.2.16 the image also tends to land in the brain folder instead of `--out`, so a naive
wrapper reports failure for an image that exists. The CLI behaviour behind both rules
is documented in the [agy CLI reference](references/agy-cli.md).

## Sizing presets (translate a ratio to exact pixels)

agy is reliable with explicit `--width`/`--height`, not ratios. Common targets:

| Ratio | Use case | Pixels (`--width --height`) |
|-------|----------|------------------------------|
| 9:16  | Stories / reels, full-screen portrait | `1024 1536` (or `576 1024`) |
| 4:5   | IG feed portrait (recommended)        | `1024 1280` |
| 2:3   | Tall portrait                          | `1024 1536` |
| 1:1   | Square feed post                       | `1024 1024` |
| 3:4   | Portrait                               | `1024 1365` |
| 16:9  | Landscape / banner / video plate       | `1536 864` or `1920 1080` |

If the user gives only a ratio, pick the matching row, state the pixels you chose,
then generate. agy often renders its own native size (16:9 came back as 1376x768),
so pass `--crop` whenever the exact size matters; it center-crops and scales.

<workflow>
Step 0: Confirm request and resolve sizing
- Action: Confirm the brief is an agy image job; resolve the target to exact
  `--width`/`--height` pixels using the presets table; pick an output path under a
  writable folder (default `~/agy_images/<short-slug>.png`).
- Input: User prompt, any ratio or size, optional reference image paths.
- Output: Concrete width, height, out path, and the list of reference paths (if any).
- Validation: Width and height are positive integers; if the user gave only a ratio,
  state the chosen pixels back before running. If the out path already exists, ask the
  user whether to replace it (then add `--overwrite`) or choose a new file name.

Step 1: Compose the prompt and references
- Action: Pass the creative brief as `--prompt`; for identity lock add each local
  reference with `--ref` (and `--refs-dir` for the folder) plus a short `--subject-anchor`.
  The script forbids the square fallback, tells agy to run nothing else, and hands the
  reference paths straight to the image tool.
- Input: Scene description, reference image paths, subject anchor.
- Output: A ready script invocation; optionally inspect it first with `--dry-run` (no quota).
- Validation: With references, describe only scene, wardrobe, lighting, mood and pose, and
  leave face, ethnicity, skin tone and existing hair to the reference; the rules are in the [prompt and identity guide](references/prompt-guide.md).

Step 2: Generate via the wrapper script
- Action: Run the resolved command through the [agy_image.py wrapper script](scripts/agy_image.py)
  with `--crop`. A run takes about 2–4 minutes plus up to `--wait-seconds` (240 s) of
  polling, so start it as a background job when the host's command timeout is shorter
  than 10 minutes. Run images one at a time, or at most three in parallel with distinct
  `--out` names. If the command itself errors or the host kills it, report that and
  re-run once; do not describe an image you have not verified.
- Input: The composed invocation from Step 1.
- Output: A single JSON object on stdout and an image at `--out`.
- Validation: The process exits and stdout parses as JSON with a `status` field.

Step 3: Read the JSON and verify or recover
- Action: On `completed`, check `matched`; if it is false, re-run the same command with
  `--crop` and `--overwrite`, and if it still does not match, stop and report the actual
  size. On `failed`, act on `error_kind` with the table below and quote
  `agy_stdout_tail` / `agy_stderr_tail`; per-kind detail is in the [troubleshooting guide](references/troubleshooting.md).
- Input: The script's JSON result.
- Output: A confirmed file whose dimensions equal the request, or a reported failure.
- Validation: `matched` is true and `actual` equals `requested`; a failure report names
  the `error_kind` and the next step.

Step 4: Present the result
- Action: Deliver per the Output contract — attach the file inline and state the actual
  pixel size; on chat hosts such as Discord, reply to the requester with the file attached.
- Input: The verified PNG and its actual dimensions.
- Output: An inline image plus a one-line size/consistency summary.
- Validation: The attachment renders and the stated size matches the JSON `actual` field.
</workflow>

### Failure handling by `error_kind`

| `error_kind` | Next action |
|---|---|
| `out_exists` | `--out` is no-clobber by default. Ask the user to approve replacing the file (`--overwrite`) or give a new `--out`. |
| `quota_exhausted` | Stop generating; tell the user the image quota is used up and when it resets if agy said so. |
| `permission_denied` | Ask the user to allow the denied tool (agy settings allow-rule, or `--allow-agy-permissions` for this one run); without approval, offer to retry without `--ref`. |
| `timeout` | Retry once with a longer `--timeout`; if it fails again, report it. |
| `no_output` / `agy_error` | Retry once with a simpler prompt; if it fails again, report the agy tail. |
| `auth_required` / `agy_missing` | Ask the user to sign in to agy interactively or install it, then stop. |
| `refs_missing` / `bad_size` / `bad_timeout` | Fix the argument and re-run; nothing was sent to agy. |

## Output contract

When the script completes, always do **both**:

1. **State the actual pixel size** (`{actual.width}x{actual.height}`) and whether it was
   cropped to fit.
2. **Attach the PNG inline** so it renders in chat. If the host cannot attach files,
   give the absolute path and say so.

Required response shape:

```
Image generated with agy.
- Size: {actual.width}x{actual.height} (requested {requested.width}x{requested.height})
- Reference-locked: yes/no
[attached: ~/agy_images/out.png]
```

Take every stated size from the JSON `actual` field; when `actual` is null, say the size
could not be verified instead of quoting the request.

<output_contract>
Deliverables, in order:
1. Result line: completed / failed.
2. Size line: actual `WxH` vs requested `WxH`, and whether it was cropped.
3. The inline attachment (or absolute path + reason if attachment is unsupported).
4. One line on identity consistency when references were used.

Rules: report the size from the script JSON `actual` field and nothing else; if `status`
is `failed`, write "failed", name the `error_kind`, quote the agy tail, and give the next
action from the failure table instead of presenting any image.
</output_contract>

<default_follow_through_policy>
- Directly do: compose the prompt, run the wrapper script, recover the image from the
  brain folder, verify dimensions, crop to exact size with ffmpeg, and attach the result.
  These are local and reversible; when any of them fails, follow the failure table.
- Ask first: replacing an existing file (`--overwrite`), passing `--allow-agy-permissions`
  (it lets agy approve its own tool calls for that run), publishing the image anywhere,
  or a batch of more than three images (the native image quota is roughly ten images
  per five-hour window).
- Stop and report: agy missing or signed out, `quota_exhausted`, a second failure of the
  same request, references not found, or output that cannot be sized even after ffmpeg.
</default_follow_through_policy>

## Character consistency (reference images)

Pass one or two clear, front-facing local references via `--ref` (repeatable) plus
`--refs-dir` for the folder. The reference owns the face; the prompt owns scene, wardrobe,
lighting, mood, and pose. Keep `--subject-anchor` short and identical across a series, and
vary only scene/wardrobe/lighting. Some agy builds deny the reference read in print mode
(`permission_denied`); handle that with the failure table above. Full rules and failure
modes are in the [prompt and identity guide](references/prompt-guide.md).

<examples>
Example 1 — exact-size portrait
Input: "用 agy 生一張 9:16 的夜景人像。"
Output:
- Resolve 9:16 to `--width 1024 --height 1536`, out `~/agy_images/night-portrait.png`.
- Run `agy_image.py --prompt "…night street portrait…" --width 1024 --height 1536 --out … --crop`.
- Report: "Size: 1024x1536 (requested 1024x1536), reference-locked: no" + inline attachment.

Example 2 — identity-locked scene
Input: "用 agy 參考我存的角色圖，生成她在京都和服散步，4:5。"
Output:
- Resolve 4:5 to `1024 1280`; pass `--ref id_shot.png --ref full_body.png --refs-dir <refs>`
  and `--subject-anchor "a young woman"`; prompt describes only scene/wardrobe/lighting.
- Verify `matched: true`; report size + "reference-locked: yes" + inline attachment.

Example 3 — brain-folder recovery
Input: "用 agy 出一張 16:9 的影片背景圖。"
Output:
- Run with `--width 1920 --height 1080 --crop`; JSON shows `source: "brain"`,
  `converted: true`, `actual` 1920x1080: report the verified size and attach the PNG.
</examples>

## Maintenance

- Re-run the fake-agy [regression test suite](scripts/test_agy_image.py) after any change
  to the wrapper; it needs no agy quota and covers every failure in the table above.
- Routing and behaviour cases for revisions live in the [trigger and functional evals](assets/evals/evals.json),
  and promotion past draft is judged by the [benchmark regression gates](assets/evals/regression_gates.json).
- Release checks required before publishing are fixed by the [skill release policy](policies/release_policy.yaml),
  and the commands actually run for each version are recorded in the [readiness report](references/readiness_report.md).
- Rename, deprecate, merge or split only as the [migration governance rules](references/migration-governance.md) describe.
- Status, owner, review dates and dependencies are tracked in the [lifecycle manifest](skill_lifecycle.yaml) (currently `draft`).
