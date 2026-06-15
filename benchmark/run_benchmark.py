#!/usr/bin/env python3
"""
REEL Benchmark — Main Runner
==============================
Pipeline per video:
  MP4 → YUV420p (ffmpeg) → encode/decode/measure all codecs → delete YUV → next video

Usage:
    python run_benchmark.py [OPTIONS]

Options:
    --input-dir PATH     Directory of .mp4 files  (default: videos/mp4)
    --reel-exe PATH      Path to `aurx` binary     (default: auto-detect)
    --workers N          Parallel codec workers     (default: 1, safe)
    --skip-codecs LIST   Comma-separated codecs to skip (e.g. Lagarith,HuffYUV)
    --resume             Skip video+codec pairs already in CSV
    --max-videos N       Process at most N videos (for quick test runs)
    --no-psnr            Skip PSNR/SSIM computation (faster)
"""

import os
import sys
import csv
import time
import random
import tempfile
import argparse
import subprocess
from pathlib import Path

from config import (
    CODECS, CSV_COLUMNS, RESULTS_DIR, TEMP_DIR,
    RANDOM_FRAME_COUNT, CSV_PATH,
    VIDEO_FPS_NUM, VIDEO_FPS_DEN,
)
from benchmark_utilities import (
    TimedResult, timed_run, timed_run_fast,
    calibrate_process_overhead,
    safe_delete, file_size_bytes, get_video_info,
    files_identical, compute_psnr_ssim,
    setup_csv, append_to_csv,
    compute_latency_stats,
    collect_system_info, save_system_info,
    check_ffmpeg, check_reel,
)


# ─── Auto-detect reel binary ────────────────────────────────────────────────

def find_reel_exe(hint: str = None) -> str:
    if hint:
        return hint
    candidates = [
        Path("target/release/reel.exe"),
        Path("../target/release/reel.exe"),
        Path("target/release/reel"),
        Path("../target/release/reel"),
    ]
    for p in candidates:
        if p.exists():
            print(f"  Auto-detected REEL binary: {p.resolve()}")
            return str(p.resolve())
    print("WARNING: Could not auto-detect 'aurx' binary. Pass --reel-exe explicitly.")
    return "aurx"


# ─── MP4 → YUV conversion ───────────────────────────────────────────────────

def mp4_to_yuv(mp4_path: Path, yuv_path: Path, width: int, height: int) -> bool:
    """
    Decode MP4 to raw yuv420p. Returns True on success.
    Forces even dimensions to satisfy YUV420p requirement.
    """
    # Ensure even dimensions (crop 1px if needed — never upscale)
    w = width  - (width  % 2)
    h = height - (height % 2)
    vf = f"scale={w}:{h}:flags=lanczos,format=yuv420p"
    cmd = [
        "ffmpeg", "-y", "-i", str(mp4_path),
        "-vf", vf,
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        str(yuv_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not yuv_path.exists() or yuv_path.stat().st_size == 0:
        print(f"    ✗ YUV extraction failed: {result.stderr.decode(errors='replace')[-300:]}")
        return False
    return True


def count_yuv_frames(yuv_path: Path, width: int, height: int) -> int:
    frame_size = width * height * 3 // 2
    total_bytes = yuv_path.stat().st_size
    if total_bytes % frame_size != 0:
        # Truncate to whole frames
        frames = total_bytes // frame_size
    else:
        frames = total_bytes // frame_size
    return frames


# ─── Per-codec benchmark ─────────────────────────────────────────────────────

def benchmark_codec(
    codec_name: str,
    codec_cfg: dict,
    yuv_path: Path,
    width: int,
    height: int,
    fps_num: int,
    fps_den: int,
    total_frames: int,
    reel_exe: str,
    compute_quality: bool,
    process_overhead: dict,
) -> dict:
    """
    Encode YUV → codec, decode back to YUV, measure everything, return a row dict.
    All temp files are created in TEMP_DIR and deleted before returning.
    """
    ext      = codec_cfg["ext"]
    pix_fmt  = codec_cfg["encode_pix_fmt"]
    size_str = f"{width}x{height}"
    fps_str  = f"{fps_num}/{fps_den}"

    encoded_path  = TEMP_DIR / f"_bench_{codec_name}{ext}"
    decoded_path  = TEMP_DIR / f"_bench_{codec_name}_dec.yuv"
    decoded_ref   = TEMP_DIR / f"_bench_{codec_name}_ref.yuv"   # for lossless check

    row = {c: "" for c in CSV_COLUMNS}
    row["codec"] = codec_name

    try:
        # ── 1. Build encode command ──────────────────────────────────────
        if codec_name == "REEL":
            encode_cmd = [
                reel_exe, "encode",
                str(yuv_path), str(encoded_path),
                "--width", str(width), "--height", str(height),
                "--fps-num", str(fps_num), "--fps-den", str(fps_den),
                "--total-frames", str(total_frames),
                "--quiet",
            ]
        elif codec_name == "FFV1":
            encode_cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
                "-r", fps_str, "-i", str(yuv_path),
                "-c:v", "ffv1", "-level", "3", "-g", "1", "-slices", "24",
                "-slicecrc", "1",
                "-pix_fmt", pix_fmt,
                str(encoded_path),
            ]
        elif codec_name.startswith("ProRes"):
            profile = codec_cfg.get("profile", "2")
            encode_cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
                "-r", fps_str, "-i", str(yuv_path),
                "-c:v", "prores_ks", "-profile:v", profile,
                "-pix_fmt", pix_fmt,
                str(encoded_path),
            ]
        elif codec_name == "HuffYUV":
            encode_cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
                "-r", fps_str, "-i", str(yuv_path),
                "-c:v", "huffyuv", "-pix_fmt", pix_fmt,
                str(encoded_path),
            ]
        elif codec_name == "Ut_Video":
            encode_cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
                "-r", fps_str, "-i", str(yuv_path),
                "-c:v", "utvideo", "-pix_fmt", pix_fmt,
                str(encoded_path),
            ]
        elif codec_name == "Lagarith":
            encode_cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", size_str,
                "-r", fps_str, "-i", str(yuv_path),
                "-c:v", "lagarith", "-pix_fmt", pix_fmt,
                str(encoded_path),
            ]
        else:
            raise ValueError(f"Unknown codec: {codec_name}")

        # ── 2. Encode ────────────────────────────────────────────────────
        enc_result: TimedResult = timed_run(encode_cmd, label=f"encode:{codec_name}")
        if enc_result.returncode != 0:
            print(f"    ✗ Encode failed ({codec_name}): {enc_result.stderr[-200:]}")
            return row
        if not encoded_path.exists() or encoded_path.stat().st_size == 0:
            print(f"    ✗ Encoded file missing/empty ({codec_name})")
            return row

        encoded_size  = file_size_bytes(encoded_path)
        raw_yuv_size  = file_size_bytes(yuv_path)
        fps_float     = fps_num / fps_den
        duration_s    = total_frames / fps_float

        enc_wall = max(enc_result.wall_time, 1e-6)
        enc_fps  = total_frames / enc_wall

        # ── 3. Build decode command ──────────────────────────────────────
        if codec_name == "REEL":
            decode_cmd = [
                reel_exe, "decode",
                str(encoded_path), str(decoded_path),
                "--quiet",
            ]
        else:
            # For all FFmpeg codecs, decode back to yuv420p
            decode_cmd = [
                "ffmpeg", "-y",
                "-i", str(encoded_path),
                "-f", "rawvideo", "-pix_fmt", "yuv420p",
                str(decoded_path),
            ]

        # ── 4. Decode ────────────────────────────────────────────────────
        dec_result: TimedResult = timed_run(decode_cmd, label=f"decode:{codec_name}")
        if dec_result.returncode != 0:
            print(f"    ✗ Decode failed ({codec_name}): {dec_result.stderr[-200:]}")
            safe_delete(encoded_path)
            return row

        dec_wall = max(dec_result.wall_time, 1e-6)
        dec_fps  = total_frames / dec_wall

        # ── 5. Lossless check ────────────────────────────────────────────
        is_lossless = False
        if codec_name in ("REEL", "FFV1", "Ut_Video", "Lagarith"):
            # These should be bit-exact; check directly
            is_lossless = files_identical(yuv_path, decoded_path)
        else:
            # ProRes / HuffYUV involve chroma upsampling; not expected to be bit-exact
            is_lossless = False

        # ── 6. PSNR / SSIM ──────────────────────────────────────────────
        psnr_y = psnr_u = psnr_v = ssim = float("inf")
        if compute_quality and decoded_path.exists():
            psnr_y, psnr_u, psnr_v, ssim = compute_psnr_ssim(
                yuv_path, decoded_path, width, height
            )

        # ── 7. Random frame access latency ──────────────────────────────
        latencies_ms: list[float] = []
        if codec_name == "REEL":
            frame_indices = random.sample(
                range(total_frames), min(RANDOM_FRAME_COUNT, total_frames)
            )
            tmp_single = TEMP_DIR / "_bench_reel_single.yuv"
            for idx in frame_indices:
                t0 = time.perf_counter()
                r = subprocess.run(
                    [reel_exe, "decode", str(encoded_path), str(tmp_single),
                     "--frame", str(idx), "--quiet"],
                    capture_output=True,
                )
                t1 = time.perf_counter()
                if r.returncode == 0:
                    elapsed_ms = (t1 - t0) * 1000.0
                    overhead_ms = process_overhead.get("reel", 0) * 1000.0
                    latencies_ms.append(max(elapsed_ms - overhead_ms, 0.0))
                safe_delete(tmp_single)
        else:
            # FFmpeg seek-based random access
            frame_indices = random.sample(
                range(total_frames), min(RANDOM_FRAME_COUNT, total_frames)
            )
            tmp_single = TEMP_DIR / "_bench_ff_single.yuv"
            for idx in frame_indices:
                seek_time = idx / fps_float
                t0 = time.perf_counter()
                r = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-ss", f"{seek_time:.6f}",
                        "-i", str(encoded_path),
                        "-vframes", "1",
                        "-f", "rawvideo", "-pix_fmt", "yuv420p",
                        str(tmp_single),
                    ],
                    capture_output=True,
                )
                t1 = time.perf_counter()
                if r.returncode == 0 and tmp_single.exists():
                    elapsed_ms = (t1 - t0) * 1000.0
                    overhead_ms = process_overhead.get("ffmpeg", 0) * 1000.0
                    latencies_ms.append(max(elapsed_ms - overhead_ms, 0.0))
                safe_delete(tmp_single)

        lat_stats = compute_latency_stats(latencies_ms)

        # ── 8. Assemble row ──────────────────────────────────────────────
        compression_ratio = raw_yuv_size / encoded_size if encoded_size > 0 else 0
        space_savings     = (1 - encoded_size / raw_yuv_size) * 100 if raw_yuv_size > 0 else 0
        bitrate_mbps      = (encoded_size * 8) / (duration_s * 1e6) if duration_s > 0 else 0
        bpp               = (encoded_size * 8) / (total_frames * width * height) if (total_frames * width * height) > 0 else 0

        enc_tput = raw_yuv_size / enc_wall / (1024 * 1024)
        dec_tput = raw_yuv_size / dec_wall / (1024 * 1024)
        enc_rt   = enc_fps / fps_float
        dec_rt   = dec_fps / fps_float

        row.update({
            "raw_yuv_size_bytes":       raw_yuv_size,
            "encoded_size_bytes":       encoded_size,
            "compression_ratio":        round(compression_ratio, 4),
            "space_savings_pct":        round(space_savings, 2),
            "encode_wall_time_s":       round(enc_result.wall_time, 4),
            "encode_cpu_time_s":        round(enc_result.cpu_time, 4),
            "decode_wall_time_s":       round(dec_result.wall_time, 4),
            "decode_cpu_time_s":        round(dec_result.cpu_time, 4),
            "encode_fps":               round(enc_fps, 2),
            "decode_fps":               round(dec_fps, 2),
            "encode_realtime_ratio":    round(enc_rt, 4),
            "decode_realtime_ratio":    round(dec_rt, 4),
            "encode_peak_memory_mb":    round(enc_result.peak_memory_mb, 2),
            "decode_peak_memory_mb":    round(dec_result.peak_memory_mb, 2),
            "encode_throughput_mbps":   round(enc_tput, 2),
            "decode_throughput_mbps":   round(dec_tput, 2),
            "bitrate_mbps":             round(bitrate_mbps, 4),
            "bits_per_pixel":           round(bpp, 6),
            "is_lossless":              is_lossless,
            "psnr_y":                   psnr_y,
            "psnr_u":                   psnr_u,
            "psnr_v":                   psnr_v,
            "ssim":                     ssim,
            "rand_frame_decode_avg_ms": round(lat_stats["avg"],    3),
            "rand_frame_decode_p50_ms": round(lat_stats["p50"],    3),
            "rand_frame_decode_p95_ms": round(lat_stats["p95"],    3),
            "rand_frame_decode_p99_ms": round(lat_stats["p99"],    3),
            "rand_frame_decode_min_ms": round(lat_stats["min"],    3),
            "rand_frame_decode_max_ms": round(lat_stats["max"],    3),
            "rand_frame_decode_stddev_ms": round(lat_stats["stddev"], 3),
            "timestamp":                time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    finally:
        safe_delete(encoded_path)
        safe_delete(decoded_path)

    return row


# ─── Per-video pipeline ─────────────────────────────────────────────────────

def probe_mp4(mp4_path: Path):
    """Returns (width, height, fps_num, fps_den). Falls back to 1920x1080@30."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "csv=s=x:p=0", str(mp4_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split("x")
            w, h = int(parts[0]), int(parts[1])
            fps_str = parts[2]
            if "/" in fps_str:
                num, den = map(int, fps_str.split("/"))
            else:
                num = int(float(fps_str) * 1000)
                den = 1000
            return w, h, num, den
    except Exception as e:
        print(f"    Warning: probe failed for {mp4_path.name}: {e}")
    return 1920, 1080, 30000, 1001


def run_video(
    video_id: int,
    mp4_path: Path,
    reel_exe: str,
    codecs_to_run: dict,
    done_codecs: set,
    compute_quality: bool,
    process_overhead: dict,
) -> list[dict]:
    """Full pipeline for one MP4. Returns list of result rows (one per codec)."""
    print(f"\n[{video_id:>4}] {mp4_path.name}")

    # ── Probe ──────────────────────────────────────────────────────────
    raw_w, raw_h, fps_num, fps_den = probe_mp4(mp4_path)
    # Round to even (YUV420p requirement)
    width  = raw_w - (raw_w % 2)
    height = raw_h - (raw_h % 2)
    fps_float = fps_num / fps_den
    print(f"         {width}x{height}  {fps_num}/{fps_den} fps")

    # ── Resolution label ───────────────────────────────────────────────
    res_map = {
        (256, 144): "144p", (426, 240): "240p", (640, 360): "360p",
        (854, 480): "480p", (1280, 720): "720p", (1920, 1080): "1080p",
        (2560, 1440): "1440p", (3840, 2160): "4k",
    }
    resolution = res_map.get((width, height), f"{width}x{height}")

    # ── Extract YUV (shared across all codecs for this video) ──────────
    yuv_path = TEMP_DIR / f"_bench_{video_id}.yuv"
    print(f"         Extracting YUV ...", end=" ", flush=True)
    t0 = time.perf_counter()
    ok = mp4_to_yuv(mp4_path, yuv_path, width, height)
    if not ok:
        print(f"\n    ✗ YUV extraction failed — skipping {mp4_path.name}")
        safe_delete(yuv_path)
        return []
    total_frames = count_yuv_frames(yuv_path, width, height)
    if total_frames == 0:
        print(f"\n    ✗ Zero frames extracted — skipping")
        safe_delete(yuv_path)
        return []
    print(f"{total_frames} frames in {time.perf_counter()-t0:.1f}s")

    rows = []
    base_row = {
        "video_id":   video_id,
        "video_file": mp4_path.name,
        "resolution": resolution,
        "width":      width,
        "height":     height,
        "fps_num":    fps_num,
        "fps_den":    fps_den,
        "motion_type": "",   # unknown for real videos
        "color_type":  "",
    }

    try:
        for codec_name, codec_cfg in codecs_to_run.items():
            if codec_name in done_codecs:
                print(f"         [SKIP] {codec_name} (already in CSV)")
                continue

            print(f"         [{codec_name:<12}] ", end="", flush=True)
            t_codec = time.perf_counter()

            row = benchmark_codec(
                codec_name, codec_cfg,
                yuv_path, width, height, fps_num, fps_den, total_frames,
                reel_exe, compute_quality, process_overhead,
            )
            elapsed = time.perf_counter() - t_codec

            if row.get("encode_fps"):
                rand_ms = row.get("rand_frame_decode_avg_ms", 0)
                print(f"enc {row['encode_fps']:.0f}fps  "
                      f"dec {row['decode_fps']:.0f}fps  "
                      f"ratio {row['compression_ratio']:.2f}x  "
                      f"rand {rand_ms:.1f}ms  "
                      f"({elapsed:.1f}s)")
            else:
                print("FAILED")

            row.update(base_row)
            rows.append(row)

    finally:
        # ── Delete YUV — this is the key step ─────────────────────────
        safe_delete(yuv_path)
        print(f"         YUV deleted.")

    return rows


# ─── Existing results loader ─────────────────────────────────────────────────

def load_done_pairs(csv_path: Path) -> set:
    """Returns set of (video_file, codec) tuples already in CSV."""
    done = set()
    if not csv_path.exists():
        return done
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            vf = row.get("video_file", "")
            cd = row.get("codec", "")
            if vf and cd:
                done.add((vf, cd))
    return done


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="REEL Benchmark Runner")
    parser.add_argument("--input-dir",    default=None,
                        help="Directory of .mp4 files (default: videos/mp4)")
    parser.add_argument("--reel-exe",     default=None,
                        help="Path to aurx binary")
    parser.add_argument("--workers",      type=int, default=1,
                        help="Parallel video workers (default: 1)")
    parser.add_argument("--skip-codecs",  default="",
                        help="Comma-separated codec names to skip")
    parser.add_argument("--resume",       action="store_true",
                        help="Skip (video, codec) pairs already in CSV")
    parser.add_argument("--max-videos",   type=int, default=None,
                        help="Process at most N videos")
    parser.add_argument("--no-psnr",      action="store_true",
                        help="Skip PSNR/SSIM (faster)")
    args = parser.parse_args()

    base_dir   = Path(__file__).parent
    input_dir  = Path(args.input_dir) if args.input_dir else base_dir / "videos" / "mp4"
    reel_exe   = find_reel_exe(args.reel_exe)
    skip_set   = {c.strip() for c in args.skip_codecs.split(",") if c.strip()}
    compute_q  = not args.no_psnr

    print("=" * 70)
    print("  REEL Benchmark Runner")
    print("=" * 70)

    # ── Preflight checks ───────────────────────────────────────────────
    check_ffmpeg()
    check_reel(reel_exe)

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = setup_csv(CSV_PATH)

    # ── Collect codecs ─────────────────────────────────────────────────
    codecs_to_run = {k: v for k, v in CODECS.items() if k not in skip_set}
    print(f"  Codecs     : {', '.join(codecs_to_run)}")

    # ── Collect videos ─────────────────────────────────────────────────
    if not input_dir.exists():
        print(f"\nERROR: Input directory not found: {input_dir}")
        print("Run downloader.py first.")
        sys.exit(1)

    mp4_files = sorted(input_dir.glob("*.mp4"))
    if not mp4_files:
        print(f"\nERROR: No .mp4 files found in {input_dir}")
        sys.exit(1)

    if args.max_videos:
        mp4_files = mp4_files[:args.max_videos]

    print(f"  Videos     : {len(mp4_files)} MP4 files in {input_dir}")
    print(f"  Output CSV : {csv_path}")
    print(f"  REEL bin   : {reel_exe}")
    print(f"  PSNR/SSIM  : {'yes' if compute_q else 'no (--no-psnr)'}")
    print()

    # ── Calibrate OS spawn overhead ────────────────────────────────────
    print("Calibrating ...")
    process_overhead = calibrate_process_overhead(reel_exe)
    print()

    # ── System info ────────────────────────────────────────────────────
    sys_info = collect_system_info(reel_exe)
    save_system_info(sys_info)

    # ── Load already-done pairs for --resume ───────────────────────────
    done_pairs = load_done_pairs(csv_path) if args.resume else set()

    # ── Run ────────────────────────────────────────────────────────────
    t_start   = time.perf_counter()
    total_rows = 0

    for video_id, mp4_path in enumerate(mp4_files):
        done_codecs_for_video = {
            codec for (vf, codec) in done_pairs if vf == mp4_path.name
        }

        rows = run_video(
            video_id       = video_id,
            mp4_path       = mp4_path,
            reel_exe       = reel_exe,
            codecs_to_run  = codecs_to_run,
            done_codecs    = done_codecs_for_video,
            compute_quality= compute_q,
            process_overhead= process_overhead,
        )

        if rows:
            append_to_csv(csv_path, rows)
            total_rows += len(rows)

    elapsed = time.perf_counter() - t_start
    print()
    print("=" * 70)
    print(f"  Done. {total_rows} rows written in {elapsed/60:.1f} min")
    print(f"  CSV : {csv_path}")
    print("=" * 70)
    print()
    print("Run analyze_results.py to generate charts and report.")


if __name__ == "__main__":
    main()