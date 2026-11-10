# -*- coding: utf-8 -*-
"""
線性圖:濃度 0 進擬合、blank 不參與統計(用法:light_intensity 環境 python test_chart_zero.py)
B-2(l) 的實驗組平均值:S1 1e-13, S2 1e-11, S3 1e-9, S4 blank, S5 0, S6 1e-10
[1] 濃度對話框:blank(S4)預設勾「不參與統計」;自訂濃度 → S4 = nan、S5 = 0
[2] 線性 X:擬合用 5 點(含 0 M),R² 與 numpy 一致;圖上列出 S4 不參與
[3] log X:0 M 畫虛線、擬合 4 點;[4] 對半稀釋跳過 S4,最後一個參與的樣本 = 0
"""
import os, tempfile
import numpy as np
import tkinter as tk
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261029.py")
for n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, n, lambda *a, **k: None)
code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
g = {"__name__": "__main__", "__file__": PROG}
exec(compile(code, PROG, "exec"), g)
root = g["root"]
figs = []
Fig = g["Figure"]
g["Figure"] = lambda *a, **k: figs.append(Fig(*a, **k)) or figs[-1]

means = [21.223, 25.080, 30.880, 15.437, 18.517, 28.216]
conc = [1e-13, 1e-11, 1e-9, None, 0.0, 1e-10]
g["blank_idx"] = 3


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def dialog(mode, log=False, c0=None):
    def go():
        win = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        ws = list(walk(win))
        chk = [w for w in ws if isinstance(w, tk.Checkbutton) and w.cget("text").startswith("S")]
        assert chk[3].cget("text") == "S4 (blank)"
        assert [bool(int(win.getvar(c.cget("variable")))) for c in chk] == [False, False, False, True, False, False]
        next(w for w in ws if isinstance(w, tk.Radiobutton) and w.cget("value") == mode).invoke()
        ents = [w for w in ws if isinstance(w, tk.Entry) and not isinstance(w, tk.ttk.Combobox)]
        cbs = [w for w in ws if isinstance(w, tk.ttk.Combobox)]
        if mode == "custom":
            for i, c in enumerate(conc):
                if c is not None:
                    ents[1 + i].insert(0, "1" if c else "0")
                    cbs[1 + i].set(str(int(round(np.log10(c)))) if c else "-9")
        else:
            ents[0].insert(0, c0); cbs[0].set("-9")
        if log:
            next(w for w in ws if isinstance(w, tk.Checkbutton) and "log" in w.cget("text")).invoke()
        next(w for w in ws if isinstance(w, tk.Button) and "OK" in w.cget("text")).invoke()
    root.after(300, go)
    return g["_ask_concentrations"](len(means))


def texts(fig):
    return " | ".join(t.get_text() for t in fig.axes[0].texts)


csv = os.path.join(tempfile.mkdtemp(), "t.csv")
# [1]
concs, mode, log_x, excl = dialog("custom")
assert excl == {3} and np.isnan(concs[3]) and concs[4] == 0.0 and abs(concs[2] - 1e-9) < 1e-20
print("[1] 濃度:", concs, " 不參與:", excl)

# [2]
g["_make_linearity_chart"](means, csv, concs, mode, log_x, excl)
x = np.array([c for i, c in enumerate(concs) if i != 3]); y = np.array([m for i, m in enumerate(means) if i != 3])
a, b = np.polyfit(x, y, 1); r2 = 1 - ((y - (a * x + b)) ** 2).sum() / ((y - y.mean()) ** 2).sum()
t = texts(figs[-1])
print("[2] 線性:", t)
assert f"R² = {r2:.4f}  (n=5)" in t and "S4 (blank) = 15.44" in t

# [3]
concs, mode, log_x, excl = dialog("custom", log=True)
g["_make_linearity_chart"](means, csv, concs, mode, log_x, excl)
t = texts(figs[-1])
lx = np.log10([1e-13, 1e-11, 1e-9, 1e-10]); ly = np.array([21.223, 25.080, 30.880, 28.216])
a, b = np.polyfit(lx, ly, 1); r2 = 1 - ((ly - (a * lx + b)) ** 2).sum() / ((ly - ly.mean()) ** 2).sum()
labels = figs[-1].axes[0].get_legend_handles_labels()[1]
print("[3] log:", t, "| 圖例:", labels)
assert f"R² = {r2:.4f}  (log x, n=4, 0 M not on log axis)" in t and "0 M (not on log axis)" in labels \
    and "Excluded (not in fit)" in labels

# [4]
concs, mode, log_x, excl = dialog("half", c0="8")
print("[4] 對半稀釋:", concs)
assert np.isnan(concs[3]) and concs[5] == 0.0 and abs(concs[0] - 8e-9) < 1e-20 and abs(concs[4] - 1e-9) < 1e-20
root.destroy()
print("\n全部通過")
