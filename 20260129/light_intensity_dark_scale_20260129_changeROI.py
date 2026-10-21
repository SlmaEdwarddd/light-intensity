import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import threading
import time
import datetime
import pandas as pd
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
start_x = start_y = end_x = end_y = 0
dragging = False
right_dragging = False          # 右鍵拖動狀態
right_drag_roi_index = -1       # 正在拖動的ROI索引
right_drag_start_x = 0          # 右鍵拖動起始的鼠標X位置
right_drag_start_y = 0          # 右鍵拖動起始的鼠標Y位置
right_drag_roi_start_pos = None # 右鍵拖動起始的ROI位置
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

# 比例尺與距離標記設置
pixel_size_um = None  # 相機像素大小（微米/像素）
show_scale_bar = False  # 是否顯示比例尺
scale_bar_length_um = 50  # 比例尺長度（微米）
show_distance_label = False  # 是否顯示距離標籤
lens_magnification = 1.0  # 透鏡倍率（預設1x，無透鏡）

CAMERA_TYPE = None
cam = None
xi_img = None
bit_depth = 8
orig_w = orig_h = 0

# 固定顯示大小為 1280x920
disp_w, disp_h = 1280, 920

user_gain_val = 0.0
user_exposure_ms = 10.0  # milliseconds
gain_locked = False
exposure_locked = False

roi_shape_choice = 'rect'   # 'rect' or 'circle'
decimal_places = None       
decimal_locked = False
settings_applied = False

# ROI 固定大小設置（用於固定大小模式）
roi_fixed_width = 50       # 矩形寬度（像素）
roi_fixed_height = 50      # 矩形高度（像素）
roi_fixed_diameter = 50    # 圓形直徑（像素）
roi_dragging_offset_x = 0  # 拖動時的X偏移量
roi_dragging_offset_y = 0  # 拖動時的Y偏移量

# 文字區自動追蹤開關：True = 隨新資料自動捲到底；False = 使用者已手動滾動，暫停自動追蹤
text_follow = True

# Tkinter UI 初始化
# 創建主視窗
root = tk.Tk()
# 給視窗取名字
root.title("光強度偵測 / Light Intensity Detection")
# 設定視窗背景顏色 #1E1E1E是深灰色
root['bg'] = '#1E1E1E'
# 建立一個 Tkinter 變數來儲存「降採樣」的設定值，預設為 '2x2'。這通常用於後續選單或按鈕的狀態串接。
downsampling_var = tk.StringVar(value='2x2')  # '1x1' 或 '2x2'


# 右側設定字體、間距設定 ex Times New Roman, 18號, 加粗
SETTINGS_LABEL_FONT = ("times new roman", 18, "bold")
SETTINGS_TYPE_FONT = ("times new roman", 12, "bold")
SETTINGS_ITEM_FONT = ("times new roman", 12)
ENTRY_FONT = ("times new roman", 12)
RADIO_FONT = ("times new roman", 12)
FRAME_PADX = 8
FRAME_PADY = 6

# 這部分根據內容大小來動態計算視窗應該多大。
## 定義右側設定面板的寬度。
right_w = 420

## 總寬度 = 顯示區域寬度 (disp_w) + 右側面板寬度。
main_w = disp_w + right_w

## 總高度 = 顯示區域高度 (disp_h) + 80 像素的額外空間（可能是為了按鈕或其他 UI 元素）。
main_h = disp_h + 80

# 套用計算好的寬高設定。
root.geometry(f"{main_w}x{main_h}")
# 不可調整長寬
root.resizable(False, False)

# 在 root 視窗中建立一個「大框框」（Frame），作為所有元件的母體容器。
main_frame = tk.Frame(root, bg=root['bg'])
# 將這個框架填滿整個視窗並允許隨視窗縮放。
main_frame.pack(fill='both', expand=True)

# 左側：影像 + 三按鈕
left_frame = tk.Frame(main_frame, bg='#1E1E1E', width=disp_w, height=disp_h+80)
# 框架靠左對齊。
left_frame.pack(side="left", fill="y")
# 「不要自動縮放」
left_frame.pack_propagate(False)


# video_label = tk.Label(...)：這是一個標籤元件，但在影像處理程式中，
# 它通常被當作「畫布」使用，用來放每一幀（Frame）的監視畫面。
video_label = tk.Label(left_frame, width=disp_w, height=disp_h, bg="black")
video_label.pack()

control_frame = tk.Frame(left_frame, bg='#1E1E1E')
control_frame.pack(pady=5, fill="x")

# 自訂按鈕樣式
# 切換到 "alt" 主題，這是自定義樣式的基礎。
style = ttk.Style()
try:
    style.theme_use("alt")
except Exception:
    pass

style.configure("Custom.TButton", font=("Arial", 15), padding=5, relief="flat", background="#0078D4", foreground="white")
style.map("Custom.TButton", foreground=[("active", "white"), ("!disabled", "white")], background=[("active", "#107C10"), ("!disabled", "#0078D4")])
style.configure("Apply.TButton", font=("Arial", 12), padding=2, relief="flat", background="#0078D4", foreground="white")
style.map("Apply.TButton", foreground=[("active", "white"), ("!disabled", "white")], background=[("active", "#107C10"), ("!disabled", "#0078D4")])


# control_frame 橫向排列三個按鈕：
# default_btn	重新選取 ROI	正常狀態
default_btn = ttk.Button(control_frame, text="重新選取 ROI / Reselect ROI", style="Custom.TButton")
default_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")
# start_btn	開始 / Start	disabled (禁用)	灰底無法點擊，通常等選好範圍後才啟動
start_btn = ttk.Button(control_frame, text="開始 / Start", style="Custom.TButton", state="disabled")
start_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")
# save_btn	儲存 CSV / Save as CSV	正常狀態
save_btn = ttk.Button(control_frame, text="儲存 CSV / Save as CSV", style="Custom.TButton")
save_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")

# 右側：設定區
right_frame = tk.Frame(main_frame, bg="#2B2B2B", width=right_w, height=disp_h+80)
right_frame.pack(side="right", fill="both")
right_frame.pack_propagate(False)

settings_label = tk.Label(right_frame, text="設定 / Settings", font=SETTINGS_LABEL_FONT, bg="#2B2B2B", fg="#00BFFF")
#上方留白8像素，下方留白4像素
settings_label.pack(pady=(8,4))

# Gain & Exposure
ge_frame = tk.LabelFrame(right_frame, text="相機設定 / Camera Settings", padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
ge_frame.pack(fill='both', padx=6, pady=4, expand=True)

gain_label = tk.Label(ge_frame, text="Gain :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
gain_label.grid(row=0, column=0, sticky='w', padx=2, pady=6)
gain_entry = ttk.Entry(ge_frame, width=12, font=ENTRY_FONT)
gain_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
gain_entry.insert(0, str(user_gain_val))

exp_label = tk.Label(ge_frame, text="Exposure(ms) :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
exp_label.grid(row=1, column=0, sticky='w', padx=2, pady=6)
exposure_entry = ttk.Entry(ge_frame, width=12, font=ENTRY_FONT)
exposure_entry.grid(row=1, column=1, sticky='w', padx=2, pady=6)
exposure_entry.insert(0, str(user_exposure_ms))


# Downsampling
down_frame = tk.LabelFrame(right_frame, text="XIMEA Downsampling (Only for XIMEA)", padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
down_frame.pack(fill='both', padx=6, pady=4, expand=True)

rb1 = ttk.Radiobutton(down_frame, text="1x1 (2464x2056)", variable=downsampling_var, value='1x1')
rb2 = ttk.Radiobutton(down_frame, text="2x2 (1232x1028)", variable=downsampling_var, value='2x2')

rb1 = tk.Radiobutton(down_frame, text="1x1 (2464x2056)", variable=downsampling_var, value='1x1', font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb2 = tk.Radiobutton(down_frame, text="2x2 (1232x1028)", variable=downsampling_var, value='2x2', font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb1.pack(anchor='w', padx=6, pady=(2,4), fill='x')
rb2.pack(anchor='w', padx=6, pady=(2,4), fill='x')

try:
    rb1.config(state="disabled")
    rb2.config(state="disabled")
except Exception:
    pass

# ROI shape selection
roi_frame = tk.LabelFrame(right_frame, text="ROI 形狀 / ROI Shape", padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
roi_frame.pack(fill='both', padx=6, pady=4, expand=True)

roi_shape_var = tk.StringVar(value='rect')
rb_rect_ui = ttk.Radiobutton(roi_frame, text="Rectangle", variable=roi_shape_var, value='rect', command=lambda: set_roi_shape('rect'))
rb_circle_ui = ttk.Radiobutton(roi_frame, text="Circle", variable=roi_shape_var, value='circle', command=lambda: set_roi_shape('circle'))

rb_rect_ui = tk.Radiobutton(roi_frame, text="Rectangle", variable=roi_shape_var, value='rect', command=lambda: set_roi_shape('rect'), font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb_circle_ui = tk.Radiobutton(roi_frame, text="Circle", variable=roi_shape_var, value='circle', command=lambda: set_roi_shape('circle'), font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb_rect_ui.pack(anchor='w', padx=6, pady=(2,4), fill='x')
rb_circle_ui.pack(anchor='w', padx=6, pady=(2,4), fill='x')

# ROI Size settings
roi_size_frame = tk.Frame(roi_frame, bg="#2B2B2B")
roi_size_frame.pack(fill='x', padx=6, pady=(6,2))

roi_size_label1 = tk.Label(roi_size_frame, text="Width (px):", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
roi_size_label1.grid(row=0, column=0, sticky='w', padx=2, pady=4)
roi_width_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_width_entry.insert(0, "50")
roi_width_entry.grid(row=0, column=1, sticky='w', padx=2, pady=4)

roi_size_label2 = tk.Label(roi_size_frame, text="Height (px):", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
roi_size_label2.grid(row=1, column=0, sticky='w', padx=2, pady=4)
roi_height_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_height_entry.insert(0, "50")
roi_height_entry.grid(row=1, column=1, sticky='w', padx=2, pady=4)

roi_size_label3 = tk.Label(roi_size_frame, text="Diameter (px):", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
roi_size_label3.grid(row=2, column=0, sticky='w', padx=2, pady=4)
roi_diameter_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_diameter_entry.insert(0, "50")
roi_diameter_entry.grid(row=2, column=1, sticky='w', padx=2, pady=4)

roi_size_note = tk.Label(roi_size_frame, text="(設定後用滑鼠拖動放置ROI)\n(Set size, then drag to place ROI)", font=("times new roman", 9), bg="#2B2B2B", fg="#888888")
roi_size_note.grid(row=3, column=0, columnspan=2, sticky='w', padx=2, pady=(4,0))

# Threshold
thr_frame = tk.LabelFrame(right_frame, text="門檻 / Threshold", padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
thr_frame.pack(fill='both', padx=6, pady=4, expand=True)
threshold_label = tk.Label(thr_frame, text="Threshold（0-255）:", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
threshold_label.grid(row=0, column=0, sticky='w', padx=2, pady=6)
threshold_entry = ttk.Entry(thr_frame, width=14, font=ENTRY_FONT)
threshold_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)

# FPS settings
fps_frame = tk.LabelFrame(right_frame, text="FPS 控制 / FPS Control", padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
fps_frame.pack(fill='both', padx=6, pady=4, expand=True)
fps_input_label = tk.Label(fps_frame, text="Set FPS(integer) :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
fps_input_label.grid(row=0, column=0, sticky='w', padx=2, pady=6)
fps_input_entry = ttk.Entry(fps_frame, width=10, font=ENTRY_FONT)
fps_input_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
fps_display_label = tk.Label(fps_frame, text="Current FPS: 0", anchor="w", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#00BFFF")
fps_display_label.grid(row=1, column=0, columnspan=2, sticky='w', padx=2, pady=(6,2))

# Decimal places
dec_frame = tk.LabelFrame(right_frame, text="顯示精度 / Display Precision", padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
dec_frame.pack(fill='both', padx=6, pady=4, expand=True)
dec_label = tk.Label(dec_frame, text="Decimal places :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
dec_label.grid(row=0, column=0, sticky='w', padx=2, pady=6)
dec_entry = ttk.Entry(dec_frame, width=6, font=ENTRY_FONT)
dec_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)

# 比例尺設置
scale_frame = tk.LabelFrame(right_frame, text="比例尺 / Scale Bar", padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
scale_frame.pack(fill='both', padx=6, pady=4, expand=True)

scale_enable_var = tk.BooleanVar(value=False)
scale_check = tk.Checkbutton(scale_frame, text="顯示比例尺 / Show Scale Bar", variable=scale_enable_var, font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
scale_check.grid(row=0, column=0, columnspan=2, sticky='w', padx=2, pady=6)

scale_label = tk.Label(scale_frame, text="像素/微米 (px/um) :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
scale_label.grid(row=1, column=0, sticky='w', padx=2, pady=6)
scale_entry = ttk.Entry(scale_frame, width=10, font=ENTRY_FONT)
scale_entry.grid(row=1, column=1, sticky='w', padx=2, pady=6)

scale_length_label = tk.Label(scale_frame, text="比例尺長度 (um) :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
scale_length_label.grid(row=2, column=0, sticky='w', padx=2, pady=6)
scale_length_entry = ttk.Entry(scale_frame, width=10, font=ENTRY_FONT)
scale_length_entry.insert(0, "50")
scale_length_entry.grid(row=2, column=1, sticky='w', padx=2, pady=6)

distance_enable_var = tk.BooleanVar(value=False)
distance_check = tk.Checkbutton(scale_frame, text="標示距離 / Show Distance Label", variable=distance_enable_var, font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
distance_check.grid(row=3, column=0, columnspan=2, sticky='w', padx=2, pady=6)

# 透鏡倍率設置
lens_frame = tk.LabelFrame(right_frame, text="透鏡倍率 / Lens Magnification", padx=FRAME_PADX, pady=FRAME_PADY, font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF", borderwidth=2, relief="solid")
lens_frame.pack(fill='both', padx=6, pady=4, expand=True)

lens_label = tk.Label(lens_frame, text="倍率 (Magnification) :", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0")
lens_label.grid(row=0, column=0, sticky='w', padx=2, pady=6)
lens_entry = ttk.Entry(lens_frame, width=10, font=ENTRY_FONT)
lens_entry.insert(0, "1.0")
lens_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)

lens_info_label = tk.Label(lens_frame, text="(例: 2x、5x、10x 或 1.5)\n(無透鏡時輸入 1.0)", font=("times new roman", 9), bg="#2B2B2B", fg="#888888")
lens_info_label.grid(row=1, column=0, columnspan=2, sticky='w', padx=2, pady=(2,4))

def set_roi_shape(shape):
    global roi_shape_choice
    roi_shape_choice = shape
    roi_shape_var.set(shape)
    validate_start_enable()

def apply_gain_and_exposure_to_camera(gain_val, exposure_us):
    global cam, CAMERA_TYPE
    ok_gain = False
    ok_exp = False
    if cam is None:
        return ok_gain, ok_exp

    # Exposure（XIMEA 單位為微秒；Thorlabs 單位為秒）
    try:
        if CAMERA_TYPE == "XIMEA":
            if hasattr(cam, "set_exposure"):
                cam.set_exposure(int(exposure_us) * 1e3)
                ok_exp = True
        else:
            if hasattr(cam, "set_exposure"):
                cam.set_exposure(float(exposure_us) / 1e3)
                ok_exp = True
            elif hasattr(cam, "exposure"):
                cam.exposure = float(exposure_us) / 1e3
                ok_exp = True
    except Exception:
        ok_exp = False

    # Gain
    try:
        if hasattr(cam, "set_gain"):
            cam.set_gain(float(gain_val))
            ok_gain = True
        elif hasattr(cam, "gain"):
            cam.gain = float(gain_val)
            ok_gain = True
    except Exception:
        ok_gain = False

    return ok_gain, ok_exp

# 所有設定欄位皆填才可start (decimal 必填、fps 必填、且至少選一個 ROI)
def validate_start_enable(event=None):

    gain_ok = bool(gain_entry.get().strip())
    exp_ok = bool(exposure_entry.get().strip())
    thr_ok = bool(threshold_entry.get().strip())
    dec_ok = bool(dec_entry.get().strip())
    fps_ok = bool(fps_input_entry.get().strip())
    roi_ok = len(rois) > 0
    if gain_ok and exp_ok and thr_ok and dec_ok and fps_ok and roi_ok:
        start_btn.config(state="normal")
    else:
        start_btn.config(state="disabled")

# 綁定欄位變動以重新驗證
for widget in (gain_entry, exposure_entry, threshold_entry, dec_entry, fps_input_entry, roi_width_entry, roi_height_entry, roi_diameter_entry):
    widget.bind("<KeyRelease>", validate_start_enable)
rb_rect_ui.config(command=lambda: (set_roi_shape('rect'), validate_start_enable()))
rb_circle_ui.config(command=lambda: (set_roi_shape('circle'), validate_start_enable()))
fps_input_entry.bind("<KeyRelease>", validate_start_enable)

# 按下start，訊息提示使用者檢查設定
def start_button_handler():

    global analyzing, roi_selected, roi_locked, threshold_value, decimal_places, user_gain_val, user_exposure_ms, user_fps_val, settings_applied

    if not gain_entry.get().strip() or not exposure_entry.get().strip() or not threshold_entry.get().strip() or not dec_entry.get().strip() or not fps_input_entry.get().strip():
        messagebox.showwarning("設定未填齊 / Missing settings", "請確認 Gain、Exposure、Threshold、Decimal places 與 FPS 都已填寫。\nPlease ensure Gain, Exposure, Threshold, Decimal places and FPS are filled.")
        return

    fps_text = fps_input_entry.get().strip()
    try:
        fps_val = int(fps_text)
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
        messagebox.showwarning("小數位錯誤 / Invalid decimal places", "請輸入 0~10 的整數作為小數位數。\nPlease enter an integer 0~10 for decimal places.")
        return

    try:
        thr_v = float(threshold_entry.get().strip())
        if thr_v < 0 or thr_v > 255:
            raise ValueError
    except Exception:
        messagebox.showwarning("門檻值錯誤 / Invalid Threshold", "Threshold 必須在 0~255。\nThreshold must be between 0 and 255.")
        return

    try:
        gain_v = float(gain_entry.get().strip())
    except Exception:
        messagebox.showwarning("Gain 格式錯誤 / Invalid Gain", "Gain 必須為數字。\nGain must be a number.")
        return
    try:
        exp_v = float(exposure_entry.get().strip())
    except Exception:
        messagebox.showwarning("Exposure 格式錯誤 / Invalid Exposure", "Exposure 必須為數字（XIMEA 為 us）。\nExposure must be a number (us for XIMEA).")
        return

    if len(rois) == 0:
        messagebox.showwarning("未選取 ROI / No ROI", "請至少選取一個 ROI。\nPlease select at least one ROI.")
        return

    summary = [
        f"Gain: {gain_v}",
        f"Exposure（ms）: {exp_v}",
        f"Threshold: {thr_v}",
        f"Decimal places: {dec_v}",
        f"FPS setting: {fps_val}",
    ]

    try:
        if CAMERA_TYPE == "XIMEA":
            ds = downsampling_var.get()
            ds_text = "1x1 (2464x2056)" if ds == '1x1' else "2x2 (1232x1028)"
            summary.append(f"XIMEA Downsampling: {ds_text}")
    except Exception:
        pass

    summary.append("")
    summary.append("請確認以上設定再開始偵測。\nPlease confirm the settings before starting.")
    if not messagebox.askokcancel("確認設定 / Confirm settings", "\n".join(summary)):
        return

    # 套用設定
    user_gain_val = gain_v
    user_exposure_ms = exp_v
    threshold_value = thr_v
    decimal_places = dec_v
    user_fps_val = fps_val
    settings_applied = True

    # 鎖定 UI
    roi_locked = True
    threshold_entry.config(state="disabled")
    default_btn.state(["disabled"])
    gain_entry.config(state="disabled")
    exposure_entry.config(state="disabled")
    dec_entry.config(state="disabled")
    fps_input_entry.config(state="disabled")
    rb_rect_ui.config(state="disabled")
    rb_circle_ui.config(state="disabled")
    
    if CAMERA_TYPE == "XIMEA":
        rb1.config(state="disabled")
        rb2.config(state="disabled")
    start_btn.config(text="停止 / Stop")

    analyzing = True
    initialize_plot_area(len(rois))
    threading.Thread(target=analysis_loop, daemon=True).start()

def on_start():
    # Start -> Stop -> Restart Detection
    if start_btn["text"].startswith("開始") or start_btn["text"].startswith("Start"):
        start_button_handler()
    elif start_btn["text"].startswith("停止") or start_btn["text"].startswith("Stop"):
        # Stop 
        global analyzing
        analyzing = False
        start_btn["text"] = "重新啟動偵測 / Restart Detection"
    else:
        # Restart Detection
        if plot_win:
            if not messagebox.askokcancel("確認重新開始 / Confirm restart", "確定要清空資料並重新偵測嗎？\nAre you sure you want to clear data and restart detection?"):
                return
            try:
                plot_win.destroy()
            except Exception:
                pass

        # reset UI & variables to initial state
        rois.clear()
        roi_selected = False
        roi_data.clear()
        timestamps.clear()
        start_btn["text"] = "開始 / Start"
        default_btn.state(["!disabled"])

        global roi_locked, threshold_value, user_gain_val, user_exposure_ms, decimal_places, user_fps_val, settings_applied
        roi_locked = False
        threshold_value = None
        threshold_entry.config(state="normal")
        threshold_entry.delete(0, tk.END)

        # restore defaults in settings
        gain_entry.config(state="normal")
        exposure_entry.config(state="normal")
        dec_entry.config(state="normal")
        fps_input_entry.config(state="normal")
        rb_rect_ui.config(state="normal")
        rb_circle_ui.config(state="normal")

        gain_entry.delete(0, tk.END)
        gain_entry.insert(0, "0.0")

        exposure_entry.delete(0, tk.END)
        exposure_entry.insert(0, str(user_exposure_ms))

        dec_entry.delete(0, tk.END)

        fps_input_entry.delete(0, tk.END)

        try:
            if CAMERA_TYPE == "XIMEA":
                rb1.config(state="normal")
                rb2.config(state="normal")
            else:
                rb1.config(state="disabled")
                rb2.config(state="disabled")
        except Exception:
            pass

        apply_defaults_on_restart_camera()

        user_gain_val = None
        user_exposure_ms = None
        decimal_places = None
        user_fps_val = None
        settings_applied = False
        start_btn.config(state="disabled")
        messagebox.showinfo("已重置 / Restarted", "已清空資料並重置設定，可重新設定並選取 ROI。\nData cleared and settings reset.")

# Reselect ROI 
def on_default():
    global rois, roi_data, timestamps, roi_selected
    if roi_locked:
        messagebox.showinfo("ROI 已鎖定 / ROI Locked", "請先 Restart 才能重新選取 ROI。\nROI is locked; restart to reselect.")
        return
    rois.clear()
    roi_data.clear()
    timestamps.clear()
    roi_selected = False
    validate_start_enable()

# 滑鼠框選ROI（固定大小，用滑鼠拖動放置位置）
def on_mouse_down(event):
    global start_x, start_y, dragging, roi_dragging_offset_x, roi_dragging_offset_y, roi_fixed_width, roi_fixed_height, roi_fixed_diameter
    if (not analyzing) and (not roi_locked):
        # 先讀取用戶輸入的ROI大小
        try:
            if roi_shape_var.get() == 'rect':
                roi_fixed_width = int(roi_width_entry.get())
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
        
        start_x = event.x
        start_y = event.y
        dragging = True
        roi_dragging_offset_x = 0
        roi_dragging_offset_y = 0

def on_mouse_move(event):
    global end_x, end_y, roi_dragging_offset_x, roi_dragging_offset_y
    if dragging:
        roi_dragging_offset_x = event.x - start_x
        roi_dragging_offset_y = event.y - start_y

def on_mouse_up(event):
    global roi_selected, dragging, roi_fixed_width, roi_fixed_height, roi_fixed_diameter
    if not dragging:
        return
    dragging = False
    
    # 根據形狀類型創建ROI
    try:
        if roi_shape_var.get() == 'rect':
            # 矩形模式
            x1 = max(0, min(disp_w - roi_fixed_width, start_x))
            y1 = max(0, min(disp_h - roi_fixed_height, start_y))
            x2 = x1 + roi_fixed_width
            y2 = y1 + roi_fixed_height
            
            rois.append(('rect', x1, y1, x2, y2))
            roi_selected = True
        else:
            # 圓形模式
            r = roi_fixed_diameter // 2
            cx = max(r, min(disp_w - r, start_x))
            cy = max(r, min(disp_h - r, start_y))
            
            rois.append(('circle', cx, cy, r))
            roi_selected = True
    except Exception as e:
        messagebox.showerror("錯誤 / Error", f"建立ROI時發生錯誤：{str(e)}\nError creating ROI: {str(e)}")
        return

    validate_start_enable()

# 檢測是否點中某個ROI
def get_roi_at_point(x, y):
    """返回包含點(x, y)的ROI索引，如果沒有則返回-1"""
    for idx, roi in enumerate(rois):
        if roi[0] == 'rect':
            _, x1, y1, x2, y2 = roi
            if x1 <= x <= x2 and y1 <= y <= y2:
                return idx
        elif roi[0] == 'circle':
            _, cx, cy, r = roi
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if dist <= r:
                return idx
    return -1

# 右鍵按下事件 - 選擇要拖動的ROI
def on_right_mouse_down(event):
    global right_dragging, right_drag_roi_index, right_drag_start_x, right_drag_start_y, right_drag_roi_start_pos
    if (not analyzing) and (not roi_locked) and len(rois) > 0:
        roi_idx = get_roi_at_point(event.x, event.y)
        if roi_idx >= 0:
            right_dragging = True
            right_drag_roi_index = roi_idx
            right_drag_start_x = event.x
            right_drag_start_y = event.y
            # 保存ROI的初始位置
            roi = rois[roi_idx]
            right_drag_roi_start_pos = roi

# 右鍵拖動事件 - 實時更新ROI位置
def on_right_mouse_move(event):
    global right_dragging, right_drag_roi_index, right_drag_start_x, right_drag_start_y, right_drag_roi_start_pos
    if not (right_dragging and right_drag_roi_index >= 0 and right_drag_roi_index < len(rois)):
        return
    
    # 計算從起始點到當前位置的總偏移量
    total_offset_x = event.x - right_drag_start_x
    total_offset_y = event.y - right_drag_start_y
    
    try:
        if right_drag_roi_start_pos[0] == 'rect':
            _, x1, y1, x2, y2 = right_drag_roi_start_pos
            width = x2 - x1
            height = y2 - y1
            
            # 計算新位置
            new_x1 = x1 + total_offset_x
            new_y1 = y1 + total_offset_y
            new_x2 = new_x1 + width
            new_y2 = new_y1 + height
            
            # 邊界檢查
            if new_x1 < 0:
                new_x1 = 0
                new_x2 = width
            if new_y1 < 0:
                new_y1 = 0
                new_y2 = height
            if new_x2 > disp_w:
                new_x2 = disp_w
                new_x1 = disp_w - width
            if new_y2 > disp_h:
                new_y2 = disp_h
                new_y1 = disp_h - height
            
            rois[right_drag_roi_index] = ('rect', new_x1, new_y1, new_x2, new_y2)
        
        elif right_drag_roi_start_pos[0] == 'circle':
            _, cx, cy, r = right_drag_roi_start_pos
            
            # 計算新中心
            new_cx = cx + total_offset_x
            new_cy = cy + total_offset_y
            
            # 邊界檢查
            new_cx = max(r, min(disp_w - r, new_cx))
            new_cy = max(r, min(disp_h - r, new_cy))
            
            rois[right_drag_roi_index] = ('circle', new_cx, new_cy, r)
    
    except Exception as e:
        pass

# 右鍵釋放事件 - 結束拖動
def on_right_mouse_up(event):
    global right_dragging, right_drag_roi_index, right_drag_roi_start_pos
    if not right_dragging or right_drag_roi_index < 0:
        return
    
    right_dragging = False
    right_drag_roi_index = -1
    right_drag_roi_start_pos = None

# 儲存 CSV 
def save_csv():
    if not roi_data or not timestamps:
        messagebox.showwarning("無資料 / No Data", "尚未產生資料，無法儲存。\nNo data to save.")
        return
    now = datetime.datetime.now()
    filename = f"Light intensity_{now:%Y_%m_%d_%H_%M_%S}.csv"
    df = pd.DataFrame({"Time (s)": timestamps})
    for i, values in enumerate(roi_data):
        df[f"Sample {i+1}"] = values
    df.to_csv(filename, index=False)
    messagebox.showinfo("儲存成功 / Saved", f"數值已儲存為 {filename}\nValues Saved as {filename}")

video_label.bind("<ButtonPress-1>", on_mouse_down)
video_label.bind("<B1-Motion>", on_mouse_move)
video_label.bind("<ButtonRelease-1>", on_mouse_up)
video_label.bind("<ButtonPress-3>", on_right_mouse_down)
video_label.bind("<B3-Motion>", on_right_mouse_move)
video_label.bind("<ButtonRelease-3>", on_right_mouse_up)
start_btn.config(command=on_start)
default_btn.config(command=on_default)
save_btn.config(command=save_csv)

# XIMEA相機初始化
def init_camera_ximea():
    global cam, xi_img, orig_w, orig_h, bit_depth

    try:
        from ximea import xiapi
    except Exception:
        raise RuntimeError("無法載入 ximea 模組；請安裝 XIMEA SDK 與 Python binding。 / Cannot import ximea module; please install XIMEA SDK and Python bindings.")

    cam = xiapi.Camera()
    cam.open_device()

    try:
        cam.set_imgdataformat("XI_MONO8")
    except Exception:
        pass
    
    try:
        ds = downsampling_var.get()
        if hasattr(cam, "set_downsampling"):
            if ds == '1x1':
                cam.set_downsampling('XI_DWN_1x1')
            else:
                cam.set_downsampling('XI_DWN_2x2')
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
        raise RuntimeError("無法讀取 XIMEA 影像: " + str(e) + "\nCannot get XIMEA image: " + str(e))

    if frame is None:
        raise RuntimeError("無法讀取 XIMEA 影像\nCannot get XIMEA image")

    if frame.dtype != np.uint8:
        try:
            frame = frame.astype(np.uint8)
        except Exception:
            frame = np.clip(frame, 0, 255).astype(np.uint8)

    orig_h, orig_w = frame.shape[:2]
    bit_depth = 8
    
    # 為 XIMEA 相機啟用 scale_entry，允許使用者自行設置比例尺
    try:
        scale_entry.config(state="normal")
    except Exception:
        pass

# Thorlabs相機初始化
def init_camera_thorlabs():
    global cam, orig_w, orig_h, bit_depth

    import pylablib as pll
    from pylablib.devices import Thorlabs

    try:
        # 嘗試多個可能的路徑
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
            # 如果以上路徑都不行，提示使用者手動設置
            import os
            if os.path.exists(r"C:\Program Files\Thorlabs"):
                # 自動搜索
                for root, dirs, files in os.walk(r"C:\Program Files\Thorlabs"):
                    if "thorlabs_tsi_camera_sdk.dll" in files:
                        pll.par["devices/dlls/thorlabs_tlcam"] = root
                        dll_found = True
                        break
        
        if not dll_found:
            raise RuntimeError("找不到 thorlabs_tsi_camera_sdk.dll，請確認已安裝 ThorCam 軟體。\nCannot find thorlabs_tsi_camera_sdk.dll. Please ensure ThorCam software is installed.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"無法設置 Thorlabs DLL 路徑: {e}\nFailed to set Thorlabs DLL path: {e}")

    cams = Thorlabs.list_cameras_tlcam()

    if not cams:
        raise RuntimeError("找不到 Thorlabs 相機，請確認連線與驅動\nNo Thorlabs cameras found\nPlease check connection and drivers.")

    serial = cams[0]
    cam = Thorlabs.ThorlabsTLCamera(serial=serial)

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
        sensor_type, bit_depth_local = cam.get_sensor_info()
        bit_depth = bit_depth_local if bit_depth_local is not None else 8
    except Exception:
        bit_depth = 8

    try:
        cam.wait_for_frame(timeout=2.0)
        frame = cam.read_oldest_image()
    except Exception as e:
        raise RuntimeError("無法讀取 Thorlabs 影像: " + str(e) + " / Cannot read Thorlabs image: " + str(e))

    if frame is None:
        raise RuntimeError("無法讀取 Thorlabs 影像 / Cannot read Thorlabs image")
    
    if bit_depth > 8:
        shift = bit_depth - 8
        frame = (frame >> shift).astype(np.uint8)
    else:
        frame = frame.astype(np.uint8)

    if frame.ndim == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    orig_h, orig_w = frame.shape[:2]
    
    # 自動設置 Thorlabs 相機的比例尺參數
    # Thorlabs camera: 3.45um x 3.45um per pixel
    try:
        scale_entry.delete(0, tk.END)
        scale_entry.insert(0, "3.45")
        scale_entry.config(state="disabled")  # 禁止使用者編輯 Thorlabs 的比例尺
        scale_enable_var.set(True)
    except Exception:
        pass

# 選擇相機
def ask_camera_choice_and_init():
    global CAMERA_TYPE, cam
    choice_win = tk.Toplevel(root)
    choice_win.resizable(False, False)
    choice_win.title("選擇相機 / Choose Camera")
    choice_win.grab_set()
    choice_win.configure(bg="#2B2B2B")
    tk.Label(choice_win, text="請選擇欲使用的相機 / Please choose camera:", font=("Arial", 12), bg="#2B2B2B", fg="#00BFFF").pack(padx=10, pady=10)

    var = tk.StringVar(value="XIMEA")

    def set_choice(val):
        var.set(val)

    rb1_choice = tk.Radiobutton(choice_win, text="XIMEA", variable=var, value="XIMEA", command=lambda: set_choice("XIMEA"), bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
    rb1_choice.pack(anchor="w", padx=20, pady=5)
    rb2_choice = tk.Radiobutton(choice_win, text="THORLABS", variable=var, value="THORLABS", command=lambda: set_choice("THORLABS"), bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
    rb2_choice.pack(anchor="w", padx=20, pady=5)

    status_label = tk.Label(choice_win, text="選擇後按 Initialize 以啟動相機 / Click 'Initialize' to start camera", fg="#888888", bg="#2B2B2B")
    status_label.pack(pady=(5,10))

    def on_init():
        nonlocal var, choice_win
        choice = var.get()
        try:
            if choice == "XIMEA":
                try:
                    rb1.config(state="normal")
                    rb2.config(state="normal")
                except Exception:
                    pass
                init_camera_ximea()
            else:
                # 若為 Thorlabs，則關閉 downsampling 選項
                try:
                    rb1.config(state="disabled")
                    rb2.config(state="disabled")
                except Exception:
                    pass
                init_camera_thorlabs()

            status_label.config(text=f"{choice} 已成功初始化。 / {choice} initialized successfully.", fg="#107C10")
            choice_win.grab_release()
            choice_win.destroy()
            globals()["CAMERA_TYPE"] = choice
            
            try:
                if choice == "XIMEA":
                    rb1.config(state="normal")
                    rb2.config(state="normal")
                else:
                    rb1.config(state="disabled")
                    rb2.config(state="disabled")
            except Exception:
                pass
        except Exception as e:
            status_label.config(text=f"初始化失敗: {e}", fg="#FF4444")
            messagebox.showerror("相機初始化錯誤 / Camera Init Error", f"{e}")

    init_btn = ttk.Button(choice_win, text="初始化 / Initialize", command=on_init)
    init_btn.pack(pady=(0,10))

    root.wait_window(choice_win)

# 關閉相機
def on_close():
    if messagebox.askokcancel("退出程式 / Exit Program", "確定要退出程式嗎？\nAre you sure you want to exit?"):
        global running, analyzing, cam, CAMERA_TYPE
        running = False
        analyzing = False
        try:
            if CAMERA_TYPE == "XIMEA" and cam is not None:
                try:
                    cam.stop_acquisition()
                except Exception:
                    pass
                try:
                    cam.close_device()
                except Exception:
                    pass
            elif CAMERA_TYPE == "THORLABS" and cam is not None:
                try:
                    cam.stop_acquisition()
                except Exception:
                    pass
                try:
                    cam.close()
                except Exception:
                    pass
        except Exception:
            pass
        root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)

# Plot / Log 初始化
def initialize_plot_area(n):
    global plot_win, canvas_frame, scrollable_frame, plot_canvases, plot_axes, plot_figures, log_text_widget, text_follow

    if plot_win:
        try:
            plot_win.destroy()
        except Exception:
            pass

    plot_win = tk.Toplevel(root)
    plot_win.title("ROI 平均光強度（每秒） / Avg ROI Intensity (per second)")
    plot_win.configure(bg="#1E1E1E")
    plot_win.protocol("WM_DELETE_WINDOW", confirm_close_plot)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    win_w = int(sw * 0.9)
    win_h = int(sh * 0.9)
    plot_win.geometry(f"{win_w}x{win_h}")

    paned = tk.PanedWindow(plot_win, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=10, bg="#1E1E1E")
    paned.pack(fill="both", expand=True)

    left_container = tk.Frame(paned, bg="#1E1E1E")
    paned.add(left_container, minsize=1000)

    canvas_frame = tk.Canvas(left_container, bg="#1E1E1E", highlightthickness=0)
    v_scroll = tk.Scrollbar(left_container, orient=tk.VERTICAL, command=canvas_frame.yview)
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

    LOG_FONT_SIZE = 18
    LOG_FONT = ("Arial", LOG_FONT_SIZE)

    text_container = tk.Frame(text_frame, bg="#1E1E1E")
    text_container.pack(side="top", fill="both", expand=True, padx=2, pady=(4,4))

    log_text_widget = tk.Text(text_container, width=40, height=34, font=LOG_FONT, wrap="word", state="disabled", bg="#2B2B2B", fg="#00BFFF", insertbackground="#00BFFF")
    log_text_widget.pack(side="left", fill="both", expand=True)

    scrollbar_text = tk.Scrollbar(text_container, orient=tk.VERTICAL, command=log_text_widget.yview)
    scrollbar_text.pack(side="right", fill="y", padx=(2,0))
    log_text_widget.configure(yscrollcommand=scrollbar_text.set)

    def scroll_to_bottom_action():
        global text_follow
        text_follow = True
        try:
            log_text_widget.see(tk.END)
        except Exception:
            pass

    button_frame = tk.Frame(text_frame, bg="#1E1E1E")
    
    button_frame.pack(side="bottom", fill="x", padx=4, pady=(2,6))

    scroll_btn = tk.Button(button_frame, text="捲到最底 / Scroll to bottom", command=scroll_to_bottom_action,
                           font=("Arial", 11), height=2, bg="#0078D4", fg="white", activebackground="#107C10", activeforeground="white")
    scroll_btn.pack(fill="x")

    # 當使用者在文字區使用滑鼠滾輪或滑動 scrollbar 時，暫停自動追蹤
    def set_text_follow(val: bool):
        global text_follow
        text_follow = val

    def on_text_wheel(event):
        set_text_follow(False)
        delta = 0
        
        if hasattr(event, 'delta'):
            try:
                delta = int(event.delta / 120)
            except Exception:
                delta = 0
        if hasattr(event, 'num'):
            if event.num == 4:
                delta = 1
            elif event.num == 5:
                delta = -1
        try:
            log_text_widget.yview_scroll(-delta, "units")
        except Exception:
            pass
        return "break"

    # 綁定文字區滾輪
    log_text_widget.bind("<MouseWheel>", on_text_wheel)

    # 當使用者點擊文字區的 scrollbar 時，也暫停自動追蹤
    scrollbar_text.bind("<ButtonPress-1>", lambda e: set_text_follow(False))

    # 當滑鼠在左側時，滾動圖表區
    def _on_canvas_mousewheel(event):
        try:
            canvas_frame.yview_scroll(int(-1*(event.delta/120)), "units")
        except Exception:
            try:
                canvas_frame.yview_scroll(int(-1*(event.delta)), "units")
            except Exception:
                pass

    def _bind_canvas_mousewheel(e):
        canvas_frame.bind_all("<MouseWheel>", _on_canvas_mousewheel)

    def _unbind_canvas_mousewheel(e):
        try:
            canvas_frame.unbind_all("<MouseWheel>")
        except Exception:
            pass

    canvas_frame.bind("<Enter>", _bind_canvas_mousewheel)
    canvas_frame.bind("<Leave>", _unbind_canvas_mousewheel)

    plot_canvases.clear()
    plot_axes.clear()
    plot_figures.clear()

    for i in range(n):
        fig = Figure(figsize=(5.5, 3.5), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_title(f"Light intensity of Sample {i+1}")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Intensity")
        ax.grid(True)
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=scrollable_frame)
        widget = canvas.get_tk_widget()
        row = i // 2
        col = i % 2
        widget.grid(row=row, column=col, padx=10, pady=10)
        widget.bind("<Button-3>", lambda event, f=fig: save_plot_image(f))
        canvas.draw()
        plot_figures.append(fig)
        plot_canvases.append(canvas)
        plot_axes.append(ax)

    scrollable_frame.update_idletasks()
    canvas_frame.config(scrollregion=canvas_frame.bbox("all"))
    paned.sash_place(0, int(win_w * 0.75), 0)

def append_log(text):
    # 在文字區新增一筆訊息，並根據 text_follow 決定是否自動滾到底
    global text_follow

    if log_text_widget:
        try:
            log_text_widget.config(state="normal")
            log_text_widget.insert(tk.END, text + "\n\n")

            if text_follow:
                log_text_widget.see(tk.END)

            # 若 text_follow 為 False，保留目前scrollbar位置
            log_text_widget.config(state="disabled")
        except Exception:
            pass

def confirm_close_plot():
    if messagebox.askokcancel("關閉視窗 / Close Window", "關閉圖表視窗後，偵測將會停止。\nClosing the plot window will STOP detection."):
        global analyzing
        analyzing = False

        try:
            start_btn["text"] = "重新啟動偵測 / Restart Detection"
            default_btn.state(["disabled"])
        except Exception:
            pass

        try:
            plot_win.destroy()
        except Exception:
            pass

def save_plot_image(fig):
    now = datetime.datetime.now()
    filename = f"Plot_{now:%Y_%m_%d_%H_%M_%S}.png"
    fig.savefig(filename)
    messagebox.showinfo("儲存成功 / Saved", f"圖表已儲存為 {filename}\nPlot saved as {filename}")

def update_plots():
    for i, values in enumerate(roi_data):
        ax = plot_axes[i]
        ax.clear()
        ax.plot(timestamps, values, marker='o')
        ax.set_title(f"Light intensity of Sample {i+1}")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Intensity")
        ax.grid(True)
        ax.figure.tight_layout()
        plot_canvases[i].draw()

def update_display():
    global pixel_size_um, show_scale_bar, scale_bar_length_um, show_distance_label, lens_magnification
    
    with frame_lock:
        frame = current_frame if current_frame is not None else None

    if frame is not None:
        if frame.ndim == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        display_frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

        # 更新全局變數
        try:
            # 讀取透鏡倍率
            lens_val = lens_entry.get().strip()
            if lens_val:
                try:
                    lens_magnification = float(lens_val)
                    if lens_magnification <= 0:
                        lens_magnification = 1.0
                except ValueError:
                    lens_magnification = 1.0
            else:
                lens_magnification = 1.0
            
            if scale_enable_var.get() and scale_entry.get().strip():
                try:
                    base_pixel_size = float(scale_entry.get().strip())
                    # 應用透鏡倍率：倍率越高，相機像素對應的實際長度越短
                    pixel_size_um = base_pixel_size / lens_magnification
                    show_scale_bar = True
                except ValueError:
                    show_scale_bar = False
                    pixel_size_um = None
            else:
                show_scale_bar = False
                pixel_size_um = None
            
            if scale_length_entry.get().strip():
                try:
                    scale_bar_length_um = float(scale_length_entry.get().strip())
                except ValueError:
                    pass
            
            show_distance_label = distance_enable_var.get()
        except Exception as e:
            show_scale_bar = False
            show_distance_label = False
            lens_magnification = 1.0

        # draw ROIs
        for i, r in enumerate(rois):
            if not r:
                continue
            if r[0] == 'rect':
                _, x1, y1, x2, y2 = r
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), (255, 255, 255), 2)
                # 改善Sample標籤的顯示
                sample_text = f"Sample {i+1}"
                text_size = cv2.getTextSize(sample_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
                text_x = x1
                text_y = max(20, y1-15)
                cv2.rectangle(display_frame, (text_x-5, text_y-text_size[1]-5), (text_x+text_size[0]+5, text_y+5), (0, 0, 0), -1)
                cv2.putText(display_frame, sample_text, (text_x, text_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
                
                # 顯示矩形的寬高（如果啟用距離標籤）
                if show_distance_label and pixel_size_um is not None:
                    width_px = x2 - x1
                    height_px = y2 - y1
                    width_um = width_px * pixel_size_um
                    height_um = height_px * pixel_size_um
                    # 如果有透鏡倍率，在尺寸後添加倍率標記
                    if lens_magnification != 1.0:
                        dist_text = f"W:{width_um:.1f}um H:{height_um:.1f}um ({lens_magnification:g}x)"
                    else:
                        dist_text = f"W:{width_um:.1f}um H:{height_um:.1f}um"
                    # 添加文字背景，改善可讀性
                    text_size = cv2.getTextSize(dist_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                    text_x = x1
                    text_y = min(display_frame.shape[0]-5, y2+20)
                    cv2.rectangle(display_frame, (text_x-5, text_y-text_size[1]-5), (text_x+text_size[0]+5, text_y+5), (0, 0, 0), -1)
                    cv2.putText(display_frame, dist_text, (text_x, text_y),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
            elif r[0] == 'circle':
                _, cx, cy, rad = r
                cv2.circle(display_frame, (int(cx), int(cy)), int(rad), (255,255,255), 2)
                # 改善Sample標籤的顯示
                sample_text = f"Sample {i+1}"
                text_size = cv2.getTextSize(sample_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
                text_x = int(cx - rad)
                text_y = max(20, int(cy - rad - 15))
                cv2.rectangle(display_frame, (text_x-5, text_y-text_size[1]-5), (text_x+text_size[0]+5, text_y+5), (0, 0, 0), -1)
                cv2.putText(display_frame, sample_text, (text_x, text_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
                
                # 顯示圓形的直徑（如果啟用距離標籤）
                if show_distance_label and pixel_size_um is not None:
                    diameter_px = 2 * rad
                    diameter_um = diameter_px * pixel_size_um
                    # 如果有透鏡倍率，在尺寸後添加倍率標記
                    if lens_magnification != 1.0:
                        dist_text = f"Diameter:{diameter_um:.1f}um ({lens_magnification:g}x)"
                    else:
                        dist_text = f"Diameter:{diameter_um:.1f}um"
                    # 添加文字背景，改善可讀性
                    text_size = cv2.getTextSize(dist_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                    text_x = int(cx - rad)
                    text_y = min(display_frame.shape[0]-5, int(cy + rad + 20))
                    cv2.rectangle(display_frame, (text_x-5, text_y-text_size[1]-5), (text_x+text_size[0]+5, text_y+5), (0, 0, 0), -1)
                    cv2.putText(display_frame, dist_text, (text_x, text_y),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)

        # preview dragging - 顯示固定大小的ROI跟隨鼠標
        if dragging:
            try:
                if roi_shape_var.get() == 'rect':
                    # 矩形模式：顯示固定大小的矩形
                    roi_w = roi_fixed_width
                    roi_h = roi_fixed_height
                    x1 = max(0, min(disp_w - roi_w, start_x))
                    y1 = max(0, min(disp_h - roi_h, start_y))
                    x2 = x1 + roi_w
                    y2 = y1 + roi_h
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (200,200,200), 1)
                    # 顯示尺寸信息
                    size_text = f"{roi_w}x{roi_h}px"
                    text_size = cv2.getTextSize(size_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    text_x = max(0, x1)
                    text_y = max(15, y1 - 5)
                    cv2.rectangle(display_frame, (text_x-2, text_y-text_size[1]-2), (text_x+text_size[0]+2, text_y+2), (0, 0, 0), -1)
                    cv2.putText(display_frame, size_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)
                else:
                    # 圓形模式：顯示固定大小的圓形
                    r = roi_fixed_diameter // 2
                    cx = max(r, min(disp_w - r, start_x))
                    cy = max(r, min(disp_h - r, start_y))
                    cv2.circle(display_frame, (cx, cy), r, (200,200,200), 1)
                    # 顯示尺寸信息
                    size_text = f"Ø{roi_fixed_diameter}px"
                    text_size = cv2.getTextSize(size_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    text_x = max(0, cx - r)
                    text_y = max(15, cy - r - 5)
                    cv2.rectangle(display_frame, (text_x-2, text_y-text_size[1]-2), (text_x+text_size[0]+2, text_y+2), (0, 0, 0), -1)
                    cv2.putText(display_frame, size_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)
            except Exception:
                pass

        # 右鍵拖動預覽 - 顯示被拖動的ROI位置
        if right_dragging and right_drag_roi_index >= 0 and right_drag_roi_index < len(rois):
            try:
                roi = rois[right_drag_roi_index]
                if roi[0] == 'rect':
                    _, x1, y1, x2, y2 = roi
                    # 用淺藍色顯示被拖動的矩形
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (100, 200, 255), 2)
                    # 顯示移動提示
                    move_text = "Moving..."
                    text_size = cv2.getTextSize(move_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    text_x = max(0, x1)
                    text_y = max(15, y1 - 15)
                    cv2.rectangle(display_frame, (text_x-2, text_y-text_size[1]-2), (text_x+text_size[0]+2, text_y+2), (0, 0, 0), -1)
                    cv2.putText(display_frame, move_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 200, 255), 1)
                elif roi[0] == 'circle':
                    _, cx, cy, r = roi
                    # 用淺藍色顯示被拖動的圓形
                    cv2.circle(display_frame, (int(cx), int(cy)), int(r), (100, 200, 255), 2)
                    # 顯示移動提示
                    move_text = "Moving..."
                    text_size = cv2.getTextSize(move_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    text_x = max(0, int(cx - r))
                    text_y = max(15, int(cy - r - 15))
                    cv2.rectangle(display_frame, (text_x-2, text_y-text_size[1]-2), (text_x+text_size[0]+2, text_y+2), (0, 0, 0), -1)
                    cv2.putText(display_frame, move_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 200, 255), 1)
            except Exception:
                pass

        # 繪製比例尺
        if show_scale_bar and pixel_size_um is not None:
            scale_bar_px = int(scale_bar_length_um / pixel_size_um)
            if scale_bar_px > 0:
                # 比例尺位置：畫面下方中央
                margin = 20
                center_x = display_frame.shape[1] // 2
                x_start = center_x - scale_bar_px // 2
                x_end = center_x + scale_bar_px // 2
                y_pos = display_frame.shape[0] - margin

                # 畫比例尺線條
                cv2.line(display_frame, (x_start, y_pos), (x_end, y_pos), (0, 255, 255), 2)
                # 畫兩端刻度
                cv2.line(display_frame, (x_start, y_pos - 5), (x_start, y_pos + 5), (0, 255, 255), 2)
                cv2.line(display_frame, (x_end, y_pos - 5), (x_end, y_pos + 5), (0, 255, 255), 2)

                # 比例尺標籤
                if lens_magnification != 1.0:
                    scale_text = f"{scale_bar_length_um:.0f}um ({lens_magnification:.1f}x)"
                else:
                    scale_text = f"{scale_bar_length_um:.0f}um"
                text_size = cv2.getTextSize(scale_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                text_x = center_x - text_size[0] // 2
                text_y = y_pos - 15
                # 添加黑色背景框
                cv2.rectangle(display_frame, (text_x-5, text_y-text_size[1]-3), (text_x+text_size[0]+5, text_y+3), (0, 0, 0), -1)
                cv2.putText(display_frame, scale_text, (text_x, text_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        img_tk = ImageTk.PhotoImage(Image.fromarray(display_frame))
        video_label.imgtk = img_tk
        video_label.configure(image=img_tk)

    fps_display_label.config(text=f"Current FPS : {int(fps_value)}")
    root.after(30, update_display)

def video_loop_ximea():
    global current_frame, valid_frame_count, last_sec_time, fps_value, xi_img, cam

    try:
        from ximea import xiapi
    except Exception:
        return

    xi_img = xiapi.Image()

    while running:
        try:
            cam.get_image(xi_img)
            frame = xi_img.get_image_data_numpy()
        except Exception:
            continue

        if frame is None:
            continue

        now_sec = int(time.time())

        if now_sec != last_sec_time:
            fps_value = valid_frame_count
            valid_frame_count = 0
            last_sec_time = now_sec

        if user_fps_val is not None and valid_frame_count >= int(user_fps_val):
            continue

        if frame.dtype != np.uint8:
            try:
                frame = frame.astype(np.uint8)
            except Exception:
                frame = np.clip(frame, 0, 255).astype(np.uint8)

        # always resize to fixed disp_w, disp_h
        try:
            frame_resized = cv2.resize(frame, (disp_w, disp_h))
        except Exception:
            frame_resized = frame

        with frame_lock:
            current_frame = frame_resized

        valid_frame_count += 1

def video_loop_thorlabs():
    global current_frame, valid_frame_count, last_sec_time, fps_value, cam, bit_depth

    while running:
        try:
            cam.wait_for_frame(timeout=1.0)
            frame = cam.read_oldest_image()
        except Exception:
            continue

        if frame is None:
            continue

        if bit_depth > 8:
            shift = bit_depth - 8
            frame = (frame >> shift).astype(np.uint8)
        else:
            frame = frame.astype(np.uint8)

        now_sec = int(time.time())

        if now_sec != last_sec_time:
            fps_value = valid_frame_count
            valid_frame_count = 0
            last_sec_time = now_sec

        if user_fps_val is not None and valid_frame_count >= int(user_fps_val):
            continue

        if frame.ndim == 3 and frame.shape[2] == 3:
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            frame_gray = frame

        try:
            frame_resized = cv2.resize(frame_gray, (disp_w, disp_h))
        except Exception:
            frame_resized = frame_gray

        with frame_lock:
            current_frame = frame_resized

        valid_frame_count += 1

def analysis_loop():
    global roi_data, timestamps, threshold_value, decimal_places

    roi_data = [[] for _ in rois]
    timestamps = []
    start_time = time.time()
    buffer_vals = [[] for _ in rois]
    last_logged_sec = -1

    while analyzing:
        with frame_lock:
            frame = current_frame if current_frame is not None else None

        if frame is None:
            time.sleep(0.01)
            continue

        elapsed = int(time.time() - start_time)

        for i, r in enumerate(rois):
            if r[0] == 'rect':
                _, x1, y1, x2, y2 = r
                hx1, hy1 = max(0, int(x1)), max(0, int(y1))
                hx2, hy2 = min(frame.shape[1], int(x2)), min(frame.shape[0], int(y2))
                if hx2 <= hx1 or hy2 <= hy1:
                    avg_val = 0.0
                else:
                    roi = frame[hy1:hy2, hx1:hx2]
                    if threshold_value is not None:
                        mask = roi <= threshold_value
                        filtered_pixels = roi[mask]
                        avg_val = float(np.mean(filtered_pixels)) if filtered_pixels.size > 0 else 0.0
                    else:
                        avg_val = float(np.mean(roi))
            elif r[0] == 'circle':
                _, cx, cy, rad = r
                cx_i = int(round(cx))
                cy_i = int(round(cy))
                rad_i = int(round(rad))
                x1 = max(0, cx_i - rad_i)
                x2 = min(frame.shape[1], cx_i + rad_i)
                y1 = max(0, cy_i - rad_i)
                y2 = min(frame.shape[0], cy_i + rad_i)
                if x2 <= x1 or y2 <= y1 or rad_i <= 0:
                    avg_val = 0.0
                else:
                    patch = frame[y1:y2, x1:x2]
                    center_x = cx_i - x1
                    center_y = cy_i - y1
                    mask = np.zeros_like(patch, dtype=np.uint8)
                    cv2.circle(mask, (center_x, center_y), rad_i, 1, -1)
                    if threshold_value is not None:
                        roi_masked = patch[mask == 1]
                        filt = roi_masked[roi_masked <= threshold_value]
                        avg_val = float(np.mean(filt)) if filt.size > 0 else 0.0
                    else:
                        roi_masked = patch[mask == 1]
                        avg_val = float(np.mean(roi_masked)) if roi_masked.size > 0 else 0.0
            else:
                avg_val = 0.0

            buffer_vals[i].append(avg_val)

        if elapsed > last_logged_sec:
            log_message = ""

            for i in range(len(rois)):
                avg_sec = np.mean(buffer_vals[i]) if buffer_vals[i] else 0.0
                rounded = round(float(avg_sec), decimal_places) if decimal_places is not None else float(avg_sec)
                roi_data[i].append(rounded)
                buffer_vals[i] = []
                log_message += f"At {elapsed} sec, Sample {i+1} = {rounded}\n"
            timestamps.append(elapsed)

            try:
                update_plots()
            except Exception:
                pass

            append_log(log_message.strip())
            last_logged_sec = elapsed
        else:
            time.sleep(0.01)

start_btn.config(command=on_start)

def apply_defaults_on_restart_camera():
    global cam, CAMERA_TYPE

    try:
        if cam is not None:
            if hasattr(cam, "set_gain"):
                try:
                    cam.set_gain(0.0)
                except Exception:
                    pass
            if hasattr(cam, "set_exposure"):
                try:
                    if CAMERA_TYPE == "XIMEA":
                        user_exposure_ms=10.0
                        cam.set_exposure(int(user_exposure_ms) * 1e3)
                    else:
                        user_exposure_ms=10.0
                        cam.set_exposure(int(user_exposure_ms) / 1e3)
                except Exception:
                    pass
            if CAMERA_TYPE == "XIMEA" and hasattr(cam, "set_downsampling"):
                try:
                    ds = downsampling_var.get()
                    if ds == '1x1':
                        cam.set_downsampling('XI_DWN_1x1')
                    else:
                        cam.set_downsampling('XI_DWN_2x2')
                except Exception:
                    pass
    except Exception:
        pass

def start_system():
    global CAMERA_TYPE

    try:
        ask_camera_choice_and_init()
    except Exception as e:
        messagebox.showerror("初始化錯誤 / Initialization Error", f"初始化過程發生錯誤: {e}")
        return

    if CAMERA_TYPE is None:
        messagebox.showerror("未選擇相機 / No Camera", "未選擇或無法初始化相機，程式將退出。\nNo camera selected or failed to initialize, the program will exit")
        root.destroy()
        return

    if CAMERA_TYPE == "XIMEA":
        try:
            threading.Thread(target=video_loop_ximea, daemon=True).start()
        except Exception:
            return
    else:
        try:
            threading.Thread(target=video_loop_thorlabs, daemon=True).start()
        except Exception:
            return

    update_display()

threading.Thread(target=start_system, daemon=True).start()

validate_start_enable()

root.mainloop()

running = False
analyzing = False
time.sleep(0.1)
try: 
    if CAMERA_TYPE == "XIMEA" and cam is not None:
        try:
            cam.stop_acquisition()
        except Exception:
            pass
        try:
            cam.close_device()
        except Exception:
            pass
    elif CAMERA_TYPE == "THORLABS" and cam is not None:
        try:
            cam.stop_acquisition()
        except Exception:
            pass
        try:
            cam.close()
        except Exception:
            pass
except Exception:
    pass

print("相機已停止並釋放資源。\nCamera stopped and resources released.")