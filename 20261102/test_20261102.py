# -*- coding: utf-8 -*-
"""
20261102 測試:依載玻片 CAD 佈局「自動」放置 ROI(使用者不框 ROI,只能整組調大小 / 形狀)

用法(light_intensity conda 環境):python test_20261102.py

用 slide_layout.json 畫「答案已知」的合成載玻片影像(px/mm、旋轉、鏡像、位置都已知,19 格各自不同亮度,
加雜訊與灰塵亮點),存成 RGBA PNG:
  [1] RGBA PNG 讀檔:不再被壓成少數灰階(用 20261029 實際出問題的 B_8)
  [2] 管理者校正(點 T1 / T8 / B1):19 個 ROI 對準格子,校正存檔
  [3] 重開程式、載玻片放偏 (+12, −7) px:不點任何東西,自動微調後 ROI 仍對準
  [4] 使用者只能整組調大小 / 形狀;點影像、右鍵拖曳都不會新增或移動 ROI
  [5] 重新量測後 ROI 保留,可直接開始
  [6] 鏡像 + 旋轉的相機也能校正;點錯格會警告
  [7] 沒有校正檔 / 相機解析度不同:不放 ROI,提示管理者校正
所有檔案寫在暫存資料夾,不動到真正的 slide_calibration.json。
輸出:test_output/test_layout_overlay.png(影像 B 自動放好的 ROI)
"""
import os, json, shutil, tempfile
import numpy as np
import cv2
import tkinter as tk
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261102.py")
LAYOUT = json.load(open(os.path.join(HERE, "slide_layout.json"), encoding="utf-8"))
WELLS = LAYOUT["wells"]

ASKS = []
messagebox.askokcancel = lambda *a, **k: (ASKS.append(a), True)[1]
for _n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _n, lambda *a, **k: None)


def make_slide(path, px_per_mm=12.0, angle_deg=2.0, mirror=False, shift=(0, 0), size=(1024, 460)):
    # 寬 ≤ 1024:程式顯示區為 1024x768,這樣影像不會被縮放,答案座標可以直接比對
    """合成影像(綠色螢光樣的 RGBA PNG);回傳 mm → 影像 px 的 2x3 轉換 A 與每格亮度。"""
    W, H = size
    c, s = np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))
    R = np.array([[c, -s], [s, c]]) @ np.diag([px_per_mm * (-1 if mirror else 1), -px_per_mm])   # 圖面 y 向上 → 影像 y 向下
    center_mm = np.array([LAYOUT["slide_w_mm"] / 2, LAYOUT["slide_h_mm"] / 2])
    t = np.array([W / 2 + shift[0], H / 2 + shift[1]]) - R @ center_mm
    A = np.hstack([R, t[:, None]])
    rng = np.random.default_rng(3)
    img = np.full((H, W), 18.0, np.float32)
    outline = np.array([[0, 0], [LAYOUT["slide_w_mm"], 0], [LAYOUT["slide_w_mm"], LAYOUT["slide_h_mm"]], [0, LAYOUT["slide_h_mm"]]])
    cv2.fillPoly(img, [np.int32([A @ [x, y, 1] for x, y in outline])], 30.0)
    level = {}
    for i, w in enumerate(WELLS):
        level[w["name"]] = 60.0 + 7.0 * i
        hw, hh = w["w_mm"] / 2, w["h_mm"] / 2
        corners = [(w["x_mm"] - hw, w["y_mm"] - hh), (w["x_mm"] + hw, w["y_mm"] - hh),
                   (w["x_mm"] + hw, w["y_mm"] + hh), (w["x_mm"] - hw, w["y_mm"] + hh)]
        cv2.fillPoly(img, [np.int32(np.round([A @ [x, y, 1] for x, y in corners]))], level[w["name"]])
    img += rng.normal(0, 1.5, img.shape)
    for _ in range(120):                                                    # 灰塵亮點
        cv2.circle(img, (int(rng.integers(0, W)), int(rng.integers(0, H))), int(rng.integers(1, 3)), 220.0, -1)
    g = np.clip(img, 0, 255).astype(np.uint8)
    cv2.imencode(".png", cv2.merge([g // 4, g, g // 5, np.full_like(g, 255)]))[1].tofile(path)
    return A, level


def load(image, app_dir, start=False):
    """無頭載入主程式;APP_DIR 指到暫存資料夾(佈局檔複製過去),校正檔也寫在那裡。"""
    code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
    g = {"__name__": "__main__", "__file__": PROG}
    exec(compile(code, PROG, "exec"), g)
    g["APP_DIR"] = app_dir
    g["ROI_DIR"] = os.path.join(app_dir, "ROI_layouts")
    g["CAMERA_TYPE"] = "IMAGE"
    assert g["load_image_file"](image)
    g["_publish_frame"](g["source_image_gray"])
    if start:
        g["init_layout_rois"]()                        # = start_system 開程式時做的事
    return g


def click_wells(g, A, names):
    g["toggle_cad_align"]()
    assert g["cad_mode"]
    for n in names:
        w = next(x for x in WELLS if x["name"] == n)
        x, y = A @ [w["x_mm"], w["y_mm"], 1]
        g["cad_click"](x + g["img_pad_x"], y + g["img_pad_y"])


def center_error(g, A):
    err = []
    for r, w in zip(g["rois"], WELLS):
        tx, ty = A @ [w["x_mm"], w["y_mm"], 1]
        if r[0] == "rect":
            cx, cy = (r[1] + r[3]) / 2, (r[2] + r[4]) / 2
        else:
            cx, cy = r[1], r[2]
        err.append(np.hypot(cx - g["img_pad_x"] - tx, cy - g["img_pad_y"] - ty))
    return max(err)


os.makedirs(os.path.join(HERE, "test_output"), exist_ok=True)
tmp = tempfile.mkdtemp(prefix="li_cad_")
shutil.copy(os.path.join(HERE, "slide_layout.json"), tmp)
print(f"佈局:{LAYOUT['source']},{LAYOUT['slide_w_mm']} x {LAYOUT['slide_h_mm']} mm,{len(WELLS)} 格")

# [1] RGBA PNG 讀檔
b8 = os.path.join(HERE, "..", "20261029", "test image", "Chi 20261014 B_8.png")
if os.path.exists(b8):
    gb = load(b8, tmp)
    old = cv2.imdecode(np.fromfile(b8, np.uint8), cv2.IMREAD_GRAYSCALE)
    top = np.bincount(old.ravel()).argsort()[::-1][:3].tolist()
    print(f"[1] B_8 RGBA PNG 灰階種類:舊讀法 {len(np.unique(old))}(集中在 {top}),新讀法 {len(np.unique(gb['source_image_gray']))}")
    assert len(np.unique(gb["source_image_gray"])) > len(np.unique(old))
    gb["root"].destroy()

# [2] 管理者校正
pa = os.path.join(tmp, "slide_a.png")
A_a, level_a = make_slide(pa)
g = load(pa, tmp, start=True)
print(f"[2] 開程式但尚未校正:ROI {len(g['rois'])} 個,Start {g['start_btn']['state']} → {g['layout_status'].cget('text').splitlines()[0][:40]}…")
assert len(g["rois"]) == 0 and str(g["start_btn"]["state"]) == "disabled"
click_wells(g, A_a, g["CAD_REFS"])
assert os.path.exists(os.path.join(tmp, "slide_calibration.json"))
e = center_error(g, A_a)
print(f"    管理者點 T1 / T8 / B1 校正後:{len(g['rois'])} 個 ROI,中心誤差最大 {e:.2f} px,已存 slide_calibration.json")
assert len(g["rois"]) == 19 and e < 1.0
g["root"].destroy()

# [3] 重開程式、載玻片放偏
pb = os.path.join(tmp, "slide_b.png")
A_b, level_b = make_slide(pb, shift=(12, -7))
g = load(pb, tmp, start=True)
e = center_error(g, A_b)
status = g["layout_status"].cget("text").replace("\n", " | ")
print(f"[3] 重開程式、載玻片偏 (+12, −7) px,不點任何東西:{len(g['rois'])} 個 ROI,中心誤差最大 {e:.2f} px")
print(f"    狀態:{status}")
assert len(g["rois"]) == 19 and e < 1.0 and str(g["start_btn"]["state"]) == "normal"
gray_level = lambda v: 0.299 * (v // 5) + 0.587 * v + 0.114 * (v // 4)
dev = max(abs(g["get_roi_patch"](g["current_frame"], r)[0].mean() - gray_level(level_b[w["name"]]))
          for r, w in zip(g["rois"], WELLS))
print(f"    每個 ROI 量到的亮度與該格亮度最大差 {dev:.2f} 灰階")
ov = cv2.cvtColor(g["current_frame"], cv2.COLOR_GRAY2BGR)
for r, w in zip(g["rois"], WELLS):
    cv2.rectangle(ov, (r[1], r[2]), (r[3], r[4]), (0, 215, 255), 1)
    cv2.putText(ov, w["name"], (r[1], r[2] - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
y0, x0 = g["img_pad_y"], g["img_pad_x"]
cv2.imwrite(os.path.join(HERE, "test_output", "test_layout_overlay.png"), ov[y0:y0 + g["img_disp_h"], x0:x0 + g["img_disp_w"]])

# [4] 只能整組調大小 / 形狀;不能手動框 / 拖曳
ppm = 12.0
g["roi_fill_var"].set(60); g["apply_layout_rois"]()
sizes = {(r[3] - r[1], r[4] - r[2]) for r in g["rois"]}
g["rb_circle_ui"].invoke()
shapes = {r[0] for r in g["rois"]}
radii = {r[3] for r in g["rois"]}
print(f"[4] 大小 60% → 19 個方形都是 {sizes}(≈ 0.6 × 3 mm × {ppm:.0f} px/mm = 22 px);"
      f"切換圓形 → 形狀 {shapes},半徑 {radii}")
assert len(sizes) == 1 and all(abs(a - 22) <= 1 and abs(b - 22) <= 1 for a, b in sizes)
assert shapes == {"circle"} and len(radii) == 1 and all(abs(r - 11) <= 1 for r in radii) and center_error(g, A_b) < 1.0
before = list(g["rois"])
class Ev:
    def __init__(s, x, y): s.x, s.y = x, y
g["on_mouse_down"](Ev(100, 100)); g["on_mouse_move"](Ev(160, 160)); g["on_mouse_up"](Ev(160, 160))
r0 = before[0]
g["on_right_mouse_down"](Ev(r0[1], r0[2])); g["on_right_mouse_move"](Ev(r0[1] + 40, r0[2] + 20)); g["on_right_mouse_up"](None)
assert g["rois"] == before
print("    在影像上左鍵框選、右鍵拖曳 → ROI 都沒有變 ✓")

# [5] 重新量測後 ROI 保留
g["start_btn"].invoke()
assert g["analyzing"]
g["root"].after(800, g["root"].quit); g["root"].mainloop()
g["start_btn"].invoke(); g["start_btn"].invoke()          # 停止 → 重新量測
assert g["rois"] == before and str(g["start_btn"]["state"]) == "normal"
print("[5] 量測 → 停止 → 重新量測:19 個 ROI 保留,可直接再開始 ✓")
g["root"].destroy()

# [6] 鏡像 + 旋轉的相機;點錯格會警告
pc = os.path.join(tmp, "cam2", "slide_c.png"); os.makedirs(os.path.dirname(pc))
shutil.copy(os.path.join(HERE, "slide_layout.json"), os.path.dirname(pc))
A_c, _ = make_slide(pc, px_per_mm=11.0, angle_deg=-3.0, mirror=True)
g = load(pc, os.path.dirname(pc))
g["rb_circle_ui"].invoke()
click_wells(g, A_c, g["CAD_REFS"])
e = center_error(g, A_c)
ASKS.clear()
click_wells(g, A_c, ("T1", "T7", "B1"))
warn = [l for l in ASKS[-1][1].splitlines() if l.startswith("⚠")] if ASKS else []
print(f"[6] 11 px/mm、旋轉 −3°、左右鏡像:中心誤差最大 {e:.2f} px;T8 誤點成 T7 → {warn[0] if warn else '沒有警告'}")
assert e < 1.0 and warn
g["root"].destroy()

# [7] 校正檔與相機不符 → 不放 ROI
pd = os.path.join(tmp, "slide_d.png")
make_slide(pd, size=(1000, 450))
g = load(pd, tmp, start=True)                          # tmp 裡的校正檔是 1024x460 影像做的
print(f"[7] 解析度不同的影像:ROI {len(g['rois'])} 個 → {g['layout_status'].cget('text').splitlines()[0][:45]}…")
assert len(g["rois"]) == 0
g["root"].destroy()
print("\n全部測試通過,已輸出 test_output/test_layout_overlay.png")
