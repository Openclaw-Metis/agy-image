#!/usr/bin/env python3
"""Regression tests for agy_image.py, driven by a fake agy (no quota spent).

Each case reproduces a failure seen in real runs on agy 1.2.16 to 1.4.x: the
image landing in the brain folder after print mode returned, a stale --out
reported as success, agy reading workspace skills from its cwd, --ref prompts
that make agy read_file the reference, quota / permission / timeout failures,
and JPEG bytes under a .png name.

Run:  python scripts/test_agy_image.py
      AGY_IMAGE_SCRIPT=<other agy_image.py> python scripts/test_agy_image.py
The second form runs the same cases against another version (e.g. the previous
release) to show which failures it still has.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib

SCRIPT = pathlib.Path(os.environ.get("AGY_IMAGE_SCRIPT")
                      or pathlib.Path(__file__).with_name("agy_image.py")).resolve()
FAKE_AGY = r'''
import json, os, pathlib, shutil, sys, time
args = sys.argv[1:]
prompt = args[args.index("--print") + 1]
pathlib.Path(os.environ["FAKE_AGY_LOG"]).write_text(json.dumps({
    "argv": args, "prompt": prompt, "cwd": os.getcwd(),
    "cwd_entries": os.listdir(os.getcwd()),
    "depth": os.environ.get("AGY_IMAGE_DEPTH"),
}, ensure_ascii=False), encoding="utf-8")
mode = os.environ.get("FAKE_AGY_MODE", "none")
if mode == "write_out":
    shutil.copy(os.environ["FAKE_AGY_SRC"], prompt.split("\n")[1].strip())
if mode == "sleep":
    time.sleep(30)
sys.stderr.write(os.environ.get("FAKE_AGY_STDERR", ""))
sys.stdout.write(json.dumps({"conversation_id": os.environ.get("FAKE_AGY_CONV", ""),
                             "status": "SUCCESS",
                             "response": os.environ.get("FAKE_AGY_RESPONSE", "Done.")}))
'''
FAKE_ENV_KEYS = ("FAKE_AGY_LOG", "FAKE_AGY_MODE", "FAKE_AGY_SRC", "FAKE_AGY_CONV",
                 "FAKE_AGY_STDERR", "FAKE_AGY_RESPONSE", "AGY_IMAGE_DEPTH")
HAS_FFMPEG = shutil.which("ffmpeg") is not None
VALUE_FLAGS = {"--prompt", "--width", "--height", "--out", "--agy-bin", "--brain-dir",
               "--wait-seconds", "--timeout", "--ref", "--refs-dir", "--subject-anchor"}


def supported_flags() -> set:
    """Flags the script under test accepts, so an older version runs its real code path."""
    help_text = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True,
                               text=True, encoding="utf-8", timeout=60).stdout
    return set(re.findall(r"--[a-z][a-z-]*", help_text))


def drop_unsupported(argv: list, supported: set) -> list:
    kept, skip = [], False
    for token in argv:
        if skip:
            skip = False
            continue
        if token.startswith("--") and token not in supported:
            skip = token in VALUE_FLAGS
            continue
        kept.append(token)
    return kept


def load_script():
    spec = importlib.util.spec_from_file_location("agy_image_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_png(path: pathlib.Path, width: int, height: int) -> pathlib.Path:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    rows = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return path


def write_jpeg(path: pathlib.Path, width: int, height: int) -> pathlib.Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"color=c=gray:s={width}x{height}", "-frames:v", "1", "-f", "image2",
                    "-c:v", "mjpeg", str(path)], check=True, timeout=60)
    return path


class AgyImageRegression(unittest.TestCase):
    def setUp(self):
        self.mod = load_script()
        self.supported = supported_flags()
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="agy-image-test-"))
        self.brain = self.tmp / "brain"
        self.brain.mkdir()
        self.out = self.tmp / "out" / "plate_raw.png"
        self.fixtures = self.tmp / "fixtures"
        self.fixtures.mkdir()
        fake = self.tmp / "fake_agy.py"
        fake.write_text(FAKE_AGY, encoding="utf-8")
        self.log = self.tmp / "fake_log.json"
        self.saved_env = {k: os.environ.get(k) for k in FAKE_ENV_KEYS}
        for key in FAKE_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["FAKE_AGY_LOG"] = str(self.log)
        os.environ["FAKE_AGY_CONV"] = "conv-test"
        real_run = subprocess.run

        def routed_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "agy-fake":
                cmd = [sys.executable, str(fake), *cmd[1:]]
            return real_run(cmd, *args, **kwargs)
        self._real_run = real_run
        subprocess.run = routed_run
        for name, value in (("TIMEOUT_GRACE_SECONDS", 1), ("POLL_INTERVAL_SECONDS", 0.2)):
            if hasattr(self.mod, name):
                setattr(self.mod, name, value)
        if hasattr(self.mod, "TERMINAL_WAIT_SECONDS"):
            self.mod.TERMINAL_WAIT_SECONDS = {k: 1 for k in self.mod.TERMINAL_WAIT_SECONDS}

    def tearDown(self):
        subprocess.run = self._real_run
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, *extra: str, size=(1024, 1280), brain=True):
        argv = ["agy_image.py", "--prompt", "雨夜的台北巷口，霓虹倒影，電影感 / rainy Taipei alley",
                "--width", str(size[0]), "--height", str(size[1]), "--out", str(self.out),
                "--agy-bin", "agy-fake", "--quiet", *extra]
        if brain:
            argv += ["--brain-dir", str(self.brain)]
        argv = drop_unsupported(argv, self.supported)
        saved_argv, sys.argv = sys.argv, argv
        buf = io.StringIO()
        started = time.time()
        try:
            with contextlib.redirect_stdout(buf):
                try:
                    code = self.mod.main()
                except SystemExit as exc:  # argparse rejects flags an older version lacks
                    code = exc.code
        finally:
            sys.argv = saved_argv
        text = buf.getvalue().strip()
        result = json.loads(text) if text.startswith("{") else {"unparsed": text}
        return code, result, time.time() - started

    def fake_log(self):
        return json.loads(self.log.read_text(encoding="utf-8")) if self.log.exists() else None

    def later(self, delay: float, action):
        timer = threading.Timer(delay, action)
        timer.start()
        self.addCleanup(timer.cancel)

    # --- brain-folder delivery (agy >= 1.2.16) -------------------------------
    def test_late_brain_image_is_recovered_into_out(self):
        os.environ["FAKE_AGY_MODE"] = "none"
        media = self.brain / "conv-test" / ".tempmediaStorage"
        self.later(1.0, lambda: (media.mkdir(parents=True),
                                 write_png(media / "media_1_ab12.png", 1024, 1280)))
        code, result, _ = self.run_script("--wait-seconds", "20")
        self.assertEqual(code, 0, result)
        self.assertEqual(result.get("status"), "completed")
        self.assertEqual(result.get("source"), "brain")
        self.assertTrue(result.get("matched"))
        self.assertTrue(self.out.is_file())

    def test_parallel_runs_claim_only_their_own_stem(self):
        os.environ["FAKE_AGY_CONV"] = "conversation-without-images"

        def drop():
            mine, other = self.brain / "sub-a", self.brain / "sub-b"
            mine.mkdir()
            other.mkdir()
            write_png(mine / "plate_raw_1792276573958.png", 1024, 1280)
            time.sleep(0.05)
            write_png(other / "someone_else_raw_1792276599999.png", 640, 640)
        self.later(0.5, drop)
        code, result, _ = self.run_script("--wait-seconds", "20")
        self.assertEqual(code, 0, result)
        self.assertTrue(str(result.get("brain_source", "")).endswith("plate_raw_1792276573958.png"))
        self.assertEqual(result.get("actual"), {"width": 1024, "height": 1280})

    def test_reference_copies_in_the_brain_are_never_returned(self):
        ref = write_png(self.fixtures / "id_shot.png", 512, 640)
        media = self.brain / "conv-test" / ".tempmediaStorage"
        media.mkdir(parents=True)
        self.later(0.3, lambda: shutil.copy(ref, media / "media_1_ref.png"))
        self.later(1.5, lambda: write_png(media / "media_2_result.png", 1024, 1280))
        code, result, _ = self.run_script("--ref", str(ref), "--wait-seconds", "20")
        self.assertEqual(code, 0, result)
        self.assertTrue(str(result.get("brain_source", "")).endswith("media_2_result.png"), result)

    def test_brain_holding_only_a_reference_copy_is_no_output(self):
        ref = write_png(self.fixtures / "id_shot.png", 512, 640)
        media = self.brain / "conv-test" / ".tempmediaStorage"
        media.mkdir(parents=True)
        self.later(0.3, lambda: shutil.copy(ref, media / "media_1_ref.png"))
        code, result, _ = self.run_script("--ref", str(ref), "--wait-seconds", "3")
        self.assertEqual(code, 1, result)
        self.assertEqual(result.get("error_kind"), "no_output")

    def test_brain_images_older_than_the_run_are_ignored(self):
        old = self.brain / "conv-test" / ".tempmediaStorage"
        old.mkdir(parents=True)
        stale = write_png(old / "media_0_old.png", 1024, 1280)
        past = time.time() - 3600
        os.utime(stale, (past, past))
        code, result, _ = self.run_script("--wait-seconds", "0")
        self.assertEqual(code, 1)
        self.assertEqual(result.get("status"), "failed")
        self.assertEqual(result.get("error_kind"), "no_output")

    # --- stale / existing --out ----------------------------------------------
    def test_existing_out_is_refused_without_overwrite(self):
        self.out.parent.mkdir(parents=True)
        write_png(self.out, 1024, 1280)
        code, result, _ = self.run_script("--wait-seconds", "0")
        self.assertEqual(code, 1)
        self.assertEqual(result.get("error_kind"), "out_exists")
        self.assertIsNone(self.fake_log(), "agy must not run when --out already exists")

    def test_stale_out_is_not_reported_as_success(self):
        self.out.parent.mkdir(parents=True)
        write_png(self.out, 1024, 1280)
        past = time.time() - 3600
        os.utime(self.out, (past, past))
        code, result, _ = self.run_script("--overwrite", "--wait-seconds", "0")
        self.assertEqual(code, 1, result)
        self.assertEqual(result.get("status"), "failed")

    # --- run environment ------------------------------------------------------
    def test_agy_runs_from_a_fresh_empty_folder_with_utf8_prompt(self):
        os.environ["FAKE_AGY_MODE"] = "write_out"
        os.environ["FAKE_AGY_SRC"] = str(write_png(self.fixtures / "src.png", 1024, 1280))
        code, result, _ = self.run_script("--wait-seconds", "5")
        self.assertEqual(code, 0, result)
        log = self.fake_log()
        self.assertEqual(log["cwd_entries"], [])
        self.assertNotEqual(pathlib.Path(log["cwd"]).resolve(), pathlib.Path.cwd().resolve())
        self.assertFalse(pathlib.Path(log["cwd"]).exists(), "the run folder is removed afterwards")
        self.assertEqual(log["depth"], "1")
        self.assertIn("雨夜的台北巷口", log["prompt"])
        self.assertEqual(result.get("source"), "out")

    def test_dry_run_requests_json_output_and_no_permission_bypass(self):
        code, result, _ = self.run_script("--dry-run", brain=False)
        self.assertEqual(code, 0)
        command = result.get("command", [])
        self.assertIn("--output-format", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        code, result, _ = self.run_script("--dry-run", "--allow-agy-permissions", brain=False)
        self.assertIn("--dangerously-skip-permissions", result.get("command", []))

    def test_reference_prompt_hands_paths_to_the_image_tool(self):
        ref = write_png(self.fixtures / "id_shot.png", 64, 64)
        code, result, _ = self.run_script("--dry-run", "--ref", str(ref), brain=False)
        self.assertEqual(code, 0)
        prompt = result.get("composed_prompt", "")
        self.assertIn(str(ref.resolve()), prompt)
        self.assertNotIn("請先讀取", prompt)
        self.assertIn("read_file", prompt)

    def test_reentry_is_blocked(self):
        os.environ["AGY_IMAGE_DEPTH"] = "1"
        code, result, _ = self.run_script()
        self.assertEqual(code, 1)
        self.assertTrue(result.get("reentry"))
        self.assertIsNone(self.fake_log())

    # --- classified failures ----------------------------------------------------
    def test_quota_exhaustion_is_classified_and_not_waited_out(self):
        os.environ["FAKE_AGY_RESPONSE"] = "Image generation failed: native image quota exhausted. Resets in 4h40m."
        code, result, elapsed = self.run_script("--wait-seconds", "60")
        self.assertEqual(code, 1)
        self.assertEqual(result.get("error_kind"), "quota_exhausted")
        self.assertLess(elapsed, 20)

    def test_permission_denial_is_classified(self):
        os.environ["FAKE_AGY_STDERR"] = "notice: a tool required the read_file permission and was denied in print mode"
        code, result, elapsed = self.run_script("--wait-seconds", "60")
        self.assertEqual(code, 1)
        self.assertEqual(result.get("error_kind"), "permission_denied")
        self.assertLess(elapsed, 20)

    def test_hung_agy_is_stopped_by_the_wrapper(self):
        os.environ["FAKE_AGY_MODE"] = "sleep"
        code, result, elapsed = self.run_script("--timeout", "1s", "--wait-seconds", "0")
        self.assertEqual(code, 1)
        self.assertEqual(result.get("error_kind"), "timeout")
        self.assertLess(elapsed, 20)

    def test_invalid_timeout_is_rejected_before_running(self):
        code, result, _ = self.run_script("--timeout", "twelve", "--wait-seconds", "0")
        self.assertEqual(code, 1)
        self.assertEqual(result.get("error_kind"), "bad_timeout")
        self.assertIsNone(self.fake_log())

    # --- container and size -----------------------------------------------------
    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
    def test_jpeg_bytes_under_png_name_are_reencoded(self):
        os.environ["FAKE_AGY_MODE"] = "write_out"
        os.environ["FAKE_AGY_SRC"] = str(write_jpeg(self.fixtures / "src.jpg", 1024, 1280))
        code, result, _ = self.run_script("--wait-seconds", "5")
        self.assertEqual(code, 0, result)
        self.assertEqual(result.get("format"), "png")
        self.assertTrue(result.get("matched"))

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
    def test_native_16x9_brain_jpeg_is_cropped_to_exact_size(self):
        media = self.brain / "conv-test" / ".tempmediaStorage"
        media.mkdir(parents=True)
        src = write_jpeg(self.fixtures / "native.jpg", 1376, 768)
        self.later(0.5, lambda: shutil.copy(src, media / "media_2_cd34.jpg"))
        code, result, _ = self.run_script("--crop", "--wait-seconds", "20", size=(1920, 1080))
        self.assertEqual(code, 0, result)
        self.assertEqual(result.get("actual"), {"width": 1920, "height": 1080})
        self.assertTrue(result.get("cropped"))
        self.assertEqual(result.get("format"), "png")


class DurationParsing(unittest.TestCase):
    def test_go_style_durations(self):
        mod = load_script()
        self.assertEqual(mod.parse_duration("12m"), 720)
        self.assertEqual(mod.parse_duration("1h30m"), 5400)
        self.assertEqual(mod.parse_duration("90s"), 90)
        for bad in ("", "0", "0s", "12", "abc", "5d"):
            self.assertIsNone(mod.parse_duration(bad), bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
