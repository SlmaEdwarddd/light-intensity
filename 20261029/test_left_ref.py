# -*- coding: utf-8 -*-
"""
左側參考平場(影像最左邊 5% 寬當平場)效果測試 —— B-8(test image/Chi 20261014 B_8.png)。

用法(light_intensity conda 環境):python test_left_ref.py
比較 3 種模式:不校正 / 左側參考 / 背景估計,全部用程式本身的函式(build_illum_correction、_roi_glint)。
每個樣本 3 個子 ROI 當重複量測(同 lod_analysis 的 sub 模式),算斜率、R²、LOD。
輸出 test_left_ref_B8.png、test_left_ref_B8.csv
"""
import os, csv, json
import numpy as np
import cv2
from tkinter import messagebox
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261029.py")
IMG = os.path.join(HERE, "test image", "Chi 20261014 B_8.png")
LABELS = ["blank", "1e-13", "1e-12", "1e-11", "1e-10", "1e-9"]      # B-8 由左到右
FIT = ["1e-13", "1e-12", "1e-11", "1e-10"]
for n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, n, lambda *a, **k: None)
messagebox.askokcancel = lambda *a, **k: True

code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
g = {"__name__": "__main__", "__file__": PROG}
exec(compile(code, PROG, "exec"), g)
g["CAMERA_TYPE"] = "IMAGE"
assert g["load_image_file"](IMG)
g["_publish_frame"](g["source_image_gray"])
gray = g["current_frame"].copy()
x0, y0, W, H = g["img_pad_x"], g["img_pad_y"], g["img_disp_w"], g["img_disp_h"]
# B_8.json 存檔時畫面是另一種縮放(1280x287),換算到目前的顯示座標
js = json.load(open(os.path.join(HERE, "ROI_layouts", "B_8.json"), encoding="utf-8"))
k = W / js["img_disp_w"]
rois = [(r[0], int(round((r[1] - js["img_pad_x"]) * k + x0)), int(round((r[2] - js["img_pad_y"]) * k + y0)),
         max(1, int(round(r[3] * k)))) for r in js["rois"]]
g["_set_rois"](rois)
g["deglint_enabled"] = True                                          # 量測時去反光(程式預設 K=4、kernel 9)


def disk(cx, cy, r):
    m = np.zeros(gray.shape, np.uint8); cv2.circle(m, (int(round(cx)), int(round(cy))), int(round(r)), 1, -1)
    return m.astype(bool)


# 背景取樣:ROI 外擴 1.5 倍以外、影像有效區內(用來看左右 / 上下是否變平)
bgmask = np.zeros(gray.shape, bool); bgmask[y0:y0 + H, x0:x0 + W] = True
for _, cx, cy, r in rois:
    bgmask &= ~disk(cx, cy, 2.5 * r)
smooth = cv2.medianBlur(gray, 5).astype(np.float32)

rows, res = [], {}
for mode in ("off", "left", "background"):
    if mode == "off":
        gain, msg = np.ones(gray.shape, np.float32), "no correction"
    else:
        gain, _, msg = g["build_illum_correction"](gray, rois, mode)
        assert gain is not None, msg
    corr = g["apply_illum_gain"](gray.astype(np.float32), gain)
    stats = {}
    for lab, r in zip(LABELS, rois):
        _, cx, cy, rad = r
        y1, y2, xa, xb = g["_roi_slice"](gray.shape, r)
        glint = np.zeros(gray.shape, bool)
        patch, cmask = g["get_roi_patch"](gray, r)
        glint[y1:y2, xa:xb] = g["_roi_glint"](gray, r, cmask)
        vals = [corr[disk(cx + 0.5 * rad * np.cos(a), cy + 0.5 * rad * np.sin(a), 0.45 * rad) & ~glint].mean()
                for a in np.deg2rad([-90, 30, 150])]
        stats[lab] = (float(np.mean(vals)), float(np.std(vals, ddof=1)))
    x = np.log10([float(l) for l in FIT]); y = np.array([stats[l][0] for l in FIT])
    m, b = np.polyfit(x, y, 1)
    r2 = 1 - np.sum((y - (m * x + b)) ** 2) / np.sum((y - y.mean()) ** 2)
    mu, sd = stats["blank"]
    lod = 10 ** ((mu + 3 * sd - b) / m)
    sc = g["apply_illum_gain"](smooth, gain)
    left_bg = float(np.median(sc[bgmask & (np.arange(gray.shape[1]) < x0 + W * 0.15)[None, :]]))
    right_bg = float(np.median(sc[bgmask & (np.arange(gray.shape[1]) > x0 + W * 0.85)[None, :]]))
    res[mode] = dict(corr=corr, stats=stats, m=m, b=b, r2=r2, lod=lod, sc=sc, lr=right_bg / left_bg)
    rows.append([mode, msg, f"{m:.4f}", f"{r2:.4f}", f"{mu:.3f}", f"{sd:.3f}", f"{lod:.3g}", f"{right_bg / left_bg:.3f}"]
                + [f"{stats[l][0]:.3f}±{stats[l][1]:.3f}" for l in LABELS])
    print(f"{mode:10s} 斜率 {m:6.3f}  R² {r2:.4f}  blank {mu:.2f}±{sd:.2f}  LOD {lod:.2e}  背景 右/左 = {right_bg / left_bg:.2f}")
    print("           " + "  ".join(f"{l}:{stats[l][0]:.2f}" for l in LABELS))

with open(os.path.join(HERE, "test_left_ref_B8.csv"), "w", newline="", encoding="utf-8-sig") as fp:
    w = csv.writer(fp)
    w.writerow(["mode", "info", "slope", "R2", "blank_mean", "blank_std", "LOD_M", "bg_right/left"] + LABELS)
    w.writerows(rows)

# ── 圖 ──
plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
names = {"off": "不校正", "left": "左側參考(最左 5% 當平場)", "background": "背景估計(多項式擬合)"}
colors = {"off": "#555555", "left": "#1f77b4", "background": "#d62728"}
fig = plt.figure(figsize=(14, 10))
gs = fig.add_gridspec(4, 2, height_ratios=[1, 1, 1, 1.6], width_ratios=[1.5, 1])
lo, hi = np.percentile(gray[y0:y0 + H, x0:x0 + W], [1, 99.5])
wref = max(3, int(round(W * g["LEFT_REF_FRAC"])))
for i, mode in enumerate(res):
    ax = fig.add_subplot(gs[i, :])
    ax.imshow(res[mode]["corr"][y0:y0 + H, x0:x0 + W], cmap="gray", vmin=lo, vmax=hi)
    for lab, (_, cx, cy, r) in zip(LABELS, rois):
        ax.add_patch(plt.Circle((cx - x0, cy - y0), r, fill=False, color="yellow", lw=0.8))
        ax.text(cx - x0, cy - y0 - r - 4, lab, color="yellow", ha="center", fontsize=8)
    if mode == "left":
        ax.add_patch(plt.Rectangle((0, 0), wref, H - 1, fill=False, color="#00BFFF", lw=2))
    ax.set_title(f"{names[mode]} — 背景 右/左 = {res[mode]['lr']:.2f}(同一對比範圍)", fontsize=11)
    ax.axis("off")

ax = fig.add_subplot(gs[3, 0])                       # 背景沿 x 的亮度(每欄背景中位數)
for mode in res:
    sc = np.where(bgmask, res[mode]["sc"], np.nan)[y0:y0 + H, x0:x0 + W]
    prof = np.nanmedian(sc, axis=0)
    ax.plot(np.arange(W), prof, color=colors[mode], label=names[mode], lw=1.2)
ax.axvspan(0, wref, color="#00BFFF", alpha=0.15, label="左側參考區")
ax.set_xlabel("x(顯示 px)"); ax.set_ylabel("背景灰階"); ax.set_title("背景亮度 由左到右(樣本外)")
ax.legend(fontsize=8)

ax = fig.add_subplot(gs[3, 1])                       # 校正曲線
xs = np.log10([float(l) for l in LABELS[1:]])
for mode in res:
    st = res[mode]["stats"]
    ax.errorbar(xs, [st[l][0] for l in LABELS[1:]], yerr=[st[l][1] for l in LABELS[1:]], fmt="o", color=colors[mode], ms=4, capsize=2)
    xf = np.log10([float(l) for l in FIT])
    ax.plot(xf, res[mode]["m"] * xf + res[mode]["b"], color=colors[mode], lw=1,
            label=f"{names[mode].split('(')[0]}  R²={res[mode]['r2']:.3f}  LOD={res[mode]['lod']:.1e}")
    ax.axhline(st["blank"][0] + 3 * st["blank"][1], color=colors[mode], ls=":", lw=0.8)
ax.set_xticks(xs)
ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"1e{int(round(v))}"))
ax.text(0.98, 0.04, "不校正與左側參考的點完全重疊", transform=ax.transAxes, ha="right", fontsize=8, color="#1f77b4")
ax.set_xlabel("濃度 (M)"); ax.set_ylabel("ROI 平均(去反光後)"); ax.set_title("校正曲線(虛線 = blank + 3σ)")
ax.legend(fontsize=8)
fig.tight_layout()
out = os.path.join(HERE, "test_left_ref_B8.png")
fig.savefig(out, dpi=110)
print("已存", out)

# 檢查:左側參考只改上下,同一列左右的增益相同
gl, _, _ = g["build_illum_correction"](gray, rois, "left")
blk = gl[y0:y0 + H, x0:x0 + W]
assert np.allclose(blk, blk[:, :1]), "左側參考的增益每列應該左右相同"
g["illum_mode"] = "left"
g["show_illum_preview"]()                            # 程式內的預覽視窗(含藍框)能正常開
assert g["illum_preview_win"] is not None
print("程式預覽視窗(左側參考)OK")
g["root"].destroy()
