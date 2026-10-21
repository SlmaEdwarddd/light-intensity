import os
import sys
import json
import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import threading
import time
import datetime
import csv
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

rois = []  # 存放 ROI，格式：('rect', x1,y1,x2,y2) 或 ('circle', cx,cy,r)
roi_data = []
timestamps = []
running = True
analyzing = False
roi_selected = False
roi_locked = False
current_frame = None
frame_lock = threading.Lock()
camera_lock = threading.Lock()   # ← 保護相機 stop/get_image/start
start_x = start_y = end_x = end_y = 0
dragging = False
right_dragging = False
right_drag_roi_index = -1
right_drag_start_x = 0
right_drag_start_y = 0
right_drag_roi_start_pos = None
plot_win = None
log_text_widget = None
plot_canvases = []
plot_axes = []
plot_figures = []
canvas_frame = None
scrollable_frame = None

# CAMERA_TYPE 現在有三種值：
#   "XIMEA_MC050"  → XIMEA MC050MG-SY
#   "XIMEA_MC023"  → XIMEA MC023MG-SY
#   "THORLABS"     → Thorlabs
CAMERA_TYPE = None
cam = None
xi_img = None
bit_depth = 8
orig_w = orig_h = 0

# 固定顯示大小為 1280x920（label 尺寸，永遠不變）
disp_w, disp_h = 1280, 920

# ── Letterbox：維持相機原始比例，影像居中，黑邊填滿 ───────────────────────────
img_disp_w = 1280   # 實際影像在 label 內的寬度
img_disp_h = 920    # 實際影像在 label 內的高度
img_pad_x  = 0      # 左右黑邊寬度
img_pad_y  = 0      # 上下黑邊高度

user_gain_val = 0.0
user_exposure_ms = 2500  # milliseconds
gain_locked = False
exposure_locked = False

roi_shape_choice = 'rect'
decimal_places = None
decimal_locked = False
settings_applied = False

roi_fixed_width = 70
roi_fixed_height = 70
roi_fixed_diameter = 50
roi_dragging_offset_x = 0
roi_dragging_offset_y = 0

text_follow = True

# ── 灰階視窗 / Grey-level windowing (display-only contrast stretch) ──
level_mode      = False   # 正在拖曳選取區域
level_drawing   = False
level_start_x   = 0
level_start_y   = 0
level_block     = None    # (x1,y1,x2,y2) 顯示座標
level_win       = None    # 直方圖視窗參考

stretch_enabled = False   # 是否套用對比拉伸（僅顯示）
stretch_min     = None    # 使用者選的最低灰階 → 映射為 0
stretch_max     = None    # 使用者選的最高灰階 → 映射為 255

deglint_preview_win   = None    # de-glint 預覽視窗參考

# ── De-glint 去亮反光（統計去離群，取代難調的 threshold）──────────────────────
deglint_enabled = False         # 是否啟用亮離群去除
deglint_show_removed = False    # 主畫面即時把被去除的反光像素染紅
DEGLINT_K       = 3.0           # White top-hat 殘留門檻的倍數:剔除 > mean + K·std 的亮點
DEGLINT_KERNEL  = 9             # ponytail: opening 核心;需大於灰塵、小於樣本,依光學/樣本大小校正

# ── 匯入圖片模式 / Import Image Mode ──────────────────────────────────────────
source_image_gray = None        # 匯入的原始灰階影像（原始解析度）
image_frame_cache = None        # letterbox 後的影像（顯示座標系，餵給串流迴圈）
image_path        = None        # 圖片路徑


# ── 工具函式：判斷是否為任一 XIMEA 機型 ──────────────────────────────────────
def is_ximea():
    return CAMERA_TYPE in ("XIMEA_MC050", "XIMEA_MC023")

def update_letterbox(cam_w, cam_h):
    """相機初始化後計算 letterbox 參數，維持原始比例。
    匯入圖片模式下上限為 1.0（永不放大），避免內插產生假紋理影響濾波驗證。"""
    global img_disp_w, img_disp_h, img_pad_x, img_pad_y
    if is_image_mode():
        ratio = min(disp_w / cam_w, disp_h / cam_h, 1.0)
    else:
        ratio = min(disp_w / cam_w, disp_h / cam_h)
    img_disp_w = max(1, int(cam_w * ratio))
    img_disp_h = max(1, int(cam_h * ratio))
    img_pad_x  = (disp_w - img_disp_w) // 2
    img_pad_y  = (disp_h - img_disp_h) // 2

def evt_to_img(ex, ey):
    """將 label 座標夾在影像有效範圍內，回傳 display-space 座標。"""
    ix = max(0, min(img_disp_w - 1, ex - img_pad_x))
    iy = max(0, min(img_disp_h - 1, ey - img_pad_y))
    return ix + img_pad_x, iy + img_pad_y

# ── Tkinter UI ───────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("光強度偵測 / Light Intensity Detection")
root['bg'] = '#1E1E1E'

SETTINGS_LABEL_FONT = ("times new roman", 18, "bold")
SETTINGS_TYPE_FONT  = ("times new roman", 12, "bold")
SETTINGS_ITEM_FONT  = ("times new roman", 12)
ENTRY_FONT  = ("times new roman", 12)
RADIO_FONT  = ("times new roman", 12)
FRAME_PADX  = 8
FRAME_PADY  = 6

right_w = 420
main_w  = disp_w + right_w
main_h  = disp_h + 80

root.geometry(f"{main_w}x{main_h}")
root.resizable(False, False)

main_frame = tk.Frame(root, bg=root['bg'])
main_frame.pack(fill='both', expand=True)

# 左側：影像 + 三按鈕
left_frame = tk.Frame(main_frame, bg='#1E1E1E', width=disp_w, height=disp_h+80)
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

style.configure("Custom.TButton", font=("Arial", 15), padding=5, relief="flat",
                background="#0078D4", foreground="white")
style.map("Custom.TButton",
          foreground=[("active", "white"), ("!disabled", "white")],
          background=[("active", "#107C10"), ("!disabled", "#0078D4")])
style.configure("Apply.TButton", font=("Arial", 12), padding=2, relief="flat",
                background="#0078D4", foreground="white")
style.map("Apply.TButton",
          foreground=[("active", "white"), ("!disabled", "white")],
          background=[("active", "#107C10"), ("!disabled", "#0078D4")])

default_btn = ttk.Button(control_frame, text="重新選取 ROI / Reselect ROI", style="Custom.TButton")
default_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")
start_btn = ttk.Button(control_frame, text="開始 / Start", style="Custom.TButton", state="disabled")
start_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")
save_btn = ttk.Button(control_frame, text="儲存 CSV / Save as CSV", style="Custom.TButton")
save_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")

# 右側：設定區（加入捲軸支援）
right_outer = tk.Frame(main_frame, bg="#2B2B2B", width=right_w, height=disp_h+80)
right_outer.pack(side="right", fill="both")
right_outer.pack_propagate(False)

right_canvas = tk.Canvas(right_outer, bg="#2B2B2B", highlightthickness=0, width=right_w)
right_vscroll = tk.Scrollbar(right_outer, orient=tk.VERTICAL, command=right_canvas.yview)
right_canvas.configure(yscrollcommand=right_vscroll.set)
right_vscroll.pack(side="right", fill="y")
right_canvas.pack(side="left", fill="both", expand=True)

right_frame = tk.Frame(right_canvas, bg="#2B2B2B", width=right_w)
right_canvas_win = right_canvas.create_window((0, 0), window=right_frame, anchor="nw")

def _on_right_frame_configure(event):
    right_canvas.configure(scrollregion=right_canvas.bbox("all"))

def _on_right_canvas_configure(event):
    right_canvas.itemconfig(right_canvas_win, width=event.width)

right_frame.bind("<Configure>", _on_right_frame_configure)
right_canvas.bind("<Configure>", _on_right_canvas_configure)

def _on_right_mousewheel(event):
    try:
        right_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    except Exception:
        pass

right_canvas.bind("<Enter>", lambda e: right_canvas.bind_all("<MouseWheel>", _on_right_mousewheel))
right_canvas.bind("<Leave>", lambda e: right_canvas.unbind_all("<MouseWheel>"))

settings_label = tk.Label(right_frame, text="設定 / Settings",
                           font=SETTINGS_LABEL_FONT, bg="#2B2B2B", fg="#00BFFF")
settings_label.pack(pady=(8, 4))

# Gain & Exposure
ge_frame = tk.LabelFrame(right_frame, text="相機設定 / Camera Settings",
                          padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                          bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
ge_frame.pack(fill='both', padx=6, pady=4, expand=True)

gain_label = tk.Label(ge_frame, text="Gain :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
gain_label.grid(row=0, column=0, sticky='w', padx=2, pady=6)
gain_entry = ttk.Entry(ge_frame, width=12, font=ENTRY_FONT)
gain_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
gain_entry.insert(0, str(user_gain_val))
gain_apply_btn = ttk.Button(ge_frame, text="Apply", style="Apply.TButton", width=7)
gain_apply_btn.grid(row=0, column=2, sticky='w', padx=(4, 2), pady=6)

exp_label = tk.Label(ge_frame, text="Exposure(ms) :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
exp_label.grid(row=1, column=0, sticky='w', padx=2, pady=6)
exposure_entry = ttk.Entry(ge_frame, width=12, font=ENTRY_FONT)
exposure_entry.grid(row=1, column=1, sticky='w', padx=2, pady=6)
exposure_entry.insert(0, str(user_exposure_ms))
exp_apply_btn = ttk.Button(ge_frame, text="Apply", style="Apply.TButton", width=7)
exp_apply_btn.grid(row=1, column=2, sticky='w', padx=(4, 2), pady=6)

# 狀態提示：顯示上次套用的結果
cam_apply_status = tk.Label(ge_frame, text="", font=("times new roman", 10),
                             bg="#2B2B2B", fg="#888888", wraplength=340, justify="left")
cam_apply_status.grid(row=2, column=0, columnspan=3, sticky='w', padx=2, pady=(0, 4))

# ROI shape
roi_frame = tk.LabelFrame(right_frame, text="ROI 形狀 / ROI Shape",
                           padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                           bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
roi_frame.pack(fill='both', padx=6, pady=4, expand=True)

roi_shape_var = tk.StringVar(value='rect')
rb_rect_ui = tk.Radiobutton(roi_frame, text="Rectangle", variable=roi_shape_var, value='rect',
                              command=lambda: set_roi_shape('rect'),
                              font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0",
                              selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb_circle_ui = tk.Radiobutton(roi_frame, text="Circle", variable=roi_shape_var, value='circle',
                                command=lambda: set_roi_shape('circle'),
                                font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0",
                                selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb_rect_ui.pack(anchor='w', padx=6, pady=(2, 4), fill='x')
rb_circle_ui.pack(anchor='w', padx=6, pady=(2, 4), fill='x')

# ROI Size
roi_size_frame = tk.Frame(roi_frame, bg="#2B2B2B")
roi_size_frame.pack(fill='x', padx=6, pady=(6, 2))

tk.Label(roi_size_frame, text="Width (px):", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=4)
roi_width_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_width_entry.insert(0, "70")
roi_width_entry.grid(row=0, column=1, sticky='w', padx=2, pady=4)

tk.Label(roi_size_frame, text="Height (px):", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=1, column=0, sticky='w', padx=2, pady=4)
roi_height_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_height_entry.insert(0, "70")
roi_height_entry.grid(row=1, column=1, sticky='w', padx=2, pady=4)

tk.Label(roi_size_frame, text="Diameter (px):", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=2, column=0, sticky='w', padx=2, pady=4)
roi_diameter_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_diameter_entry.insert(0, "50")
roi_diameter_entry.grid(row=2, column=1, sticky='w', padx=2, pady=4)

tk.Label(roi_size_frame, text="(設定後用滑鼠拖動放置ROI)\n(Set size, then drag to place ROI)",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888"
         ).grid(row=3, column=0, columnspan=2, sticky='w', padx=2, pady=(4, 0))

# ── 自動 ROI 格線 / Auto ROI grid ─────────────────────────────
auto_frame = tk.Frame(roi_frame, bg="#2B2B2B")
auto_frame.pack(fill='x', padx=6, pady=(8, 2))

# 影像類型模式選擇
tk.Label(auto_frame, text="影像類型 / Image type:", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#00BFFF").grid(row=0, column=0, columnspan=2,
                                          sticky='w', padx=2, pady=(2, 0))

auto_mode_var = tk.StringVar(value='spot')

rb_mode_spot = tk.Radiobutton(
    auto_frame, text="A. 實心亮點（螢光圓斑）/ Filled spots",
    variable=auto_mode_var, value='spot',
    font=("times new roman", 11), bg="#2B2B2B", fg="#E0E0E0",
    selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00FF7F",
    anchor='w', justify='left')
rb_mode_spot.grid(row=1, column=0, columnspan=2, sticky='w', padx=12)

rb_mode_square = tk.Radiobutton(
    auto_frame, text="B. 方框輪廓（明暗差異大）/ Square outlines",
    variable=auto_mode_var, value='square',
    font=("times new roman", 11), bg="#2B2B2B", fg="#E0E0E0",
    selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00FF7F",
    anchor='w', justify='left')
rb_mode_square.grid(row=2, column=0, columnspan=2, sticky='w', padx=12)

tk.Label(auto_frame, text="Rows:", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=3, column=0, sticky='w', padx=2, pady=4)
grid_rows_entry = ttk.Entry(auto_frame, width=6, font=ENTRY_FONT)
grid_rows_entry.insert(0, "1")
grid_rows_entry.grid(row=3, column=1, sticky='w', padx=2, pady=4)

tk.Label(auto_frame, text="Columns:", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=4, column=0, sticky='w', padx=2, pady=4)
grid_cols_entry = ttk.Entry(auto_frame, width=6, font=ENTRY_FONT)
grid_cols_entry.insert(0, "6")
grid_cols_entry.grid(row=4, column=1, sticky='w', padx=2, pady=4)

auto_roi_btn = ttk.Button(auto_frame, text="自動放置 ROI / Auto-place ROI", style="Apply.TButton")
auto_roi_btn.grid(row=5, column=0, columnspan=2, sticky='we', padx=2, pady=(6, 2))

auto_mode_hint = tk.Label(
    auto_frame,
    text=("A：樣本為實心亮斑、背景暗且均勻 → 門檻分割 + 分群\n"
          "B：樣本為方框輪廓、各格亮度差異大 → 梯度 + 模板匹配\n"
          "(右鍵拖曳可微調任一 ROI)"),
    font=("times new roman", 9), bg="#2B2B2B", fg="#888888", justify="left")
auto_mode_hint.grid(row=6, column=0, columnspan=2, sticky='w', padx=2, pady=(2, 0))

roi_save_btn = ttk.Button(auto_frame, text="存 ROI / Save ROIs", style="Apply.TButton")
roi_save_btn.grid(row=7, column=0, sticky='we', padx=2, pady=(6, 2))
roi_load_btn = ttk.Button(auto_frame, text="載入 ROI / Load ROIs", style="Apply.TButton")
roi_load_btn.grid(row=7, column=1, sticky='we', padx=2, pady=(6, 2))

# Decimal places
dec_frame = tk.LabelFrame(right_frame, text="顯示精度 / Display Precision",
                           padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                           bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
dec_frame.pack(fill='both', padx=6, pady=4, expand=True)
tk.Label(dec_frame, text="Decimal places :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
dec_entry = ttk.Entry(dec_frame, width=6, font=ENTRY_FONT)
dec_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
dec_entry.insert(0, "2")

# ── 去亮反光 UI (De-glint) ─────────────────────────────────────────────────────
mf_frame = tk.LabelFrame(right_frame, text="去亮反光 / De-glint",
                          padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                          bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
mf_frame.pack(fill='both', padx=6, pady=4, expand=True)

deglint_enable_var = tk.BooleanVar(value=False)
deglint_check = tk.Checkbutton(mf_frame, text="去亮反光 / De-glint (auto)",
                               variable=deglint_enable_var,
                               command=lambda: toggle_deglint(),
                               font=RADIO_FONT, bg="#2B2B2B", fg="#E0E0E0",
                               selectcolor="#2B2B2B", activebackground="#2B2B2B",
                               activeforeground="#00BFFF", anchor="w")
deglint_check.pack(anchor='w', padx=4, pady=(2, 2), fill='x')
tk.Label(mf_frame,
         text="自動丟棄 ROI 內明顯過亮的離群像素；免設門檻，專打小面積反光。",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888",
         wraplength=360, justify="left").pack(anchor='w', padx=4, pady=(0, 2))
tk.Label(mf_frame,
         text="Auto-rejects bright outliers inside each ROI; no threshold needed.",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888",
         wraplength=360, justify="left").pack(anchor='w', padx=4, pady=(0, 4))
deglint_status_label = tk.Label(mf_frame, text="未啟用 / Disabled",
                                font=("times new roman", 10), bg="#2B2B2B", fg="#888888",
                                wraplength=360, justify="left")
deglint_status_label.pack(anchor='w', padx=4, pady=(0, 2))

deglint_k_var = tk.DoubleVar(value=DEGLINT_K)
deglint_k_scale = tk.Scale(mf_frame, from_=1.0, to=5.0, resolution=0.1,
                           orient=tk.HORIZONTAL, variable=deglint_k_var,
                           label="K (top-hat 門檻;小=去更多,大=只去最亮)",
                           command=lambda v: _set_deglint_k(v), length=340,
                           bg="#2B2B2B", fg="#E0E0E0", troughcolor="#444",
                           highlightthickness=0, font=("Arial", 9))
deglint_k_scale.pack(fill='x', padx=4, pady=(2, 2))
deglint_k_scale.bind("<ButtonRelease-1>", lambda e: _refresh_deglint_preview_if_open(e))
deglint_preview_btn = ttk.Button(mf_frame, text="預覽去除效果 / Preview De-glint",
                                 style="Apply.TButton",
                                 command=lambda: show_deglint_preview())
deglint_preview_btn.pack(fill='x', padx=4, pady=(2, 4))
deglint_show_var = tk.BooleanVar(value=False)
deglint_show_check = tk.Checkbutton(mf_frame, text="主畫面標紅去除點 / Show removed on live view",
                                    variable=deglint_show_var,
                                    command=lambda: _toggle_show_removed(),
                                    font=RADIO_FONT, bg="#2B2B2B", fg="#E0E0E0",
                                    selectcolor="#2B2B2B", activebackground="#2B2B2B",
                                    activeforeground="#00BFFF", anchor="w")
deglint_show_check.pack(anchor='w', padx=4, pady=(0, 4), fill='x')

# ── 灰階分佈 / 對比增強 UI ────────────────────────────────────────────────────
level_frame = tk.LabelFrame(right_frame, text="灰階分佈 / Grey-level & Contrast",
                            padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                            bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
level_frame.pack(fill='both', padx=6, pady=4, expand=True)

tk.Label(level_frame,
         text="選取區域檢視灰階分佈，並將選定範圍拉伸為 0–255（僅影響顯示）。\n"
              "Select a region to view its histogram, then stretch the chosen range to 0–255 (display only).",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888",
         justify="left").pack(anchor='w', padx=4, pady=(2,4))

level_btn_row = tk.Frame(level_frame, bg="#2B2B2B"); level_btn_row.pack(fill='x', padx=4, pady=(0,4))
level_select_btn = ttk.Button(level_btn_row, text="選取區域 / Select Region", style="Apply.TButton")
level_select_btn.pack(side="left", expand=True, fill="x", padx=(0,2))
level_auto_btn   = ttk.Button(level_btn_row, text="自動對比 / Auto", style="Apply.TButton")
level_auto_btn.pack(side="left", expand=True, fill="x", padx=(2,2))
level_reset_btn  = ttk.Button(level_btn_row, text="重置對比 / Reset", style="Apply.TButton")
level_reset_btn.pack(side="left", expand=True, fill="x", padx=(2,0))

level_status_label = tk.Label(level_frame, text="", font=("times new roman", 10),
                              bg="#2B2B2B", fg="#888888", wraplength=360, justify="left")
level_status_label.pack(anchor='w', padx=4, pady=(0,2))


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


def _glint_mask(gray):
    """整張影像 White Top-hat:opening 抹掉大片亮區(樣本本體),殘留的小面積亮點
    (灰塵/反光)超過 mean + K·std 即判為反光。回傳整張的布林遮罩。"""
    k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DEGLINT_KERNEL, DEGLINT_KERNEL))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
    thf = th.astype(np.float32)
    return th > (thf.mean() + DEGLINT_K * thf.std())


def _roi_slice(shape, r):
    """回傳 ROI 在整張影像中的切片邊界 (y1, y2, x1, x2),與 get_roi_patch 相同裁切。"""
    h, w = shape[:2]
    if r[0] == 'rect':
        _, x1, y1, x2, y2 = r
        return (max(0, int(y1)), min(h, int(y2)), max(0, int(x1)), min(w, int(x2)))
    _, cx, cy, rad = r
    cx = int(round(cx)); cy = int(round(cy)); rad = int(round(rad))
    return (max(0, cy - rad), min(h, cy + rad), max(0, cx - rad), min(w, cx + rad))


def _deglint_overlay(display_frame, gray, r, glint_full):
    """在 display_frame 上把 ROI r 內被去除的反光像素染紅,回傳去除%。
    反光來自整張影像的 top-hat 遮罩 glint_full,只取此 ROI 的對應區塊。"""
    patch, cmask = get_roi_patch(gray, r)
    if patch is None or patch.size == 0:
        return 0.0
    y1, y2, x1, x2 = _roi_slice(gray.shape, r)
    reject = glint_full[y1:y2, x1:x2].copy()
    if reject.shape != patch.shape[:2]:
        return 0.0
    valid = np.ones(patch.shape[:2], bool)
    if cmask is not None:
        valid &= (cmask == 1)
    reject &= valid
    n_valid = int(valid.sum())
    pct = 100.0 * int(reject.sum()) / n_valid if n_valid else 0.0
    sub = display_frame[y1:y2, x1:x2]
    if sub.shape[:2] == reject.shape:
        sub[reject] = [255, 0, 0]
    return pct


def compute_roi_mean(patch, circle_mask=None, glint_sub=None):
    """圓形遮罩 → 排除 de-glint 反光像素(若啟用) → 平均。"""
    if patch is None or patch.size == 0:
        return 0.0

    valid = np.ones(patch.shape[:2], bool)
    if circle_mask is not None:
        valid &= (circle_mask == 1)

    # De-glint：整張影像 top-hat 的反光遮罩(此 ROI 對應區塊),被判為反光的像素不計入平均
    if deglint_enabled and glint_sub is not None and glint_sub.shape == valid.shape:
        valid &= ~glint_sub

    px = patch[valid]
    return float(np.mean(px)) if px.size > 0 else 0.0


# ── 邏輯函式 ─────────────────────────────────────────────────────────────────

def show_deglint_preview():
    """整張影像 top-hat 去反光,單一畫面三格:原圖 / 標紅(不納入計算) / 去掉的反光。"""
    global deglint_preview_win

    with frame_lock:
        frame = current_frame.copy() if current_frame is not None else None
    if frame is None:
        messagebox.showwarning("無影像 / No Frame", "尚未取得影像。\nNo frame available yet.")
        return

    gray   = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    reject = _glint_mask(gray)                    # 整張 top-hat 反光遮罩

    before   = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    marked   = before.copy(); marked[reject]  = [255, 0, 0]      # 標紅:這些不納入計算
    removed  = np.zeros_like(before); removed[reject] = [255, 0, 0]  # 只顯示被去掉的

    n_rej = int(reject.sum())
    ratio = 100.0 * n_rej / gray.size
    mb    = float(gray.mean())
    ma    = float(gray[~reject].mean()) if n_rej < gray.size else 0.0

    if deglint_preview_win is not None:
        try:
            deglint_preview_win.destroy()
        except Exception:
            pass

    deglint_preview_win = tk.Toplevel(root)
    deglint_preview_win.title("De-glint 去亮反光預覽 / De-glint Preview")
    deglint_preview_win.configure(bg="#1E1E1E")

    H, W = gray.shape[:2]
    scr_w = int(root.winfo_screenwidth()  * 0.94)
    scr_h = int(root.winfo_screenheight() * 0.70)
    SC = min((scr_w - 40) / (3.0 * W), scr_h / float(H))
    SC = max(0.05, min(SC, 4.0))
    dw, dh = max(1, int(W * SC)), max(1, int(H * SC))

    tk.Label(deglint_preview_win,
             text=f"整張影像 White Top-hat  |  kernel={DEGLINT_KERNEL}  K={DEGLINT_K:.2f}"
                  f"  |  去除 {n_rej} px ({ratio:.2f}%)  |  Mean {mb:.2f} → {ma:.2f} (Δ {ma-mb:+.2f})",
             font=("Arial", 12, "bold"), bg="#1E1E1E", fg="#00BFFF").pack(pady=(8, 2))
    tk.Label(deglint_preview_win,
             text="紅色 = 被判為反光的像素;不納入平均計算 / Red = glint pixels, excluded from the mean",
             font=("Arial", 10), bg="#1E1E1E", fg="#888888").pack(pady=(0, 6))

    row = tk.Frame(deglint_preview_win, bg="#1E1E1E"); row.pack(padx=8, pady=(0, 8))
    keep_refs = []
    for title, im in [("原圖 / Original",        before),
                      ("標紅(不計入) / Marked",  marked),
                      ("去掉的反光 / Removed",    removed)]:
        col = tk.Frame(row, bg="#1E1E1E"); col.pack(side="left", padx=5)
        tk.Label(col, text=title, font=("Arial", 11), bg="#1E1E1E", fg="#E0E0E0").pack(pady=(0, 3))
        big  = cv2.resize(im, (dw, dh), interpolation=cv2.INTER_AREA)
        tkim = ImageTk.PhotoImage(Image.fromarray(big)); keep_refs.append(tkim)
        lb = tk.Label(col, image=tkim, bg="#2B2B2B", bd=1, relief="solid"); lb.image = tkim; lb.pack()
    deglint_preview_win.keep_refs = keep_refs

    btnf = tk.Frame(deglint_preview_win, bg="#1E1E1E"); btnf.pack(fill="x", padx=10, pady=(0, 10))
    tk.Button(btnf, text="重新擷取 / Refresh", command=lambda: show_deglint_preview(),
              font=("Arial", 11), bg="#0078D4", fg="white",
              activebackground="#107C10", activeforeground="white", height=2
              ).pack(side="left", expand=True, fill="x", padx=(0, 4))
    tk.Button(btnf, text="關閉 / Close", command=deglint_preview_win.destroy,
              font=("Arial", 11), bg="#555555", fg="white",
              activebackground="#777777", activeforeground="white", height=2
              ).pack(side="left", expand=True, fill="x", padx=(4, 0))

    deglint_preview_win.update_idletasks()
    w = min(deglint_preview_win.winfo_reqwidth() + 20,  int(root.winfo_screenwidth()  * 0.96))
    h = min(deglint_preview_win.winfo_reqheight() + 20, int(root.winfo_screenheight() * 0.92))
    deglint_preview_win.geometry(f"{w}x{h}")


def toggle_deglint():
    global deglint_enabled
    deglint_enabled = deglint_enable_var.get()
    try:
        if deglint_enabled:
            deglint_status_label.config(text=f"已啟用 / Enabled (K={DEGLINT_K:.2f})", fg="#00FF7F")
            root.after(100, show_deglint_preview)
        else:
            deglint_status_label.config(text="未啟用 / Disabled", fg="#888888")
    except Exception:
        pass


def _set_deglint_k(v):
    """滑桿即時更新 K(便宜操作:只改值與狀態,不重建預覽視窗)。"""
    global DEGLINT_K
    try:
        DEGLINT_K = float(v)
    except Exception:
        return
    try:
        if deglint_enabled:
            deglint_status_label.config(text=f"已啟用 / Enabled (K={DEGLINT_K:.2f})", fg="#00FF7F")
    except Exception:
        pass


def _toggle_show_removed():
    global deglint_show_removed
    deglint_show_removed = deglint_show_var.get()


def _refresh_deglint_preview_if_open(*_):
    """放開滑鼠時才刷新預覽(避免每 0.1 步重建視窗卡頓)。"""
    try:
        if deglint_preview_win is not None and deglint_preview_win.winfo_exists():
            root.after(0, show_deglint_preview)
    except Exception:
        pass


def toggle_level_select():
    global level_mode, level_drawing, level_block
    if level_mode:
        level_mode = False; level_drawing = False
        level_select_btn.config(text="選取區域 / Select Region")
        level_status_label.config(text="", fg="#888888")
    else:
        level_mode = True; level_drawing = False; level_block = None
        level_select_btn.config(text="取消選取 / Cancel")
        level_status_label.config(text="在影像上拖曳選取區域\nDrag on the image to select a region",
                                  fg="#FFD700")


def show_level_window(x1, y1, x2, y2):
    global level_win
    with frame_lock:
        frame = current_frame.copy() if current_frame is not None else None
    if frame is None:
        messagebox.showwarning("無影像 / No Frame", "尚未取得影像。\nNo frame available.")
        return
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    region = gray[int(y1):int(y2), int(x1):int(x2)]
    if region.size == 0:
        messagebox.showwarning("區域無效 / Invalid", "選取區域無資料。\nEmpty region.")
        return

    try:
        if level_win is not None and level_win.winfo_exists():
            level_win.destroy()
    except Exception:
        pass

    level_win = tk.Toplevel(root)
    level_win.title("灰階分佈與對比 / Grey-level Distribution & Contrast")
    level_win['bg'] = "#1E1E1E"

    r_min = int(region.min()); r_max = int(region.max())
    init_lo = r_min if stretch_min is None else int(stretch_min)
    init_hi = r_max if stretch_max is None else int(stretch_max)
    if init_hi <= init_lo:
        init_lo, init_hi = r_min, max(r_min + 1, r_max)

    # 直方圖
    fig = Figure(figsize=(5.2, 2.6), dpi=100)
    ax  = fig.add_subplot(111)
    hist = cv2.calcHist([region], [0], None, [256], [0, 256]).flatten()
    ax.bar(np.arange(256), hist, width=1.0, color="#4FC3F7")
    ax.set_xlim(0, 255)
    _med = float(np.median(region))
    ax.axvline(_med, color="#00E5FF", lw=1.4, linestyle="--", label=f"median={_med:.0f}")
    ax.legend(fontsize=7, loc="upper right")
    ax.set_title("Grey-level histogram (selected region)", fontsize=9)
    ax.set_xlabel("Grey level", fontsize=8); ax.set_ylabel("Pixel count", fontsize=8)
    ax.tick_params(labelsize=7)
    vline_lo = ax.axvline(init_lo, color="#FF5252", lw=1.5)
    vline_hi = ax.axvline(init_hi, color="#FFD54F", lw=1.5)
    fig.tight_layout()
    canvas = FigureCanvasTkAgg(fig, master=level_win)
    canvas.get_tk_widget().pack(padx=10, pady=(10, 4))

    r_med = float(np.median(region))
    r_mad = float(np.median(np.abs(region.astype(np.float32) - r_med)))
    tk.Label(level_win,
        text=(f"Region {region.shape[1]}x{region.shape[0]} px  |  "
              f"min={r_min}  max={r_max}  mean={region.mean():.1f}  "
              f"median={r_med:.1f}  std={region.std():.1f}  MAD={r_mad:.1f}"),
        font=("Consolas", 10), bg="#1E1E1E", fg="#00FF7F").pack(pady=(0, 6))

    # 前後預覽（縮圖）
    prev_row = tk.Frame(level_win, bg="#1E1E1E"); prev_row.pack(pady=4)
    tk.Label(prev_row, text="Before", bg="#1E1E1E", fg="#E0E0E0", font=("Arial",9)).grid(row=0,column=0)
    tk.Label(prev_row, text="After",  bg="#1E1E1E", fg="#E0E0E0", font=("Arial",9)).grid(row=0,column=1)
    lbl_before = tk.Label(prev_row, bg="#1E1E1E"); lbl_before.grid(row=1, column=0, padx=6)
    lbl_after  = tk.Label(prev_row, bg="#1E1E1E"); lbl_after.grid(row=1, column=1, padx=6)

    PW = 220
    ratio = PW / max(1, region.shape[1])
    ph = max(1, int(region.shape[0] * ratio))
    before_small = cv2.resize(region, (PW, ph), interpolation=cv2.INTER_NEAREST)
    before_tk = ImageTk.PhotoImage(Image.fromarray(before_small))
    lbl_before.configure(image=before_tk); lbl_before.image = before_tk
    refs = {"after": None}

    lo_var = tk.IntVar(value=init_lo); hi_var = tk.IntVar(value=init_hi)

    def _refresh(*_):
        lo = lo_var.get(); hi = hi_var.get()
        if hi <= lo:
            hi = lo + 1; hi_var.set(hi)
        vline_lo.set_xdata([lo, lo]); vline_hi.set_xdata([hi, hi])
        canvas.draw_idle()
        out = np.clip((before_small.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        aftk = ImageTk.PhotoImage(Image.fromarray(out)); refs["after"] = aftk
        lbl_after.configure(image=aftk); lbl_after.image = aftk

    sld = tk.Frame(level_win, bg="#1E1E1E"); sld.pack(fill="x", padx=14, pady=6)
    tk.Scale(sld, from_=0, to=255, orient=tk.HORIZONTAL, variable=lo_var,
             label="Min grey → 0", command=_refresh, length=460,
             bg="#1E1E1E", fg="#FF5252", troughcolor="#444", highlightthickness=0).pack(fill="x")
    tk.Scale(sld, from_=0, to=255, orient=tk.HORIZONTAL, variable=hi_var,
             label="Max grey → 255", command=_refresh, length=460,
             bg="#1E1E1E", fg="#FFD54F", troughcolor="#444", highlightthickness=0).pack(fill="x")

    def _apply():
        global stretch_enabled, stretch_min, stretch_max
        lo = lo_var.get(); hi = hi_var.get()
        if hi <= lo:
            messagebox.showwarning("範圍錯誤 / Invalid range", "Max 必須大於 Min。\nMax must exceed Min.")
            return
        stretch_min = lo; stretch_max = hi; stretch_enabled = True
        level_status_label.config(text=f"對比已套用 / Applied: [{lo}, {hi}] → [0,255]", fg="#00FF7F")

    btnf = tk.Frame(level_win, bg="#1E1E1E"); btnf.pack(fill="x", padx=14, pady=(6,12))
    tk.Button(btnf, text="套用 / Apply", command=_apply, bg="#0078D4", fg="white",
              activebackground="#107C10", activeforeground="white", font=("Arial",11), height=2
              ).pack(side="left", expand=True, fill="x", padx=(0,4))
    tk.Button(btnf, text="重置 / Reset", command=lambda: (_reset_stretch_global()),
              bg="#555", fg="white", activebackground="#777", activeforeground="white",
              font=("Arial",11), height=2).pack(side="left", expand=True, fill="x", padx=4)
    tk.Button(btnf, text="關閉 / Close", command=level_win.destroy, bg="#555", fg="white",
              activebackground="#777", activeforeground="white", font=("Arial",11), height=2
              ).pack(side="left", expand=True, fill="x", padx=(4,0))

    _refresh()

def set_roi_shape(shape):
    global roi_shape_choice
    roi_shape_choice = shape
    roi_shape_var.set(shape)
    validate_start_enable()

def apply_gain_and_exposure_to_camera(gain_val, exposure_ms):
    global cam

    ok_gain = False
    ok_exp  = False

    if is_image_mode():
        # 匯入圖片模式沒有相機，Gain/Exposure 不適用
        return False, False

    if is_ximea():
        try:
            # ── camera_lock 保護整個 stop → set → start 序列 ──────────────────
            with camera_lock:
                try:
                    cam.stop_acquisition()
                    print("[camera] XIMEA acquisition stopped")
                except Exception as e:
                    print(f"[camera] stop_acquisition warning: {e}")

                try:
                    cam.set_gain(float(gain_val))
                    ok_gain = True
                    print(f"[camera] XIMEA gain = {gain_val} dB")
                except Exception as e:
                    print(f"[camera] XIMEA set_gain failed: {e}")

                try:
                    exposure_us = int(exposure_ms * 1000)
                    cam.set_exposure(exposure_us)
                    ok_exp = True
                    print(f"[camera] XIMEA exposure = {exposure_us} µs ({exposure_ms} ms)")
                except Exception as e:
                    print(f"[camera] XIMEA set_exposure failed: {e}")

                try:
                    actual_exp  = cam.get_exposure()
                    actual_gain = cam.get_gain()
                    print(f"[camera] 確認讀回 — exposure={actual_exp} µs, gain={actual_gain} dB")
                except Exception:
                    pass

                try:
                    cam.start_acquisition()
                    print("[camera] XIMEA acquisition restarted")
                except Exception as e:
                    print(f"[camera] start_acquisition failed: {e}")

        except Exception as e:
            print(f"[camera] XIMEA apply settings error: {e}")

    elif CAMERA_TYPE == "THORLABS":
        try:
            if hasattr(cam, "set_gain"):
                cam.set_gain(float(gain_val))
                ok_gain = True
        except Exception as e:
            print(f"[camera] Thorlabs set_gain failed: {e}")

        try:
            cam.set_exposure(exposure_ms / 1000.0)
            ok_exp = True
            print(f"[camera] Thorlabs exposure = {exposure_ms/1000.0} s")
        except Exception as e:
            print(f"[camera] Thorlabs set_exposure failed: {e}")

    return ok_gain, ok_exp

def on_gain_exposure_change(event=None):
    global analyzing, user_gain_val, user_exposure_ms, cam, CAMERA_TYPE

    append_log(f"[DEBUG] on_gain_exposure_change 被觸發: analyzing={analyzing}, cam is None={cam is None}, CAMERA_TYPE={CAMERA_TYPE}")

    if not analyzing or cam is None:
        append_log(f"[DEBUG] 跳過應用: analyzing={analyzing}, cam={cam}")
        return

    try:
        gain_text     = gain_entry.get().strip()
        exposure_text = exposure_entry.get().strip()

        append_log(f"[DEBUG] 讀取UI值: Gain={gain_text}, Exposure={exposure_text}")

        if gain_text and exposure_text:
            gain_val     = float(gain_text)
            exposure_val = float(exposure_text)

            append_log(f"[DEBUG] 應用設定到相機: Gain={gain_val}, Exposure={exposure_val}ms, Camera Type={CAMERA_TYPE}")

            ok_gain, ok_exp = apply_gain_and_exposure_to_camera(gain_val, exposure_val)

            append_log(f"[DEBUG] 應用結果 - Gain: {ok_gain}, Exposure: {ok_exp}")

            if ok_gain:
                user_gain_val = gain_val
            if ok_exp:
                user_exposure_ms = exposure_val

    except Exception as e:
        append_log(f"[DEBUG] on_gain_exposure_change 例外: {str(e)}")

def validate_start_enable(event=None):
    dec_ok  = bool(dec_entry.get().strip())
    roi_ok  = len(rois) > 0
    if is_image_mode():
        # 匯入圖片模式：Gain/Exposure 不需填（沒有相機）
        gain_ok = exp_ok = True
    else:
        gain_ok = bool(gain_entry.get().strip())
        exp_ok  = bool(exposure_entry.get().strip())
    if gain_ok and exp_ok and dec_ok and roi_ok:
        start_btn.config(state="normal")
    else:
        start_btn.config(state="disabled")

for widget in (gain_entry, exposure_entry, dec_entry,
               roi_width_entry, roi_height_entry, roi_diameter_entry):
    widget.bind("<KeyRelease>", validate_start_enable)
gain_entry.bind("<FocusOut>", on_gain_exposure_change)
exposure_entry.bind("<FocusOut>", on_gain_exposure_change)
rb_rect_ui.config(command=lambda: (set_roi_shape('rect'), validate_start_enable()))
rb_circle_ui.config(command=lambda: (set_roi_shape('circle'), validate_start_enable()))

def start_button_handler():
    global analyzing, roi_selected, roi_locked, decimal_places
    global user_gain_val, user_exposure_ms, settings_applied

    img_mode = is_image_mode()

    # 匯入圖片模式不需要 Gain/Exposure
    required = [dec_entry.get().strip()]
    if not img_mode:
        required += [gain_entry.get().strip(), exposure_entry.get().strip()]
    if not all(required):
        msg = ("請確認 Decimal places 已填寫。\n"
               "Please ensure Decimal places is filled."
               if img_mode else
               "請確認 Gain、Exposure 與 Decimal places 都已填寫。\n"
               "Please ensure Gain, Exposure and Decimal places are filled.")
        messagebox.showwarning("設定未填齊 / Missing settings", msg)
        return

    try:
        dec_v = int(dec_entry.get().strip())
        if dec_v < 0 or dec_v > 10:
            raise ValueError
    except Exception:
        messagebox.showwarning("小數位錯誤 / Invalid decimal places",
                               "請輸入 0~10 的整數作為小數位數。\nPlease enter an integer 0~10 for decimal places.")
        return

    if img_mode:
        gain_v = 0.0
        exp_v  = 0.0
    else:
        try:
            gain_v = float(gain_entry.get().strip())
        except Exception:
            messagebox.showwarning("Gain 格式錯誤 / Invalid Gain", "Gain 必須為數字。\nGain must be a number.")
            return

        try:
            exp_v = float(exposure_entry.get().strip())
        except Exception:
            messagebox.showwarning("Exposure 格式錯誤 / Invalid Exposure",
                                   "Exposure 必須為數字。\nExposure must be a number.")
            return

    if len(rois) == 0:
        messagebox.showwarning("未選取 ROI / No ROI", "請至少選取一個 ROI。\nPlease select at least one ROI.")
        return

    summary = []
    if not img_mode:
        summary += [f"Gain: {gain_v}", f"Exposure（ms）: {exp_v}"]
    else:
        summary += [f"來源 / Source: {os.path.basename(image_path) if image_path else 'image'}"]
    summary += [
        f"Decimal places: {dec_v}",
        f"De-glint: {('ON (K=%.1f)' % DEGLINT_K) if deglint_enabled else 'OFF'}",
    ]

    summary +=["", "請確認以上設定再開始偵測。\nPlease confirm the settings before starting."]
    if not messagebox.askokcancel("確認設定 / Confirm settings", "\n".join(summary)):
        return

    user_gain_val    = gain_v
    user_exposure_ms = exp_v
    decimal_places   = dec_v
    settings_applied = True

    apply_gain_and_exposure_to_camera(user_gain_val, user_exposure_ms)

    roi_locked = True
    save_roi_layout(silent=True)   # 第一次量測自動記錄 ROI 座標
    default_btn.state(["disabled"])
    gain_entry.config(state="disabled")
    exposure_entry.config(state="disabled")
    gain_apply_btn.config(state="disabled")
    exp_apply_btn.config(state="disabled")
    dec_entry.config(state="disabled")
    rb_rect_ui.config(state="disabled")
    rb_circle_ui.config(state="disabled")

    start_btn.config(text="停止 / Stop")
    analyzing = True
    initialize_plot_area(len(rois))
    threading.Thread(target=analysis_loop, daemon=True).start()

def on_start():
    if start_btn["text"].startswith("開始") or start_btn["text"].startswith("Start"):
        start_button_handler()
    elif start_btn["text"].startswith("停止") or start_btn["text"].startswith("Stop"):
        global analyzing
        analyzing = False
        start_btn["text"] = "重新啟動偵測 / Restart Detection"
    else:
        if plot_win:
            if not messagebox.askokcancel("確認重新開始 / Confirm restart",
                                          "確定要清空資料並重新偵測嗎？\nAre you sure you want to clear data and restart detection?"):
                return
            try:
                plot_win.destroy()
            except Exception:
                pass

        rois.clear()
        roi_selected = False
        roi_data.clear()
        timestamps.clear()
        start_btn["text"] = "開始 / Start"
        default_btn.state(["!disabled"])

        global roi_locked, user_gain_val, user_exposure_ms
        global decimal_places, settings_applied
        roi_locked = False

        dec_entry.config(state="normal")
        rb_rect_ui.config(state="normal")
        rb_circle_ui.config(state="normal")

        # ── De-glint 重置 ──
        deglint_check.config(state="normal")
        deglint_preview_btn.config(state="normal")
        deglint_k_scale.config(state="normal")
        deglint_k_var.set(3.0)
        _set_deglint_k(3.0)
        deglint_show_check.config(state="normal")
        deglint_show_var.set(False)
        _toggle_show_removed()
        deglint_enable_var.set(False)
        toggle_deglint()

        dec_entry.delete(0, tk.END)
        dec_entry.insert(0, "2")

        if is_image_mode():
            # 圖片模式：Gain/Exposure 維持停用，重新套用圖片模式 UI 預設
            setup_ui_for_image_mode()
        else:
            gain_entry.config(state="normal")
            exposure_entry.config(state="normal")
            gain_apply_btn.config(state="normal")
            exp_apply_btn.config(state="normal")

            gain_entry.delete(0, tk.END)
            gain_entry.insert(0, "0.0")

            exposure_entry.delete(0, tk.END)
            exposure_entry.insert(0, str(user_exposure_ms))

            apply_defaults_on_restart_camera()

        user_gain_val    = None
        user_exposure_ms = None
        decimal_places   = None
        settings_applied = False
        start_btn.config(state="disabled")
        messagebox.showinfo("已重置 / Restarted",
                            "已清空資料並重置設定，可重新設定並選取 ROI。\nData cleared and settings reset.")

def on_default():
    global rois, roi_data, timestamps, roi_selected
    if roi_locked:
        messagebox.showinfo("ROI 已鎖定 / ROI Locked",
                            "請先 Restart 才能重新選取 ROI。\nROI is locked; restart to reselect.")
        return
    rois.clear()
    roi_data.clear()
    timestamps.clear()
    roi_selected = False
    validate_start_enable()


# ── 即時套用 Gain / Exposure（不需要開始偵測）────────────────────────────────

def _do_apply_camera_preview(apply_gain=True, apply_exp=True):
    """從 UI 讀取 Gain / Exposure，立刻套用到相機並更新狀態標籤。
    不需要 analyzing=True；相機初始化後隨時可呼叫。"""
    global user_gain_val, user_exposure_ms

    if is_image_mode():
        cam_apply_status.config(
            text="匯入圖片模式：Gain/Exposure 不適用。\nImage mode: Gain/Exposure not applicable.",
            fg="#888888")
        return

    if cam is None:
        cam_apply_status.config(text="相機尚未初始化 / Camera not initialized.", fg="#FF4444")
        return

    gain_text = gain_entry.get().strip()
    exp_text  = exposure_entry.get().strip()

    try:
        gain_v = float(gain_text) if gain_text else user_gain_val
    except ValueError:
        cam_apply_status.config(text="Gain 格式錯誤 / Invalid Gain value.", fg="#FF4444")
        return
    try:
        exp_v = float(exp_text) if exp_text else user_exposure_ms
    except ValueError:
        cam_apply_status.config(text="Exposure 格式錯誤 / Invalid Exposure value.", fg="#FF4444")
        return

    cam_apply_status.config(text="套用中… / Applying…", fg="#FFD700")
    root.update_idletasks()

    def _worker():
        ok_gain, ok_exp = apply_gain_and_exposure_to_camera(
            gain_v  if apply_gain else user_gain_val,
            exp_v   if apply_exp  else user_exposure_ms,
        )
        if apply_gain and ok_gain:
            globals()["user_gain_val"]    = gain_v
        if apply_exp  and ok_exp:
            globals()["user_exposure_ms"] = exp_v

        def _update_ui():
            parts = []
            if apply_gain:
                parts.append(f"Gain {'✓' if ok_gain else '✗'} {gain_v} dB")
            if apply_exp:
                parts.append(f"Exp {'✓' if ok_exp else '✗'} {exp_v} ms")
            all_ok = (ok_gain if apply_gain else True) and (ok_exp if apply_exp else True)
            cam_apply_status.config(
                text="  |  ".join(parts),
                fg="#00FF7F" if all_ok else "#FF8C00"
            )
        root.after(0, _update_ui)

    threading.Thread(target=_worker, daemon=True).start()

gain_apply_btn.config(command=lambda: _do_apply_camera_preview(apply_gain=True,  apply_exp=False))
exp_apply_btn.config( command=lambda: _do_apply_camera_preview(apply_gain=False, apply_exp=True))


# ── 滑鼠事件 ──────────────────────────────────────────────────────────────────

def on_mouse_down(event):
    global start_x, start_y, dragging, roi_dragging_offset_x, roi_dragging_offset_y
    global roi_fixed_width, roi_fixed_height, roi_fixed_diameter
    global level_drawing, level_start_x, level_start_y, level_block

    if level_mode:
        level_drawing = True
        lx, ly = evt_to_img(event.x, event.y)
        level_start_x = lx; level_start_y = ly
        level_block = (lx, ly, lx, ly)
        return

    if (not analyzing) and (not roi_locked):
        try:
            if roi_shape_var.get() == 'rect':
                roi_fixed_width  = int(roi_width_entry.get())
                roi_fixed_height = int(roi_height_entry.get())
                if roi_fixed_width <= 0 or roi_fixed_height <= 0:
                    messagebox.showwarning("無效輸入 / Invalid Input", "寬度和高度必須大於0。\nWidth and height must be > 0.")
                    return
            else:
                roi_fixed_diameter = int(roi_diameter_entry.get())
                if roi_fixed_diameter <= 0:
                    messagebox.showwarning("無效輸入 / Invalid Input", "直徑必須大於0。\nDiameter must be > 0.")
                    return
        except ValueError:
            messagebox.showwarning("無效輸入 / Invalid Input", "請輸入有效的數字。\nPlease enter valid numbers.")
            return
        start_x, start_y = evt_to_img(event.x, event.y)
        dragging = True
        roi_dragging_offset_x = 0
        roi_dragging_offset_y = 0

def on_mouse_move(event):
    global end_x, end_y, roi_dragging_offset_x, roi_dragging_offset_y
    global level_block

    if level_mode and level_drawing and level_block is not None:
        mx, my = evt_to_img(event.x, event.y)
        level_block = (level_start_x, level_start_y, mx, my)
        return

    if dragging:
        roi_dragging_offset_x = event.x - start_x
        roi_dragging_offset_y = event.y - start_y

def on_mouse_up(event):
    global roi_selected, dragging, roi_fixed_width, roi_fixed_height, roi_fixed_diameter
    global level_mode, level_drawing, level_block

    if level_mode and level_drawing:
        level_drawing = False
        mx, my = evt_to_img(event.x, event.y)
        x1 = min(level_start_x, mx); x2 = max(level_start_x, mx)
        y1 = min(level_start_y, my); y2 = max(level_start_y, my)
        level_mode = False
        level_select_btn.config(text="選取區域 / Select Region")
        if (x2 - x1) >= 5 and (y2 - y1) >= 5:
            level_block = (x1, y1, x2, y2)
            show_level_window(x1, y1, x2, y2)
        else:
            level_block = None
            level_status_label.config(text="區域太小，請重選。\nRegion too small.", fg="#FF4444")
        return

    if not dragging:
        return
    dragging = False
    try:
        if roi_shape_var.get() == 'rect':
            x1 = max(img_pad_x, min(img_pad_x + img_disp_w - roi_fixed_width,  start_x))
            y1 = max(img_pad_y, min(img_pad_y + img_disp_h - roi_fixed_height, start_y))
            rois.append(('rect', x1, y1, x1 + roi_fixed_width, y1 + roi_fixed_height))
            roi_selected = True
        else:
            r  = roi_fixed_diameter // 2
            cx = max(img_pad_x + r, min(img_pad_x + img_disp_w - r, start_x))
            cy = max(img_pad_y + r, min(img_pad_y + img_disp_h - r, start_y))
            rois.append(('circle', cx, cy, r))
            roi_selected = True
    except Exception as e:
        messagebox.showerror("錯誤 / Error", f"建立ROI時發生錯誤：{str(e)}\nError creating ROI: {str(e)}")
        return
    validate_start_enable()

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
def apply_display_stretch(gray):
    """僅供顯示：把 [stretch_min, stretch_max] 線性拉伸到 [0,255]。不影響量測值。"""
    if not stretch_enabled or stretch_min is None or stretch_max is None:
        return gray
    lo = float(stretch_min); hi = float(stretch_max)
    if hi <= lo:
        return gray
    out = (gray.astype(np.float32) - lo) * (255.0 / (hi - lo))
    return np.clip(out, 0, 255).astype(np.uint8)


def _auto_stretch_global():
    """Auto 對比：取整張畫面 1~99 百分位當 min/max 做線性拉伸（僅顯示，量測不受影響）。"""
    global stretch_enabled, stretch_min, stretch_max
    with frame_lock:
        frame = current_frame.copy() if current_frame is not None else None
    if frame is None:
        try: level_status_label.config(text="尚無影像 / No frame", fg="#FFA500")
        except Exception: pass
        return
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    lo = float(np.percentile(gray, 1.0))
    hi = float(np.percentile(gray, 99.0))
    if hi <= lo:
        hi = lo + 1.0
    stretch_min = lo; stretch_max = hi; stretch_enabled = True
    try:
        level_status_label.config(
            text=f"Auto 對比 / Auto-contrast: {int(lo)}–{int(hi)} → 0–255", fg="#00FF7F")
    except Exception:
        pass


def _reset_stretch_global():
    global stretch_enabled, stretch_min, stretch_max
    stretch_enabled = False; stretch_min = None; stretch_max = None
    try:
        level_status_label.config(text="對比已重置 / Contrast reset", fg="#888888")
    except Exception:
        pass

def _auto_grid_positions(centroids, R, C, w, h):
    """Cluster blob centroids into C column-x and R row-y positions (sub-image coords)."""
    cx = np.array([c[0] for c in centroids], dtype=np.float32)
    cy = np.array([c[1] for c in centroids], dtype=np.float32)

    def cluster_1d(vals, k, span):
        vals = vals.reshape(-1, 1).astype(np.float32)
        if len(vals) >= k and k > 1:
            crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
            _, _, centers = cv2.kmeans(vals, k, None, crit, 5, cv2.KMEANS_PP_CENTERS)
            return sorted(float(c) for c in centers.flatten())
        if k == 1:
            return [float(vals.mean())] if len(vals) else [span / 2.0]
        return list(np.linspace(vals.min(), vals.max(), k)) if len(vals) else \
               list(np.linspace(0, span, k))

    return cluster_1d(cx, C, w), cluster_1d(cy, R, h)


# ══════════════════════════════════════════════════════════════════
# 模式 A：實心亮點 —— 背景平坦化 + Otsu + 連通元件 + k-means
# ══════════════════════════════════════════════════════════════════
def _auto_grid_positions(centroids, R, C, w, h):
    cx = np.array([c[0] for c in centroids], dtype=np.float32)
    cy = np.array([c[1] for c in centroids], dtype=np.float32)

    def cluster_1d(vals, k, span):
        vals = vals.reshape(-1, 1).astype(np.float32)
        if len(vals) >= k and k > 1:
            crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
            _, _, centers = cv2.kmeans(vals, k, None, crit, 5, cv2.KMEANS_PP_CENTERS)
            return sorted(float(c) for c in centers.flatten())
        if k == 1:
            return [float(vals.mean())] if len(vals) else [span / 2.0]
        if len(vals):
            return list(np.linspace(float(vals.min()), float(vals.max()), k))
        return list(np.linspace(0, span, k))

    return cluster_1d(cx, C, w), cluster_1d(cy, R, h)


def _detect_mode_spot(sub, R, C):
    """模式 A。回傳 (col_x, row_y, 訊息) —— 座標相對 sub 左上角。"""
    Hs, Ws = sub.shape[:2]
    cell = min(Ws / C, Hs / R)
    ca = cell ** 2
    target = R * C

    best = None
    for sigma_cell in (0.2, 0.3, 0.4, 0.5, 0.75, 1.0):
        bg = cv2.GaussianBlur(sub, (0, 0), sigmaX=cell * sigma_cell)
        # 負值截 0：否則 NORM_MINMAX 會把「等於背景」映到中間灰階，
        # 導致 Otsu 把整片背景誤判為前景
        d = np.clip(sub.astype(np.int16) - bg.astype(np.int16), 0, None).astype(np.uint8)
        lo = np.percentile(d, 1.0); hi = np.percentile(d, 99.0)
        if hi <= lo:
            hi = lo + 1
        norm8 = (np.clip((d.astype(np.float32) - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
        _, bw = cv2.threshold(cv2.GaussianBlur(norm8, (5, 5), 0), 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if 100.0 * (bw > 0).sum() / bw.size > 45:      # 背景被誤判，跳過
            continue

        ok = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, ok, iterations=1)
        for cf in (0.0, 0.03, 0.05, 0.08, 0.10, 0.13, 0.15, 0.18, 0.20):
            if cf > 0:
                cs = int(np.clip(cell * cf, 3, 35)) | 1
                ck = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cs, cs))
                closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, ck, iterations=2)
            else:
                closed = opened
            # 填洞：封閉的中空結構補成實心 → 質心＝幾何中心
            ff = closed.copy()
            ffm = np.zeros((Hs + 2, Ws + 2), np.uint8)
            cv2.floodFill(ff, ffm, (0, 0), 255)
            solid = closed | cv2.bitwise_not(ff)

            n, _, stats, cents = cv2.connectedComponentsWithStats(solid, connectivity=8)
            # 面積基準用 cell^2 而非 blob 中位數：灰塵多於真樣本時，
            # 中位數會落在灰塵區間，真樣本反而被當成「太大」剔除
            good = [(float(cents[i][0]), float(cents[i][1]), float(stats[i, cv2.CC_STAT_AREA]))
                    for i in range(1, n)
                    if 0.02 * ca <= stats[i, cv2.CC_STAT_AREA] <= 1.5 * ca]
            err = abs(len(good) - target)
            if good and (best is None or err < best[0]):
                best = (err, good, sigma_cell, cf)

    if best is None or not best[1]:
        return None, None, "模式 A 偵測不到樣本。請確認背景是否夠暗，或改用模式 B。"

    _, good, sig, cf = best
    areas   = np.array([g[2] for g in good], dtype=np.float32)
    spot_sz = int(2.0 * np.sqrt(np.median(areas) / np.pi)) if areas.size else None
    col_x, row_y = _auto_grid_positions(good, R, C, Ws, Hs)
    msg = (f"模式 A：偵測到 {len(good)} 個樣本（目標 {target}）\n"
           f"sigma={sig:.2f}  close={cf:.2f}")
    return col_x, row_y, msg, spot_sz


# ══════════════════════════════════════════════════════════════════
# 模式 B：方框輪廓 —— Sobel 梯度 + NCC 模板匹配
# ══════════════════════════════════════════════════════════════════
def _find_peaks_simple(sig, height, distance):
    idx = [i for i in range(1, len(sig) - 1)
           if sig[i] >= sig[i - 1] and sig[i] > sig[i + 1] and sig[i] >= height]
    idx.sort(key=lambda i: -sig[i])
    kept = []
    for i in idx:
        if all(abs(i - j) >= distance for j in kept):
            kept.append(i)
    return sorted(kept)


def _detect_mode_square(sub, R, C):
    """模式 B。回傳 (col_x, row_y, 訊息, 模板尺寸)。"""
    Hs, Ws = sub.shape[:2]
    target = R * C

    # 梯度幅值：把「亮度差異」問題轉成「邊緣結構」問題
    gx = cv2.Sobel(sub, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(sub, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.normalize(cv2.magnitude(gx, gy), None, 0, 255,
                        cv2.NORM_MINMAX).astype(np.uint8).astype(np.float32)

    # 依格數估計方框尺寸，在其附近搜尋
    est = min(Ws / C, Hs / R)
    cands = sorted({int(est * f) for f in (0.55, 0.65, 0.75, 0.85, 0.95)
                    if 12 <= int(est * f) < min(Hs, Ws) * 0.9})
    if not cands:
        return None, None, "影像太小，無法建立模板。", None

    best = None
    for s in cands:
        th = max(3, int(s * 0.04))
        tpl = np.zeros((s, s), np.float32)
        cv2.rectangle(tpl, (th, th), (s - th, s - th), 1.0, th)
        r = cv2.matchTemplate(mag, tpl * 255.0, cv2.TM_CCOEFF_NORMED)
        if best is None or r.max() > best[0]:
            best = (r.max(), s, r)
    score, sz, res = best

    # 列投影定位樣本帶（可一舉排除外圍干擾結構）
    rowmax = res.max(axis=1)
    if R == 1:
        bands = [int(np.argmax(rowmax))]
    else:
        thr = rowmax.max() * 0.4
        dist = max(5, int(res.shape[0] / (R * 2)))
        cand = _find_peaks_simple(rowmax, thr, dist)
        cand.sort(key=lambda y: -rowmax[y])
        bands = sorted(cand[:R])
        if len(bands) < R:
            base = bands if bands else [int(np.argmax(rowmax))]
            bands = sorted(set(base)) if len(base) >= R else \
                    list(np.linspace(min(base), max(base) + sz * (R - 1), R).astype(int))

    half = max(5, int(sz * 0.15))
    row_y, all_cols = [], []
    for by in bands:
        y0 = max(0, by - half); y1 = min(res.shape[0], by + half + 1)
        colmax = res[y0:y1, :].max(axis=0)
        thr = max(0.10, colmax.max() * 0.35)
        pk = _find_peaks_simple(colmax, thr, max(3, int(sz * 0.6)))
        pk.sort(key=lambda x: -colmax[x])       # 假峰分數天然較低
        chosen = sorted(pk[:C])
        if len(chosen) >= 2 and C > 2:
            # 等距擬合微調（利用格線規律性）
            xs = np.array(chosen, float); i = np.arange(len(xs))
            A = np.vstack([i, np.ones_like(i)]).T
            pitch, x0 = np.linalg.lstsq(A, xs, rcond=None)[0]
            chosen = [int(round(x0 + pitch * k)) for k in range(len(xs))]
        while len(chosen) < C and chosen:        # 不足則依既有間距外推
            p = (chosen[-1] - chosen[0]) / max(1, len(chosen) - 1)
            chosen.append(int(chosen[-1] + p))
        all_cols.append(chosen[:C])
        row_y.append(by + sz / 2.0)

    if not all_cols or not all_cols[0]:
        return None, None, "模式 B 偵測不到方框。請確認邊緣是否清晰。", None

    col_x = [float(np.mean([c[j] for c in all_cols if j < len(c)])) + sz / 2.0
             for j in range(C)]
    msg = (f"模式 B：模板 {sz}x{sz}  最高 NCC = {score:.3f}\n"
           f"偵測到 {len(bands)} 列 x {len(all_cols[0])} 行")
    return col_x, sorted(row_y), msg, sz


# ══════════════════════════════════════════════════════════════════
# 主入口：依使用者選的模式分派
# ══════════════════════════════════════════════════════════════════
def auto_detect_rois():
    global rois, roi_selected

    if roi_locked or analyzing:
        messagebox.showinfo("ROI 已鎖定 / Locked",
                            "偵測進行中無法自動放置，請先 Restart。\n"
                            "Cannot auto-place while running.")
        return

    try:
        R = int(grid_rows_entry.get().strip())
        C = int(grid_cols_entry.get().strip())
        if R <= 0 or C <= 0:
            raise ValueError
    except Exception:
        messagebox.showwarning("格線輸入錯誤 / Invalid grid",
                               "請輸入正整數的 Rows 與 Columns。\n"
                               "Enter positive integers.")
        return

    with frame_lock:
        frame = current_frame.copy() if current_frame is not None else None
    if frame is None:
        messagebox.showwarning("無影像 / No Frame",
                               "尚未取得影像。\nNo frame available yet.")
        return
    if frame.ndim == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    x0, y0 = img_pad_x, img_pad_y
    x1, y1 = img_pad_x + img_disp_w, img_pad_y + img_disp_h
    sub = frame[y0:y1, x0:x1]

    mode = auto_mode_var.get()
    tpl_sz = None
    spot_sz = None
    if mode == 'square':
        col_x, row_y, msg, tpl_sz = _detect_mode_square(sub, R, C)
    else:
        col_x, row_y, msg, spot_sz = _detect_mode_spot(sub, R, C)

    if col_x is None:
        messagebox.showwarning("偵測失敗 / Detection failed", msg)
        return

    # ROI 尺寸：模式 B 若使用者沒填則沿用偵測到的模板尺寸
    shape = roi_shape_var.get()
    rad = w = h = None
    try:
        if shape == 'circle':
            rad = max(2, int(roi_diameter_entry.get()) // 2)
        else:
            w = int(roi_width_entry.get()); h = int(roi_height_entry.get())
    except Exception:
        asz = None
        if mode == 'square' and tpl_sz:
            asz = int(tpl_sz)                       # square：用偵測到的模板尺寸
        elif spot_sz:
            asz = max(4, int(spot_sz * 0.45))       # spot：樣本 65%，置中不碰邊
        if asz is not None:
            def _min_gap(v):
                v = sorted(v)
                return min((v[k+1]-v[k] for k in range(len(v)-1)), default=1e9)
            cap = int(min(_min_gap(col_x), _min_gap(row_y)) * 0.9)
            if cap >= 6:
                asz = min(asz, cap)                 # 夾限：避免相鄰 ROI 重疊
            w = h = asz; rad = max(2, asz // 2)
        else:
            messagebox.showwarning("ROI 尺寸錯誤 / Invalid size",
                                   "請先填入有效的 ROI 尺寸。\nEnter a valid ROI size.")
            return

    new_rois = []
    for i in range(R):
        cy = row_y[i] + y0
        for j in range(C):
            cx = col_x[j] + x0
            if shape == 'circle':
                ccx = int(max(x0 + rad, min(x1 - rad, cx)))
                ccy = int(max(y0 + rad, min(y1 - rad, cy)))
                new_rois.append(('circle', ccx, ccy, rad))
            else:
                rx1 = int(max(x0, min(x1 - w, cx - w / 2)))
                ry1 = int(max(y0, min(y1 - h, cy - h / 2)))
                new_rois.append(('rect', rx1, ry1, rx1 + w, ry1 + h))

    if len(rois) > 0 and not messagebox.askokcancel(
            "覆蓋現有 ROI / Replace ROIs",
            f"將以 {R}x{C}={R*C} 個自動 ROI 覆蓋現有 {len(rois)} 個。\n"
            f"Replace {len(rois)} existing ROIs with {R*C} auto ROIs?"):
        return

    rois.clear(); rois.extend(new_rois)
    roi_selected = True
    validate_start_enable()
    messagebox.showinfo(
        "完成 / Done",
        f"{msg}\n\n已放置 {len(new_rois)} 個 ROI（{R} x {C}）。\n"
        f"右鍵拖曳可微調 / Right-drag to fine-tune.")

def on_right_mouse_down(event):
    global right_dragging, right_drag_roi_index, right_drag_start_x, right_drag_start_y, right_drag_roi_start_pos
    if (not analyzing) and (not roi_locked) and len(rois) > 0:
        roi_idx = get_roi_at_point(event.x, event.y)
        if roi_idx >= 0:
            right_dragging          = True
            right_drag_roi_index    = roi_idx
            right_drag_start_x      = event.x
            right_drag_start_y      = event.y
            right_drag_roi_start_pos = rois[roi_idx]

def on_right_mouse_move(event):
    global right_dragging, right_drag_roi_index, right_drag_start_x, right_drag_start_y, right_drag_roi_start_pos
    if not (right_dragging and 0 <= right_drag_roi_index < len(rois)):
        return
    dx = event.x - right_drag_start_x
    dy = event.y - right_drag_start_y
    try:
        if right_drag_roi_start_pos[0] == 'rect':
            _, x1, y1, x2, y2 = right_drag_roi_start_pos
            w, h = x2 - x1, y2 - y1
            nx1 = max(img_pad_x, min(img_pad_x + img_disp_w - w, x1 + dx))
            ny1 = max(img_pad_y, min(img_pad_y + img_disp_h - h, y1 + dy))
            rois[right_drag_roi_index] = ('rect', nx1, ny1, nx1 + w, ny1 + h)
        elif right_drag_roi_start_pos[0] == 'circle':
            _, cx, cy, r = right_drag_roi_start_pos
            rois[right_drag_roi_index] = (
                'circle',
                max(img_pad_x + r, min(img_pad_x + img_disp_w - r, cx + dx)),
                max(img_pad_y + r, min(img_pad_y + img_disp_h - r, cy + dy)),
                r
            )
    except Exception:
        pass

def on_right_mouse_up(event):
    global right_dragging, right_drag_roi_index, right_drag_roi_start_pos
    if not right_dragging or right_drag_roi_index < 0:
        return
    right_dragging           = False
    right_drag_roi_index     = -1
    right_drag_roi_start_pos = None

# ROI 座標檔集中放在程式(或打包後 exe)旁的 ROI_layouts 資料夾,與啟動目錄無關
APP_DIR  = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
ROI_DIR  = os.path.join(APP_DIR, "ROI_layouts")
ROI_LAST = "ROI_last.json"          # 開始量測時自動存的那份(每次覆蓋)
ROI_TYPES = [("ROI 座標檔 / ROI layout", "*.json"), ("All files", "*.*")]
last_csv_dir = None                 # 記住上次 CSV 存放的資料夾

def save_roi_layout(silent=False):
    """存目前 ROI(形狀+座標+大小)與座標空間資訊。
    silent=True:開始量測時自動存成 ROI_last.json;否則讓使用者自訂檔名。"""
    if not rois:
        if not silent:
            messagebox.showwarning("無 ROI / No ROI", "目前沒有 ROI 可存。\nNo ROI to save.")
        return
    try:
        os.makedirs(ROI_DIR, exist_ok=True)
    except Exception:
        pass
    if silent:
        path = os.path.join(ROI_DIR, ROI_LAST)
    else:
        path = filedialog.asksaveasfilename(
            title="儲存 ROI 座標 / Save ROI layout", initialdir=ROI_DIR,
            initialfile=f"ROI_{datetime.datetime.now():%Y%m%d_%H%M%S}.json",
            defaultextension=".json", filetypes=ROI_TYPES)
        if not path:
            return
    data = {
        "rois": [list(r) for r in rois],
        "camera_type": CAMERA_TYPE,
        "orig_w": orig_w, "orig_h": orig_h,
        "img_disp_w": img_disp_w, "img_disp_h": img_disp_h,
        "img_pad_x": img_pad_x, "img_pad_y": img_pad_y,
        "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        if not silent:
            messagebox.showerror("存檔失敗 / Save failed", str(e))
        return
    if not silent:
        messagebox.showinfo("已存 ROI / ROI saved",
                            f"{len(rois)} 個 ROI 已存到:\n{os.path.normpath(path)}")


def load_roi_layout():
    """讓使用者從之前存的 ROI 座標檔中挑一份載入;座標空間不符時先警告再決定是否套用。"""
    global roi_selected
    if roi_locked or analyzing:
        messagebox.showinfo("ROI 已鎖定 / Locked",
                            "執行中無法載入,請先 Restart。\nCannot load while running.")
        return
    path = filedialog.askopenfilename(
        title="選擇 ROI 座標檔 / Choose ROI layout",
        initialdir=ROI_DIR if os.path.isdir(ROI_DIR) else APP_DIR,
        filetypes=ROI_TYPES)
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        messagebox.showerror("讀取失敗 / Load failed", str(e)); return

    loaded = data.get("rois", [])
    if not loaded:
        messagebox.showwarning("無 ROI / Empty", "檔案內沒有 ROI。")
        return

    warn = ""
    if (data.get("img_disp_w"), data.get("img_disp_h"),
        data.get("img_pad_x"), data.get("img_pad_y")) != \
       (img_disp_w, img_disp_h, img_pad_x, img_pad_y):
        warn += "\n- 影像顯示範圍與存檔時不同(相機/解析度可能不同),ROI 位置可能偏移。"
    if data.get("camera_type") and data.get("camera_type") != CAMERA_TYPE:
        warn += f"\n- 相機不同(存檔:{data.get('camera_type')} / 目前:{CAMERA_TYPE})。"
    if warn and not messagebox.askokcancel("座標空間不符 / Mismatch",
                                           "座標空間與存檔時不同,仍要載入嗎?" + warn):
        return

    rois.clear()
    for r in loaded:
        shape = r[0]
        nums = [int(round(float(v))) for v in r[1:]]
        rois.append((shape, *nums))
    roi_selected = len(rois) > 0
    validate_start_enable()
    messagebox.showinfo("已載入 ROI / ROI loaded",
                        f"{os.path.basename(path)}\n"
                        f"載入 {len(rois)} 個 ROI（存檔時間 {data.get('saved_at','?')}）。")


def _ask_concentrations(n):
    """濃度輸入視窗:尾數 × 10^指數(-6 ~ -15)。回傳 (concs, mode) 或 None(取消)。"""
    EXPS = ["-6", "-7", "-8", "-9", "-10", "-11", "-12", "-13", "-14", "-15"]
    win = tk.Toplevel(root); win.title("輸入濃度 / Enter concentrations")
    win.configure(bg="#2B2B2B"); win.grab_set()
    mode_var = tk.StringVar(value="half")

    tk.Label(win, text=f"共 {n} 個樣本 / {n} samples  (Sample 1 = 第一個濃度)",
             bg="#2B2B2B", fg="#00BFFF", font=("Arial", 12, "bold")).pack(padx=12, pady=(10, 6))

    # 對半稀釋
    fb = tk.LabelFrame(win, text="", bg="#2B2B2B", fg="#E0E0E0", padx=6, pady=4)
    tk.Radiobutton(fb, text="對半稀釋 / Half-dilution(只填最高濃度,最後一點=空白)",
                   variable=mode_var, value="half", bg="#2B2B2B", fg="#E0E0E0",
                   selectcolor="#2B2B2B", command=lambda: _toggle()).grid(row=0, column=0, columnspan=4, sticky="w")
    tk.Label(fb, text="最高濃度 C0:", bg="#2B2B2B", fg="#E0E0E0").grid(row=1, column=0, sticky="e", padx=4, pady=4)
    e_top = tk.Entry(fb, width=10); e_top.grid(row=1, column=1, padx=2)
    tk.Label(fb, text="× 10^", bg="#2B2B2B", fg="#E0E0E0").grid(row=1, column=2, sticky="e")
    cb_top = ttk.Combobox(fb, values=EXPS, width=5, state="readonly"); cb_top.set("-9"); cb_top.grid(row=1, column=3, padx=2)
    fb.pack(fill="x", padx=12, pady=6)

    # 自訂:每個樣本一組(尾數 + 指數)
    fa = tk.LabelFrame(win, text="", bg="#2B2B2B", fg="#E0E0E0", padx=6, pady=4)
    tk.Radiobutton(fa, text="自訂 / Custom(每個樣本:尾數 × 10^指數;空白樣本尾數填 0)",
                   variable=mode_var, value="custom", bg="#2B2B2B", fg="#E0E0E0",
                   selectcolor="#2B2B2B", command=lambda: _toggle()).grid(row=0, column=0, columnspan=8, sticky="w")
    man_entries, exp_cbs = [], []
    per_row = 2
    for i in range(n):
        r = 1 + i // per_row; c = (i % per_row) * 4
        tk.Label(fa, text=f"S{i+1}:", bg="#2B2B2B", fg="#E0E0E0").grid(row=r, column=c, sticky="e", padx=(6, 2), pady=2)
        me = tk.Entry(fa, width=9); me.grid(row=r, column=c + 1, padx=2)
        tk.Label(fa, text="× 10^", bg="#2B2B2B", fg="#E0E0E0").grid(row=r, column=c + 2, sticky="e")
        ce = ttk.Combobox(fa, values=EXPS, width=5, state="readonly"); ce.set("-9"); ce.grid(row=r, column=c + 3, padx=(2, 6))
        man_entries.append(me); exp_cbs.append(ce)
    fa.pack(fill="x", padx=12, pady=6)

    def _toggle():
        is_half = (mode_var.get() == "half")
        e_top.config(state="normal" if is_half else "disabled")
        cb_top.config(state="readonly" if is_half else "disabled")
        for me, ce in zip(man_entries, exp_cbs):
            me.config(state="disabled" if is_half else "normal")
            ce.config(state="disabled" if is_half else "readonly")
    _toggle()

    result = {"val": None}
    def _ok():
        try:
            if mode_var.get() == "half":
                c0 = float(e_top.get().strip()) * (10.0 ** int(cb_top.get()))
                concs = [c0 / (2 ** i) for i in range(n - 1)] + [0.0]
                result["val"] = (concs, "half", log_var.get())
            else:
                concs = []
                for me, ce in zip(man_entries, exp_cbs):
                    man = float((me.get().strip() or "0"))
                    concs.append(man * (10.0 ** int(ce.get())) if man != 0 else 0.0)
                result["val"] = (concs, "custom", log_var.get())
        except Exception:
            messagebox.showwarning("格式錯誤 / Invalid",
                                   "尾數請輸入數字(例:4.108),數量級由下拉選。\nEnter a numeric mantissa; pick the exponent.")
            return
        win.destroy()

    log_var = tk.BooleanVar(value=False)
    tk.Checkbutton(win, text="X 軸取 log / Log scale X  (排除空白 0)", variable=log_var,
                   bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
                   activebackground="#2B2B2B", activeforeground="#00BFFF").pack(padx=12, anchor="w", pady=(0, 4))

    bf = tk.Frame(win, bg="#2B2B2B"); bf.pack(fill="x", padx=12, pady=(6, 12))
    tk.Button(bf, text="確定 / OK", command=_ok, bg="#0078D4", fg="white", width=12).pack(side="left", expand=True, padx=4)
    tk.Button(bf, text="取消 / Cancel", command=win.destroy, bg="#555", fg="white", width=12).pack(side="left", expand=True, padx=4)
    root.wait_window(win)
    return result["val"]


def _make_linearity_chart(means, csv_path, concs, mode, log_x=False):
    """濃度-光強度線性圖:存 PNG 並彈窗預覽。
       log_x=True:X 軸取 log10(濃度),排除空白(0),改做 y vs log10(x) 半對數擬合。"""
    x = np.array(concs, dtype=float)
    y = np.array(means, dtype=float)

    def _fit(xx, yy):
        a, b = np.polyfit(xx, yy, 1)
        yh = a * xx + b
        ss_res = float(np.sum((yy - yh) ** 2)); ss_tot = float(np.sum((yy - np.mean(yy)) ** 2))
        return a, b, (1 - ss_res / ss_tot if ss_tot > 0 else float("nan"))

    fig = Figure(figsize=(7, 5), dpi=100)
    ax = fig.add_subplot(111)

    if log_x:
        msk = x > 0                      # log 軸無法放空白(0),排除
        xm, ym = x[msk], y[msk]
        if xm.size < 2:
            messagebox.showwarning("Too few / 點數不足",
                                   "取 log 後有效點 < 2(空白無法取 log)。改用線性 X。\n"
                                   "Falling back to linear X.")
            return _make_linearity_chart(means, csv_path, concs, mode, log_x=False)
        lx = np.log10(xm)
        a, b, r2 = _fit(lx, ym)
        ax.scatter(xm, ym, s=70, color="#0078D4", zorder=3, label="Data")
        xs = np.logspace(float(lx.min()), float(lx.max()), 100)
        ax.plot(xs, a * np.log10(xs) + b, color="#D83B01", lw=2,
                label=f"Fit: y = {a:.3f}*log10(x) + {b:.2f}")
        yb = y[x == 0]
        for i, val in enumerate(yb):
            ax.axhline(float(val), color="#888888", ls="--", lw=1.2,
                       label=("Blank (x=0)" if i == 0 else None))
        ax.set_xscale("log")
        ax.set_xlabel("Concentration (M, log scale)")
        if yb.size:
            ax.text(0.05, 0.80, "Blank = " + ", ".join(f"{float(v):.1f}" for v in yb)
                    + "  (shown, not in R²)", transform=ax.transAxes,
                    fontsize=9, color="#555555", va="top")
        r2_text = f"R² = {r2:.4f}  (log x, blank excluded)"
    else:
        a, b, r2_all = _fit(x, y)
        r2_no = None
        if mode == "half":
            m2 = x != 0
            if int(m2.sum()) >= 2:
                _, _, r2_no = _fit(x[m2], y[m2])
        ax.scatter(x, y, s=70, color="#0078D4", zorder=3, label="Data")
        xs = np.linspace(float(x.min()), float(x.max()), 100)
        ax.plot(xs, a * xs + b, color="#D83B01", lw=2, label=f"Fit: y = {a:.3e}x + {b:.2f}")
        if bool((x == 0).any()):
            ax.scatter(x[x == 0], y[x == 0], s=90, facecolors="none", edgecolors="#333333",
                       linewidths=1.5, zorder=4, label="Blank")
        ax.set_xlabel("Concentration (M)")
        r2_text = (f"R² = {r2_all:.4f}  (with blank)\nR² = {r2_no:.4f}  (no blank)"
                   if r2_no is not None else f"R² = {r2_all:.4f}")

    ax.set_ylabel("Intensity (grayscale)")
    ax.set_title("Concentration vs Intensity"); ax.grid(True, alpha=0.3, which="both")
    ax.text(0.05, 0.92, r2_text, transform=ax.transAxes, fontsize=11, va="top",
            bbox=dict(boxstyle="round", fc="#FFF7E6", ec="#D83B01"))
    ax.legend(loc="lower right")
    fig.tight_layout()

    png_path = (csv_path[:-4] if csv_path.lower().endswith(".csv") else csv_path) + ".png"
    fig.savefig(png_path, dpi=150)

    win = tk.Toplevel(root); win.title("線性圖表 / Linearity Chart"); win.configure(bg="#1E1E1E")
    canvas = FigureCanvasTkAgg(fig, master=win); canvas.draw()
    canvas.get_tk_widget().pack(padx=10, pady=10)
    tk.Label(win, text=f"Saved: {os.path.basename(png_path)}", bg="#1E1E1E", fg="#00FF7F",
             font=("Arial", 10)).pack(pady=(0, 8))
    return png_path


def save_csv():
    ts   = list(timestamps)
    data = [list(v) for v in roi_data]
    n    = min([len(ts)] + [len(v) for v in data]) if data else 0
    ts   = ts[:n]
    data = [v[:n] for v in data]
    if n == 0:
        messagebox.showwarning("無資料 / No Data", "尚未產生資料，無法儲存。\nNo data to save.")
        return
    global last_csv_dir
    now      = datetime.datetime.now()
    filename = filedialog.asksaveasfilename(
        title="儲存 CSV / Save CSV", initialdir=last_csv_dir or os.getcwd(),
        initialfile=f"Light intensity_{now:%Y_%m_%d_%H_%M_%S}.csv",
        defaultextension=".csv", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
    if not filename:
        return                      # 取消:資料仍保留,可再按一次儲存
    filename = os.path.normpath(filename)
    last_csv_dir = os.path.dirname(filename)

    STABLE_AFTER_SEC = 10
    sample_cols    = [f"Sample {i+1}" for i in range(len(data))]
    stable_indices = [idx for idx, t in enumerate(ts) if t > STABLE_AFTER_SEC]
    stable_count   = len(stable_indices)

    means, stds, cvs, maxs, mins = [], [], [], [], []
    for values in data:
        arr = (np.array([values[idx] for idx in stable_indices], dtype=float)
               if stable_indices else np.array(values, dtype=float))
        m  = float(np.mean(arr))        if len(arr) > 0 else 0.0
        sd = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        cv = (sd / m * 100.0)           if m != 0       else 0.0
        mx = float(np.max(arr))         if len(arr) > 0 else 0.0
        mn = float(np.min(arr))         if len(arr) > 0 else 0.0
        means.append(round(m,  6)); stds.append(round(sd, 6))
        cvs.append(round(cv, 4));   maxs.append(round(mx, 6)); mins.append(round(mn, 6))

    note_text = (
        f"Statistics: t > {STABLE_AFTER_SEC}s  ({stable_count} pts, "
        f"t={ts[stable_indices[0]]}s ~ {ts[stable_indices[-1]]}s)"
        if stable_indices else
        f"WARNING: recording <= {STABLE_AFTER_SEC}s - stats computed from ALL data points"
    )
    mf_info = ("De-glint: ON (K=%.1f)" % DEGLINT_K) if deglint_enabled else "De-glint: OFF"

    blank  = [""] * len(data)
    header = ["Time (s)"] + sample_cols
    stat_rows = [
        [mf_info]    + blank,
        [note_text]  + blank,
        [f"Mean (t>{STABLE_AFTER_SEC}s)"]    + means,
        [f"Std Dev (t>{STABLE_AFTER_SEC}s)"] + stds,
        [f"CV (%) (t>{STABLE_AFTER_SEC}s)"]  + cvs,
        [f"Max (t>{STABLE_AFTER_SEC}s)"]     + maxs,
        [f"Min (t>{STABLE_AFTER_SEC}s)"]     + mins,
    ]
    with open(filename, "w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(header)
        w.writerows(stat_rows)
        for r in range(n):
            w.writerow([ts[r]] + [data[i][r] for i in range(len(data))])
    if messagebox.askyesno("Make chart? / 製作圖表",
                           f"CSV saved: {filename}\n是否要製作濃度-光強度線性圖?\nMake a linearity chart?"):
        if len(means) < 2:
            messagebox.showwarning("Too few / 樣本不足", "需要至少 2 個樣本才能畫線性圖。")
            return
        res = _ask_concentrations(len(means))
        if res is None:
            return
        concs, mode, log_x = res
        png = _make_linearity_chart(means, filename, concs, mode, log_x)
        messagebox.showinfo("Done / 完成", f"Saved:\n{filename}\n{png}")
    else:
        messagebox.showinfo("Saved / 儲存成功", f"Values saved as {filename}")

video_label.bind("<ButtonPress-1>",   on_mouse_down)
video_label.bind("<B1-Motion>",       on_mouse_move)
video_label.bind("<ButtonRelease-1>", on_mouse_up)
video_label.bind("<ButtonPress-3>",   on_right_mouse_down)
video_label.bind("<B3-Motion>",       on_right_mouse_move)
video_label.bind("<ButtonRelease-3>", on_right_mouse_up)
start_btn.config(command=on_start)
default_btn.config(command=on_default)
save_btn.config(command=save_csv)
auto_roi_btn.config(command=auto_detect_rois)
roi_save_btn.config(command=lambda: save_roi_layout(False))
roi_load_btn.config(command=load_roi_layout)

level_select_btn.config(command=toggle_level_select)
level_auto_btn.config(command=_auto_stretch_global)
level_reset_btn.config(command=_reset_stretch_global)


# ── 相機初始化 ────────────────────────────────────────────────────────────────

def init_camera_ximea_mc050():
    """XIMEA MC050MG-SY 初始化（支援 Downsampling）"""
    global cam, xi_img, orig_w, orig_h, bit_depth

    try:
        from ximea import xiapi
    except Exception:
        raise RuntimeError("無法載入 ximea 模組 / Cannot import ximea module.")

    cam = xiapi.Camera()
    cam.open_device()

    try:
        cam.set_imgdataformat("XI_MONO8")
    except Exception:
        pass

    try:
        if hasattr(cam, "set_exposure"):
            cam.set_exposure(user_exposure_ms * 1e3)
    except Exception:
        pass

    xi_img = xiapi.Image()

    try:
        cam.start_acquisition()
    except Exception:
        pass

    try:
        cam.get_image(xi_img)
        frame = xi_img.get_image_data_numpy()
    except Exception as e:
        raise RuntimeError(f"無法讀取 XIMEA MC050 影像: {e}\nCannot get MC050 image: {e}")

    if frame is None:
        raise RuntimeError("無法讀取 XIMEA MC050 影像 / Cannot get MC050 image")

    if frame.dtype != np.uint8:
        frame = np.clip(frame, 0, 255).astype(np.uint8)

    orig_h, orig_w = frame.shape[:2]
    update_letterbox(orig_w, orig_h)
    bit_depth = 8


def init_camera_ximea_mc023():
    """XIMEA MC023MG-SY 初始化（無 Downsampling）"""
    global cam, xi_img, orig_w, orig_h, bit_depth

    try:
        from ximea import xiapi
    except Exception:
        raise RuntimeError("無法載入 ximea 模組 / Cannot import ximea module.")

    cam = xiapi.Camera()
    cam.open_device()

    try:
        cam.set_imgdataformat("XI_MONO8")
    except Exception:
        pass

    try:
        if hasattr(cam, "set_exposure"):
            cam.set_exposure(user_exposure_ms * 1e3)
    except Exception:
        pass

    xi_img = xiapi.Image()

    try:
        cam.start_acquisition()
    except Exception:
        pass

    frame = None
    for attempt in range(5):
        try:
            cam.get_image(xi_img)
            frame = xi_img.get_image_data_numpy()
            if frame is not None:
                break
        except Exception as e:
            print(f"[MC023 init] get_image attempt {attempt+1} failed: {e}")
            time.sleep(0.3)

    if frame is None:
        raise RuntimeError("無法讀取 XIMEA MC023 影像 / Cannot get MC023 image after retries")

    if frame.dtype != np.uint8:
        frame = np.clip(frame, 0, 255).astype(np.uint8)

    orig_h, orig_w = frame.shape[:2]
    update_letterbox(orig_w, orig_h)
    bit_depth = 10


def init_camera_thorlabs():
    """Thorlabs 初始化"""
    global cam, orig_w, orig_h, bit_depth, user_exposure_ms

    THORLABS_DEFAULT_EXPOSURE_MS = 30.0
    user_exposure_ms = THORLABS_DEFAULT_EXPOSURE_MS
    try:
        exposure_entry.delete(0, tk.END)
        exposure_entry.insert(0, str(THORLABS_DEFAULT_EXPOSURE_MS))
    except Exception:
        pass

    import pylablib as pll
    from pylablib.devices import Thorlabs

    try:
        possible_paths = [
            r"C:\Program Files\Thorlabs\ThorImageCAM\Bin",
            r"C:\Program Files (x86)\Thorlabs\ThorImageCAM\Bin",
            r"C:\Program Files\Thorlabs\Scientific Imaging\ThorCam\Bin",
        ]
        dll_found = False
        for path in possible_paths:
            try:
                pll.par["devices/dlls/thorlabs_tlcam"] = path
                dll_found = True
                break
            except Exception:
                continue

        if not dll_found:
            import os
            if os.path.exists(r"C:\Program Files\Thorlabs"):
                for root_dir, dirs, files in os.walk(r"C:\Program Files\Thorlabs"):
                    if "thorlabs_tsi_camera_sdk.dll" in files:
                        pll.par["devices/dlls/thorlabs_tlcam"] = root_dir
                        dll_found = True
                        break

        if not dll_found:
            raise RuntimeError("找不到 thorlabs_tsi_camera_sdk.dll，請確認已安裝 ThorCam 軟體。\n"
                               "Cannot find thorlabs_tsi_camera_sdk.dll.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"無法設置 Thorlabs DLL 路徑: {e}")

    cams = Thorlabs.list_cameras_tlcam()
    if not cams:
        raise RuntimeError("找不到 Thorlabs 相機，請確認連線與驅動\nNo Thorlabs cameras found.")

    cam = Thorlabs.ThorlabsTLCamera(serial=cams[0])

    try:
        cam.set_exposure(user_exposure_ms / 1e3)
    except Exception:
        pass

    try:
        cam.setup_acquisition(nframes=100)
        cam.start_acquisition()
    except Exception:
        pass

    try:
        _, bit_depth_local = cam.get_sensor_info()
        bit_depth = bit_depth_local if bit_depth_local is not None else 8
    except Exception:
        bit_depth = 8

    try:
        cam.wait_for_frame(timeout=2.0)
        frame = cam.read_oldest_image()
    except Exception as e:
        raise RuntimeError(f"無法讀取 Thorlabs 影像: {e}")

    if frame is None:
        raise RuntimeError("無法讀取 Thorlabs 影像 / Cannot read Thorlabs image")

    if bit_depth > 8:
        frame = (frame >> (bit_depth - 8)).astype(np.uint8)
    else:
        frame = frame.astype(np.uint8)

    if frame.ndim == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    orig_h, orig_w = frame.shape[:2]
    update_letterbox(orig_w, orig_h)


# ── 相機選擇視窗 ──────────────────────────────────────────────────────────────

# ── 匯入圖片模式 / Import Image Mode ──────────────────────────────────────────

def is_image_mode():
    return CAMERA_TYPE == "IMAGE"

def _letterbox_image(gray):
    """把灰階影像做成 letterbox（與相機串流相同的顯示座標系）。"""
    global source_image_gray, image_frame_cache
    if (img_disp_w, img_disp_h) == (orig_w, orig_h):
        small = gray
    else:
        small = cv2.resize(gray, (img_disp_w, img_disp_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((disp_h, disp_w), dtype=np.uint8)
    canvas[img_pad_y:img_pad_y + img_disp_h,
           img_pad_x:img_pad_x + img_disp_w] = small
    image_frame_cache = canvas


def load_image_file(path):
    """讀入圖片檔，設定原始解析度、letterbox 參數與快取影像。回傳 True/False。"""
    global source_image_gray, orig_w, orig_h, image_path

    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        messagebox.showerror("載入失敗 / Load Failed",
                             f"無法讀取圖片：\n{path}\nCannot read image.")
        return False

    source_image_gray = img
    image_path = path
    orig_h, orig_w = img.shape[:2]
    # 匯入模式永不放大（放大會讓內插產生假紋理，干擾濾波驗證）
    update_letterbox(orig_w, orig_h)
    _letterbox_image(img)
    return True


def init_image_mode():
    """匯入圖片模式初始化：跳出選檔對話框並載入。回傳 True/False。"""
    from tkinter import filedialog
    path = filedialog.askopenfilename(
        title="選擇要分析的圖片 / Select Image to Analyze",
        filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                   ("All files", "*.*")])
    if not path:
        return False
    return load_image_file(path)


def setup_ui_for_image_mode():
    """匯入圖片模式：停用相機相關欄位，並預填合理預設值。"""
    try:
        # Gain / Exposure 對圖片無意義 → 停用並標示
        gain_entry.config(state="normal")
        gain_entry.delete(0, tk.END)
        gain_entry.insert(0, "N/A")
        gain_entry.config(state="disabled")
        exposure_entry.config(state="normal")
        exposure_entry.delete(0, tk.END)
        exposure_entry.insert(0, "N/A")
        exposure_entry.config(state="disabled")
        gain_apply_btn.config(state="disabled")
        exp_apply_btn.config(state="disabled")
        cam_apply_status.config(
            text="匯入圖片模式 / Image mode：Gain/Exposure 不適用。",
            fg="#888888")

        # 顯示載入的圖片資訊於相機狀態列
        if image_path:
            base = os.path.basename(image_path)
            append_log(f"[圖片模式] 已載入：{base}  ({orig_w}x{orig_h} px)")
    except Exception as e:
        print(f"[image mode] UI setup warning: {e}")


def ask_camera_choice_and_init():
    global CAMERA_TYPE, cam

    choice_win = tk.Toplevel(root)
    choice_win.resizable(False, False)
    choice_win.title("選擇相機 / Choose Camera")
    choice_win.grab_set()
    choice_win.configure(bg="#2B2B2B")

    tk.Label(choice_win, text="請選擇欲使用的相機 / Please choose camera:",
             font=("Arial", 12), bg="#2B2B2B", fg="#00BFFF").pack(padx=10, pady=10)

    var = tk.StringVar(value="XIMEA_MC050")

    for label, value in [
        ("XIMEA MC050MG-SY", "XIMEA_MC050"),
        ("XIMEA MC023MG-SY", "XIMEA_MC023"),
        ("THORLABS",          "THORLABS"),
        ("匯入圖片 / Import Image (無相機)", "IMAGE"),
    ]:
        tk.Radiobutton(choice_win, text=label, variable=var, value=value,
                       command=lambda v=value: var.set(v),
                       bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
                       activebackground="#2B2B2B", activeforeground="#00BFFF",
                       font=("Arial", 11)
                       ).pack(anchor="w", padx=20, pady=5)

    status_label = tk.Label(choice_win,
                             text="選擇後按 Initialize 以啟動相機 / Click 'Initialize' to start camera",
                             fg="#888888", bg="#2B2B2B")
    status_label.pack(pady=(5, 10))

    def on_init():
        choice = var.get()

        # 圖片模式:選檔對話框需在主執行緒;沒有阻塞的相機呼叫
        if choice == "IMAGE":
            if not init_image_mode():
                status_label.config(text="No image selected / 未選擇圖片", fg="#FF4444")
                return
            status_label.config(text=f"{choice} initialized.", fg="#107C10")
            choice_win.grab_release(); choice_win.destroy()
            globals()["CAMERA_TYPE"] = choice
            return

        # 相機模式:把會阻塞的 init(open_device/長曝光 get_image)丟到 worker 執行緒,
        # Tk 只在主執行緒(root.after)更新,避免跨執行緒操作 Tk 造成卡死。
        def _ok():
            status_label.config(text=f"{choice} initialized.", fg="#107C10")
            choice_win.grab_release(); choice_win.destroy()
            globals()["CAMERA_TYPE"] = choice

        def _fail(msg):
            init_btn.config(state="normal")
            status_label.config(text=f"Init failed: {msg}", fg="#FF4444")
            messagebox.showerror("Init Error / 初始化錯誤", msg)

        def _worker():
            try:
                if choice == "XIMEA_MC050":
                    init_camera_ximea_mc050()
                elif choice == "XIMEA_MC023":
                    init_camera_ximea_mc023()
                else:
                    init_camera_thorlabs()
            except Exception as e:
                root.after(0, _fail, str(e)); return
            root.after(0, _ok)

        init_btn.config(state="disabled")
        status_label.config(text=f"{choice} initializing... / 初始化中", fg="#FFA500")
        threading.Thread(target=_worker, daemon=True).start()

    init_btn = ttk.Button(choice_win, text="Initialize / 初始化", command=on_init)
    init_btn.pack(pady=(0, 10))
    root.wait_window(choice_win)


# ── 關閉程式 ──────────────────────────────────────────────────────────────────

def on_close():
    if messagebox.askokcancel("退出程式 / Exit Program", "確定要退出程式嗎？\nAre you sure you want to exit?"):
        global running, analyzing, cam, CAMERA_TYPE
        running   = False
        analyzing = False

        try:
            if is_ximea() and cam is not None:
                try: cam.stop_acquisition()
                except Exception: pass
                try: cam.close_device()
                except Exception: pass
            elif CAMERA_TYPE == "THORLABS" and cam is not None:
                try: cam.stop_acquisition()
                except Exception: pass
                try: cam.close()
                except Exception: pass
        except Exception:
            pass
        root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)


# ── Plot / Log ────────────────────────────────────────────────────────────────

def initialize_plot_area(n):
    global plot_win, canvas_frame, scrollable_frame, plot_canvases, plot_axes, plot_figures, log_text_widget, text_follow

    if plot_win:
        try: plot_win.destroy()
        except Exception: pass

    plot_win = tk.Toplevel(root)
    plot_win.title("ROI 平均光強度（每秒） / Avg ROI Intensity (per second)")
    plot_win.configure(bg="#1E1E1E")
    plot_win.protocol("WM_DELETE_WINDOW", confirm_close_plot)

    sw, sh  = root.winfo_screenwidth(), root.winfo_screenheight()
    win_w   = int(sw * 0.9)
    win_h   = int(sh * 0.9)
    plot_win.geometry(f"{win_w}x{win_h}")

    paned = tk.PanedWindow(plot_win, orient=tk.HORIZONTAL, sashrelief=tk.RAISED,
                           sashwidth=10, bg="#1E1E1E")
    paned.pack(fill="both", expand=True)

    left_container = tk.Frame(paned, bg="#1E1E1E")
    paned.add(left_container, minsize=1000)

    canvas_frame = tk.Canvas(left_container, bg="#1E1E1E", highlightthickness=0)
    v_scroll = tk.Scrollbar(left_container, orient=tk.VERTICAL,   command=canvas_frame.yview)
    h_scroll = tk.Scrollbar(left_container, orient=tk.HORIZONTAL, command=canvas_frame.xview)
    canvas_frame.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
    canvas_frame.grid(row=0, column=0, sticky="nsew")
    v_scroll.grid(row=0, column=1, sticky="ns")
    h_scroll.grid(row=1, column=0, sticky="ew")
    left_container.rowconfigure(0, weight=1)
    left_container.columnconfigure(0, weight=1)

    scrollable_frame = tk.Frame(canvas_frame, bg="#1E1E1E")
    canvas_frame.create_window((0, 0), window=scrollable_frame, anchor="nw")

    text_frame = tk.Frame(paned, bg="#1E1E1E")
    paned.add(text_frame, minsize=320)

    text_container = tk.Frame(text_frame, bg="#1E1E1E")
    text_container.pack(side="top", fill="both", expand=True, padx=2, pady=(4, 4))

    log_text_widget = tk.Text(text_container, width=40, height=34, font=("Arial", 18),
                               wrap="word", state="disabled",
                               bg="#2B2B2B", fg="#00BFFF", insertbackground="#00BFFF")
    log_text_widget.pack(side="left", fill="both", expand=True)

    scrollbar_text = tk.Scrollbar(text_container, orient=tk.VERTICAL, command=log_text_widget.yview)
    scrollbar_text.pack(side="right", fill="y", padx=(2, 0))
    log_text_widget.configure(yscrollcommand=scrollbar_text.set)

    def scroll_to_bottom_action():
        global text_follow
        text_follow = True
        try: log_text_widget.see(tk.END)
        except Exception: pass

    button_frame = tk.Frame(text_frame, bg="#1E1E1E")
    button_frame.pack(side="bottom", fill="x", padx=4, pady=(2, 6))
    tk.Button(button_frame, text="捲到最底 / Scroll to bottom", command=scroll_to_bottom_action,
              font=("Arial", 11), height=2, bg="#0078D4", fg="white",
              activebackground="#107C10", activeforeground="white").pack(fill="x")

    def set_text_follow(val):
        global text_follow
        text_follow = val

    def on_text_wheel(event):
        set_text_follow(False)
        delta = 0
        if hasattr(event, 'delta'):
            try: delta = int(event.delta / 120)
            except Exception: delta = 0
        if hasattr(event, 'num'):
            delta = 1 if event.num == 4 else (-1 if event.num == 5 else delta)
        try: log_text_widget.yview_scroll(-delta, "units")
        except Exception: pass
        return "break"

    log_text_widget.bind("<MouseWheel>", on_text_wheel)
    scrollbar_text.bind("<ButtonPress-1>", lambda e: set_text_follow(False))

    def _on_canvas_mousewheel(event):
        try: canvas_frame.yview_scroll(int(-1*(event.delta/120)), "units")
        except Exception:
            try: canvas_frame.yview_scroll(int(-1*event.delta), "units")
            except Exception: pass

    canvas_frame.bind("<Enter>", lambda e: canvas_frame.bind_all("<MouseWheel>", _on_canvas_mousewheel))
    canvas_frame.bind("<Leave>", lambda e: canvas_frame.unbind_all("<MouseWheel>"))

    plot_canvases.clear(); plot_axes.clear(); plot_figures.clear()

    for i in range(n):
        fig = Figure(figsize=(5.5, 3.5), dpi=100)
        ax  = fig.add_subplot(111)
        ax.set_title(f"Light intensity of Sample {i+1}")
        ax.set_xlabel("Time (s)"); ax.set_ylabel("Intensity"); ax.grid(True)
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=scrollable_frame)
        widget = canvas.get_tk_widget()
        widget.grid(row=i // 2, column=i % 2, padx=10, pady=10)
        widget.bind("<Button-3>", lambda event, f=fig: save_plot_image(f))
        canvas.draw()
        plot_figures.append(fig); plot_canvases.append(canvas); plot_axes.append(ax)

    scrollable_frame.update_idletasks()
    canvas_frame.config(scrollregion=canvas_frame.bbox("all"))
    paned.sash_place(0, int(win_w * 0.75), 0)

def append_log(text):
    global text_follow
    if log_text_widget:
        try:
            log_text_widget.config(state="normal")
            log_text_widget.insert(tk.END, text + "\n\n")
            if text_follow:
                log_text_widget.see(tk.END)
            log_text_widget.config(state="disabled")
        except Exception:
            pass

def confirm_close_plot():
    if messagebox.askokcancel("關閉視窗 / Close Window",
                              "關閉圖表視窗後，偵測將會停止。\nClosing the plot window will STOP detection."):
        global analyzing
        analyzing = False
        try:
            start_btn["text"] = "重新啟動偵測 / Restart Detection"
            default_btn.state(["disabled"])
        except Exception:
            pass
        try: plot_win.destroy()
        except Exception: pass

def save_plot_image(fig):
    now      = datetime.datetime.now()
    filename = f"Plot_{now:%Y_%m_%d_%H_%M_%S}.png"
    fig.savefig(filename)
    messagebox.showinfo("儲存成功 / Saved", f"圖表已儲存為 {filename}\nPlot saved as {filename}")

def update_plots():
    for i, values in enumerate(roi_data):
        ax = plot_axes[i]
        ax.clear()
        ax.plot(timestamps, values, marker='o')
        ax.set_title(f"Light intensity of Sample {i+1}")
        ax.set_xlabel("Time (s)"); ax.set_ylabel("Intensity"); ax.grid(True)
        ax.figure.tight_layout()
        plot_canvases[i].draw()

def update_display():
    with frame_lock:
        frame = current_frame if current_frame is not None else None

    if frame is not None:
        gray          = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        gray_disp     = apply_display_stretch(gray)   # 顯示用對比拉伸（量測仍用原始 gray）
        display_frame = cv2.cvtColor(gray_disp, cv2.COLOR_GRAY2RGB)

        glint_full = _glint_mask(gray) if (deglint_enabled and deglint_show_removed) else None
        for i, r in enumerate(rois):
            if not r:
                continue
            if r[0] == 'rect':
                _, x1, y1, x2, y2 = r
                _gp = (_deglint_overlay(display_frame, gray, r, glint_full)
                       if glint_full is not None else None)
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), (255, 255, 255), 2)

                txt = f"Sample {i+1}  ({x2-x1}x{y2-y1} px)"
                if _gp is not None:
                    txt += f"  glint {_gp:.1f}%"

                tsz  = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                tx, ty = x1, max(20, y1 - 15)
                cv2.rectangle(display_frame, (tx-5, ty-tsz[1]-5), (tx+tsz[0]+5, ty+5), (0, 0, 0), -1)
                cv2.putText(display_frame, txt, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            elif r[0] == 'circle':
                _, cx, cy, rad = r
                _gp = (_deglint_overlay(display_frame, gray, r, glint_full)
                       if glint_full is not None else None)
                cv2.circle(display_frame, (int(cx), int(cy)), int(rad), (255, 255, 255), 2)

                txt = f"Sample {i+1}  (Dia {rad*2} px)"
                if _gp is not None:
                    txt += f"  glint {_gp:.1f}%"

                tsz = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                tx  = int(cx - rad)
                ty  = max(20, int(cy - rad - 15))
                cv2.rectangle(display_frame, (tx-5, ty-tsz[1]-5), (tx+tsz[0]+5, ty+5), (0, 0, 0), -1)
                cv2.putText(display_frame, txt, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if dragging:
            try:
                if roi_shape_var.get() == 'rect':
                    x1 = max(img_pad_x, min(img_pad_x + img_disp_w - roi_fixed_width,  start_x))
                    y1 = max(img_pad_y, min(img_pad_y + img_disp_h - roi_fixed_height, start_y))
                    cv2.rectangle(display_frame, (x1, y1), (x1+roi_fixed_width, y1+roi_fixed_height), (200, 200, 200), 1)
                    stxt = f"{roi_fixed_width}x{roi_fixed_height}px"
                    ssz = cv2.getTextSize(stxt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    sx, sy = max(0, x1), max(15, y1 - 5)
                    cv2.rectangle(display_frame, (sx-2, sy-ssz[1]-2), (sx+ssz[0]+2, sy+2), (0, 0, 0), -1)
                    cv2.putText(display_frame, stxt, (sx, sy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
                else:
                    r  = roi_fixed_diameter // 2
                    cx = max(img_pad_x + r, min(img_pad_x + img_disp_w - r, start_x))
                    cy = max(img_pad_y + r, min(img_pad_y + img_disp_h - r, start_y))
                    cv2.circle(display_frame, (cx, cy), r, (200, 200, 200), 1)
                    stxt = f"Dia {roi_fixed_diameter}px"
                    ssz = cv2.getTextSize(stxt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    sx, sy = max(0, cx - r), max(15, cy - r - 5)
                    cv2.rectangle(display_frame, (sx-2, sy-ssz[1]-2), (sx+ssz[0]+2, sy+2), (0, 0, 0), -1)
                    cv2.putText(display_frame, stxt, (sx, sy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            except Exception:
                pass

        if right_dragging and 0 <= right_drag_roi_index < len(rois):
            try:
                roi = rois[right_drag_roi_index]
                if roi[0] == 'rect':
                    _, x1, y1, x2, y2 = roi
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (100, 200, 255), 2)
                    mtxt = "Moving..."
                    msz  = cv2.getTextSize(mtxt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    mx, my = max(0, x1), max(15, y1 - 15)
                    cv2.rectangle(display_frame, (mx-2, my-msz[1]-2), (mx+msz[0]+2, my+2), (0, 0, 0), -1)
                    cv2.putText(display_frame, mtxt, (mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 200, 255), 1)
                elif roi[0] == 'circle':
                    _, cx, cy, r = roi
                    cv2.circle(display_frame, (int(cx), int(cy)), int(r), (100, 200, 255), 2)
                    mtxt = "Moving..."
                    msz  = cv2.getTextSize(mtxt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    mx, my = max(0, int(cx - r)), max(15, int(cy - r - 15))
                    cv2.rectangle(display_frame, (mx-2, my-msz[1]-2), (mx+msz[0]+2, my+2), (0, 0, 0), -1)
                    cv2.putText(display_frame, mtxt, (mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 200, 255), 1)
            except Exception:
                pass

         # ── 灰階選取框（拖曳中）────────────────────────────────────────────────
        if level_mode and level_block is not None:
            try:
                lx1, ly1, lx2, ly2 = [int(v) for v in level_block]
                cv2.rectangle(display_frame, (min(lx1,lx2), min(ly1,ly2)),
                              (max(lx1,lx2), max(ly1,ly2)), (0, 255, 255), 2)
            except Exception:
                pass
        img_tk = ImageTk.PhotoImage(Image.fromarray(display_frame))
        video_label.imgtk = img_tk
        video_label.configure(image=img_tk)

    root.after(30, update_display)


# ── 影像串流 ──────────────────────────────────────────────────────────────────

frame_seq = 0   # 每次發布新影像 +1；analysis_loop 用它避免重複計入同一張

def _publish_frame(frame):
    """Letterbox 進顯示座標系並發布。resize 失敗就丟棄此幀 ——
    絕不發布座標系與 ROI 不一致的影像。回傳是否成功。"""
    global current_frame, frame_seq
    try:
        small = cv2.resize(frame, (img_disp_w, img_disp_h))
        out = np.zeros((disp_h, disp_w), dtype=np.uint8)
        out[img_pad_y:img_pad_y+img_disp_h, img_pad_x:img_pad_x+img_disp_w] = small
    except Exception:
        return False
    with frame_lock:
        current_frame = out
        frame_seq += 1
    return True


def video_loop_ximea():
    """共用於 MC050 與 MC023"""
    global current_frame, xi_img, cam

    try:
        from ximea import xiapi
    except Exception:
        return

    xi_img = xiapi.Image()
    fail_count = 0

    while running:
        try:
            # ── camera_lock 保護：與 apply 的 stop/start 互斥 ─────────────────
            with camera_lock:
                cam.get_image(xi_img)
                frame = xi_img.get_image_data_numpy()
        except Exception:
            fail_count += 1
            time.sleep(0.05)
            if fail_count == 20:   # 約 1 秒持續失敗才提示，避免洗版
                root.after(0, append_log, "WARNING: camera read failing / 相機讀取失敗 — 請檢查連線")
            continue
        else:
            fail_count = 0
        if frame is None:
            continue

        if frame.dtype != np.uint8:
            try:    frame = frame.astype(np.uint8)
            except Exception: frame = np.clip(frame, 0, 255).astype(np.uint8)

        _publish_frame(frame)

def video_loop_thorlabs():
    global current_frame, cam, bit_depth

    fail_count = 0

    while running:
        try:
            cam.wait_for_frame(timeout=1.0)
            frame = cam.read_oldest_image()
        except Exception:
            fail_count += 1
            time.sleep(0.05)
            if fail_count == 20:
                root.after(0, append_log, "WARNING: camera read failing / 相機讀取失敗 — 請檢查連線")
            continue
        else:
            fail_count = 0
        if frame is None:
            continue

        if bit_depth > 8:
            frame = (frame >> (bit_depth - 8)).astype(np.uint8)
        else:
            frame = frame.astype(np.uint8)

        if frame.ndim == 3 and frame.shape[2] == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        _publish_frame(frame)


def video_loop_image():
    """匯入圖片模式：持續把靜態影像餵進 current_frame，
    讓所有既有的 ROI/分析邏輯不需改動即可運作。"""
    global current_frame

    while running:
        if image_frame_cache is None:
            time.sleep(0.05)
            continue

        _publish_frame(source_image_gray if source_image_gray is not None else image_frame_cache)
        time.sleep(0.03)   # 靜態影像不需高更新率，約 30fps 顯示即可


# ── 分析迴圈 ──────────────────────────────────────────────────────────────────

def analysis_loop():
    global roi_data, timestamps, decimal_places

    roi_data     = [[] for _ in rois]
    timestamps   = []
    start_time   = time.time()
    buffer_vals  = [[] for _ in rois]
    last_logged_sec = -1
    last_seq = -1

    while analyzing:
        with frame_lock:
            frame = current_frame if current_frame is not None else None
            seq   = frame_seq
        if frame is None or seq == last_seq:
            time.sleep(0.002)   # 尚無新影像，讓出 CPU
            continue
        last_seq = seq

        elapsed = int(time.time() - start_time)

        glint_full = _glint_mask(frame) if deglint_enabled else None
        for i, r in enumerate(rois):
            patch, cmask = get_roi_patch(frame, r)
            gsub = None
            if glint_full is not None:
                gy1, gy2, gx1, gx2 = _roi_slice(frame.shape, r)
                gsub = glint_full[gy1:gy2, gx1:gx2]
            buffer_vals[i].append(compute_roi_mean(patch, cmask, gsub))

        if elapsed > last_logged_sec:
            log_message = ""
            for i in range(len(rois)):
                avg_sec = np.mean(buffer_vals[i]) if buffer_vals[i] else 0.0
                rounded = round(float(avg_sec), decimal_places) if decimal_places is not None else float(avg_sec)
                roi_data[i].append(rounded)
                buffer_vals[i] = []
                log_message += f"At {elapsed} sec, Sample {i+1} = {rounded}\n"
            timestamps.append(elapsed)
            root.after(0, update_plots)
            root.after(0, append_log, log_message.strip())
            last_logged_sec = elapsed


start_btn.config(command=on_start)


# ── 重啟相機預設值 ─────────────────────────────────────────────────────────────

def apply_defaults_on_restart_camera():
    global cam, CAMERA_TYPE
    try:
        if cam is not None:
            if hasattr(cam, "set_gain"):
                try: cam.set_gain(0.0)
                except Exception: pass
            if hasattr(cam, "set_exposure"):
                try:
                    if is_ximea():
                        if CAMERA_TYPE == "XIMEA_MC050":
                            cam.set_exposure(2500.0 * 1e3)
                        else:
                            cam.set_exposure(30.0 * 1e3)
                    else:
                        cam.set_exposure(30.0 / 1e3)
                except Exception: pass
    except Exception:
        pass


# ── 啟動系統 ──────────────────────────────────────────────────────────────────

def start_system():
    global CAMERA_TYPE

    try:
        ask_camera_choice_and_init()
    except Exception as e:
        messagebox.showerror("初始化錯誤 / Initialization Error", f"初始化過程發生錯誤: {e}")
        return

    if CAMERA_TYPE is None:
        messagebox.showerror("未選擇相機 / No Camera",
                             "未選擇或無法初始化相機，程式將退出。\nNo camera selected or failed to initialize.")
        root.destroy()
        return

    if is_ximea():
        threading.Thread(target=video_loop_ximea, daemon=True).start()
    elif CAMERA_TYPE == "THORLABS":
        threading.Thread(target=video_loop_thorlabs, daemon=True).start()
    else:  # IMAGE
        setup_ui_for_image_mode()
        threading.Thread(target=video_loop_image, daemon=True).start()

    update_display()
    validate_start_enable()

root.after(100, start_system)   # 主執行緒執行相機選擇/初始化(阻塞呼叫在 on_init 內丟 worker)
validate_start_enable()
root.mainloop()

# ── 結束清理 ──────────────────────────────────────────────────────────────────
running   = False
analyzing = False
time.sleep(0.1)
try:
    if is_ximea() and cam is not None:
        try: cam.stop_acquisition()
        except Exception: pass
        try: cam.close_device()
        except Exception: pass
    elif CAMERA_TYPE == "THORLABS" and cam is not None:
        try: cam.stop_acquisition()
        except Exception: pass
        try: cam.close()
        except Exception: pass
except Exception:
    pass

print("相機已停止並釋放資源。\nCamera stopped and resources released.")