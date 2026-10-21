# -*- coding: utf-8 -*-
"""
Auto ROI 管線逐階段診斷工具 / Step-by-step pipeline debugger
============================================================
把 auto_detect_rois() 每一個處理階段輸出成獨立圖檔 + 總覽拼圖，
並在終端機列印每階段的統計數字，方便觀察問題出在哪一步。

用法 / Usage:
    python auto_roi_debug.py <影像> --rows 2 --cols 12
    python auto_roi_debug.py <影像> --rows 1 --cols 6 --close-factor 0.15
    python auto_roi_debug.py <影像> --rows 2 --cols 12 --no-auto-close

相對於初版的四項修正（實測兩張樣本圖後發現）:
  ① 背景相減後「負值截為 0」
     否則 NORM_MINMAX 會把「與背景相同」映射到中間灰階，
     Otsu 就把整片背景判為前景（白色樣本圖實測 fg% 高達 68.8%）。
  ② 背景估計 sigma 改為相對「單格尺寸 cell」而非影像尺寸
     影像很寬時 sigma 會與樣本大小脫鉤。
  ③ 面積過濾基準改用「cell^2」而非「blob 面積中位數」
     灰塵數量若多於真樣本，中位數會落在灰塵區間，
     真樣本反而被當成「太大」剔除（綠圖實測 24 個只留 6 個）。
  ④ close_factor 自動掃描：挑 blob 數最接近 R×C 的值
     實測綠圖最佳 0.05、白圖最佳 0.15，無單一固定值可通吃。
"""

import os
import argparse
import numpy as np
import cv2


class Params:
    bg_sigma_cell    = 1.0
    pct_low          = 1.0
    pct_high         = 99.0
    pre_blur_ksize   = 5
    open_ksize       = 5
    close_factor     = 0.10
    close_iter       = 2
    area_lo_cell     = 0.02
    area_hi_cell     = 1.5
    kmeans_attempts  = 5
    auto_close       = True
    close_sweep      = (0.0, 0.03, 0.05, 0.08, 0.10, 0.13, 0.15, 0.18, 0.20)
    sigma_sweep      = (0.2, 0.3, 0.4, 0.5, 0.75, 1.0)


def to_bgr(img):
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img.copy()


def label_panel(img, text, color=(0, 255, 255)):
    img = to_bgr(img)
    h, w = img.shape[:2]
    bar = max(26, int(h * 0.12))
    canvas = np.zeros((h + bar, w, 3), np.uint8)
    canvas[bar:, :] = img
    fs = max(0.45, min(0.85, w / 1100.0))
    cv2.putText(canvas, text, (8, int(bar * 0.72)),
                cv2.FONT_HERSHEY_SIMPLEX, fs, color, 1, cv2.LINE_AA)
    return canvas


def stats_line(name, arr):
    a = arr.astype(np.float64)
    return (f"  {name:<20s} min={a.min():6.1f} max={a.max():6.1f} "
            f"mean={a.mean():7.2f} std={a.std():6.2f}")


def save(outdir, idx, name, img):
    cv2.imwrite(os.path.join(outdir, f"{idx:02d}_{name}.png"), to_bgr(img))


def auto_grid_positions(centroids, R, C, w, h, attempts=5):
    cx = np.array([c[0] for c in centroids], np.float32)
    cy = np.array([c[1] for c in centroids], np.float32)

    def cluster_1d(vals, k, span):
        vals = vals.reshape(-1, 1).astype(np.float32)
        if len(vals) >= k and k > 1:
            crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
            _, _, centers = cv2.kmeans(vals, k, None, crit, attempts,
                                       cv2.KMEANS_PP_CENTERS)
            return sorted(float(c) for c in centers.flatten())
        if k == 1:
            return [float(vals.mean())] if len(vals) else [span / 2.0]
        if len(vals):
            return list(np.linspace(float(vals.min()), float(vals.max()), k))
        return list(np.linspace(0, span, k))

    return cluster_1d(cx, C, w), cluster_1d(cy, R, h)


def flatten_and_otsu(sub, cell, sigma_cell, P):
    """去背景漸層 -> 負值截0 -> 百分位正規化 -> Otsu。回傳中間結果字典。"""
    sigma = cell * sigma_cell
    bg = cv2.GaussianBlur(sub, (0, 0), sigmaX=sigma)
    diff_signed = sub.astype(np.int16) - bg.astype(np.int16)
    neg_ratio = 100.0 * (diff_signed < 0).sum() / diff_signed.size
    d = np.clip(diff_signed, 0, None).astype(np.uint8)

    lo = np.percentile(d, P.pct_low)
    hi = np.percentile(d, P.pct_high)
    if hi <= lo:
        hi = lo + 1
    norm8 = (np.clip((d.astype(np.float32) - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
    k = P.pre_blur_ksize | 1
    blur = cv2.GaussianBlur(norm8, (k, k), 0)
    otsu_t, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return dict(sigma=sigma, bg=bg, d=d, neg_ratio=neg_ratio,
                lo=lo, hi=hi, norm8=norm8, otsu_t=otsu_t, bw=bw,
                fg_pct=100.0 * (bw > 0).sum() / bw.size)


def morph_and_components(bw, cell, close_factor, P):
    Hs, Ws = bw.shape[:2]
    ok = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (P.open_ksize | 1,) * 2)
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, ok, iterations=1)

    if close_factor > 0:
        cs = int(np.clip(cell * close_factor, 3, 35)) | 1
        ck = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cs, cs))
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, ck,
                                  iterations=P.close_iter)
    else:
        cs, closed = 0, opened

    ff = closed.copy()
    ffm = np.zeros((Hs + 2, Ws + 2), np.uint8)
    cv2.floodFill(ff, ffm, (0, 0), 255)
    holes = cv2.bitwise_not(ff)
    solid = closed | holes

    n, _, stats, cents = cv2.connectedComponentsWithStats(solid, connectivity=8)
    ca = cell ** 2
    a_lo, a_hi = P.area_lo_cell * ca, P.area_hi_cell * ca
    good, rejected = [], []
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        pt = (float(cents[i][0]), float(cents[i][1]))
        (good if a_lo <= a <= a_hi else rejected).append((pt, a))

    return dict(opened=opened, closed=closed, holes=holes, solid=solid,
                close_size=cs, n_blobs=n - 1, good=good, rejected=rejected,
                a_lo=a_lo, a_hi=a_hi)


def run_pipeline(img_path, R, C, outdir, P,
                 roi_shape='circle', roi_diameter=None, roi_w=None, roi_h=None,
                 tag=""):
    os.makedirs(outdir, exist_ok=True)
    panels = []
    print("=" * 76)
    print(f"Auto ROI 逐階段診斷 {tag} | grid = {R} x {C} = {R*C}")
    print("=" * 76)

    raw = cv2.imread(img_path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise FileNotFoundError(img_path)
    sub = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY) if raw.ndim == 3 else raw.copy()
    Hs, Ws = sub.shape[:2]
    cell = min(Ws / C, Hs / R)
    ca = cell ** 2

    print(f"\n[1] 輸入 / Input   {os.path.basename(img_path)}  {Ws}x{Hs}")
    print(stats_line("gray", sub))
    print(f"  單格估計 cell = {cell:.1f} px   cell^2 = {ca:.0f}")
    save(outdir, 0, "input", sub)
    panels.append(label_panel(sub, f"1. Input gray {Ws}x{Hs} (cell={cell:.0f}px)"))

    target = R * C

    # ── 自動掃描 (sigma_cell x close_factor) ──────────────────────────
    used_sigma_cell = P.bg_sigma_cell
    used_cf = P.close_factor
    if P.auto_close:
        print(f"\n[*] 自動參數掃描 / Auto sweep   (target blobs = {target})")
        print(f"  逐一嘗試 sigma_cell x close_factor, 取 blob 數最接近 target 者")
        print(f"  {'sigma':>6s} {'cf':>5s} {'kernel':>7s} {'fg%':>6s} "
              f"{'holes':>7s} {'kept':>5s} {'err':>4s}")
        best = None
        for sc in P.sigma_sweep:
            fo = flatten_and_otsu(sub, cell, sc, P)
            if fo["fg_pct"] > 45:            # 背景被誤判為前景, 直接跳過
                print(f"  {sc:6.2f} {'--':>5s} {'--':>7s} {fo['fg_pct']:5.1f}% "
                      f"{'--':>7s} {'--':>5s} {'skip':>4s}   (fg% 過高)")
                continue
            for cf in P.close_sweep:
                mc = morph_and_components(fo["bw"], cell, cf, P)
                kept = len(mc["good"])
                err = abs(kept - target)
                hp = int((mc["holes"] > 0).sum())
                mark = ""
                if best is None or err < best[0]:
                    best = (err, sc, cf, fo, mc)
                    mark = "  <- best"
                if err <= 2 or mark:
                    print(f"  {sc:6.2f} {cf:5.2f} {mc['close_size']:7d} "
                          f"{fo['fg_pct']:5.1f}% {hp:7d} {kept:5d} {err:4d}{mark}")
        if best is None:
            print("  [X] 所有參數組合皆失敗")
            return None
        _, used_sigma_cell, used_cf, fo, res = best
        print(f"  -> 選用 sigma_cell = {used_sigma_cell:.2f}, "
              f"close_factor = {used_cf:.2f}  "
              f"(kept {len(res['good'])}/{target})")
    else:
        fo = flatten_and_otsu(sub, cell, used_sigma_cell, P)
        res = morph_and_components(fo["bw"], cell, used_cf, P)

    sigma, bg, d = fo["sigma"], fo["bg"], fo["d"]
    neg_ratio = fo["neg_ratio"]
    lo, hi, norm8 = fo["lo"], fo["hi"], fo["norm8"]
    otsu_t, bw, fg_pct = fo["otsu_t"], fo["bw"], fo["fg_pct"]

    print(f"\n[2] 去背景漸層 / Background flattening (sigma = cell x "
          f"{used_sigma_cell} = {sigma:.1f})")
    print(stats_line("background", bg))
    print(f"  背景動態範圍 = {int(bg.max()-bg.min())} 灰階 (越大代表照明越不均)")
    print(f"  負差值像素 = {neg_ratio:.1f}%  -> 已截為 0")
    print(f"    * 若不截負值, NORM_MINMAX 會把「等於背景」映射到中間灰階,")
    print(f"      Otsu 就會把整片背景誤判為前景")
    print(stats_line("clipped diff", d))
    save(outdir, 1, "background", bg)
    save(outdir, 2, "flattened", d)
    panels.append(label_panel(bg, f"2a. Background estimate (sigma={sigma:.0f})"))
    panels.append(label_panel(d, f"2b. Flattened, negatives clipped ({neg_ratio:.0f}% were neg)"))

    print(f"\n[3] 正規化 + Otsu")
    print(f"  百分位 {P.pct_low}%={lo:.1f}  {P.pct_high}%={hi:.1f}")
    print(f"  Otsu 自動門檻 = {otsu_t:.0f}")
    print(f"  前景占比 = {fg_pct:.2f}%" +
          ("   OK 合理" if fg_pct < 45 else "   [!] 過高, 可能背景被誤判為前景"))
    save(outdir, 3, "normalized", norm8)
    save(outdir, 4, "otsu", bw)
    panels.append(label_panel(norm8, f"3a. Percentile-normalized [{lo:.0f},{hi:.0f}]"))
    panels.append(label_panel(bw, f"3b. Otsu binary t={otsu_t:.0f} fg={fg_pct:.1f}%"))

    print(f"\n[4] 形態學 / Morphology  (close_factor = {used_cf:.2f})")
    opened, closed = res["opened"], res["closed"]
    holes, solid = res["holes"], res["solid"]
    print(f"  open kernel = {P.open_ksize|1}   close kernel = {res['close_size']}"
          f"   iterations = {P.close_iter}")
    print(f"  前景占比: Otsu {fg_pct:.2f}% -> open "
          f"{100.0*(opened>0).sum()/opened.size:.2f}% -> close "
          f"{100.0*(closed>0).sum()/closed.size:.2f}%")
    save(outdir, 5, "opened", opened)
    save(outdir, 6, "closed", closed)
    panels.append(label_panel(opened, f"4a. OPEN {P.open_ksize|1}x{P.open_ksize|1} (despeckle)"))
    panels.append(label_panel(closed, f"4b. CLOSE {res['close_size']}x{res['close_size']} (cf={used_cf:.2f})"))

    hp = int((holes > 0).sum())
    print(f"\n[5] floodFill 填洞 / Hole filling")
    print(f"  被填補的封閉內部 = {hp} px ({100.0*hp/solid.size:.2f}%)")
    print("  -> 無封閉中空結構 (實心亮點樣本屬正常)" if hp == 0
          else "  -> 偵測到中空結構並填實 (中空方框靠這步變實心)")
    save(outdir, 7, "holes", holes)
    save(outdir, 8, "solid", solid)
    panels.append(label_panel(holes, f"5a. Enclosed holes = {hp} px"))
    panels.append(label_panel(solid, "5b. Solid = closed | holes"))

    good, rejected = res["good"], res["rejected"]
    print(f"\n[6] 連通元件 + 面積過濾 / Components")
    print(f"  blob 總數 = {res['n_blobs']}")
    print(f"  接受範圍 = [{res['a_lo']:.0f}, {res['a_hi']:.0f}]"
          f"  (= cell^2 x [{P.area_lo_cell}, {P.area_hi_cell}])")
    print(f"    * 用 cell^2 而非 blob 面積中位數: 灰塵若多於真樣本,")
    print(f"      中位數會落在灰塵區間導致真樣本全被剔除")
    print(f"  通過 = {len(good)}  剔除 = {len(rejected)}   (target {target})")
    if good:
        ga = sorted(a for _, a in good)
        print(f"  通過面積: {ga[:12]}{' ...' if len(ga) > 12 else ''}")
    if rejected:
        ra = sorted(a for _, a in rejected)
        print(f"  剔除面積: {ra[:12]}{' ...' if len(ra) > 12 else ''}")

    cc = to_bgr(solid.copy())
    cc[solid > 0] = (80, 80, 80)
    for pt, a in good:
        cv2.circle(cc, (int(pt[0]), int(pt[1])), 4, (0, 255, 0), -1)
    for pt, a in rejected:
        cv2.drawMarker(cc, (int(pt[0]), int(pt[1])), (0, 0, 255),
                       cv2.MARKER_TILTED_CROSS, 9, 2)
    save(outdir, 9, "components", cc)
    panels.append(label_panel(cc, f"6. {len(good)} kept (green) / {len(rejected)} rejected (red x)"))

    if not good:
        print("\n  [X] 無有效 blob, 管線中止")
        return None

    centroids = [pt for pt, _ in good]
    col_x, row_y = auto_grid_positions(centroids, R, C, Ws, Hs, P.kmeans_attempts)
    print(f"\n[7-8] k-means 格線分群")
    print(f"  col_x ({len(col_x)}) = {[f'{v:.0f}' for v in col_x]}")
    print(f"  row_y ({len(row_y)}) = {[f'{v:.0f}' for v in row_y]}")
    if len(col_x) > 1:
        g = np.diff(col_x)
        print(f"  行間距 = {[f'{v:.0f}' for v in g]}")
        if g.max() > 1.5 * np.median(g):
            print("    -> 偵測到明顯較大間距 (版面分區), k-means 已正確容納")

    gv = to_bgr(norm8.copy())
    for x in col_x:
        cv2.line(gv, (int(x), 0), (int(x), Hs), (255, 160, 0), 1)
    for y in row_y:
        cv2.line(gv, (0, int(y)), (Ws, int(y)), (255, 160, 0), 1)
    for pt in centroids:
        cv2.circle(gv, (int(pt[0]), int(pt[1])), 3, (0, 255, 0), -1)
    save(outdir, 10, "grid", gv)
    panels.append(label_panel(gv, "7. k-means grid (orange) + centroids (green)"))

    src = ""
    if roi_shape == 'circle':
        if roi_diameter:
            rad = roi_diameter // 2
            src = "使用者指定"
        else:
            mg = float(np.median([a for _, a in good]))
            rad = max(3, int(round((mg / np.pi) ** 0.5)))
            src = "依通過 blob 面積中位數推算"
    else:
        if not roi_w or not roi_h:
            mg = float(np.median([a for _, a in good]))
            roi_w = roi_h = max(6, int(round(mg ** 0.5)))

    new_rois = []
    for i in range(R):
        cy = row_y[i]
        for j in range(C):
            cx = col_x[j]
            if roi_shape == 'circle':
                new_rois.append(('circle',
                                 int(max(rad, min(Ws - rad, cx))),
                                 int(max(rad, min(Hs - rad, cy))), rad))
            else:
                rx1 = int(max(0, min(Ws - roi_w, cx - roi_w / 2)))
                ry1 = int(max(0, min(Hs - roi_h, cy - roi_h / 2)))
                new_rois.append(('rect', rx1, ry1, rx1 + roi_w, ry1 + roi_h))

    print(f"\n[9-10] 建立 ROI")
    if roi_shape == 'circle':
        print(f"  圓形  半徑 = {rad} px  直徑 = {rad*2} px  ({src})")
    else:
        print(f"  矩形  {roi_w} x {roi_h} px")
    print(f"  ROI 數 = {len(new_rois)} (= {R} x {C})  編號 row-major")

    fin = to_bgr(cv2.normalize(sub, None, 0, 255, cv2.NORM_MINMAX))
    for idx, r in enumerate(new_rois):
        if r[0] == 'circle':
            _, x, y, rr = r
            cv2.circle(fin, (x, y), rr, (255, 255, 255), 1)
            tp = (x - rr, y - rr - 3)
        else:
            _, a, b, c2, d2 = r
            cv2.rectangle(fin, (a, b), (c2, d2), (255, 255, 255), 1)
            tp = (a, b - 3)
        cv2.putText(fin, str(idx + 1), tp, cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (0, 255, 255), 1, cv2.LINE_AA)
    save(outdir, 11, "final_rois", fin)
    panels.append(label_panel(fin, f"8. Final {len(new_rois)} ROIs (contrast-stretched view)"))

    print(f"\n[OK] 覆蓋檢查 / Coverage (每個 ROI 內前景像素占比)")
    covs = []
    for r in new_rois:
        m = np.zeros((Hs, Ws), np.uint8)
        if r[0] == 'circle':
            cv2.circle(m, (r[1], r[2]), r[3], 1, -1)
        else:
            m[r[2]:r[4], r[1]:r[3]] = 1
        tot = int(m.sum())
        covs.append(100.0 * int(((solid > 0) & (m == 1)).sum()) / tot if tot else 0.0)
    for i in range(R):
        print(f"  Row {i+1}: " + " ".join(f"{v:5.1f}%" for v in covs[i*C:(i+1)*C]))
    weak = [i + 1 for i, v in enumerate(covs) if v < 20.0]
    print(f"  平均覆蓋率 = {np.mean(covs):.1f}%")
    print(f"  [!] 覆蓋率 <20% 的 ROI: {weak}  -> 樣本偏暗或需右鍵微調" if weak
          else "  OK 全部 ROI 覆蓋率 >= 20%, 格線對位良好")

    maxw = max(p.shape[1] for p in panels)
    stack = []
    for p in panels:
        if p.shape[1] < maxw:
            p = cv2.copyMakeBorder(p, 0, 0, 0, maxw - p.shape[1],
                                   cv2.BORDER_CONSTANT, value=(0, 0, 0))
        stack.append(p)
        stack.append(np.full((5, maxw, 3), 40, np.uint8))
    cv2.imwrite(os.path.join(outdir, "_overview.png"), np.vstack(stack))
    print(f"\n輸出 -> {outdir}/  (含 _overview.png 總覽拼圖)")
    print("=" * 76 + "\n")
    return new_rois


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--outdir", default="debug_out")
    ap.add_argument("--shape", choices=["circle", "rect"], default="circle")
    ap.add_argument("--diameter", type=int, default=None)
    ap.add_argument("--roi-w", type=int, default=None)
    ap.add_argument("--roi-h", type=int, default=None)
    ap.add_argument("--close-factor", type=float, default=Params.close_factor)
    ap.add_argument("--no-auto-close", action="store_true")
    ap.add_argument("--bg-sigma-cell", type=float, default=Params.bg_sigma_cell)
    ap.add_argument("--area-lo", type=float, default=Params.area_lo_cell)
    ap.add_argument("--area-hi", type=float, default=Params.area_hi_cell)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    P = Params()
    P.close_factor = a.close_factor
    P.auto_close = not a.no_auto_close
    P.bg_sigma_cell = a.bg_sigma_cell
    P.area_lo_cell = a.area_lo
    P.area_hi_cell = a.area_hi

    run_pipeline(a.image, a.rows, a.cols, a.outdir, P,
                 roi_shape=a.shape, roi_diameter=a.diameter,
                 roi_w=a.roi_w, roi_h=a.roi_h, tag=a.tag)


if __name__ == "__main__":
    main()