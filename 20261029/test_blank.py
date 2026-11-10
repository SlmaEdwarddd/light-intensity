# -*- coding: utf-8 -*-
"""
Blank 扣除測試(用法:light_intensity 環境 python test_blank.py)
[1] 按「擷取平場」→ 對話框選 S3 是 blank(真的點對話框的按鈕)
[2] 模擬 20 秒量測資料 → 存 CSV:每個樣本扣掉 blank 的平均(t>10s),blank 欄平均 0、標準差不變
[3] 換 ROI(載入 / 清除)後 blank 自動取消;對話框選「空白玻片」仍走原本的平場流程
"""
import os, csv, tempfile
import numpy as np
import tkinter as tk
from tkinter import messagebox, filedialog

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261029.py")
for n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, n, lambda *a, **k: None)
messagebox.askyesno = lambda *a, **k: False                       # 存 CSV 後不畫圖
asked = []
messagebox.askokcancel = lambda *a, **k: asked.append(a[0]) or False
code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
g = {"__name__": "__main__", "__file__": PROG}
exec(compile(code, PROG, "exec"), g)
root = g["root"]
g["CAMERA_TYPE"] = "IMAGE"
img = os.path.join(HERE, "test image", "Chi 20261014 B_8.png")
assert g["load_image_file"](img)
g["_publish_frame"](g["source_image_gray"])
x0, y0 = g["img_pad_x"], g["img_pad_y"]
g["_set_rois"]([("circle", x0 + 90 + 126 * i, y0 + 95, 23) for i in range(6)])


def click_dialog(label):
    """對話框出現後,點選文字含 label 的選項再按確定。"""
    def walk(w):
        yield w
        for c in w.winfo_children():
            yield from walk(c)
    def go():
        win = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        ws = list(walk(win))
        next(w for w in ws if isinstance(w, tk.Radiobutton) and label in w.cget("text")).invoke()
        next(w for w in ws if isinstance(w, tk.Button) and "OK" in w.cget("text")).invoke()
    root.after(300, go)


# [1]
click_dialog("S3 是 blank")
g["capture_flat_field"]()
assert g["blank_idx"] == 2, g["blank_idx"]
print("[1] 對話框選 S3 → blank_idx =", g["blank_idx"], "| 狀態:", g["illum_status"].cget("text").splitlines()[-1])
g["update_display"]()                                              # 主畫面標 BLANK 不出錯

# [2]
rng = np.random.default_rng(0)
levels = [6.0, 6.3, 7.7, 9.7, 11.0, 12.0]
g["timestamps"][:] = list(range(21))
g["roi_data"][:] = [[round(float(L + rng.normal(0, 0.1)), 2) for _ in range(21)] for L in levels]
g["decimal_places"] = 2
raw = [np.array(v) for v in g["roi_data"]]
out = os.path.join(tempfile.mkdtemp(), "blank_test.csv")
filedialog.asksaveasfilename = lambda **k: out
g["save_csv"]()
rows = list(csv.reader(open(out, encoding="utf-8")))
hdr = rows[0]
get = lambda name: next(r for r in rows if r[0].startswith(name))
mean = [float(v) for v in get("Mean")[1:]]
std = [float(v) for v in get("Std Dev")[1:]]
bm = raw[2][11:].mean()
print("[2] 欄名:", hdr[1:])
print("    ", get("Blank subtraction")[0])
print("    扣除後 Mean:", mean)
print("    原始 Mean  :", get("Raw Mean")[1:])
assert hdr[3] == "Sample 3 (blank)"
assert abs(mean[2]) < 0.01, "blank 扣完應為 0"
for i in range(6):
    assert abs(mean[i] - (raw[i][11:].mean() - bm)) < 0.01
    assert abs(std[i] - raw[i][11:].std(ddof=1)) < 0.01, "標準差應不變"
data_rows = [r for r in rows if r[0].isdigit()]
assert abs(float(data_rows[0][2]) - (raw[1][0] - bm)) < 0.011, "時間序列也要扣除"
print("    blank 欄平均 0、各欄標準差不變、時間序列已扣除 OK")

# [3]
g["_set_rois"](list(g["rois"]))
assert g["blank_idx"] is None
print("[3] 換 ROI 後 blank 自動取消 OK")
click_dialog("空白玻片")
g["capture_flat_field"]()
assert g["blank_idx"] is None and asked and "flat" in asked[-1].lower()
print("    選「空白玻片」→ 走原本的擷取平場確認(", asked[-1], ")OK")
root.destroy()
print("\n全部通過")
