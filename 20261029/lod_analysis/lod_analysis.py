# -*- coding: utf-8 -*-
"""
灰塵雜訊對 LOD 的影響:比較多種影像處理方式(只處理樣本 ROI)

流程(與使用者 Excel「Chi 數據分析 20261029 Ozzy.xlsx」一致):
  灰階 = ImageJ 算法 (R+G+B)/3 → 每個樣本 3 個子 ROI 當 3 次量測 → 平均 / 標準差(ddof=1, 同 Excel STDEV)
  校正曲線:強度 = m·log10(C) + b(用 Excel 圖表的同一組濃度點)
  LOD = 10^((μ_blank + 3σ_blank − b) / m)

處理方式(全部只作用在樣本 ROI 內):
  Raw           原始平均(= ImageJ 直接量)
  Median3       3x3 中值濾波後平均
  Deglint       White Top-hat 偵測灰塵(K=4, kernel 9),灰塵像素不計入平均(= 程式現行分數)
  B             灰塵像素用鄰近顏色補(Telea inpaint)後平均
  B2            B 再處理一次(連灰塵光暈 2 px 一起補)後平均
  Deglint-k13   同 Deglint,kernel 13(抓得到較大的灰塵/氣泡)
  B2-k13        同 B2,kernel 13
  Deglint-k13-grow  kernel 13 偵測後,灰塵 + 外擴 2 px 光暈都不計入平均(排除版的 B2,不補任何數值)
  Median-ROI    子 ROI 的中位數(穩健統計,不需偵測)
  B2-k13-BG     B2-k13 再扣掉樣本外圈環形區的局部背景(中位數)→ 修正照明不均

用法:python lod_analysis.py      (light_intensity conda 環境)
輸出:results_*.csv、fig_*.png(本資料夾)
"""
import os, sys, csv
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(HERE, "..", "test image")
K = 4.0
GROW = 2
# 重複量測的定義:sub = 樣本內 3 個不同位置的子 ROI;jitter = 整顆 ROI 重畫 3 次(位置偏移 ±3 px)
REP_MODE = sys.argv[1] if len(sys.argv) > 1 else "sub"

# 樣本由左到右的濃度標籤、初估中心、ROI 半徑;fit = Excel 圖表用的濃度點;blank = 算 LOD 的空白樣本
IMAGES = {
    "B-2(h)": dict(file="Chi 20261014 B_2 (h).png", r=30, y=(20, 145), half=45,
                   labels=["1e-13", "1e-11", "1e-9", "blank", "0", "1e-10", "control"],
                   guess=[75, 184, 295, 410, 509, 621, 727],
                   fit=["1e-13", "1e-11", "1e-10", "1e-9"], blank="blank",
                   excel={"1e-13": (28.641, 0.424), "1e-11": (33.572, 0.342), "1e-9": (45.617, 3.855),
                          "blank": (21.999, 1.432), "0": (23.064, 2.203), "1e-10": (36.593, 1.154),
                          "control": (48.782, 1.790)}),
    "B-2(l)": dict(file="Chi 20261014 B_2 (l).jpg", r=24, y=(15, 125), half=40,
                   labels=["1e-13", "1e-11", "1e-9", "blank", "0", "1e-10"],
                   guess=[62, 160, 255, 355, 462, 555],
                   fit=["1e-13", "1e-11", "1e-10", "1e-9"], blank="blank",
                   excel={"1e-13": (21.223, 0.602), "1e-11": (25.080, 0.216), "1e-9": (30.880, 3.029),
                          "blank": (15.437, 0.936), "0": (18.517, 2.060), "1e-10": (28.216, 0.959)}),
    "B-8": dict(file="Chi 20261014 B_8.png", r=30, y=(40, 150), half=50,
                labels=["blank", "1e-13", "1e-12", "1e-11", "1e-10", "1e-9"],
                guess=[134, 263, 386, 513, 638, 764],
                fit=["1e-13", "1e-12", "1e-11", "1e-10"], blank="blank",
                excel={"blank": (6.037, 0.100), "1e-13": (6.705, 0.153), "1e-12": (8.663, 0.247),
                       "1e-11": (11.180, 0.336), "1e-10": (13.694, 0.354), "1e-9": (12.016, 0.157)}),
}
METHODS = ["Raw", "Median3", "Deglint", "B", "B2", "Deglint-k13", "B2-k13", "Deglint-k13-grow", "Median-ROI", "B2-k13-BG"]


def load_gray(path):
    im = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED)
    return im[..., :3].astype(np.float32).mean(-1)            # ImageJ RGB → 8-bit:(R+G+B)/3


def centers(gray, guess, yr, half):
    """去亮點 + 模糊後,在初估位置附近取亮度質心(扣視窗 40 百分位當背景)。"""
    m = cv2.GaussianBlur(cv2.medianBlur(np.clip(gray, 0, 255).astype(np.uint8), 9).astype(np.float32), (0, 0), 6)
    out = []
    for gx in guess:
        x0 = max(0, gx - half)
        win = m[yr[0]:yr[1], x0:gx + half]
        w = np.clip(win - np.percentile(win, 40), 0, None)
        ys, xs = np.mgrid[0:win.shape[0], 0:win.shape[1]]
        out.append((int(round((xs * w).sum() / w.sum() + x0)), int(round((ys * w).sum() / w.sum() + yr[0]))))
    return out


def disk(shape, cx, cy, r):
    m = np.zeros(shape, np.uint8)
    cv2.circle(m, (int(cx), int(cy)), int(r), 1, -1)
    return m.astype(bool)


def glint_mask(gray, cx, cy, r, kernel):
    """與程式 _roi_glint 相同:ROI 外擴 kernel 的區塊做 White Top-hat,門檻 = ROI 內 median + K·1.4826·MAD。"""
    H, W = gray.shape
    x1, x2, y1, y2 = max(0, cx - r - kernel), min(W, cx + r + kernel), max(0, cy - r - kernel), min(H, cy + r + kernel)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    th = np.zeros_like(gray)
    th[y1:y2, x1:x2] = cv2.morphologyEx(gray[y1:y2, x1:x2], cv2.MORPH_TOPHAT, k)
    inside = disk(gray.shape, cx, cy, r)
    v = th[inside]
    med = float(np.median(v)); mad = max(float(np.median(np.abs(v - med))), 1.0 / 3)   # 灰階為 (R+G+B)/3,最小單位 1/3
    return (th > med + K * 1.4826 * mad) & inside


def inpaint(gray, mask):
    """Telea inpaint。OpenCV 只收 8-bit,所以對四捨五入的整數部分 inpaint,
    沒被補的像素再加回原本的小數部分((R+G+B)/3 有 1/3 精度),只有補上的像素是整數。"""
    base = np.clip(np.round(gray), 0, 255).astype(np.uint8)
    out = cv2.inpaint(base, mask.astype(np.uint8), 3, cv2.INPAINT_TELEA).astype(np.float32)
    return out + np.where(mask, 0, gray - base.astype(np.float32))


def inpaint_roi(gray, mask, inside):
    """只用 ROI 內的正常像素當補值來源(與程式 fill_glint 相同):在 ROI 外接方框內做,
    圓外像素也當成缺口不參考,補完還原。否則壓在圓周上的灰塵會從圓外被延伸進來變成白點。"""
    ys, xs = np.nonzero(inside)
    y1, y2, x1, x2 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    out = gray.copy()
    sub_in = inside[y1:y2, x1:x2]
    filled = inpaint(gray[y1:y2, x1:x2], mask[y1:y2, x1:x2] | ~sub_in)
    out[y1:y2, x1:x2] = np.where(sub_in, filled, gray[y1:y2, x1:x2])
    return out


def b2(gray, mask, inside):
    g1 = inpaint_roi(gray, mask, inside)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * GROW + 1,) * 2)
    grow = (cv2.dilate(mask.astype(np.uint8), k) > 0) & inside
    return inpaint_roi(g1, grow, inside)


def sub_rois(cx, cy, r):
    if REP_MODE == "jitter":
        return [(cx - 3, cy, r), (cx + 3, cy, r), (cx, cy + 3, r)]
    """每個樣本 3 個子 ROI(120° 間隔、距中心 0.5r、半徑 0.45r)= 3 次重複量測。"""
    return [(cx + 0.5 * r * np.cos(a), cy + 0.5 * r * np.sin(a), 0.45 * r) for a in np.deg2rad([-90, 30, 150])]


def measure(gray, cx, cy, r):
    """回傳 {方法: [3 個子 ROI 的值]} 與給視覺化用的中間結果。"""
    inside = disk(gray.shape, cx, cy, r)
    m9, m13 = glint_mask(gray, cx, cy, r, 9), glint_mask(gray, cx, cy, r, 13)
    med3 = cv2.medianBlur(np.clip(np.round(gray), 0, 255).astype(np.uint8), 3).astype(np.float32)
    imgB, imgB2, imgB2k = inpaint_roi(gray, m9, inside), b2(gray, m9, inside), b2(gray, m13, inside)
    kg = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * GROW + 1,) * 2)
    m13g = (cv2.dilate(m13.astype(np.uint8), kg) > 0) & inside
    ring = disk(gray.shape, cx, cy, int(r * 2.0)) & ~disk(gray.shape, cx, cy, int(r * 1.5))     # 樣本外圈背景
    bg = float(np.median(gray[ring]))          # 中位數本身不受少數灰塵亮點影響
    out = {m: [] for m in METHODS}
    for sx, sy, sr in sub_rois(cx, cy, r):
        s = disk(gray.shape, sx, sy, sr)
        out["Raw"].append(gray[s].mean())
        out["Median3"].append(med3[s].mean())
        out["Deglint"].append(gray[s & ~m9].mean())
        out["B"].append(imgB[s].mean())
        out["B2"].append(imgB2[s].mean())
        out["Deglint-k13"].append(gray[s & ~m13].mean())
        out["B2-k13"].append(imgB2k[s].mean())
        out["Deglint-k13-grow"].append(gray[s & ~m13g].mean())
        out["Median-ROI"].append(float(np.median(gray[s])))
        out["B2-k13-BG"].append(imgB2k[s].mean() - bg)
    return out, dict(m9=m9, m13=m13, B2=imgB2, B2k=imgB2k, inside=inside, ring=ring)


def fit_lod(stats, fit_labels, blank):
    x = np.log10([float(l) for l in fit_labels])
    y = np.array([stats[l][0] for l in fit_labels])
    m, b = np.polyfit(x, y, 1)
    r2 = 1 - np.sum((y - (m * x + b)) ** 2) / np.sum((y - y.mean()) ** 2)
    mu, sd = stats[blank]
    log_lod = (mu + 3 * sd - b) / m
    return m, b, r2, log_lod


if __name__ == "__main__":
    all_rows, lod_rows, vis = [], [], {}
    for name, cfg in IMAGES.items():
        gray = load_gray(os.path.join(IMG_DIR, cfg["file"]))
        cs = centers(gray, cfg["guess"], cfg["y"], cfg["half"])
        per = {}
        for lab, (cx, cy) in zip(cfg["labels"], cs):
            vals, extra = measure(gray, cx, cy, cfg["r"])
            per[lab] = (vals, extra, (cx, cy))
        vis[name] = (gray, per, cfg)
        print(f"\n══ {name}  centers {cs}")
        # 驗證:Raw 與 Excel 的平均值(不同人畫 ROI,只看趨勢是否一致)
        ex = [cfg["excel"][l][0] for l in cfg["labels"] if l in cfg["excel"]]
        mine = [np.mean(per[l][0]["Raw"]) for l in cfg["labels"] if l in cfg["excel"]]
        print(f"  Raw vs Excel 平均值:相關係數 r = {np.corrcoef(ex, mine)[0, 1]:.3f}")
        print("  " + " | ".join(f"{l}: {e:.1f}/{m_:.1f}" for l, e, m_ in zip([l for l in cfg['labels'] if l in cfg['excel']], ex, mine)))
        for meth in METHODS:
            stats = {l: (float(np.mean(per[l][0][meth])), float(np.std(per[l][0][meth], ddof=1))) for l in cfg["labels"]}
            m, b, r2, log_lod = fit_lod(stats, cfg["fit"], cfg["blank"])
            cv_mean = np.mean([100 * stats[l][1] / abs(stats[l][0]) for l in cfg["fit"]])
            lod_rows.append([name, meth, m, b, r2, stats[cfg["blank"]][0], stats[cfg["blank"]][1], cv_mean, log_lod, 10 ** log_lod])
            for l in cfg["labels"]:
                all_rows.append([name, meth, l] + [round(v, 4) for v in per[l][0][meth]] + [round(stats[l][0], 4), round(stats[l][1], 4)])
        # Excel 自己的數值用同一公式重算(對照用)
        estats = cfg["excel"]
        m, b, r2, log_lod = fit_lod(estats, cfg["fit"], cfg["blank"])
        lod_rows.append([name, "Excel(使用者)", m, b, r2, estats[cfg["blank"]][0], estats[cfg["blank"]][1],
                         np.mean([100 * estats[l][1] / estats[l][0] for l in cfg["fit"]]), log_lod, 10 ** log_lod])

    with open(os.path.join(HERE, f"results_replicates_{REP_MODE}.csv"), "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp); w.writerow(["image", "method", "sample", "rep1", "rep2", "rep3", "mean", "std"]); w.writerows(all_rows)
    with open(os.path.join(HERE, f"results_lod_{REP_MODE}.csv"), "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["image", "method", "slope", "intercept", "R2", "blank_mean", "blank_std", "fit_points_mean_CV%", "log10_LOD", "LOD_M"])
        for r in lod_rows:
            w.writerow([r[0], r[1]] + [f"{v:.6g}" for v in r[2:]])

    print("\n影像    方法            斜率     R²      blank μ±σ        平均CV%   LOD (M)")
    for r in lod_rows:
        print(f"{r[0]:7s} {r[1]:14s} {r[2]:7.3f}  {r[4]:.4f}  {r[5]:7.2f}±{r[6]:5.2f}   {r[7]:6.2f}   {r[9]:.2e}")

    import pickle
    with open(os.path.join(HERE, f"_vis_{REP_MODE}.pkl"), "wb") as fp:
        pickle.dump({k: (v[0], {l: (p[0], {kk: vv for kk, vv in p[1].items()}, p[2]) for l, p in v[1].items()}, v[2])
                     for k, v in vis.items()}, fp)
