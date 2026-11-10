# -*- coding: utf-8 -*-
"""
背景變亮是「照明不均」還是「樣本的光散到背景」?—— 用濃度順序不同的影像來分辨

B-8 的濃度由左到右遞增,背景也由左到右變亮,兩者綁在一起分不開。
B-2(h)/(l) 的濃度順序是打亂的:
  - 背景跟著「位置」變(越右越亮,不管旁邊是什麼濃度) → 照明不均
  - 背景跟著「旁邊樣本的亮度」變(亮樣本旁邊的背景就亮) → 樣本的光散到背景

背景量在「相鄰樣本之間的縫隙」與「影像左右兩端」(B-2 的樣本幾乎填滿高度,上下方沒有背景):
  縫隙 = 兩樣本中點 ±6 px 的直條、在兩個樣本實際範圍以外的像素中位數;旁邊亮度 = 兩側樣本平均
再用 背景 = a + b·(x/寬) + c·旁邊樣本亮度 迴歸。
灰階 = (R+G+B)/3(同 lod_analysis);灰塵用顏色抓((R+B)/2 > 4,外擴 2 px)後不計入背景。
用法:python bg_vs_order.py   輸出:bg_vs_order.png、bg_vs_order.csv
"""
import os, csv
import numpy as np
import cv2
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import lod_analysis as LA
from b8_analysis import load_rgb, dust_mask

HERE = os.path.dirname(os.path.abspath(__file__))
GAP = 6              # 縫隙直條半寬(px)


def extent(sm, cx, cy, r0, rmax):
    """樣本實際半徑(同程式 _sample_extent):往外每圈平均亮度降到 背景+10%·(樣本−背景) 處。"""
    H, W = sm.shape
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.hypot(xx - cx, yy - cy).astype(int)
    m = d <= rmax
    cnt = np.bincount(d[m], minlength=rmax + 1)
    prof = np.bincount(d[m], weights=sm[m], minlength=rmax + 1) / np.maximum(cnt, 1)
    ok = cnt > 0
    prof = np.interp(np.arange(rmax + 1), np.flatnonzero(ok), prof[ok])
    prof = np.convolve(np.pad(prof, 2, mode="edge"), np.ones(5) / 5, "valid")
    peak, base = prof[:r0 + 1].max(), prof[r0:].min()
    if peak - base < 1.0:
        return r0
    hit = np.flatnonzero(prof[r0:] <= base + 0.1 * (peak - base))
    return r0 + int(hit[0]) if hit.size else rmax


rows, per_img = [], {}
for name, cfg in LA.IMAGES.items():
    R, G, B = load_rgb(os.path.join(LA.IMG_DIR, cfg["file"]))
    gray = (R + G + B) / 3
    dust = dust_mask(R, B)
    sm = cv2.medianBlur(np.clip(np.round(gray), 0, 255).astype(np.uint8), 5).astype(np.float32)
    H, W = gray.shape
    yy, xx = np.mgrid[0:H, 0:W]
    cs = LA.centers(gray, cfg["guess"], cfg["y"], cfg["half"])
    spacing = np.median(np.diff([c[0] for c in cs]))
    ext = [extent(sm, cx, cy, cfg["r"], int(spacing * 0.6)) for cx, cy in cs]
    S = [float(np.median(gray[np.hypot(xx - cx, yy - cy) <= cfg["r"]])) for cx, cy in cs]
    outside = np.ones((H, W), bool)
    for (cx, cy), e in zip(cs, ext):
        outside &= np.hypot(xx - cx, yy - cy) > e
    bgok = outside & ~dust

    pts = []   # (位置 x, 背景, 旁邊樣本亮度, 說明, 區域遮罩)
    regions = [(xx < cs[0][0] - ext[0], S[0], f"左端|{cfg['labels'][0]}")]
    for i in range(len(cs) - 1):
        mid = (cs[i][0] + cs[i + 1][0]) / 2
        regions.append((np.abs(xx - mid) <= GAP, (S[i] + S[i + 1]) / 2, f"{cfg['labels'][i]}|{cfg['labels'][i + 1]}"))
    regions.append((xx > cs[-1][0] + ext[-1], S[-1], f"{cfg['labels'][-1]}|右端"))
    for reg, nb, lab in regions:
        m = reg & bgok
        if m.sum() < 40:
            continue
        pts.append((float(xx[m].mean()), float(np.median(gray[m])), nb, lab, m))
        rows.append([name, lab, round(float(xx[m].mean())), round(float(np.median(gray[m])), 3), round(nb, 2), int(m.sum())])

    x = np.array([p[0] for p in pts]) / W; bg = np.array([p[1] for p in pts]); nb = np.array([p[2] for p in pts])
    coef = np.linalg.lstsq(np.stack([np.ones_like(x), x, nb], 1), bg, rcond=None)[0]
    cx_nb, cx_bg, cnb_bg = np.corrcoef(x, nb)[0, 1], np.corrcoef(x, bg)[0, 1], np.corrcoef(nb, bg)[0, 1]
    per_img[name] = dict(gray=gray, cs=cs, ext=ext, pts=pts, coef=coef, W=W, S=S, labels=cfg["labels"],
                         corr=(cx_nb, cx_bg, cnb_bg))
    print(f"\n══ {name}  ({W}x{H}, 樣本實際半徑 {ext})")
    print("   樣本亮度 " + "  ".join(f"{l}:{s:.1f}" for l, s in zip(cfg["labels"], S)))
    print("   背景     " + "  ".join(f"[{p[3]}] x={p[0]:.0f} 背景 {p[1]:.2f}" for p in pts))
    print(f"   corr(位置, 旁邊亮度) {cx_nb:+.2f} | corr(位置, 背景) {cx_bg:+.2f} | corr(旁邊亮度, 背景) {cnb_bg:+.2f}")
    print(f"   迴歸 背景 = {coef[0]:.2f} {coef[1]:+.2f}·(x/寬) {coef[2]:+.3f}·旁邊亮度"
          f"  → 左到右 {coef[1]:+.2f};旁邊亮度從最暗到最亮 {coef[2] * (nb.max() - nb.min()):+.2f}")

with open(os.path.join(HERE, "bg_vs_order.csv"), "w", newline="", encoding="utf-8-sig") as fp:
    w = csv.writer(fp)
    w.writerow(["image", "region", "x_px", "background", "neighbor_sample_brightness", "pixels"])
    w.writerows(rows)

# ── 圖:每張影像一列 = 影像(標量背景的位置)/ 背景 vs 位置 / 背景 vs 旁邊樣本亮度 ──
n = len(per_img)
fig, axes = plt.subplots(n, 3, figsize=(17, 3.2 * n), gridspec_kw=dict(width_ratios=[1.5, 1, 1]))
for i, (name, d) in enumerate(per_img.items()):
    g = d["gray"]
    ax = axes[i, 0]
    ax.imshow(g, cmap="gray", vmin=np.percentile(g, 1), vmax=np.percentile(g, 99.5))
    ov = np.zeros(g.shape + (4,));
    for p in d["pts"]:
        ov[p[4]] = (0, 1, 1, 0.55)
    ax.imshow(ov)
    for (cx, cy), e, lab in zip(d["cs"], d["ext"], d["labels"]):
        ax.add_patch(plt.Circle((cx, cy), e, fill=False, color="magenta", lw=0.8))
        ax.text(cx, 4, lab, color="yellow", ha="center", va="top", fontsize=8)
    ax.set_title(f"{name}:青色 = 量背景的位置(縫隙、兩端),紫圈 = 樣本實際範圍", fontsize=9); ax.axis("off")
    xs = [p[0] for p in d["pts"]]; bg = [p[1] for p in d["pts"]]; nb = [p[2] for p in d["pts"]]
    c = d["corr"]
    ax = axes[i, 1]
    ax.plot(xs, bg, "o-", color="#d62728")
    for p in d["pts"]:
        ax.annotate(p[3], (p[0], p[1]), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=7)
    ax.set_xlabel("位置 x (px)"); ax.set_ylabel("背景灰階")
    ax.set_title(f"背景 vs 位置(相關係數 {c[1]:+.2f})", fontsize=9)
    ax = axes[i, 2]
    ax.scatter(nb, bg, color="#2ca02c")
    for p in d["pts"]:
        ax.annotate(p[3], (p[2], p[1]), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=7)
    ax.set_xlabel("旁邊樣本亮度"); ax.set_ylabel("背景灰階")
    ax.set_title(f"背景 vs 旁邊樣本亮度(相關係數 {c[2]:+.2f};位置與旁邊亮度 {c[0]:+.2f})", fontsize=9)
fig.tight_layout()
p = os.path.join(HERE, "bg_vs_order.png"); fig.savefig(p, dpi=100)
print("\n已存", p)
