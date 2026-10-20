#!/usr/bin/env python3
"""Generate an image via the agy (Antigravity) CLI in print mode.

This is a thin, deterministic wrapper around `agy --print`. The agy CLI is an
agentic assistant whose image tool defaults to a 1024x1024 square canvas and
honours *aspect-ratio shorthand* ("4:5", "9:16") only inconsistently. The
reliable lever is to demand **exact pixel dimensions** and forbid the square
fallback — this script bakes that into the composed prompt, then verifies the
real output dimensions and (optionally) enforces the exact size with ffmpeg.

Since agy 1.2.16 image requests are handed to a built-in `image-generator`
subagent that saves into the conversation's artifacts under
`~/.gemini/antigravity-cli/brain/<conversation>/`, and print mode can return
before that file exists. The script therefore asks agy for JSON output (to learn
the conversation id), polls for the image for a bounded time, and recovers it
from the brain folder into `--out` when agy did not write `--out` itself.

Prints a single JSON object to stdout:
{
  "status": "completed",
  "out": "/abs/path.png",
  "requested": {"width": 1024, "height": 1536},
  "actual":    {"width": 1024, "height": 1536},
  "matched": true,
  "cropped": false,
  "format": "png",
  "source": "brain",
  "agy_report": "…last line agy printed…"
}
Failures carry "status": "failed", an "error_kind" and a "hint".

Auth / permissions:
  No API key. agy authenticates locally and generation consumes the local
  Antigravity/Gemini account quota. agy runs from a fresh empty folder so it
  cannot pick up workspace skills or rules; `--allow-agy-permissions` (opt-in)
  passes `--dangerously-skip-permissions` for hosts where print mode denies the
  tool calls a run needs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
CONTAINER_BY_SUFFIX = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
DEFAULT_BRAIN_DIR = pathlib.Path.home() / ".gemini" / "antigravity-cli" / "brain"
# Added on top of --timeout before the wrapper kills agy itself: agy waits for
# background tasks up to its own deadline, so a hung child must not hang us too.
TIMEOUT_GRACE_SECONDS = 60
# Poll budget once agy's own output already explains the failure, instead of the
# full --wait-seconds. A permission notice can be benign (a denied side read while
# the image subagent still works), so it keeps a longer budget than quota/auth.
TERMINAL_WAIT_SECONDS = {"quota_exhausted": 15, "auth_required": 15,
                         "permission_denied": 60, "timeout": 15, "agy_error": 30}
POLL_INTERVAL_SECONDS = 2.0

HINTS = {
    "bad_size": "Pass positive integers to --width and --height.",
    "reentry": "Do not run agy_image.py inside an agy run; use the native image tool.",
    "refs_missing": "Fix the --ref paths; nothing was sent to agy.",
    "out_exists": "The --out file already exists. Ask the user before replacing it, then re-run with --overwrite, or pick a new --out.",
    "bad_timeout": "Use a positive Go-style duration such as 90s, 12m or 1h30m.",
    "agy_missing": "Install agy or pass --agy-bin with its full path.",
    "timeout": "agy exceeded --timeout and was stopped. Retry once with a longer --timeout; check `agy -p /quota` first.",
    "quota_exhausted": "The agy image quota is used up. Stop and tell the user when it resets; do not retry in a loop.",
    "permission_denied": "agy print mode denied a tool call (for --ref, reading the reference). Ask the user to allow it (agy settings allow-rule, or --allow-agy-permissions for this run), or retry without --ref.",
    "auth_required": "Run agy interactively once to sign in, then retry.",
    "agy_error": "agy exited with an error. Read agy_stderr_tail; retry once only if it looks transient.",
    "no_output": "No image appeared at --out or in the agy brain folder. Read agy_stdout_tail / agy_stderr_tail and retry once with a simpler prompt.",
}


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
        with path.open("rb") as fh:
            head = fh.read(64)
    except OSError:
        return None, None
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", _png_size(head)
    if head[:2] == b"\xff\xd8":
        try:
            return "jpeg", _jpeg_size(path)
        except OSError:
            return "jpeg", None
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
        "\n（若圖片工具無法直接存到這個路徑，留在你的 artifacts 即可：外部腳本會負責複製、轉檔與裁切，"
        "你不需要也不要用其他工具處理檔案。If the image tool cannot save to this path, leave the "
        "image in your artifacts; an external script copies, converts and crops it, so do not "
        "use any other tool on the file.）"
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
        "(your built-in image generation tool) 產生這張圖並存成上面的 PNG 路徑。"
        " 嚴禁執行任何 shell 指令、python 腳本、`agy_image.py`，也不要讀取、呼叫或載入 "
        "任何 skill（包含 `agy-image`）、規則或工作區檔案，更不要再開一個 agy/Antigravity session 來生圖。"
        " Do NOT run any shell command, python script or agy_image.py, do NOT open "
        "or load any skill, rule or workspace file, and do NOT spawn another agy "
        "session — generate the image yourself with your native image tool."
        " 做完直接回報路徑與尺寸即可。"
    )
    if refs:
        ref_block = "\n".join(f"- {r}" for r in refs)
        anchor = subject_anchor or "參考圖中的同一個人 / the same person as in the references"
        # Print mode denies read_file on these paths, so the references go to the
        # image tool by path instead of being opened by the agent first.
        lines.append(
            "\n【角色參考圖 / CHARACTER REFERENCE】把以下參考圖的檔案路徑直接交給圖片生成工具作為 "
            "reference image（不要用 read_file 或其他工具開啟它們），並保持"
            "「同一個人」的臉部五官、髮型髮色、膚色與體型一致：\n"
            f"{ref_block}\n"
            "Pass these file paths straight to your image generation tool as reference "
            "images; do not open them with read_file or any other tool.\n"
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
# ffmpeg encode / size enforcement                                             #
# --------------------------------------------------------------------------- #
def crop_filter(size: Tuple[int, int], target_w: int, target_h: int) -> str:
    """Center-crop to the target aspect, then scale to the exact target size."""
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
    return f"crop={cw}:{ch}:{x}:{y},scale={target_w}:{target_h}"


def ffmpeg_encode(src: pathlib.Path, dst: pathlib.Path, vf: Optional[str] = None) -> bool:
    """Re-encode src into dst (container chosen by dst's suffix), optionally filtered.

    Writes a sibling temp file first so a failed encode never truncates dst, and
    src may equal dst. Returns True on success.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    tmp = dst.with_name(f"{dst.stem}.agy-tmp{dst.suffix}")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src)]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-frames:v", "1", str(tmp)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        result = None
    if result is None or result.returncode != 0 or not tmp.exists():
        if tmp.exists():
            tmp.unlink()
        return False
    tmp.replace(dst)
    return True


def enforce_size_with_ffmpeg(src: pathlib.Path, target_w: int, target_h: int) -> bool:
    """Crop+scale src in place to exactly target_w x target_h. True if ffmpeg ran."""
    _, size = detect_image(src)
    if not size:
        return False
    return ffmpeg_encode(src, src, crop_filter(size, target_w, target_h))


# --------------------------------------------------------------------------- #
# Run helpers                                                                  #
# --------------------------------------------------------------------------- #
def parse_duration(text: str) -> Optional[float]:
    """Parse a Go-style duration ("90s", "12m", "1h30m") into seconds; None if invalid."""
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text.strip())
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    total = hours * 3600 + minutes * 60 + seconds
    return float(total) if total > 0 else None


def build_add_dirs(out_path: pathlib.Path, refs: List[str],
                   refs_dir: Optional[str]) -> List[str]:
    candidates: List[pathlib.Path] = [out_path.parent]
    if refs_dir:
        candidates.append(pathlib.Path(refs_dir).expanduser())
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


def parse_agy_json(stdout: str) -> Dict[str, Any]:
    """Return agy's --output-format json object, or {} when stdout is not JSON."""
    text = stdout.strip()
    start = text.find("{")
    if start < 0:
        return {}
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def classify_failure(text: str) -> str:
    lowered = text.lower()
    if re.search(r"quota|resource[_ ]exhausted|rate[ -]?limit|\b429\b", lowered):
        return "quota_exhausted"
    if re.search(r"permission|denied|allow[- ]rule|not allowed", lowered):
        return "permission_denied"
    if re.search(r"sign[ -]?in|log[ -]?in|authenticat|oauth|unauthori", lowered):
        return "auth_required"
    return "no_output"


def file_fingerprint(path: pathlib.Path) -> Tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _images_in(folder: pathlib.Path, since: float,
               exclude: frozenset = frozenset()) -> List[pathlib.Path]:
    if not folder.is_dir():
        return []
    hits: List[pathlib.Path] = []
    for path in folder.iterdir():
        try:
            if not (path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
                    and ".agy-tmp" not in path.name and path.stat().st_mtime >= since):
                continue
            if exclude and path.stat().st_size in {size for size, _ in exclude}:
                if file_fingerprint(path) in exclude:
                    continue
            hits.append(path)
        except OSError:
            continue
    return hits


def find_brain_image(brain_dir: pathlib.Path, conversation_id: str, stem: str,
                     since: float, exclude: frozenset = frozenset()) -> Optional[pathlib.Path]:
    """Locate the image this run produced in agy's brain folder.

    The print conversation (the JSON `conversation_id`) keeps `<out-stem>_<ts>.jpg`;
    the image-generator subagent's conversation keeps `.tempmediaStorage/` copies,
    including copies of the reference images it was given, which `exclude`
    (size, sha256) filters out. Only files newer than the run start count, and the
    stem match keeps parallel runs from claiming each other's images.
    """
    stem_lower = stem.lower()

    def pick(hits: List[pathlib.Path]) -> Optional[pathlib.Path]:
        if not hits:
            return None
        named = [p for p in hits if p.name.lower().startswith(stem_lower)]
        return max(named or hits, key=lambda p: p.stat().st_mtime)

    if conversation_id:
        conv = brain_dir / conversation_id
        found = pick(_images_in(conv, since, exclude)
                     + _images_in(conv / ".tempmediaStorage", since, exclude))
        if found:
            return found
    if not brain_dir.is_dir():
        return None
    named: List[pathlib.Path] = []
    for conv in brain_dir.iterdir():
        try:
            if conv.is_dir() and conv.stat().st_mtime >= since:
                named += [p for p in _images_in(conv, since, exclude)
                          if p.name.lower().startswith(stem_lower + "_")]
        except OSError:
            continue
    return max(named, key=lambda p: p.stat().st_mtime) if named else None


def wait_until_stable(path: pathlib.Path, timeout: float = 20.0) -> None:
    """Wait until the file size stops changing (the writer may still be flushing)."""
    deadline = time.time() + timeout
    last = -1
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        if size > 0 and size == last:
            return
        last = size
        time.sleep(0.5)


def run_agy(cmd: List[str], cwd: str, env: Dict[str, str],
            timeout_seconds: float) -> Tuple[Optional[int], str, str, bool]:
    """Run agy; return (exit_code, stdout, stderr, timed_out)."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        def _text(value: Any) -> str:
            if isinstance(value, bytes):
                return value.decode("utf-8", "replace")
            return value or ""
        return None, _text(exc.stdout), _text(exc.stderr), True
    return proc.returncode, proc.stdout or "", proc.stderr or "", False


def emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def fail(kind: str, error: str, **extra: Any) -> int:
    payload: Dict[str, Any] = {"status": "failed", "error_kind": kind, "error": error}
    payload.update(extra)
    payload["hint"] = HINTS.get(kind, "")
    emit(payload)
    return 1


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an image with the agy (Antigravity) CLI at an exact pixel size."
    )
    parser.add_argument("--prompt", required=True,
                        help="Scene / subject description (the creative prompt).")
    parser.add_argument("--width", type=int, required=True, help="Exact output width in px.")
    parser.add_argument("--height", type=int, required=True, help="Exact output height in px.")
    parser.add_argument("--out", required=True,
                        help="Output path, e.g. ~/agy_images/out.png (made absolute).")
    parser.add_argument("--ref", action="append", default=[],
                        help="Character reference image path (repeatable).")
    parser.add_argument("--refs-dir", default=None,
                        help="Directory of reference images to --add-dir into the workspace.")
    parser.add_argument("--subject-anchor", default=None,
                        help="Short subject anchor kept constant across a series, e.g. 'a young woman'.")
    parser.add_argument("--timeout", default="12m",
                        help="agy --print-timeout as a Go duration (default 12m).")
    parser.add_argument("--wait-seconds", type=float, default=240.0,
                        help="How long to poll for a late image after agy returns (default 240).")
    parser.add_argument("--brain-dir", default=str(DEFAULT_BRAIN_DIR),
                        help="agy brain folder to recover images from (default ~/.gemini/antigravity-cli/brain).")
    parser.add_argument("--crop", action="store_true",
                        help="If output size != requested, enforce exact size via ffmpeg crop+scale.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Allow replacing an existing --out file (ask the user first).")
    parser.add_argument("--allow-agy-permissions", action="store_true",
                        help="Pass --dangerously-skip-permissions to agy for this run (user opt-in only).")
    parser.add_argument("--agy-bin", default="agy", help="agy binary (default 'agy').")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the composed prompt + command as JSON without running agy.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logs on stderr.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr, flush=True)

    out_path = pathlib.Path(args.out).expanduser().resolve()
    requested = {"width": args.width, "height": args.height}
    if args.width <= 0 or args.height <= 0:
        return fail("bad_size", "--width and --height must be positive integers", out=str(out_path))

    # Re-entrancy guard. This script drives `agy`, which is itself an agent: it can
    # see an installed agy-image skill and re-run this very script, spawning an
    # unbounded agy -> agy_image.py -> agy recursion that produces no image. The
    # child env carries a depth marker; inside it, refuse to spawn another agy.
    if os.environ.get("AGY_IMAGE_DEPTH"):
        return fail("reentry",
                    "agy-image re-entry blocked: already inside an agy-image generation "
                    "(AGY_IMAGE_DEPTH set). Use your built-in image generation tool to "
                    f"create the PNG at {out_path} at exactly {args.width}x{args.height} px.",
                    out=str(out_path), reentry=True)

    timeout_seconds = parse_duration(args.timeout)
    if timeout_seconds is None:
        return fail("bad_timeout", f"invalid --timeout {args.timeout!r}", out=str(out_path))

    refs = [str(pathlib.Path(r).expanduser().resolve()) for r in args.ref]
    missing = [r for r in refs if not pathlib.Path(r).is_file()]
    if missing:
        return fail("refs_missing", "reference image(s) not found", missing=missing, out=str(out_path))

    if out_path.exists() and not args.overwrite and not args.dry_run:
        return fail("out_exists", f"{out_path} already exists", out=str(out_path))

    prompt_text = compose_prompt(
        out_path=str(out_path), width=args.width, height=args.height,
        scene=args.prompt, refs=refs, subject_anchor=args.subject_anchor,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    add_dirs = build_add_dirs(out_path, refs, args.refs_dir)

    cmd: List[str] = [args.agy_bin, "--print-timeout", args.timeout, "--output-format", "json"]
    for d in add_dirs:
        cmd += ["--add-dir", d]
    if args.allow_agy_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd += ["--print", prompt_text]

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "command": cmd[:-1] + ["<prompt>"],
            "cwd": "<fresh empty temp folder>",
            "add_dirs": add_dirs,
            "composed_prompt": prompt_text,
            "requested": requested,
            "out": str(out_path),
            "out_exists": out_path.exists(),
        }, ensure_ascii=False, indent=2))
        return 0

    log(f"[agy-image] running agy (timeout {args.timeout}); add-dirs: {add_dirs}")
    log("[agy-image] print mode buffers output — this can take several minutes…")
    # agy loads skills and rules from the working directory's .agents/ folders and
    # print mode denies the reads it then attempts, so it runs from an empty folder.
    run_dir = tempfile.mkdtemp(prefix="agy-image-run-")
    try:
        return generate(args, cmd, run_dir, out_path, requested, refs, timeout_seconds, log)
    finally:
        # On Windows a lingering agy child can still hold the folder; leave it then.
        shutil.rmtree(run_dir, ignore_errors=True)


def generate(args: argparse.Namespace, cmd: List[str], run_dir: str,
             out_path: pathlib.Path, requested: Dict[str, int], refs: List[str],
             timeout_seconds: float, log: Any) -> int:
    child_env = os.environ.copy()
    child_env["AGY_IMAGE_DEPTH"] = "1"
    brain_dir = pathlib.Path(args.brain_dir).expanduser()
    ref_prints = frozenset(file_fingerprint(pathlib.Path(r)) for r in refs)
    started = time.time() - 1.0  # filesystem mtime granularity slack
    try:
        exit_code, agy_stdout, agy_stderr, timed_out = run_agy(
            cmd, run_dir, child_env, timeout_seconds + TIMEOUT_GRACE_SECONDS)
    except FileNotFoundError:
        return fail("agy_missing", f"agy binary not found: {args.agy_bin!r} — is it on PATH?",
                    out=str(out_path))

    agy_json = parse_agy_json(agy_stdout)
    conversation_id = str(agy_json.get("conversation_id") or "")
    response = str(agy_json.get("response") or agy_stdout).strip()
    last_line = response.splitlines()[-1] if response else ""
    early_kind = classify_failure("\n".join([response, agy_stderr]))
    if timed_out and early_kind == "no_output":
        early_kind = "timeout"
    elif exit_code not in (0, None) and early_kind == "no_output":
        early_kind = "agy_error"
    wait_seconds = max(0.0, args.wait_seconds)
    if early_kind in TERMINAL_WAIT_SECONDS:
        wait_seconds = min(wait_seconds, TERMINAL_WAIT_SECONDS[early_kind])

    # The image-generator subagent can still be writing after print mode returns.
    source: Optional[str] = None
    found: Optional[pathlib.Path] = None
    deadline = time.time() + wait_seconds
    while True:
        try:
            if out_path.is_file() and out_path.stat().st_mtime >= started:
                found, source = out_path, "out"
        except OSError:
            pass
        if found is None:
            brain_hit = find_brain_image(brain_dir, conversation_id, out_path.stem, started,
                                         ref_prints)
            if brain_hit is not None:
                found, source = brain_hit, "brain"
        if found is not None or time.time() >= deadline:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    tails = {
        "agy_exit_code": exit_code,
        "agy_status": agy_json.get("status"),
        "conversation_id": conversation_id or None,
        "agy_stdout_tail": response[-800:],
        "agy_stderr_tail": agy_stderr.strip()[-800:],
    }
    if found is None:
        message = ("agy exceeded the time limit and produced no image" if early_kind == "timeout"
                   else "agy did not produce the output file")
        return fail(early_kind, message, out=str(out_path), **tails)

    wait_until_stable(found)
    warnings: List[str] = []
    if timed_out:
        warnings.append("agy hit the time limit, but its image was recovered")
    brain_source: Optional[str] = None
    if source == "brain":
        brain_source = str(found)
        log(f"[agy-image] recovered image from brain folder: {found}")

    fmt, size = detect_image(found)
    cropped = False
    converted = False
    expected_fmt = CONTAINER_BY_SUFFIX.get(out_path.suffix.lower())
    needs_crop = bool(args.crop and size and size != (args.width, args.height))
    needs_reencode = expected_fmt is not None and fmt != expected_fmt
    if needs_crop or needs_reencode:
        vf = crop_filter(size, args.width, args.height) if needs_crop and size else None
        if needs_crop:
            log(f"[agy-image] size {size[0]}x{size[1]} != {args.width}x{args.height}; enforcing via ffmpeg")
        if ffmpeg_encode(found, out_path, vf):
            cropped = needs_crop
            converted = needs_reencode
        else:
            warnings.append("ffmpeg missing or failed; size/container left as produced")
            if found != out_path:
                shutil.copy2(found, out_path)
    elif found != out_path:
        shutil.copy2(found, out_path)

    fmt, size = detect_image(out_path)
    result: Dict[str, Any] = {
        "status": "completed",
        "out": str(out_path),
        "requested": requested,
        "actual": {"width": size[0], "height": size[1]} if size else None,
        "matched": bool(size and size == (args.width, args.height)),
        "cropped": cropped,
        "converted": converted,
        "format": fmt,
        "source": source,
        "brain_source": brain_source,
        "conversation_id": conversation_id or None,
        "elapsed_seconds": round(time.time() - started, 1),
        "agy_report": last_line,
    }
    if size is None:
        warnings.append("could not parse output dimensions from header")
    if warnings:
        result["warning"] = "; ".join(warnings)
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
