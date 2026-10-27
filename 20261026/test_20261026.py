# -*- coding: utf-8 -*-
"""
20261026 測試:亮度不均校正(背景估計 / 平場參考)

用法(在 light_intensity conda 環境):
    python test_20261026.py

[1] 合成影像(已知答案):6 個樣本真實亮度已知,照明左暗右亮 + 上下暗角 + 灰塵 + 雜訊。
    校正正確時,各樣本「量測值 / 真實值」應該一樣 → 看比例的 CV 與對真實值的 R²。
[2] 真實測試圖(20261022/messageImage_1792573760104.jpg):看背景不均勻度降多少、各 ROI 增益。
[3] 完整量測流程:開始 → 停止 → 存 CSV,CSV 數值 = 預覽算的校正後平均;平場重開程式可載入。
輸出:illum_compare.png(真實圖:原圖 / 照明分佈 / 校正後)、illum_synthetic.csv
"""
import os, sys, time, csv, tempfile, threading, collections
import numpy as np
import cv2
import tkinter as tk
from tkinter import messagebox, filedialog

HERE  = os.path.dirname(os.path.abspath(__file__))
PROG  = os.path.join(HERE, "20261026.py")
REAL  = os.path.join(HERE, "..", "20261022", "messageImage_1792573760104.jpg")
REAL_CENTERS = [(134, 89), (263, 94), (386, 91), (513, 101), (638, 92), (764, 96)]   # 見 test_20261022.py

MSGS, DLG = [], collections.deque()
messagebox.askokcancel = lambda *a, **k: True
messagebox.askyesno    = lambda *a, **k: False
for _n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _n, lambda *a, **k: MSGS.append(a))
filedialog.asksaveasfilename = lambda **k: DLG.popleft()


def load_program(image, app_dir):
    """無頭載入主程式(不跑 mainloop、不跳相機選擇);app_dir 指到暫存資料夾,不動到真正的設定檔。"""
    code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0]
    code = code.replace("root.after(100, start_system)", "pass")
    g = {"__name__": "__main__", "__file__": PROG}
    exec(compile(code, PROG, "exec"), g)
    g["APP_DIR"] = app_dir
    g["ROI_DIR"] = os.path.join(app_dir, "ROI_layouts")
    g["CAMERA_TYPE"] = "IMAGE"
    assert g["load_image_file"](image)
    g["setup_ui_for_image_mode"]()
    threading.Thread(target=g["video_loop_image"], daemon=True).start()
    return g


def pump(root, sec):
    t = time.time()
    while time.time() - t < sec:
        root.update(); time.sleep(0.01)


def roi_rects(g, centers, size):
    px, py, h = g["img_pad_x"], g["img_pad_y"], size // 2
    return [("rect", cx - h + px, cy - h + py, cx + h + px, cy + h + py) for cx, cy in centers]


def roi_means(g, rois, gain=None):
    """與量測相同的 ROI 平均(含目前的 de-glint 設定);gain 給定時套用亮度校正。"""
    with g["frame_lock"]:
        f = g["current_frame"].copy()
    out = []
    for r in rois:
        patch, cmask = g["get_roi_patch"](f, r)
        gs = g["_roi_glint"](f, r, cmask) if g["deglint_enabled"] else None
        y1, y2, x1, x2 = g["_roi_slice"](f.shape, r)
        out.append(g["compute_roi_mean"](patch, cmask, gs, None if gain is None else gain[y1:y2, x1:x2])[0])
    return np.array(out)


def r2(x, y):
    a, b = np.polyfit(x, y, 1)
    return 1 - np.sum((y - (a * x + b)) ** 2) / np.sum((y - y.mean()) ** 2)


tmp = tempfile.mkdtemp(prefix="li_illum_")

# ══ [1] 合成影像 ═══════════════════════════════════════════════════════════════
rng = np.random.default_rng(0)
H, W = 300, 900
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
illum = (0.45 + 0.55 * xx / (W - 1)) * (1 - 0.25 * ((yy - H / 2) / (H / 2)) ** 2)   # 左暗右亮 + 上下暗角
BG = 12.0
TRUE = np.array([64, 32, 16, 8, 4, 2], np.float32) * 2.5                          # 對半稀釋的真實亮度
SC_CENTERS = [(95 + 142 * i, 150) for i in range(6)]
scene = np.full((H, W), BG, np.float32)
for (cx, cy), t in zip(SC_CENTERS, TRUE):
    scene[(xx - cx) ** 2 + (yy - cy) ** 2 <= 55 ** 2] += t


def shoot(sc):
    im = sc * illum + rng.normal(0, 1.0, sc.shape)
    for _ in range(250):                                                            # 灰塵亮點
        x, y = rng.integers(0, W), rng.integers(0, H)
        cv2.circle(im, (int(x), int(y)), int(rng.integers(1, 3)), float(rng.uniform(80, 220)), -1)
    return np.clip(im, 0, 255).astype(np.uint8)


sample_png = os.path.join(tmp, "synthetic_sample.png"); cv2.imwrite(sample_png, shoot(scene))
flat_png   = os.path.join(tmp, "synthetic_flat.png");   cv2.imwrite(flat_png, shoot(np.full((H, W), 150, np.float32)))

g = load_program(flat_png, tmp)
root = g["root"]; pump(root, 0.3)
g["deglint_enable_var"].set(True); g["deglint_enabled"] = True
rois = roi_rects(g, SC_CENTERS, 60)
g["_set_rois"](rois)

# 平場:先在空白參考上擷取,再換成樣本影像(同一套座標)
g["capture_flat_field"](); pump(root, 1.5)
assert g["flat_field"] is not None and os.path.exists(g["_flat_path"]()), "平場沒有擷取 / 存檔"
assert g["load_image_file"](sample_png); pump(root, 0.3)
with g["frame_lock"]:
    gray = g["current_frame"].copy()

results = {"raw": roi_means(g, rois)}
for mode in ("background", "flat"):
    gain, _, msg = g["build_illum_correction"](gray, rois, mode)
    assert gain is not None, msg
    results[mode] = roi_means(g, rois, gain)

truth = BG + TRUE
print("\n[1] 合成影像(真實亮度已知;照明左右差 %.1f 倍)" % (illum.max() / illum.min()))
print("     真實值  " + " ".join(f"{v:7.1f}" for v in truth))
rows = []
for name, label in (("raw", "未校正  "), ("background", "背景估計"), ("flat", "平場參考")):
    m = results[name]; ratio = m / truth
    cv_ = 100 * ratio.std() / ratio.mean()
    rows.append([name] + [round(float(v), 3) for v in m] + [round(cv_, 2), round(r2(truth, m), 5)])
    print(f"  {label} " + " ".join(f"{v:7.2f}" for v in m) + f" | 量測/真實 CV {cv_:5.2f}% | R² {r2(truth, m):.5f}")
with open(os.path.join(HERE, "illum_synthetic.csv"), "w", newline="", encoding="utf-8") as fp:
    w = csv.writer(fp)
    w.writerow(["mode"] + [f"S{i+1}" for i in range(6)] + ["ratio_CV_%", "R2_vs_truth"])
    w.writerow(["truth"] + [float(v) for v in truth] + ["", ""])
    w.writerows(rows)
cv_raw, cv_bg, cv_flat = (r[-2] for r in rows)
assert cv_bg < cv_raw / 3 and cv_flat < cv_raw / 5, "校正後各樣本比例應該明顯更一致"
root.destroy()

# ══ [2] 真實測試圖 ═════════════════════════════════════════════════════════════
g = load_program(REAL, tmp)
root = g["root"]; pump(root, 0.3)
g["deglint_enable_var"].set(True); g["deglint_enabled"] = True
rois = roi_rects(g, REAL_CENTERS, 60)
g["_set_rois"](rois)
with g["frame_lock"]:
    gray = g["current_frame"].copy()
gain, pts, msg = g["build_illum_correction"](gray, rois, "background")
sm = cv2.medianBlur(gray, 5).astype(np.float32)
v0 = sm[pts]; v1 = g["apply_illum_gain"](v0, gain[pts])
facs = g["roi_gain_factors"](gain, rois)
m0, m1 = roi_means(g, rois), roi_means(g, rois, gain)
print("\n[2] 真實測試圖(背景估計)")
print(f"  背景不均勻度 CV {100 * v0.std() / v0.mean():.1f}% → {100 * v1.std() / v1.mean():.1f}%")
print("  增益   " + " ".join(f"{f:7.3f}" for f in facs))
print("  校正前 " + " ".join(f"{v:7.2f}" for v in m0))
print("  校正後 " + " ".join(f"{v:7.2f}" for v in m1))
assert v1.std() / v1.mean() < 0.5 * v0.std() / v0.mean()

# 對照圖(與程式內預覽同樣的三格)
x0, y0, Wd, Hd = g["img_pad_x"], g["img_pad_y"], g["img_disp_w"], g["img_disp_h"]
sub, gsub = gray[y0:y0 + Hd, x0:x0 + Wd], gain[y0:y0 + Hd, x0:x0 + Wd]
a, b = g["_stretch_pair"](sub, g["apply_illum_gain"](sub, gsub))
imap = cv2.applyColorMap(cv2.normalize(1.0 / gsub, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8), cv2.COLORMAP_JET)
a, b = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR), cv2.cvtColor(b, cv2.COLOR_GRAY2BGR)
for i, r in enumerate(rois):
    _, x1, y1, x2, y2 = r
    for im in (a, imap, b):
        cv2.rectangle(im, (x1 - x0, y1 - y0), (x2 - x0, y2 - y0), (0, 215, 255), 1)
    cv2.putText(imap, f"x{facs[i]:.2f}", (x1 - x0, y1 - y0 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.putText(a, f"{m0[i]:.1f}", (x1 - x0, y2 - y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
    cv2.putText(b, f"{m1[i]:.1f}", (x1 - x0, y2 - y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

def titled(im, text):
    bar = np.full((24, im.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, text, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return np.vstack([bar, im])

cv2.imwrite(os.path.join(HERE, "illum_compare.png"), cv2.resize(np.vstack([
    titled(a, "Original (ROI mean below box)"),
    titled(imap, "Estimated illumination (red = bright, blue = dark; gain per ROI)"),
    titled(b, "Corrected (same contrast range as original)")]), None, fx=1.5, fy=1.5, interpolation=cv2.INTER_NEAREST))
print("  已輸出 illum_compare.png / illum_synthetic.csv")

# ══ [3] 完整量測流程 ═══════════════════════════════════════════════════════════
print("\n[3] 量測流程(背景估計 + De-glint)")
g["illum_mode_var"].set("background"); g["toggle_illum_mode"]()
g["show_illum_preview"](); g["illum_preview_win"].update()
assert g["illum_preview_win"].winfo_exists()
for w in root.winfo_children():
    if isinstance(w, tk.Toplevel) and w is not g["adv_win"]:
        w.destroy()
g["start_btn"].invoke()
assert g["analyzing"] and g["illum_gain"] is not None
assert all(str(w["state"]) == "disabled" for w in g["illum_radios"]), "量測中應鎖定校正方式"
root.after(3500, root.quit); root.mainloop()
g["start_btn"].invoke(); pump(root, 0.3)
DLG.append(os.path.join(tmp, "run.csv")); g["save_btn"].invoke()
data = list(csv.reader(open(os.path.join(tmp, "run.csv"), encoding="utf-8")))
info = [r[0] for r in data if r[0].startswith("Illumination correction")][0]
gains = [float(v) for v in [r for r in data if r[0].startswith("Illum gain")][0][1:]]
means = [float(v) for v in [r for r in data if r[0].startswith("Mean")][0][1:]]
print("  CSV:", info)
print("  CSV 增益  :", gains)
print("  CSV Mean  :", means)
print("  預覽校正後:", [round(v, 2) for v in m1])
assert np.allclose(means, np.round(m1, 2), atol=0.011) and np.allclose(gains, np.round(facs, 4), atol=1e-4)
g["start_btn"].invoke()                                     # 重新量測
assert g["illum_gain"] is None and all(str(w["state"]) == "normal" for w in g["illum_radios"])
print("  CSV 與預覽一致;重新量測後校正解鎖 ✓")
root.destroy()

# 平場檔重開程式可載入(在 [1] 擷取的那份;尺寸與真實圖不同 → 應拒用)
g = load_program(sample_png, tmp)
assert g["load_flat_field"](silent=True) and g["flat_field"] is not None
g["root"].destroy()
g = load_program(REAL, tmp)
assert not g["load_flat_field"](silent=True), "解析度不同的平場不應被套用"
g["root"].destroy()
print("  平場:同解析度重開自動載入、不同解析度拒用 ✓")
print("\n全部測試通過")
