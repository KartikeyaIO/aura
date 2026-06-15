"""
REEL Benchmark Configuration
=============================
Central definitions for resolutions, codecs, paths, and test matrix generation.
"""

import os
import random
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
VIDEOS_DIR = BASE_DIR / "videos"
RESULTS_DIR = BASE_DIR / "results"
TEMP_DIR = RESULTS_DIR / "temp"
CHARTS_DIR = RESULTS_DIR / "charts"
TABLES_DIR = RESULTS_DIR / "tables"
CSV_PATH = RESULTS_DIR / "benchmark_results.csv"
SYSTEM_INFO_PATH = RESULTS_DIR / "system_info.json"
MANIFEST_PATH = VIDEOS_DIR / "manifest.csv"

# ─── Random Seed (for reproducibility) ──────────────────────────────
RANDOM_SEED = 42

# ─── Video Parameters ──────────────────────────────────────────────
VIDEO_DURATION = 30    # seconds per clip
VIDEO_FPS_NUM = 30000  # Default fps numerator
VIDEO_FPS_DEN = 1000   # Default fps denominator (30.0 fps)
TOTAL_VIDEOS = 150     # total test videos to generate
RANDOM_FRAME_COUNT = 100  # random frames to decode per video per codec

# ─── Resolutions ────────────────────────────────────────────────────
RESOLUTIONS = {
    "144p":  (256, 144),
    "240p":  (426, 240),
    "360p":  (640, 360),
    "480p":  (854, 480),
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k":    (3840, 2160),
}

# ─── Motion & Color Types (For synthetic generation only) ───────────
MOTION_TYPES = ["low", "medium", "high"]
COLOR_TYPES = ["low_contrast", "high_contrast", "vivid", "monochrome", "gradient", "mixed"]

# ─── Codec Definitions ─────────────────────────────────────────────
# Note: ProRes requires YUV422p minimum, so encode converts 420->422.
CODECS = {
    "FFV1": {
        "ext": ".mkv",
        "encode_pix_fmt": "yuv420p",
    },
    "ProRes_HQ": {
        "ext": ".mov",
        "profile": "3",
        "encode_pix_fmt": "yuv422p10le",
    },
    "ProRes_HD": {
        "ext": ".mov",
        "profile": "2",
        "encode_pix_fmt": "yuv422p10le",
    },
    "ProRes_Std": {
        "ext": ".mov",
        "profile": "1",
        "encode_pix_fmt": "yuv422p10le",
    },
    "REEL": {
        "ext": ".reel",
        "encode_pix_fmt": "yuv420p",
    },
    "HuffYUV": {
        "ext": ".avi",
        "encode_pix_fmt": "yuv422p",
    },
    "Ut_Video": {
        "ext": ".avi",
        "encode_pix_fmt": "yuv420p",
    }
    
}

# ─── CSV Column Schema ─────────────────────────────────────────────
CSV_COLUMNS = [
    "video_id", "video_file", "resolution", "width", "height",
    "fps_num", "fps_den", "motion_type", "color_type", "codec",
    "raw_yuv_size_bytes", "encoded_size_bytes",
    "compression_ratio", "space_savings_pct",
    "encode_wall_time_s", "encode_cpu_time_s",
    "decode_wall_time_s", "decode_cpu_time_s",
    "encode_fps", "decode_fps",
    "encode_realtime_ratio", "decode_realtime_ratio",
    "encode_peak_memory_mb", "decode_peak_memory_mb",
    "encode_throughput_mbps", "decode_throughput_mbps",
    "bitrate_mbps", "bits_per_pixel",
    "is_lossless",
    "psnr_y", "psnr_u", "psnr_v", "ssim",
    "rand_frame_decode_avg_ms", "rand_frame_decode_p50_ms",
    "rand_frame_decode_p95_ms", "rand_frame_decode_p99_ms",
    "rand_frame_decode_min_ms", "rand_frame_decode_max_ms",
    "rand_frame_decode_stddev_ms",
    "timestamp",
]

def generate_test_matrix(seed=RANDOM_SEED, count=TOTAL_VIDEOS):
    rng = random.Random(seed)
    res_keys = list(RESOLUTIONS.keys())
    matrix = []
    for i in range(count):
        res_label = rng.choice(res_keys)
        w, h = RESOLUTIONS[res_label]
        motion = rng.choice(MOTION_TYPES)
        color = rng.choice(COLOR_TYPES)
        filename = f"vid_{i:03d}_{res_label}_{motion}_{color}.mp4"
        matrix.append({
            "video_id": i,
            "filename": filename,
            "resolution": res_label,
            "width": w,
            "height": h,
            "fps_num": VIDEO_FPS_NUM,
            "fps_den": VIDEO_FPS_DEN,
            "motion": motion,
            "color": color,
            "seed": rng.randint(0, 2**31),
        })
    return matrix