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

threshold_value = None

user_fps_val = None
fps_locked = False
valid_frame_count = 0
last_sec_time = int(time.time())
fps_value = 0

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

# ── 門檻預覽框 ────────────────────────────────────────────────────────────────
preview_block         = None    # (x1,y1,x2,y2) 顯示座標
preview_mode          = False   # 正在拖曳設置預覽框
preview_drawing       = False   # 滑鼠拖曳中
preview_start_x       = 0
preview_start_y       = 0

# ── 比例尺 ─────────────────────────────────────────────────────────────────────
scale_mode            = False   # 正在畫比例尺線段
scale_drawing         = False   # 滑鼠正在拖曳
scale_line_disp       = None    # (x1,y1,x2,y2) 顯示座標
scale_pixels_per_unit = None    # 每單位對應幾 px
scale_unit            = "mm"    # 使用者選擇的單位

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

# ── Median Filter 灰塵濾除 ────────────────────────────────────────────────────
median_filter_enabled = False   # 是否啟用
MEDIAN_KERNEL         = 3       # 固定 3，不開放調整（k>3 會使亮邊洩漏）
MEDIAN_DIFF_THRESH    = 5       # 差異圖判定：改動超過此值才標紅
median_preview_win    = None    # 預覽視窗參考
deglint_preview_win   = None    # de-glint 預覽視窗參考
median_last_ratio     = []      # 每個 ROI 最近一次被 median 修正的比例(%)

# ── De-glint 去亮反光（統計去離群，取代難調的 threshold）──────────────────────
deglint_enabled = False         # 是否啟用亮離群去除
deglint_show_removed = False    # 主畫面即時把被去除的反光像素染紅
DEGLINT_K_DEFAULT = 4.0         # 20261022 測試圖:K=4 乾淨 ROI 誤刪 <2%,灰塵多的 ROI 仍去除約 10%
DEGLINT_K       = DEGLINT_K_DEFAULT   # 各 ROI top-hat 殘留門檻倍數:剔除 > median + K·1.4826·MAD 的亮點
DEGLINT_KERNEL  = 9             # ponytail: opening 核心;需大於灰塵、小於樣本,依光學/樣本大小校正

# ── 亮度不均校正 / Illumination correction ───────────────────────────────────
# 校正值 = 暗場值 + (原始值 − 暗場值) × 增益;增益 = ROI 位置的平均照明 / 該像素照明
illum_mode     = "off"          # "off" | "background"(背景擬合) | "flat"(平場參考)
illum_gain     = None           # 量測中使用的增益圖(顯示座標 float32);None = 不校正
illum_factors  = []             # 各 ROI 的平均增益(顯示 / CSV 用)
illum_info     = ""             # 寫進 CSV 的校正說明
illum_dark     = 0.0            # 暗場值(相機無光時的灰階),由進階設定輸入
flat_field     = None           # 平場參考算出的照明分佈(顯示座標 float32)
flat_saved_at  = ""
illum_preview_win = None
ILLUM_DEG      = 2              # 背景擬合多項式次數(20261022 測試圖:2 次最穩,3 次在樣本處亂外插)
ILLUM_EXCLUDE  = 1.0            # 擬合時排除 ROI 外擴 (倍 ROI 邊長) 的區域;樣本通常比 ROI 大
FLAT_FRAMES    = 20             # 擷取平場時平均的張數

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

# ── 進階設定視窗 / Advanced(預設隱藏,由選單「設定」或主面板按鈕開啟)────────
adv_win = tk.Toplevel(root)
adv_win.title("進階設定 / Advanced Settings")
adv_win.configure(bg="#2B2B2B")
adv_win.geometry(f"{right_w + 40}x{disp_h - 40}")
adv_win.withdraw()
adv_win.protocol("WM_DELETE_WINDOW", adv_win.withdraw)   # 關閉只是隱藏,設定值保留

adv_canvas = tk.Canvas(adv_win, bg="#2B2B2B", highlightthickness=0)
adv_vscroll = tk.Scrollbar(adv_win, orient=tk.VERTICAL, command=adv_canvas.yview)
adv_canvas.configure(yscrollcommand=adv_vscroll.set)
adv_vscroll.pack(side="right", fill="y")
adv_canvas.pack(side="left", fill="both", expand=True)
adv_frame = tk.Frame(adv_canvas, bg="#2B2B2B")
_adv_canvas_win = adv_canvas.create_window((0, 0), window=adv_frame, anchor="nw")
adv_frame.bind("<Configure>", lambda e: adv_canvas.configure(scrollregion=adv_canvas.bbox("all")))
adv_canvas.bind("<Configure>", lambda e: adv_canvas.itemconfig(_adv_canvas_win, width=e.width))
adv_canvas.bind("<Enter>", lambda e: adv_canvas.bind_all(
    "<MouseWheel>", lambda ev: adv_canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units")))
adv_canvas.bind("<Leave>", lambda e: adv_canvas.unbind_all("<MouseWheel>"))

def show_advanced():
    adv_win.deiconify()
    adv_win.lift()

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

# 固定 ROI:樣本座標固定時,位置與大小鎖定,開程式自動載入
roi_fixed_var = tk.BooleanVar(value=False)
roi_fixed_check = tk.Checkbutton(auto_frame, text="固定 ROI(鎖定座標與大小)/ Fixed ROI",
                                 variable=roi_fixed_var, command=lambda: toggle_fixed_roi(),
                                 font=RADIO_FONT, bg="#2B2B2B", fg="#FFD700",
                                 selectcolor="#2B2B2B", activebackground="#2B2B2B",
                                 activeforeground="#FFD700", anchor="w")
roi_fixed_check.grid(row=8, column=0, columnspan=2, sticky='w', padx=2, pady=(8, 0))
roi_set_fixed_btn = ttk.Button(auto_frame, text="設為固定 ROI / Set current as fixed",
                               style="Apply.TButton", command=lambda: set_fixed_roi())
roi_set_fixed_btn.grid(row=9, column=0, columnspan=2, sticky='we', padx=2, pady=(2, 2))
roi_fixed_status = tk.Label(auto_frame, text="未固定 / Not fixed", font=("times new roman", 10),
                            bg="#2B2B2B", fg="#888888", wraplength=360, justify="left")
roi_fixed_status.grid(row=10, column=0, columnspan=2, sticky='w', padx=2, pady=(0, 2))

# 對比(僅影響顯示)— 主面板;選區直方圖留在進階設定
ct_frame = tk.LabelFrame(right_frame, text="對比 / Contrast (display only)",
                         padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                         bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
ct_frame.pack(fill='both', padx=6, pady=4, expand=True)
ct_btn_row = tk.Frame(ct_frame, bg="#2B2B2B"); ct_btn_row.pack(fill='x', pady=(0, 2))

# Threshold
thr_frame = tk.LabelFrame(adv_frame, text="門檻 / Threshold",
                           padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                           bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
thr_frame.pack(fill='both', padx=6, pady=4, expand=True)
tk.Label(thr_frame, text="Threshold（0-255）:", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
threshold_entry = ttk.Entry(thr_frame, width=14, font=ENTRY_FONT)
threshold_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
threshold_entry.insert(0, "255")

# FPS
fps_frame = tk.LabelFrame(adv_frame, text="FPS 控制 / FPS Control",
                           padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                           bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
fps_frame.pack(fill='both', padx=6, pady=4, expand=True)
tk.Label(fps_frame, text="Set FPS(integer) :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
fps_input_entry = ttk.Entry(fps_frame, width=10, font=ENTRY_FONT)
fps_input_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
fps_display_label = tk.Label(fps_frame, text="Current FPS: 0", anchor="w",
                              font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#00BFFF")
fps_display_label.grid(row=1, column=0, columnspan=2, sticky='w', padx=2, pady=(6, 2))
fps_input_entry.insert(0, "50")

# Decimal places
dec_frame = tk.LabelFrame(adv_frame, text="顯示精度 / Display Precision",
                           padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                           bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
dec_frame.pack(fill='both', padx=6, pady=4, expand=True)
tk.Label(dec_frame, text="Decimal places :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
dec_entry = ttk.Entry(dec_frame, width=6, font=ENTRY_FONT)
dec_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
dec_entry.insert(0, "2")

# 亮度校正進階:暗場值
idark_frame = tk.LabelFrame(adv_frame, text="亮度校正進階 / Illumination Advanced",
                            padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                            bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
idark_frame.pack(fill='both', padx=6, pady=4, expand=True)
tk.Label(idark_frame, text="暗場值 Dark level (0-254) :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
illum_dark_entry = ttk.Entry(idark_frame, width=6, font=ENTRY_FONT)
illum_dark_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
illum_dark_entry.insert(0, "0")
tk.Label(idark_frame,
         text="相機完全沒光(蓋上鏡頭)時 ROI 的平均灰階。校正會先扣掉它再乘增益;\n"
              "若相機有固定底值卻填 0,背景估計會過度校正。",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888",
         justify="left").grid(row=1, column=0, columnspan=2, sticky='w', padx=2, pady=(0, 2))

# ── 門檻預覽框 UI ─────────────────────────────────────────────────────────────
prev_frame = tk.LabelFrame(adv_frame, text="門檻預覽 / Threshold Preview",
                            padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                            bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
prev_frame.pack(fill='both', padx=6, pady=4, expand=True)

tk.Label(prev_frame,
         text="在影像上拖曳設置預覽框\n高於滑條值的像素會標紅\nDrag on image to set preview box\nPixels above slider value turn red",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888",
         justify="left").pack(anchor='w', padx=4, pady=(2, 4))

preview_threshold_var = tk.IntVar(value=200)

preview_slider = tk.Scale(
    prev_frame, from_=0, to=255,
    orient=tk.HORIZONTAL, variable=preview_threshold_var,
    label="Preview Threshold (0-255)",
    font=("times new roman", 10),
    bg="#2B2B2B", fg="#E0E0E0", highlightthickness=0,
    troughcolor="#444444", activebackground="#00BFFF",
    length=360, resolution=1
)
preview_slider.pack(fill='x', padx=4, pady=(2, 6))

preview_btn_frame = tk.Frame(prev_frame, bg="#2B2B2B")
preview_btn_frame.pack(fill='x', padx=4, pady=(0, 4))

preview_set_btn   = ttk.Button(preview_btn_frame, text="設置預覽框 / Set Block", style="Apply.TButton")
preview_set_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))
preview_clear_btn = ttk.Button(preview_btn_frame, text="清除 / Clear", style="Apply.TButton")
preview_clear_btn.pack(side="left", expand=True, fill="x", padx=(2, 0))

preview_status_label = tk.Label(prev_frame, text="尚未設置 / Not set",
                                 font=("times new roman", 10), bg="#2B2B2B", fg="#888888")
preview_status_label.pack(anchor='w', padx=4, pady=(0, 2))

# ── 灰塵濾除 UI (Median Filter) ────────────────────────────────────────────────
mf_frame = tk.LabelFrame(right_frame, text="灰塵濾除 / Dust Removal (Median)",
                          padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                          bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
mf_frame.pack(fill='both', padx=6, pady=4, expand=True)

median_enable_var = tk.BooleanVar(value=False)
median_check = tk.Checkbutton(mf_frame, text="啟用 Median Filter (3x3)",
                               variable=median_enable_var,
                               command=lambda: toggle_median_filter(),
                               font=RADIO_FONT, bg="#2B2B2B", fg="#E0E0E0",
                               selectcolor="#2B2B2B", activebackground="#2B2B2B",
                               activeforeground="#00BFFF", anchor="w")
median_check.pack(anchor='w', padx=4, pady=(2, 4), fill='x')

tk.Label(mf_frame,
         text="用 3x3 中值取代灰塵亮點，邊緣仍由 Threshold 濾除。\n"
              "Replaces dust with 3x3 median; edges still cut by Threshold.",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888",
         justify="left").pack(anchor='w', padx=4, pady=(0, 4))

median_preview_btn = ttk.Button(mf_frame, text="預覽濾波效果 / Preview Filter",
                                 style="Apply.TButton",
                                 command=lambda: show_median_preview())
median_preview_btn.pack(fill='x', padx=4, pady=(2, 4))

median_status_label = tk.Label(mf_frame, text="未啟用 / Disabled",
                                font=("times new roman", 10), bg="#2B2B2B", fg="#888888",
                                wraplength=360, justify="left")
median_status_label.pack(anchor='w', padx=4, pady=(0, 2))

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
deglint_k_scale = tk.Scale(mf_frame, from_=1.0, to=8.0, resolution=0.1,
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

# ── 亮度不均校正 UI ────────────────────────────────────────────────────────────
illum_frame = tk.LabelFrame(right_frame, text="亮度校正 / Illumination Correction",
                            padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                            bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
illum_frame.pack(fill='both', padx=6, pady=4, expand=True)
illum_mode_var = tk.StringVar(value="off")
illum_radios = []
for _lbl, _val in (("關閉 / Off", "off"),
                   ("背景估計(免參考影像)/ Background fit", "background"),
                   ("平場參考(較準,需空白樣本)/ Flat-field", "flat")):
    _rb = tk.Radiobutton(illum_frame, text=_lbl, variable=illum_mode_var, value=_val,
                         command=lambda: toggle_illum_mode(), font=RADIO_FONT, anchor="w",
                         bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
                         activebackground="#2B2B2B", activeforeground="#00BFFF")
    _rb.pack(anchor='w', padx=4, fill='x')
    illum_radios.append(_rb)
illum_btn_row = tk.Frame(illum_frame, bg="#2B2B2B"); illum_btn_row.pack(fill='x', padx=4, pady=(4, 2))
illum_preview_btn = ttk.Button(illum_btn_row, text="預覽校正 / Preview", style="Apply.TButton",
                               command=lambda: show_illum_preview())
illum_preview_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))
flat_capture_btn = ttk.Button(illum_btn_row, text="擷取平場 / Capture flat", style="Apply.TButton",
                              command=lambda: capture_flat_field())
flat_capture_btn.pack(side="left", expand=True, fill="x", padx=(2, 0))
illum_status = tk.Label(illum_frame, text="未校正 / Off", font=("times new roman", 10),
                        bg="#2B2B2B", fg="#888888", wraplength=360, justify="left")
illum_status.pack(anchor='w', padx=4, pady=(0, 2))

adv_btn = ttk.Button(right_frame, text="進階設定 / Advanced ⚙", style="Apply.TButton",
                     command=lambda: show_advanced())
adv_btn.pack(fill='x', padx=6, pady=(0, 6), after=settings_label)   # 放在標題下方,不用捲動

# ── 灰階分佈 / 對比增強 UI ────────────────────────────────────────────────────
level_frame = tk.LabelFrame(adv_frame, text="灰階分佈 / Grey-level & Contrast",
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
level_select_btn.pack(fill="x")
level_auto_btn   = ttk.Button(ct_btn_row, text="自動對比 / Auto", style="Apply.TButton")
level_auto_btn.pack(side="left", expand=True, fill="x", padx=(2,2))
level_reset_btn  = ttk.Button(ct_btn_row, text="重置對比 / Reset", style="Apply.TButton")
level_reset_btn.pack(side="left", expand=True, fill="x", padx=(2,0))

level_status_label = tk.Label(ct_frame, text="", font=("times new roman", 10),
                              bg="#2B2B2B", fg="#888888", wraplength=360, justify="left")
level_status_label.pack(anchor='w', padx=4, pady=(0,2))

# ── 比例尺設定 UI ──────────────────────────────────────────────────────────────
scale_frame = tk.LabelFrame(adv_frame, text="比例尺 / Scale Bar",
                             padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT,
                             bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
scale_frame.pack(fill='both', padx=6, pady=4, expand=True)

tk.Label(scale_frame, text="單位 / Unit:", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=4)
scale_unit_var = tk.StringVar(value="mm")
scale_unit_entry = ttk.Entry(scale_frame, width=8, font=ENTRY_FONT,
                              textvariable=scale_unit_var)
scale_unit_entry.grid(row=0, column=1, sticky='w', padx=2, pady=4)

scale_draw_btn = ttk.Button(scale_frame, text="畫比例線 / Draw Scale Line",
                             style="Apply.TButton")
scale_draw_btn.grid(row=1, column=0, columnspan=2, sticky='ew', padx=2, pady=4)

scale_status_label = tk.Label(scale_frame,
                               text="尚未設定 / Not set",
                               font=("times new roman", 10), bg="#2B2B2B", fg="#888888",
                               wraplength=360, justify="left")
scale_status_label.grid(row=2, column=0, columnspan=2, sticky='w', padx=2, pady=(2, 4))

scale_clear_btn = ttk.Button(scale_frame, text="清除比例尺 / Clear Scale",
                              style="Apply.TButton")
scale_clear_btn.grid(row=3, column=0, columnspan=2, sticky='ew', padx=2, pady=4)


# ── Median Filter 核心函式 ────────────────────────────────────────────────────

def apply_median_filter(patch):
    """
    Method A：用中值濾波取代灰塵像素值。
    必須在 threshold 之前呼叫（threshold 會產生非矩形區域，無法做 medianBlur）。
    """
    if patch is None or patch.size == 0:
        return patch
    if min(patch.shape[:2]) <= MEDIAN_KERNEL:
        return patch          # patch 太小，跳過
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


def _roi_slice(shape, r):
    """回傳 ROI 在整張影像中的切片邊界 (y1, y2, x1, x2),與 get_roi_patch 相同裁切。"""
    h, w = shape[:2]
    if r[0] == 'rect':
        _, x1, y1, x2, y2 = r
        return (max(0, int(y1)), min(h, int(y2)), max(0, int(x1)), min(w, int(x2)))
    _, cx, cy, rad = r
    cx = int(round(cx)); cy = int(round(cy)); rad = int(round(rad))
    return (max(0, cy - rad), min(h, cy + rad), max(0, cx - rad), min(w, cx + rad))


def _roi_glint(gray, r, cmask=None):
    """只對單一 ROI 做 White Top-hat 去反光,回傳與 get_roi_patch 同形狀的布林遮罩(None = ROI 無效)。
    opening 在 ROI 外擴 kernel 寬的區塊上做,避免 ROI 邊緣被誤判;
    門檻 median + K·1.4826·MAD 只用此 ROI 內的 top-hat 殘留統計,不受其他 ROI、背景或 ROI 內灰塵多寡影響。"""
    y1, y2, x1, x2 = _roi_slice(gray.shape, r)
    if y2 <= y1 or x2 <= x1:
        return None
    m = DEGLINT_KERNEL
    H, W = gray.shape[:2]
    py1, py2, px1, px2 = max(0, y1 - m), min(H, y2 + m), max(0, x1 - m), min(W, x2 + m)
    k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DEGLINT_KERNEL, DEGLINT_KERNEL))
    th = cv2.morphologyEx(gray[py1:py2, px1:px2], cv2.MORPH_TOPHAT, k)
    th = th[y1 - py1:y2 - py1, x1 - px1:x2 - px1]
    inside = (th[cmask == 1] if cmask is not None and cmask.shape == th.shape else th).astype(np.float32)
    if inside.size == 0:
        return None
    # 穩健門檻:中位數 / MAD 不會被 ROI 內的灰塵本身拉高(mean + K·std 會,灰塵越多漏越多)
    med = float(np.median(inside))
    mad = max(float(np.median(np.abs(inside - med))), 1.0)   # ponytail: 下限 1 灰階,避免極平坦 ROI 的 MAD=0 把中位數以上全剔除
    return th > (med + DEGLINT_K * 1.4826 * mad)


def _deglint_overlay(display_frame, gray, r):
    """在 display_frame 上把 ROI r 內被去除的反光像素染紅,回傳去除%。"""
    patch, cmask = get_roi_patch(gray, r)
    if patch is None or patch.size == 0:
        return 0.0
    y1, y2, x1, x2 = _roi_slice(gray.shape, r)
    reject = _roi_glint(gray, r, cmask)
    if reject is None or reject.shape != patch.shape[:2]:
        return 0.0
    valid = np.ones(patch.shape[:2], bool)
    if cmask is not None:
        valid &= (cmask == 1)
    if threshold_value is not None:
        valid &= (patch <= threshold_value)
    reject &= valid
    n_valid = int(valid.sum())
    pct = 100.0 * int(reject.sum()) / n_valid if n_valid else 0.0
    sub = display_frame[y1:y2, x1:x2]
    if sub.shape[:2] == reject.shape:
        sub[reject] = [255, 0, 0]
    return pct


def compute_roi_mean(patch, circle_mask=None, glint_sub=None, gain_sub=None):
    """
    正確順序：medianBlur(若啟用) → threshold → 圓形遮罩 → 去反光 → 亮度校正(若有 gain_sub) → 平均
    Threshold 與去反光都看原始灰階;亮度校正只作用在留下來的像素。
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

    # De-glint：此 ROI 的 top-hat 反光遮罩,被判為反光的像素不計入平均
    if deglint_enabled and glint_sub is not None and glint_sub.shape == valid.shape:
        valid &= ~glint_sub

    px = work[valid]
    if px.size and gain_sub is not None and gain_sub.shape == valid.shape:
        px = apply_illum_gain(px, gain_sub[valid])
    return (float(np.mean(px)) if px.size > 0 else 0.0), changed_ratio


# ── 亮度不均校正 ──────────────────────────────────────────────────────────────

def apply_illum_gain(vals, gain):
    """校正值 = 暗場值 + (原始值 − 暗場值) × 增益。"""
    return illum_dark + (np.asarray(vals, np.float32) - illum_dark) * gain


def _poly_terms(x, y, deg):
    """2D 多項式基底 x^i·y^j(i+j ≤ deg),座標先正規化到 [-1, 1] 避免數值問題。"""
    return np.stack([x ** i * y ** j for i in range(deg + 1) for j in range(deg + 1 - i)], -1)


def estimate_illumination(gray, roi_list):
    """背景擬合照明分佈:不需參考影像,假設背景亮度與照明成正比。
    去灰塵(median 5)→ 降採樣 → 排除 ROI 外擴區(樣本)→ 2 次多項式 + 非對稱 sigma clipping
    (比擬合面亮太多的點=樣本/灰塵剔除,暗一點的容忍)。
    回傳 (照明圖 float32 顯示座標, 背景取樣點 (ys, xs)) ;背景點太少回傳 (None, None)。"""
    x0, y0 = img_pad_x, img_pad_y
    sub = gray[y0:y0 + img_disp_h, x0:x0 + img_disp_w]
    H, W = sub.shape[:2]
    sm = cv2.medianBlur(sub, 5).astype(np.float32)
    step = max(1, int(max(H, W) / 200))                   # 約 200 點寬的取樣格
    ys, xs = np.mgrid[0:H:step, 0:W:step]
    keep = np.ones(ys.shape, bool)
    for r in roi_list:
        ry1, ry2, rx1, rx2 = _roi_slice(gray.shape, r)
        rx1 -= x0; rx2 -= x0; ry1 -= y0; ry2 -= y0
        ex, ey = ILLUM_EXCLUDE * (rx2 - rx1), ILLUM_EXCLUDE * (ry2 - ry1)
        keep &= ~((xs >= rx1 - ex) & (xs < rx2 + ex) & (ys >= ry1 - ey) & (ys < ry2 + ey))
    ys, xs = ys[keep], xs[keep]
    nterm = (ILLUM_DEG + 1) * (ILLUM_DEG + 2) // 2
    if ys.size < nterm * 10:
        return None, None
    A = _poly_terms(xs / max(W - 1, 1) * 2 - 1, ys / max(H - 1, 1) * 2 - 1, ILLUM_DEG)
    b = sm[ys, xs]
    ok = np.ones(b.shape, bool)
    for _ in range(10):
        coef = np.linalg.lstsq(A[ok], b[ok], rcond=None)[0]
        res = b - A @ coef
        s = 1.4826 * float(np.median(np.abs(res[ok] - np.median(res[ok])))) + 1e-6
        new = (res < 2.0 * s) & (res > -3.0 * s)
        if (new == ok).all() or new.sum() < nterm * 10:
            break
        ok = new
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    fit = _poly_terms(xx / max(W - 1, 1) * 2 - 1, yy / max(H - 1, 1) * 2 - 1, ILLUM_DEG) @ coef.astype(np.float32)
    illum = np.full(gray.shape[:2], float(np.median(b[ok])), np.float32)
    illum[y0:y0 + H, x0:x0 + W] = fit
    return illum, (ys[ok] + y0, xs[ok] + x0)


def flat_illumination(avg):
    """平場參考影像 → 平滑的照明分佈(去灰塵 + 大範圍高斯模糊,保留暗角等真實形狀)。"""
    x0, y0 = img_pad_x, img_pad_y
    sub = np.clip(avg[y0:y0 + img_disp_h, x0:x0 + img_disp_w], 0, 255).astype(np.uint8)
    sm = cv2.medianBlur(sub, 5).astype(np.float32)
    sm = cv2.GaussianBlur(sm, (0, 0), sigmaX=max(sm.shape) / 40.0)
    illum = np.full(avg.shape[:2], float(sm.mean()), np.float32)
    illum[y0:y0 + sm.shape[0], x0:x0 + sm.shape[1]] = sm
    return illum


def make_illum_gain(illum, roi_list):
    """增益圖:以各 ROI 位置的平均照明為目標,讓校正後的數值維持在原本的量級。"""
    den = np.clip(illum - illum_dark, 1.0, None)          # ponytail: 照明 ≤ 暗場+1 視為 1,避免除以 0
    pix = [illum[y1:y2, x1:x2] for (y1, y2, x1, x2) in (_roi_slice(illum.shape, r) for r in roi_list)]
    pix = [p for p in pix if p.size]
    target = float(np.mean(np.concatenate([p.ravel() for p in pix]))) if pix else \
             float(np.median(illum[img_pad_y:img_pad_y + img_disp_h, img_pad_x:img_pad_x + img_disp_w]))
    return ((target - illum_dark) / den).astype(np.float32)


def _read_illum_dark():
    global illum_dark
    try:
        illum_dark = min(254.0, max(0.0, float(illum_dark_entry.get().strip() or 0)))
    except Exception:
        illum_dark = 0.0
        illum_dark_entry.delete(0, tk.END); illum_dark_entry.insert(0, "0")
    return illum_dark


def build_illum_correction(gray, roi_list, mode):
    """依模式算出 (增益圖, 背景取樣點, 說明文字);失敗回傳 (None, None, 錯誤訊息)。"""
    _read_illum_dark()
    if mode == "background":
        illum, pts = estimate_illumination(gray, roi_list)
        if illum is None:
            return None, None, ("背景區域太小,無法擬合照明。請縮小 ROI 或改用平場參考。\n"
                                "Not enough background to fit illumination.")
        info = f"background fit (poly deg {ILLUM_DEG})"
    elif mode == "flat":
        if flat_field is None:
            return None, None, ("尚未擷取平場參考。請放上均勻空白樣本後按「擷取平場」。\n"
                                "No flat-field reference yet: press 'Capture flat'.")
        if flat_field.shape != gray.shape[:2]:
            return None, None, "平場參考的影像尺寸與目前不同,請重新擷取。\nFlat-field size mismatch; capture again."
        illum, pts = flat_field, None
        info = f"flat-field ({flat_saved_at})"
    else:
        return None, None, ""
    return make_illum_gain(illum, roi_list), pts, f"Illumination correction: {info}, dark={illum_dark:g}"


def roi_gain_factors(gain, roi_list):
    out = []
    for r in roi_list:
        y1, y2, x1, x2 = _roi_slice(gain.shape, r)
        out.append(float(gain[y1:y2, x1:x2].mean()) if y2 > y1 and x2 > x1 else 1.0)
    return out


def prepare_illum_correction():
    """開始量測前呼叫:依目前模式、畫面與 ROI 算好增益圖(量測期間固定不變)。失敗回傳 False。"""
    global illum_gain, illum_factors, illum_info
    illum_gain, illum_factors, illum_info = None, [], "Illumination correction: OFF"
    if illum_mode == "off":
        return True
    with frame_lock:
        frame = current_frame.copy() if current_frame is not None else None
    if frame is None:
        messagebox.showwarning("無影像 / No Frame", "尚未取得影像,無法計算亮度校正。")
        return False
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    gain, _, msg = build_illum_correction(gray, rois, illum_mode)
    if gain is None:
        messagebox.showwarning("亮度校正失敗 / Correction failed", msg)
        return False
    illum_gain, illum_factors, illum_info = gain, roi_gain_factors(gain, rois), msg
    return True


def _stretch_pair(a, b):
    """兩張圖用同一組對比範圍(以原圖的 1~99.5 百分位)拉伸,才能公平比較。"""
    lo, hi = np.percentile(a, 1), np.percentile(a, 99.5)
    f = lambda im: np.clip((im.astype(np.float32) - lo) * 255.0 / max(1.0, hi - lo), 0, 255).astype(np.uint8)
    return f(a), f(b)


def show_illum_preview():
    """預覽亮度校正:原圖 / 照明分佈(含各 ROI 增益)/ 校正後,附各 ROI 校正前後平均值。"""
    global illum_preview_win
    if illum_mode == "off":
        messagebox.showinfo("亮度校正未開啟 / Off", "請先選擇「背景估計」或「平場參考」。\nChoose a correction mode first.")
        return
    with frame_lock:
        frame = current_frame.copy() if current_frame is not None else None
    if frame is None:
        messagebox.showwarning("無影像 / No Frame", "尚未取得影像。\nNo frame available yet.")
        return
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    gain, pts, msg = build_illum_correction(gray, rois, illum_mode)
    if gain is None:
        messagebox.showwarning("亮度校正失敗 / Correction failed", msg)
        return

    x0, y0, W, H = img_pad_x, img_pad_y, img_disp_w, img_disp_h
    sub, gsub = gray[y0:y0 + H, x0:x0 + W], gain[y0:y0 + H, x0:x0 + W]
    corr = apply_illum_gain(sub, gsub)
    a, b = _stretch_pair(sub, corr)
    illum_vis = 1.0 / gsub                                 # 照明相對強度(增益的倒數)
    iv = cv2.normalize(illum_vis, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    imap = cv2.cvtColor(cv2.applyColorMap(iv, cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)
    a, b = cv2.cvtColor(a, cv2.COLOR_GRAY2RGB), cv2.cvtColor(b, cv2.COLOR_GRAY2RGB)

    lines, facs = [], roi_gain_factors(gain, rois)
    for i, r in enumerate(rois):
        patch, cmask = get_roi_patch(gray, r)
        if patch is None or patch.size == 0:
            continue
        gs = _roi_glint(gray, r, cmask) if deglint_enabled else None
        y1, y2, x1, x2 = _roi_slice(gray.shape, r)
        m0, _ = compute_roi_mean(patch, cmask, gs)
        m1, _ = compute_roi_mean(patch, cmask, gs, gain[y1:y2, x1:x2])
        lines.append(f"S{i+1:<2}  x{facs[i]:.3f}   {m0:8.2f} -> {m1:8.2f}")
        for im in (a, imap, b):
            cv2.rectangle(im, (x1 - x0, y1 - y0), (x2 - x0, y2 - y0), (255, 215, 0), 1)
        cv2.putText(imap, f"x{facs[i]:.2f}", (x1 - x0, max(12, y1 - y0 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    cv_txt = ""
    if pts is not None and len(pts[0]) > 10:                # 背景不均勻度(背景取樣點的 CV)
        sm = cv2.medianBlur(gray, 5).astype(np.float32)
        v0 = sm[pts]; v1 = apply_illum_gain(v0, gain[pts])
        cv_txt = (f"  |  背景不均勻度 CV {100 * v0.std() / max(v0.mean(), 1e-6):.1f}% → "
                  f"{100 * v1.std() / max(v1.mean(), 1e-6):.1f}%")

    try:
        if illum_preview_win is not None:
            illum_preview_win.destroy()
    except Exception:
        pass
    illum_preview_win = tk.Toplevel(root)
    illum_preview_win.title("亮度校正預覽 / Illumination Correction Preview")
    illum_preview_win.configure(bg="#1E1E1E")
    tk.Label(illum_preview_win, text=msg + cv_txt, font=("Arial", 12, "bold"),
             bg="#1E1E1E", fg="#00BFFF").pack(pady=(8, 2))
    tk.Label(illum_preview_win,
             text="左:原圖 / 中:照明分佈(紅亮藍暗,數字為各 ROI 增益)/ 右:校正後(與原圖同一對比範圍)",
             font=("Arial", 10), bg="#1E1E1E", fg="#888888").pack(pady=(0, 6))

    SC = min((root.winfo_screenwidth() * 0.94 - 40) / (3.0 * W), root.winfo_screenheight() * 0.55 / H)
    SC = max(0.05, min(SC, 4.0))
    row = tk.Frame(illum_preview_win, bg="#1E1E1E"); row.pack(padx=8)
    refs = []
    for title, im in (("原圖 / Original", a), ("照明分佈 / Illumination", imap), ("校正後 / Corrected", b)):
        col = tk.Frame(row, bg="#1E1E1E"); col.pack(side="left", padx=4)
        tk.Label(col, text=title, font=("Arial", 11), bg="#1E1E1E", fg="#E0E0E0").pack()
        big = cv2.resize(im, (max(1, int(W * SC)), max(1, int(H * SC))), interpolation=cv2.INTER_AREA)
        tkim = ImageTk.PhotoImage(Image.fromarray(big)); refs.append(tkim)
        tk.Label(col, image=tkim, bg="#2B2B2B").pack()
    illum_preview_win.refs = refs
    if lines:
        tk.Label(illum_preview_win, text="ROI  增益      校正前 ->   校正後\n" + "\n".join(lines),
                 font=("Consolas", 10), bg="#1E1E1E", fg="#00FF7F", justify="left").pack(pady=6)
    btnf = tk.Frame(illum_preview_win, bg="#1E1E1E"); btnf.pack(fill="x", padx=10, pady=(0, 10))
    tk.Button(btnf, text="重新擷取 / Refresh", command=show_illum_preview, font=("Arial", 11),
              bg="#0078D4", fg="white", height=2).pack(side="left", expand=True, fill="x", padx=(0, 4))
    tk.Button(btnf, text="關閉 / Close", command=illum_preview_win.destroy, font=("Arial", 11),
              bg="#555555", fg="white", height=2).pack(side="left", expand=True, fill="x", padx=(4, 0))


def _flat_path():
    return os.path.join(APP_DIR, "calibration", "flat_field.npz")


def _update_illum_status():
    txt = {"off": "未校正 / Off",
           "background": "背景估計:開始量測時用 ROI 以外的背景擬合照明",
           "flat": "平場參考:" + (f"已擷取({flat_saved_at})" if flat_field is not None else "尚未擷取,請按「擷取平場」")}[illum_mode]
    illum_status.config(text=txt, fg="#888888" if illum_mode == "off" else
                        ("#FF8C00" if illum_mode == "flat" and flat_field is None else "#00FF7F"))


def toggle_illum_mode():
    global illum_mode
    illum_mode = illum_mode_var.get()
    _update_illum_status()


def load_flat_field(silent=False):
    """讀 calibration/flat_field.npz;影像座標空間不符就不用(相機或解析度換了要重拍)。"""
    global flat_field, flat_saved_at
    path = _flat_path()
    if not os.path.exists(path):
        return False
    try:
        d = np.load(path)
        meta = tuple(int(v) for v in d["letterbox"])
        if meta != (img_disp_w, img_disp_h, img_pad_x, img_pad_y):
            if not silent:
                messagebox.showwarning("平場不符 / Mismatch", "平場參考的相機解析度與目前不同,請重新擷取。")
            return False
        flat_field, flat_saved_at = d["illum"].astype(np.float32), str(d["saved_at"])
    except Exception as e:
        if not silent:
            messagebox.showerror("讀取平場失敗 / Load failed", str(e))
        return False
    _update_illum_status()
    return True


def capture_flat_field():
    """擷取平場參考:平均多張影像 → 平滑照明分佈 → 存 calibration/flat_field.npz。"""
    if analyzing or roi_locked:
        messagebox.showinfo("量測中 / Running", "量測中無法擷取平場。\nCannot capture while running.")
        return
    if not messagebox.askokcancel(
            "擷取平場 / Capture flat-field",
            "請在樣本位置放上「均勻」的空白參考(空白片 / 均勻螢光片),\n"
            "光源、Gain、Exposure 與量測時相同。\n\n"
            f"按確定後平均 {FLAT_FRAMES} 張影像作為照明分佈。"):
        return
    frames, last, t0 = [], [-1], time.time()

    def _grab():
        global flat_field, flat_saved_at
        with frame_lock:
            f, s = current_frame, frame_seq
        if f is not None and s != last[0]:
            frames.append(f.astype(np.float32)); last[0] = s
        if len(frames) < FLAT_FRAMES and time.time() - t0 < 10:
            root.after(20, _grab)
            return
        if not frames:
            messagebox.showwarning("無影像 / No Frame", "沒有取得影像。"); return
        avg = np.mean(frames, axis=0)
        flat_field = flat_illumination(avg)
        flat_saved_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            os.makedirs(os.path.dirname(_flat_path()), exist_ok=True)
            np.savez_compressed(_flat_path(), illum=flat_field, saved_at=flat_saved_at, camera=str(CAMERA_TYPE),
                                letterbox=np.array([img_disp_w, img_disp_h, img_pad_x, img_pad_y]))
        except Exception as e:
            messagebox.showerror("存檔失敗 / Save failed", str(e))
        illum_mode_var.set("flat"); toggle_illum_mode()
        sub = flat_field[img_pad_y:img_pad_y + img_disp_h, img_pad_x:img_pad_x + img_disp_w]
        messagebox.showinfo("平場已擷取 / Flat captured",
                            f"平均 {len(frames)} 張。照明最暗 / 最亮 = {sub.min() / sub.max():.2f}\n"
                            f"已存:{os.path.normpath(_flat_path())}")

    root.after(0, _grab)


def show_median_preview():
    """並排顯示 ROI 的濾波前 / 後 / 差異圖，附統計比對。"""
    global median_preview_win

    if len(rois) == 0:
        messagebox.showinfo("尚未選取 ROI / No ROI",
                            "請先框選至少一個 ROI。\nPlease select at least one ROI first.")
        return

    with frame_lock:
        frame = current_frame.copy() if current_frame is not None else None
    if frame is None:
        messagebox.showwarning("無影像 / No Frame", "尚未取得影像。\nNo frame available yet.")
        return

    if median_preview_win is not None:
        try:
            median_preview_win.destroy()
        except Exception:
            pass

    median_preview_win = tk.Toplevel(root)
    median_preview_win.title("Median Filter 預覽 / Median Filter Preview")
    median_preview_win.configure(bg="#1E1E1E")

    outer = tk.Canvas(median_preview_win, bg="#1E1E1E", highlightthickness=0)
    vsb   = tk.Scrollbar(median_preview_win, orient=tk.VERTICAL, command=outer.yview)
    outer.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    outer.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(outer, bg="#1E1E1E")
    outer.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: outer.configure(scrollregion=outer.bbox("all")))

    def _wheel(e):
        try:
            outer.yview_scroll(int(-1*(e.delta/120)), "units")
        except Exception:
            pass
    outer.bind("<Enter>", lambda e: outer.bind_all("<MouseWheel>", _wheel))
    outer.bind("<Leave>", lambda e: outer.unbind_all("<MouseWheel>"))

    tk.Label(inner,
             text=f"Median Filter (kernel={MEDIAN_KERNEL})  |  Threshold = {threshold_entry.get().strip() or 'N/A'}",
             font=("Arial", 14, "bold"), bg="#1E1E1E", fg="#00BFFF").pack(pady=(10, 2))
    tk.Label(inner,
             text="紅色 = 被 median filter 修正的像素（灰塵）\n"
                  "Red = pixels corrected by median filter (dust)",
             font=("Arial", 10), bg="#1E1E1E", fg="#888888").pack(pady=(0, 8))

    keep_refs = []

    try:
        thr_v = float(threshold_entry.get().strip())
    except Exception:
        thr_v = None

    for i, r in enumerate(rois):
        patch, cmask = get_roi_patch(frame, r)
        if patch is None or patch.size == 0:
            continue

        clean   = apply_median_filter(patch)
        diffmap = np.abs(patch.astype(np.int16) - clean.astype(np.int16))
        changed = diffmap > MEDIAN_DIFF_THRESH

        # 顯示用：放大到易於觀察
        SC = max(1, min(6, int(320 / max(patch.shape[0], patch.shape[1], 1))))
        SC = max(SC, 2)

        def to_rgb(g):
            return cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)

        p_before = to_rgb(patch)
        p_after  = to_rgb(clean)
        p_diff   = to_rgb(patch.copy())
        p_diff[changed] = [255, 40, 40]

        # 圓形 ROI：把圓外變暗
        if cmask is not None:
            for pim in (p_before, p_after, p_diff):
                pim[cmask == 0] = (pim[cmask == 0] * 0.25).astype(np.uint8)

        blk = tk.LabelFrame(inner, text=f"Sample {i+1}", font=("Arial", 12, "bold"),
                            bg="#2B2B2B", fg="#00BFFF", padx=8, pady=6)
        blk.pack(fill="x", padx=10, pady=6)

        prow = tk.Frame(blk, bg="#2B2B2B")
        prow.pack()

        for title, im in [("濾波前 / Before", p_before),
                          ("濾波後 / After",  p_after),
                          ("差異 / Diff",     p_diff)]:
            col = tk.Frame(prow, bg="#2B2B2B")
            col.pack(side="left", padx=6)
            tk.Label(col, text=title, font=("Arial", 10), bg="#2B2B2B", fg="#E0E0E0").pack()
            big = cv2.resize(im, (im.shape[1]*SC, im.shape[0]*SC),
                             interpolation=cv2.INTER_NEAREST)
            tkim = ImageTk.PhotoImage(Image.fromarray(big))
            keep_refs.append(tkim)
            lb = tk.Label(col, image=tkim, bg="#2B2B2B", bd=1, relief="solid")
            lb.image = tkim
            lb.pack()

        # ── 統計比對 ──
        def stat(arr, mask):
            v = np.ones(arr.shape[:2], bool)
            if mask is not None:
                v &= (mask == 1)
            if thr_v is not None:
                v &= (arr <= thr_v)
            px = arr[v]
            return (px.mean() if px.size else 0.0,
                    px.std()  if px.size else 0.0,
                    int(px.size))

        mb, sb, nb = stat(patch, cmask)
        ma, sa, na = stat(clean, cmask)
        n_changed  = int((changed & (cmask == 1)).sum()) if cmask is not None else int(changed.sum())
        n_total    = int((cmask == 1).sum()) if cmask is not None else int(patch.size)
        ratio      = n_changed / n_total * 100.0 if n_total else 0.0

        info = (
            f"被修正像素 / Corrected : {n_changed} px  ({ratio:.2f}%)\n"
            f"─────────────────────────────────────────\n"
            f"{'':16}{'Before':>12}{'After':>12}{'Delta':>12}\n"
            f"{'Mean':16}{mb:12.3f}{ma:12.3f}{ma-mb:+12.3f}\n"
            f"{'Std Dev':16}{sb:12.3f}{sa:12.3f}{sa-sb:+12.3f}\n"
            f"{'有效像素 / N':16}{nb:12d}{na:12d}{na-nb:+12d}"
        )
        tk.Label(blk, text=info, font=("Courier New", 10), bg="#2B2B2B",
                 fg="#00FF7F", justify="left").pack(anchor="w", pady=(6, 2))

    median_preview_win.keep_refs = keep_refs

    btnf = tk.Frame(inner, bg="#1E1E1E")
    btnf.pack(fill="x", padx=10, pady=10)
    tk.Button(btnf, text="重新擷取 / Refresh", command=lambda: show_median_preview(),
              font=("Arial", 11), bg="#0078D4", fg="white",
              activebackground="#107C10", activeforeground="white", height=2
              ).pack(side="left", expand=True, fill="x", padx=(0, 4))
    tk.Button(btnf, text="關閉 / Close", command=median_preview_win.destroy,
              font=("Arial", 11), bg="#555555", fg="white",
              activebackground="#777777", activeforeground="white", height=2
              ).pack(side="left", expand=True, fill="x", padx=(4, 0))

    median_preview_win.update_idletasks()
    w = min(inner.winfo_reqwidth() + 30, int(root.winfo_screenwidth() * 0.9))
    h = min(inner.winfo_reqheight() + 30, int(root.winfo_screenheight() * 0.85))
    median_preview_win.geometry(f"{w}x{h}")


def toggle_median_filter():
    """啟用時，若已有 ROI 則自動跳出預覽視窗。"""
    global median_filter_enabled, median_preview_win
    median_filter_enabled = median_enable_var.get()

    if median_filter_enabled:
        median_status_label.config(
            text=f"已啟用 / Enabled (kernel={MEDIAN_KERNEL})", fg="#00FF7F")
        if len(rois) > 0:
            root.after(100, show_median_preview)      # ← 框完 ROI 啟用即跳窗
        else:
            median_status_label.config(
                text="已啟用，但尚未選取 ROI。\nEnabled, but no ROI selected yet.",
                fg="#FFD700")
    else:
        median_status_label.config(text="未啟用 / Disabled", fg="#888888")
        if median_preview_win is not None:
            try:
                median_preview_win.destroy()
            except Exception:
                pass
            median_preview_win = None


# ── 邏輯函式 ─────────────────────────────────────────────────────────────────

def deglint_roi_stats(gray, r):
    """單一 ROI 的去反光結果:(patch, 圓形遮罩, 反光遮罩, 去除%, 去除前平均, 去除後平均)。
    有效像素 = 圓形遮罩內且 ≤ Threshold,與量測時的定義一致。ROI 無效回傳 None。"""
    patch, cmask = get_roi_patch(gray, r)
    if patch is None or patch.size == 0:
        return None
    rej = _roi_glint(gray, r, cmask)
    if rej is None or rej.shape != patch.shape[:2]:
        return None
    valid = np.ones(patch.shape[:2], bool)
    if cmask is not None:
        valid &= (cmask == 1)
    if threshold_value is not None:
        valid &= (patch <= threshold_value)
    rej = rej & valid
    keep = valid & ~rej
    n = int(valid.sum())
    pct = 100.0 * int(rej.sum()) / n if n else 0.0
    mb = float(patch[valid].mean()) if n else 0.0
    ma = float(patch[keep].mean()) if keep.any() else 0.0
    return patch, cmask, rej, pct, mb, ma


def show_deglint_preview():
    """各 ROI 獨立 top-hat 去反光;每個 ROI 一欄:原圖 / 標紅(不計入) / 去掉的反光,附去除%與平均值變化。"""
    global deglint_preview_win

    if not rois:
        messagebox.showinfo("尚未設置 ROI / No ROI",
                            "去反光只處理 ROI 範圍,請先設置 ROI。\nDe-glint works on ROIs only; place ROIs first.")
        return
    with frame_lock:
        frame = current_frame.copy() if current_frame is not None else None
    if frame is None:
        messagebox.showwarning("無影像 / No Frame", "尚未取得影像。\nNo frame available yet.")
        return
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame

    blocks = []
    for i, r in enumerate(rois):
        st = deglint_roi_stats(gray, r)
        if st is None:
            continue
        patch, cmask, rej, pct, mb, ma = st
        before  = cv2.cvtColor(patch, cv2.COLOR_GRAY2RGB)
        marked  = before.copy(); marked[rej] = [255, 0, 0]          # 標紅:這些不納入計算
        removed = np.zeros_like(before); removed[rej] = [255, 0, 0]  # 只顯示被去掉的
        if cmask is not None:                                         # 圓形 ROI:圓外變暗
            for im in (before, marked):
                im[cmask == 0] = (im[cmask == 0] * 0.25).astype(np.uint8)
        blocks.append((i, before, marked, removed, pct, mb, ma))
    if not blocks:
        messagebox.showwarning("ROI 無效 / Invalid ROI", "ROI 不在影像範圍內。\nROIs are outside the image.")
        return

    if deglint_preview_win is not None:
        try:
            deglint_preview_win.destroy()
        except Exception:
            pass

    deglint_preview_win = tk.Toplevel(root)
    deglint_preview_win.title("De-glint 去亮反光預覽(各 ROI) / De-glint Preview per ROI")
    deglint_preview_win.configure(bg="#1E1E1E")

    # 放大倍率:讓所有 ROI 欄位排得下(每列最多 8 個 ROI,超過換行)
    ncol  = min(len(blocks), 8)
    nrow  = (len(blocks) + ncol - 1) // ncol
    pw    = max(b[1].shape[1] for b in blocks)
    ph    = max(b[1].shape[0] for b in blocks)
    scr_w = int(root.winfo_screenwidth()  * 0.94)
    scr_h = int(root.winfo_screenheight() * 0.75)
    SC = min((scr_w - 40) / (ncol * (pw + 14)), (scr_h - 120) / (nrow * 3 * (ph + 12) + nrow * 60))
    SC = max(0.5, min(SC, 6.0))

    tk.Label(deglint_preview_win,
             text=f"各 ROI 獨立 White Top-hat  |  kernel={DEGLINT_KERNEL}  K={DEGLINT_K:.2f}"
                  f"  |  門檻 = median + K·1.4826·MAD(ROI 內 top-hat 殘留)",
             font=("Arial", 12, "bold"), bg="#1E1E1E", fg="#00BFFF").pack(pady=(8, 2))
    tk.Label(deglint_preview_win,
             text="每欄由上到下:原圖 / 標紅(不計入) / 去掉的反光。紅色 = 被判為反光的像素,不納入平均計算\n"
                  "Each column: original / marked / removed. Red = glint pixels, excluded from the mean",
             font=("Arial", 10), bg="#1E1E1E", fg="#888888").pack(pady=(0, 6))

    grid = tk.Frame(deglint_preview_win, bg="#1E1E1E"); grid.pack(padx=8, pady=(0, 8))
    keep_refs = []
    for k, (i, before, marked, removed, pct, mb, ma) in enumerate(blocks):
        col = tk.Frame(grid, bg="#2B2B2B", bd=1, relief="solid")
        col.grid(row=k // ncol, column=k % ncol, padx=4, pady=4, sticky="n")
        tk.Label(col, text=f"Sample {i+1}", font=("Arial", 11, "bold"),
                 bg="#2B2B2B", fg="#00BFFF").pack(pady=(3, 2))
        for im in (before, marked, removed):
            big  = cv2.resize(im, (max(1, int(im.shape[1] * SC)), max(1, int(im.shape[0] * SC))),
                              interpolation=cv2.INTER_NEAREST)
            tkim = ImageTk.PhotoImage(Image.fromarray(big)); keep_refs.append(tkim)
            lb = tk.Label(col, image=tkim, bg="#2B2B2B"); lb.image = tkim; lb.pack(padx=4, pady=2)
        tk.Label(col, text=f"去除 {pct:.2f}%\nMean {mb:.2f} → {ma:.2f}\n(Δ {ma-mb:+.2f})",
                 font=("Consolas", 9), bg="#2B2B2B", fg="#00FF7F", justify="center").pack(pady=(2, 4))
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
    thr_ok  = bool(threshold_entry.get().strip())
    dec_ok  = bool(dec_entry.get().strip())
    fps_ok  = bool(fps_input_entry.get().strip())
    roi_ok  = len(rois) > 0
    if is_image_mode():
        # 匯入圖片模式：Gain/Exposure 不需填（沒有相機）
        gain_ok = exp_ok = True
    else:
        gain_ok = bool(gain_entry.get().strip())
        exp_ok  = bool(exposure_entry.get().strip())
    if gain_ok and exp_ok and thr_ok and dec_ok and fps_ok and roi_ok:
        start_btn.config(state="normal")
    else:
        start_btn.config(state="disabled")

for widget in (gain_entry, exposure_entry, threshold_entry, dec_entry,
               fps_input_entry, roi_width_entry, roi_height_entry, roi_diameter_entry):
    widget.bind("<KeyRelease>", validate_start_enable)
gain_entry.bind("<FocusOut>", on_gain_exposure_change)
exposure_entry.bind("<FocusOut>", on_gain_exposure_change)
rb_rect_ui.config(command=lambda: (set_roi_shape('rect'), validate_start_enable()))
rb_circle_ui.config(command=lambda: (set_roi_shape('circle'), validate_start_enable()))
fps_input_entry.bind("<KeyRelease>", validate_start_enable)

def start_button_handler():
    global analyzing, roi_selected, roi_locked, threshold_value, decimal_places
    global user_gain_val, user_exposure_ms, user_fps_val, settings_applied

    img_mode = is_image_mode()

    # 匯入圖片模式不需要 Gain/Exposure
    required = [threshold_entry.get().strip(), dec_entry.get().strip(),
                fps_input_entry.get().strip()]
    if not img_mode:
        required += [gain_entry.get().strip(), exposure_entry.get().strip()]
    if not all(required):
        msg = ("請確認 Threshold、Decimal places 與 FPS 都已填寫。\n"
               "Please ensure Threshold, Decimal places and FPS are filled."
               if img_mode else
               "請確認 Gain、Exposure、Threshold、Decimal places 與 FPS 都已填寫。\n"
               "Please ensure Gain, Exposure, Threshold, Decimal places and FPS are filled.")
        messagebox.showwarning("設定未填齊 / Missing settings", msg)
        return

    try:
        fps_val = int(fps_input_entry.get().strip())
        if fps_val <= 0:
            raise ValueError
    except Exception:
        messagebox.showwarning("FPS 格式錯誤 / Invalid FPS", "FPS 必須為大於 0 的整數。\nFPS must be a positive integer.")
        return

    try:
        dec_v = int(dec_entry.get().strip())
        if dec_v < 0 or dec_v > 10:
            raise ValueError
    except Exception:
        messagebox.showwarning("小數位錯誤 / Invalid decimal places",
                               "請輸入 0~10 的整數作為小數位數。\nPlease enter an integer 0~10 for decimal places.")
        return

    try:
        thr_v = float(threshold_entry.get().strip())
        if thr_v < 0 or thr_v > 255:
            raise ValueError
    except Exception:
        messagebox.showwarning("門檻值錯誤 / Invalid Threshold",
                               "Threshold 必須在 0~255。\nThreshold must be between 0 and 255.")
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
        f"Threshold: {thr_v}",
        f"Decimal places: {dec_v}",
        f"FPS setting: {fps_val}",
        f"Median filter: {'ON (3x3)' if median_filter_enabled else 'OFF'}",
    ]

    if not prepare_illum_correction():
        return
    if illum_gain is not None:
        summary.append(illum_info.replace('Illumination correction', 'Illum correction'))
        summary.append('  gain: ' + ', '.join(f'S{i+1} x{f:.2f}' for i, f in enumerate(illum_factors)))
    else:
        summary.append('Illum correction: OFF')

    if scale_pixels_per_unit is not None:
        summary.append(f"比例尺 / Scale: {scale_pixels_per_unit:.2f} px/{scale_unit}")

    summary += ["", "請確認以上設定再開始偵測。\nPlease confirm the settings before starting."]
    if not messagebox.askokcancel("確認設定 / Confirm settings", "\n".join(summary)):
        globals()['illum_gain'] = None            # 取消就不保留剛算的校正
        return

    user_gain_val    = gain_v
    user_exposure_ms = exp_v
    threshold_value  = thr_v
    decimal_places   = dec_v
    user_fps_val     = fps_val
    settings_applied = True

    apply_gain_and_exposure_to_camera(user_gain_val, user_exposure_ms)

    roi_locked = True
    save_roi_layout(silent=True)   # 第一次量測自動記錄 ROI 座標
    threshold_entry.config(state="disabled")
    default_btn.state(["disabled"])
    gain_entry.config(state="disabled")
    exposure_entry.config(state="disabled")
    gain_apply_btn.config(state="disabled")
    exp_apply_btn.config(state="disabled")
    dec_entry.config(state="disabled")
    fps_input_entry.config(state="disabled")
    rb_rect_ui.config(state="disabled")
    rb_circle_ui.config(state="disabled")
    median_check.config(state="disabled")
    median_preview_btn.config(state="disabled")
    for w in illum_radios + [flat_capture_btn, illum_dark_entry]:   # 量測中校正方式固定
        w.config(state="disabled")

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

        if not roi_fixed:                # 固定 ROI 保留,不清除
            rois.clear()
        roi_data.clear()
        timestamps.clear()
        start_btn["text"] = "開始 / Start"
        default_btn.state(["!disabled"])

        global roi_locked, threshold_value, user_gain_val, user_exposure_ms
        global decimal_places, user_fps_val, settings_applied
        roi_locked = False
        threshold_value = None
        threshold_entry.config(state="normal")
        threshold_entry.delete(0, tk.END)
        threshold_entry.insert(0, "255")

        dec_entry.config(state="normal")
        fps_input_entry.config(state="normal")
        rb_rect_ui.config(state="normal")
        rb_circle_ui.config(state="normal")

        # ── Median filter 重置 ──
        median_check.config(state="normal")
        for w in illum_radios + [flat_capture_btn, illum_dark_entry]:
            w.config(state="normal")
        globals()['illum_gain'] = None; illum_factors.clear()
        median_preview_btn.config(state="normal")
        median_last_ratio.clear()
        median_enable_var.set(False)
        toggle_median_filter()

        # ── De-glint 重置 ──
        deglint_check.config(state="normal")
        deglint_preview_btn.config(state="normal")
        deglint_k_scale.config(state="normal")
        deglint_k_var.set(DEGLINT_K_DEFAULT)
        _set_deglint_k(DEGLINT_K_DEFAULT)
        deglint_show_check.config(state="normal")
        deglint_show_var.set(False)
        _toggle_show_removed()
        deglint_enable_var.set(False)
        toggle_deglint()

        dec_entry.delete(0, tk.END)
        dec_entry.insert(0, "2")
        fps_input_entry.delete(0, tk.END)

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
        user_fps_val     = None
        settings_applied = False
        validate_start_enable()          # 固定 ROI 時可直接再按開始
        messagebox.showinfo("已重置 / Restarted",
                            "已清空資料並重置設定，可重新設定並選取 ROI。\nData cleared and settings reset.")

def on_default():
    global rois, roi_data, timestamps, roi_selected
    if roi_locked:
        messagebox.showinfo("ROI 已鎖定 / ROI Locked",
                            "請先 Restart 才能重新選取 ROI。\nROI is locked; restart to reselect.")
        return
    if _fixed_blocked():
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


# ── 比例尺邏輯 ────────────────────────────────────────────────────────────────

def toggle_scale_mode():
    global scale_mode, scale_drawing, scale_line_disp
    if scale_mode:
        scale_mode    = False
        scale_drawing = False
        scale_draw_btn.config(text="畫比例線 / Draw Scale Line")
        scale_status_label.config(text="已取消 / Cancelled", fg="#888888")
    else:
        scale_mode = True
        scale_draw_btn.config(text="取消畫線 / Cancel Drawing")
        scale_status_label.config(
            text="請在影像上拖曳畫出一條已知長度的線段。\n"
                 "Drag on the image to draw a line of known length.",
            fg="#FFD700")

def clear_scale():
    global scale_mode, scale_drawing, scale_line_disp, scale_pixels_per_unit, scale_unit
    scale_mode            = False
    scale_drawing         = False
    scale_line_disp       = None
    scale_pixels_per_unit = None
    scale_unit            = "mm"
    scale_draw_btn.config(text="畫比例線 / Draw Scale Line")
    scale_status_label.config(text="尚未設定 / Not set", fg="#888888")

def finish_scale_line(x1, y1, x2, y2):
    """比例線畫完後彈出對話框讓使用者輸入長度"""
    global scale_pixels_per_unit, scale_unit, scale_mode, scale_drawing

    px_len = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    if px_len < 5:
        scale_status_label.config(text="線段太短，請重畫。\nLine too short, try again.", fg="#FF4444")
        scale_mode    = False
        scale_drawing = False
        scale_draw_btn.config(text="畫比例線 / Draw Scale Line")
        return

    unit = scale_unit_var.get().strip() or "mm"

    dlg = tk.Toplevel(root)
    dlg.title("輸入實際長度 / Enter Real Length")
    dlg.configure(bg="#2B2B2B")
    dlg.resizable(False, False)
    dlg.grab_set()

    tk.Label(dlg,
             text=f"此線段在影像中的長度為 {px_len:.1f} px\n"
                  f"請輸入它的實際長度（單位：{unit}）\n\n"
                  f"This line is {px_len:.1f} px long.\n"
                  f"Enter its real-world length ({unit}):",
             font=("Arial", 12), bg="#2B2B2B", fg="#E0E0E0", justify="left").pack(padx=16, pady=(14, 6))

    length_var = tk.StringVar()
    ent = ttk.Entry(dlg, textvariable=length_var, font=ENTRY_FONT, width=14)
    ent.pack(padx=16, pady=6)
    ent.focus_set()

    msg_lbl = tk.Label(dlg, text="", font=("Arial", 10), bg="#2B2B2B", fg="#FF4444")
    msg_lbl.pack(padx=16)

    def confirm():
        global scale_pixels_per_unit, scale_unit, scale_mode, scale_drawing
        try:
            real_len = float(length_var.get().strip())
            if real_len <= 0:
                raise ValueError
        except ValueError:
            msg_lbl.config(text="請輸入大於 0 的數字。\nEnter a number > 0.")
            return

        scale_pixels_per_unit = px_len / real_len
        scale_unit            = unit
        scale_mode            = False
        scale_drawing         = False
        scale_draw_btn.config(text="畫比例線 / Draw Scale Line")

        fov_w = disp_w / scale_pixels_per_unit
        fov_h = disp_h / scale_pixels_per_unit

        px_size_orig_w = fov_w / orig_w if orig_w > 0 else 0.0
        px_size_orig_h = fov_h / orig_h if orig_h > 0 else 0.0

        scale_status_label.config(
            text=(
                f"已設定：{real_len} {unit} = {px_len:.1f} px\n"
                f"解析度：{scale_pixels_per_unit:.3f} px/{unit}\n"
                f"─────────────────────\n"
                f"實際視野 / FOV\n"
                f"  {fov_w:.3f} x {fov_h:.3f} {unit}\n"
                f"相機解析度 / Camera res\n"
                f"  {orig_w} x {orig_h} px\n"
                f"單像素尺寸 / Pixel size\n"
                f"  {px_size_orig_w:.4f} x {px_size_orig_h:.4f} {unit}/px"
            ),
            fg="#00FF7F")
        dlg.destroy()

    ttk.Button(dlg, text="確認 / Confirm", command=confirm).pack(pady=(6, 14))
    dlg.bind("<Return>", lambda e: confirm())
    root.wait_window(dlg)


scale_draw_btn.config(command=toggle_scale_mode)
scale_clear_btn.config(command=clear_scale)


# ── 門檻預覽框邏輯 ─────────────────────────────────────────────────────────────

def toggle_preview_mode():
    global preview_mode, preview_drawing
    if preview_mode:
        preview_mode    = False
        preview_drawing = False
        preview_set_btn.config(text="設置預覽框 / Set Block")
        preview_status_label.config(text="已取消 / Cancelled", fg="#888888")
    else:
        preview_mode = True
        preview_set_btn.config(text="取消設置 / Cancel")
        preview_status_label.config(
            text="請在影像上拖曳畫出預覽框。\nDrag on image to draw preview box.",
            fg="#FFD700")

def clear_preview_block():
    global preview_block, preview_mode, preview_drawing
    preview_block   = None
    preview_mode    = False
    preview_drawing = False
    preview_set_btn.config(text="設置預覽框 / Set Block")
    preview_status_label.config(text="尚未設置 / Not set", fg="#888888")

preview_set_btn.config(command=toggle_preview_mode)
preview_clear_btn.config(command=clear_preview_block)


# ── 滑鼠事件 ──────────────────────────────────────────────────────────────────

def on_mouse_down(event):
    global start_x, start_y, dragging, roi_dragging_offset_x, roi_dragging_offset_y
    global roi_fixed_width, roi_fixed_height, roi_fixed_diameter
    global scale_drawing, scale_line_disp
    global preview_drawing, preview_start_x, preview_start_y, preview_block
    global level_drawing, level_start_x, level_start_y, level_block

    if level_mode:
        level_drawing = True
        lx, ly = evt_to_img(event.x, event.y)
        level_start_x = lx; level_start_y = ly
        level_block = (lx, ly, lx, ly)
        return

    # ── 比例尺模式攔截 ──────────────────────────────────────────────────────────
    if scale_mode:
        scale_drawing   = True
        scale_line_disp = (event.x, event.y, event.x, event.y)
        return

    # ── 預覽框模式攔截 ──────────────────────────────────────────────────────────
    if preview_mode:
        preview_drawing  = True
        px, py = evt_to_img(event.x, event.y)
        preview_start_x  = px
        preview_start_y  = py
        preview_block    = (px, py, px, py)
        return

    if (not analyzing) and (not roi_locked) and (not roi_fixed):
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
    global scale_line_disp, preview_block
    global level_block

    if level_mode and level_drawing and level_block is not None:
        mx, my = evt_to_img(event.x, event.y)
        level_block = (level_start_x, level_start_y, mx, my)
        return

    if scale_mode and scale_drawing and scale_line_disp is not None:
        scale_line_disp = (scale_line_disp[0], scale_line_disp[1], event.x, event.y)
        return

    if preview_mode and preview_drawing and preview_block is not None:
        mx, my = evt_to_img(event.x, event.y)
        preview_block = (preview_start_x, preview_start_y, mx, my)
        return

    if dragging:
        roi_dragging_offset_x = event.x - start_x
        roi_dragging_offset_y = event.y - start_y

def on_mouse_up(event):
    global roi_selected, dragging, roi_fixed_width, roi_fixed_height, roi_fixed_diameter
    global scale_drawing, scale_line_disp
    global preview_drawing, preview_mode, preview_block
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

    if scale_mode and scale_drawing and scale_line_disp is not None:
        scale_drawing   = False
        x1, y1, _, _   = scale_line_disp
        scale_line_disp = (x1, y1, event.x, event.y)
        finish_scale_line(x1, y1, event.x, event.y)
        return

    # ── 預覽框拖曳結束 ──────────────────────────────────────────────────────────
    if preview_mode and preview_drawing:
        preview_drawing = False
        mx, my = evt_to_img(event.x, event.y)
        x1 = min(preview_start_x, mx);  x2 = max(preview_start_x, mx)
        y1 = min(preview_start_y, my);  y2 = max(preview_start_y, my)
        x1 = max(img_pad_x, x1);        y1 = max(img_pad_y, y1)
        x2 = min(img_pad_x + img_disp_w, x2)
        y2 = min(img_pad_y + img_disp_h, y2)
        if x2 - x1 >= 5 and y2 - y1 >= 5:
            preview_block = (x1, y1, x2, y2)
            preview_mode  = False
            preview_set_btn.config(text="設置預覽框 / Set Block")
            preview_status_label.config(
                text=f"已設置：{x2-x1} x {y2-y1} px\nSet: {x2-x1} x {y2-y1} px",
                fg="#00FF7F")
        else:
            preview_block = None
            preview_status_label.config(text="框太小，請重畫。\nBox too small.", fg="#FF4444")
            preview_mode = False
            preview_set_btn.config(text="設置預覽框 / Set Block")
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

    if _fixed_blocked():
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
    if (not analyzing) and (not roi_locked) and (not roi_fixed) and len(rois) > 0:
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

def save_roi_layout(silent=False, path=None):
    """存目前 ROI(形狀+座標+大小)與座標空間資訊,成功回傳 True。
    path 指定時直接存該檔;silent=True:開始量測時自動存成 ROI_last.json;否則讓使用者自訂檔名。"""
    if not rois:
        if not silent:
            messagebox.showwarning("無 ROI / No ROI", "目前沒有 ROI 可存。\nNo ROI to save.")
        return False
    try:
        os.makedirs(ROI_DIR, exist_ok=True)
    except Exception:
        pass
    if path:
        pass
    elif silent:
        path = os.path.join(ROI_DIR, ROI_LAST)
    else:
        path = filedialog.asksaveasfilename(
            title="儲存 ROI 座標 / Save ROI layout", initialdir=ROI_DIR,
            initialfile=f"ROI_{datetime.datetime.now():%Y%m%d_%H%M%S}.json",
            defaultextension=".json", filetypes=ROI_TYPES)
        if not path:
            return False
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
        return False
    if not silent:
        messagebox.showinfo("已存 ROI / ROI saved",
                            f"{len(rois)} 個 ROI 已存到:\n{os.path.normpath(path)}")
    return True


def _read_roi_file(path):
    """讀 ROI 座標檔 → (ROI 清單, 檔案資料);讀取失敗、沒有 ROI、或座標空間不符且使用者取消,回傳 (None, None)。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        messagebox.showerror("讀取失敗 / Load failed", f"{os.path.basename(path)}\n{e}")
        return None, None

    loaded = data.get("rois", [])
    if not loaded:
        messagebox.showwarning("無 ROI / Empty", f"{os.path.basename(path)} 內沒有 ROI。")
        return None, None

    warn = ""
    if (data.get("img_disp_w"), data.get("img_disp_h"),
        data.get("img_pad_x"), data.get("img_pad_y")) != \
       (img_disp_w, img_disp_h, img_pad_x, img_pad_y):
        warn += "\n- 影像顯示範圍與存檔時不同(相機/解析度可能不同),ROI 位置可能偏移。"
    if data.get("camera_type") and data.get("camera_type") != CAMERA_TYPE:
        warn += f"\n- 相機不同(存檔:{data.get('camera_type')} / 目前:{CAMERA_TYPE})。"
    if warn and not messagebox.askokcancel("座標空間不符 / Mismatch",
                                           f"{os.path.basename(path)}\n座標空間與存檔時不同,仍要載入嗎?" + warn):
        return None, None
    return [(r[0], *[int(round(float(v))) for v in r[1:]]) for r in loaded], data


def _set_rois(new_rois):
    global roi_selected
    rois.clear(); rois.extend(new_rois)
    roi_selected = len(rois) > 0
    validate_start_enable()


def load_roi_layout():
    """讓使用者從之前存的 ROI 座標檔中挑一份載入;座標空間不符時先警告再決定是否套用。"""
    if roi_locked or analyzing:
        messagebox.showinfo("ROI 已鎖定 / Locked",
                            "執行中無法載入,請先 Restart。\nCannot load while running.")
        return
    if _fixed_blocked():
        return
    path = filedialog.askopenfilename(
        title="選擇 ROI 座標檔 / Choose ROI layout",
        initialdir=ROI_DIR if os.path.isdir(ROI_DIR) else APP_DIR,
        filetypes=ROI_TYPES)
    if not path:
        return
    new_rois, data = _read_roi_file(path)
    if new_rois is None:
        return
    _set_rois(new_rois)
    messagebox.showinfo("已載入 ROI / ROI loaded",
                        f"{os.path.basename(path)}\n"
                        f"載入 {len(rois)} 個 ROI（存檔時間 {data.get('saved_at','?')}）。")


# ── 固定 ROI(樣本座標固定)────────────────────────────────────────────────────
ROI_FIXED = "ROI_fixed.json"        # 固定 ROI 檔:開程式自動載入並鎖定
roi_fixed = False                   # True:ROI 位置與大小鎖定,不能新增 / 移動 / 清除 / 換檔


def _fixed_blocked():
    """固定 ROI 鎖定中就提示並回傳 True(呼叫端應中止)。"""
    if roi_fixed:
        messagebox.showinfo("ROI 已固定 / Fixed ROI",
                            "目前使用固定 ROI,位置與大小已鎖定。\n"
                            "要調整請先取消勾選「固定 ROI」。\n"
                            "Fixed ROI is locked; uncheck 'Fixed ROI' to edit.")
    return roi_fixed


def _set_fixed_lock(on, info=""):
    """切換固定 ROI 鎖定狀態並同步 UI。"""
    global roi_fixed
    roi_fixed = bool(on)
    roi_fixed_var.set(roi_fixed)
    state = "disabled" if roi_fixed else "normal"
    for w in (auto_roi_btn, roi_load_btn):
        w.config(state=state)
    if roi_fixed:
        roi_fixed_status.config(text=f"已固定 {len(rois)} 個 ROI(黃框){info}", fg="#FFD700")
    else:
        roi_fixed_status.config(text="未固定:可新增 / 拖曳 / 自動放置 ROI / Not fixed", fg="#888888")


def load_fixed_roi(silent=False):
    """載入 ROI_fixed.json 並鎖定;成功回傳 True。"""
    path = os.path.join(ROI_DIR, ROI_FIXED)
    if not os.path.exists(path):
        if not silent:
            messagebox.showinfo("尚未設定固定 ROI / No fixed ROI",
                                "還沒有固定 ROI。請先擺好 ROI,再按「設為固定 ROI」。\n"
                                "No fixed ROI yet: place ROIs, then press 'Set current as fixed'.")
        return False
    new_rois, data = _read_roi_file(path)
    if new_rois is None:
        return False
    _set_rois(new_rois)
    _set_fixed_lock(True, f"\n{data.get('saved_at', '?')} 設定")
    return True


def set_fixed_roi():
    """把目前的 ROI 存成固定 ROI 並鎖定。"""
    if roi_locked or analyzing:
        messagebox.showinfo("量測中 / Running", "量測中無法變更固定 ROI。\nCannot change while running.")
        return
    if not rois:
        messagebox.showwarning("無 ROI / No ROI", "請先擺好 ROI。\nPlace ROIs first.")
        return
    path = os.path.join(ROI_DIR, ROI_FIXED)
    if not messagebox.askokcancel(
            "設為固定 ROI / Set fixed ROI",
            f"將目前 {len(rois)} 個 ROI 設為固定座標(位置與大小鎖定)。\n"
            f"之後開程式會自動載入。\n\n存檔:{os.path.normpath(path)}"
            + ("\n\n(會覆蓋原本的固定 ROI)" if os.path.exists(path) else "")):
        return
    if save_roi_layout(silent=True, path=path):
        _set_fixed_lock(True, f"\n{datetime.datetime.now():%Y-%m-%d %H:%M:%S} 設定")
    else:
        messagebox.showerror("存檔失敗 / Save failed", f"無法寫入 {path}")


def toggle_fixed_roi():
    """勾選 → 載入固定 ROI 並鎖定;取消勾選 → 解鎖可調整(ROI 保留)。"""
    if roi_locked or analyzing:
        roi_fixed_var.set(roi_fixed)                 # 量測中不允許切換,還原勾選狀態
        messagebox.showinfo("量測中 / Running", "量測中無法切換固定 ROI。\nCannot change while running.")
        return
    if roi_fixed_var.get():
        if not load_fixed_roi():
            roi_fixed_var.set(False)
    else:
        _set_fixed_lock(False)


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
    scale_info = (f"Scale: {scale_pixels_per_unit:.4f} px/{scale_unit}"
                  if scale_pixels_per_unit is not None else "Scale: Not set")
    mf_info = (f"Median filter: ON (kernel={MEDIAN_KERNEL})"
               if median_filter_enabled else "Median filter: OFF")
    mf_info += ("  |  De-glint: ON (K=%.1f)" % DEGLINT_K) if deglint_enabled else "  |  De-glint: OFF"

    blank  = [""] * len(data)
    header = ["Time (s)"] + sample_cols
    stat_rows = [
        [mf_info]    + blank,
        [scale_info] + blank,
        [illum_info or "Illumination correction: OFF"] + blank,
    ] + ([["Illum gain (per ROI)"] + [round(f, 4) for f in illum_factors]] if illum_factors else []) + [
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

        # FPS 對靜態圖片無實質意義，但流程需要 → 預填 30
        if not fps_input_entry.get().strip():
            fps_input_entry.insert(0, "30")

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
        global running, analyzing, cam, CAMERA_TYPE, median_preview_win
        running   = False
        analyzing = False

        if median_preview_win is not None:
            try:
                median_preview_win.destroy()
            except Exception:
                pass
            median_preview_win = None

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

        if scale_pixels_per_unit is not None:
            fov_w = disp_w / scale_pixels_per_unit
            fov_h = disp_h / scale_pixels_per_unit
            cam_res = f"{orig_w}x{orig_h}" if orig_w > 0 else "?"
            fov_lines = [
                f"Camera: {cam_res} px  |  FOV: {fov_w:.2f} x {fov_h:.2f} {scale_unit}",
                f"Pixel size: {fov_w/orig_w:.4f} x {fov_h/orig_h:.4f} {scale_unit}/px" if orig_w > 0 else "",
            ]
            fy = 22
            for fline in fov_lines:
                if not fline:
                    continue
                fsz = cv2.getTextSize(fline, cv2.FONT_HERSHEY_SIMPLEX, 0.60, 2)[0]
                cv2.rectangle(display_frame, (6, fy - fsz[1] - 4), (10 + fsz[0] + 4, fy + 4), (0, 0, 0), -1)
                cv2.putText(display_frame, fline, (10, fy), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (0, 220, 255), 2)
                fy += fsz[1] + 12

        show_glint = deglint_enabled and deglint_show_removed
        roi_color  = (255, 215, 0) if roi_fixed else (255, 255, 255)   # 固定 ROI = 黃框
        for i, r in enumerate(rois):
            if not r:
                continue
            if r[0] == 'rect':
                _, x1, y1, x2, y2 = r
                _gp = _deglint_overlay(display_frame, gray, r) if show_glint else None
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), roi_color, 2)

                if scale_pixels_per_unit is not None:
                    w_real = (x2 - x1) / scale_pixels_per_unit
                    h_real = (y2 - y1) / scale_pixels_per_unit
                    txt = f"S{i+1}  {w_real:.2f}x{h_real:.2f} {scale_unit}"
                else:
                    txt = f"Sample {i+1}  ({x2-x1}x{y2-y1} px)"
                if _gp is not None:
                    txt += f"  glint {_gp:.1f}%"
                if illum_gain is not None and i < len(illum_factors):
                    txt += f"  x{illum_factors[i]:.2f}"

                tsz  = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                tx, ty = x1, max(20, y1 - 15)
                cv2.rectangle(display_frame, (tx-5, ty-tsz[1]-5), (tx+tsz[0]+5, ty+5), (0, 0, 0), -1)
                cv2.putText(display_frame, txt, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            elif r[0] == 'circle':
                _, cx, cy, rad = r
                _gp = _deglint_overlay(display_frame, gray, r) if show_glint else None
                cv2.circle(display_frame, (int(cx), int(cy)), int(rad), roi_color, 2)

                if scale_pixels_per_unit is not None:
                    d_real = (rad * 2) / scale_pixels_per_unit
                    txt = f"S{i+1}  Dia {d_real:.2f} {scale_unit}"
                else:
                    txt = f"Sample {i+1}  (Dia {rad*2} px)"
                if _gp is not None:
                    txt += f"  glint {_gp:.1f}%"
                if illum_gain is not None and i < len(illum_factors):
                    txt += f"  x{illum_factors[i]:.2f}"

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
                    if scale_pixels_per_unit is not None:
                        wr = roi_fixed_width  / scale_pixels_per_unit
                        hr = roi_fixed_height / scale_pixels_per_unit
                        stxt = f"{roi_fixed_width}x{roi_fixed_height}px  ({wr:.2f}x{hr:.2f} {scale_unit})"
                    else:
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
                    if scale_pixels_per_unit is not None:
                        dr = roi_fixed_diameter / scale_pixels_per_unit
                        stxt = f"Dia {roi_fixed_diameter}px  ({dr:.2f} {scale_unit})"
                    else:
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

        if scale_line_disp is not None:
            sx1, sy1, sx2, sy2 = [int(v) for v in scale_line_disp]
            bar_color = (0, 220, 255)

            cv2.line(display_frame, (sx1, sy1), (sx2, sy2), bar_color, 2)

            angle = np.arctan2(sy2 - sy1, sx2 - sx1)
            perp  = angle + np.pi / 2
            tick  = 8
            for px, py in [(sx1, sy1), (sx2, sy2)]:
                tx1_ = int(px + tick * np.cos(perp))
                ty1_ = int(py + tick * np.sin(perp))
                tx2_ = int(px - tick * np.cos(perp))
                ty2_ = int(py - tick * np.sin(perp))
                cv2.line(display_frame, (tx1_, ty1_), (tx2_, ty2_), bar_color, 2)

            if scale_pixels_per_unit is not None:
                px_len_bar = ((sx2 - sx1)**2 + (sy2 - sy1)**2) ** 0.5
                real_len   = px_len_bar / scale_pixels_per_unit
                bar_txt    = f"{real_len:.2f} {scale_unit}"
            else:
                px_len_bar = ((sx2 - sx1)**2 + (sy2 - sy1)**2) ** 0.5
                bar_txt    = f"{px_len_bar:.0f} px  (setting...)"

            ssz = cv2.getTextSize(bar_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)[0]
            mx  = (sx1 + sx2) // 2 - ssz[0] // 2
            my  = min(sy1, sy2) - 12
            my  = max(my, 16)
            cv2.rectangle(display_frame, (mx - 4, my - ssz[1] - 4), (mx + ssz[0] + 4, my + 4), (0, 0, 0), -1)
            cv2.putText(display_frame, bar_txt, (mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.65, bar_color, 2)

        # ── 預覽框：標紅高於門檻的像素 ────────────────────────────────────────────
        if preview_block is not None:
            try:
                px1, py1, px2, py2 = [int(v) for v in preview_block]
                # 拖曳中要正規化座標
                bx1 = max(img_pad_x, min(px1, px2)); bx2 = min(img_pad_x + img_disp_w, max(px1, px2))
                by1 = max(img_pad_y, min(py1, py2)); by2 = min(img_pad_y + img_disp_h, max(py1, py2))
                if bx2 > bx1 and by2 > by1:
                    thr_val = preview_threshold_var.get()
                    # 取出該區塊灰階
                    region_gray = gray[by1:by2, bx1:bx2]
                    # 建立遮罩：灰階值 > thr_val → 標紅
                    red_mask = region_gray > thr_val
                    region_rgb = display_frame[by1:by2, bx1:bx2].copy()
                    region_rgb[red_mask] = [220, 30, 30]
                    display_frame[by1:by2, bx1:bx2] = region_rgb

                    # 紅色邊框
                    cv2.rectangle(display_frame, (bx1, by1), (bx2, by2), (220, 30, 30), 2)

                    # 標籤：顯示當前門檻值與紅點比例
                    red_ratio = red_mask.sum() / red_mask.size * 100 if red_mask.size > 0 else 0.0
                    ptxt = f"Preview thr>{thr_val}  red:{red_ratio:.1f}%"
                    psz  = cv2.getTextSize(ptxt, cv2.FONT_HERSHEY_SIMPLEX, 0.60, 2)[0]
                    ptx  = bx1
                    pty  = max(16, by1 - 8)
                    cv2.rectangle(display_frame, (ptx - 2, pty - psz[1] - 4),
                                  (ptx + psz[0] + 4, pty + 4), (0, 0, 0), -1)
                    cv2.putText(display_frame, ptxt, (ptx, pty),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.60, (220, 30, 30), 2)
            except Exception:
                pass

        # ── 預覽框拖曳中的即時預覽外框 ────────────────────────────────────────────
        if preview_mode and preview_drawing and preview_block is not None:
            try:
                dx1, dy1, dx2, dy2 = [int(v) for v in preview_block]
                cv2.rectangle(display_frame, (min(dx1,dx2), min(dy1,dy2)),
                              (max(dx1,dx2), max(dy1,dy2)), (220, 30, 30), 1)
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

    fps_display_label.config(text=f"Current FPS : {int(fps_value)}")
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
    global current_frame, valid_frame_count, last_sec_time, fps_value, xi_img, cam

    try:
        from ximea import xiapi
    except Exception:
        return

    xi_img = xiapi.Image()
    next_due = time.monotonic()
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

        now_sec = int(time.time())
        if now_sec != last_sec_time:
            fps_value         = valid_frame_count
            valid_frame_count = 0
            last_sec_time     = now_sec

        if user_fps_val is not None:
            now = time.monotonic()
            if now < next_due:
                continue
            next_due = max(now, next_due + 1.0 / float(user_fps_val))

        if frame.dtype != np.uint8:
            try:    frame = frame.astype(np.uint8)
            except Exception: frame = np.clip(frame, 0, 255).astype(np.uint8)

        if not _publish_frame(frame):
            continue
        valid_frame_count += 1

def video_loop_thorlabs():
    global current_frame, valid_frame_count, last_sec_time, fps_value, cam, bit_depth

    next_due = time.monotonic()
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

        now_sec = int(time.time())
        if now_sec != last_sec_time:
            fps_value         = valid_frame_count
            valid_frame_count = 0
            last_sec_time     = now_sec

        if user_fps_val is not None:
            now = time.monotonic()
            if now < next_due:
                continue
            next_due = max(now, next_due + 1.0 / float(user_fps_val))

        if frame.ndim == 3 and frame.shape[2] == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if not _publish_frame(frame):
            continue
        valid_frame_count += 1


def video_loop_image():
    """匯入圖片模式：持續把靜態影像餵進 current_frame，
    讓所有既有的 ROI/threshold/median/分析邏輯不需改動即可運作。"""
    global current_frame, valid_frame_count, last_sec_time, fps_value

    while running:
        if image_frame_cache is None:
            time.sleep(0.05)
            continue

        now_sec = int(time.time())
        if now_sec != last_sec_time:
            fps_value         = valid_frame_count
            valid_frame_count = 0
            last_sec_time     = now_sec

        if _publish_frame(source_image_gray if source_image_gray is not None else image_frame_cache):
            valid_frame_count += 1
        time.sleep(0.03)   # 靜態影像不需高更新率，約 30fps 顯示即可


# ── 分析迴圈 ──────────────────────────────────────────────────────────────────

def analysis_loop():
    global roi_data, timestamps, threshold_value, decimal_places

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

        for i, r in enumerate(rois):
            patch, cmask = get_roi_patch(frame, r)
            gsub = _roi_glint(frame, r, cmask) if deglint_enabled else None   # 只對此 ROI 去反光
            gnsub = None
            if illum_gain is not None:
                ly1, ly2, lx1, lx2 = _roi_slice(frame.shape, r)
                gnsub = illum_gain[ly1:ly2, lx1:lx2]
            avg_val, changed_ratio = compute_roi_mean(patch, cmask, gsub, gnsub)
            buffer_vals[i].append(avg_val)

            while len(median_last_ratio) <= i:
                median_last_ratio.append(0.0)
            median_last_ratio[i] = changed_ratio

        if elapsed > last_logged_sec:
            log_message = ""
            for i in range(len(rois)):
                avg_sec = np.mean(buffer_vals[i]) if buffer_vals[i] else 0.0
                rounded = round(float(avg_sec), decimal_places) if decimal_places is not None else float(avg_sec)
                roi_data[i].append(rounded)
                buffer_vals[i] = []

                roi_size_str = ""
                if scale_pixels_per_unit is not None:
                    r = rois[i]
                    if r[0] == 'rect':
                        _, rx1, ry1, rx2, ry2 = r
                        wr = (rx2 - rx1) / scale_pixels_per_unit
                        hr = (ry2 - ry1) / scale_pixels_per_unit
                        roi_size_str = f"  [{wr:.2f}x{hr:.2f} {scale_unit}]"
                    elif r[0] == 'circle':
                        _, rcx, rcy, rrad = r
                        dr = (rrad * 2) / scale_pixels_per_unit
                        roi_size_str = f"  [Dia {dr:.2f} {scale_unit}]"

                mf_str = ""
                if median_filter_enabled and i < len(median_last_ratio):
                    mf_str = f"  (median fixed {median_last_ratio[i]:.2f}%)"

                log_message += f"At {elapsed} sec, Sample {i+1}{roi_size_str} = {rounded}{mf_str}\n"
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

    load_fixed_roi(silent=True)        # 有 ROI_fixed.json 就自動載入並鎖定
    load_flat_field(silent=True)       # 有 calibration/flat_field.npz 就載入(座標空間相符才用)
    _set_fixed_lock(roi_fixed)
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