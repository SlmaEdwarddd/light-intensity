# -*- coding: utf-8 -*-
"""
測試 20261029_1.png / 20261029_2.png:
  [ROI]  每個樣本放圓形 ROI,比較 修整 A(加權平均)/ B(鄰近顏色)/ B2(B 再處理一次,連光暈一起補)
  [整張] 整張影像有效區當成一個大 ROI 做 B2(K 用 WHOLE_K;ROI 預設 K=4 用在整張會抹掉樣本輪廓)

樣本中心:中值濾波去亮點 + 高斯模糊後,在每個樣本附近取亮度質心(自動放置 ROI 在這兩張圖上不可靠)。
用法:python test_more_images.py
輸出(每張圖 <name> = 20261029_1 / 20261029_2):
    <name>_roi_compare.png       原圖 / 標紅 / A / B / B2(對比放大)
    <name>_whole_B2_K12.png      整張:原圖 / 標紅 / B2(對比放大)
    <name>_whole_B2_only_K12.png 整張 B2 結果(未調對比)
"""
import os
import numpy as np
import cv2
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261029.py")
WHOLE_K = 12.0
for _n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _n, lambda *a, **k: None)

# 每張圖:樣本中心的初估(依影像目測)、找質心的視窗半寬、ROI 半徑
IMAGES = {
    "20261029_1": dict(guess=[134, 263, 386, 513, 638, 764], y=(40, 150), half=50, radius=30),
    "20261029_2": dict(guess=[80, 185, 298, 405, 510, 620, 728], y=(20, 145), half=45, radius=30),
}


def load(image):
    code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
    g = {"__name__": "__main__", "__file__": PROG}
    exec(compile(code, PROG, "exec"), g)
    g["CAMERA_TYPE"] = "IMAGE"
    assert g["load_image_file"](image)
    g["_publish_frame"](g["source_image_gray"])
    return g


def centers(gray_img, guess, yr, half):
    """去亮點(median 9)+ 模糊後,在每個初估位置附近取亮度質心(扣掉視窗內 40 百分位當背景)。"""
    m = cv2.GaussianBlur(cv2.medianBlur(gray_img, 9).astype(np.float32), (0, 0), 6)
    out = []
    for gx in guess:
        x0 = max(0, gx - half)
        win = m[yr[0]:yr[1], x0:gx + half]
        w = np.clip(win - np.percentile(win, 40), 0, None)
        ys, xs = np.mgrid[0:win.shape[0], 0:win.shape[1]]
        out.append((int(round((xs * w).sum() / w.sum() + x0)), int(round((ys * w).sum() / w.sum() + yr[0]))))
    return out


def titled(p, t):
    bar = np.full((26, p.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, t, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return np.vstack([bar, p])


def stack(ps, ts, vertical):
    ps = [titled(p, t) for p, t in zip(ps, ts)]
    if vertical:
        gap = np.full((8, ps[0].shape[1], 3), 60, np.uint8)
        out = ps[0]
        for p in ps[1:]:
            out = np.vstack([out, gap, p])
    else:
        gap = np.full((ps[0].shape[0], 8, 3), 60, np.uint8)
        out = ps[0]
        for p in ps[1:]:
            out = np.hstack([out, gap, p])
    return out


for name, cfg in IMAGES.items():
    path = os.path.join(HERE, name + ".png")
    g = load(path)
    gray = g["current_frame"].copy()
    px, py, W, H = g["img_pad_x"], g["img_pad_y"], g["img_disp_w"], g["img_disp_h"]
    sub = gray[py:py + H, px:px + W]
    cs = centers(sub, cfg["guess"], cfg["y"], cfg["half"])
    rois = [("circle", cx + px, cy + py, cfg["radius"]) for cx, cy in cs]
    g["_set_rois"](rois)
    methods = [m for m, _ in g["FILL_METHODS"]]

    print(f"\n══ {name}({W}x{H},{len(rois)} 個圓形 ROI 半徑 {cfg['radius']},K={g['DEGLINT_K']:.0f})")
    print("  樣本中心:", cs)
    print("  ROI | 標紅   | 原始    分數(紅點不計入) |  A      B      B2   | B2 多改(光暈)")
    lo = np.percentile(sub, 1); hi = np.percentile(sub, 99.5)
    st = lambda im: cv2.cvtColor(np.clip((im.astype(np.float32) - lo) * 255 / max(1, hi - lo), 0, 255).astype(np.uint8),
                                 cv2.COLOR_GRAY2BGR)
    full = {m: g["clean_image"](gray, m) for m in methods}
    marked = st(sub)
    for i, r in enumerate(rois):
        patch, cmask, rej, pct, mb, ma = g["deglint_roi_stats"](gray, r)
        ins = cmask == 1
        c = {m: g["fill_glint"](patch, rej, m, cmask) for m in methods}
        extra = int(((c["inpaint2"] != patch) & ~rej).sum())
        print(f"  S{i+1:<2} | {pct:5.1f}% | {mb:6.2f}  {ma:6.2f}             | {c['avg'][ins].mean():6.2f} "
              f"{c['inpaint'][ins].mean():6.2f} {c['inpaint2'][ins].mean():6.2f} | {extra:4d}")
        y1, y2, x1, x2 = g["_roi_slice"](gray.shape, r)
        marked[y1 - py:y2 - py, x1 - px:x2 - px][rej] = (0, 0, 255)
        changed = full["inpaint2"] != sub                             # 只修 ROI:ROI 外不可改
    inside = np.zeros(sub.shape, bool)
    for r in rois:
        cv2.circle(inside.view(np.uint8), (r[1] - px, r[2] - py), r[3], 1, -1)
    assert not ((full["inpaint2"] != sub) & ~inside).any(), "ROI 外不應被修改"

    def boxed(im):
        im = im.copy()
        for r in rois:
            cv2.circle(im, (r[1] - px, r[2] - py), r[3] + 1, (0, 215, 255), 1)
        return cv2.resize(im, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(os.path.join(HERE, f"{name}_roi_compare.png"),
                stack([boxed(st(sub)), boxed(marked)] + [boxed(st(full[m])) for m in methods],
                      ["Original", "Marked (red = excluded)", "A: weighted avg", "B: inpaint", "B2: inpaint x2 (+halo)"],
                      vertical=True))

    # 整張 B2
    g["DEGLINT_K"] = WHOLE_K
    whole = ("rect", px, py, px + W, py + H)
    patch, _, rej, pct, mb, ma = g["deglint_roi_stats"](gray, whole)
    b2 = g["fill_glint"](patch, rej, "inpaint2")
    print(f"  [整張 B2, K={WHOLE_K:g}] 標紅 {pct:.2f}%,B2 修改 {100 * (b2 != patch).mean():.1f}%,"
          f"平均 {patch.mean():.2f} → {b2.mean():.2f},最大值 {patch.max()} → {b2.max()}")
    mk = st(patch); mk[rej] = (0, 0, 255)
    cv2.imwrite(os.path.join(HERE, f"{name}_whole_B2_only_K{WHOLE_K:g}.png"), b2)
    cv2.imwrite(os.path.join(HERE, f"{name}_whole_B2_K{WHOLE_K:g}.png"),
                stack([cv2.resize(x, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_NEAREST) for x in (st(patch), mk, st(b2))],
                      ["Original", f"Marked {pct:.1f}% (K={WHOLE_K:g})", "B2 whole image"], vertical=True))
    g["root"].destroy()

print("\n已輸出 *_roi_compare.png / *_whole_B2_K12.png / *_whole_B2_only_K12.png")
