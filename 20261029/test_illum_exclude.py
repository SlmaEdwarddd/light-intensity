# -*- coding: utf-8 -*-
"""
背景估計:樣本比 ROI 大時的排除測試(舊:固定排除 ROI 中心 ±3 倍半徑 / 新:自動量樣本大小)。

用法(light_intensity conda 環境):python test_illum_exclude.py
[1] 合成圖,照明其實均勻;6 個樣本實心半徑 45 px + 淡光暈到 ~80 px、由左到右越來越亮,ROI 只有 r=10
    (光暈每點只比背景亮一點,低於 sigma clipping 門檻,剔不掉,但數量多會把擬合拉高)
    → 正確答案:不需校正,各 ROI 增益 ≈ 1。舊方法會把框外的樣本當成背景,誤以為右邊照明較亮。
[2] 同樣的樣本,但照明由左到右真的變 2 倍 → 新方法要還原出真實照明。
[3] B-8:同一張圖,ROI 大小 r=8 / 23 / 35,看照明估計是否還會跟著 ROI 大小變。
輸出 test_illum_exclude.png
"""
import os, json
import numpy as np
import cv2
from tkinter import messagebox
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261029.py")
OUT = os.path.join(HERE, "test_output"); os.makedirs(OUT, exist_ok=True)
for n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, n, lambda *a, **k: None)
messagebox.askokcancel = lambda *a, **k: True
code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
g = {"__name__": "__main__", "__file__": PROG}
exec(compile(code, PROG, "exec"), g)
g["CAMERA_TYPE"] = "IMAGE"
new_extent = g["_sample_extent"]


def load(img):
    p = os.path.join(OUT, "_illum_exclude_tmp.png")
    cv2.imencode(".png", img)[1].tofile(p)
    assert g["load_image_file"](p)
    g["_publish_frame"](g["source_image_gray"])
    return g["current_frame"].copy()


def run(gray, rois, old):
    """old=True:把樣本大小固定成 ROI 半徑 → 排除範圍 = 舊版的 ±3 倍半徑。"""
    g["_sample_extent"] = (lambda sm, cx, cy, r0, rmax: 3 * r0 / g["ILLUM_EXCLUDE_MARGIN"]) if old else new_extent
    illum, pts = g["estimate_illumination"](gray, rois)
    gain = g["make_illum_gain"](illum, rois)
    return illum, pts, list(g["illum_excl"]), g["roi_gain_factors"](gain, rois)


def synth(illum_ratio, seed=0):
    rng = np.random.default_rng(seed)
    H, W = 170, 900
    xx, yy = np.meshgrid(np.arange(W), np.arange(H))
    light = 1 + (illum_ratio - 1) * xx / (W - 1)                    # 照明:左 1 → 右 illum_ratio
    sig = np.zeros((H, W), np.float32)
    cxs = [100 + 140 * i for i in range(6)]
    for i, cx in enumerate(cxs):
        d = np.hypot(xx - cx, yy - 85)
        sig += (0.3 + 0.35 * i) * np.where(d < 45, 1.0, 0.25 * np.exp(-((d - 45) / 18.0) ** 2))  # 實心 45 px + 淡光暈到 ~80 px
    img = 20 * light * (1 + sig) + rng.normal(0, 1.5, (H, W))
    for _ in range(80):                                              # 灰塵
        cv2.circle(img, (int(rng.uniform(0, W)), int(rng.uniform(0, H))), 1, float(rng.uniform(80, 160)), -1)
    return np.clip(img, 0, 255).astype(np.uint8), cxs, light


res = {}
for case, ratio in (("均勻照明", 1.0), ("照明左→右 2 倍", 2.0)):
    img, cxs, light = synth(ratio)
    gray = load(img)
    x0, y0 = g["img_pad_x"], g["img_pad_y"]
    rois = [("circle", cx + x0, 85 + y0, 10) for cx in cxs]
    g["_set_rois"](rois)
    true = np.array([light[85, cx] for cx in cxs]); true_gain = true.mean() / true
    for old in (True, False):
        illum, pts, excl, facs = run(gray, rois, old)
        err = np.max(np.abs(np.array(facs) / true_gain - 1)) * 100
        name = "舊(±3r)" if old else "新(自動)"
        res[(case, old)] = (gray, illum, pts, excl, facs, true_gain, x0, y0)
        print(f"[{case}] {name}: 排除半徑 {[round(e[2]) for e in excl]}  ROI 增益 {np.round(facs, 3).tolist()}"
              f"  真實 {np.round(true_gain, 3).tolist()}  最大誤差 {err:.1f}%")
        if not old:
            assert err < 3.0, f"{case}:新方法誤差 {err:.1f}% 過大"

# [3] B-8:不同 ROI 大小
img = cv2.imdecode(np.fromfile(os.path.join(HERE, "test image", "Chi 20261014 B_8.png"), np.uint8), cv2.IMREAD_UNCHANGED)
gray = load(cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY))
x0, y0, W = g["img_pad_x"], g["img_pad_y"], g["img_disp_w"]
js = json.load(open(os.path.join(HERE, "ROI_layouts", "B_8.json"), encoding="utf-8"))
k = W / js["img_disp_w"]
cen = [((r[1] - js["img_pad_x"]) * k + x0, (r[2] - js["img_pad_y"]) * k + y0) for r in js["rois"]]
b8 = {}
for rr in (8, 23, 35):
    rois = [("circle", int(round(cx)), int(round(cy)), rr) for cx, cy in cen]
    for old in (True, False):
        illum, pts, excl, facs = run(gray, rois, old)
        lr = illum[int(cen[-1][1]), int(cen[-1][0])] / illum[int(cen[0][1]), int(cen[0][0])]
        b8[(rr, old)] = (lr, facs, excl)
        print(f"[B-8 ROI r={rr:2d}] {'舊' if old else '新'}: 排除半徑 {[round(e[2]) for e in excl]}  "
              f"照明 最右/最左樣本 = {lr:.2f}  ROI 增益 {np.round(facs, 2).tolist()}")
spread_old = np.ptp([b8[(rr, True)][0] for rr in (8, 23, 35)])
spread_new = np.ptp([b8[(rr, False)][0] for rr in (8, 23, 35)])
print(f"B-8 照明右/左 隨 ROI 大小的變動:舊 {spread_old:.2f} → 新 {spread_new:.2f}")
assert spread_new < spread_old, "新方法的照明估計應該比較不受 ROI 大小影響"

# ── 圖:均勻照明那組,舊 vs 新 ──
plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
fig, axes = plt.subplots(3, 2, figsize=(14, 9), gridspec_kw=dict(height_ratios=[1, 1, 1.1]))
for col, case in enumerate(("均勻照明", "照明左→右 2 倍")):
    for row, old in enumerate((True, False)):
        gray, illum, pts, excl, facs, tg, x0, y0 = res[(case, old)]
        ax = axes[row, col]
        ax.imshow(gray[y0:y0 + 170, x0:x0 + 900], cmap="gray", vmin=15, vmax=80)
        ax.scatter(pts[1] - x0, pts[0] - y0, s=1, c="w", alpha=0.5)
        for cx, cy, rad in excl:
            ax.add_patch(plt.Circle((cx - x0, cy - y0), rad, fill=False, color="magenta", lw=1.2))
            ax.add_patch(plt.Circle((cx - x0, cy - y0), 10, fill=False, color="yellow", lw=1))
        err = np.max(np.abs(np.array(facs) / tg - 1)) * 100
        ax.set_title(f"{case} — {'舊:排除 ±3 倍 ROI 半徑' if old else '新:自動量樣本大小'}(增益最大誤差 {err:.1f}%)", fontsize=10)
        ax.axis("off")
    ax = axes[2, col]
    for old, c in ((True, "#d62728"), (False, "#1f77b4")):
        gray, illum, *_ , x0, y0 = res[(case, old)]
        ax.plot(illum[y0 + 85, x0:x0 + 900] / illum[y0 + 85, x0 + 450], c, label="舊" if old else "新")
    _, cxs, light = synth(1.0 if col == 0 else 2.0)
    ax.plot(light[85] / light[85, 450], "k--", label="真實照明")
    ax.set_title("估計的照明(中央那一列,以中間為 1)", fontsize=10); ax.set_xlabel("x (px)"); ax.legend(fontsize=8)
fig.suptitle("黃圈 = ROI(r=10),紫圈 = 排除的樣本範圍,白點 = 用來擬合照明的背景點", fontsize=11)
fig.tight_layout()
p = os.path.join(HERE, "test_illum_exclude.png"); fig.savefig(p, dpi=105)
print("已存", p)

# 程式預覽視窗能畫出排除範圍
g["_sample_extent"] = new_extent
g["_set_rois"]([("circle", int(round(cx)), int(round(cy)), 23) for cx, cy in cen])
g["illum_mode"] = "background"
g["show_illum_preview"]()
assert g["illum_preview_win"] is not None
print("程式預覽視窗(背景估計 + 排除範圍)OK")
g["root"].destroy()
