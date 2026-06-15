#!/usr/bin/env python3
"""
REEL Benchmark — MP4 Dataset Downloader (yt-dlp edition)
=========================================================
Downloads 54 public domain / CC-licensed videos from YouTube using yt-dlp,
spanning all resolution tiers (144p to 1080p) and content categories.

All videos are either:
  - Public domain (NASA, US govt)
  - CC BY / CC BY-SA licensed
  - Blender Foundation open movies (CC BY 3.0)

Prerequisites:
    pip install yt-dlp
    sudo apt install ffmpeg

Usage:
    python downloader.py
    python downloader.py --output-dir /path/to/videos
    python downloader.py --workers 2 --dry-run
"""

import os
import sys
import csv
import time
import argparse
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

DATASET = [
    # Blender Open Movies (CC BY 3.0) - best codec test content
    {"id": "bbb_1080p",     "res": "1080", "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"},
    {"id": "sintel_1080p",  "res": "1080", "cat": "animation",  "motion": "medium", "url": "https://www.youtube.com/watch?v=eRsGyueVLvQ"},
    {"id": "tos_1080p",     "res": "1080", "cat": "vfx",        "motion": "high",   "url": "https://www.youtube.com/watch?v=R6MlUcmOul8"},
    {"id": "cosmos_1080p",  "res": "1080", "cat": "animation",  "motion": "medium", "url": "https://www.youtube.com/watch?v=Y-rmzh0PI3c"},
    {"id": "caminandes",    "res": "1080", "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=SkVqJ1SGeL0"},
    {"id": "glass_half",    "res": "1080", "cat": "animation",  "motion": "medium", "url": "https://www.youtube.com/watch?v=Z4C82eyhwgU"},
    {"id": "elephants",     "res": "1080", "cat": "animation",  "motion": "medium", "url": "https://www.youtube.com/watch?v=TLkA0RELQ1g"},
    {"id": "hero_blender",  "res": "1080", "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=pKmSdY56VtY"},
    {"id": "sprite_fright", "res": "1080", "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=_cMxraX_5RE"},
    # NASA Public Domain
    {"id": "nasa_iss_1",    "res": "1080", "cat": "space",      "motion": "low",    "url": "https://www.youtube.com/watch?v=RtU_mdL2vBM"},
    {"id": "nasa_iss_2",    "res": "1080", "cat": "space",      "motion": "low",    "url": "https://www.youtube.com/watch?v=nPHegSslZGE"},
    {"id": "nasa_launch",   "res": "1080", "cat": "space",      "motion": "high",   "url": "https://www.youtube.com/watch?v=OnoNITE-CLc"},
    {"id": "nasa_mars",     "res": "1080", "cat": "space",      "motion": "low",    "url": "https://www.youtube.com/watch?v=4czjS9h4Fpg"},
    {"id": "nasa_aurora",   "res": "1080", "cat": "space",      "motion": "medium", "url": "https://www.youtube.com/watch?v=HsXbfCRqNrE"},
    {"id": "nasa_sun",      "res": "1080", "cat": "space",      "motion": "high",   "url": "https://www.youtube.com/watch?v=l2HNmCm_u3A"},
    # Nature / various motion levels
    {"id": "nature_ocean",  "res": "1080", "cat": "nature",     "motion": "medium", "url": "https://www.youtube.com/watch?v=LXb3EKWsInQ"},
    {"id": "nature_birds",  "res": "1080", "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=bnKpV60IOAI"},
    {"id": "nature_rain",   "res": "1080", "cat": "nature",     "motion": "low",    "url": "https://www.youtube.com/watch?v=yIQd2Ya0Ziw"},
    {"id": "nature_fire",   "res": "1080", "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=hAoMGSPJqMo"},
    {"id": "nature_snow",   "res": "1080", "cat": "nature",     "motion": "low",    "url": "https://www.youtube.com/watch?v=OBvXLb9Y8TQ"},
    {"id": "waterfall",     "res": "1080", "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=QX55pFBFXPo"},
    {"id": "ocean_waves",   "res": "1080", "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=_Oh8OPiZ5pU"},
    {"id": "traffic_tl",    "res": "1080", "cat": "urban",      "motion": "medium", "url": "https://www.youtube.com/watch?v=cFBfPMAvCCk"},
    {"id": "screen_code",   "res": "1080", "cat": "screencast", "motion": "low",    "url": "https://www.youtube.com/watch?v=zOjov-2OZ0E"},
    {"id": "screen_slides", "res": "1080", "cat": "screencast", "motion": "low",    "url": "https://www.youtube.com/watch?v=rfscVS0vtbw"},
    # 720p
    {"id": "720p_bbb",      "res": "720",  "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"},
    {"id": "720p_sintel",   "res": "720",  "cat": "animation",  "motion": "medium", "url": "https://www.youtube.com/watch?v=eRsGyueVLvQ"},
    {"id": "720p_ocean",    "res": "720",  "cat": "nature",     "motion": "medium", "url": "https://www.youtube.com/watch?v=LXb3EKWsInQ"},
    {"id": "720p_iss",      "res": "720",  "cat": "space",      "motion": "low",    "url": "https://www.youtube.com/watch?v=RtU_mdL2vBM"},
    {"id": "720p_traffic",  "res": "720",  "cat": "urban",      "motion": "high",   "url": "https://www.youtube.com/watch?v=cFBfPMAvCCk"},
    {"id": "720p_tos",      "res": "720",  "cat": "vfx",        "motion": "high",   "url": "https://www.youtube.com/watch?v=R6MlUcmOul8"},
    {"id": "720p_fire",     "res": "720",  "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=hAoMGSPJqMo"},
    # 480p
    {"id": "480p_bbb",      "res": "480",  "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"},
    {"id": "480p_iss",      "res": "480",  "cat": "space",      "motion": "low",    "url": "https://www.youtube.com/watch?v=nPHegSslZGE"},
    {"id": "480p_waterfall","res": "480",  "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=QX55pFBFXPo"},
    {"id": "480p_rain",     "res": "480",  "cat": "nature",     "motion": "low",    "url": "https://www.youtube.com/watch?v=yIQd2Ya0Ziw"},
    {"id": "480p_traffic",  "res": "480",  "cat": "urban",      "motion": "medium", "url": "https://www.youtube.com/watch?v=cFBfPMAvCCk"},
    {"id": "480p_sprite",   "res": "480",  "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=_cMxraX_5RE"},
    # 360p
    {"id": "360p_bbb",      "res": "360",  "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"},
    {"id": "360p_iss",      "res": "360",  "cat": "space",      "motion": "low",    "url": "https://www.youtube.com/watch?v=RtU_mdL2vBM"},
    {"id": "360p_ocean",    "res": "360",  "cat": "nature",     "motion": "medium", "url": "https://www.youtube.com/watch?v=LXb3EKWsInQ"},
    {"id": "360p_fire",     "res": "360",  "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=hAoMGSPJqMo"},
    {"id": "360p_sintel",   "res": "360",  "cat": "animation",  "motion": "medium", "url": "https://www.youtube.com/watch?v=eRsGyueVLvQ"},
    # 240p
    {"id": "240p_bbb",      "res": "240",  "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"},
    {"id": "240p_iss",      "res": "240",  "cat": "space",      "motion": "low",    "url": "https://www.youtube.com/watch?v=nPHegSslZGE"},
    {"id": "240p_waterfall","res": "240",  "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=QX55pFBFXPo"},
    {"id": "240p_snow",     "res": "240",  "cat": "nature",     "motion": "low",    "url": "https://www.youtube.com/watch?v=OBvXLb9Y8TQ"},
    # 144p
    {"id": "144p_bbb",      "res": "144",  "cat": "animation",  "motion": "high",   "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"},
    {"id": "144p_iss",      "res": "144",  "cat": "space",      "motion": "low",    "url": "https://www.youtube.com/watch?v=RtU_mdL2vBM"},
    {"id": "144p_fire",     "res": "144",  "cat": "nature",     "motion": "high",   "url": "https://www.youtube.com/watch?v=hAoMGSPJqMo"},
    {"id": "144p_rain",     "res": "144",  "cat": "nature",     "motion": "low",    "url": "https://www.youtube.com/watch?v=yIQd2Ya0Ziw"},
]

assert len(DATASET) >= 50, f"Only {len(DATASET)} entries"


def check_ytdlp():
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("ERROR: yt-dlp not found. Install with:  pip install yt-dlp")
        sys.exit(1)


def download_one(entry: dict, dest_dir: Path) -> tuple:
    vid_id   = entry["id"]
    res      = entry["res"]
    url      = entry["url"]
    out_path = dest_dir / f"{vid_id}.mp4"

    if out_path.exists() and out_path.stat().st_size > 10_000:
        return True, ""

    # Prefer h264+m4a in mp4 container at target height.
    # The postprocessor arg forces yuv420p so the benchmark always
    # gets a consistent pixel format without an extra ffmpeg pass.
    fmt = (
        f"bestvideo[height<={res}][ext=mp4][vcodec^=avc]+"
        f"bestaudio[ext=m4a]"
        f"/bestvideo[height<={res}][ext=mp4]+bestaudio"
        f"/best[height<={res}][ext=mp4]"
        f"/best[height<={res}]"
    )

    cmd = [
        "yt-dlp",
        "--format", fmt,
        "--merge-output-format", "mp4",
        "--postprocessor-args", "ffmpeg:-vf format=yuv420p -an",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        "--output", str(out_path),
        url,
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()[-200:]
        if not out_path.exists() or out_path.stat().st_size < 10_000:
            return False, "Output missing or too small"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Timeout (300s)"
    except Exception as e:
        return False, str(e)


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def download_all(dest_dir: Path, workers: int, dry_run: bool):
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = dest_dir / "manifest.csv"

    done = set()
    if manifest_path.exists():
        with open(manifest_path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("success") == "True":
                    done.add(row["id"])

    todo = [e for e in DATASET if e["id"] not in done]

    print("=" * 70)
    print("  REEL Benchmark — MP4 Dataset Downloader (yt-dlp)")
    print("=" * 70)
    print(f"  Total entries : {len(DATASET)}")
    print(f"  Already done  : {len(done)}")
    print(f"  To download   : {len(todo)}")
    print(f"  Destination   : {dest_dir}")
    print(f"  Workers       : {workers}")
    print()

    if dry_run:
        for e in todo:
            print(f"  {e['id']:25s}  {e['res']:4s}p  {e['motion']:6s}  {e['url']}")
        return

    write_header = not manifest_path.exists()
    completed = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, e, dest_dir): e for e in todo}
        for fut in as_completed(futures):
            entry = futures[fut]
            success, err = fut.result()
            completed[entry["id"]] = (success, err)

    ok_count = 0
    with open(manifest_path, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["id", "resolution", "category", "motion",
                        "path", "size_bytes", "success", "error"])
        for i, entry in enumerate(todo):
            vid_id = entry["id"]
            success, err = completed.get(vid_id, (False, "not run"))
            out_path = dest_dir / f"{vid_id}.mp4"
            size = out_path.stat().st_size if (success and out_path.exists()) else 0
            icon = "✓" if success else "✗"
            info = _human_size(size) if success else err[:70]
            print(f"  [{i+1:>3}/{len(todo)}] {icon} {vid_id:25s}  {info}")
            if success:
                ok_count += 1
            w.writerow([vid_id, entry["res"], entry["cat"], entry["motion"],
                        str(out_path) if success else "", size, success, err])

    total_ok = len(done) + ok_count
    print()
    print("=" * 70)
    print(f"  Done: {total_ok} / {len(DATASET)} videos")
    if total_ok < len(DATASET):
        print(f"  Failed: {len(DATASET) - total_ok} — re-run to retry")
    print(f"  Manifest: {manifest_path}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--workers", type=int, default=3,
                        help="Parallel downloads (default 3)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    check_ytdlp()
    base = Path(__file__).parent
    dest = Path(args.output_dir) if args.output_dir else base / "videos" / "mp4"
    download_all(dest, workers=args.workers, dry_run=args.dry_run)


if __name__ == "__main__":
    main()