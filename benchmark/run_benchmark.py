#!/usr/bin/env python3
"""
REEL Codec Benchmark — Main Orchestrator
=========================================
For each of 150 videos, runs the full pipeline:

  MP4 -> YUV420p -> [FFV1 | ProRes HQ/HD/Std | REEL] -> YUV420p
                          + random frame decode
                          + bit-exact / PSNR / SSIM verification
                          + cleanup after each video

Results are written incrementally to CSV (crash-safe).

Usage:
    python benchmark/run_benchmark.py
    python benchmark/run_benchmark.py --smoke-test
    python benchmark/run_benchmark.py --reel-path c:\\aura\\target\\release\\reel.exe
    python benchmark/run_benchmark.py --resume
"""

import os
import sys
import csv
import random
import argparse
import time
from pathlib import Path
from datetime import datetime

from config import (
    CODECS, VIDEOS_DIR, RESULTS_DIR, TEMP_DIR, CSV_PATH,
    MANIFEST_PATH, VIDEO_DURATION, VIDEO_FPS,
    RANDOM_FRAME_COUNT, RANDOM_SEED, SYSTEM_INFO_PATH,
)
from utils import (
    timed_run, timed_run_fast, safe_delete, file_size_bytes,
    yuv_frame_size, files_identical, compute_psnr_ssim,
    compute_latency_stats, setup_csv, append_to_csv,
    collect_system_info, save_system_info,
    check_ffmpeg, check_reel, CSV_COLUMNS,
)


# ────────────────────────────────────────────────────────────────────
#  Encoding helpers
# ────────────────────────────────────────────────────────────────────

def mp4_to_yuv(mp4_path, yuv_path):
    """Convert MP4 -> raw YUV420p via FFmpeg."""
    return timed_run([
        "ffmpeg", "-y", "-i", str(mp4_path),
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        str(yuv_path),
    ], label="MP4->YUV")


def encode_ffv1(yuv_path, output_path, width, height, fps):
    """YUV420p -> FFV1 (lossless, intra-only, GOP=1)."""
    return timed_run([
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", str(yuv_path),
        "-c:v", "ffv1", "-level", "3", "-g", "1",
        str(output_path),
    ], label="Encode FFV1")


def encode_prores(yuv_path, output_path, width, height, profile, fps):
    """YUV420p -> ProRes (converts to yuv422p10le internally)."""
    return timed_run([
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", str(yuv_path),
        "-c:v", "prores_ks", "-profile:v", profile,
        "-pix_fmt", "yuv422p10le",
        str(output_path),
    ], label=f"Encode ProRes (profile {profile})")


def encode_reel(yuv_path, output_path, width, height, reel_exe, fps):
    """YUV420p -> REEL (.reel) format."""
    # REEL CLI expects fps as num/den; assume integer for now
    fps_int = int(round(fps))
    return timed_run([
        reel_exe, "encode",
        str(yuv_path), str(output_path),
        "--width", str(width), "--height", str(height),
        "--fps-num", str(fps_int), "--fps-den", "1",
    ], label="Encode REEL")


def encode_huffyuv(yuv_path, output_path, width, height, fps):
    """YUV420p -> HuffYUV (requires yuv422p or rgb24)."""
    return timed_run([
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", str(yuv_path),
        "-c:v", "huffyuv", "-pix_fmt", "yuv422p",
        str(output_path),
    ], label="Encode HuffYUV")


def encode_utvideo(yuv_path, output_path, width, height, fps):
    """YUV420p -> Ut Video."""
    return timed_run([
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", str(yuv_path),
        "-c:v", "utvideo",
        str(output_path),
    ], label="Encode Ut Video")


def encode_lagarith(yuv_path, output_path, width, height, fps):
    """YUV420p -> Lagarith."""
    return timed_run([
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", str(yuv_path),
        "-c:v", "lagarith",
        str(output_path),
    ], label="Encode Lagarith")


def decode_ffmpeg(input_path, output_path):
    """Decode FFV1/ProRes -> raw YUV420p."""
    return timed_run([
        "ffmpeg", "-y", "-i", str(input_path),
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        str(output_path),
    ], label="Decode (FFmpeg)")


def decode_reel_full(input_path, output_path, reel_exe):
    """Decode REEL -> raw YUV420p (all frames)."""
    return timed_run([
        reel_exe, "decode", str(input_path), str(output_path),
    ], label="Decode REEL")


# ────────────────────────────────────────────────────────────────────
#  Codec dispatch
# ────────────────────────────────────────────────────────────────────

def encode_with_codec(codec_name, yuv_path, output_path, width, height, reel_exe, fps):
    """Dispatch encoding to the appropriate codec handler."""
    cfg = CODECS[codec_name]
    if codec_name == "FFV1":
        return encode_ffv1(yuv_path, output_path, width, height, fps)
    elif codec_name.startswith("ProRes"):
        return encode_prores(yuv_path, output_path, width, height, cfg["profile"], fps)
    elif codec_name == "REEL":
        return encode_reel(yuv_path, output_path, width, height, reel_exe, fps)
    elif codec_name == "HuffYUV":
        return encode_huffyuv(yuv_path, output_path, width, height, fps)
    elif codec_name == "Ut_Video":
        return encode_utvideo(yuv_path, output_path, width, height, fps)
    elif codec_name == "Lagarith":
        return encode_lagarith(yuv_path, output_path, width, height, fps)
    else:
        raise ValueError(f"Unknown codec: {codec_name}")


def decode_with_codec(codec_name, input_path, output_path, reel_exe):
    """Dispatch decoding to the appropriate handler."""
    if codec_name == "REEL":
        return decode_reel_full(input_path, output_path, reel_exe)
    else:
        return decode_ffmpeg(input_path, output_path)


# ────────────────────────────────────────────────────────────────────
#  Random frame decode
# ────────────────────────────────────────────────────────────────────

def random_frame_decode(codec_name, input_path, width, height,
                        total_frames, reel_exe, temp_out):
    """
    Decode RANDOM_FRAME_COUNT random frames and measure per-frame latency.
    REEL uses O(1) OIT access; FFV1/ProRes use FFmpeg seek.
    """
    rng = random.Random(42)
    n = min(RANDOM_FRAME_COUNT, total_frames)
    indices = sorted(rng.sample(range(total_frames), n))
    latencies = []

    for idx in indices:
        safe_delete(temp_out)

        if codec_name == "REEL":
            cmd = [reel_exe, "decode", str(input_path), str(temp_out),
                   "--frame", str(idx)]
        else:
            frame_time = idx / VIDEO_FPS
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{frame_time:.6f}",
                "-i", str(input_path),
                "-frames:v", "1",
                "-f", "rawvideo", "-pix_fmt", "yuv420p",
                str(temp_out),
            ]

        elapsed, rc = timed_run_fast(cmd)
        if rc == 0:
            latencies.append(elapsed * 1000.0)  # -> milliseconds
        safe_delete(temp_out)

    return compute_latency_stats(latencies)


# ────────────────────────────────────────────────────────────────────
#  Result row builder
# ────────────────────────────────────────────────────────────────────

def build_result_row(video, codec_name, raw_size, encoded_size,
                     enc, dec, is_lossless,
                     psnr_y, psnr_u, psnr_v, ssim_val,
                     rand_stats, total_frames):
    """Assemble a single CSV row dict."""
    fps = video.get("fps", VIDEO_FPS)
    duration = total_frames / fps if fps > 0 else 0

    enc_fps = total_frames / enc.wall_time if enc.wall_time > 0 else 0
    dec_fps = total_frames / dec.wall_time if dec.wall_time > 0 else 0

    comp = raw_size / encoded_size if encoded_size > 0 else 0
    savings = (1 - encoded_size / raw_size) * 100 if raw_size > 0 else 0

    enc_rt = duration / enc.wall_time if enc.wall_time > 0 else 0
    dec_rt = duration / dec.wall_time if dec.wall_time > 0 else 0

    raw_mb = raw_size / (1024 * 1024)
    enc_tp = raw_mb / enc.wall_time if enc.wall_time > 0 else 0
    dec_tp = raw_mb / dec.wall_time if dec.wall_time > 0 else 0

    bitrate = (encoded_size * 8) / duration / 1_000_000 if duration > 0 else 0
    px = video["width"] * video["height"]
    bpp = (encoded_size * 8) / (total_frames * px) if total_frames > 0 and px > 0 else 0

    def fmt_psnr(v):
        return "inf" if v == float("inf") else f"{v:.2f}"

    return {
        "video_id": video["video_id"],
        "video_file": video["filename"],
        "resolution": video["resolution"],
        "width": video["width"],
        "height": video["height"],
        "motion_type": video["motion"],
        "color_type": video["color"],
        "codec": codec_name,
        "raw_yuv_size_bytes": raw_size,
        "encoded_size_bytes": encoded_size,
        "compression_ratio": f"{comp:.4f}",
        "space_savings_pct": f"{savings:.2f}",
        "encode_wall_time_s": f"{enc.wall_time:.4f}",
        "encode_cpu_time_s": f"{enc.cpu_time:.4f}",
        "decode_wall_time_s": f"{dec.wall_time:.4f}",
        "decode_cpu_time_s": f"{dec.cpu_time:.4f}",
        "encode_fps": f"{enc_fps:.2f}",
        "decode_fps": f"{dec_fps:.2f}",
        "encode_realtime_ratio": f"{enc_rt:.4f}",
        "decode_realtime_ratio": f"{dec_rt:.4f}",
        "encode_peak_memory_mb": f"{enc.peak_memory_mb:.2f}",
        "decode_peak_memory_mb": f"{dec.peak_memory_mb:.2f}",
        "encode_throughput_mbps": f"{enc_tp:.2f}",
        "decode_throughput_mbps": f"{dec_tp:.2f}",
        "bitrate_mbps": f"{bitrate:.4f}",
        "bits_per_pixel": f"{bpp:.6f}",
        "is_lossless": is_lossless,
        "psnr_y": fmt_psnr(psnr_y),
        "psnr_u": fmt_psnr(psnr_u),
        "psnr_v": fmt_psnr(psnr_v),
        "ssim": f"{ssim_val:.6f}",
        "rand_frame_decode_avg_ms": f"{rand_stats['avg']:.3f}",
        "rand_frame_decode_p50_ms": f"{rand_stats['p50']:.3f}",
        "rand_frame_decode_p95_ms": f"{rand_stats['p95']:.3f}",
        "rand_frame_decode_p99_ms": f"{rand_stats['p99']:.3f}",
        "rand_frame_decode_min_ms": f"{rand_stats['min']:.3f}",
        "rand_frame_decode_max_ms": f"{rand_stats['max']:.3f}",
        "rand_frame_decode_stddev_ms": f"{rand_stats['stddev']:.3f}",
        "timestamp": datetime.now().isoformat(),
    }


# ────────────────────────────────────────────────────────────────────
#  Per-video pipeline
# ────────────────────────────────────────────────────────────────────

def process_video(video, reel_exe, csv_path):
    """
    Full pipeline for a single video:
      MP4 -> YUV420p -> encode -> decode -> verify -> random-access -> cleanup
    Intermediate files are deleted after each codec and after the video.
    """
    if Path(video["filename"]).is_absolute():
        video_path = Path(video["filename"])
    else:
        video_path = VIDEOS_DIR / video["filename"]
    width = video["width"]
    height = video["height"]

    if not video_path.exists():
        print(f"  WARNING: Video not found: {video_path}")
        return

    os.makedirs(TEMP_DIR, exist_ok=True)
    raw_yuv = TEMP_DIR / "raw.yuv"

    try:
        # ── Step 1: MP4 -> YUV420p ──────────────────────────────────
        print("  [1] MP4 -> YUV420p ...", end=" ", flush=True)
        mp4_res = mp4_to_yuv(video_path, raw_yuv)
        if mp4_res.returncode != 0:
            print(f"FAILED (exit {mp4_res.returncode})")
            if mp4_res.stderr:
                print(f"      Error Details:\n{mp4_res.stderr}")
            return
        raw_size = file_size_bytes(raw_yuv)
        frame_size = yuv_frame_size(width, height)
        total_frames = raw_size // frame_size
        print(f"OK ({raw_size / (1024*1024):.1f} MB, {total_frames} frames)")

        results = []

        # ── Step 2: Per-codec benchmark ─────────────────────────────
        for codec_name, codec_cfg in CODECS.items():
            encoded_file = TEMP_DIR / f"encoded{codec_cfg['ext']}"
            decoded_yuv = TEMP_DIR / "decoded.yuv"
            rand_yuv = TEMP_DIR / "rand_frame.yuv"

            try:
                # Encode
                print(f"  [{codec_name:12s}] Encode  ...", end=" ", flush=True)
                fps = video.get("fps", VIDEO_FPS)
                enc = encode_with_codec(
                    codec_name, raw_yuv, encoded_file, width, height, reel_exe, fps
                )
                if enc.returncode != 0:
                    print("FAILED")
                    if enc.stderr:
                        print(f"      Encode Error:\n{enc.stderr}")
                    continue
                enc_size = file_size_bytes(encoded_file)
                ratio = raw_size / enc_size if enc_size > 0 else 0
                print(f"OK  {enc_size/(1024*1024):8.1f} MB  "
                      f"{ratio:5.2f}x  {enc.wall_time:.2f}s")

                # Decode
                print(f"  [{codec_name:12s}] Decode  ...", end=" ", flush=True)
                dec = decode_with_codec(
                    codec_name, encoded_file, decoded_yuv, reel_exe
                )
                if dec.returncode != 0:
                    print("FAILED")
                    if dec.stderr:
                        print(f"      Decode Error:\n{dec.stderr}")
                    continue
                print(f"OK  {dec.wall_time:.2f}s")

                # Lossless check
                print(f"  [{codec_name:12s}] Verify  ...", end=" ", flush=True)
                is_lossless = files_identical(str(raw_yuv), str(decoded_yuv))
                print("LOSSLESS" if is_lossless else "LOSSY")

                # PSNR / SSIM
                print(f"  [{codec_name:12s}] Quality ...", end=" ", flush=True)
                psnr_y, psnr_u, psnr_v, ssim_val = compute_psnr_ssim(
                    raw_yuv, decoded_yuv, width, height
                )
                print(f"OK  SSIM={ssim_val:.4f}")

                # Random frame decode
                print(f"  [{codec_name:12s}] Random  ...", end=" ", flush=True)
                rand_stats = random_frame_decode(
                    codec_name, encoded_file, width, height,
                    total_frames, reel_exe, rand_yuv
                )
                print(f"OK  avg={rand_stats['avg']:.1f}ms  "
                      f"p95={rand_stats['p95']:.1f}ms")

                # Build result
                print(f"  [{codec_name:12s}] Saving  ...", end=" ", flush=True)
                row = build_result_row(
                    video, codec_name, raw_size, enc_size,
                    enc, dec, is_lossless,
                    psnr_y, psnr_u, psnr_v, ssim_val,
                    rand_stats, total_frames,
                )
                results.append(row)
                print("OK")

            finally:
                # Cleanup encoded + decoded after each codec
                print(f"  [{codec_name:12s}] Cleanup ...", end=" ", flush=True)
                safe_delete(encoded_file)
                safe_delete(decoded_yuv)
                safe_delete(rand_yuv)
                print("OK")

        # Write results for this video (crash-safe)
        if results:
            append_to_csv(csv_path, results)

    finally:
        # Cleanup raw YUV after all codecs are done for this video
        print("  [Cleanup     ] Removing raw YUV ...", end=" ", flush=True)
        safe_delete(raw_yuv)
        print("OK")


# ────────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="REEL Codec Benchmark — Compare REEL vs FFV1 vs ProRes"
    )
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Run only 3 videos for quick validation"
    )
    parser.add_argument(
        "--reel-path", type=str, default=None,
        help="Path to reel.exe (will prompt if not provided)"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip already-processed videos (based on existing CSV)"
    )
    parser.add_argument(
        "--input-dir", type=str, default=None,
        help="Path to a directory containing custom videos (.mp4, .mkv) to benchmark"
    )
    args = parser.parse_args()

    print()
    print("=" * 70)
    print("  REEL Codec Benchmarking Pipeline")
    print("  Codecs: REEL | FFV1 | ProRes HQ | ProRes HD | ProRes Standard")
    print("=" * 70)
    print()

    # ── Get REEL executable path ────────────────────────────────────
    reel_exe = args.reel_path
    if not reel_exe:
        reel_exe = input(
            "Enter path to REEL executable\n"
            "  (e.g. c:\\aura\\target\\release\\reel.exe): "
        ).strip().strip('"').strip("'")
        if not reel_exe:
            print("No path provided. Exiting.")
            sys.exit(1)

    if not os.path.isfile(reel_exe):
        print(f"Error: REEL executable not found at: {reel_exe}")
        sys.exit(1)

    # ── Get Custom Videos Directory ─────────────────────────────────
    user_input_dir = args.input_dir
    if not user_input_dir:
        ans = input(
            "\nEnter path to directory containing videos to benchmark\n"
            "  (Press Enter to use default 'benchmark/videos/'): "
        ).strip().strip('"').strip("'")
        if ans:
            user_input_dir = ans

    # ── Validate dependencies ───────────────────────────────────────
    print("Checking dependencies ...")
    check_ffmpeg()
    print("  [OK] FFmpeg")
    check_reel(reel_exe)
    print(f"  [OK] REEL: {reel_exe}")
    print()

    # ── Collect system info ─────────────────────────────────────────
    print("Collecting system info ...")
    sys_info = collect_system_info(reel_exe)
    save_system_info(sys_info)
    print()

    manifest = []
    input_dir = Path(user_input_dir) if user_input_dir else VIDEOS_DIR

    if user_input_dir or not MANIFEST_PATH.exists():
        if not input_dir.is_dir():
            print(f"Error: Directory not found: {input_dir}")
            sys.exit(1)
        print(f"Scanning directory for video files: {input_dir} ...")
        from utils import get_video_info
        video_id = 0
        valid_exts = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".m2ts", ".vob", ".vdo"]
        for f in sorted(input_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in valid_exts:
                w, h, fps = get_video_info(f)
                if w and h:
                    manifest.append({
                        "video_id": video_id,
                        "filename": str(f.resolve()),
                        "resolution": f"{w}x{h}",
                        "width": w,
                        "height": h,
                        "fps": fps,
                        "motion": "custom",
                        "color": "custom",
                        "seed": 0,
                    })
                    video_id += 1
        print(f"  Found {len(manifest)} videos automatically.\n")

    if not manifest and not user_input_dir and MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["video_id"] = int(row["video_id"])
                row["width"] = int(row["width"])
                row["height"] = int(row["height"])
                row["seed"] = int(row["seed"])
                row["fps"] = VIDEO_FPS
                manifest.append(row)

    if not manifest:
        print(f"Error: No videos found to benchmark in {input_dir}.")
        print("Place video files in the directory or run 'python benchmark/generate_videos.py'.")
        sys.exit(1)

    if args.smoke_test:
        manifest = manifest[:3]
        print(f"  SMOKE TEST: running {len(manifest)} videos only\n")

    # ── Resume support ──────────────────────────────────────────────
    processed_ids = set()
    if args.resume and CSV_PATH.exists():
        with open(CSV_PATH, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                processed_ids.add(int(row["video_id"]))
        print(f"  Resuming: {len(processed_ids)} videos already processed\n")

    # ── Setup output CSV ────────────────────────────────────────────
    csv_path = setup_csv()

    # ── Run benchmark ───────────────────────────────────────────────
    total = len(manifest)
    start_time = time.time()

    for i, video in enumerate(manifest):
        vid = video["video_id"]

        if vid in processed_ids:
            print(f"[{i+1}/{total}] SKIP video {vid} (already processed)")
            continue

        elapsed = time.time() - start_time
        if i > 0 and elapsed > 0:
            rate = elapsed / i
            eta = rate * (total - i)
            eta_str = f" | ETA: {eta/60:.0f} min"
        else:
            eta_str = ""

        pct = ((i + 1) / total) * 100

        print(f"\n{'─' * 70}")
        print(f"[{i+1}/{total} - {pct:.1f}%] {video['filename']}{eta_str}")
        print(f"  {video['resolution']} ({video['width']}x{video['height']})  "
              f"motion={video['motion']}  color={video['color']}")
        print(f"{'─' * 70}")

        process_video(video, reel_exe, csv_path)

    # ── Done ────────────────────────────────────────────────────────
    total_time = time.time() - start_time
    print(f"\n{'=' * 70}")
    print(f"  Benchmark complete!")
    print(f"  Total time: {total_time/60:.1f} minutes")
    print(f"  Results CSV: {csv_path}")
    print(f"  System info: {SYSTEM_INFO_PATH}")
    print(f"{'=' * 70}")
    print(f"\nNext step:  python benchmark/analyze_results.py")


if __name__ == "__main__":
    main()
