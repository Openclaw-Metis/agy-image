#!/usr/bin/env python3
"""Generate an image via the agy (Antigravity) CLI in print mode.

This is a thin, deterministic wrapper around `agy --print`. The agy CLI is an
agentic assistant whose image tool defaults to a 1024x1024 square canvas and
honours *aspect-ratio shorthand* ("4:5", "9:16") only inconsistently. The
reliable lever is to demand **exact pixel dimensions** and forbid the square
fallback — this script bakes that into the composed prompt, then verifies the
real output dimensions and (optionally) enforces the exact size with ffmpeg.

Prints a single JSON object to stdout:
{
  "out": "/abs/path.png",
  "requested": {"width": 1024, "height": 1536},
  "actual":    {"width": 1024, "height": 1536},
  "matched": true,
  "cropped": false,
  "format": "png",
  "agy_report": "…last line agy printed…"
}

Auth / permissions:
  No API key. agy authenticates locally; the `agy` wrapper auto-injects
  `--dangerously-skip-permissions`. Generation consumes the local
  Antigravity/Gemini account quota (no API key, no usage credits).

Notes:
  - agy sometimes writes JPEG bytes under a `.png` name; "format" reports the
    real container detected from the file header.
  - Print mode buffers output: nothing is printed until agy finishes, so a
    generous --timeout (default 12m) is expected.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Image header parsing (no PIL dependency)                                     #
# --------------------------------------------------------------------------- #
def _png_size(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _jpeg_size(path: pathlib.Path) -> Optional[Tuple[int, int]]:
    with path.open("rb") as fh:
        if fh.read(2) != b"\xff\xd8":
            return None
        while True:
            marker = fh.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                return None
            code = marker[1]
            # Standalone markers without a length payload.
            if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
                continue
            length_bytes = fh.read(2)
            if len(length_bytes) < 2:
                return None
            length = struct.unpack(">H", length_bytes)[0]
            # SOF0..SOF15 (excluding DHT 0xC4, DAC 0xCC) carry dimensions.
            if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                payload = fh.read(5)
                if len(payload) < 5:
                    return None
                height, width = struct.unpack(">HH", payload[1:5])
                return width, height
            fh.seek(length - 2, os.SEEK_CUR)


def _webp_size(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    fmt = data[12:16]
    if fmt == b"VP8 ":
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return w, h
    if fmt == b"VP8L":
        b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
        w = ((b1 & 0x3F) << 8 | b0) + 1
        h = ((b3 & 0x0F) << 10 | b2 << 2 | (b1 & 0xC0) >> 6) + 1
        return w, h
    if fmt == b"VP8X":
        w = (data[24] | data[25] << 8 | data[26] << 16) + 1
        h = (data[27] | data[28] << 8 | data[29] << 16) + 1
        return w, h
    return None


def detect_image(path: pathlib.Path) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
    """Return (format, (width, height)) reading only the file header."""
    try:
        head = path.read_bytes()[:64]
    except OSError:
        return None, None
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", _png_size(head)
    if head[:2] == b"\xff\xd8":
        return "jpeg", _jpeg_size(path)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp", _webp_size(head)
    return None, None


# --------------------------------------------------------------------------- #
# Prompt composition                                                           #
# --------------------------------------------------------------------------- #
def compose_prompt(
    *,
    out_path: str,
    width: int,
    height: int,
    scene: str,
    refs: List[str],
    subject_anchor: Optional[str],
) -> str:
    lines: List[str] = []
    lines.append(
        "請使用你的圖片生成工具生成一張圖片，並把成品存成 PNG 檔到："
        f"\n{out_path}"
    )
    lines.append(
        "\n【重要｜輸出尺寸 / CRITICAL OUTPUT SIZE】\n"
        f"成品必須是精確的 {width} x {height} 像素（寬 {width}、高 {height}）。"
        f"The result MUST be exactly {width} x {height} pixels (width {width}, "
        f"height {height}). 不要輸出 1024x1024 方圖，也不要把方圖補邊或拉伸成這個尺寸。"
        " Do NOT output a 1024x1024 square, and do not pad or upscale a square "
        "to reach this size."
    )
    lines.append(
        "\n【執行紀律｜EXECUTION DISCIPLINE — 必讀】\n"
        "你（agy）就是圖片生成器本身。請『直接』用你內建的圖片生成工具 "
        "(your built-in generate_image tool) 產生這張圖並存成上面的 PNG 路徑。"
        " 嚴禁執行任何 shell 指令、python 腳本、`agy_image.py`，也不要呼叫或載入 "
        "`agy-image` skill 或再開一個 agy/Antigravity session 來生圖。"
        " Do NOT run any shell command, python script, agy_image.py, or the "
        "agy-image skill, and do NOT spawn another agy session — generate the "
        "image yourself with your native image tool. 做完直接回報路徑與尺寸即可。"
    )
    if refs:
        ref_block = "\n".join(f"- {r}" for r in refs)
        anchor = subject_anchor or "參考圖中的同一個人 / the same person as in the references"
        lines.append(
            "\n【角色參考圖 / CHARACTER REFERENCE】請先讀取以下參考圖，務必保持"
            "「同一個人」的臉部五官、髮型髮色、膚色與體型一致：\n"
            f"{ref_block}\n"
            "規則：參考圖擁有臉孔；prompt 只負責場景、服裝、光線、情緒與構圖。"
            "Reference owns the face; the prompt owns scene, wardrobe, lighting, "
            "mood, and composition. 不要重述五官、種族、膚色或既有髮型細節。"
            f"\nSubject anchor: {anchor}."
        )
    lines.append(f"\n【場景 / SCENE】\n{scene}")
    lines.append(
        "\n生成後請回報成品檔案的絕對路徑與實際輸出的像素尺寸 "
        "(report the absolute file path and the actual output pixel dimensions)."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# ffmpeg size enforcement                                                      #
# --------------------------------------------------------------------------- #
def enforce_size_with_ffmpeg(
    src: pathlib.Path, target_w: int, target_h: int
) -> bool:
    """Center-crop src to the target aspect, then scale to exact target size.

    Overwrites src on success. Returns True if ffmpeg ran successfully.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    fmt, size = detect_image(src)
    if not size:
        return False
    aw, ah = size
    target_aspect = target_w / target_h
    if aw / ah > target_aspect:
        ch = ah
        cw = round(ah * target_aspect)
    else:
        cw = aw
        ch = round(aw / target_aspect)
    x = (aw - cw) // 2
    y = (ah - ch) // 2
    vf = f"crop={cw}:{ch}:{x}:{y},scale={target_w}:{target_h}"
    tmp = src.with_suffix(src.suffix + ".tmp.png")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src),
           "-vf", vf, str(tmp)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not tmp.exists():
        if tmp.exists():
            tmp.unlink()
        return False
    tmp.replace(src)
    return True


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
def build_add_dirs(out_path: pathlib.Path, refs: List[str],
                   refs_dir: Optional[str]) -> List[str]:
    candidates: List[pathlib.Path] = [out_path.parent]
    if refs_dir:
        candidates.append(pathlib.Path(refs_dir))
    for r in refs:
        candidates.append(pathlib.Path(r).parent)
    seen: List[str] = []
    for c in candidates:
        try:
            resolved = str(c.resolve())
        except OSError:
            continue
        if c.is_dir() and resolved not in seen:
            seen.append(resolved)
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an image with the agy (Antigravity) CLI at an exact pixel size."
    )
    parser.add_argument("--prompt", required=True,
                        help="Scene / subject description (the creative prompt).")
    parser.add_argument("--width", type=int, required=True, help="Exact output width in px.")
    parser.add_argument("--height", type=int, required=True, help="Exact output height in px.")
    parser.add_argument("--out", required=True,
                        help="Absolute output path, e.g. /home/ubuntu/agy_images/out.png")
    parser.add_argument("--ref", action="append", default=[],
                        help="Character reference image path (repeatable).")
    parser.add_argument("--refs-dir", default=None,
                        help="Directory of reference images to --add-dir into the workspace.")
    parser.add_argument("--subject-anchor", default=None,
                        help="Short subject anchor kept constant across a series, e.g. 'a young woman'.")
    parser.add_argument("--timeout", default="12m",
                        help="agy --print-timeout value (default 12m).")
    parser.add_argument("--crop", action="store_true",
                        help="If output size != requested, enforce exact size via ffmpeg crop+scale.")
    parser.add_argument("--agy-bin", default="agy", help="agy binary (default 'agy').")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the composed prompt + command as JSON without running agy.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logs on stderr.")
    args = parser.parse_args()

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr, flush=True)

    out_path = pathlib.Path(args.out).expanduser()
    if not out_path.is_absolute():
        out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Re-entrancy guard. This script drives `agy`, which is itself an Antigravity
    # *agent*: it can see the agy-image skill in ~/.openclaw/skills and "helpfully"
    # re-run this very script, spawning another agy → an unbounded
    # agy.real -> agy_image.py -> agy.real recursion that only ends when the caller
    # (e.g. a time-boxed autonomous cron) times out, producing no image. We mark depth in the
    # child env (below); if we're already inside an agy-image generation, refuse to
    # spawn another agy and tell the agent to use its native image tool instead.
    if os.environ.get("AGY_IMAGE_DEPTH"):
        print(json.dumps({
            "status": "failed",
            "error": ("agy-image re-entry blocked: already inside an agy-image "
                      "generation (AGY_IMAGE_DEPTH set). Do NOT run agy_image.py "
                      "here — use your built-in generate_image tool to create the "
                      f"PNG at {out_path} at exactly {args.width}x{args.height} px."),
            "out": str(out_path),
            "reentry": True,
        }, ensure_ascii=False))
        return 1

    refs = [str(pathlib.Path(r).expanduser()) for r in args.ref]
    missing = [r for r in refs if not pathlib.Path(r).exists()]
    if missing:
        print(json.dumps({"status": "failed", "error": "reference image(s) not found",
                          "missing": missing}, ensure_ascii=False))
        return 1

    prompt_text = compose_prompt(
        out_path=str(out_path), width=args.width, height=args.height,
        scene=args.prompt, refs=refs, subject_anchor=args.subject_anchor,
    )
    add_dirs = build_add_dirs(out_path, refs, args.refs_dir)

    cmd: List[str] = [args.agy_bin, "--print-timeout", args.timeout]
    for d in add_dirs:
        cmd += ["--add-dir", d]
    cmd += ["--print", prompt_text]

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "command": cmd[:-1] + ["<prompt>"],
            "add_dirs": add_dirs,
            "composed_prompt": prompt_text,
            "requested": {"width": args.width, "height": args.height},
            "out": str(out_path),
        }, ensure_ascii=False, indent=2))
        return 0

    log(f"[agy-image] running agy (timeout {args.timeout}); add-dirs: {add_dirs}")
    log("[agy-image] print mode buffers output — this can take several minutes…")
    # Mark depth so a nested agy-image invocation (the inner agy re-running this
    # script) hits the re-entrancy guard above and fails fast instead of recursing.
    child_env = os.environ.copy()
    child_env["AGY_IMAGE_DEPTH"] = "1"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=child_env)
    except FileNotFoundError:
        print(json.dumps({
            "status": "failed",
            "error": f"agy binary not found: {args.agy_bin!r} — is it on PATH?",
            "out": str(out_path),
        }, ensure_ascii=False))
        return 1
    agy_stdout = (proc.stdout or "").strip()
    agy_stderr = (proc.stderr or "").strip()
    last_line = agy_stdout.splitlines()[-1] if agy_stdout else ""

    if not out_path.exists():
        print(json.dumps({
            "status": "failed",
            "error": "agy did not produce the output file",
            "exit_code": proc.returncode,
            "out": str(out_path),
            "agy_stdout_tail": agy_stdout[-800:],
            "agy_stderr_tail": agy_stderr[-800:],
        }, ensure_ascii=False))
        return 1

    fmt, size = detect_image(out_path)
    cropped = False
    if size is None:
        # File exists but header unparsed; report what we can.
        result: Dict[str, Any] = {
            "status": "completed",
            "out": str(out_path),
            "requested": {"width": args.width, "height": args.height},
            "actual": None,
            "matched": False,
            "cropped": False,
            "format": fmt,
            "agy_report": last_line,
            "warning": "could not parse output dimensions from header",
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    aw, ah = size
    matched = (aw == args.width and ah == args.height)
    if not matched and args.crop:
        log(f"[agy-image] size {aw}x{ah} != {args.width}x{args.height}; enforcing via ffmpeg")
        if enforce_size_with_ffmpeg(out_path, args.width, args.height):
            cropped = True
            fmt, size = detect_image(out_path)
            if size:
                aw, ah = size
            matched = (aw == args.width and ah == args.height)
        else:
            log("[agy-image] ffmpeg enforce failed (ffmpeg missing or error)")

    result = {
        "status": "completed",
        "out": str(out_path),
        "requested": {"width": args.width, "height": args.height},
        "actual": {"width": aw, "height": ah},
        "matched": matched,
        "cropped": cropped,
        "format": fmt,
        "agy_report": last_line,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
