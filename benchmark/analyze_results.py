#!/usr/bin/env python3
"""
REEL Benchmark — Analysis & Report Generation
==============================================
Reads benchmark_results.csv and produces:
  - 12 publication-quality figures (SVG + PNG @ 300dpi)
  - LaTeX-ready tables (.tex)
  - Statistical significance tests (ANOVA, Mann-Whitney, Cohen's d)
  - Auto-generated methodology draft
  - Summary report

Usage:
    python benchmark/analyze_results.py
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns

from config import RESULTS_DIR, CHARTS_DIR, TABLES_DIR, CSV_PATH, SYSTEM_INFO_PATH


# ─── Constants ──────────────────────────────────────────────────────

CODEC_COLORS = {
    "REEL":       "#FF6B35",
    "FFV1":       "#4ECDC4",
    "HuffYUV":    "#F1C40F",
    "Ut_Video":   "#E67E22",
    "Lagarith":   "#2ECC71",
    "ProRes_HQ":  "#2C3E50",
    "ProRes_HD":  "#3498DB",
    "ProRes_Std": "#9B59B6",
}
CODEC_ORDER = ["REEL", "FFV1", "HuffYUV", "Ut_Video", "Lagarith", "ProRes_HQ", "ProRes_HD", "ProRes_Std"]
RES_ORDER = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "4k"]


# ─── Setup ──────────────────────────────────────────────────────────

def setup_plot_style():
    """Configure matplotlib for publication-quality output."""
    plt.rcParams.update({
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "font.size": 11,
        "font.family": "serif",
        "axes.titlesize": 13,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.figsize": (10, 6),
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })
    sns.set_palette("husl")


def load_data():
    """Load and clean benchmark CSV."""
    df = pd.read_csv(CSV_PATH)

    num_cols = [
        "raw_yuv_size_bytes", "encoded_size_bytes",
        "compression_ratio", "space_savings_pct",
        "encode_wall_time_s", "encode_cpu_time_s",
        "decode_wall_time_s", "decode_cpu_time_s",
        "encode_fps", "decode_fps",
        "encode_realtime_ratio", "decode_realtime_ratio",
        "encode_peak_memory_mb", "decode_peak_memory_mb",
        "encode_throughput_mbps", "decode_throughput_mbps",
        "bitrate_mbps", "bits_per_pixel",
        "rand_frame_decode_avg_ms", "rand_frame_decode_p50_ms",
        "rand_frame_decode_p95_ms", "rand_frame_decode_p99_ms",
        "rand_frame_decode_min_ms", "rand_frame_decode_max_ms",
        "rand_frame_decode_stddev_ms",
    ]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["psnr_y", "psnr_u", "psnr_v"]:
        if col in df.columns:
            df[col] = df[col].replace("inf", np.inf)
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "ssim" in df.columns:
        df["ssim"] = pd.to_numeric(df["ssim"], errors="coerce")

    df["resolution"] = pd.Categorical(df["resolution"], categories=RES_ORDER, ordered=True)
    df["codec"] = pd.Categorical(df["codec"], categories=CODEC_ORDER, ordered=True)

    return df


# ─── Figure helpers ─────────────────────────────────────────────────

def _save(fig, name):
    fig.savefig(CHARTS_DIR / f"{name}.svg", format="svg", bbox_inches="tight")
    fig.savefig(CHARTS_DIR / f"{name}.png", format="png", bbox_inches="tight")
    plt.close(fig)
    print(f"    {name}")


def _codec_palette(codecs):
    return [CODEC_COLORS.get(c, "#999") for c in codecs]


# ─── Figures ────────────────────────────────────────────────────────

def fig_encode_time_vs_resolution(df):
    fig, ax = plt.subplots(figsize=(10, 6))
    g = df.groupby(["resolution", "codec"])["encode_wall_time_s"].mean().reset_index()
    for c in CODEC_ORDER:
        d = g[g["codec"] == c]
        if not d.empty:
            ax.plot(d["resolution"], d["encode_wall_time_s"],
                    marker="o", label=c, color=CODEC_COLORS.get(c), linewidth=2)
    ax.set_xlabel("Resolution"); ax.set_ylabel("Encode Time (s)")
    ax.set_title("Encode Time vs Resolution"); ax.legend(); ax.set_yscale("log")
    _save(fig, "fig_encode_time_vs_resolution")


def fig_decode_time_vs_resolution(df):
    fig, ax = plt.subplots(figsize=(10, 6))
    g = df.groupby(["resolution", "codec"])["decode_wall_time_s"].mean().reset_index()
    for c in CODEC_ORDER:
        d = g[g["codec"] == c]
        if not d.empty:
            ax.plot(d["resolution"], d["decode_wall_time_s"],
                    marker="s", label=c, color=CODEC_COLORS.get(c), linewidth=2)
    ax.set_xlabel("Resolution"); ax.set_ylabel("Decode Time (s)")
    ax.set_title("Decode Time vs Resolution"); ax.legend(); ax.set_yscale("log")
    _save(fig, "fig_decode_time_vs_resolution")


def fig_compression_ratio_vs_resolution(df):
    fig, ax = plt.subplots(figsize=(12, 6))
    g = df.groupby(["resolution", "codec"])["compression_ratio"].mean().reset_index()
    piv = g.pivot(index="resolution", columns="codec", values="compression_ratio")
    piv = piv.reindex(columns=CODEC_ORDER)
    piv.plot(kind="bar", ax=ax, color=_codec_palette(piv.columns))
    ax.set_xlabel("Resolution"); ax.set_ylabel("Compression Ratio")
    ax.set_title("Compression Ratio by Resolution"); ax.legend(title="Codec")
    plt.xticks(rotation=45)
    _save(fig, "fig_compression_ratio_vs_resolution")


def fig_compression_ratio_heatmap(df):
    fig, ax = plt.subplots(figsize=(10, 5))
    g = df.groupby(["resolution", "codec"])["compression_ratio"].mean().reset_index()
    piv = g.pivot(index="codec", columns="resolution", values="compression_ratio")
    piv = piv.reindex(index=CODEC_ORDER, columns=RES_ORDER)
    sns.heatmap(piv, annot=True, fmt=".2f", cmap="YlOrRd", ax=ax,
                linewidths=0.5, cbar_kws={"label": "Compression Ratio"})
    ax.set_title("Compression Ratio Heatmap")
    _save(fig, "fig_compression_ratio_heatmap")


def fig_random_frame_latency_boxplot(df):
    fig, ax = plt.subplots(figsize=(10, 6))
    plot_df = df[["codec", "rand_frame_decode_avg_ms"]].dropna()
    sns.boxplot(data=plot_df, x="codec", y="rand_frame_decode_avg_ms",
                order=CODEC_ORDER, ax=ax, palette=CODEC_COLORS)
    ax.set_xlabel("Codec"); ax.set_ylabel("Latency (ms)")
    ax.set_title("Random Frame Decode Latency")
    _save(fig, "fig_random_frame_latency_boxplot")


def fig_throughput_bar(df):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, col, title in [
        (axes[0], "encode_throughput_mbps", "Encode Throughput"),
        (axes[1], "decode_throughput_mbps", "Decode Throughput"),
    ]:
        means = df.groupby("codec")[col].mean().reindex(CODEC_ORDER)
        means.plot(kind="bar", ax=ax, color=_codec_palette(means.index))
        ax.set_title(title); ax.set_ylabel("MB/s")
        ax.tick_params(axis="x", rotation=45)
    fig.suptitle("Throughput Comparison", fontsize=14); fig.tight_layout()
    _save(fig, "fig_throughput_bar")


def fig_file_size_comparison(df):
    fig, ax = plt.subplots(figsize=(12, 6))
    g = df.groupby(["resolution", "codec"])["encoded_size_bytes"].mean().reset_index()
    g["size_mb"] = g["encoded_size_bytes"] / (1024 * 1024)
    piv = g.pivot(index="resolution", columns="codec", values="size_mb")
    piv = piv.reindex(columns=CODEC_ORDER)
    piv.plot(kind="bar", ax=ax, color=_codec_palette(piv.columns))
    ax.set_xlabel("Resolution"); ax.set_ylabel("File Size (MB)")
    ax.set_title("Encoded File Size by Resolution"); ax.legend(title="Codec")
    plt.xticks(rotation=45)
    _save(fig, "fig_file_size_comparison")


def fig_motion_impact(df):
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, motion in zip(axes, ["low", "medium", "high"]):
        sub = df[df["motion_type"] == motion]
        means = sub.groupby("codec")["compression_ratio"].mean().reindex(CODEC_ORDER)
        means.plot(kind="bar", ax=ax, color=_codec_palette(means.index))
        ax.set_title(f"{motion.capitalize()} Motion"); ax.set_ylabel("Compression Ratio")
        ax.tick_params(axis="x", rotation=45)
    fig.suptitle("Compression by Motion Type", fontsize=14); fig.tight_layout()
    _save(fig, "fig_motion_impact")


def fig_memory_usage(df):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, col, title in [
        (axes[0], "encode_peak_memory_mb", "Encode Peak Memory"),
        (axes[1], "decode_peak_memory_mb", "Decode Peak Memory"),
    ]:
        means = df.groupby("codec")[col].mean().reindex(CODEC_ORDER)
        means.plot(kind="bar", ax=ax, color=_codec_palette(means.index))
        ax.set_title(title); ax.set_ylabel("Peak RSS (MB)")
        ax.tick_params(axis="x", rotation=45)
    fig.suptitle("Peak Memory Usage", fontsize=14); fig.tight_layout()
    _save(fig, "fig_memory_usage")


def fig_realtime_ratio(df):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, col, title in [
        (axes[0], "encode_realtime_ratio", "Encode"),
        (axes[1], "decode_realtime_ratio", "Decode"),
    ]:
        means = df.groupby("codec")[col].mean().reindex(CODEC_ORDER)
        means.plot(kind="bar", ax=ax, color=_codec_palette(means.index))
        ax.axhline(y=1.0, color="red", linestyle="--", alpha=0.7, label="Real-time")
        ax.set_title(title); ax.set_ylabel("Ratio (>1 = faster)")
        ax.tick_params(axis="x", rotation=45); ax.legend()
    fig.suptitle("Real-time Performance Ratio", fontsize=14); fig.tight_layout()
    _save(fig, "fig_realtime_ratio")


def fig_bits_per_pixel(df):
    fig, ax = plt.subplots(figsize=(10, 6))
    px = df["width"] * df["height"]
    for c in CODEC_ORDER:
        m = df["codec"] == c
        ax.scatter(px[m], df.loc[m, "bits_per_pixel"],
                   alpha=0.5, label=c, color=CODEC_COLORS.get(c), s=30)
    ax.set_xlabel("Pixels / Frame"); ax.set_ylabel("Bits / Pixel")
    ax.set_title("Encoding Efficiency"); ax.set_xscale("log"); ax.legend()
    _save(fig, "fig_bits_per_pixel")


def fig_scalability(df):
    fig, ax = plt.subplots(figsize=(10, 6))
    d = df.copy()
    d["pixel_count"] = d["width"] * d["height"]
    for c in CODEC_ORDER:
        s = d[d["codec"] == c].groupby("pixel_count")["encode_wall_time_s"].mean().reset_index()
        s = s.sort_values("pixel_count")
        ax.plot(s["pixel_count"], s["encode_wall_time_s"],
                marker="o", label=c, color=CODEC_COLORS.get(c), linewidth=2)
    ax.set_xlabel("Pixels / Frame (log)"); ax.set_ylabel("Encode Time (s, log)")
    ax.set_title("Encoding Scalability"); ax.set_xscale("log"); ax.set_yscale("log")
    ax.legend()
    _save(fig, "fig_scalability")


# ─── LaTeX Tables ──────────────────────────────────────────────────

def gen_latex_overall(df):
    agg = df.groupby("codec").agg({
        "compression_ratio": ["mean", "std"],
        "encode_wall_time_s": ["mean", "std"],
        "decode_wall_time_s": ["mean", "std"],
        "encode_fps": "mean",
        "decode_fps": "mean",
        "encode_peak_memory_mb": "mean",
        "rand_frame_decode_avg_ms": ["mean", "std"],
    }).round(2).reindex(CODEC_ORDER)

    lines = [
        "% Auto-generated by analyze_results.py",
        "\\begin{table}[htbp]", "\\centering",
        "\\caption{Overall Codec Performance (Mean $\\pm$ Std Dev)}",
        "\\label{tab:overall}",
        "\\begin{tabular}{lrrrrr}", "\\toprule",
        "Codec & Comp. Ratio & Enc. (s) & Dec. (s) & Enc. FPS & Rand. (ms) \\\\",
        "\\midrule",
    ]
    for c in CODEC_ORDER:
        if c not in agg.index:
            continue
        r = agg.loc[c]
        cr = f"{r[('compression_ratio','mean')]:.2f} $\\pm$ {r[('compression_ratio','std')]:.2f}"
        et = f"{r[('encode_wall_time_s','mean')]:.2f} $\\pm$ {r[('encode_wall_time_s','std')]:.2f}"
        dt = f"{r[('decode_wall_time_s','mean')]:.2f} $\\pm$ {r[('decode_wall_time_s','std')]:.2f}"
        ef = f"{r[('encode_fps','mean')]:.0f}"
        ra = f"{r[('rand_frame_decode_avg_ms','mean')]:.1f} $\\pm$ {r[('rand_frame_decode_avg_ms','std')]:.1f}"
        lines.append(f"{c.replace('_',' ')} & {cr} & {et} & {dt} & {ef} & {ra} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]

    p = TABLES_DIR / "table_overall_comparison.tex"
    p.write_text("\n".join(lines))
    print("    table_overall_comparison.tex")


def gen_latex_by_resolution(df):
    agg = df.groupby(["resolution", "codec"]).agg({
        "compression_ratio": "mean",
        "encode_wall_time_s": "mean",
        "decode_wall_time_s": "mean",
        "rand_frame_decode_avg_ms": "mean",
    }).round(2)

    lines = [
        "% Auto-generated by analyze_results.py",
        "\\begin{table}[htbp]", "\\centering", "\\small",
        "\\caption{Performance by Resolution (Mean)}", "\\label{tab:by_resolution}",
        "\\begin{tabular}{llrrrr}", "\\toprule",
        "Res. & Codec & Comp. & Enc.(s) & Dec.(s) & Rand.(ms) \\\\",
        "\\midrule",
    ]
    for res in RES_ORDER:
        first = True
        for c in CODEC_ORDER:
            try:
                r = agg.loc[(res, c)]
            except KeyError:
                continue
            rl = res if first else ""
            lines.append(
                f"{rl} & {c.replace('_',' ')} & {r['compression_ratio']:.2f} & "
                f"{r['encode_wall_time_s']:.2f} & {r['decode_wall_time_s']:.2f} & "
                f"{r['rand_frame_decode_avg_ms']:.1f} \\\\"
            )
            first = False
        lines.append("\\midrule")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]

    p = TABLES_DIR / "table_by_resolution.tex"
    p.write_text("\n".join(lines))
    print("    table_by_resolution.tex")


def gen_latex_by_motion(df):
    agg = df.groupby(["motion_type", "codec"]).agg({
        "compression_ratio": "mean",
        "encode_wall_time_s": "mean",
        "rand_frame_decode_avg_ms": "mean",
    }).round(2)

    lines = [
        "% Auto-generated", "\\begin{table}[htbp]", "\\centering",
        "\\caption{Performance by Motion Type}", "\\label{tab:by_motion}",
        "\\begin{tabular}{llrrr}", "\\toprule",
        "Motion & Codec & Comp. Ratio & Enc.(s) & Rand.(ms) \\\\", "\\midrule",
    ]
    for m in ["low", "medium", "high"]:
        first = True
        for c in CODEC_ORDER:
            try:
                r = agg.loc[(m, c)]
            except KeyError:
                continue
            ml = m.capitalize() if first else ""
            lines.append(
                f"{ml} & {c.replace('_',' ')} & {r['compression_ratio']:.2f} & "
                f"{r['encode_wall_time_s']:.2f} & {r['rand_frame_decode_avg_ms']:.1f} \\\\"
            )
            first = False
        lines.append("\\midrule")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]

    p = TABLES_DIR / "table_by_motion.tex"
    p.write_text("\n".join(lines))
    print("    table_by_motion.tex")


def gen_latex_significance(df):
    """p-value matrix (Mann-Whitney U on compression ratio)."""
    lines = [
        "% Auto-generated", "\\begin{table}[htbp]", "\\centering",
        "\\caption{Pairwise Statistical Significance (Compression Ratio, Mann-Whitney U)}",
        "\\label{tab:significance}",
        "\\begin{tabular}{l" + "r" * len(CODEC_ORDER) + "}", "\\toprule",
        " & " + " & ".join(c.replace("_", " ") for c in CODEC_ORDER) + " \\\\",
        "\\midrule",
    ]
    for c1 in CODEC_ORDER:
        vals = []
        for c2 in CODEC_ORDER:
            if c1 == c2:
                vals.append("---")
            else:
                d1 = df[df["codec"] == c1]["compression_ratio"].dropna()
                d2 = df[df["codec"] == c2]["compression_ratio"].dropna()
                if len(d1) > 0 and len(d2) > 0:
                    try:
                        _, p = sp_stats.mannwhitneyu(d1, d2, alternative="two-sided")
                        vals.append("$<$0.001" if p < 0.001 else f"{p:.3f}")
                    except Exception:
                        vals.append("N/A")
                else:
                    vals.append("N/A")
        lines.append(f"{c1.replace('_',' ')} & " + " & ".join(vals) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]

    p = TABLES_DIR / "table_statistical_significance.tex"
    p.write_text("\n".join(lines))
    print("    table_statistical_significance.tex")


# ─── Statistical Analysis ──────────────────────────────────────────

def run_statistical_analysis(df):
    print("\n  Statistical analysis ...")
    results = {}
    metrics = {
        "compression_ratio": "Compression Ratio",
        "encode_wall_time_s": "Encode Time",
        "decode_wall_time_s": "Decode Time",
        "rand_frame_decode_avg_ms": "Random Frame Latency",
    }

    for metric, label in metrics.items():
        print(f"\n    {label}")
        groups, names = [], []
        for c in CODEC_ORDER:
            d = df[df["codec"] == c][metric].dropna()
            if len(d) > 0:
                groups.append(d.values)
                names.append(c)
        if len(groups) < 2:
            continue

        # Omnibus test
        try:
            stat, p = sp_stats.kruskal(*groups)
            print(f"      Kruskal-Wallis: H={stat:.3f}, p={p:.6f}")
        except Exception as e:
            print(f"      Kruskal-Wallis failed: {e}")
            stat, p = 0, 1

        # Pairwise
        n_comp = len(groups) * (len(groups) - 1) // 2
        pairwise = []
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                try:
                    _, pu = sp_stats.mannwhitneyu(groups[i], groups[j], alternative="two-sided")
                    pc = min(pu * n_comp, 1.0)  # Bonferroni
                    diff = np.mean(groups[i]) - np.mean(groups[j])
                    pooled = np.sqrt((np.var(groups[i]) + np.var(groups[j])) / 2)
                    d_val = diff / pooled if pooled > 0 else 0
                    sig = "***" if pc < 0.001 else "**" if pc < 0.01 else "*" if pc < 0.05 else "ns"
                    pairwise.append({
                        "a": names[i], "b": names[j],
                        "p_raw": float(pu), "p_corr": float(pc),
                        "cohens_d": float(d_val), "sig": sig,
                    })
                    print(f"      {names[i]} vs {names[j]}: p={pc:.4f} {sig}, d={d_val:.3f}")
                except Exception as e:
                    print(f"      {names[i]} vs {names[j]}: {e}")

        results[metric] = {
            "omnibus_stat": float(stat), "omnibus_p": float(p),
            "pairwise": pairwise,
        }

    out = RESULTS_DIR / "statistical_analysis.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n    -> {out}")
    return results


# ─── Methodology Draft ─────────────────────────────────────────────

def generate_methodology(df):
    si = {}
    if SYSTEM_INFO_PATH.exists():
        with open(SYSTEM_INFO_PATH) as f:
            si = json.load(f)

    n_vid = df["video_id"].nunique()
    rc = df.groupby("resolution")["video_id"].nunique()
    mc = df.groupby("motion_type")["video_id"].nunique()

    text = f"""# Methodology

## Test Corpus

A corpus of {n_vid} synthetic video clips was generated using FFmpeg lavfi
sources (testsrc2, mandelbrot, life, color, smptebars). Each clip is 30 seconds
at 30 fps, YUV420p.

Videos were randomly assigned combinations of:
- **Resolution**: {', '.join(f'{r} (n={rc.get(r,0)})' for r in RES_ORDER if r in rc.index)}
- **Motion**: {', '.join(f'{m} (n={mc.get(m,0)})' for m in ['low','medium','high'] if m in mc.index)}
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
- Random frame decode latency (avg, p50, p95, p99)

## Hardware & Software

| Item | Value |
|------|-------|
| OS | {si.get('os', 'N/A')} {si.get('os_release', '')} |
| CPU | {si.get('processor', 'N/A')} ({si.get('cpu_count_logical', 'N/A')} cores) |
| RAM | {si.get('ram_total_gb', 'N/A')} GB |
| FFmpeg | {si.get('ffmpeg_version', 'N/A')} |
| REEL | {si.get('reel_version', 'N/A')} |
| Rust | {si.get('rustc_version', 'N/A')} |
| Python | {si.get('python_version', 'N/A')} |

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
"""
    out = RESULTS_DIR / "methodology_draft.md"
    out.write_text(text)
    print(f"    {out}")


# ─── Summary Report ────────────────────────────────────────────────

def generate_summary_report(df):
    lines = [
        "# REEL Codec Benchmark — Summary Report",
        f"\nGenerated: {datetime.now().isoformat()}",
        f"Videos: {df['video_id'].nunique()} | "
        f"Codecs: {', '.join(CODEC_ORDER)}",
        "",
        "## Compression Ratio (higher = better)",
    ]
    for c, v in df.groupby("codec")["compression_ratio"].mean().reindex(CODEC_ORDER).items():
        lines.append(f"- **{c}**: {v:.2f}x")

    lines += ["", "## Encode Speed (fps)"]
    for c, v in df.groupby("codec")["encode_fps"].mean().reindex(CODEC_ORDER).items():
        lines.append(f"- **{c}**: {v:.0f}")

    lines += ["", "## Decode Speed (fps)"]
    for c, v in df.groupby("codec")["decode_fps"].mean().reindex(CODEC_ORDER).items():
        lines.append(f"- **{c}**: {v:.0f}")

    lines += ["", "## Random Frame Access (ms, lower = better)"]
    for c, v in df.groupby("codec")["rand_frame_decode_avg_ms"].mean().reindex(CODEC_ORDER).items():
        lines.append(f"- **{c}**: {v:.1f}")

    lines += ["", "## Lossless Verification"]
    for c in CODEC_ORDER:
        sub = df[df["codec"] == c]
        pct = (sub["is_lossless"].astype(str).str.lower() == "true").mean() * 100
        lines.append(f"- **{c}**: {pct:.0f}% bit-exact")

    lines += [
        "", "---",
        "Full results: `benchmark_results.csv`",
        "Charts: `results/charts/`",
        "LaTeX: `results/tables/`",
    ]

    out = RESULTS_DIR / "benchmark_report.md"
    out.write_text("\n".join(lines))
    print(f"    {out}")


# ─── Main ──────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  REEL Benchmark — Analysis & Report Generation")
    print("=" * 60)

    if not CSV_PATH.exists():
        print(f"\nError: {CSV_PATH} not found.")
        print("Run 'python benchmark/run_benchmark.py' first.")
        sys.exit(1)

    setup_plot_style()
    os.makedirs(CHARTS_DIR, exist_ok=True)
    os.makedirs(TABLES_DIR, exist_ok=True)

    print("\nLoading data ...")
    df = load_data()
    n_rows = len(df)
    n_vids = df["video_id"].nunique()
    n_codecs = df["codec"].nunique()
    print(f"  {n_rows} rows | {n_vids} videos | {n_codecs} codecs")

    # ── Figures ─────────────────────────────────────────────────────
    print("\nGenerating figures ...")
    fig_encode_time_vs_resolution(df)
    fig_decode_time_vs_resolution(df)
    fig_compression_ratio_vs_resolution(df)
    fig_compression_ratio_heatmap(df)
    fig_random_frame_latency_boxplot(df)
    fig_throughput_bar(df)
    fig_file_size_comparison(df)
    fig_motion_impact(df)
    fig_memory_usage(df)
    fig_realtime_ratio(df)
    fig_bits_per_pixel(df)
    fig_scalability(df)

    # ── LaTeX tables ────────────────────────────────────────────────
    print("\nGenerating LaTeX tables ...")
    gen_latex_overall(df)
    gen_latex_by_resolution(df)
    gen_latex_by_motion(df)
    gen_latex_significance(df)

    # ── Statistics ──────────────────────────────────────────────────
    run_statistical_analysis(df)

    # ── Methodology ─────────────────────────────────────────────────
    print("\nMethodology draft ...")
    generate_methodology(df)

    # ── Report ──────────────────────────────────────────────────────
    print("\nSummary report ...")
    generate_summary_report(df)

    print(f"\n{'=' * 60}")
    print(f"  Analysis complete!")
    print(f"  Charts:      {CHARTS_DIR}")
    print(f"  Tables:      {TABLES_DIR}")
    print(f"  Report:      {RESULTS_DIR / 'benchmark_report.md'}")
    print(f"  Methodology: {RESULTS_DIR / 'methodology_draft.md'}")
    print(f"  Statistics:  {RESULTS_DIR / 'statistical_analysis.json'}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
