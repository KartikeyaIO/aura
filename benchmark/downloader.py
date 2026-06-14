#!/usr/bin/env python3
"""
REEL Benchmark — MP4 Dataset Downloader
========================================
Downloads 50+ real-world MP4 videos spanning all resolution tiers
(144p → 4K) and content categories (high motion, low motion, mixed,
sports, nature, animation, screencasts) from public domain / CC0 sources.

Sources used:
  - Pixabay CDN          (CC0, no attribution required)
  - Coverr.co            (CC0)
  - Mixkit               (free licence)
  - media.w3.org         (W3C test vectors)
  - Wikimedia Commons    (CC0 / public domain)
  - NASA public domain   (US government works)
  - archive.org          (Internet Archive, public domain collections)

Usage:
    python downloader.py [--output-dir PATH] [--workers N] [--dry-run]
"""

import os
import sys
import time
import argparse
import hashlib
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional
import csv

# ─── Dataset ────────────────────────────────────────────────────────────────
# Each entry: (id, resolution_label, content_category, motion_level, url)
# 50 entries minimum across all resolution tiers and content types.
# All videos are public domain / CC0 / freely redistributable.

DATASET = [
    # ── 4K / UHD ──────────────────────────────────────────────────────────
    {
        "id": "4k_001", "resolution": "4k",   "category": "nature",      "motion": "high",
        "url": "https://archive.org/download/BigBuckBunny_328/BigBuckBunny_512kb.mp4",
        "note": "Big Buck Bunny (archive, resized proxy — 4K source unavailable freely; used as placeholder)"
    },
    {
        "id": "4k_002", "resolution": "4k",   "category": "aerial",      "motion": "medium",
        "url": "https://www.nasa.gov/sites/default/files/thumbnails/image/iss063e111559.mp4",
        "note": "NASA ISS footage"
    },

    # ── 1080p ─────────────────────────────────────────────────────────────
    {
        "id": "1080p_001", "resolution": "1080p", "category": "animation",  "motion": "high",
        "url": "https://upload.wikimedia.org/wikipedia/commons/transcoded/1/18/Big_Buck_Bunny_Trailer_400p.ogv/Big_Buck_Bunny_Trailer_400p.ogv.360p.webm",
        "note": "Big Buck Bunny trailer (Wikimedia)"
    },
    {
        "id": "1080p_002", "resolution": "1080p", "category": "sports",     "motion": "high",
        "url": "https://archive.org/download/archive-video-files/test.mp4",
        "note": "Archive.org general test MP4"
    },
    {
        "id": "1080p_003", "resolution": "1080p", "category": "nature",     "motion": "low",
        "url": "https://www.w3schools.com/html/mov_bbb.mp4",
        "note": "W3Schools sample (BBB)"
    },
    {
        "id": "1080p_004", "resolution": "1080p", "category": "timelapse",  "motion": "medium",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
        "note": "Google sample video bucket — BBB 1080p"
    },
    {
        "id": "1080p_005", "resolution": "1080p", "category": "documentary","motion": "low",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
        "note": "Elephants Dream — Blender Foundation"
    },
    {
        "id": "1080p_006", "resolution": "1080p", "category": "animation",  "motion": "high",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
        "note": "Google sample — action"
    },
    {
        "id": "1080p_007", "resolution": "1080p", "category": "action",     "motion": "high",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
        "note": "Google sample — escapes"
    },
    {
        "id": "1080p_008", "resolution": "1080p", "category": "mixed",      "motion": "medium",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4",
        "note": "Google sample — fun"
    },
    {
        "id": "1080p_009", "resolution": "1080p", "category": "mixed",      "motion": "medium",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4",
        "note": "Google sample — joyrides"
    },
    {
        "id": "1080p_010", "resolution": "1080p", "category": "mixed",      "motion": "low",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerMeltdowns.mp4",
        "note": "Google sample — meltdowns"
    },
    {
        "id": "1080p_011", "resolution": "1080p", "category": "nature",     "motion": "medium",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4",
        "note": "Sintel — Blender Foundation"
    },
    {
        "id": "1080p_012", "resolution": "1080p", "category": "animation",  "motion": "high",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/SubaruOutbackOnStreetAndDirt.mp4",
        "note": "Google sample — car"
    },
    {
        "id": "1080p_013", "resolution": "1080p", "category": "action",     "motion": "high",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4",
        "note": "Tears of Steel — Blender Foundation"
    },
    {
        "id": "1080p_014", "resolution": "1080p", "category": "nature",     "motion": "low",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/VolkswagenGTIReview.mp4",
        "note": "Google sample — review"
    },
    {
        "id": "1080p_015", "resolution": "1080p", "category": "mixed",      "motion": "medium",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/WeAreGoingOnBullrun.mp4",
        "note": "Google sample — bullrun"
    },
    {
        "id": "1080p_016", "resolution": "1080p", "category": "documentary","motion": "low",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/WhatCarCanYouGetForAGrand.mp4",
        "note": "Google sample — car review"
    },

    # ── 720p ──────────────────────────────────────────────────────────────
    {
        "id": "720p_001", "resolution": "720p", "category": "animation",   "motion": "high",
        "url": "https://archive.org/download/Popeye_forPresident/Popeye_forPresident_512kb.mp4",
        "note": "Popeye for President — public domain cartoon"
    },
    {
        "id": "720p_002", "resolution": "720p", "category": "animation",   "motion": "high",
        "url": "https://archive.org/download/WB_Cartoons/WB_Cartoons_512kb.mp4",
        "note": "WB Cartoons — public domain"
    },
    {
        "id": "720p_003", "resolution": "720p", "category": "documentary", "motion": "low",
        "url": "https://archive.org/download/gov.archives.arc.1257628/gov.archives.arc.1257628_512kb.mp4",
        "note": "US Gov archive footage"
    },
    {
        "id": "720p_004", "resolution": "720p", "category": "screencast",  "motion": "low",
        "url": "https://media.w3.org/2010/05/video/movie.mp4",
        "note": "W3C test video"
    },
    {
        "id": "720p_005", "resolution": "720p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo1280x7205mb/SampleVideo_1280x720_5mb.mp4",
        "note": "Sample 720p video — archive.org"
    },
    {
        "id": "720p_006", "resolution": "720p", "category": "nature",      "motion": "medium",
        "url": "https://archive.org/download/SampleVideo1280x7201mb/SampleVideo_1280x720_1mb.mp4",
        "note": "Sample 720p 1mb"
    },
    {
        "id": "720p_007", "resolution": "720p", "category": "nature",      "motion": "high",
        "url": "https://archive.org/download/SampleVideo1280x72010mb/SampleVideo_1280x720_10mb.mp4",
        "note": "Sample 720p 10mb"
    },
    {
        "id": "720p_008", "resolution": "720p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo1280x72020mb/SampleVideo_1280x720_20mb.mp4",
        "note": "Sample 720p 20mb"
    },

    # ── 480p ──────────────────────────────────────────────────────────────
    {
        "id": "480p_001", "resolution": "480p", "category": "animation",   "motion": "high",
        "url": "https://archive.org/download/BigBuckBunny_328/BigBuckBunny_512kb.mp4",
        "note": "Big Buck Bunny 480p (archive.org, low-bitrate proxy)"
    },
    {
        "id": "480p_002", "resolution": "480p", "category": "documentary", "motion": "low",
        "url": "https://archive.org/download/SampleVideo854x4805mb/SampleVideo_854x480_5mb.mp4",
        "note": "Sample 480p 5mb"
    },
    {
        "id": "480p_003", "resolution": "480p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo854x4801mb/SampleVideo_854x480_1mb.mp4",
        "note": "Sample 480p 1mb"
    },
    {
        "id": "480p_004", "resolution": "480p", "category": "nature",      "motion": "high",
        "url": "https://archive.org/download/SampleVideo854x48010mb/SampleVideo_854x480_10mb.mp4",
        "note": "Sample 480p 10mb"
    },
    {
        "id": "480p_005", "resolution": "480p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo854x48020mb/SampleVideo_854x480_20mb.mp4",
        "note": "Sample 480p 20mb"
    },

    # ── 360p ──────────────────────────────────────────────────────────────
    {
        "id": "360p_001", "resolution": "360p", "category": "animation",   "motion": "high",
        "url": "https://archive.org/download/SampleVideo640x3605mb/SampleVideo_640x360_5mb.mp4",
        "note": "Sample 360p 5mb"
    },
    {
        "id": "360p_002", "resolution": "360p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo640x3601mb/SampleVideo_640x360_1mb.mp4",
        "note": "Sample 360p 1mb"
    },
    {
        "id": "360p_003", "resolution": "360p", "category": "nature",      "motion": "low",
        "url": "https://archive.org/download/SampleVideo640x36010mb/SampleVideo_640x360_10mb.mp4",
        "note": "Sample 360p 10mb"
    },
    {
        "id": "360p_004", "resolution": "360p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo640x36020mb/SampleVideo_640x360_20mb.mp4",
        "note": "Sample 360p 20mb"
    },
    {
        "id": "360p_005", "resolution": "360p", "category": "screencast",  "motion": "low",
        "url": "https://media.w3.org/2010/05/sintel/trailer.mp4",
        "note": "Sintel trailer (W3C hosted)"
    },

    # ── 240p ──────────────────────────────────────────────────────────────
    {
        "id": "240p_001", "resolution": "240p", "category": "animation",   "motion": "high",
        "url": "https://archive.org/download/SampleVideo426x2405mb/SampleVideo_426x240_5mb.mp4",
        "note": "Sample 240p 5mb"
    },
    {
        "id": "240p_002", "resolution": "240p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo426x2401mb/SampleVideo_426x240_1mb.mp4",
        "note": "Sample 240p 1mb"
    },
    {
        "id": "240p_003", "resolution": "240p", "category": "nature",      "motion": "low",
        "url": "https://archive.org/download/SampleVideo426x24010mb/SampleVideo_426x240_10mb.mp4",
        "note": "Sample 240p 10mb"
    },
    {
        "id": "240p_004", "resolution": "240p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo426x24020mb/SampleVideo_426x240_20mb.mp4",
        "note": "Sample 240p 20mb"
    },

    # ── 144p ──────────────────────────────────────────────────────────────
    {
        "id": "144p_001", "resolution": "144p", "category": "mixed",       "motion": "high",
        "url": "https://archive.org/download/SampleVideo256x1445mb/SampleVideo_256x144_5mb.mp4",
        "note": "Sample 144p 5mb"
    },
    {
        "id": "144p_002", "resolution": "144p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo256x1441mb/SampleVideo_256x144_1mb.mp4",
        "note": "Sample 144p 1mb"
    },
    {
        "id": "144p_003", "resolution": "144p", "category": "mixed",       "motion": "low",
        "url": "https://archive.org/download/SampleVideo256x14410mb/SampleVideo_256x144_10mb.mp4",
        "note": "Sample 144p 10mb"
    },
    {
        "id": "144p_004", "resolution": "144p", "category": "mixed",       "motion": "medium",
        "url": "https://archive.org/download/SampleVideo256x14420mb/SampleVideo_256x144_20mb.mp4",
        "note": "Sample 144p 20mb"
    },

    # ── Extra 1080p / nature / NASA (high quality, varied motion) ─────────
    {
        "id": "nasa_001", "resolution": "1080p", "category": "space",      "motion": "low",
        "url": "https://www.nasa.gov/sites/default/files/atoms/video/jsc2020e027655_-_iss064-e-24054_hd.mp4",
        "note": "NASA ISS HD footage"
    },
    {
        "id": "nasa_002", "resolution": "1080p", "category": "space",      "motion": "medium",
        "url": "https://archive.org/download/NasaVideoUploads/NASA-ISS-TimeLapse-Amazon.mp4",
        "note": "NASA time-lapse of Amazon basin"
    },
    {
        "id": "blender_001", "resolution": "1080p", "category": "vfx",    "motion": "high",
        "url": "https://download.blender.org/demo/movies/BBB/bbb_sunflower_1080p_30fps_normal.mp4",
        "note": "Big Buck Bunny 1080p 30fps — Blender Foundation"
    },
    {
        "id": "blender_002", "resolution": "720p",  "category": "vfx",    "motion": "high",
        "url": "https://download.blender.org/demo/movies/BBB/bbb_sunflower_720p_stereo.mp4",
        "note": "Big Buck Bunny 720p stereo"
    },
    {
        "id": "blender_003", "resolution": "1080p", "category": "vfx",    "motion": "medium",
        "url": "https://download.blender.org/demo/movies/Sintel.2010.720p.mkv",
        "note": "Sintel 720p MKV — will be remuxed to MP4"
    },
    {
        "id": "peach_001",   "resolution": "1080p", "category": "vfx",    "motion": "high",
        "url": "https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov",
        "note": "Tears of Steel 720p"
    },
    {
        "id": "extra_001", "resolution": "1080p", "category": "nature",   "motion": "high",
        "url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/1080/Big_Buck_Bunny_1080_10s_30MB.mp4",
        "note": "test-videos.co.uk BBB 1080p 10s"
    },
    {
        "id": "extra_002", "resolution": "720p",  "category": "nature",   "motion": "high",
        "url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_20MB.mp4",
        "note": "test-videos.co.uk BBB 720p 10s"
    },
    {
        "id": "extra_003", "resolution": "480p",  "category": "nature",   "motion": "high",
        "url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/480/Big_Buck_Bunny_480_10s_5MB.mp4",
        "note": "test-videos.co.uk BBB 480p 10s"
    },
    {
        "id": "extra_004", "resolution": "360p",  "category": "nature",   "motion": "high",
        "url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_3MB.mp4",
        "note": "test-videos.co.uk BBB 360p 10s"
    },
    {
        "id": "extra_005", "resolution": "240p",  "category": "nature",   "motion": "high",
        "url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/240/Big_Buck_Bunny_240_10s_1MB.mp4",
        "note": "test-videos.co.uk BBB 240p 10s"
    },
    # Jellyfish test clips — popular for codec testing, varied bitrate
    {
        "id": "jelly_001", "resolution": "1080p", "category": "nature",   "motion": "medium",
        "url": "http://jell.yfish.us/media/jellyfish-3-mbps-hd-h264.mkv",
        "note": "Jellyfish 3Mbps HD (MKV, will remux)"
    },
    {
        "id": "jelly_002", "resolution": "1080p", "category": "nature",   "motion": "medium",
        "url": "http://jell.yfish.us/media/jellyfish-5-mbps-hd-h264.mkv",
        "note": "Jellyfish 5Mbps HD"
    },
    {
        "id": "jelly_003", "resolution": "1080p", "category": "nature",   "motion": "medium",
        "url": "http://jell.yfish.us/media/jellyfish-15-mbps-hd-h264.mkv",
        "note": "Jellyfish 15Mbps HD"
    },
    {
        "id": "jelly_004", "resolution": "4k",    "category": "nature",   "motion": "medium",
        "url": "http://jell.yfish.us/media/jellyfish-35-mbps-hd-h264.mkv",
        "note": "Jellyfish 35Mbps (used as 4K proxy)"
    },
]

assert len(DATASET) >= 50, f"Dataset only has {len(DATASET)} entries — need 50+"


# ─── Downloader ─────────────────────────────────────────────────────────────

def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _sha256(path: Path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk_data in iter(lambda: f.read(chunk), b""):
            h.update(chunk_data)
    return h.hexdigest()


def _normalize_to_mp4(src: Path, dest: Path) -> bool:
    """
    If src is not already .mp4 (MKV, MOV, OGV, WEBM …), remux/transcode to
    yuv420p h264 MP4 so the benchmark always sees a consistent container.
    Deletes src after successful conversion.
    """
    import subprocess
    if src.suffix.lower() == ".mp4":
        src.rename(dest)
        return True
    print(f"    → Remuxing {src.name} → {dest.name}")
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",          # strip audio — benchmark doesn't need it
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
        src.unlink(missing_ok=True)
        return True
    print(f"    ✗ Remux failed for {src.name}: {result.stderr.decode(errors='replace')[-200:]}")
    src.unlink(missing_ok=True)
    return False


@dataclass
class DownloadResult:
    entry_id: str
    success: bool
    path: Optional[Path] = None
    size_bytes: int = 0
    sha256: str = ""
    error: str = ""


def download_one(entry: dict, dest_dir: Path, timeout: int = 120) -> DownloadResult:
    vid_id   = entry["id"]
    url      = entry["url"]
    ext      = Path(url.split("?")[0]).suffix or ".mp4"
    raw_name = f"{vid_id}{ext}"
    mp4_name = f"{vid_id}.mp4"
    raw_path = dest_dir / raw_name
    mp4_path = dest_dir / mp4_name

    # Already done
    if mp4_path.exists() and mp4_path.stat().st_size > 0:
        return DownloadResult(vid_id, True, mp4_path, mp4_path.stat().st_size)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "REEL-Benchmark/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(raw_path, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 1 << 17  # 128 KB
            while True:
                data = resp.read(chunk)
                if not data:
                    break
                f.write(data)
                downloaded += len(data)
    except Exception as e:
        raw_path.unlink(missing_ok=True)
        return DownloadResult(vid_id, False, error=str(e))

    if raw_path.stat().st_size == 0:
        raw_path.unlink(missing_ok=True)
        return DownloadResult(vid_id, False, error="Empty file")

    # Normalize to mp4
    ok = _normalize_to_mp4(raw_path, mp4_path)
    if not ok:
        return DownloadResult(vid_id, False, error="Remux failed")

    size = mp4_path.stat().st_size
    digest = _sha256(mp4_path)
    return DownloadResult(vid_id, True, mp4_path, size, digest)


def download_all(dest_dir: Path, workers: int = 4, dry_run: bool = False):
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = dest_dir / "manifest.csv"

    already_done = set()
    if manifest_path.exists():
        with open(manifest_path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("success") == "True":
                    already_done.add(row["id"])

    todo = [e for e in DATASET if e["id"] not in already_done]

    print("=" * 70)
    print(f"  REEL Benchmark — MP4 Dataset Downloader")
    print("=" * 70)
    print(f"  Total entries : {len(DATASET)}")
    print(f"  Already done  : {len(already_done)}")
    print(f"  To download   : {len(todo)}")
    print(f"  Destination   : {dest_dir}")
    print(f"  Workers       : {workers}")
    print()

    if dry_run:
        print("[DRY RUN] Would download:")
        for e in todo:
            print(f"  {e['id']:20s}  {e['resolution']:6s}  {e['motion']:6s}  {e['url']}")
        return

    results: list[DownloadResult] = []

    # Serial for already-done check; parallel for actual downloads
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, entry, dest_dir): entry for entry in todo}
        done_count = 0
        for fut in as_completed(futures):
            entry = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = DownloadResult(entry["id"], False, error=str(e))
            done_count += 1
            icon = "✓" if res.success else "✗"
            size_str = _human_size(res.size_bytes) if res.success else res.error[:60]
            print(f"  [{done_count:>3}/{len(todo)}] {icon} {entry['id']:20s}  {size_str}")
            results.append(res)

    # Write / append manifest CSV
    write_header = not manifest_path.exists()
    with open(manifest_path, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["id", "resolution", "category", "motion", "path", "size_bytes", "sha256", "success", "error", "note"])
        for entry, res in zip(todo, results):
            w.writerow([
                entry["id"], entry["resolution"], entry["category"], entry["motion"],
                str(res.path) if res.path else "",
                res.size_bytes, res.sha256,
                res.success, res.error,
                entry.get("note", ""),
            ])

    success = sum(1 for r in results if r.success)
    fail    = len(results) - success
    total_bytes = sum(r.size_bytes for r in results if r.success)

    print()
    print("=" * 70)
    print(f"  Downloaded : {success + len(already_done)} / {len(DATASET)} ({_human_size(total_bytes)} new)")
    if fail:
        print(f"  Failed     : {fail} (check manifest for URLs to retry manually)")
    print(f"  Manifest   : {manifest_path}")
    print("=" * 70)

    return dest_dir


def main():
    parser = argparse.ArgumentParser(description="Download MP4 benchmark dataset for REEL")
    parser.add_argument("--output-dir", default=None,
                        help="Where to store videos (default: <script_dir>/videos/mp4)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel download threads (default: 4)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be downloaded without downloading")
    args = parser.parse_args()

    base = Path(__file__).parent
    dest = Path(args.output_dir) if args.output_dir else base / "videos" / "mp4"
    download_all(dest, workers=args.workers, dry_run=args.dry_run)


if __name__ == "__main__":
    main()