# -*- coding: utf-8 -*-
"""
20261022 測試:固定 ROI + 只對 ROI 去反光(White Top-hat)

用法(在 light_intensity conda 環境):
    python test_20261022.py

測試影像:messageImage_1792573760104.jpg(6 個淡綠色圓形樣本 + 大量亮點灰塵)
輸出:
    deglint_compare.png   舊版(整張圖)vs 新版(只處理 ROI)去反光對照圖
    deglint_compare.csv   每個樣本的去除比例、平均值、標準差
    終端機印出固定 ROI 行為檢查與量測流程結果(全部 assert,失敗會直接報錯)
"""
import os, sys, time, csv, json, tempfile, threading, collections
import numpy as np
import cv2
import tkinter as tk
from tkinter import messagebox, filedialog

HERE  = os.path.dirname(os.path.abspath(__file__))
PROG  = os.path.join(HERE, "20261022.py")
IMAGE = os.path.join(HERE, "messageImage_1792573760104.jpg")

# 這張圖 6 個樣本的中心(原圖像素座標;去亮點 + 模糊後取質心量得)
CENTERS = [(134, 89), (263, 94), (386, 91), (513, 101), (638, 92), (764, 96)]
ROI_SIZE = 60            # 方形 ROI 邊長(樣本直徑約 100 px,取中心 60x60 不碰邊)

# ── 無頭載入主程式:對話框一律自動回答,不跑 mainloop、不跳相機選擇 ────────────
MSGS, DLG = [], collections.deque()
messagebox.askokcancel = lambda *a, **k: True
messagebox.askyesno    = lambda *a, **k: False
for _n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _n, lambda *a, **k: MSGS.append(a))
filedialog.asksaveasfilename = lambda **k: DLG.popleft()
filedialog.askopenfilename   = lambda **k: DLG.popleft()


def load_program(roi_dir):
    code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0]
    code = code.replace("root.after(100, start_system)", "pass")
    g = {"__name__": "__main__", "__file__": PROG}
    exec(compile(code, PROG, "exec"), g)
    g["ROI_DIR"] = roi_dir                 # 測試用暫存資料夾,不動到真正的 ROI_layouts
    g["CAMERA_TYPE"] = "IMAGE"
    assert g["load_image_file"](IMAGE)
    g["setup_ui_for_image_mode"]()
    return g


def pump(root, sec):
    t = time.time()
    while time.time() - t < sec:
        root.update(); time.sleep(0.01)


def old_whole_image_glint(gray, K, kernel):
    """舊版(20261006):整張影像 top-hat,門檻用整張影像統計。"""
    k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k).astype(np.float32)
    return th > (th.mean() + K * th.std())


# ══════════════════════════════════════════════════════════════════════════════
tmp = tempfile.mkdtemp(prefix="li_test_")
g = load_program(os.path.join(tmp, "ROI_layouts"))
root = g["root"]
threading.Thread(target=g["video_loop_image"], daemon=True).start()
pump(root, 0.3)

px, py = g["img_pad_x"], g["img_pad_y"]            # 原圖 → 顯示座標的位移(此圖不縮放)
assert (g["img_disp_w"], g["img_disp_h"]) == (g["orig_w"], g["orig_h"]), "測試假設此圖不縮放"
h = ROI_SIZE // 2
fixed = [("rect", cx - h + px, cy - h + py, cx + h + px, cy + h + py) for cx, cy in CENTERS]

# ── 1. 去反光:舊版整張圖 vs 新版只處理 ROI ──────────────────────────────────
with g["frame_lock"]:
    frame = g["current_frame"].copy()
K, KER = g["DEGLINT_K"], g["DEGLINT_KERNEL"]
OLD_K = 3.0                                  # 舊版(20261006)的預設 K
t0 = time.perf_counter(); old_mask = old_whole_image_glint(frame, OLD_K, KER); t_old = time.perf_counter() - t0
# 參考值:大範圍 median 把亮點完全抹掉後的 ROI 平均,當作「沒有灰塵時」的大概水準
ref_img = cv2.medianBlur(frame, 11)
rows = []
t_new = 0.0
for i, r in enumerate(fixed):
    patch, _ = g["get_roi_patch"](frame, r)
    y1, y2, x1, x2 = g["_roi_slice"](frame.shape, r)
    old = old_mask[y1:y2, x1:x2]
    t0 = time.perf_counter(); new = g["_roi_glint"](frame, r); t_new += time.perf_counter() - t0
    p = patch.astype(np.float64)
    rows.append({
        "sample": i + 1, "ref_mean": float(ref_img[y1:y2, x1:x2].mean()),
        "raw_mean": p.mean(), "raw_std": p.std(), "raw_max": int(patch.max()),
        "old_removed_%": 100 * old.mean(), "old_mean": p[~old].mean(), "old_std": p[~old].std(),
        "new_removed_%": 100 * new.mean(), "new_mean": p[~new].mean(), "new_std": p[~new].std(),
        "new_max_kept": int(patch[~new].max()),
    })

print("\n[1] 去反光比較(kernel=%d, ROI %dx%d;舊 = 整張圖 mean+%.0f·std,新 = 各 ROI median+%.0f·1.4826·MAD)"
      % (KER, ROI_SIZE, ROI_SIZE, OLD_K, K))
print(" S | 參考值 | 原始 mean/std/max   | 舊:整張圖 去除% mean / std | 新:只處理ROI 去除% mean / std | 新:保留的最大值")
for r in rows:
    print(f" {r['sample']} | {r['ref_mean']:6.2f} | {r['raw_mean']:6.2f} {r['raw_std']:6.2f} {r['raw_max']:4d} |"
          f"   {r['old_removed_%']:5.2f}%  {r['old_mean']:6.2f} {r['old_std']:6.2f}  |"
          f"   {r['new_removed_%']:5.2f}%  {r['new_mean']:6.2f} {r['new_std']:6.2f}  | {r['new_max_kept']:4d}")
err = lambda key: np.mean([abs(r[key] - r["ref_mean"]) for r in rows])
print(f" 與參考值的平均誤差:原始 {err('raw_mean'):.2f} / 舊 {err('old_mean'):.2f} / 新 {err('new_mean'):.2f} 灰階")
assert max(r["new_max_kept"] for r in rows) < 60, "新版不應保留明顯的灰塵亮點"
print(f" 運算時間:舊(整張 {frame.shape[1]}x{frame.shape[0]}){t_old*1000:.2f} ms / 新(6 個 ROI){t_new*1000:.2f} ms")

with open(os.path.join(HERE, "deglint_compare.csv"), "w", newline="", encoding="utf-8") as fp:
    w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
    w.writeheader()
    for r in rows:
        w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})

# 對照圖:上 = 原圖(對比拉伸)+ ROI,中 = 舊版標紅,下 = 新版標紅(只在 ROI 內)
sub = frame[py:py + g["img_disp_h"], px:px + g["img_disp_w"]]
lo, hi = np.percentile(sub, 1), np.percentile(sub, 99.5)
base = np.clip((sub.astype(np.float32) - lo) * 255 / max(1, hi - lo), 0, 255).astype(np.uint8)
base = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
old_v, new_v, top = base.copy(), base.copy(), base.copy()
old_v[old_mask[py:py + g["img_disp_h"], px:px + g["img_disp_w"]]] = (0, 0, 255)
for i, r in enumerate(fixed):
    _, x1, y1, x2, y2 = [r[0]] + [v - (px if k % 2 == 0 else py) for k, v in enumerate(r[1:])]
    new = g["_roi_glint"](frame, r)
    new_v[y1:y2, x1:x2][new] = (0, 0, 255)
    for im in (top, old_v, new_v):
        cv2.rectangle(im, (x1, y1), (x2, y2), (0, 215, 255), 1)
    cv2.putText(top, f"S{i+1}", (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 215, 255), 1)
    cv2.putText(new_v, f"{rows[i]['new_removed_%']:.1f}%", (x1, y2 + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

def titled(im, text):
    bar = np.full((24, im.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, text, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return np.vstack([bar, im])

out = np.vstack([titled(top, "Original (contrast stretched) + fixed ROIs"),
                 titled(old_v, "OLD: whole-image top-hat, mean+3std (red = removed, everywhere)"),
                 titled(new_v, "NEW: top-hat per ROI only, median+%.0f*1.4826*MAD (red = removed, %% per sample)" % K)])
cv2.imwrite(os.path.join(HERE, "deglint_compare.png"), cv2.resize(out, None, fx=1.5, fy=1.5,
                                                                  interpolation=cv2.INTER_NEAREST))
print(" 已輸出 deglint_compare.png / deglint_compare.csv")

# ── 2. 固定 ROI 行為 ─────────────────────────────────────────────────────────
print("\n[2] 固定 ROI")
g["_set_rois"](fixed)
g["set_fixed_roi"]()
fixed_path = os.path.join(g["ROI_DIR"], g["ROI_FIXED"])
assert g["roi_fixed"] and os.path.exists(fixed_path)
print(" 設為固定 ROI -> 已存檔並鎖定:", os.path.basename(fixed_path))

class Ev:                                    # 模擬滑鼠事件
    def __init__(s, x, y): s.x, s.y = x, y

before = list(g["rois"])
g["on_mouse_down"](Ev(px + 40, py + 160)); g["on_mouse_up"](Ev(px + 40, py + 160))   # 左鍵新增
g["on_right_mouse_down"](Ev(fixed[0][1] + 5, fixed[0][2] + 5))                       # 右鍵拖曳
g["on_right_mouse_move"](Ev(fixed[0][1] + 60, fixed[0][2] + 40)); g["on_right_mouse_up"](None)
g["on_default"](); g["auto_detect_rois"](); g["load_roi_layout"]()
assert g["rois"] == before, "固定 ROI 被改動了"
print(" 鎖定中:左鍵新增 / 右鍵拖曳 / 清除 / 自動放置 / 載入 都被擋下,ROI 不變 ✓")
assert str(g["auto_roi_btn"]["state"]) == "disabled" and str(g["roi_load_btn"]["state"]) == "disabled"

# 解鎖後可以拖曳,重新勾選會回到固定座標
g["roi_fixed_var"].set(False); g["toggle_fixed_roi"]()
g["on_right_mouse_down"](Ev(fixed[0][1] + 5, fixed[0][2] + 5))
g["on_right_mouse_move"](Ev(fixed[0][1] + 25, fixed[0][2] + 5)); g["on_right_mouse_up"](None)
assert g["rois"][0] != fixed[0], "解鎖後應可拖曳"
g["roi_fixed_var"].set(True); g["toggle_fixed_roi"]()
assert g["rois"] == fixed and g["roi_fixed"]
print(" 取消勾選可拖曳調整;重新勾選回到固定座標 ✓")

# ── 3. 量測流程 + 重新量測保留固定 ROI ──────────────────────────────────────
print("\n[3] 量測流程(De-glint ON)")
g["deglint_enable_var"].set(True); g["toggle_deglint"]()
pump(root, 0.3)
for w in root.winfo_children():                # 關掉啟用去反光時自動跳出的預覽視窗
    if isinstance(w, tk.Toplevel) and w is not g["adv_win"]:
        w.destroy()
g["start_btn"].invoke()
assert g["analyzing"]
root.after(3500, root.quit); root.mainloop()     # 分析執行緒的 root.after 需要主迴圈在跑
g["start_btn"].invoke()                        # 停止
pump(root, 0.3)
DLG.append(os.path.join(tmp, "run.csv")); g["save_btn"].invoke()
data = list(csv.reader(open(os.path.join(tmp, "run.csv"), encoding="utf-8")))
means = [float(v) for v in [r for r in data if r[0].startswith("Mean")][0][1:]]
preview = [round(g["deglint_roi_stats"](frame, r)[5], 2) for r in fixed]
print(" CSV Mean    :", means)
print(" 預覽算的平均:", preview)
assert np.allclose(means, preview, atol=0.011), "CSV 平均值應等於預覽的去除後平均"
assert data[1][0].endswith("De-glint: ON (K=%.1f)" % K)
print(" CSV 與預覽一致 ✓")

g["start_btn"].invoke()                        # 重新量測
assert g["rois"] == fixed and g["roi_fixed"], "重新量測後固定 ROI 應保留"
assert str(g["start_btn"]["state"]) == "normal", "固定 ROI 時重新量測後應可直接開始"
print(" 重新量測:固定 ROI 保留,可直接再按開始 ✓")
root.destroy()

# ── 4. 重開程式自動載入固定 ROI ──────────────────────────────────────────────
print("\n[4] 重開程式")
g2 = load_program(os.path.join(tmp, "ROI_layouts"))
g2["load_fixed_roi"](silent=True); g2["_set_fixed_lock"](g2["roi_fixed"])   # = start_system 的啟動流程
assert g2["rois"] == fixed and g2["roi_fixed"]
print(" 自動載入 ROI_fixed.json 並鎖定 ✓", g2["roi_fixed_status"].cget("text").splitlines()[0])
g2["root"].destroy()
print("\n全部測試通過")
