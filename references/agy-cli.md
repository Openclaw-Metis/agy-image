# agy (Antigravity) CLI — image generation reference

Checked against agy 1.2.16 to 1.4.x (`agy --help`, `agy changelog`) and real runs on
Windows 11 and Ubuntu hosts.

## What agy is

`agy` is Google's Antigravity agentic CLI (Gemini-backed). It is **not** a plain
text-to-image API — it is an LLM agent that, when asked, calls its own image
generation tool, writes the file to disk, and reports back. This skill drives it
non-interactively in **print mode**.

Since 1.2.16 the agent hands image requests to a built-in **`image-generator`
subagent**, which writes its own prompt, checks each result (up to three attempts) and
saves the images to the conversation's artifacts. That changes where the file lands
(see "The brain folder" below).

## Install locations

| Host | Binary | Notes |
|------|--------|-------|
| Windows | `%LOCALAPPDATA%\agy\bin\agy.exe` (on PATH) | No wrapper; nothing injects permission flags. |
| Ubuntu (original host) | `~/.local/bin/agy` bash wrapper around `agy.real` | The wrapper injected `--dangerously-skip-permissions`, set a fake `SSH_CONNECTION`, and could wrap a keyring session. |

The skill no longer relies on the Linux wrapper's flag injection: permission bypass is
an explicit, per-run opt-in (`--allow-agy-permissions`).

## Print-mode flags used by this skill

| Flag | Purpose |
|------|---------|
| `--print "<prompt>"` | Run a single prompt non-interactively. Must be the last flag (it takes the prompt as its value). |
| `--print-timeout 12m` | Go-style duration. Default is unlimited (`0s`). When it expires mid-turn agy returns the partial output and **exits 0** with a warning on stderr, so exit code 0 does not mean an image exists. |
| `--output-format json` | One JSON object: `conversation_id`, `status`, `response`, `duration_seconds`, `usage`. The `conversation_id` names the brain folder of the print conversation. |
| `--add-dir <dir>` | Add a directory to the workspace (repeatable). Used for the output dir and any reference-image dirs. |
| `--dangerously-skip-permissions` | Auto-approve every tool call. Only sent when the caller passes `--allow-agy-permissions`. |

Useful read-only checks (no turn, no quota): `agy -p "/quota" --output-format json`
reports the Gemini 5-hour and weekly model quota. The native **image** quota is
separate and is not listed there; when it runs out, runs report it in the response.
Observed: about ten images, then a reset roughly 4h40m later.

## The brain folder

Images are saved under `~/.gemini/antigravity-cli/brain/<conversation-id>/`:

- the print conversation (the `conversation_id` in the JSON output) keeps
  `<name>_<timestamp>.jpg` at its top level. The name usually repeats the requested
  file's stem (`portrait_1792493683545.jpg` for `portrait.png`) but not always
  (`taiwan_tea_plantation_sunrise_1792494138409.jpg` for `plate_169.png`), which is why
  the conversation id, not the name, is the primary key;
- the image-generator subagent's conversation keeps `.tempmediaStorage/media_<timestamp>_<hash>.*`
  copies: the result, and also a copy of every reference image it was handed;
- `.user_uploaded/` holds attachments and is never treated as output.

(Observed on agy 1.4.1, 2026-10-20. Some older notes describe the two folders the other
way round, so the script searches both places.)

Print mode can return while the subagent is still saving, and the main agent does not
copy the file to the requested path when print mode denies it file tools (it usually
says so in its reply). `agy_image.py` therefore polls for up to `--wait-seconds` and
accepts, in order: a fresh `--out`, an image in the print conversation's folder (top
level or `.tempmediaStorage/`), then any new top-level image whose name starts with
`<out-stem>_`. Only files newer than the run start count, which keeps parallel runs
(three at once worked) from taking each other's images, and files byte-identical to a
`--ref` are skipped so a reference copy is never returned as the result.

Timing seen on agy 1.4.1: the image appears about 45–60 s into the run. When agy was
only told to save to `--out`, its main agent then spent another 1.5–2 minutes trying (and
being denied) to copy or convert the file; whole runs took 151 s and 203 s. With the
prompt now saying the wrapper does that work, the next run took 79 s (one sample).

## The aspect-ratio trap

agy's image tool's native canvas is **1024x1024 square**. Putting a ratio in the
prompt is unreliable:

- One 9:16 request: agy self-cropped to **576x1024** (correct).
- A "ar 4:5" request: agy returned **1024x1024** square (ignored the ratio).
- An explicit "**1024 x 1536 pixels, do not output a square**" request: agy returned a
  genuine native **1024x1536** (correct, no stretch, no pad).
- 16:9 plates through the image-generator subagent came back as **1376x768** JPEG.

**Rule: always specify exact `width x height` pixels, forbid the 1024x1024 square
fallback, and pass `--crop` when the exact size matters.** Ratios are for humans;
pixels are for agy.

## Workspace and permissions in print mode

- agy loads `skills.json`, `rules.json` and `.agents/skills` from every `.agents/` folder
  between the working directory and the project root. Started inside a repository it
  tried to open one of those skills, print mode denied the read ("a tool required the
  read_file permission"), and no image was made. The wrapper therefore runs agy from a
  fresh empty temp folder.
- Headless runs soft-deny any tool that needs a confirmation and print a stderr notice
  naming the allow-rule that would permit it; they honour `permissions` in agy's
  `settings.json`. Asking agy to *read* a reference image hits this, so the composed
  prompt hands reference paths straight to the image tool instead.

## Output quirks

- agy usually delivers **JPEG bytes**, sometimes under a `.png` name. The script detects
  the real container from the header and, when ffmpeg is available, re-encodes to the
  container `--out` names (`converted: true`).
- agy's own report of the size is not reliable: one run said "1792 x 1024" for a file
  that was 1376x768. Only the header-read `actual` field counts.

## Verifying / fixing size without PIL

The script reads PNG/JPEG/WEBP dimensions from the file header (stdlib only). To force
an exact size it center-crops to the target aspect and scales with **ffmpeg**:

```bash
ffmpeg -y -loglevel error -i in.jpg -vf "crop=cw:ch:x:y,scale=W:H" -frames:v 1 out.png
```

`--crop` does this automatically when `actual != requested`.
