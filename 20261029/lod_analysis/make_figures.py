# -*- coding: utf-8 -*-
"""產生報告用的圖(需先跑 lod_analysis.py)。"""
import os, csv, pickle
import numpy as np
import cv2
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from lod_analysis import IMAGES, sub_rois

HERE = os.path.dirname(os.path.abspath(__file__))
vis = pickle.load(open(os.path.join(HERE, "_vis_sub.pkl"), "rb"))
rows = list(csv.DictReader(open(os.path.join(HERE, "results_lod_sub.csv"), encoding="utf-8-sig")))
reps = list(csv.DictReader(open(os.path.join(HERE, "results_replicates_sub.csv"), encoding="utf-8-sig")))
NAMES = list(IMAGES)
SHOW = ["Raw", "Median3", "Deglint", "B", "B2", "Deglint-k13", "B2-k13", "Deglint-k13-grow", "Median-ROI", "B2-k13-BG"]
COL = {"Raw": "#888888", "Deglint": "#1f77b4", "B2": "#2ca02c", "B2-k13": "#d62728", "Deglint-k13-grow": "#9467bd"}


def stretch(g, lo=None, hi=None):
    lo = np.percentile(g, 1) if lo is None else lo
    hi = np.percentile(g, 99.7) if hi is None else hi
    return np.clip((g - lo) * 255 / max(1e-6, hi - lo), 0, 255).astype(np.uint8)


# ── 圖 1:ROI 配置與偵測到的灰塵(kernel 9 紅 / 只多 kernel 13 抓到的 橘)────────────
fig, axes = plt.subplots(len(NAMES), 1, figsize=(12, 2.6 * len(NAMES)))
for ax, n in zip(axes, NAMES):
    gray, per, cfg = vis[n]
    im = cv2.cvtColor(stretch(gray), cv2.COLOR_GRAY2RGB)
    for lab, (vals, ex, (cx, cy)) in per.items():
        im[ex["m13"] & ~ex["m9"]] = (255, 160, 0)
        im[ex["m9"]] = (255, 0, 0)
        cv2.circle(im, (cx, cy), cfg["r"], (255, 215, 0), 1)
        for sx, sy, sr in sub_rois(cx, cy, cfg["r"]):
            cv2.circle(im, (int(sx), int(sy)), int(sr), (0, 255, 255), 1)
        cv2.putText(im, lab, (cx - 22, max(10, cy - cfg["r"] - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    ax.imshow(im); ax.set_title(f"{n}:黃圈 = 樣本 ROI,青圈 = 3 個重複量測子 ROI,紅 = 偵測到的灰塵(kernel 9),橘 = kernel 13 額外抓到", fontsize=9)
    ax.axis("off")
fig.tight_layout(); fig.savefig(os.path.join(HERE, "fig1_roi_layout.png"), dpi=130); plt.close(fig)

# ── 圖 2:blank 樣本特寫(灰塵最影響 LOD 的地方)──────────────────────────────
fig, axes = plt.subplots(len(NAMES), 5, figsize=(12, 2.6 * len(NAMES)))
for row, n in zip(axes, NAMES):
    gray, per, cfg = vis[n]
    vals, ex, (cx, cy) = per[cfg["blank"]]
    r = cfg["r"] + 6
    sl = (slice(max(0, cy - r), cy + r), slice(max(0, cx - r), cx + r))
    ref = gray[sl]; lo, hi = np.percentile(ref, 1), np.percentile(ref, 99.7)
    mk = cv2.cvtColor(stretch(ref, lo, hi), cv2.COLOR_GRAY2RGB); mk[ex["m9"][sl]] = (255, 0, 0)
    panels = [("原圖", stretch(ref, lo, hi)), ("標紅(灰塵)", mk), ("B2", stretch(ex["B2"][sl], lo, hi)),
              ("B2-k13", stretch(ex["B2k"][sl], lo, hi))]
    for ax, (t, p) in zip(row, panels):
        ax.imshow(p, cmap="gray", vmin=0, vmax=255); ax.set_title(f"{n} blank:{t}", fontsize=9); ax.axis("off")
    # 3 個子 ROI 的值
    rr = [x for x in reps if x["image"] == n and x["sample"] == cfg["blank"]]
    txt = "\n".join(f"{x['method']:<11s} {float(x['rep1']):6.2f} {float(x['rep2']):6.2f} {float(x['rep3']):6.2f}  σ={float(x['std']):.2f}"
                    for x in rr if x["method"] in ("Raw", "Deglint", "Deglint-k13-grow", "B2", "B2-k13"))
    row[4].text(0, 0.5, "blank 3 次量測:\n" + txt, fontsize=8, family="monospace", va="center"); row[4].axis("off")
fig.tight_layout(); fig.savefig(os.path.join(HERE, "fig2_blank_closeup.png"), dpi=130); plt.close(fig)

# ── 圖 3:校正曲線(Raw vs 處理後),含 blank+3σ 水平線 ───────────────────────
fig, axes = plt.subplots(1, len(NAMES), figsize=(5.2 * len(NAMES), 4.2))
for ax, n in zip(axes, NAMES):
    cfg = IMAGES[n]
    xs = np.log10([float(l) for l in cfg["fit"]])
    for meth in ("Raw", "Deglint", "Deglint-k13-grow", "B2-k13"):
        d = {x["sample"]: (float(x["mean"]), float(x["std"])) for x in reps if x["image"] == n and x["method"] == meth}
        y = np.array([d[l][0] for l in cfg["fit"]]); e = np.array([d[l][1] for l in cfg["fit"]])
        rr = [x for x in rows if x["image"] == n and x["method"] == meth][0]
        m, b = float(rr["slope"]), float(rr["intercept"])
        ax.errorbar(xs, y, yerr=e, fmt="o", color=COL[meth], capsize=3, ms=5)
        xx = np.linspace(xs.min() - 1.0, xs.max(), 50)
        ax.plot(xx, m * xx + b, color=COL[meth], lw=1.2,
                label=f"{meth}: R²={float(rr['R2']):.3f}, LOD={float(rr['LOD_M']):.1e}")
        ax.axhline(d[cfg["blank"]][0] + 3 * d[cfg["blank"]][1], color=COL[meth], ls=":", lw=1)
    ax.axvline(xs.min(), color="k", ls="--", lw=0.8)
    ax.text(xs.min(), ax.get_ylim()[1], " 最低校正濃度", fontsize=8, va="top")
    ax.set_xlabel("log10(濃度 / M)"); ax.set_ylabel("平均灰階 (ImageJ)")
    ax.set_title(f"{n}(虛點線 = blank + 3σ)", fontsize=10); ax.legend(fontsize=7, loc="upper left"); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(os.path.join(HERE, "fig3_calibration.png"), dpi=130); plt.close(fig)

# ── 圖 4:各方法的 blank σ 與 LOD ───────────────────────────────────────────
fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
w = 0.8 / len(NAMES); x = np.arange(len(SHOW))
for i, n in enumerate(NAMES):
    d = {r["method"]: r for r in rows if r["image"] == n}
    a1.bar(x + i * w, [float(d[m]["blank_std"]) for m in SHOW], w, label=n)
    a2.bar(x + i * w, [float(d[m]["LOD_M"]) for m in SHOW], w, label=n)
    a2.axhline(1e-13, color="k", ls="--", lw=0.8)
a1.set_ylabel("blank 標準差 σ(3 次量測)"); a1.legend(); a1.grid(axis="y", alpha=0.3)
a2.set_yscale("log"); a2.set_ylabel("LOD (M)"); a2.grid(axis="y", alpha=0.3)
from matplotlib.ticker import FuncFormatter, LogLocator
a2.yaxis.set_major_locator(LogLocator(base=10))
a2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"1e{int(round(np.log10(v)))}"))   # 中文字型沒有 mathtext 負號
a2.text(len(SHOW) - 0.5, 1.3e-13, "最低校正濃度 1e-13 M(低於此為外插)", fontsize=8, ha="right")
a2.set_xticks(x + w * (len(NAMES) - 1) / 2); a2.set_xticklabels(SHOW, rotation=20)
fig.tight_layout(); fig.savefig(os.path.join(HERE, "fig4_sigma_lod.png"), dpi=130); plt.close(fig)
print("figures done")
