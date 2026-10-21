# =============================================================================
#  圓形樣品 Auto ROI 逐步視覺化 / Circular-Sample Auto-ROI Step Visualizer
#
#  針對螢光影像（暗背景 + 亮圓點樣品）設計。
#  Designed for fluorescence images: dark background, bright circular wells.
#
#  流程 / Pipeline:
#    綠通道 -> 對比拉伸 -> 模糊 -> 門檻 -> 形態學 -> 連通元件
#    -> 面積/圓形度過濾 -> 圓偵測 -> 網格擬合補回漏掉的 -> 量測
#
#  使用方式 / Usage:
#    python autoroi_circle_steps.py
#    python autoroi_circle_steps.py <image_path>
# =============================================================================

import os
import sys
import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ── 全域 ──────────────────────────────────────────────────────────────────────
src_color  = None
src_gray   = None
image_path = None
steps      = []
cur_step   = 0
final_rois = []      # [(cx, cy, r), ...]
hist_data  = None

PARAM = dict(
    channel='G',
    blur=5,
    thr=12,          # 螢光影像門檻很低！Fluorescence needs a LOW threshold
    auto_thr=True,   # 用 Otsu 自動決定
    open_k=5,
    close_k=9,
    min_area=150,
    min_circ=0.55,
    min_r=8,
    uniform_r=True,  # 所有 ROI 用同一半徑（公平比較）
    grid_fill=True,  # 用網格擬合補回漏掉的樣品
    rows=2,
    groups=2,        # 樣品分成幾群（中間有大間隔）
    cols_pg=6,       # 每群幾欄 / columns per group
)


# =============================================================================
#  Pipeline
# =============================================================================

def extract_channel(bgr, ch):
    if bgr.ndim == 2:
        return bgr.copy()
    b, g, r = cv2.split(bgr[:, :, :3])
    return {'B': b, 'G': g, 'R': r,
            'Gray': cv2.cvtColor(bgr[:, :, :3], cv2.COLOR_BGR2GRAY),
            'Max': np.maximum(np.maximum(b, g), r)}.get(ch, g)


def stretch(gray, lo=None, hi=None):
    """對比拉伸，只為了『看得見』，不影響量測。"""
    g = gray.astype(np.float32)
    if lo is None:
        lo = float(np.percentile(g, 50))
    if hi is None:
        hi = float(np.percentile(g, 99.9))
    if hi <= lo:
        hi = lo + 1
    return np.clip((g - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)


def gray_to_rgb(g):
    return cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)


def _cluster_by_proximity(vals, tol):
    """把 1D 值依鄰近程度分群（相差 < tol 視為同一群），回傳每群中位數。"""
    if len(vals) == 0:
        return []
    v = np.sort(np.asarray(vals, float))
    groups = [[v[0]]]
    for x in v[1:]:
        if x - groups[-1][-1] <= tol:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [float(np.median(g)) for g in groups]


def _complete_lattice(positions, want, spacing, lo, hi, score_fn):
    """
    把 positions 補成 want 個等距位置。
    1) 先補內部空缺（間距約 2x spacing 者插中點）
    2) 仍不足則往左右延伸，用 score_fn 評分挑訊號較強的一側
    """
    pos = sorted(positions)
    if spacing is None or spacing <= 1:
        return pos[:want]

    # 內部補洞
    guard = 0
    while len(pos) < want and guard < 50:
        guard += 1
        best_i, best_gap = -1, 0
        for i in range(len(pos) - 1):
            gap = pos[i + 1] - pos[i]
            if gap > spacing * 1.6 and gap > best_gap:
                best_gap, best_i = gap, i
        if best_i < 0:
            break
        n_missing = int(round(best_gap / spacing)) - 1
        if n_missing < 1:
            break
        step = best_gap / (n_missing + 1)
        for j in range(1, n_missing + 1):
            if len(pos) < want:
                pos.append(pos[best_i] + step * j)
        pos = sorted(pos)

    # 往兩側延伸
    guard = 0
    while len(pos) < want and guard < 50:
        guard += 1
        cand_l = pos[0] - spacing
        cand_r = pos[-1] + spacing
        sl = score_fn(cand_l) if cand_l >= lo else -1e9
        sr = score_fn(cand_r) if cand_r <= hi else -1e9
        if sl <= -1e8 and sr <= -1e8:
            break
        if sl >= sr:
            pos.insert(0, cand_l)
        else:
            pos.append(cand_r)
    return sorted(pos)[:want]


def fit_grid_and_fill(circles, rows, groups, cols_per_group, shape, med_r, gray=None):
    """
    從偵測到的圓擬合規則網格，補回漏掉的位置。
    - 先用鄰近分群找出實際的列 / 欄位置（不會硬切成固定數量）
    - 欄位不足時，依規則間距往內補洞、往外延伸（用局部亮度挑方向）
    - 每個偵測圓最多只配對一次，避免重複
    """
    if not circles:
        return [], [], ([], [])
    H, W = shape[:2]
    ys = [c[1] for c in circles]
    xs = [c[0] for c in circles]

    # 列：用半徑當容差分群
    row_y = _cluster_by_proximity(ys, med_r * 1.2)
    if len(row_y) > rows:                       # 群太多 → 取最密集的幾群
        row_y = sorted(row_y)[:rows]
    while len(row_y) < rows and row_y:          # 群太少 → 依列距補
        sp = (np.median(np.diff(sorted(row_y)))
              if len(row_y) > 1 else med_r * 3)
        row_y.append(row_y[-1] + sp)
    row_y = sorted(row_y)

    # 欄：先鄰近分群，得到實際欄位置
    col_all = _cluster_by_proximity(xs, med_r * 1.2)

    # 依大間隙切成 groups 群
    if groups > 1 and len(col_all) > 1:
        d = np.diff(col_all)
        cut_idx = np.argsort(d)[-(groups - 1):]
        cuts = sorted(int(i) for i in cut_idx)
        chunks = np.split(np.array(col_all), [c + 1 for c in cuts])
    else:
        chunks = [np.array(col_all)]

    def local_score(cx):
        """候選欄位的局部亮度（用來決定往哪邊延伸）。"""
        if gray is None:
            return 0.0
        x1 = int(max(0, cx - med_r)); x2 = int(min(W, cx + med_r))
        if x2 <= x1:
            return -1e9
        return float(gray[:, x1:x2].mean())

    col_x = []
    for chunk in chunks:
        ch = sorted(float(v) for v in chunk)
        if not ch:
            continue
        sp = float(np.median(np.diff(ch))) if len(ch) > 1 else med_r * 2.4
        ch = _complete_lattice(ch, cols_per_group, sp, 0, W - 1, local_score)
        col_x.extend(ch)
    col_x = sorted(col_x)

    # 配對：每個偵測圓只能用一次
    used = set()
    filled, added = [], []
    for cy in row_y:
        for cx in col_x:
            best, bd, bi = None, 1e9, -1
            for i, (dx, dy, dr) in enumerate(circles):
                if i in used:
                    continue
                dist = ((dx - cx) ** 2 + (dy - cy) ** 2) ** 0.5
                if dist < bd:
                    bd, best, bi = dist, (dx, dy, dr), i
            if best is not None and bd < med_r * 1.3:
                used.add(bi)
                filled.append(best)
            else:
                filled.append((cx, cy, med_r))
                added.append((cx, cy, med_r))
    return filled, added, (row_y, col_x)


def run_pipeline():
    global steps, final_rois, hist_data
    steps = []
    final_rois = []

    if src_color is None:
        return

    H, W = src_color.shape[:2]
    ch = PARAM['channel']

    # ── 1. 原始 ──
    if src_color.ndim == 3:
        disp = cv2.cvtColor(src_color[:, :, :3], cv2.COLOR_BGR2RGB)
        b, g, r = cv2.split(src_color[:, :, :3])
        d = (f"原始輸入 / Original ({W}x{H})\n"
             f"通道平均 / Means:  B={b.mean():.1f}  G={g.mean():.1f}  R={r.mean():.1f}\n"
             f"螢光影像很暗，肉眼幾乎看不到內容是正常的。\n"
             f"Fluorescence images look almost black — that's expected.")
    else:
        disp = gray_to_rgb(src_color)
        d = f"灰階輸入 / Grayscale input ({W}x{H})"
    steps.append(("1. 原始輸入 / Original", disp, d))

    # ── 2. 通道分離 ──
    if src_color.ndim == 3:
        b, g, r = cv2.split(src_color[:, :, :3])
        trio = cv2.cvtColor(np.hstack([stretch(b), stretch(g), stretch(r)]),
                            cv2.COLOR_GRAY2RGB)
        for i, nm in enumerate(['B', 'G', 'R']):
            cv2.putText(trio, nm, (i * W + 10, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        steps.append(("2. 通道分離（已拉伸）/ Channel split (stretched)", trio,
                      f"三個通道都做對比拉伸後比較。\n"
                      f"All three channels, contrast-stretched for viewing.\n"
                      f"B std={b.std():.1f}  G std={g.std():.1f}  R std={r.std():.1f}\n"
                      f"→ G 通道 std 最大 = 訊號最強，所以選 G。\n"
                      f"→ G has the highest std = strongest signal."))

    gray = src_gray
    p = {q: float(np.percentile(gray, q)) for q in (50, 90, 99, 99.9)}
    hist_data = gray
    steps.append((f"3. 選定通道 {ch} / Selected channel", gray_to_rgb(gray),
                  f"min={gray.min()} max={gray.max()} mean={gray.mean():.2f} std={gray.std():.2f}\n"
                  f"p50={p[50]:.0f}  p90={p[90]:.0f}  p99={p[99]:.0f}  p99.9={p[99.9]:.0f}\n"
                  f"※ 訊號全在低灰階區！門檻要設 10~20，不是 200。\n"
                  f"※ All signal is in the LOW range — threshold ~10-20, NOT 200."))

    # ── 4. 對比拉伸（僅顯示）──
    st = stretch(gray)
    steps.append(("4. 對比拉伸（僅顯示）/ Contrast stretch (view only)", gray_to_rgb(st),
                  f"把 p50~p99.9（{p[50]:.0f}~{p[99.9]:.0f}）拉到 0~255，樣品才看得見。\n"
                  f"Stretches {p[50]:.0f}~{p[99.9]:.0f} to 0~255 so wells become visible.\n"
                  f"※ 僅影響顯示，量測仍用原始灰階。\n"
                  f"※ Display only; measurement uses original values."))

    # ── 5. 模糊 ──
    k = PARAM['blur'] | 1
    blur = cv2.GaussianBlur(gray, (k, k), 0)
    steps.append((f"5. 高斯模糊 {k}x{k} / Gaussian blur", gray_to_rgb(stretch(blur)),
                  f"抑制雜訊與灰塵單點，避免被當成樣品。\n"
                  f"Suppresses noise/dust specks so they aren't taken as wells.\n"
                  f"kernel={k}x{k}"))

    # ── 6. 門檻 ──
    if PARAM['auto_thr']:
        otsu_v, _m = cv2.threshold(blur, 0, 255,
                                   cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr = int(otsu_v)
    else:
        thr = PARAM['thr']
    mask0 = (blur > thr).astype(np.uint8) * 255
    steps.append((f"6. 門檻 thr={thr} / Threshold", gray_to_rgb(mask0),
                  f"{'Otsu 自動 / auto' if PARAM['auto_thr'] else '手動 / manual'} "
                  f"門檻 = {thr}\n"
                  f"白 = 高於門檻（樣品），黑 = 背景。\n"
                  f"White = above threshold (wells), black = background.\n"
                  f"前景佔比 / Foreground: {(mask0>0).mean()*100:.2f}%"))

    # ── 7. 形態學 ──
    ok = PARAM['open_k'] | 1
    ck = PARAM['close_k'] | 1
    m1 = cv2.morphologyEx(mask0 // 255, cv2.MORPH_OPEN,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ok, ok)))
    m2 = cv2.morphologyEx(m1, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ck, ck)))
    both = np.hstack([m1 * 255, m2 * 255])
    steps.append((f"7. 形態學 open{ok} → close{ck} / Morphology",
                  gray_to_rgb(both),
                  f"左：open（去掉小雜點）  右：close（填補樣品內部破洞）\n"
                  f"Left: open (removes specks)  Right: close (fills holes)\n"
                  f"open={ok}x{ok}, close={ck}x{ck}"))

    # ── 8. 連通元件 ──
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m2, 8)
    rng = np.random.default_rng(0)
    colors = rng.integers(60, 255, size=(max(n, 1), 3))
    colors[0] = [0, 0, 0]
    lab_rgb = colors[lab].astype(np.uint8)
    steps.append((f"8. 連通元件 / Connected components ({n-1})", lab_rgb,
                  f"每個獨立區塊給一個顏色，共 {n-1} 個。\n"
                  f"Each blob gets a color; {n-1} blobs total.\n"
                  f"接下來用面積與圓形度篩選出真正的樣品。\n"
                  f"Next: filter by area and circularity."))

    # ── 9. 篩選 ──
    cnts, _h = cv2.findContours(m2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    v9 = cv2.cvtColor(stretch(gray), cv2.COLOR_GRAY2RGB)
    accepted, rejected = [], []
    for c in cnts:
        a = cv2.contourArea(c)
        (cx, cy), r = cv2.minEnclosingCircle(c)
        circ = a / (np.pi * r * r) if r > 0 else 0
        if a >= PARAM['min_area'] and circ >= PARAM['min_circ'] and r >= PARAM['min_r']:
            accepted.append((cx, cy, r, a, circ))
            cv2.circle(v9, (int(cx), int(cy)), int(r), (0, 255, 0), 2)
        else:
            rejected.append((cx, cy, r, a, circ))
            if a > 40:
                cv2.circle(v9, (int(cx), int(cy)), max(3, int(r)), (255, 60, 60), 1)
                cv2.putText(v9, f"a{a:.0f} c{circ:.2f}",
                            (int(cx) - 28, int(cy) - int(r) - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 60, 60), 1)
    steps.append((f"9. 面積/圓形度篩選 / Area & circularity filter", v9,
                  f"綠 = 通過（{len(accepted)} 個），紅 = 被剔除（標示 area/circularity）。\n"
                  f"Green = accepted ({len(accepted)}), Red = rejected.\n"
                  f"門檻 / Limits: area>={PARAM['min_area']}, "
                  f"circularity>={PARAM['min_circ']}, r>={PARAM['min_r']}\n"
                  f"被剔除的常是：氣泡、變形樣品、兩個黏在一起的。\n"
                  f"Rejects are usually bubbles, deformed or merged wells."))

    circles = [(c[0], c[1], c[2]) for c in accepted]
    med_r = float(np.median([c[2] for c in circles])) if circles else 20.0

    # ── 10. 偵測結果 ──
    v10 = cv2.cvtColor(stretch(gray), cv2.COLOR_GRAY2RGB)
    for i, (cx, cy, r) in enumerate(sorted(circles, key=lambda z: (z[1] // 40, z[0]))):
        cv2.circle(v10, (int(cx), int(cy)), int(r), (0, 255, 0), 2)
        cv2.circle(v10, (int(cx), int(cy)), 2, (0, 255, 255), -1)
    steps.append((f"10. 偵測到的圓 / Detected circles ({len(circles)})", v10,
                  f"共偵測到 {len(circles)} 個樣品，中位半徑 = {med_r:.1f} px。\n"
                  f"Detected {len(circles)} wells, median radius = {med_r:.1f} px."))

    # ── 11. 網格擬合補回漏掉的 ──
    if PARAM['grid_fill'] and circles:
        filled, added, gridlines = fit_grid_and_fill(
            circles, PARAM['rows'], PARAM['groups'], PARAM['cols_pg'],
            gray.shape, med_r, gray=blur)
        v11 = cv2.cvtColor(stretch(gray), cv2.COLOR_GRAY2RGB)
        if gridlines:
            row_y, col_x = gridlines
            for y in row_y:
                cv2.line(v11, (0, int(y)), (W, int(y)), (60, 60, 160), 1)
            for x in col_x:
                cv2.line(v11, (int(x), 0), (int(x), H), (60, 60, 160), 1)
        for (cx, cy, r) in filled:
            is_new = any(abs(cx - a[0]) < 1 and abs(cy - a[1]) < 1 for a in added)
            col = (255, 200, 0) if is_new else (0, 255, 0)
            cv2.circle(v11, (int(cx), int(cy)), int(r), col, 2)
        steps.append((f"11. 網格擬合補回 / Grid fit & fill (+{len(added)})", v11,
                      f"從偵測到的圓擬合 {PARAM['rows']} 列 x "
                      f"{PARAM['groups']}群x{PARAM['cols_pg']}欄 網格，\n"
                      f"在沒偵測到的交叉點補上（橘色）。\n"
                      f"Fits {PARAM['rows']} rows x {PARAM['groups']} groups x {PARAM['cols_pg']} cols; fills gaps (orange).\n"
                      f"綠 = 偵測到 ({len(filled)-len(added)})，"
                      f"橘 = 補回 ({len(added)})，合計 {len(filled)}。\n"
                      f"※ 補回的位置請目視確認是否合理。\n"
                      f"※ Please eyeball the filled ones — they are estimates."))
        circles = filled

    # ── 12. 統一半徑 ──
    if PARAM['uniform_r'] and circles:
        circles = [(cx, cy, med_r) for (cx, cy, _r) in circles]

    circles = sorted(circles, key=lambda z: (z[1] // 40, z[0]))
    final_rois = [(float(a), float(b), float(c)) for a, b, c in circles]

    # ── 13. 最終量測 ──
    v13 = cv2.cvtColor(stretch(gray), cv2.COLOR_GRAY2RGB)
    lines = []
    for i, (cx, cy, r) in enumerate(final_rois):
        x1 = max(0, int(cx - r)); x2 = min(W, int(cx + r))
        y1 = max(0, int(cy - r)); y2 = min(H, int(cy + r))
        if x2 <= x1 or y2 <= y1:
            continue
        patch = gray[y1:y2, x1:x2]
        msk = np.zeros(patch.shape[:2], np.uint8)
        cv2.circle(msk, (int(cx) - x1, int(cy) - y1), int(r), 1, -1)
        px = patch[msk == 1]
        mean = float(px.mean()) if px.size else 0.0
        cv2.circle(v13, (int(cx), int(cy)), int(r), (0, 255, 0), 2)
        cv2.putText(v13, f"{i+1}", (int(cx) - 8, int(cy) + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        lines.append(f"  #{i+1:2}  ({cx:5.0f},{cy:4.0f}) r={r:4.1f}  mean={mean:6.2f}")
    body = "\n".join(lines[:14])
    if len(lines) > 14:
        body += f"\n  ... 共 {len(lines)} 個 / {len(lines)} total"
    steps.append((f"12. 最終 ROI 與量測 / Final ROIs ({len(final_rois)})", v13,
                  f"圓形 ROI 的平均灰階（原始值，非拉伸值）。\n"
                  f"Mean gray inside each circle (ORIGINAL values, not stretched).\n"
                  + body))


# =============================================================================
#  UI
# =============================================================================

root = tk.Tk()
root.title("圓形樣品 Auto ROI 逐步視覺化 / Circular Auto-ROI Steps")
root.configure(bg="#1E1E1E")
root.geometry("1500x900")

TITLE_F = ("Arial", 15, "bold")
ITEM_F = ("Arial", 11)
MONO_F = ("Courier New", 9)

main = tk.Frame(root, bg="#1E1E1E")
main.pack(fill="both", expand=True)

left = tk.Frame(main, bg="#1E1E1E")
left.pack(side="left", fill="both", expand=True)

step_title = tk.Label(left, text="請先載入影像 / Load an image",
                      font=TITLE_F, bg="#1E1E1E", fg="#00BFFF")
step_title.pack(pady=(8, 2))

img_label = tk.Label(left, bg="#000000")
img_label.pack(fill="both", expand=True, padx=8)

desc_label = tk.Label(left, text="", font=MONO_F, bg="#1E1E1E", fg="#00FF7F",
                      justify="left", anchor="w")
desc_label.pack(fill="x", padx=10, pady=(4, 2))

nav = tk.Frame(left, bg="#1E1E1E")
nav.pack(fill="x", padx=8, pady=(2, 8))
prev_btn = tk.Button(nav, text="◀ Prev", font=ITEM_F, bg="#0078D4", fg="white",
                     activebackground="#107C10", activeforeground="white", height=2)
prev_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
step_pos = tk.Label(nav, text="- / -", font=("Arial", 12, "bold"),
                    bg="#1E1E1E", fg="#E0E0E0", width=10)
step_pos.pack(side="left", padx=6)
next_btn = tk.Button(nav, text="Next ▶", font=ITEM_F, bg="#0078D4", fg="white",
                     activebackground="#107C10", activeforeground="white", height=2)
next_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))

right = tk.Frame(main, bg="#2B2B2B", width=370)
right.pack(side="right", fill="y")
right.pack_propagate(False)

tk.Label(right, text="設定 / Settings", font=TITLE_F,
         bg="#2B2B2B", fg="#00BFFF").pack(pady=(10, 6))

load_btn = tk.Button(right, text="載入影像 / Load Image", font=ITEM_F,
                     bg="#0078D4", fg="white", activebackground="#107C10",
                     activeforeground="white", height=2)
load_btn.pack(fill="x", padx=10, pady=4)

info_lbl = tk.Label(right, text="尚未載入 / No image", font=("Arial", 9),
                    bg="#2B2B2B", fg="#888888", wraplength=330, justify="left")
info_lbl.pack(anchor="w", padx=12, pady=(0, 4))

cf = tk.LabelFrame(right, text="通道 / Channel", font=("Arial", 10, "bold"),
                   bg="#2B2B2B", fg="#00BFFF", padx=6, pady=3)
cf.pack(fill="x", padx=10, pady=3)
ch_var = tk.StringVar(value="G")
for nm, vl in [("Green (螢光建議)", "G"), ("Blue", "B"), ("Red", "R"),
               ("Gray", "Gray"), ("Max", "Max")]:
    tk.Radiobutton(cf, text=nm, variable=ch_var, value=vl, font=("Arial", 10),
                   bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
                   activebackground="#2B2B2B", activeforeground="#00BFFF",
                   anchor="w").pack(anchor="w", fill="x")


def mkrow(parent, label, default, r):
    tk.Label(parent, text=label, font=("Arial", 10), bg="#2B2B2B",
             fg="#E0E0E0").grid(row=r, column=0, sticky="w", pady=1)
    e = ttk.Entry(parent, width=7)
    e.insert(0, str(default))
    e.grid(row=r, column=1, sticky="w", padx=4, pady=1)
    return e


df = tk.LabelFrame(right, text="偵測 / Detection", font=("Arial", 10, "bold"),
                   bg="#2B2B2B", fg="#00BFFF", padx=6, pady=3)
df.pack(fill="x", padx=10, pady=3)
auto_var = tk.BooleanVar(value=True)
tk.Checkbutton(df, text="自動門檻 Otsu / Auto threshold", variable=auto_var,
               font=("Arial", 10), bg="#2B2B2B", fg="#E0E0E0",
               selectcolor="#2B2B2B", activebackground="#2B2B2B",
               activeforeground="#00BFFF", anchor="w"
               ).grid(row=0, column=0, columnspan=2, sticky="w")
thr_e = mkrow(df, "手動門檻 Thr:", 12, 1)
blur_e = mkrow(df, "Blur:", 5, 2)
open_e = mkrow(df, "Open k:", 5, 3)
close_e = mkrow(df, "Close k:", 9, 4)
area_e = mkrow(df, "Min area:", 150, 5)
circ_e = mkrow(df, "Min circ:", 0.55, 6)
minr_e = mkrow(df, "Min radius:", 8, 7)

gf = tk.LabelFrame(right, text="網格補回 / Grid Fill", font=("Arial", 10, "bold"),
                   bg="#2B2B2B", fg="#00BFFF", padx=6, pady=3)
gf.pack(fill="x", padx=10, pady=3)
grid_var = tk.BooleanVar(value=True)
tk.Checkbutton(gf, text="補回漏掉的樣品 / Fill missing", variable=grid_var,
               font=("Arial", 10), bg="#2B2B2B", fg="#E0E0E0",
               selectcolor="#2B2B2B", activebackground="#2B2B2B",
               activeforeground="#00BFFF", anchor="w"
               ).grid(row=0, column=0, columnspan=2, sticky="w")
rows_e = mkrow(gf, "列數 Rows:", 2, 1)
grp_e  = mkrow(gf, "群數 Groups:", 2, 2)
cpg_e  = mkrow(gf, "每群欄數 Cols/grp:", 6, 3)
unif_var = tk.BooleanVar(value=True)
tk.Checkbutton(gf, text="統一半徑 / Uniform radius", variable=unif_var,
               font=("Arial", 10), bg="#2B2B2B", fg="#E0E0E0",
               selectcolor="#2B2B2B", activebackground="#2B2B2B",
               activeforeground="#00BFFF", anchor="w"
               ).grid(row=4, column=0, columnspan=2, sticky="w")

run_btn = tk.Button(right, text="執行流程 / Run Pipeline",
                    font=("Arial", 12, "bold"), bg="#107C10", fg="white",
                    activebackground="#0078D4", activeforeground="white", height=2)
run_btn.pack(fill="x", padx=10, pady=5)

hist_btn = tk.Button(right, text="灰階直方圖 / Histogram", font=ITEM_F,
                     bg="#0078D4", fg="white", activebackground="#107C10",
                     activeforeground="white", height=2)
hist_btn.pack(fill="x", padx=10, pady=(0, 3))

csv_btn = tk.Button(right, text="匯出 CSV / Export CSV", font=ITEM_F,
                    bg="#0078D4", fg="white", activebackground="#107C10",
                    activeforeground="white", height=2)
csv_btn.pack(fill="x", padx=10, pady=(0, 3))

save_btn = tk.Button(right, text="儲存所有步驟 / Save Steps", font=ITEM_F,
                     bg="#0078D4", fg="white", activebackground="#107C10",
                     activeforeground="white", height=2)
save_btn.pack(fill="x", padx=10, pady=(0, 3))

step_list = tk.Listbox(right, font=("Arial", 10), bg="#1E1E1E", fg="#00BFFF",
                       selectbackground="#0078D4", height=12, highlightthickness=0)
step_list.pack(fill="both", expand=True, padx=10, pady=(5, 10))


# =============================================================================
#  行為
# =============================================================================

def show_step(i):
    global cur_step
    if not steps:
        return
    cur_step = max(0, min(len(steps) - 1, i))
    title, im, desc = steps[cur_step]
    lw = img_label.winfo_width()
    lh = img_label.winfo_height()
    if lw <= 1:      # 尚未完成 layout 時的合理預設
        lw = max(600, root.winfo_width() - 400)
    if lh <= 1:
        lh = max(300, root.winfo_height() - 260)
    maxw, maxh = max(400, lw - 8), max(200, lh - 8)
    h, w = im.shape[:2]
    sc = min(maxw / w, maxh / h, 4.0)
    disp = cv2.resize(im, (max(1, int(w * sc)), max(1, int(h * sc))),
                      interpolation=cv2.INTER_NEAREST if sc > 1 else cv2.INTER_AREA)
    tkim = ImageTk.PhotoImage(Image.fromarray(disp))
    img_label.imgtk = tkim
    img_label.configure(image=tkim)
    step_title.config(text=title)
    desc_label.config(text=desc)
    step_pos.config(text=f"{cur_step+1} / {len(steps)}")
    step_list.selection_clear(0, tk.END)
    step_list.selection_set(cur_step)


def refresh_list():
    step_list.delete(0, tk.END)
    for t, _, _ in steps:
        step_list.insert(tk.END, t)


def read_params():
    try:
        PARAM['channel'] = ch_var.get()
        PARAM['auto_thr'] = auto_var.get()
        PARAM['thr'] = int(thr_e.get())
        PARAM['blur'] = max(1, int(blur_e.get()))
        PARAM['open_k'] = max(1, int(open_e.get()))
        PARAM['close_k'] = max(1, int(close_e.get()))
        PARAM['min_area'] = max(1, int(area_e.get()))
        PARAM['min_circ'] = float(circ_e.get())
        PARAM['min_r'] = max(1, int(minr_e.get()))
        PARAM['grid_fill'] = grid_var.get()
        PARAM['uniform_r'] = unif_var.get()
        PARAM['rows'] = max(1, int(rows_e.get()))
        PARAM['groups'] = max(1, int(grp_e.get()))
        PARAM['cols_pg'] = max(1, int(cpg_e.get()))
        return True
    except ValueError:
        messagebox.showwarning("參數錯誤 / Invalid", "請輸入有效數字。\nEnter valid numbers.")
        return False


def do_load(path=None):
    global src_color, src_gray, image_path
    if path is None:
        path = filedialog.askopenfilename(
            title="選擇影像 / Select Image",
            filetypes=[("Image", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("All", "*.*")])
    if not path:
        return False
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        messagebox.showerror("載入失敗 / Failed", f"無法讀取 / Cannot read:\n{path}")
        return False
    if im.ndim == 3 and im.shape[2] == 4:
        im = im[:, :, :3]
    if im.ndim == 3:
        b, g, r = cv2.split(im)
        d1 = int(np.abs(b.astype(np.int16) - g.astype(np.int16)).max())
        d2 = int(np.abs(g.astype(np.int16) - r.astype(np.int16)).max())
        if max(d1, d2) <= 6:
            im = g
    src_color = im
    image_path = path
    src_gray = extract_channel(src_color, ch_var.get())
    h, w = src_color.shape[:2]
    kind = "彩色 / Color" if src_color.ndim == 3 else "灰階 / Gray"
    info_lbl.config(text=f"{os.path.basename(path)}\n{w} x {h}  ({kind})", fg="#00FF7F")
    do_run()
    return True


def do_run():
    global src_gray
    if src_color is None:
        messagebox.showwarning("無影像 / No Image", "請先載入影像。\nLoad an image first.")
        return
    if not read_params():
        return
    src_gray = extract_channel(src_color, PARAM['channel'])
    run_pipeline()
    refresh_list()
    show_step(0)


def do_hist():
    if hist_data is None:
        messagebox.showinfo("無資料 / No Data", "請先執行流程。\nRun the pipeline first.")
        return
    w = tk.Toplevel(root)
    w.title("灰階直方圖 / Histogram")
    w.configure(bg="#1E1E1E")
    fig = Figure(figsize=(8, 5), dpi=100)
    h = np.bincount(hist_data.flatten(), minlength=256).astype(float)
    ax = fig.add_subplot(211)
    ax.bar(range(256), h, width=1.0, color="#00BFFF")
    ax.set_title("Full range"); ax.set_xlabel("Gray"); ax.set_ylabel("Count")
    ax.set_xlim(0, 255)
    ax2 = fig.add_subplot(212)
    ax2.bar(range(80), h[:80], width=1.0, color="#00FF7F")
    thr = PARAM['thr']
    if PARAM['auto_thr']:
        b = cv2.GaussianBlur(hist_data, (PARAM['blur'] | 1,) * 2, 0)
        thr = int(cv2.threshold(b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0])
    ax2.axvline(thr, color="#FF4444", lw=2, label=f"threshold={thr}")
    ax2.set_title("Zoom 0-80 (where the signal actually is)")
    ax2.set_xlabel("Gray"); ax2.set_ylabel("Count"); ax2.legend()
    fig.tight_layout()
    c = FigureCanvasTkAgg(fig, master=w)
    c.get_tk_widget().pack(fill="both", expand=True)
    c.draw()
    w.geometry("850x650")


def do_csv():
    if not final_rois:
        messagebox.showwarning("無資料 / No Data", "請先執行流程。\nRun the pipeline first.")
        return
    import datetime, csv
    g = src_gray
    H, W = g.shape[:2]
    fn = f"circle_roi_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(fn, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["Source", os.path.basename(image_path or "")])
        wr.writerow(["Channel", PARAM['channel']])
        wr.writerow(["Note", "Values are ORIGINAL gray levels (not contrast-stretched)"])
        wr.writerow([])
        wr.writerow(["Index", "CenterX", "CenterY", "Radius", "Mean", "Std", "Min", "Max", "Pixels"])
        for i, (cx, cy, r) in enumerate(final_rois):
            x1 = max(0, int(cx - r)); x2 = min(W, int(cx + r))
            y1 = max(0, int(cy - r)); y2 = min(H, int(cy + r))
            patch = g[y1:y2, x1:x2]
            m = np.zeros(patch.shape[:2], np.uint8)
            cv2.circle(m, (int(cx) - x1, int(cy) - y1), int(r), 1, -1)
            px = patch[m == 1]
            if px.size == 0:
                continue
            wr.writerow([i + 1, f"{cx:.1f}", f"{cy:.1f}", f"{r:.1f}",
                         f"{px.mean():.3f}", f"{px.std():.3f}",
                         int(px.min()), int(px.max()), px.size])
    messagebox.showinfo("已儲存 / Saved", f"{len(final_rois)} 個 ROI 已存到:\n{os.path.abspath(fn)}")


def do_save():
    if not steps:
        messagebox.showwarning("無資料 / No Data", "請先執行流程。\nRun first.")
        return
    base = os.path.splitext(os.path.basename(image_path or "img"))[0]
    outdir = f"circle_steps_{base}"
    os.makedirs(outdir, exist_ok=True)
    for i, (t, im, _) in enumerate(steps):
        cv2.imwrite(os.path.join(outdir, f"{i+1:02d}.png"),
                    cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    messagebox.showinfo("已儲存 / Saved",
                        f"{len(steps)} 張已存到:\n{os.path.abspath(outdir)}")


load_btn.config(command=lambda: do_load())
run_btn.config(command=do_run)
hist_btn.config(command=do_hist)
csv_btn.config(command=do_csv)
save_btn.config(command=do_save)
prev_btn.config(command=lambda: show_step(cur_step - 1))
next_btn.config(command=lambda: show_step(cur_step + 1))
step_list.bind("<<ListboxSelect>>",
               lambda e: show_step(step_list.curselection()[0])
               if step_list.curselection() else None)
_last_size = [0, 0]


def _on_resize(e):
    if abs(e.width - _last_size[0]) > 20 or abs(e.height - _last_size[1]) > 20:
        _last_size[0], _last_size[1] = e.width, e.height
        if steps:
            show_step(cur_step)


img_label.bind("<Configure>", _on_resize)
root.bind("<Left>", lambda e: show_step(cur_step - 1))
root.bind("<Right>", lambda e: show_step(cur_step + 1))

if __name__ == "__main__":
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        root.after(120, lambda: do_load(sys.argv[1]))
    root.mainloop()