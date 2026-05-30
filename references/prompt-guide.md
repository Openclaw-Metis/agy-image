# Prompt guide for agy image generation

## Basics

Write a descriptive prompt (English, Chinese, or mixed). agy's Gemini image tool does
well with photorealistic scenes. A good prompt covers:

- **Subject** — what/who is in the frame.
- **Style** — photorealistic, editorial, cinematic, film look, etc.
- **Lighting / mood** — night, golden hour, strong flash (CCD look), soft daylight.
- **Composition** — close-up, upper-body, full body, wide shot, shallow depth of field.

Put the most important elements first. Add realism cues that worked well here:
real skin texture, natural hair strands with flyaways, real props, real environment.

## Sizing is separate from the prompt

Do **not** rely on "ar 4:5" inside the creative text — agy honours it inconsistently.
Always set the size with the script's `--width`/`--height`. See `agy-cli.md`.

## Identity preservation with reference images

Use `--ref <path>` (repeatable) plus `--refs-dir <dir>` when the goal is the **same
person** across scenes. Core rule:

> The reference owns the face. The prompt owns scene, wardrobe, lighting, mood, pose.

### Include in the prompt
- Scene and environment
- Clothing and accessories
- Lighting and mood
- Composition / pose
- A short subject anchor, e.g. `a young woman`

### Leave out of the prompt
- Facial features, ethnicity, skin tone
- Age markers (unless intentionally changing age)
- Hair details that already exist in the reference

### Reference selection
- Prefer 1–2 clear, front-facing, well-lit references.
- Avoid 3+ references — they average features and weaken the identity lock.
- Keep the face unobstructed (no sunglasses, masks, large hats, heavy bangs).

### Multi-scene series
Lock these across the whole series and vary only scene/wardrobe/lighting/pose:
- same `--ref` set
- same `--subject-anchor` text
- same `--width`/`--height`

Generate one image at a time and compare each result to the reference. If facial
structure, skin tone, or age drift, fix the prompt (usually by removing a facial
descriptor) before continuing.

### Failure modes

| Symptom | Fix |
|---------|-----|
| Face changes between scenes | Remove facial descriptors; let the reference own the face. |
| Identity averages out | Use 1–2 refs max, front-facing, well-lit. |
| Attribute drift | Do not restate ethnicity, skin tone, age, or hair unless changing them. |
| Series inconsistency | Keep anchor text and pixel size identical across the series. |
| Face hallucinated | Do not occlude the face (sunglasses, masks, big hats, heavy bangs). |

## Worked example

```bash
python3 {baseDir}/scripts/agy_image.py \
  --prompt "soaking in a Japanese open-air onsen at night, folded white towel on her head, hair up, relaxed smile, steam rising, stone lantern, maple leaves, ryokan lights, real skin texture, shallow depth of field" \
  --ref /path/refs/id_shot.png --ref /path/refs/full_body.png \
  --refs-dir /path/refs \
  --subject-anchor "a young woman" \
  --width 1024 --height 1280 \
  --out /home/ubuntu/agy_images/onsen.png --crop
```
