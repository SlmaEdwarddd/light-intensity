# -*- coding: utf-8 -*-
"""
背景排除區測試(用法:light_intensity 環境 python test_bg_exclude.py)
B-2(l):只框 1e-13 / 1e-11 / 1e-9 / 1e-10 四個樣本,blank 和 0 不框
[1] 不畫排除區:沒框的 blank、0 被當成背景
[2] 用滑鼠事件畫兩個排除區蓋住它們 → 背景點不落在框內,增益改變
[3] 存 ROI 檔 → 清除 → 載入,排除區跟著回來;Restart(on_default)會清掉
"""
import os, json, tempfile
import numpy as np
from tkinter import messagebox, filedialog

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261029.py")
for n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, n, lambda *a, **k: None)
messagebox.askokcancel = lambda *a, **k: True
code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
g = {"__name__": "__main__", "__file__": PROG}
exec(compile(code, PROG, "exec"), g)
root = g["root"]
g["CAMERA_TYPE"] = "IMAGE"
assert g["load_image_file"](os.path.join(HERE, "test image", "Chi 20261014 B_2 (l).jpg"))
gray = g["source_image_gray"]
g["_publish_frame"](gray); gray = g["current_frame"]
x0, y0, W, H = g["img_pad_x"], g["img_pad_y"], g["img_disp_w"], g["img_disp_h"]
s = W / g["orig_w"]
guess = [62, 160, 255, 355, 462, 555]                  # 1e-13, 1e-11, 1e-9, blank, 0, 1e-10(原圖座標,同 lod_analysis)
cy, r = int(y0 + 70 * s), int(24 * s)
X = [int(x0 + gx * s) for gx in guess]
g["_set_rois"]([("circle", X[i], cy, r) for i in (0, 1, 2, 5)])
g["illum_mode"] = "background"


class Ev:
    def __init__(self, x, y): self.x, self.y = x, y


def run():
    gain, pts, msg = g["build_illum_correction"](gray, g["rois"], "background")
    return g["roi_gain_factors"](gain, g["rois"]), pts, msg


def in_rects(pts):
    ys, xs = pts
    return sum(int(((xs >= a) & (xs < c) & (ys >= b) & (ys < d)).sum()) for a, b, c, d in g["bg_excl_rects"])


f0, p0, _ = run()
half = int(45 * s)
rects = [(X[i] - half, y0 + 1, X[i] + half, y0 + H - 2) for i in (3, 4)]   # 蓋住 blank、0
g["bg_excl_rects"][:] = rects
n_before = in_rects(p0)
g["bg_excl_rects"].clear()

# [2] 用滑鼠畫(模擬按下 → 拖曳 → 放開)
g["toggle_bg_excl_mode"]()
for a, b, c, d in rects:
    g["on_mouse_down"](Ev(a, b)); g["on_mouse_move"](Ev(c, d)); g["on_mouse_up"](Ev(c, d))
g["toggle_bg_excl_mode"]()
assert len(g["bg_excl_rects"]) == 2 and len(g["rois"]) == 4, "排除區模式不應新增 ROI"
f1, p1, msg = run()
print("[1] 不畫排除區:落在 blank/0 位置的背景點", n_before, "個;增益", [round(v, 3) for v in f0])
print("[2] 畫排除區後:落在框內的背景點", in_rects(p1), "個;增益", [round(v, 3) for v in f1])
print("   ", msg)
assert n_before > 0 and in_rects(p1) == 0 and "2 exclude" in msg
g["show_illum_preview"](); g["update_display"]()          # 預覽、主畫面畫紫框不出錯

# [3] 存檔 / 載入
path = os.path.join(tempfile.mkdtemp(), "roi.json")
assert g["save_roi_layout"](silent=True, path=path)
assert len(json.load(open(path, encoding="utf-8"))["exclude"]) == 2
saved = list(g["bg_excl_rects"])
g["clear_bg_excl"](); assert not g["bg_excl_rects"]
filedialog.askopenfilename = lambda **k: path
g["load_roi_layout"]()
assert g["bg_excl_rects"] == saved, (g["bg_excl_rects"], saved)
g["on_default"](); assert not g["bg_excl_rects"]
print("[3] 存檔 / 載入 / Restart 清除 OK")
root.destroy()
print("\n全部通過")
