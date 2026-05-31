"""
REEL Benchmark Utilities
========================
Timed subprocess execution, file operations, PSNR/SSIM quality metrics,
CSV helpers, system info collection.
"""

import os
import sys
import re
import csv
import time
import json
import hashlib
import platform
import subprocess
import statistics
from pathlib import Path
from dataclasses import dataclass

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("Warning: psutil not installed — memory profiling disabled.")
    print("  Install with:  pip install psutil")

from config import CSV_COLUMNS, CSV_PATH, RESULTS_DIR, SYSTEM_INFO_PATH


# ─── Data Classes ───────────────────────────────────────────────────

@dataclass
class TimedResult:
    """Result of a timed subprocess execution."""
    wall_time: float = 0.0
    cpu_time: float = 0.0
    peak_memory_mb: float = 0.0
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


# ─── Subprocess Execution ──────────────────────────────────────────

def timed_run(cmd, label="", timeout=3600):
    """
    Run a command and measure wall time, CPU time, and peak memory.
    Uses psutil for memory/CPU profiling when available.
    """
    start_wall = time.perf_counter()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    peak_memory = 0
    cpu_time = 0.0

    if HAS_PSUTIL:
        try:
            ps_proc = psutil.Process(proc.pid)
            while proc.poll() is None:
                try:
                    mem_info = ps_proc.memory_info()
                    peak_memory = max(peak_memory, mem_info.rss)
                    ct = ps_proc.cpu_times()
                    cpu_time = ct.user + ct.system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break
                time.sleep(0.01)  # 10ms polling

            # Final read after process exits
            try:
                ct = ps_proc.cpu_times()
                cpu_time = ct.user + ct.system
                mem_info = ps_proc.memory_info()
                peak_memory = max(peak_memory, mem_info.rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        except psutil.NoSuchProcess:
            proc.wait()
    else:
        proc.wait()

    end_wall = time.perf_counter()

    stdout = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
    stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""

    if proc.returncode != 0 and label:
        print(f"\n    WARNING: {label} failed (exit {proc.returncode})")
        if stderr:
            for line in stderr.strip().split("\n")[-5:]:
                print(f"      {line}")

    return TimedResult(
        wall_time=end_wall - start_wall,
        cpu_time=cpu_time,
        peak_memory_mb=peak_memory / (1024 * 1024),
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def timed_run_fast(cmd):
    """Lightweight timing — just wall time, for random frame decode tests."""
    start = time.perf_counter()
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.perf_counter() - start
    return elapsed, result.returncode


# ─── File Operations ────────────────────────────────────────────────

def safe_delete(path):
    """Delete a file if it exists, silently ignore errors."""
    try:
        p = str(path) if path else None
        if p and os.path.exists(p):
            os.remove(p)
    except OSError:
        pass


def file_size_bytes(path):
    """Return file size in bytes, or 0 if not found."""
    try:
        return os.path.getsize(str(path))
    except OSError:
        return 0


def yuv_frame_size(width, height):
    """Size of one YUV420p frame in bytes: W*H + 2*(W/2)*(H/2) = W*H*3/2."""
    return width * height * 3 // 2


def get_video_info(path):
    """Get width, height, and fps using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "csv=s=x:p=0", str(path)
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            parts = r.stdout.strip().split("x")
            w = int(parts[0])
            h = int(parts[1])
            fps_str = parts[2]
            if "/" in fps_str:
                num, den = fps_str.split("/")
                fps = float(num) / float(den) if den != "0" else 30.0
            else:
                fps = float(fps_str)
            return w, h, fps
    except Exception as e:
        print(f"Warning: Failed to probe {path}: {e}")
    return 1920, 1080, 30.0  # fallback defaults


def files_identical(path_a, path_b, chunk_size=1024 * 1024):
    """Streaming byte-for-byte comparison of two files."""
    try:
        size_a = os.path.getsize(path_a)
        size_b = os.path.getsize(path_b)
        if size_a != size_b:
            return False

        with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
            while True:
                ca = fa.read(chunk_size)
                cb = fb.read(chunk_size)
                if ca != cb:
                    return False
                if not ca:
                    break
        return True
    except OSError:
        return False


# ─── Quality Metrics ───────────────────────────────────────────────

def compute_psnr_ssim(original_yuv, decoded_yuv, width, height):
    """
    Compute PSNR (per plane) and SSIM between two raw YUV420p files
    using FFmpeg's psnr and ssim filters.

    Returns (psnr_y, psnr_u, psnr_v, ssim_all).
    """
    psnr_y = psnr_u = psnr_v = float("inf")
    ssim_val = 1.0
    size_str = f"{width}x{height}"

    # ── PSNR ──
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
            "-i", str(original_yuv),
            "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
            "-i", str(decoded_yuv),
            "-lavfi", "psnr",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        for line in result.stderr.split("\n"):
            if "PSNR" in line and "y:" in line:
                ym = re.search(r"y:(\S+)", line)
                um = re.search(r"u:(\S+)", line)
                vm = re.search(r"v:(\S+)", line)
                if ym:
                    v = ym.group(1)
                    psnr_y = float("inf") if v == "inf" else float(v)
                if um:
                    v = um.group(1)
                    psnr_u = float("inf") if v == "inf" else float(v)
                if vm:
                    v = vm.group(1)
                    psnr_v = float("inf") if v == "inf" else float(v)
    except Exception as e:
        print(f"\n    WARNING: PSNR computation failed: {e}")

    # ── SSIM ──
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
            "-i", str(original_yuv),
            "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
            "-i", str(decoded_yuv),
            "-lavfi", "ssim",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        for line in result.stderr.split("\n"):
            if "SSIM" in line and "All:" in line:
                match = re.search(r"All:([\d.]+)", line)
                if match:
                    ssim_val = float(match.group(1))
    except Exception as e:
        print(f"\n    WARNING: SSIM computation failed: {e}")

    return psnr_y, psnr_u, psnr_v, ssim_val


# ─── CSV Handling ───────────────────────────────────────────────────

def setup_csv(path=None):
    """Create CSV file with headers if it doesn't exist."""
    path = path or CSV_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()

    return path


def append_to_csv(path, rows):
    """Append result rows to the CSV (crash-safe incremental writes)."""
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        for row in rows:
            writer.writerow(row)


# ─── Statistics ─────────────────────────────────────────────────────

def percentile(data, p):
    """Compute the p-th percentile of a list."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])


def compute_latency_stats(latencies_ms):
    """Compute summary statistics from a list of millisecond values."""
    if not latencies_ms:
        return {"avg": 0, "p50": 0, "p95": 0, "p99": 0,
                "min": 0, "max": 0, "stddev": 0}
    return {
        "avg": statistics.mean(latencies_ms),
        "p50": percentile(latencies_ms, 50),
        "p95": percentile(latencies_ms, 95),
        "p99": percentile(latencies_ms, 99),
        "min": min(latencies_ms),
        "max": max(latencies_ms),
        "stddev": statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0,
    }


# ─── System Info ────────────────────────────────────────────────────

def collect_system_info(reel_path=""):
    """Collect hardware/software environment info for reproducibility."""
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "cpu_count_logical": os.cpu_count(),
    }

    if HAS_PSUTIL:
        vm = psutil.virtual_memory()
        info["ram_total_gb"] = round(vm.total / (1024 ** 3), 2)
        info["ram_available_gb"] = round(vm.available / (1024 ** 3), 2)

    # FFmpeg version
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
        info["ffmpeg_version"] = r.stdout.split("\n")[0] if r.stdout else "unknown"
    except Exception:
        info["ffmpeg_version"] = "not found"

    # REEL version
    if reel_path and os.path.isfile(reel_path):
        try:
            r = subprocess.run([reel_path, "--version"], capture_output=True, text=True, timeout=10)
            info["reel_version"] = r.stdout.strip()
        except Exception:
            info["reel_version"] = "unknown"
        info["reel_path"] = reel_path

    # Rust compiler
    try:
        r = subprocess.run(["rustc", "--version"], capture_output=True, text=True, timeout=10)
        info["rustc_version"] = r.stdout.strip()
    except Exception:
        info["rustc_version"] = "not found"

    info["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return info


def save_system_info(info, path=None):
    """Save system info to JSON file."""
    path = path or SYSTEM_INFO_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(info, f, indent=2)
    print(f"  System info saved to {path}")


# ─── Validation Helpers ────────────────────────────────────────────

def check_ffmpeg():
    """Verify FFmpeg is available in PATH."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except FileNotFoundError:
        print("ERROR: FFmpeg not found in PATH. Please install FFmpeg.")
        sys.exit(1)


def check_reel(reel_path):
    """Verify the REEL executable works."""
    try:
        result = subprocess.run(
            [reel_path, "--help"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass
    print(f"ERROR: REEL executable not working at {reel_path}")
    sys.exit(1)
