#!/usr/bin/env python3
"""
REEL Benchmark — Video Corpus Generator
========================================
Generates 150 random synthetic test videos using FFmpeg lavfi sources.
Each video is a random combination of resolution x motion x color.

Usage:
    python benchmark/generate_videos.py
"""

import os
import sys
import csv
import random
import subprocess
from pathlib import Path
from collections import Counter

from config import (
    RESOLUTIONS, MOTION_TYPES, COLOR_TYPES, VIDEOS_DIR,
    MANIFEST_PATH, VIDEO_DURATION, VIDEO_FPS, RANDOM_SEED,
    generate_test_matrix,
)


def get_ffmpeg_filter(width, height, motion, color, seed):
    """
    Build an FFmpeg lavfi filter expression for a given video configuration.

    Motion controls the base source (static vs dynamic).
    Color controls post-processing (contrast, saturation, hue, etc.).
    """
    rng = random.Random(seed)

    # ── Base source by motion level ──────────────────────────────────
    if motion == "low":
        # Near-static content with minimal temporal change
        color_hex = f"0x{rng.randint(0, 0xFFFFFF):06X}"
        bases = [
            f"color=c={color_hex}:s={width}x{height}:d={VIDEO_DURATION}:r={VIDEO_FPS},"
            f"noise=alls=3:allf=t",
            f"smptebars=s={width}x{height}:d={VIDEO_DURATION}:r={VIDEO_FPS}",
            f"color=c=0x{rng.randint(0, 0xFFFFFF):06X}:s={width}x{height}:"
            f"d={VIDEO_DURATION}:r={VIDEO_FPS},noise=alls=5:allf=t",
            f"rgbtestsrc=s={width}x{height}:d={VIDEO_DURATION}:r={VIDEO_FPS}",
        ]
    elif motion == "medium":
        # Moderate motion — animated test patterns
        bases = [
            f"testsrc2=s={width}x{height}:d={VIDEO_DURATION}:r={VIDEO_FPS}",
            f"testsrc=s={width}x{height}:d={VIDEO_DURATION}:r={VIDEO_FPS}",
            f"testsrc2=s={width}x{height}:d={VIDEO_DURATION}:r={VIDEO_FPS},"
            f"noise=alls=15:allf=t",
        ]
    else:  # high
        # Fast, complex motion — fractal zoom, noise, game of life
        bases = [
            f"mandelbrot=s={width}x{height}:r={VIDEO_FPS}:end_scale=0.001",
            f"testsrc2=s={width}x{height}:d={VIDEO_DURATION}:r={VIDEO_FPS},"
            f"noise=alls=40:allf=t",
            f"life=s={width}x{height}:r={VIDEO_FPS}:mold=5:"
            f"death_color=red:life_color=green",
        ]

    base = rng.choice(bases)

    # ── Color / contrast modifier ────────────────────────────────────
    if color == "low_contrast":
        modifier = ",eq=contrast=0.3:brightness=0.05"
    elif color == "high_contrast":
        modifier = ",eq=contrast=2.5:brightness=-0.1"
    elif color == "vivid":
        modifier = ",eq=saturation=3.0:contrast=1.2"
    elif color == "monochrome":
        modifier = ",hue=s=0"
    elif color == "gradient":
        speed = rng.randint(10, 60)
        modifier = f",hue=H=t*{speed}"
    else:  # mixed
        sat = rng.uniform(0.5, 2.5)
        modifier = f",eq=contrast=1.5:saturation={sat:.1f}"

    return base + modifier


def generate_video(config, output_path):
    """Generate a single synthetic video using FFmpeg."""
    w = config["width"]
    h = config["height"]
    motion = config["motion"]
    color = config["color"]
    seed = config["seed"]

    filter_expr = get_ffmpeg_filter(w, h, motion, color, seed)

    # Sources without built-in duration need explicit -t
    needs_duration = ("mandelbrot" in filter_expr or "life" in filter_expr)

    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", filter_expr]

    if needs_duration:
        cmd.extend(["-t", str(VIDEO_DURATION)])

    cmd.extend([
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        str(output_path),
    ])

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=600
    )

    if result.returncode != 0:
        print(f"FAILED")
        # Show a compact error
        err_lines = result.stderr.strip().split("\n")
        for line in err_lines[-3:]:
            print(f"      {line}")
        return False

    return True


def main():
    print("=" * 65)
    print("  REEL Benchmark — Video Corpus Generator")
    print("=" * 65)
    print()

    # ── Generate test matrix ─────────────────────────────────────────
    matrix = generate_test_matrix()

    # ── Create output directory ──────────────────────────────────────
    os.makedirs(VIDEOS_DIR, exist_ok=True)

    # ── Check if all videos already exist ────────────────────────────
    existing = sum(1 for v in matrix if (VIDEOS_DIR / v["filename"]).exists())
    if existing == len(matrix):
        print(f"  All {len(matrix)} videos already exist. Skipping generation.")
        print(f"  Delete {VIDEOS_DIR} to regenerate.")
        return

    # ── Print corpus info ────────────────────────────────────────────
    print(f"  Generating {len(matrix)} test videos...")
    print(f"  Duration: {VIDEO_DURATION}s each @ {VIDEO_FPS} fps")
    print(f"  Seed: {RANDOM_SEED}")
    print()

    res_dist = Counter(v["resolution"] for v in matrix)
    mot_dist = Counter(v["motion"] for v in matrix)
    col_dist = Counter(v["color"] for v in matrix)

    print(f"  Resolution distribution: {dict(sorted(res_dist.items()))}")
    print(f"  Motion distribution:     {dict(mot_dist)}")
    print(f"  Color distribution:      {dict(col_dist)}")
    print()

    # ── Generate videos ──────────────────────────────────────────────
    success = 0
    failed = 0
    total = len(matrix)

    for i, config in enumerate(matrix):
        output_path = VIDEOS_DIR / config["filename"]

        if output_path.exists():
            print(f"  [{i+1:3d}/{total}] SKIP {config['filename']} (exists)")
            success += 1
            continue

        tag = (f"{config['resolution']}, {config['motion']}, "
               f"{config['color']}")
        print(f"  [{i+1:3d}/{total}] {config['filename']} "
              f"({tag}) ... ", end="", flush=True)

        if generate_video(config, output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"OK ({size_mb:.1f} MB)")
            success += 1
        else:
            failed += 1

    # ── Write manifest CSV ───────────────────────────────────────────
    with open(MANIFEST_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "video_id", "filename", "resolution", "width", "height",
            "motion", "color", "seed",
        ])
        writer.writeheader()
        for config in matrix:
            writer.writerow(config)

    print(f"\n{'=' * 65}")
    print(f"  Done! {success} generated, {failed} failed.")
    print(f"  Manifest: {MANIFEST_PATH}")
    print(f"  Videos:   {VIDEOS_DIR}")
    print(f"{'=' * 65}")


if __name__ == "__main__":
    main()
