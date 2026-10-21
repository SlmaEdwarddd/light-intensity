# -*- coding: utf-8 -*-
"""
模式 B 逐步教學檢視器 / Mode B Step-by-Step Viewer
==================================================
用方向鍵一步一步瀏覽 NCC 模板匹配管線的每個處理階段。
每一步顯示「處理前 -> 處理後」的影像變化，
並在終端機印出該步驟的程式碼、參數與原理說明。

操作 / Controls
---------------
    ->  或  D  或  空白鍵    下一步
    <-  或  A                上一步
    S                       儲存目前這一步的圖
    Q  或  ESC              離開

用法 / Usage
------------
    python modeB_stepviewer.py <影像路徑> --rows 1 --cols 6
    python modeB_stepviewer.py img.jpg --rows 1 --cols 6 --save-all

無 GUI 環境（遠端伺服器）請加 --save-all，直接把每步輸出成圖檔。
"""

import os
import argparse
import numpy as np
import cv2


MAXW, MAXH = 1000, 620


# ══════════════════════════════════════════════════════════════════
# 顯示工具
# ══════════════════════════════════════════════════════════════════
def to_bgr(img):
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img.copy()


def fit(img, maxw=MAXW, maxh=MAXH):
    h, w = img.shape[:2]
    r = min(maxw / w, maxh / h, 1.0)
    if r < 1.0:
        img = cv2.resize(img, (int(w * r), int(h * r)), interpolation=cv2.INTER_AREA)
    return img


def stretch(gray):
    """對比拉伸，讓暗圖在螢幕上看得見（僅顯示用，不影響運算）"""
    return cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def add_caption(img, lines, color=(0, 255, 255)):
    img = to_bgr(img)
    h, w = img.shape[:2]
    lh = 24
    bar = lh * len(lines) + 10
    canvas = np.zeros((h + bar, w, 3), np.uint8)
    canvas[bar:, :] = img
    for i, t in enumerate(lines):
        c = color if i == 0 else (200, 200, 200)
        fs = 0.62 if i == 0 else 0.5
        cv2.putText(canvas, t, (10, 22 + i * lh),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, c, 1, cv2.LINE_AA)
    return canvas


def side_by_side(left, right, ltitle, rtitle):
    l = add_caption(fit(to_bgr(left), MAXW // 2 - 10, MAXH), [ltitle], (150, 150, 150))
    r = add_caption(fit(to_bgr(right), MAXW // 2 - 10, MAXH), [rtitle], (0, 255, 255))
    h = max(l.shape[0], r.shape[0])

    def pad(a):
        if a.shape[0] < h:
            a = cv2.copyMakeBorder(a, 0, h - a.shape[0], 0, 0,
                                   cv2.BORDER_CONSTANT, value=(0, 0, 0))
        return a

    return np.hstack([pad(l), np.full((h, 4, 3), 60, np.uint8), pad(r)])


def banner(text):
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def code_block(code, why):
    print("\n[程式碼]")
    for ln in code.strip("\n").split("\n"):
        print("    " + ln)
    print("\n[原理]")
    for ln in why.strip("\n").split("\n"):
        print("    " + ln)


def local_peaks(sig, height, distance, topk=None):
    """簡易 find_peaks + NMS，依分數排序"""
    idx = [i for i in range(1, len(sig) - 1)
           if sig[i] >= sig[i - 1] and sig[i] > sig[i + 1] and sig[i] >= height]
    idx.sort(key=lambda i: -sig[i])
    kept = []
    for i in idx:
        if all(abs(i - j) >= distance for j in kept):
            kept.append(i)
    if topk is None:
        return kept, []
    return sorted(kept[:topk]), sorted(kept[topk:])


# ══════════════════════════════════════════════════════════════════
# 建立所有步驟
# ══════════════════════════════════════════════════════════════════
def build_steps(img_path, R, C):
    steps = []

    # ── STEP 0：輸入 ───────────────────────────────────────────────
    im = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if im is None:
        raise FileNotFoundError(img_path)
    H, W = im.shape

    steps.append(dict(
        title="STEP 0 / 輸入影像 Input",
        image=add_caption(stretch(im), [
            f"STEP 0  Input  {W}x{H}",
            f"mean={im.mean():.1f}  min={im.min()}  max={im.max()}",
            "(contrast-stretched for display; original is darker)"]),
        code="im = cv2.imread(path, cv2.IMREAD_GRAYSCALE)",
        why=("這類影像的三個困難點:\n"
             "  1. 各格亮度差異大 -> 單一門檻無法兼顧亮暗\n"
             "  2. 外圍有明亮的干擾結構 -> 會被誤認為樣本\n"
             "  3. 滿版灰塵斑點 -> 會產生大量假 blob"),
        log=[f"影像尺寸 = {W} x {H}",
             f"平均灰階 = {im.mean():.2f}   最大 = {im.max()}"]))

    # ── STEP 1：Sobel X ───────────────────────────────────────────
    gx = cv2.Sobel(im, cv2.CV_32F, 1, 0, ksize=3)
    gx_vis = stretch(np.abs(gx))
    steps.append(dict(
        title="STEP 1 / Sobel X  水平方向梯度",
        image=side_by_side(stretch(im), gx_vis,
                           "before: original", "after: |gx|  vertical edges"),
        code="gx = cv2.Sobel(im, cv2.CV_32F, 1, 0, ksize=3)",
        why=("(1, 0) = 對 x 方向取一次導數, 偵測「左右亮度差」\n\n"
             "卷積核:   -1   0  +1\n"
             "          -2   0  +2      <- 左右兩側相減\n"
             "          -1   0  +1\n\n"
             "因此「垂直的邊」(方框左右兩邊) 被強烈響應,\n"
             "水平的邊幾乎沒有反應。"),
        log=[f"|gx| 範圍 = {np.abs(gx).min():.1f} ~ {np.abs(gx).max():.1f}",
             "觀察: 方框的左右直邊變亮, 上下橫邊消失"]))

    # ── STEP 2：Sobel Y ───────────────────────────────────────────
    gy = cv2.Sobel(im, cv2.CV_32F, 0, 1, ksize=3)
    gy_vis = stretch(np.abs(gy))
    steps.append(dict(
        title="STEP 2 / Sobel Y  垂直方向梯度",
        image=side_by_side(gx_vis, gy_vis,
                           "|gx|  vertical edges", "|gy|  horizontal edges"),
        code="gy = cv2.Sobel(im, cv2.CV_32F, 0, 1, ksize=3)",
        why=("(0, 1) = 對 y 方向取一次導數, 偵測「上下亮度差」\n\n"
             "卷積核:   -1  -2  -1\n"
             "           0   0   0      <- 上下兩側相減\n"
             "          +1  +2  +1\n\n"
             "與 gx 互補: 這次是「水平的邊」(方框上下兩邊) 被響應。"),
        log=[f"|gy| 範圍 = {np.abs(gy).min():.1f} ~ {np.abs(gy).max():.1f}",
             "觀察: 與上一步剛好相反, 橫邊亮、直邊暗"]))

    # ── STEP 3：合成梯度幅值 ──────────────────────────────────────
    mag_f = cv2.magnitude(gx, gy)
    mag = cv2.normalize(mag_f, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    steps.append(dict(
        title="STEP 3 / 合成梯度幅值 magnitude",
        image=side_by_side(stretch(im), mag,
                           "before: original (absolute brightness)",
                           "after: gradient magnitude (brightness CHANGE)"),
        code=("mag = cv2.magnitude(gx, gy)        # sqrt(gx^2 + gy^2)\n"
              "mag = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX)"),
        why=("用畢氏定理把兩個方向合成單一「邊緣強度」,\n"
             "四個邊和角落都能同時被表示。\n\n"
             "★ 這是整個方法的轉捩點:\n"
             "  原圖比的是「絕對亮度」  -> 暗樣本輸在起跑點\n"
             "  梯度圖比的是「亮度落差」-> 暗樣本的邊緣一樣清楚\n\n"
             "請比對左右兩圖中最暗的那幾格: 原圖幾乎看不見,\n"
             "梯度圖上輪廓與最亮的那格同樣分明。"),
        log=["問題已從「絕對亮度」轉換成「邊緣結構」",
             "樣本內部的填色消失, 只剩輪廓線"]))

    # ── STEP 4：合成模板 ──────────────────────────────────────────
    est = min(W / C, H / R)
    cands = sorted({int(est * f) for f in (0.55, 0.65, 0.75, 0.85, 0.95)
                    if 12 <= int(est * f) < min(H, W) * 0.9})
    magf = mag.astype(np.float32)
    scores, best = [], None
    for s in cands:
        t_ = max(3, int(s * 0.04))
        t = np.zeros((s, s), np.float32)
        cv2.rectangle(t, (t_, t_), (s - t_, s - t_), 1.0, t_)
        r = cv2.matchTemplate(magf, t * 255.0, cv2.TM_CCOEFF_NORMED)
        scores.append((s, float(r.max())))
        if best is None or r.max() > best[0]:
            best = (r.max(), s, r, t)
    _, sz, res, tpl = best
    th = max(3, int(sz * 0.04))

    tpl_big = cv2.resize((tpl * 255).astype(np.uint8), (260, 260),
                         interpolation=cv2.INTER_NEAREST)
    tpl_big = cv2.copyMakeBorder(tpl_big, 20, 20, 20, 20,
                                 cv2.BORDER_CONSTANT, value=0)
    steps.append(dict(
        title="STEP 4 / 合成方框模板 Synthetic template",
        image=add_caption(tpl_big, [
            f"STEP 4  Template   sz={sz}   th={th}",
            "HOLLOW square: interior stays black (not filled)",
            "because only EDGES are bright in the gradient map"]),
        code=(f"est = min(W/C, H/R)             # = {est:.1f}  估計格子大小\n"
              f"sz  = {sz}                        # 候選中 NCC 最高者\n"
              f"th  = max(3, int(sz * 0.04))    # = {th}  邊框粗細\n"
              "tpl = np.zeros((sz, sz), np.float32)\n"
              "cv2.rectangle(tpl, (th, th), (sz-th, sz-th), 1.0, th)"),
        why=("三個變數的意義:\n"
             "  sz  = 模板邊長。由 R/C 反推格子大小後在附近搜尋\n"
             "  th  = 邊框粗細 (尺寸的 4%)。max(3,..) 防止太細畫不出來\n"
             "  tpl = sz x sz 的畫布。先全 0 (黑), 再在上面畫邊框\n\n"
             "cv2.rectangle 的參數:\n"
             f"  (th, th)         左上角 = ({th}, {th})\n"
             f"  (sz-th, sz-th)   右下角 = ({sz-th}, {sz-th})\n"
             "  1.0              線的顏色值 (0~1 浮點)\n"
             f"  th               線寬 = {th}px  <- 不是填滿, 是畫邊框線\n\n"
             "★ 為何要空心: 模板要跟「梯度圖」比對, 而梯度圖上\n"
             "  方框內部是平坦的(暗), 只有邊緣是亮的。\n"
             "  模板要長得像它要匹配的目標圖, 而不是像原圖。\n\n"
             "★ 模板是程式合成的, 不需使用者先框一個範例樣本。"),
        log=[f"估計格子尺寸 est = {est:.1f}"] +
            [f"  size={s:4d}   max NCC = {v:.3f}" +
             ("   <- 選用" if s == sz else "") for s, v in scores]))

    # ── STEP 5：NCC 響應圖 ────────────────────────────────────────
    res_vis = cv2.applyColorMap(
        cv2.normalize(res, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8),
        cv2.COLORMAP_JET)
    steps.append(dict(
        title="STEP 5 / NCC 匹配響應圖",
        image=side_by_side(mag, res_vis,
                           "before: gradient map", "after: NCC response (red = high)"),
        code="res = cv2.matchTemplate(mag, tpl * 255.0, cv2.TM_CCOEFF_NORMED)",
        why=("模板在梯度圖上逐點滑動, 每個位置算一次相關係數。\n\n"
             "TM_CCOEFF_NORMED 的分母會除以各視窗自己的標準差:\n"
             "  亮方框: 分子大, 但分母(標準差)也大 -> 比值適中\n"
             "  暗方框: 分子小, 但分母(標準差)也小 -> 比值同樣適中\n"
             "★ 亮度不再是判準, 形狀才是。\n\n"
             "圖中可見一條明顯的紅色水平帶, 那正是樣本所在的列。\n"
             "外圍干擾結構是「長條線」而非「方框」, 分數偏低。"),
        log=[f"響應圖尺寸 = {res.shape[1]} x {res.shape[0]}",
             f"最高分 = {res.max():.3f}    最低分 = {res.min():.3f}"]))

    # ── STEP 6：列投影 ────────────────────────────────────────────
    rowmax = res.max(axis=1)
    if R == 1:
        bands = [int(np.argmax(rowmax))]
    else:
        kept, _ = local_peaks(rowmax, rowmax.max() * 0.4,
                              max(5, int(res.shape[0] / (R * 2))), topk=R)
        bands = kept if kept else [int(np.argmax(rowmax))]

    prof = np.zeros((260, res.shape[0], 3), np.uint8)
    rn = (rowmax - rowmax.min()) / max(1e-6, rowmax.max() - rowmax.min())
    for i, v in enumerate(rn):
        cv2.line(prof, (i, 259), (i, int(259 - v * 250)), (0, 200, 255), 1)
    for b in bands:
        cv2.line(prof, (b, 0), (b, 259), (0, 0, 255), 2)
    prof = cv2.rotate(prof, cv2.ROTATE_90_CLOCKWISE)

    steps.append(dict(
        title="STEP 6 / 列投影定位樣本帶",
        image=side_by_side(res_vis, prof,
                           "NCC response map", "row-max profile (red = chosen band)"),
        code=("rowmax = res.max(axis=1)       # 每一列取「最大」分數\n"
              "band   = int(np.argmax(rowmax))"),
        why=("取每列的「最大」值而非平均: 一列中只要有一個樣本,\n"
             "該列就該被選中; 用平均會被大片背景稀釋掉。\n\n"
             "★ 這一步同時達成兩件事:\n"
             "  1. 定位樣本所在的 y 位置\n"
             "  2. 一舉排除外圍干擾結構 (它們形不成強峰)\n\n"
             f"搜尋範圍從 {res.shape[0]} 列縮小到一條窄帶。"),
        log=[f"band y = {b}    score = {rowmax[b]:.3f}" for b in bands]))

    # ── STEP 7：帶內取列峰 ────────────────────────────────────────
    half = max(5, int(sz * 0.15))
    dist = max(3, int(sz * 0.6))
    all_cols, all_scores, rejected = [], [], []
    for by in bands:
        y0, y1 = max(0, by - half), min(res.shape[0], by + half + 1)
        colmax = res[y0:y1, :].max(axis=0)
        chosen, drop = local_peaks(colmax, max(0.10, colmax.max() * 0.35),
                                   dist, topk=C)
        all_cols.append(chosen)
        all_scores.append([float(colmax[x]) for x in chosen])
        rejected.append([(x, float(colmax[x])) for x in drop])

    peak_vis = to_bgr(stretch(im))
    for bi, by in enumerate(bands):
        for k, x in enumerate(all_cols[bi]):
            cv2.rectangle(peak_vis, (x, by), (x + sz, by + sz), (0, 255, 0), 2)
            cv2.putText(peak_vis, f"{all_scores[bi][k]:.2f}", (x + 3, by - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
        for x, s in rejected[bi]:
            cv2.rectangle(peak_vis, (x, by), (x + sz, by + sz), (0, 0, 255), 2)
            cv2.putText(peak_vis, f"{s:.2f} X", (x + 3, by - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

    lg = []
    for bi in range(len(bands)):
        lg.append(f"band {bi+1}: cols   = {all_cols[bi]}")
        lg.append(f"          scores = {[round(v, 3) for v in all_scores[bi]]}")
        if len(all_cols[bi]) > 1:
            lg.append(f"          gaps   = {np.diff(all_cols[bi]).tolist()}")
        if rejected[bi]:
            lg.append(f"          剔除假峰 = {[(x, round(s, 3)) for x, s in rejected[bi]]}")

    steps.append(dict(
        title="STEP 7 / 帶內取列峰 + 假峰排除",
        image=add_caption(peak_vis, [
            f"STEP 7   GREEN = kept (top {C} by score)    RED = rejected false peak",
            "number above each box = NCC score"]),
        code=("colmax = res[y0:y1, :].max(axis=0)\n"
              "peaks  = find_peaks(colmax, height=thr,\n"
              f"                    distance={dist})   # NMS = 模板寬 x 0.6\n"
              "peaks.sort(key=lambda x: -colmax[x])\n"
              f"chosen = sorted(peaks[:{C}])            # 取分數前 C 名"),
        why=("distance 參數是非極大值抑制 (NMS): 兩峰至少相距\n"
             "60% 模板寬, 避免同一個樣本產生多個相鄰峰。\n\n"
             "★ 假峰為何能自動被排除:\n"
             "  「完整方框輪廓」這個形狀在影像中相當獨特,\n"
             "  真樣本與假峰的分數之間有明顯落差,\n"
             "  依分數排序取前 C 名即可乾淨分離。"),
        log=lg))

    # ── STEP 8：等距擬合 ──────────────────────────────────────────
    fitted, fitlog = [], []
    for bi, by in enumerate(bands):
        xs = np.array(all_cols[bi], float)
        if len(xs) >= 2 and C > 2:
            i = np.arange(len(xs))
            A = np.vstack([i, np.ones_like(i)]).T
            pitch, x0 = np.linalg.lstsq(A, xs, rcond=None)[0]
            fx = [int(round(x0 + pitch * k)) for k in range(len(xs))]
            fitlog += [f"band {bi+1}: pitch = {pitch:.1f}px    x0 = {x0:.1f}",
                       f"   原始 = {[int(v) for v in xs]}",
                       f"   擬合 = {fx}",
                       f"   位移 = {[int(a - b) for a, b in zip(fx, xs)]}"]
        else:
            fx = [int(v) for v in xs]
        fitted.append(fx)

    fitvis = to_bgr(stretch(im))
    for bi, by in enumerate(bands):
        for x in all_cols[bi]:
            cv2.rectangle(fitvis, (x, by), (x + sz, by + sz), (0, 0, 255), 1)
        for x in fitted[bi]:
            cv2.rectangle(fitvis, (x, by), (x + sz, by + sz), (0, 255, 0), 2)

    steps.append(dict(
        title="STEP 8 / 等距擬合修正",
        image=add_caption(fitvis, [
            "STEP 8   RED thin = raw detection    GREEN thick = after pitch fit",
            "uses the prior that grid spacing must be uniform"]),
        code=("i = np.arange(len(xs))\n"
              "A = np.vstack([i, np.ones_like(i)]).T\n"
              "pitch, x0 = np.linalg.lstsq(A, xs, rcond=None)[0]\n"
              "fitted = [x0 + pitch * k for k in range(len(xs))]"),
        why=("最小平方法擬合直線, 把「第 k 個樣本的 x 座標」建模為\n"
             "      x_k = x0 + k * pitch\n"
             "解出起始位置 x0 與間距 pitch, 再用擬合值取代原始偵測值。\n\n"
             "★ 注意: 這一步假設同一列的樣本「等距排列」。\n"
             "  若版面中間有分區留空 (例如 6格 + 空隙 + 6格),\n"
             "  擬合會被拉偏 -> 那種版面請改用模式 A。"),
        log=fitlog if fitlog else ["樣本數不足, 略過擬合"]))

    # ── STEP 9：最終 ROI ─────────────────────────────────────────
    fin = to_bgr(stretch(im))
    n, means = 0, []
    for bi, by in enumerate(bands):
        for x in fitted[bi]:
            n += 1
            cv2.rectangle(fin, (x, by), (x + sz, by + sz), (0, 255, 0), 2)
            cv2.putText(fin, str(n), (x + 4, by - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
            p = im[max(0, by):min(H, by + sz), max(0, x):min(W, x + sz)]
            means.append(p.mean() if p.size else 0)

    ratio = (max(means) / min(means)) if means and min(means) > 0 else 0
    steps.append(dict(
        title="STEP 9 / 最終 ROI 結果",
        image=add_caption(fin, [
            f"STEP 9   Final: {n} ROIs    size = {sz}x{sz}",
            f"brightest/darkest mean-gray ratio = {ratio:.1f}x"]),
        code=("rois.append(('rect', x, y, x + sz, y + sz))\n"
              "# 與手動框選同格式 -> 右鍵拖曳即可微調"),
        why=("產生的 ROI 與手動框選格式完全相同, 因此下游\n"
             "(量測 / 繪圖 / CSV / 右鍵微調) 完全不需修改。\n\n"
             f"★ 各格平均灰階相差 {ratio:.1f} 倍。在這個比值下,\n"
             "  任何單一全域門檻都無法同時保住最亮與最暗的格子,\n"
             "  而 NCC 完全不受影響。"),
        log=["各 ROI 平均灰階:",
             "   " + "  ".join(f"#{k+1}={v:.0f}" for k, v in enumerate(means)),
             f"最亮/最暗比 = {ratio:.1f}x"]))

    return steps


# ══════════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════════
def show_step(i, steps):
    s = steps[i]
    banner(f"[{i+1}/{len(steps)}]  {s['title']}")
    code_block(s["code"], s["why"])
    print("\n[數值]")
    for ln in s["log"]:
        print("    " + ln)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--save-all", action="store_true",
                    help="不開視窗, 直接把每步存成圖檔")
    ap.add_argument("--outdir", default="stepviewer_out")
    args = ap.parse_args()

    steps = build_steps(args.image, args.rows, args.cols)

    if args.save_all:
        os.makedirs(args.outdir, exist_ok=True)
        for i, s in enumerate(steps):
            cv2.imwrite(os.path.join(args.outdir, f"step{i}_{s['title'].split('/')[0].strip().replace(' ','')}.png"),
                        s["image"])
            show_step(i, steps)
        print(f"\n全部 {len(steps)} 步已存到 {args.outdir}/")
        return

    print("\n操作:  -> / D / 空白 = 下一步     <- / A = 上一步     "
          "S = 存圖     Q = 離開\n")
    win = "Mode B Step Viewer"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    i, last = 0, -1
    while True:
        if i != last:
            show_step(i, steps)
            print("\n(在視窗中按 -> 繼續)")
            cv2.imshow(win, fit(steps[i]["image"]))
            last = i

        k = cv2.waitKey(30) & 0xFF
        if k in (ord('q'), 27):
            break
        if k in (ord('d'), ord(' '), 83):          # 83 = Right arrow
            i = min(i + 1, len(steps) - 1)
        elif k in (ord('a'), 81):                  # 81 = Left arrow
            i = max(i - 1, 0)
        elif k == ord('s'):
            os.makedirs(args.outdir, exist_ok=True)
            p = os.path.join(args.outdir, f"step{i}.png")
            cv2.imwrite(p, steps[i]["image"])
            print(f"    已儲存 -> {p}")

        try:
            if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                break
        except cv2.error:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()