# =============================================================================
#  Median Filter 驗證工具（離線圖片版 / No Camera Required）
#  Median Filter Validation Tool (Offline Image Version)
#
#  用途 / Purpose:
#    不需接相機，載入靜態圖片即可驗證 Threshold + Median Filter 的效果。
#    Load a static image to validate Threshold + Median Filter without a camera.
#
#  與主程式一致的邏輯 / Same logic as main program:
#    patch -> medianBlur(3) -> threshold(<=thr) -> 圓形遮罩 -> mean
#
#  使用方式 / Usage:
#    python filter_test_image.py
#    或 / or:
#    python filter_test_image.py <image_path>
# =============================================================================

import os
import sys
import cv2
import datetime
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk

# ── 全域狀態 ──────────────────────────────────────────────────────────────────
rois = []                    # ('rect', x1,y1,x2,y2) 或 ('circle', cx,cy,r)
source_gray = None           # 原始灰階影像（原始解析度）
display_gray = None          # letterbox 後的灰階（顯示座標系，與 ROI 同座標）
image_path = None

threshold_value = 200.0

# ── Median Filter ─────────────────────────────────────────────────────────────
median_filter_enabled = False
MEDIAN_KERNEL         = 3      # 固定 3（k>3 會使亮邊洩漏）
MEDIAN_DIFF_THRESH    = 5      # 差異圖判定：改動超過此值才標紅
median_preview_win    = None

# ── 顯示 / Letterbox ──────────────────────────────────────────────────────────
disp_w, disp_h = 900, 650
img_disp_w = disp_w
img_disp_h = disp_h
img_pad_x  = 0
img_pad_y  = 0
orig_w = orig_h = 0

# ── 滑鼠狀態 ──────────────────────────────────────────────────────────────────
dragging = False
start_x = start_y = 0
right_dragging = False
right_drag_roi_index = -1
right_drag_start_x = 0
right_drag_start_y = 0
right_drag_roi_start_pos = None

roi_fixed_width = 50
roi_fixed_height = 50
roi_fixed_diameter = 50


# ── Letterbox 工具 ────────────────────────────────────────────────────────────

def update_letterbox(cam_w, cam_h):
    """
    計算 letterbox 參數，維持原始比例。
    重要：ratio 上限為 1.0（永不放大）。放大會讓內插產生假紋理，
    median filter 會把那些紋理也抹掉，導致驗證結果失真。
    Never upscale: interpolation invents texture that median smooths,
    which would corrupt the validation.
    """
    global img_disp_w, img_disp_h, img_pad_x, img_pad_y
    ratio      = min(disp_w / cam_w, disp_h / cam_h, 1.0)
    img_disp_w = max(1, int(cam_w * ratio))
    img_disp_h = max(1, int(cam_h * ratio))
    img_pad_x  = (disp_w - img_disp_w) // 2
    img_pad_y  = (disp_h - img_disp_h) // 2


def evt_to_img(ex, ey):
    """將 label 座標夾在影像有效範圍內。"""
    ix = max(0, min(img_disp_w - 1, ex - img_pad_x))
    iy = max(0, min(img_disp_h - 1, ey - img_pad_y))
    return ix + img_pad_x, iy + img_pad_y


# =============================================================================
#  核心濾波邏輯（與主程式完全一致）
#  Core filter logic (identical to main program)
# =============================================================================

def apply_median_filter(patch):
    """Method A：用中值濾波取代灰塵像素值。必須在 threshold 之前呼叫。"""
    if patch is None or patch.size == 0:
        return patch
    if min(patch.shape[:2]) <= MEDIAN_KERNEL:
        return patch
    return cv2.medianBlur(patch, MEDIAN_KERNEL)


def get_roi_patch(frame, r):
    """從 frame 取出 ROI 的 patch 與圓形遮罩。回傳 (patch, mask or None)"""
    if frame is None or r is None:
        return None, None

    if r[0] == 'rect':
        _, x1, y1, x2, y2 = r
        hx1 = max(0, int(x1)); hy1 = max(0, int(y1))
        hx2 = min(frame.shape[1], int(x2)); hy2 = min(frame.shape[0], int(y2))
        if hx2 <= hx1 or hy2 <= hy1:
            return None, None
        return frame[hy1:hy2, hx1:hx2], None

    elif r[0] == 'circle':
        _, cx, cy, rad = r
        cx_i = int(round(cx)); cy_i = int(round(cy)); rad_i = int(round(rad))
        x1 = max(0, cx_i - rad_i); x2 = min(frame.shape[1], cx_i + rad_i)
        y1 = max(0, cy_i - rad_i); y2 = min(frame.shape[0], cy_i + rad_i)
        if x2 <= x1 or y2 <= y1 or rad_i <= 0:
            return None, None
        patch = frame[y1:y2, x1:x2]
        mask  = np.zeros(patch.shape[:2], dtype=np.uint8)
        cv2.circle(mask, (cx_i - x1, cy_i - y1), rad_i, 1, -1)
        return patch, mask

    return None, None


def compute_roi_mean(patch, circle_mask=None):
    """
    正確順序：medianBlur(若啟用) -> threshold -> 圓形遮罩 -> 平均
    回傳 (平均值, 被 median 改動的像素比例%)
    """
    if patch is None or patch.size == 0:
        return 0.0, 0.0

    changed_ratio = 0.0
    work = patch

    if median_filter_enabled:
        work = apply_median_filter(patch)
        diff = np.abs(patch.astype(np.int16) - work.astype(np.int16))
        changed = diff > MEDIAN_DIFF_THRESH
        if circle_mask is not None:
            n = int((circle_mask == 1).sum())
            changed_ratio = float((changed & (circle_mask == 1)).sum()) / n * 100.0 if n else 0.0
        else:
            changed_ratio = float(changed.sum()) / changed.size * 100.0

    valid = np.ones(work.shape[:2], bool)
    if circle_mask is not None:
        valid &= (circle_mask == 1)
    if threshold_value is not None:
        valid &= (work <= threshold_value)

    px = work[valid]
    return (float(np.mean(px)) if px.size > 0 else 0.0), changed_ratio


# =============================================================================
#  合成灰塵（用於驗證 filter 是否真的有效）
#  Synthetic dust injection (to prove the filter works)
# =============================================================================

def inject_synthetic_dust(gray, n_bright=10, n_gray=40, seed=42, roi_bounds=None):
    """
    在影像上加入人工灰塵點，用於驗證濾波器。
    - n_bright  : 亮灰塵（>threshold，本來就會被 threshold 擋掉）
    - n_gray    : 灰灰塵（<threshold，只有 median filter 抓得到）← 關鍵測試
    - roi_bounds: [(x1,y1,x2,y2), ...] 若提供，灰塵只灑在這些範圍內
                  （否則灰塵散落全圖，可能完全沒落在 ROI 裡，測不出效果）
    回傳 (加了灰塵的影像, 灰塵位置清單)
    """
    rng = np.random.default_rng(seed)
    out = gray.copy()
    spots = []
    h, w = out.shape[:2]

    for i in range(n_bright + n_gray):
        is_gray_dust = i >= n_bright

        if roi_bounds:
            # 灑在隨機一個 ROI 內，確保灰塵真的進入量測範圍
            bx1, by1, bx2, by2 = roi_bounds[int(rng.integers(0, len(roi_bounds)))]
            bx1 = max(3, bx1); by1 = max(3, by1)
            bx2 = min(w - 3, bx2); by2 = min(h - 3, by2)
            if bx2 <= bx1 + 1 or by2 <= by1 + 1:
                continue
            cx = int(rng.integers(bx1, bx2))
            cy = int(rng.integers(by1, by2))
        else:
            cx = int(rng.integers(20, w - 20))
            cy = int(rng.integers(20, h - 20))
        rad = int(rng.integers(1, 3))

        local = int(np.median(out[max(0, cy-6):cy+7, max(0, cx-6):cx+7]))
        if is_gray_dust:
            # 灰灰塵：明顯亮於鄰域，但仍低於 threshold
            val = min(int(threshold_value) - 5, local + int(rng.integers(12, 22)))
        else:
            # 亮灰塵：遠高於 threshold
            val = int(rng.integers(235, 256))

        if val <= local:
            continue
        cv2.circle(out, (cx, cy), rad, int(val), -1)
        spots.append((cx, cy, rad, val, 'gray' if is_gray_dust else 'bright'))

    return out, spots


# =============================================================================
#  Tkinter UI
# =============================================================================

root = tk.Tk()
root.title("Median Filter 驗證工具（圖片版）/ Filter Validation (Image Mode)")
root['bg'] = '#1E1E1E'

SETTINGS_LABEL_FONT = ("times new roman", 16, "bold")
SETTINGS_TYPE_FONT  = ("times new roman", 11, "bold")
SETTINGS_ITEM_FONT  = ("times new roman", 11)
ENTRY_FONT  = ("times new roman", 11)
RADIO_FONT  = ("times new roman", 11)

right_w = 360
root.geometry(f"{disp_w + right_w}x{disp_h + 90}")
root.resizable(False, False)

main_frame = tk.Frame(root, bg=root['bg'])
main_frame.pack(fill='both', expand=True)

left_frame = tk.Frame(main_frame, bg='#1E1E1E', width=disp_w, height=disp_h + 90)
left_frame.pack(side="left", fill="y")
left_frame.pack_propagate(False)

video_label = tk.Label(left_frame, width=disp_w, height=disp_h, bg="black")
video_label.pack()

control_frame = tk.Frame(left_frame, bg='#1E1E1E')
control_frame.pack(pady=5, fill="x")

style = ttk.Style()
try:
    style.theme_use("alt")
except Exception:
    pass
style.configure("Custom.TButton", font=("Arial", 12), padding=4, relief="flat",
                background="#0078D4", foreground="white")
style.map("Custom.TButton",
          foreground=[("active", "white"), ("!disabled", "white")],
          background=[("active", "#107C10"), ("!disabled", "#0078D4")])
style.configure("Apply.TButton", font=("Arial", 10), padding=2, relief="flat",
                background="#0078D4", foreground="white")
style.map("Apply.TButton",
          foreground=[("active", "white"), ("!disabled", "white")],
          background=[("active", "#107C10"), ("!disabled", "#0078D4")])

load_btn = ttk.Button(control_frame, text="載入圖片 / Load Image", style="Custom.TButton")
load_btn.pack(side="left", padx=2, pady=6, expand=True, fill="x")
clear_btn = ttk.Button(control_frame, text="清除 ROI / Clear ROI", style="Custom.TButton")
clear_btn.pack(side="left", padx=2, pady=6, expand=True, fill="x")
export_btn = ttk.Button(control_frame, text="匯出 CSV / Export CSV", style="Custom.TButton")
export_btn.pack(side="left", padx=2, pady=6, expand=True, fill="x")

# ── 右側設定面板（含捲軸）──────────────────────────────────────────────────────
right_outer = tk.Frame(main_frame, bg="#2B2B2B", width=right_w, height=disp_h + 90)
right_outer.pack(side="right", fill="both")
right_outer.pack_propagate(False)

right_canvas = tk.Canvas(right_outer, bg="#2B2B2B", highlightthickness=0, width=right_w)
right_vscroll = tk.Scrollbar(right_outer, orient=tk.VERTICAL, command=right_canvas.yview)
right_canvas.configure(yscrollcommand=right_vscroll.set)
right_vscroll.pack(side="right", fill="y")
right_canvas.pack(side="left", fill="both", expand=True)

right_frame = tk.Frame(right_canvas, bg="#2B2B2B", width=right_w)
right_canvas_win = right_canvas.create_window((0, 0), window=right_frame, anchor="nw")
right_frame.bind("<Configure>",
                 lambda e: right_canvas.configure(scrollregion=right_canvas.bbox("all")))
right_canvas.bind("<Configure>",
                  lambda e: right_canvas.itemconfig(right_canvas_win, width=e.width))

def _on_right_wheel(event):
    try:
        right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    except Exception:
        pass

right_canvas.bind("<Enter>", lambda e: right_canvas.bind_all("<MouseWheel>", _on_right_wheel))
right_canvas.bind("<Leave>", lambda e: right_canvas.unbind_all("<MouseWheel>"))

tk.Label(right_frame, text="驗證設定 / Validation", font=SETTINGS_LABEL_FONT,
         bg="#2B2B2B", fg="#00BFFF").pack(pady=(8, 4))

# ── 影像資訊 ──────────────────────────────────────────────────────────────────
info_frame = tk.LabelFrame(right_frame, text="影像 / Image", padx=6, pady=5,
                           font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                           borderwidth=2, relief="solid")
info_frame.pack(fill='x', padx=6, pady=4)
img_info_label = tk.Label(info_frame, text="尚未載入 / No image loaded",
                          font=("times new roman", 9), bg="#2B2B2B", fg="#888888",
                          wraplength=320, justify="left")
img_info_label.pack(anchor='w', padx=2, pady=2)

# ── ROI 形狀 ──────────────────────────────────────────────────────────────────
roi_frame = tk.LabelFrame(right_frame, text="ROI 形狀 / ROI Shape", padx=6, pady=5,
                          font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                          borderwidth=2, relief="solid")
roi_frame.pack(fill='x', padx=6, pady=4)

roi_shape_var = tk.StringVar(value='rect')
tk.Radiobutton(roi_frame, text="Rectangle", variable=roi_shape_var, value='rect',
               font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0",
               selectcolor="#2B2B2B", activebackground="#2B2B2B",
               activeforeground="#00BFFF").pack(anchor='w', fill='x')
tk.Radiobutton(roi_frame, text="Circle", variable=roi_shape_var, value='circle',
               font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0",
               selectcolor="#2B2B2B", activebackground="#2B2B2B",
               activeforeground="#00BFFF").pack(anchor='w', fill='x')

sz = tk.Frame(roi_frame, bg="#2B2B2B")
sz.pack(fill='x', pady=(4, 0))
tk.Label(sz, text="Width:", font=SETTINGS_ITEM_FONT, bg="#2B2B2B",
         fg="#E0E0E0").grid(row=0, column=0, sticky='w', pady=2)
roi_width_entry = ttk.Entry(sz, width=8, font=ENTRY_FONT)
roi_width_entry.insert(0, "80")
roi_width_entry.grid(row=0, column=1, sticky='w', padx=4, pady=2)

tk.Label(sz, text="Height:", font=SETTINGS_ITEM_FONT, bg="#2B2B2B",
         fg="#E0E0E0").grid(row=1, column=0, sticky='w', pady=2)
roi_height_entry = ttk.Entry(sz, width=8, font=ENTRY_FONT)
roi_height_entry.insert(0, "80")
roi_height_entry.grid(row=1, column=1, sticky='w', padx=4, pady=2)

tk.Label(sz, text="Diameter:", font=SETTINGS_ITEM_FONT, bg="#2B2B2B",
         fg="#E0E0E0").grid(row=2, column=0, sticky='w', pady=2)
roi_diameter_entry = ttk.Entry(sz, width=8, font=ENTRY_FONT)
roi_diameter_entry.insert(0, "80")
roi_diameter_entry.grid(row=2, column=1, sticky='w', padx=4, pady=2)

tk.Label(roi_frame, text="左鍵放置 ROI，右鍵拖曳移動\nLeft-click to place, right-drag to move",
         font=("times new roman", 8), bg="#2B2B2B", fg="#888888",
         justify="left").pack(anchor='w', pady=(4, 0))

# ── Threshold ─────────────────────────────────────────────────────────────────
thr_frame = tk.LabelFrame(right_frame, text="門檻 / Threshold", padx=6, pady=5,
                          font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                          borderwidth=2, relief="solid")
thr_frame.pack(fill='x', padx=6, pady=4)

threshold_var = tk.IntVar(value=200)
threshold_slider = tk.Scale(thr_frame, from_=0, to=255, orient=tk.HORIZONTAL,
                            variable=threshold_var, label="Threshold (<= 保留)",
                            font=("times new roman", 9), bg="#2B2B2B", fg="#E0E0E0",
                            highlightthickness=0, troughcolor="#444444",
                            activebackground="#00BFFF", length=320, resolution=1,
                            command=lambda v: on_threshold_change(v))
threshold_slider.pack(fill='x')

show_thr_var = tk.BooleanVar(value=False)
tk.Checkbutton(thr_frame, text="顯示被 Threshold 擋掉的像素（藍）",
               variable=show_thr_var, command=lambda: refresh_display(),
               font=("times new roman", 9), bg="#2B2B2B", fg="#E0E0E0",
               selectcolor="#2B2B2B", activebackground="#2B2B2B",
               activeforeground="#00BFFF", anchor="w").pack(anchor='w', fill='x')

# ── Median Filter ─────────────────────────────────────────────────────────────
mf_frame = tk.LabelFrame(right_frame, text="灰塵濾除 / Median Filter", padx=6, pady=5,
                         font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                         borderwidth=2, relief="solid")
mf_frame.pack(fill='x', padx=6, pady=4)

median_enable_var = tk.BooleanVar(value=False)
tk.Checkbutton(mf_frame, text="啟用 Median Filter (3x3)", variable=median_enable_var,
               command=lambda: toggle_median_filter(),
               font=RADIO_FONT, bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
               activebackground="#2B2B2B", activeforeground="#00BFFF",
               anchor="w").pack(anchor='w', fill='x')

median_preview_btn = ttk.Button(mf_frame, text="預覽濾波效果 / Preview",
                                style="Apply.TButton",
                                command=lambda: show_median_preview())
median_preview_btn.pack(fill='x', pady=(4, 2))

median_status_label = tk.Label(mf_frame, text="未啟用 / Disabled",
                               font=("times new roman", 9), bg="#2B2B2B", fg="#888888",
                               wraplength=320, justify="left")
median_status_label.pack(anchor='w')

# ── 合成灰塵測試 ──────────────────────────────────────────────────────────────
dust_frame = tk.LabelFrame(right_frame, text="合成灰塵測試 / Synthetic Dust Test",
                           padx=6, pady=5, font=SETTINGS_TYPE_FONT,
                           bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
dust_frame.pack(fill='x', padx=6, pady=4)

tk.Label(dust_frame,
         text="加入人工灰塵點來驗證濾波器：\n"
              "• 亮灰塵 (>thr)：threshold 就能擋\n"
              "• 灰灰塵 (<thr)：只有 median 抓得到\n"
              "Inject synthetic dust to prove the filter works.",
         font=("times new roman", 8), bg="#2B2B2B", fg="#888888",
         justify="left").pack(anchor='w', pady=(0, 4))

dust_btn_row = tk.Frame(dust_frame, bg="#2B2B2B")
dust_btn_row.pack(fill='x')
inject_btn = ttk.Button(dust_btn_row, text="加入灰塵 / Inject", style="Apply.TButton",
                        command=lambda: on_inject_dust())
inject_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))
restore_btn = ttk.Button(dust_btn_row, text="還原 / Restore", style="Apply.TButton",
                         command=lambda: on_restore_image())
restore_btn.pack(side="left", expand=True, fill="x", padx=(2, 0))

dust_status_label = tk.Label(dust_frame, text="", font=("times new roman", 9),
                             bg="#2B2B2B", fg="#888888", wraplength=320, justify="left")
dust_status_label.pack(anchor='w', pady=(2, 0))

# ── 即時量測結果 ──────────────────────────────────────────────────────────────
res_frame = tk.LabelFrame(right_frame, text="量測結果 / Results", padx=6, pady=5,
                          font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                          borderwidth=2, relief="solid")
res_frame.pack(fill='both', padx=6, pady=4, expand=True)

result_text = tk.Text(res_frame, height=14, width=40, font=("Courier New", 9),
                      bg="#1E1E1E", fg="#00FF7F", state="disabled", wrap="none")
result_text.pack(fill='both', expand=True)


# =============================================================================
#  邏輯函式
# =============================================================================

def set_result_text(txt):
    result_text.config(state="normal")
    result_text.delete("1.0", tk.END)
    result_text.insert("1.0", txt)
    result_text.config(state="disabled")


def on_threshold_change(v):
    global threshold_value
    try:
        threshold_value = float(v)
    except ValueError:
        return
    refresh_display()
    update_results()


def toggle_median_filter():
    global median_filter_enabled, median_preview_win
    median_filter_enabled = median_enable_var.get()

    if median_filter_enabled:
        median_status_label.config(text=f"已啟用 / Enabled (kernel={MEDIAN_KERNEL})",
                                   fg="#00FF7F")
        if len(rois) > 0:
            root.after(100, show_median_preview)
        else:
            median_status_label.config(text="已啟用，但尚未選取 ROI。\nEnabled, no ROI yet.",
                                       fg="#FFD700")
    else:
        median_status_label.config(text="未啟用 / Disabled", fg="#888888")
        if median_preview_win is not None:
            try:
                median_preview_win.destroy()
            except Exception:
                pass
            median_preview_win = None
    refresh_display()
    update_results()


def load_image(path=None):
    """載入圖片並建立 letterbox 顯示影像。"""
    global source_gray, display_gray, orig_w, orig_h, image_path, _pristine_gray, dust_active

    if path is None:
        path = filedialog.askopenfilename(
            title="選擇圖片 / Select Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                       ("All files", "*.*")])
    if not path:
        return False

    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        messagebox.showerror("載入失敗 / Load Failed",
                             f"無法讀取圖片：\n{path}\nCannot read image.")
        return False

    image_path  = path
    source_gray = img
    orig_h, orig_w = img.shape[:2]
    update_letterbox(orig_w, orig_h)

    # 建立與主程式相同的 letterbox 影像（ROI 座標系）
    # 1:1 時完全不 resize，保留原始像素值
    if (img_disp_w, img_disp_h) == (orig_w, orig_h):
        small = img
    else:
        small = cv2.resize(img, (img_disp_w, img_disp_h),
                           interpolation=cv2.INTER_AREA)
    canvas = np.zeros((disp_h, disp_w), dtype=np.uint8)
    canvas[img_pad_y:img_pad_y + img_disp_h,
           img_pad_x:img_pad_x + img_disp_w] = small
    display_gray  = canvas
    _pristine_gray = canvas.copy()
    dust_active   = False

    rois.clear()
    img_info_label.config(
        text=f"{os.path.basename(path)}\n"
             f"原始 / Original: {orig_w} x {orig_h} px\n"
             f"顯示 / Display : {img_disp_w} x {img_disp_h} px",
        fg="#00FF7F")
    dust_status_label.config(text="", fg="#888888")
    refresh_display()
    update_results()
    return True


_pristine_gray = None   # 未加灰塵的原始 letterbox 影像
dust_active    = False  # 目前畫面是否含合成灰塵


def on_inject_dust():
    """加入合成灰塵並自動比對濾波前後。"""
    global display_gray, dust_active
    if display_gray is None:
        messagebox.showwarning("無影像 / No Image", "請先載入圖片。\nLoad an image first.")
        return

    # 若已有 ROI，把灰塵灑進 ROI 內；否則散落全圖
    bounds = []
    for r in rois:
        if r[0] == 'rect':
            bounds.append((int(r[1]), int(r[2]), int(r[3]), int(r[4])))
        else:
            cx, cy, rr = int(r[1]), int(r[2]), int(r[3])
            k = int(rr * 0.7)     # 內接方形，確保落在圓內
            bounds.append((cx - k, cy - k, cx + k, cy + k))

    dusty, spots = inject_synthetic_dust(_pristine_gray, roi_bounds=bounds or None)
    display_gray = dusty
    dust_active  = True

    n_gray   = sum(1 for s in spots if s[4] == 'gray')
    n_bright = sum(1 for s in spots if s[4] == 'bright')
    where = "ROI 內 / inside ROI" if bounds else "全圖 / whole image"
    dust_status_label.config(
        text=f"已加入 {len(spots)} 顆灰塵（{where}）\n"
             f"  亮灰塵 / Bright (>thr): {n_bright}\n"
             f"  灰灰塵 / Gray  (<thr): {n_gray}  ← 關鍵測試"
             + ("" if bounds else "\n提示：先框 ROI 再加灰塵，效果較明顯"),
        fg="#FFD700")
    refresh_display()
    update_results()


def on_restore_image():
    global display_gray, dust_active
    if _pristine_gray is None:
        return
    display_gray = _pristine_gray.copy()
    dust_active  = False
    dust_status_label.config(text="已還原原始影像 / Restored.", fg="#888888")
    refresh_display()
    update_results()


def update_results():
    """計算每個 ROI 在 filter on/off 下的結果並顯示。"""
    if display_gray is None or len(rois) == 0:
        set_result_text("載入圖片並框選 ROI 後顯示結果。\n\n"
                        "Load an image and draw an ROI\nto see results.")
        return

    global median_filter_enabled
    saved = median_filter_enabled

    lines = [f"Threshold = {int(threshold_value)}   Median = "
             f"{'ON (3x3)' if saved else 'OFF'}", "=" * 42, ""]

    for i, r in enumerate(rois):
        patch, cmask = get_roi_patch(display_gray, r)
        if patch is None:
            continue

        median_filter_enabled = False
        mean_off, _ = compute_roi_mean(patch, cmask)
        median_filter_enabled = True
        mean_on, ratio = compute_roi_mean(patch, cmask)
        median_filter_enabled = saved

        # 有效像素數
        def n_valid(arr, mask):
            v = np.ones(arr.shape[:2], bool)
            if mask is not None:
                v &= (mask == 1)
            v &= (arr <= threshold_value)
            return int(v.sum())

        clean = apply_median_filter(patch)
        n_off = n_valid(patch, cmask)
        n_on  = n_valid(clean, cmask)

        shape_str = "Rect" if r[0] == 'rect' else "Circle"
        lines.append(f"Sample {i+1} ({shape_str})  {patch.shape[1]}x{patch.shape[0]} px")
        lines.append(f"  {'':10}{'Median OFF':>12}{'Median ON':>12}")
        lines.append(f"  {'Mean':10}{mean_off:12.4f}{mean_on:12.4f}")
        lines.append(f"  {'Valid N':10}{n_off:12d}{n_on:12d}")
        lines.append(f"  {'Delta':10}{'':12}{mean_on - mean_off:+12.4f}")
        lines.append(f"  被修正 / Corrected: {ratio:.3f}%")

        # ── 合成灰塵模式：與「無灰塵的真值」比對，這才是濾波器有沒有效的證據 ──
        if dust_active and _pristine_gray is not None:
            pp, pm = get_roi_patch(_pristine_gray, r)
            if pp is not None:
                # 公平比較：median 本身會微幅改變基準，
                # 所以 median ON 要跟「乾淨影像也過 median」比，而不是跟原始比。
                median_filter_enabled = False
                truth_off, _ = compute_roi_mean(pp, pm)
                median_filter_enabled = True
                truth_on, _ = compute_roi_mean(pp, pm)
                median_filter_enabled = saved

                err_off = mean_off - truth_off
                err_on  = mean_on - truth_on
                lines.append("  " + "-" * 38)
                lines.append("  對照無灰塵真值 / vs dust-free truth")
                lines.append(f"  {'':10}{'OFF':>12}{'ON':>12}")
                lines.append(f"  {'Truth':10}{truth_off:12.4f}{truth_on:12.4f}")
                lines.append(f"  {'Error':10}{err_off:+12.4f}{err_on:+12.4f}")
                if abs(err_off) > 1e-9:
                    impr = (1 - abs(err_on) / abs(err_off)) * 100
                    verdict = "有效 / EFFECTIVE" if abs(err_on) < abs(err_off) else "無改善 / NO GAIN"
                    lines.append(f"  誤差降低 / Error cut: {impr:+.1f}%  {verdict}")
        lines.append("")

    set_result_text("\n".join(lines))


def refresh_display():
    """重繪主畫面：ROI 外框 + 可選的 threshold 標示。"""
    if display_gray is None:
        video_label.configure(image="")
        return

    disp = cv2.cvtColor(display_gray, cv2.COLOR_GRAY2RGB)

    # ── 標示被 threshold 擋掉的像素（僅 ROI 內）──
    if show_thr_var.get():
        for r in rois:
            patch, cmask = get_roi_patch(display_gray, r)
            if patch is None:
                continue
            if r[0] == 'rect':
                x1, y1, x2, y2 = (int(v) for v in r[1:])
                x1 = max(0, x1); y1 = max(0, y1)
                x2 = min(disp.shape[1], x2); y2 = min(disp.shape[0], y2)
            else:
                cx, cy, rad = (int(v) for v in r[1:])
                x1 = max(0, cx - rad); x2 = min(disp.shape[1], cx + rad)
                y1 = max(0, cy - rad); y2 = min(disp.shape[0], cy + rad)

            work = apply_median_filter(patch) if median_filter_enabled else patch
            blocked = work > threshold_value
            if cmask is not None:
                blocked &= (cmask == 1)
            reg = disp[y1:y2, x1:x2]
            reg[blocked] = [60, 130, 255]
            disp[y1:y2, x1:x2] = reg

    # ── ROI 外框 ──
    for i, r in enumerate(rois):
        if r[0] == 'rect':
            x1, y1, x2, y2 = (int(v) for v in r[1:])
            cv2.rectangle(disp, (x1, y1), (x2, y2), (255, 255, 255), 2)
            txt = f"S{i+1}"
            ty = max(16, y1 - 6)
            cv2.putText(disp, txt, (x1, ty), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (255, 255, 255), 2)
        else:
            cx, cy, rad = (int(v) for v in r[1:])
            cv2.circle(disp, (cx, cy), rad, (255, 255, 255), 2)
            txt = f"S{i+1}"
            cv2.putText(disp, txt, (cx - rad, max(16, cy - rad - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # ── 拖曳中的預覽框 ──
    if dragging:
        try:
            if roi_shape_var.get() == 'rect':
                w = int(roi_width_entry.get()); h = int(roi_height_entry.get())
                x1 = max(img_pad_x, min(img_pad_x + img_disp_w - w, start_x))
                y1 = max(img_pad_y, min(img_pad_y + img_disp_h - h, start_y))
                cv2.rectangle(disp, (x1, y1), (x1 + w, y1 + h), (200, 200, 200), 1)
            else:
                rr = int(roi_diameter_entry.get()) // 2
                cx = max(img_pad_x + rr, min(img_pad_x + img_disp_w - rr, start_x))
                cy = max(img_pad_y + rr, min(img_pad_y + img_disp_h - rr, start_y))
                cv2.circle(disp, (cx, cy), rr, (200, 200, 200), 1)
        except ValueError:
            pass

    imtk = ImageTk.PhotoImage(Image.fromarray(disp))
    video_label.imgtk = imtk
    video_label.configure(image=imtk)


# =============================================================================
#  預覽視窗（與主程式相同版面）
# =============================================================================

def show_median_preview():
    global median_preview_win

    if display_gray is None:
        messagebox.showwarning("無影像 / No Image", "請先載入圖片。\nLoad an image first.")
        return
    if len(rois) == 0:
        messagebox.showinfo("尚未選取 ROI / No ROI",
                            "請先框選至少一個 ROI。\nSelect at least one ROI first.")
        return

    if median_preview_win is not None:
        try:
            median_preview_win.destroy()
        except Exception:
            pass

    median_preview_win = tk.Toplevel(root)
    median_preview_win.title("Median Filter 預覽 / Preview")
    median_preview_win.configure(bg="#1E1E1E")

    outer = tk.Canvas(median_preview_win, bg="#1E1E1E", highlightthickness=0)
    vsb = tk.Scrollbar(median_preview_win, orient=tk.VERTICAL, command=outer.yview)
    outer.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    outer.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(outer, bg="#1E1E1E")
    outer.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: outer.configure(scrollregion=outer.bbox("all")))

    def _wheel(e):
        try:
            outer.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception:
            pass
    outer.bind("<Enter>", lambda e: outer.bind_all("<MouseWheel>", _wheel))
    outer.bind("<Leave>", lambda e: outer.unbind_all("<MouseWheel>"))

    tk.Label(inner, text=f"Median Filter (kernel={MEDIAN_KERNEL})  |  "
                         f"Threshold = {int(threshold_value)}",
             font=("Arial", 13, "bold"), bg="#1E1E1E", fg="#00BFFF").pack(pady=(10, 2))
    tk.Label(inner, text="紅色 = 被 median filter 修正的像素（灰塵）\n"
                         "Red = pixels corrected by median filter (dust)",
             font=("Arial", 9), bg="#1E1E1E", fg="#888888").pack(pady=(0, 8))

    keep_refs = []
    thr_v = threshold_value

    for i, r in enumerate(rois):
        patch, cmask = get_roi_patch(display_gray, r)
        if patch is None or patch.size == 0:
            continue

        clean = apply_median_filter(patch)
        diffmap = np.abs(patch.astype(np.int16) - clean.astype(np.int16))
        changed = diffmap > MEDIAN_DIFF_THRESH

        SC = max(2, min(6, int(300 / max(patch.shape[0], patch.shape[1], 1))))

        def to_rgb(g):
            return cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)

        p_before = to_rgb(patch)
        p_after  = to_rgb(clean)
        p_diff   = to_rgb(patch.copy())
        p_diff[changed] = [255, 40, 40]

        if cmask is not None:
            for pim in (p_before, p_after, p_diff):
                pim[cmask == 0] = (pim[cmask == 0] * 0.25).astype(np.uint8)

        blk = tk.LabelFrame(inner, text=f"Sample {i+1}", font=("Arial", 11, "bold"),
                            bg="#2B2B2B", fg="#00BFFF", padx=6, pady=4)
        blk.pack(fill="x", padx=10, pady=6)

        prow = tk.Frame(blk, bg="#2B2B2B")
        prow.pack()

        for title, im in [("濾波前 / Before", p_before),
                          ("濾波後 / After",  p_after),
                          ("差異 / Diff",     p_diff)]:
            col = tk.Frame(prow, bg="#2B2B2B")
            col.pack(side="left", padx=5)
            tk.Label(col, text=title, font=("Arial", 9),
                     bg="#2B2B2B", fg="#E0E0E0").pack()
            big = cv2.resize(im, (im.shape[1] * SC, im.shape[0] * SC),
                             interpolation=cv2.INTER_NEAREST)
            tkim = ImageTk.PhotoImage(Image.fromarray(big))
            keep_refs.append(tkim)
            lb = tk.Label(col, image=tkim, bg="#2B2B2B", bd=1, relief="solid")
            lb.image = tkim
            lb.pack()

        def stat(arr, mask):
            v = np.ones(arr.shape[:2], bool)
            if mask is not None:
                v &= (mask == 1)
            if thr_v is not None:
                v &= (arr <= thr_v)
            px = arr[v]
            return (px.mean() if px.size else 0.0,
                    px.std() if px.size else 0.0,
                    int(px.size))

        mb, sb, nb = stat(patch, cmask)
        ma, sa, na = stat(clean, cmask)
        n_changed = int((changed & (cmask == 1)).sum()) if cmask is not None else int(changed.sum())
        n_total = int((cmask == 1).sum()) if cmask is not None else int(patch.size)
        ratio = n_changed / n_total * 100.0 if n_total else 0.0

        info = (
            f"被修正像素 / Corrected : {n_changed} px  ({ratio:.2f}%)\n"
            f"-----------------------------------------\n"
            f"{'':14}{'Before':>11}{'After':>11}{'Delta':>11}\n"
            f"{'Mean':14}{mb:11.3f}{ma:11.3f}{ma-mb:+11.3f}\n"
            f"{'Std Dev':14}{sb:11.3f}{sa:11.3f}{sa-sb:+11.3f}\n"
            f"{'Valid N':14}{nb:11d}{na:11d}{na-nb:+11d}"
        )
        tk.Label(blk, text=info, font=("Courier New", 9), bg="#2B2B2B",
                 fg="#00FF7F", justify="left").pack(anchor="w", pady=(4, 2))

    median_preview_win.keep_refs = keep_refs

    btnf = tk.Frame(inner, bg="#1E1E1E")
    btnf.pack(fill="x", padx=10, pady=10)
    tk.Button(btnf, text="關閉 / Close", command=median_preview_win.destroy,
              font=("Arial", 10), bg="#555555", fg="white",
              activebackground="#777777", activeforeground="white",
              height=2).pack(fill="x")

    median_preview_win.update_idletasks()
    w = min(inner.winfo_reqwidth() + 30, int(root.winfo_screenwidth() * 0.9))
    h = min(inner.winfo_reqheight() + 30, int(root.winfo_screenheight() * 0.85))
    median_preview_win.geometry(f"{w}x{h}")


# =============================================================================
#  滑鼠事件
# =============================================================================

def on_mouse_down(event):
    global dragging, start_x, start_y
    global roi_fixed_width, roi_fixed_height, roi_fixed_diameter
    if display_gray is None:
        return
    try:
        if roi_shape_var.get() == 'rect':
            roi_fixed_width  = int(roi_width_entry.get())
            roi_fixed_height = int(roi_height_entry.get())
            if roi_fixed_width <= 0 or roi_fixed_height <= 0:
                messagebox.showwarning("無效輸入 / Invalid Input",
                                       "寬高必須大於 0。\nWidth/Height must be > 0.")
                return
        else:
            roi_fixed_diameter = int(roi_diameter_entry.get())
            if roi_fixed_diameter <= 0:
                messagebox.showwarning("無效輸入 / Invalid Input",
                                       "直徑必須大於 0。\nDiameter must be > 0.")
                return
    except ValueError:
        messagebox.showwarning("無效輸入 / Invalid Input",
                               "請輸入有效數字。\nEnter valid numbers.")
        return
    start_x, start_y = evt_to_img(event.x, event.y)
    dragging = True
    refresh_display()


def on_mouse_move(event):
    global start_x, start_y
    if dragging:
        start_x, start_y = evt_to_img(event.x, event.y)
        refresh_display()


def on_mouse_up(event):
    global dragging
    if not dragging:
        return
    dragging = False
    if roi_shape_var.get() == 'rect':
        x1 = max(img_pad_x, min(img_pad_x + img_disp_w - roi_fixed_width, start_x))
        y1 = max(img_pad_y, min(img_pad_y + img_disp_h - roi_fixed_height, start_y))
        rois.append(('rect', x1, y1, x1 + roi_fixed_width, y1 + roi_fixed_height))
    else:
        rr = roi_fixed_diameter // 2
        cx = max(img_pad_x + rr, min(img_pad_x + img_disp_w - rr, start_x))
        cy = max(img_pad_y + rr, min(img_pad_y + img_disp_h - rr, start_y))
        rois.append(('circle', cx, cy, rr))
    refresh_display()
    update_results()


def get_roi_at_point(x, y):
    for idx, roi in enumerate(rois):
        if roi[0] == 'rect':
            _, x1, y1, x2, y2 = roi
            if x1 <= x <= x2 and y1 <= y <= y2:
                return idx
        elif roi[0] == 'circle':
            _, cx, cy, r = roi
            if ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 <= r:
                return idx
    return -1


def on_right_down(event):
    global right_dragging, right_drag_roi_index, right_drag_start_x
    global right_drag_start_y, right_drag_roi_start_pos
    if len(rois) == 0:
        return
    idx = get_roi_at_point(event.x, event.y)
    if idx >= 0:
        right_dragging = True
        right_drag_roi_index = idx
        right_drag_start_x = event.x
        right_drag_start_y = event.y
        right_drag_roi_start_pos = rois[idx]


def on_right_move(event):
    if not (right_dragging and 0 <= right_drag_roi_index < len(rois)):
        return
    dx = event.x - right_drag_start_x
    dy = event.y - right_drag_start_y
    if right_drag_roi_start_pos[0] == 'rect':
        _, x1, y1, x2, y2 = right_drag_roi_start_pos
        w, h = x2 - x1, y2 - y1
        nx1 = max(img_pad_x, min(img_pad_x + img_disp_w - w, x1 + dx))
        ny1 = max(img_pad_y, min(img_pad_y + img_disp_h - h, y1 + dy))
        rois[right_drag_roi_index] = ('rect', nx1, ny1, nx1 + w, ny1 + h)
    else:
        _, cx, cy, r = right_drag_roi_start_pos
        rois[right_drag_roi_index] = (
            'circle',
            max(img_pad_x + r, min(img_pad_x + img_disp_w - r, cx + dx)),
            max(img_pad_y + r, min(img_pad_y + img_disp_h - r, cy + dy)),
            r)
    refresh_display()


def on_right_up(event):
    global right_dragging, right_drag_roi_index, right_drag_roi_start_pos
    if not right_dragging:
        return
    right_dragging = False
    right_drag_roi_index = -1
    right_drag_roi_start_pos = None
    update_results()


def on_clear_roi():
    rois.clear()
    refresh_display()
    update_results()


def on_export_csv():
    """匯出每個 ROI 在 filter on/off 下的比對結果。"""
    if display_gray is None or len(rois) == 0:
        messagebox.showwarning("無資料 / No Data",
                               "請先載入圖片並框選 ROI。\nLoad image and draw ROI first.")
        return

    global median_filter_enabled
    saved = median_filter_enabled
    recs = []

    for i, r in enumerate(rois):
        patch, cmask = get_roi_patch(display_gray, r)
        if patch is None:
            continue
        median_filter_enabled = False
        mean_off, _ = compute_roi_mean(patch, cmask)
        median_filter_enabled = True
        mean_on, ratio = compute_roi_mean(patch, cmask)
        median_filter_enabled = saved

        clean = apply_median_filter(patch)

        def stat(arr, mask):
            v = np.ones(arr.shape[:2], bool)
            if mask is not None:
                v &= (mask == 1)
            v &= (arr <= threshold_value)
            px = arr[v]
            return (float(px.mean()) if px.size else 0.0,
                    float(px.std()) if px.size else 0.0,
                    int(px.size))

        mb, sb, nb = stat(patch, cmask)
        ma, sa, na = stat(clean, cmask)

        recs.append({
            "Sample": f"Sample {i+1}",
            "Shape": r[0],
            "ROI_px": f"{patch.shape[1]}x{patch.shape[0]}",
            "Threshold": int(threshold_value),
            "Mean_MedianOFF": round(mb, 4),
            "Mean_MedianON": round(ma, 4),
            "Mean_Delta": round(ma - mb, 4),
            "Std_MedianOFF": round(sb, 4),
            "Std_MedianON": round(sa, 4),
            "ValidN_MedianOFF": nb,
            "ValidN_MedianON": na,
            "ValidN_Delta": na - nb,
            "Corrected_pct": round(ratio, 4),
        })

    now = datetime.datetime.now()
    fn = f"filter_validation_{now:%Y_%m_%d_%H_%M_%S}.csv"
    df = pd.DataFrame(recs)
    header = pd.DataFrame([{
        "Sample": f"Image: {os.path.basename(image_path) if image_path else 'N/A'}",
        "Shape": f"Median kernel: {MEDIAN_KERNEL}",
        "ROI_px": f"Diff thresh: {MEDIAN_DIFF_THRESH}",
    }])
    pd.concat([header, df], ignore_index=True).to_csv(fn, index=False)
    messagebox.showinfo("儲存成功 / Saved", f"已儲存為 {fn}\nSaved as {fn}")


video_label.bind("<ButtonPress-1>",   on_mouse_down)
video_label.bind("<B1-Motion>",       on_mouse_move)
video_label.bind("<ButtonRelease-1>", on_mouse_up)
video_label.bind("<ButtonPress-3>",   on_right_down)
video_label.bind("<B3-Motion>",       on_right_move)
video_label.bind("<ButtonRelease-3>", on_right_up)

load_btn.config(command=lambda: load_image())
clear_btn.config(command=on_clear_roi)
export_btn.config(command=on_export_csv)

set_result_text("載入圖片並框選 ROI 後顯示結果。\n\n"
                "Load an image and draw an ROI\nto see results.")

# ── 啟動時可由命令列帶入圖片 ──────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        root.after(100, lambda: load_image(sys.argv[1]))
    root.mainloop()