# Methodology

## Test Corpus

A corpus of 2 synthetic video clips was generated using FFmpeg lavfi
sources (testsrc2, mandelbrot, life, color, smptebars). Each clip is 30 seconds
at 30 fps, YUV420p.

Videos were randomly assigned combinations of:
- **Resolution**: 144p (n=0), 240p (n=0), 360p (n=0), 480p (n=0), 720p (n=0), 1080p (n=0), 1440p (n=0), 4k (n=0)
- **Motion**: 
- **Color**: low contrast, high contrast, vivid, monochrome, gradient, mixed

Random seed: 42 (reproducible).

## Codecs Under Test

1. **REEL (Aura)** — custom intermediate format, per-frame zstd, O(1) random access via OIT. YUV420p native.
2. **FFV1** — lossless intra-frame (level 3, GOP=1). YUV420p native.
3. **HuffYUV** — similar philosophy intermediate codec. Requires YUV422p.
4. **Ut Video** — editing-oriented lossless. YUV420p native.
5. **Lagarith** — classic lossless intermediate. YUV420p native.
6. **ProRes HQ** (profile 3) — requires YUV422p10le minimum.
7. **ProRes HD** (profile 2) — requires YUV422p10le minimum.
8. **ProRes Standard** (profile 1) — requires YUV422p10le minimum.

ProRes and HuffYUV profiles require 420p->422p conversion during encode and back during decode,
introducing chroma resampling differences.

## Measurement Pipeline

For each video:
1. MP4 -> raw YUV420p (FFmpeg)
2. Encode: YUV420p -> codec
3. Decode: codec -> YUV420p
4. Verify: bit-exact comparison + PSNR/SSIM
5. Random access: 10 random frames decoded individually
6. Cleanup: all intermediates deleted

Metrics per codec per video:
- Wall time, CPU time (encode/decode)
- Peak RSS memory (psutil, 10ms polling)
- File sizes, compression ratios, bitrate, bits/pixel
- Random frame decode latency in microseconds (avg, p50, p95, p99)

## Hardware & Software

| Item | Value |
|------|-------|
| OS | Windows 11 |
| CPU | AMD64 Family 25 Model 68 Stepping 1, AuthenticAMD (16 cores) |
| RAM | 13.35 GB |
| FFmpeg | ffmpeg version 8.1-essentials_build-www.gyan.dev Copyright (c) 2000-2026 the FFmpeg developers |
| REEL | aurx 1.0 |
| Rust | rustc 1.92.0 (ded5c06cf 2025-12-08) |
| Python | 3.12.10 |

## Statistical Methods

- Omnibus: Kruskal-Wallis H-test (non-parametric)
- Post-hoc: Mann-Whitney U with Bonferroni correction
- Effect size: Cohen's d
- Significance: alpha = 0.05

## Limitations

- Synthetic clips may not represent all real-world characteristics
- ProRes comparison involves unavoidable 420->422 colorspace conversion
- Memory polling at 10ms may underestimate brief peaks
- Single-machine results; hardware-dependent
