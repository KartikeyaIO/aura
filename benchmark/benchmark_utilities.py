"""
REEL Benchmark Utilities
========================
Timed subprocess execution, file operations, PSNR/SSIM quality metrics,
CSV helpers, system info collection, and Process Overhead Calibration.
"""

import os
import sys
import re
import csv
import time
import json
import platform
import subprocess
import statistics
import tempfile
from pathlib import Path
from dataclasses import dataclass

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from config import CSV_COLUMNS, CSV_PATH, SYSTEM_INFO_PATH

@dataclass
class TimedResult:
    wall_time: float = 0.0
    cpu_time: float = 0.0
    peak_memory_mb: float = 0.0
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

def timed_run(cmd, label="", timeout=3600):
    start_wall = time.perf_counter()
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f)
        peak_memory, cpu_time = 0, 0.0
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
                    time.sleep(0.01)
            except psutil.NoSuchProcess:
                proc.wait()
        else:
            proc.wait()
        end_wall = time.perf_counter()
        out_f.seek(0)
        stdout = out_f.read().decode(errors="replace")
        err_f.seek(0)
        stderr = err_f.read().decode(errors="replace")

    return TimedResult(
        wall_time=end_wall - start_wall,
        cpu_time=cpu_time,
        peak_memory_mb=peak_memory / (1024 * 1024),
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )

def timed_run_fast(cmd):
    start = time.perf_counter()
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.perf_counter() - start
    return elapsed, result.returncode

def calibrate_process_overhead(reel_exe):
    """Measures the bare minimum OS time to spawn a process to subtract from microbenchmarks."""
    print("  Calibrating OS Process Spawn Latency (100 passes) ... ", end="", flush=True)
    ffmpeg_times, reel_times = [], []
    for _ in range(50):
        # Time the simplest possible commands
        f_time, _ = timed_run_fast(["ffmpeg", "-version"])
        ffmpeg_times.append(f_time)
        r_time, _ = timed_run_fast([reel_exe, "--version"])
        reel_times.append(r_time)
        
    ffmpeg_overhead = statistics.median(ffmpeg_times)
    reel_overhead = statistics.median(reel_times)
    print(f"FFmpeg: {ffmpeg_overhead*1000:.1f}ms | REEL: {reel_overhead*1000:.1f}ms")
    return {"ffmpeg": ffmpeg_overhead, "reel": reel_overhead}

def safe_delete(path):
    try:
        if path and os.path.exists(path): os.remove(path)
    except OSError: pass

def file_size_bytes(path):
    try: return os.path.getsize(str(path))
    except OSError: return 0

def yuv_frame_size(width, height):
    return width * height * 3 // 2

def get_video_info(path):
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "csv=s=x:p=0", str(path)
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            parts = r.stdout.strip().split("x")
            w, h = int(parts[0]), int(parts[1])
            fps_str = parts[2]
            if "/" in fps_str:
                num, den = map(int, fps_str.split("/"))
            else:
                num, den = int(float(fps_str) * 1000), 1000
            return w, h, num, den
    except Exception as e:
        print(f"Warning: Failed to probe {path}: {e}")
    return 1920, 1080, 30000, 1001

def files_identical(path_a, path_b, chunk_size=1024 * 1024):
    try:
        if os.path.getsize(path_a) != os.path.getsize(path_b): return False
        with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
            while True:
                ca = fa.read(chunk_size)
                cb = fb.read(chunk_size)
                if ca != cb: return False
                if not ca: break
        return True
    except OSError: return False

def compute_psnr_ssim(original_yuv, decoded_yuv, width, height):
    psnr_y = psnr_u = psnr_v = float("inf")
    ssim_val = 1.0
    size_str = f"{width}x{height}"
    
    # Using high-quality sws_flags to ensure fair chroma downsampling if source codec was 422
    for metric, lavfi_filter in [("psnr", "psnr"), ("ssim", "ssim")]:
        try:
            cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str, "-i", str(original_yuv),
                "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str, "-i", str(decoded_yuv),
                "-lavfi", f"[0:v][1:v]{lavfi_filter}", "-f", "null", "-"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if metric == "psnr":
                for line in result.stderr.split("\n"):
                    if "PSNR" in line and "y:" in line:
                        ym = re.search(r"y:(\S+)", line)
                        um = re.search(r"u:(\S+)", line)
                        vm = re.search(r"v:(\S+)", line)
                        if ym: psnr_y = float("inf") if ym.group(1) == "inf" else float(ym.group(1))
                        if um: psnr_u = float("inf") if um.group(1) == "inf" else float(um.group(1))
                        if vm: psnr_v = float("inf") if vm.group(1) == "inf" else float(vm.group(1))
            else:
                for line in result.stderr.split("\n"):
                    if "SSIM" in line and "All:" in line:
                        match = re.search(r"All:([\d.]+)", line)
                        if match: ssim_val = float(match.group(1))
        except Exception: pass
    return psnr_y, psnr_u, psnr_v, ssim_val

def setup_csv(path=None):
    path = path or CSV_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
    return path

def append_to_csv(path, rows):
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        for row in rows: writer.writerow(row)

def percentile(data, p):
    if not data: return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])

def compute_latency_stats(latencies_ms):
    if not latencies_ms: return {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "stddev": 0}
    return {
        "avg": statistics.mean(latencies_ms),
        "p50": percentile(latencies_ms, 50),
        "p95": percentile(latencies_ms, 95),
        "p99": percentile(latencies_ms, 99),
        "min": min(latencies_ms),
        "max": max(latencies_ms),
        "stddev": statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0,
    }

def collect_system_info(reel_path=""):
    info = {
        "os": platform.system(), "os_version": platform.version(), "os_release": platform.release(),
        "architecture": platform.machine(), "processor": platform.processor(),
        "python_version": platform.python_version(), "cpu_count_logical": os.cpu_count(),
    }
    if HAS_PSUTIL:
        vm = psutil.virtual_memory()
        info["ram_total_gb"] = round(vm.total / (1024 ** 3), 2)
        info["ram_available_gb"] = round(vm.available / (1024 ** 3), 2)
    try: info["ffmpeg_version"] = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0]
    except Exception: info["ffmpeg_version"] = "not found"
    try: info["reel_version"] = subprocess.run([reel_path, "--version"], capture_output=True, text=True).stdout.strip()
    except Exception: info["reel_version"] = "unknown"
    try: info["rustc_version"] = subprocess.run(["rustc", "--version"], capture_output=True, text=True).stdout.strip()
    except Exception: info["rustc_version"] = "not found"
    info["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return info

def save_system_info(info, path=None):
    path = path or SYSTEM_INFO_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(info, f, indent=2)

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except FileNotFoundError:
        print("ERROR: FFmpeg not found in PATH.")
        sys.exit(1)

def check_reel(reel_path):
    try:
        if subprocess.run([reel_path, "--help"], capture_output=True, text=True, timeout=10).returncode == 0:
            return True
    except Exception: pass
    print(f"ERROR: REEL executable not working at {reel_path}")
    sys.exit(1)