# -*- coding: utf-8 -*-
"""
20261029 測試:去反光預覽加入「修整後」影像,三種補償方式並排比對(只修 ROI)
  修整 A :加權平均  —— 紅點用周圍保留像素的高斯加權平均填補(較平滑)
  修整 B :鄰近顏色  —— Telea inpainting,從缺口邊緣依附近顏色與走向往內延伸(較自然)
  修整 B2:B 再處理一次 —— 連灰塵周圍被映亮的光暈(FILL_GROW_PX)一起補,去掉 B 留下的淡點

用法(在 light_intensity conda 環境):
    python test_20261029.py

[1] 人造灰塵:三種方式都應補回平坦值
[2] 截圖影像 screenshot_original_panel.png(使用者截圖中「原圖」那一格,已縮小,僅供示意)
[3] 使用者影像 IMG_0779.jpg + ROI_layouts/ROI_fixed.json 的 12 個 ROI,重點看 Sample 4:
    「同樣設定再做一次 B」為什麼沒變化,以及 B2 的效果
輸出:
    cleaned_compare.png / cleaned_zoom.png   截圖影像:原圖 / 標紅 / A / B / B2
    img0779_compare.png                      IMG_0779 的 12 個 ROI:原圖 / 標紅 / A / B / B2
    s4_compare.png                           Sample 4 放大:原圖 / 標紅 / A / B / B 再做一次(同設定)/ B2
    cleaned_avg.png / cleaned_inpaint.png / cleaned_inpaint2.png   程式「儲存修整後影像」的輸出
"""
import os, json, time, threading, collections
import numpy as np
import cv2
from tkinter import messagebox, filedialog

HERE  = os.path.dirname(os.path.abspath(__file__))
PROG  = os.path.join(HERE, "20261029.py")
SHOT  = os.path.join(HERE, "screenshot_original_panel.png")
USER  = os.path.join(HERE, "IMG_0779.jpg")
USER_ROIS = os.path.join(HERE, "ROI_layouts", "ROI_fixed.json")
COLS, ROWS, SIZE = (118, 157), (72, 97, 122, 147, 372, 398), 18     # 截圖影像:2 欄 x 6 列

MSGS, DLG = [], collections.deque()
messagebox.askokcancel = lambda *a, **k: True
for _n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _n, lambda *a, **k: MSGS.append(a))
filedialog.asksaveasfilename = lambda **k: DLG.popleft()


def load(image):
    code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
    g = {"__name__": "__main__", "__file__": PROG}
    exec(compile(code, PROG, "exec"), g)
    g["CAMERA_TYPE"] = "IMAGE"
    assert g["load_image_file"](image)
    g["setup_ui_for_image_mode"]()
    g["_publish_frame"](g["source_image_gray"])
    return g


def titled(p, t):
    bar = np.full((26, p.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, t, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return np.vstack([bar, p])


def side_by_side(ps, ts):
    ps = [titled(p, t) for p, t in zip(ps, ts)]
    gap = np.full((ps[0].shape[0], 8, 3), 60, np.uint8)
    out = ps[0]
    for p in ps[1:]:
        out = np.hstack([out, gap, p])
    return out


def stretch(im, ref, gain=3.0):
    """對比放大(以 ref 為準),讓暗的樣本與灰塵看得清楚。"""
    lo = np.percentile(ref, 1)
    return np.clip((im.astype(np.float32) - lo) * gain, 0, 255).astype(np.uint8)


bgr = lambda im: cv2.cvtColor(im, cv2.COLOR_GRAY2BGR) if im.ndim == 2 else im
NAMES = ["Original", "Marked (red = excluded)", "A: weighted avg", "B: inpaint", "B2: inpaint x2 (+halo)"]

# ── [1] 人造灰塵 ──────────────────────────────────────────────────────────────
g = load(SHOT)
METHODS = [m for m, _ in g["FILL_METHODS"]]                                  # avg / inpaint / inpaint2
rng = np.random.default_rng(1)
flat = np.clip(rng.normal(50, 2, (40, 40)), 0, 255).astype(np.uint8)
dusty = flat.copy(); rej = np.zeros(flat.shape, bool)
for x, y in rng.integers(3, 37, (8, 2)):
    cv2.circle(dusty, (int(x), int(y)), 2, 220, -1); rej[y - 2:y + 3, x - 2:x + 3] = True
rej &= dusty == 220
k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g["FILL_GROW_PX"] + 1,) * 2)
grow = cv2.dilate(rej.astype(np.uint8), k) > 0
print("[1] 平坦 50 + 灰塵 220:")
for m in METHODS:
    fixed = g["fill_glint"](dusty, rej, m)
    allowed = grow if m == "inpaint2" else rej                               # B2 允許改到光暈範圍
    same = np.array_equal(fixed[~allowed], dusty[~allowed])
    print(f"  {m:9s} 灰塵處 {fixed[rej].mean():5.1f} ± {fixed[rej].std():4.1f};允許範圍外不變:{same}")
    assert abs(fixed[rej].mean() - 50) < 3 and same

# ── [2] 截圖影像 ──────────────────────────────────────────────────────────────
root = g["root"]
px, py, h = g["img_pad_x"], g["img_pad_y"], SIZE // 2
rois = [("rect", x - h + px, y - h + py, x + h + px, y + h + py) for y in ROWS for x in COLS]
g["_set_rois"](rois)
gray = g["current_frame"].copy()
sub = gray[py:py + g["img_disp_h"], px:px + g["img_disp_w"]]
full = {m: g["clean_image"](gray, m) for m in METHODS}
inside = np.zeros(sub.shape, bool)
for r in rois:
    _, x1, y1, x2, y2 = r
    inside[y1 - py:y2 - py, x1 - px:x2 - px] = True
print("\n[2] 截圖影像:%d 個 ROI" % len(rois))
for m in METHODS:
    changed = full[m] != sub
    print(f"  {m:9s} 修整 {changed.sum():4d} px,全部在 ROI 內:{not (changed & ~inside).any()}")
    assert not (changed & ~inside).any()

marked = bgr(sub)
for r in rois:
    patch, cmask, rej, *_ = g["deglint_roi_stats"](gray, r)
    _, x1, y1, x2, y2 = r
    marked[y1 - py:y2 - py, x1 - px:x2 - px][rej] = (0, 0, 255)

g["deglint_enabled"] = True
for r in rois:                                    # 量測分數不受修整影響:仍是紅點不計入的平均
    patch, cmask = g["get_roi_patch"](gray, r)
    gm = g["_roi_glint"](gray, r, cmask)
    assert g["compute_roi_mean"](patch, cmask, gm)[0] == float(patch[~gm].mean())
print("  分數計算不變:仍是「紅點不計入」的平均 ✓")


def boxes(im, rs, ox, oy):
    im = bgr(im).copy()
    for r in rs:
        if r[0] == "rect":
            cv2.rectangle(im, (r[1] - ox - 1, r[2] - oy - 1), (r[3] - ox, r[4] - oy), (0, 215, 255), 1)
        else:
            cv2.circle(im, (r[1] - ox, r[2] - oy), r[3] + 1, (0, 215, 255), 1)
    return im

strip = lambda im: cv2.resize(boxes(im, rois, px, py)[:, 60:210], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
cv2.imwrite(os.path.join(HERE, "cleaned_compare.png"),
            side_by_side([strip(sub), strip(marked)] + [strip(full[m]) for m in METHODS], NAMES))
zy1, zy2, zx1, zx2 = 55, 165, 100, 176
def zoom(im):
    z = im[zy1:zy2, zx1:zx2]
    z = bgr(stretch(z, sub)) if z.ndim == 2 else z
    return cv2.resize(z, None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST)
mk = bgr(stretch(sub, sub)); mk[(marked == (0, 0, 255)).all(-1)] = (0, 0, 255)
cv2.imwrite(os.path.join(HERE, "cleaned_zoom.png"),
            side_by_side([zoom(sub), zoom(mk)] + [zoom(full[m]) for m in METHODS], NAMES))

# 預覽視窗(五格)+「儲存修整後影像」(三張)
g["show_deglint_preview"]()
win = g["deglint_preview_win"]; win.update()
grid = win.winfo_children()[2]
caps = [w.cget("text") for w in grid.winfo_children()[0].winfo_children() if w.winfo_class() == "Label"][1:11:2]
print("  預覽每欄:", " / ".join(caps))
assert len(caps) == 5
DLG.append(os.path.join(HERE, "cleaned.png"))
btn = [w for w in win.winfo_children()[-1].winfo_children() if "Save cleaned" in w.cget("text")][0]
btn.invoke()
for m in METHODS:
    saved = cv2.imread(os.path.join(HERE, f"cleaned_{m}.png"), 0)
    assert saved is not None and np.array_equal(saved, full[m]), m
print("  「儲存修整後影像」輸出 cleaned_avg / cleaned_inpaint / cleaned_inpaint2.png ✓")
root.destroy()

# ── [3] 使用者影像 IMG_0779 + 12 個固定 ROI,重點 Sample 4 ───────────────────────
g = load(USER)
d = json.load(open(USER_ROIS, encoding="utf-8"))
assert (d["img_disp_w"], d["img_disp_h"], d["img_pad_x"], d["img_pad_y"]) == \
       (g["img_disp_w"], g["img_disp_h"], g["img_pad_x"], g["img_pad_y"]), "ROI 檔與影像座標空間不符"
rois = [tuple([r[0]] + [int(v) for v in r[1:]]) for r in d["rois"]]
g["_set_rois"](rois)
gray = g["current_frame"].copy()
px, py = g["img_pad_x"], g["img_pad_y"]

print(f"\n[3] IMG_0779:{len(rois)} 個 ROI(K={g['DEGLINT_K']:.0f},B2 擴 {g['FILL_GROW_PX']} px)")
print("  ROI | 標紅  | 原始    分數  |  A      B      B2   | B2 多改的 px(光暈)")
for i, r in enumerate(rois):
    patch, cmask, rej, pct, mb, ma = g["deglint_roi_stats"](gray, r)
    ins = cmask == 1
    c = {m: g["fill_glint"](patch, rej, m, cmask) for m in METHODS}
    extra = int(((c["inpaint2"] != patch) & ~rej).sum())
    print(f"  S{i+1:<2} | {pct:4.1f}% | {mb:6.2f} {ma:6.2f} | {c['avg'][ins].mean():6.2f} {c['inpaint'][ins].mean():6.2f} "
          f"{c['inpaint2'][ins].mean():6.2f} | {extra:3d}")

# Sample 4:同樣設定在 B 的結果上再做一次 B → 沒有新的點被標紅
r4 = rois[3]
y1, y2, x1, x2 = g["_roi_slice"](gray.shape, r4)
patch, cmask, rej, pct, mb, ma = g["deglint_roi_stats"](gray, r4)
b1 = g["fill_glint"](patch, rej, "inpaint", cmask)
g2 = gray.copy(); g2[y1:y2, x1:x2] = b1
_, _, rej2, *_ = g["deglint_roi_stats"](g2, r4)
bb = g["fill_glint"](b1, rej2, "inpaint", cmask)
b2 = g["fill_glint"](patch, rej, "inpaint2", cmask)
ins = cmask == 1
print(f"\n  Sample 4:第一次 B 標紅 {int(rej.sum())} px;在 B 的圖上用同樣設定再做一次,新標紅 {int(rej2.sum())} px")
print(f"  → 中位數/MAD 門檻不會因為去掉亮點而降低,B 留下的淡點(光暈)本來就沒超過門檻,所以重做不會變")
print(f"  B2(連光暈 {g['FILL_GROW_PX']} px 一起補):修改 {int((b2 != patch).sum())} px,"
      f"ROI 標準差 {patch[ins].std():.2f} → B {b1[ins].std():.2f} → B2 {b2[ins].std():.2f}")
assert b2[ins].std() < b1[ins].std()

def z4(im):
    a = stretch(im, patch[ins], 255.0 / max(1, np.percentile(patch[ins], 99.5) - np.percentile(patch[ins], 1))) if im.ndim == 2 else im
    a = bgr(a).copy(); a[~ins] = (a[~ins] * 0.3).astype(np.uint8)
    return cv2.resize(a, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
m4 = bgr(stretch(patch, patch[ins], 255.0 / max(1, np.percentile(patch[ins], 99.5) - np.percentile(patch[ins], 1))))
m4[rej] = (0, 0, 255)
cv2.imwrite(os.path.join(HERE, "s4_compare.png"),
            side_by_side([z4(patch), z4(m4), z4(g["fill_glint"](patch, rej, "avg", cmask)), z4(b1), z4(bb), z4(b2)],
                         ["Sample 4", "Marked", "A", "B", "B again (same)", "B2"]))

# 12 個 ROI 整區對照
sub = gray[py:py + g["img_disp_h"], px:px + g["img_disp_w"]]
full = {m: g["clean_image"](gray, m) for m in METHODS}
mk = bgr(stretch(sub, sub))
for r in rois:
    patch, cmask, rej, *_ = g["deglint_roi_stats"](gray, r)
    yy1, yy2, xx1, xx2 = g["_roi_slice"](gray.shape, r)
    mk[yy1 - py:yy2 - py, xx1 - px:xx2 - px][rej] = (0, 0, 255)
xs = [r[1] - px for r in rois]; ys = [r[2] - py for r in rois]
cy1, cy2, cx1, cx2 = max(0, min(ys) - 30), max(ys) + 30, max(0, min(xs) - 30), max(xs) + 30
crop = lambda im: cv2.resize(boxes(bgr(stretch(im, sub)) if im.ndim == 2 else im, rois, px, py)[cy1:cy2, cx1:cx2],
                             None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
cv2.imwrite(os.path.join(HERE, "img0779_compare.png"),
            side_by_side([crop(sub), crop(mk)] + [crop(full[m]) for m in METHODS], NAMES))
g["root"].destroy()
print("\n已輸出 cleaned_compare.png / cleaned_zoom.png / img0779_compare.png / s4_compare.png")
print("      cleaned_avg.png / cleaned_inpaint.png / cleaned_inpaint2.png\n全部測試通過")
