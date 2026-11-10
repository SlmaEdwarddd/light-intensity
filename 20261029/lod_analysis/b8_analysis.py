# -*- coding: utf-8 -*-
"""
B-8 專題:找比 Top-hat 去灰塵更適合 B-8 的處理方式

B-8 的兩個問題(見 灰塵雜訊影像處理與LOD分析報告.md):
  1. 灰塵:Top-hat 去灰塵後 CV 變好,但斜率 2.40 → 1.61、LOD 變差(1e-13 與 blank 分不開)
  2. 照明不均:背景左暗右亮,而 B-8 的濃度剛好由左到右增加 → 照明梯度可能被當成訊號

新的兩個想法:
  A. 用「顏色」抓灰塵:螢光樣本只有綠色(R、B ≈ 0),灰塵偏白(R、B 明顯升高)
     → (R+B)/2 > 門檻 的像素(外擴 2 px 含光暈)不計入,不會誤刪樣本本身較亮的紋理
  B. 用樣本外圈背景校正照明:
     - 扣背景(net = 樣本 − 背景)       :去掉加性的背景,但照明倍率仍在
     - 比值(ratio = 樣本 / 背景)        :照明是乘上去的 → 比值與照明無關
     - 全圖背景擬合(2 次曲面)後除以照明:同 20261026 的背景估計校正

量測流程、ROI、重複量測、LOD 公式與 lod_analysis.py 相同。
用法:python b8_analysis.py   輸出:b8_results.csv、b8_fig_*.png
"""
import os, csv
import numpy as np
import cv2
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import lod_analysis as LA

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = LA.IMAGES["B-8"]
DUST_RB = 4.0          # ponytail: (R+B)/2 > 4 視為灰塵(背景約 0.7);依相機雜訊調整
DUST_GROW = 2          # 灰塵遮罩外擴 px(含光暈)
SAMPLE_R = 50          # 樣本本體半徑(px,直徑約 100)
RING = (56, 66)        # 外圈背景環(px):樣本外、碰不到相鄰樣本(間距約 125)


def load_rgb(path):
    im = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32)
    return im[..., 2], im[..., 1], im[..., 0]          # R, G, B


def dust_mask(R, B):
    m = ((R + B) / 2 > DUST_RB).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * DUST_GROW + 1,) * 2)
    return cv2.dilate(m, k) > 0


def illum_fit(img, valid, deg=2):
    """全圖背景 2 次曲面擬合(同 20261026 背景估計);valid = 可當背景的像素。"""
    H, W = img.shape
    ys, xs = np.mgrid[0:H:3, 0:W:3]
    keep = valid[ys, xs]
    xn, yn = xs[keep] / W * 2 - 1, ys[keep] / H * 2 - 1
    A = np.stack([xn ** i * yn ** j for i in range(deg + 1) for j in range(deg + 1 - i)], -1)
    b = img[ys, xs][keep]
    ok = np.ones(b.shape, bool)
    for _ in range(10):
        c = np.linalg.lstsq(A[ok], b[ok], rcond=None)[0]
        r = b - A @ c
        s = 1.4826 * np.median(np.abs(r[ok] - np.median(r[ok]))) + 1e-6
        new = (r < 2 * s) & (r > -3 * s)
        if (new == ok).all():
            break
        ok = new
    yy, xx = np.mgrid[0:H, 0:W]
    X, Y = xx / W * 2 - 1, yy / H * 2 - 1
    return sum(ci * X ** i * Y ** j for ci, (i, j) in zip(c, [(i, j) for i in range(deg + 1) for j in range(deg + 1 - i)]))


def main(rep_mode):
    LA.REP_MODE = rep_mode
    R, G, B = load_rgb(os.path.join(LA.IMG_DIR, CFG["file"]))
    gray = (R + G + B) / 3
    cs = LA.centers(gray, CFG["guess"], CFG["y"], CFG["half"])
    shape = gray.shape
    dust = dust_mask(R, B)
    spots_all = np.zeros(shape, bool)
    for cx, cy in cs:
        spots_all |= LA.disk(shape, cx, cy, SAMPLE_R + 6)
    illum = illum_fit(G, ~spots_all & ~dust)
    G_flat = G / np.clip(illum, 1e-3, None) * float(np.mean(illum[~spots_all]))

    methods = ["Raw", "Deglint-k13-grow", "G", "Color-dust", "Color-dust + 扣背景", "Color-dust + 比值", "Color-dust + 照明擬合"]
    stats = {m: {} for m in methods}
    diag = []
    for lab, (cx, cy) in zip(CFG["labels"], cs):
        inside = LA.disk(shape, cx, cy, CFG["r"])
        m13 = LA.glint_mask(gray, cx, cy, CFG["r"], 13)
        kg = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * LA.GROW + 1,) * 2)
        m13g = (cv2.dilate(m13.astype(np.uint8), kg) > 0) & inside
        ring = LA.disk(shape, cx, cy, RING[1]) & ~LA.disk(shape, cx, cy, RING[0]) & ~dust
        bg = float(np.median(G[ring]))
        vals = {m: [] for m in methods}
        for sx, sy, sr in LA.sub_rois(cx, cy, CFG["r"]):
            s = LA.disk(shape, sx, sy, sr)
            keep = s & ~dust
            vals["Raw"].append(gray[s].mean())
            vals["Deglint-k13-grow"].append(gray[s & ~m13g].mean())
            vals["G"].append(G[s].mean())
            vals["Color-dust"].append(G[keep].mean())
            vals["Color-dust + 扣背景"].append(G[keep].mean() - bg)
            vals["Color-dust + 比值"].append(G[keep].mean() / bg)
            vals["Color-dust + 照明擬合"].append(G_flat[keep].mean())
        for m in methods:
            stats[m][lab] = (float(np.mean(vals[m])), float(np.std(vals[m], ddof=1)))
        diag.append((lab, cx, bg, 100 * (inside & dust).sum() / inside.sum(), 100 * m13g.sum() / inside.sum(),
                     float(illum[cy, cx])))
    return cs, stats, methods, diag, (R, G, B, gray, dust, illum, spots_all)


def evaluate(stats, methods):
    rows = []
    for m in methods:
        mm, b, r2, log_lod = LA.fit_lod(stats[m], CFG["fit"], "blank")
        mu, sd = stats[m]["blank"]
        lo = stats[m]["1e-13"][0]
        cv = np.mean([100 * stats[m][l][1] / abs(stats[m][l][0]) for l in CFG["fit"]])
        # 1e-13 比 blank 高出幾個 blank σ;1e-9 相對 1e-10 的變化(原始數據 1e-9 比 1e-10 低)
        z13 = (lo - mu) / sd if sd > 0 else float("inf")
        hook = stats[m]["1e-9"][0] - stats[m]["1e-10"][0]
        rows.append(dict(method=m, slope=mm, intercept=b, R2=r2, blank_mean=mu, blank_std=sd, CV=cv,
                         LOD=10 ** log_lod, z13=z13, hook=hook, rel_slope=mm / max(abs(mu), 1e-9)))
    return rows


if __name__ == "__main__":
    out_rows = []
    for mode in ("sub", "jitter"):
        cs, stats, methods, diag, imgs = main(mode)
        rows = evaluate(stats, methods)
        if mode == "sub":
            print("樣本 | 中心 x | 外圈背景 G | ROI 內顏色灰塵% | ROI 內 Top-hat 標記% | 照明擬合值")
            for lab, cx, bg, dpct, tpct, il in diag:
                print(f"  {lab:6s} {cx:4d}   {bg:6.2f}        {dpct:5.1f}%            {tpct:5.1f}%          {il:6.2f}")
        print(f"\n重複量測定義:{mode}")
        print(f"  {'方法':22s} 斜率   R²     blank μ±σ      CV%   1e-13 高出 blank   LOD (M)   1e-9 − 1e-10")
        for r in rows:
            flag = " *" if r["LOD"] < 1e-13 else "  "
            print(f"  {r['method']:22s} {r['slope']:6.3f} {r['R2']:.3f} {r['blank_mean']:7.3f}±{r['blank_std']:.3f} "
                  f"{r['CV']:5.1f}   {r['z13']:6.1f} σ        {r['LOD']:.1e}{flag} {r['hook']:+7.3f}")
            out_rows.append([mode] + [r[k] if isinstance(r[k], str) else f"{r[k]:.6g}" for k in
                                      ("method", "slope", "intercept", "R2", "blank_mean", "blank_std", "CV", "z13", "LOD", "hook")])
        if mode == "sub":
            sub_stats, sub_rows, sub_imgs, sub_cs = stats, rows, imgs, cs

    with open(os.path.join(HERE, "b8_results.csv"), "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["rep_mode", "method", "slope", "intercept", "R2", "blank_mean", "blank_std", "fit_CV%",
                    "1e-13_minus_blank_in_sigma", "LOD_M", "1e-9_minus_1e-10"])
        w.writerows(out_rows)

    # ── 圖:通道 / 灰塵遮罩 / 照明 ──────────────────────────────────────────────
    R, G, B, gray, dust, illum, spots_all = sub_imgs
    fig, ax = plt.subplots(4, 1, figsize=(12, 11))
    ax[0].imshow(np.clip(G * 4, 0, 255), cmap="gray", vmin=0, vmax=255); ax[0].set_title("G 通道(螢光)", fontsize=10)
    ax[1].imshow(np.clip((R + B) / 2 * 25, 0, 255), cmap="gray", vmin=0, vmax=255)
    ax[1].set_title("(R+B)/2 通道:只有灰塵發亮,樣本幾乎看不到", fontsize=10)
    ov = cv2.cvtColor(np.clip(G * 4, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2RGB); ov[dust] = (255, 0, 0)
    for (cx, cy), lab in zip(sub_cs, CFG["labels"]):
        cv2.circle(ov, (cx, cy), CFG["r"], (255, 215, 0), 1)
        cv2.circle(ov, (cx, cy), RING[0], (0, 200, 255), 1); cv2.circle(ov, (cx, cy), RING[1], (0, 200, 255), 1)
        cv2.putText(ov, lab, (cx - 20, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    ax[2].imshow(ov); ax[2].set_title(f"顏色灰塵遮罩(紅,(R+B)/2 > {DUST_RB:g} 外擴 {DUST_GROW} px)、ROI(黃)、外圈背景環(藍)", fontsize=10)
    im3 = ax[3].imshow(illum, cmap="viridis"); ax[3].set_title("全圖背景擬合的照明分佈(G 通道):左暗右亮", fontsize=10)
    fig.colorbar(im3, ax=ax[3], fraction=0.015)
    for a in ax:
        a.axis("off")
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "b8_fig_channels.png"), dpi=120); plt.close(fig)

    # ── 圖:各方法校正曲線(含 blank 與 1e-9,正規化到 blank=0、1e-10=1 方便比較形狀)──
    show = ["Raw", "Deglint-k13-grow", "Color-dust", "Color-dust + 比值", "Color-dust + 照明擬合"]
    order = ["1e-13", "1e-12", "1e-11", "1e-10", "1e-9"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6))
    for m in show:
        st = sub_stats[m]; b0 = st["blank"][0]; top = st["1e-10"][0] - b0
        x = [np.log10(float(l)) for l in order]
        y = [(st[l][0] - b0) / top for l in order]; e = [st[l][1] / abs(top) for l in order]
        a1.errorbar(x, y, yerr=e, marker="o", capsize=3, label=m)
    a1.axhline(0, color="k", lw=0.8, ls=":"); a1.set_xlabel("log10(濃度 / M)"); a1.set_ylabel("(訊號 − blank) / (1e-10 − blank)")
    a1.set_title("校正曲線形狀(blank = 0,1e-10 = 1);誤差棒 = 3 個子 ROI 標準差", fontsize=10); a1.legend(fontsize=8); a1.grid(alpha=0.3)
    names = [r["method"] for r in sub_rows]
    a2.barh(names, [r["LOD"] for r in sub_rows], color=["#888" if r["LOD"] >= 1e-13 else "#d62728" for r in sub_rows])
    a2.set_xscale("log"); a2.axvline(1e-13, color="k", ls="--", lw=0.8)
    a2.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"1e{int(round(np.log10(v)))}"))
    a2.set_title("LOD(M,子 ROI 定義;虛線 = 最低校正濃度,紅 = 外插)", fontsize=10); a2.grid(axis="x", alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "b8_fig_methods.png"), dpi=120); plt.close(fig)
    print("\n已輸出 b8_results.csv、b8_fig_channels.png、b8_fig_methods.png")
