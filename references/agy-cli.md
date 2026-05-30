# agy (Antigravity) CLI — image generation reference

## What agy is

`agy` is Google's Antigravity agentic CLI (Gemini-backed). It is **not** a plain
text-to-image API — it is an LLM agent that, when asked, calls its own image
generation tool, writes the file to disk, and reports back. This skill drives it
non-interactively in **print mode**.

## The wrapper at `/home/ubuntu/.local/bin/agy`

On this machine `agy` is a bash wrapper around the real binary `agy.real`. It:
1. Auto-injects `--dangerously-skip-permissions` (so tool calls are not prompted).
2. Sets a fake `SSH_CONNECTION` if unset (Antigravity's remote capability profile).
3. Optionally wraps in a dbus/keyring session (`AGY_ENABLE_KEYRING_WRAP=1`).

Because of (1) you do **not** pass the danger flag yourself. To opt out, set
`AGY_REQUIRE_PERMISSIONS=1`. No API key is needed; auth is local and generation
uses the Antigravity/Gemini account quota (not Krea credits).

## Print-mode flags used by this skill

| Flag | Purpose |
|------|---------|
| `--print "<prompt>"` | Run a single prompt non-interactively and print the response. |
| `--print-timeout 12m` | Max wait for print mode. Image gen can take minutes. |
| `--add-dir <dir>` | Add a directory to the workspace (repeatable). Used for the output dir and any reference-image dirs so agy can read/write them. |

Print mode **buffers**: the log/stdout stays empty until agy finishes, then prints
the whole response at once. Do not treat an empty log as a hang before the timeout.

## The aspect-ratio trap (the reason this skill exists)

agy's image tool's native canvas is **1024x1024 square**. Putting a ratio in the
prompt is unreliable:

- One 9:16 request: agy self-cropped to **576x1024** (correct).
- A "ar 4:5" request: agy returned **1024x1024** square (ignored the ratio).
- An explicit "**1024 x 1536 pixels, do not output a square**" request: agy returned a
  genuine native **1024x1536** (correct, no stretch, no pad).

**Rule: always specify exact `width x height` pixels and explicitly forbid the
1024x1024 square fallback.** Ratios are for humans; pixels are for agy. The
`agy_image.py` script encodes this in every prompt and then verifies the result.

## Output quirks

- agy sometimes writes **JPEG bytes under a `.png` filename**. The script detects the
  real container from the file header and reports it in the JSON `format` field.
- Generation reports are written under
  `/home/ubuntu/.gemini/antigravity-cli/brain/<id>/generation_report.md`.
- Default working/output area used by this skill: `/home/ubuntu/agy_images/`.

## Verifying / fixing size without PIL

PIL is not installed on this box. The script reads PNG/JPEG/WEBP dimensions from the
file header (stdlib only). To force an exact size when agy drifts, it center-crops to
the target aspect and scales to the exact pixels with **ffmpeg**:

```bash
ffmpeg -y -loglevel error -i in.png -vf "crop=cw:ch:x:y,scale=W:H" out.png
```

`--crop` on the script does this automatically when `actual != requested`.
