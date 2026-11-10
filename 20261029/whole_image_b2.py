# -*- coding: utf-8 -*-
"""
測試:IMG_0779 整張影像做 B2(B 方案做 2 次:inpaint 補紅點 → 連光暈 FILL_GROW_PX 一起再補一次)

程式平常只修整 ROI;這裡把「整張影像有效區」當成一個大 ROI,其餘流程與參數和程式完全相同
(White Top-hat kernel=DEGLINT_KERNEL、門檻 median + K·1.4826·MAD、B2 擴 FILL_GROW_PX)。
解析度 = 程式量測用的顯示座標(IMG_0779 1045x1567 → 613x920)。

用法:python whole_image_b2.py [K]   (K 預設 12;程式的 ROI 預設 K=4 用在整張圖會把樣本輪廓也抹掉)
      整張圖大多是暗而平的背景,門檻(median + K·MAD)被壓得很低,所以整張處理時 K 要調大
輸出:img0779_whole_B2_K<K>.png        原圖 / 標紅 / B2 三張並排(對比 x3)
      img0779_whole_B2_only_K<K>.png   只有 B2 結果(613x920,未做對比調整)
"""
import os, sys
import numpy as np
import cv2
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261029.py")
for _n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _n, lambda *a, **k: None)

code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
g = {"__name__": "__main__", "__file__": PROG}
exec(compile(code, PROG, "exec"), g)
g["CAMERA_TYPE"] = "IMAGE"
assert g["load_image_file"](os.path.join(HERE, "IMG_0779.jpg"))
g["_publish_frame"](g["source_image_gray"])
gray = g["current_frame"].copy()
K = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
g["DEGLINT_K"] = K
px, py, W, H = g["img_pad_x"], g["img_pad_y"], g["img_disp_w"], g["img_disp_h"]

whole = ("rect", px, py, px + W, py + H)                     # 整張影像有效區 = 一個大 ROI
patch, cmask, rej, pct, mb, ma = g["deglint_roi_stats"](gray, whole)
b1 = g["fill_glint"](patch, rej, "inpaint")
b2 = g["fill_glint"](patch, rej, "inpaint2")
changed = b2 != patch
print(f"IMG_0779 整張 {W}x{H}(kernel={g['DEGLINT_KERNEL']}, K={g['DEGLINT_K']:.0f}, 擴 {g['FILL_GROW_PX']} px)")
print(f"  標紅 {int(rej.sum())} px ({pct:.2f}%);B2 共修改 {int(changed.sum())} px ({100 * changed.mean():.1f}%)")
print(f"  整張平均 {patch.mean():.2f} → B {b1.mean():.2f} → B2 {b2.mean():.2f};最大值 {patch.max()} → {b2.max()}")

tag = f"K{K:g}"
cv2.imwrite(os.path.join(HERE, f"img0779_whole_B2_only_{tag}.png"), b2)

# 並排(對比 x3 才看得到暗處的灰塵)
lo = np.percentile(patch, 1)
st = lambda im: cv2.cvtColor(np.clip((im.astype(np.float32) - lo) * 3, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
mk = st(patch); mk[rej] = (0, 0, 255)
panels = []
for im, t in ((st(patch), "Original (contrast x3)"), (mk, f"Marked {pct:.1f}%"), (st(b2), "B2 whole image")):
    bar = np.full((30, im.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, t, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    panels += [np.vstack([bar, im]), np.full((im.shape[0] + 30, 10, 3), 60, np.uint8)]
cv2.imwrite(os.path.join(HERE, f"img0779_whole_B2_{tag}.png"), np.hstack(panels[:-1]))
g["root"].destroy()
print(f"已輸出 img0779_whole_B2_{tag}.png / img0779_whole_B2_only_{tag}.png")
