# -*- coding: utf-8 -*-
"""
White Top-hat 過程視覺化 / Step-by-step visualiser

用「地形 + 滾球」的角度,把去反光的每一步畫出來:
  原圖 → 侵蝕 Erosion → 膨脹(=開運算 Opening) → Top-hat(原圖-Opening)
       → 偵測(門檻) → 去除後
可拉滑桿改變 kernel(刷子大小)與 K(門檻嚴格度),即時看過程變化。

用法:  python tophat_demo.py [影像路徑]
預設影像:20260815.jpg
"""
import sys
import numpy as np
from PIL import Image
import matplotlib
matplotlib.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei",
                                          "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider
from scipy.ndimage import grey_erosion, grey_dilation

IMG_PATH = sys.argv[1] if len(sys.argv) > 1 else "20260815.jpg"

gray = np.asarray(Image.open(IMG_PATH).convert("L"), dtype=np.uint8)
H, W = gray.shape

# ── 版面:上排 6 張影像 + 下方一條「地形剖面」+ 三個滑桿 ────────────────
fig = plt.figure(figsize=(16, 7))
gs = fig.add_gridspec(2, 6, height_ratios=[3, 2], hspace=0.35, wspace=0.12)
titles = ["1. 原圖 Original", "2. 侵蝕 Erosion（取最小）",
          "3. 膨脹→開運算 Opening", "4. Top-hat（原圖-Opening）",
          "5. 偵測 Detected（紅）", "6. 去除後 After"]
img_ax = [fig.add_subplot(gs[0, i]) for i in range(6)]
prof_ax = fig.add_subplot(gs[1, :])

# 滑桿
plt.subplots_adjust(bottom=0.20)
ax_k   = plt.axes([0.10, 0.10, 0.35, 0.03])
ax_K   = plt.axes([0.10, 0.055, 0.35, 0.03])
ax_row = plt.axes([0.60, 0.10, 0.32, 0.03])
s_kern = Slider(ax_k,   "kernel（刷子大小）", 3, 41, valinit=9,  valstep=2)
s_K    = Slider(ax_K,   "K（門檻嚴格度）",     1.0, 6.0, valinit=3.0, valstep=0.1)
s_row  = Slider(ax_row, "剖面列 row",          0, H - 1, valinit=H // 2, valstep=1)


def compute(k, K):
    ero    = grey_erosion(gray, size=(k, k))          # 侵蝕:窗內取最小 → 亮區縮、小亮點消失
    opened = grey_dilation(ero, size=(k, k))          # 膨脹侵蝕結果 = 開運算 Opening
    tophat = np.clip(gray.astype(np.int16) - opened.astype(np.int16), 0, None).astype(np.uint8)
    thr    = float(tophat.mean() + K * tophat.std())
    mask   = tophat > thr
    after  = gray.copy()
    after[mask] = opened[mask]                        # 去除後:反光用 opening(周邊背景)值取代
    return ero, opened, tophat, thr, mask, after


def draw(_=None):
    k = int(s_kern.val); K = float(s_K.val); row = int(s_row.val)
    ero, opened, tophat, thr, mask, after = compute(k, K)

    detected = np.dstack([gray, gray, gray]).astype(np.uint8)
    detected[mask] = [255, 40, 40]

    panels = [gray, ero, opened, tophat, detected, after]
    cmaps  = ["gray", "gray", "gray", "magma", None, "gray"]
    for ax, im, cm, tt in zip(img_ax, panels, cmaps, titles):
        ax.clear()
        ax.imshow(im, cmap=cm, vmin=None if cm is None else 0)
        ax.axhline(row, color="#00E5FF", lw=0.8)      # 標出目前剖面位置
        ax.set_title(tt, fontsize=8); ax.set_xticks([]); ax.set_yticks([])

    # 下方:地形剖面(藍=原圖, 綠=侵蝕下拉, 橘=開運算, 紅填色=Top-hat 殘留)
    prof_ax.clear()
    x = np.arange(W)
    g = gray[row].astype(float); e = ero[row].astype(float); o = opened[row].astype(float)
    prof_ax.plot(x, g, color="#1f77b4", lw=1.0, label="原圖 gray（地形高度）")
    prof_ax.plot(x, e, color="#2ca02c", lw=1.0, ls=":",  label="侵蝕 Erosion（取最小,下拉）")
    prof_ax.plot(x, o, color="#ff7f0e", lw=1.2, label="開運算 Opening（膨脹回來的下緣）")
    prof_ax.fill_between(x, o, g, where=(g > o), color="#d62728", alpha=0.35,
                         label="Top-hat = 原圖 - Opening（小亮點）")
    m = mask[row]
    if m.any():
        prof_ax.plot(x[m], g[m], "o", ms=3, color="#d62728", label="判定為反光")
    prof_ax.set_title(f"第 {row} 列剖面  |  kernel={k}  K={K:.1f}  門檻(top-hat)>{thr:.1f}"
                      f"  |  被去除 {100*mask.mean():.2f}%", fontsize=9)
    prof_ax.set_xlabel("像素位置 x"); prof_ax.set_ylabel("灰階")
    prof_ax.grid(True, alpha=0.3); prof_ax.legend(fontsize=8, loc="upper right")
    fig.canvas.draw_idle()


for s in (s_kern, s_K, s_row):
    s.on_changed(draw)
draw()

if __name__ == "__main__":
    import matplotlib
    if matplotlib.get_backend().lower() == "agg":
        fig.savefig("tophat_demo.png", dpi=120, bbox_inches="tight")
        print("已存圖:tophat_demo.png")
    else:
        plt.show()
