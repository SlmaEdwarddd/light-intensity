"""
main.py
-------
Application entry point.

Responsibilities
  1. Build the main Tkinter window (left video area + right settings panel).
  2. Wire every button, entry, and event to the appropriate handler.
  3. Launch the camera-selection dialog and start the capture thread.
  4. Run root.mainloop(); clean up the camera when the window closes.

Module layout
─────────────
  state.py        – shared global variables
  camera.py       – camera init, video loops, gain/exposure helpers
  analysis.py     – intensity measurement loop, CSV export
  roi_events.py   – mouse handlers for placing / moving ROIs
  ui_display.py   – per-frame renderer (update_display)
  ui_plot.py      – plot window, log panel
  main.py         – YOU ARE HERE
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox

import state
import camera
import analysis
import roi_events
import ui_display
import ui_plot


# ─────────────────────────────────────────────────────────────────────────────
# Font / style constants
# ─────────────────────────────────────────────────────────────────────────────
SETTINGS_LABEL_FONT = ("times new roman", 18, "bold")
SETTINGS_TYPE_FONT  = ("times new roman", 12, "bold")
SETTINGS_ITEM_FONT  = ("times new roman", 12)
ENTRY_FONT          = ("times new roman", 12)
RADIO_FONT          = ("times new roman", 12)
FRAME_PADX = 8
FRAME_PADY = 6


# ─────────────────────────────────────────────────────────────────────────────
# Window setup
# ─────────────────────────────────────────────────────────────────────────────

root = tk.Tk()
root.title("光強度偵測 / Light Intensity Detection")
root['bg'] = '#1E1E1E'
# 不能改變視窗大小，這樣可以確保畫面元素不會亂掉
root.resizable(False, False) 


right_w = 420
root.geometry(f"{state.disp_w + right_w}x{state.disp_h + 80}")

downsampling_var = tk.StringVar(value='2x2')

main_frame = tk.Frame(root, bg='#1E1E1E')
main_frame.pack(fill='both', expand=True)


# ─────────────────────────────────────────────────────────────────────────────
# Left panel – video + 3 buttons
# ─────────────────────────────────────────────────────────────────────────────

left_frame = tk.Frame(main_frame, bg='#1E1E1E',
                      width=state.disp_w, height=state.disp_h + 80)
left_frame.pack(side="left", fill="y")
left_frame.pack_propagate(False)

video_label = tk.Label(left_frame, width=state.disp_w, height=state.disp_h, bg="black")
video_label.pack()

control_frame = tk.Frame(left_frame, bg='#1E1E1E')
control_frame.pack(pady=5, fill="x")

# Button styles
# 自訂顏色和字體的按鈕樣式，讓 UI 看起來更現代化
style = ttk.Style()
try:
    style.theme_use("alt")
except Exception:
    pass

# configure 靜態樣式，map 動態交互效果
style.configure("Custom.TButton",
                font=("Arial", 15), padding=5, relief="flat",
                background="#0078D4", foreground="white")
# map是 動態行為
# active 是按下去的狀態，!disabled 是正常可點擊的狀態。這裡讓按鈕在被點擊時顏色變深一點。
style.map("Custom.TButton",
          foreground=[("active", "white"), ("!disabled", "white")],
          background=[("active", "#107C10"), ("!disabled", "#0078D4")])

style.configure("Apply.TButton",
                font=("Arial", 12), padding=2, relief="flat",
                background="#0078D4", foreground="white")
style.map("Apply.TButton",
          foreground=[("active", "white"), ("!disabled", "white")],
          background=[("active", "#107C10"), ("!disabled", "#0078D4")])

# expand 參數讓按鈕在水平方向上撐滿整個 control_frame，這樣看起來更整齊
default_btn = ttk.Button(control_frame, text="重新選取 ROI / Reselect ROI", style="Custom.TButton")
default_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")

start_btn = ttk.Button(control_frame, text="開始 / Start", style="Custom.TButton", state="disabled")
start_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")

save_btn = ttk.Button(control_frame, text="儲存 CSV / Save as CSV", style="Custom.TButton")
save_btn.pack(side="left", padx=0, pady=10, ipadx=5, ipady=4, expand=True, fill="x")


# ─────────────────────────────────────────────────────────────────────────────
# Right panel – settings
# ─────────────────────────────────────────────────────────────────────────────

right_frame = tk.Frame(main_frame, bg="#2B2B2B", width=right_w, height=state.disp_h + 80)
right_frame.pack(side="right", fill="both")
right_frame.pack_propagate(False)

tk.Label(right_frame, text="設定 / Settings",
         font=SETTINGS_LABEL_FONT, bg="#2B2B2B", fg="#00BFFF").pack(pady=(8, 4))

# ── Camera settings (Gain / Exposure) ────────────────────────────────────────
ge_frame = tk.LabelFrame(right_frame, text="相機設定 / Camera Settings",
                          padx=FRAME_PADX, pady=FRAME_PADY,
                          font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                          borderwidth=2, relief="solid")
ge_frame.pack(fill='both', padx=6, pady=4, expand=True)

tk.Label(ge_frame, text="Gain :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
gain_entry = ttk.Entry(ge_frame, width=12, font=ENTRY_FONT)
gain_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
gain_entry.insert(0, str(state.user_gain_val))

tk.Label(ge_frame, text="Exposure(ms) :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=1, column=0, sticky='w', padx=2, pady=6)
exposure_entry = ttk.Entry(ge_frame, width=12, font=ENTRY_FONT)
exposure_entry.grid(row=1, column=1, sticky='w', padx=2, pady=6)
exposure_entry.insert(0, str(state.user_exposure_ms))

# ── XIMEA Downsampling ────────────────────────────────────────────────────────
down_frame = tk.LabelFrame(right_frame, text="XIMEA Downsampling (Only for XIMEA)",
                            padx=FRAME_PADX, pady=FRAME_PADY,
                            font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                            borderwidth=2, relief="solid")
down_frame.pack(fill='both', padx=6, pady=4, expand=True)

rb1 = tk.Radiobutton(down_frame, text="1x1 (2464x2056)", variable=downsampling_var, value='1x1',
                     font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0",
                     selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb2 = tk.Radiobutton(down_frame, text="2x2 (1232x1028)", variable=downsampling_var, value='2x2',
                     font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0",
                     selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb1.pack(anchor='w', padx=6, pady=(2, 4), fill='x')
rb2.pack(anchor='w', padx=6, pady=(2, 4), fill='x')

try:
    rb1.config(state="disabled")
    rb2.config(state="disabled")
except Exception:
    pass

# ── ROI shape ─────────────────────────────────────────────────────────────────
roi_frame = tk.LabelFrame(right_frame, text="ROI 形狀 / ROI Shape",
                           padx=FRAME_PADX, pady=FRAME_PADY,
                           font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                           borderwidth=2, relief="solid")
roi_frame.pack(fill='both', padx=6, pady=4, expand=True)

roi_shape_var = tk.StringVar(value='rect')

rb_rect_ui = tk.Radiobutton(roi_frame, text="Rectangle",
                             variable=roi_shape_var, value='rect',
                             font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0",
                             selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb_circle_ui = tk.Radiobutton(roi_frame, text="Circle",
                               variable=roi_shape_var, value='circle',
                               font=RADIO_FONT, anchor="w", bg="#2B2B2B", fg="#E0E0E0",
                               selectcolor="#2B2B2B", activebackground="#2B2B2B", activeforeground="#00BFFF")
rb_rect_ui.pack(anchor='w', padx=6, pady=(2, 4), fill='x')
rb_circle_ui.pack(anchor='w', padx=6, pady=(2, 4), fill='x')

# ROI size entries
roi_size_frame = tk.Frame(roi_frame, bg="#2B2B2B")
roi_size_frame.pack(fill='x', padx=6, pady=(6, 2))

tk.Label(roi_size_frame, text="Width (px):",    font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=4)
roi_width_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_width_entry.insert(0, "50")
roi_width_entry.grid(row=0, column=1, sticky='w', padx=2, pady=4)

tk.Label(roi_size_frame, text="Height (px):",   font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0").grid(row=1, column=0, sticky='w', padx=2, pady=4)
roi_height_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_height_entry.insert(0, "50")
roi_height_entry.grid(row=1, column=1, sticky='w', padx=2, pady=4)

tk.Label(roi_size_frame, text="Diameter (px):", font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#E0E0E0").grid(row=2, column=0, sticky='w', padx=2, pady=4)
roi_diameter_entry = ttk.Entry(roi_size_frame, width=10, font=ENTRY_FONT)
roi_diameter_entry.insert(0, "50")
roi_diameter_entry.grid(row=2, column=1, sticky='w', padx=2, pady=4)

tk.Label(roi_size_frame,
         text="(設定後用滑鼠拖動放置ROI)\n(Set size, then drag to place ROI)",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888"
         ).grid(row=3, column=0, columnspan=2, sticky='w', padx=2, pady=(4, 0))

# ── Threshold ─────────────────────────────────────────────────────────────────
thr_frame = tk.LabelFrame(right_frame, text="門檻 / Threshold",
                           padx=FRAME_PADX, pady=FRAME_PADY,
                           font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                           borderwidth=2, relief="solid")
thr_frame.pack(fill='both', padx=6, pady=4, expand=True)

tk.Label(thr_frame, text="Threshold（0-255）:", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
threshold_entry = ttk.Entry(thr_frame, width=14, font=ENTRY_FONT)
threshold_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)

# ── FPS control ───────────────────────────────────────────────────────────────
fps_frame = tk.LabelFrame(right_frame, text="FPS 控制 / FPS Control",
                           padx=FRAME_PADX, pady=FRAME_PADY,
                           font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                           borderwidth=2, relief="solid")
fps_frame.pack(fill='both', padx=6, pady=4, expand=True)

tk.Label(fps_frame, text="Set FPS(integer) :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
fps_input_entry = ttk.Entry(fps_frame, width=10, font=ENTRY_FONT)
fps_input_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)

fps_display_label = tk.Label(fps_frame, text="Current FPS: 0", anchor="w",
                              font=SETTINGS_ITEM_FONT, bg="#2B2B2B", fg="#00BFFF")
fps_display_label.grid(row=1, column=0, columnspan=2, sticky='w', padx=2, pady=(6, 2))

# ── Decimal places ────────────────────────────────────────────────────────────
dec_frame = tk.LabelFrame(right_frame, text="顯示精度 / Display Precision",
                           padx=FRAME_PADX, pady=FRAME_PADY,
                           font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                           borderwidth=2, relief="solid")
dec_frame.pack(fill='both', padx=6, pady=4, expand=True)

tk.Label(dec_frame, text="Decimal places :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
dec_entry = ttk.Entry(dec_frame, width=6, font=ENTRY_FONT)
dec_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)

# ── Scale bar ─────────────────────────────────────────────────────────────────
scale_frame = tk.LabelFrame(right_frame, text="比例尺 / Scale Bar",
                             padx=FRAME_PADX, pady=FRAME_PADY,
                             font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                             borderwidth=2, relief="solid")
scale_frame.pack(fill='both', padx=6, pady=4, expand=True)

scale_enable_var = tk.BooleanVar(value=False)
tk.Checkbutton(scale_frame, text="顯示比例尺 / Show Scale Bar",
               variable=scale_enable_var, font=SETTINGS_ITEM_FONT,
               bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
               activebackground="#2B2B2B", activeforeground="#00BFFF"
               ).grid(row=0, column=0, columnspan=2, sticky='w', padx=2, pady=6)

tk.Label(scale_frame, text="像素/微米 (px/um) :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=1, column=0, sticky='w', padx=2, pady=6)
scale_entry = ttk.Entry(scale_frame, width=10, font=ENTRY_FONT)
scale_entry.grid(row=1, column=1, sticky='w', padx=2, pady=6)

tk.Label(scale_frame, text="比例尺長度 (um) :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=2, column=0, sticky='w', padx=2, pady=6)
scale_length_entry = ttk.Entry(scale_frame, width=10, font=ENTRY_FONT)
scale_length_entry.insert(0, "50")
scale_length_entry.grid(row=2, column=1, sticky='w', padx=2, pady=6)

distance_enable_var = tk.BooleanVar(value=False)
tk.Checkbutton(scale_frame, text="標示距離 / Show Distance Label",
               variable=distance_enable_var, font=SETTINGS_ITEM_FONT,
               bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
               activebackground="#2B2B2B", activeforeground="#00BFFF"
               ).grid(row=3, column=0, columnspan=2, sticky='w', padx=2, pady=6)

# ── Lens magnification ────────────────────────────────────────────────────────
lens_frame = tk.LabelFrame(right_frame, text="透鏡倍率 / Lens Magnification",
                            padx=FRAME_PADX, pady=FRAME_PADY,
                            font=SETTINGS_TYPE_FONT, bg="#2B2B2B", fg="#00BFFF",
                            borderwidth=2, relief="solid")
lens_frame.pack(fill='both', padx=6, pady=4, expand=True)

tk.Label(lens_frame, text="倍率 (Magnification) :", font=SETTINGS_ITEM_FONT,
         bg="#2B2B2B", fg="#E0E0E0").grid(row=0, column=0, sticky='w', padx=2, pady=6)
lens_entry = ttk.Entry(lens_frame, width=10, font=ENTRY_FONT)
lens_entry.insert(0, "1.0")
lens_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)

tk.Label(lens_frame,
         text="(例: 2x、5x、10x 或 1.5)\n(無透鏡時輸入 1.0)",
         font=("times new roman", 9), bg="#2B2B2B", fg="#888888"
         ).grid(row=1, column=0, columnspan=2, sticky='w', padx=2, pady=(2, 4))


# ─────────────────────────────────────────────────────────────────────────────
# Validation helper
# ─────────────────────────────────────────────────────────────────────────────


# 這些參數都有輸入值後 start 按鈕才會啟用，這樣可以避免使用者忘了填某個參數就開始偵測，導致錯誤或不預期的行為。
def validate_start_enable(event=None):
    ok = all([
        gain_entry.get().strip(),
        exposure_entry.get().strip(),
        threshold_entry.get().strip(),
        dec_entry.get().strip(),
        fps_input_entry.get().strip(),
        len(state.rois) > 0,
    ])
    start_btn.config(state="normal" if ok else "disabled")



def set_roi_shape(shape):
    state.roi_shape_choice = shape
    roi_shape_var.set(shape)
    validate_start_enable()


# ─────────────────────────────────────────────────────────────────────────────
# Gain / exposure live update
# ─────────────────────────────────────────────────────────────────────────────

def on_gain_exposure_change(event=None):
    ui_plot.append_log(
        f"[DEBUG] gain/exp change: analyzing={state.analyzing}, cam={state.cam is not None}"
    )
    if not state.analyzing or state.cam is None:
        return
    try:
        gain_text = gain_entry.get().strip()
        exp_text  = exposure_entry.get().strip()
        if gain_text and exp_text:
            gain_val = float(gain_text)
            exp_val  = float(exp_text)
            ui_plot.append_log(f"[DEBUG] applying gain={gain_val}, exp={exp_val}")
            ok_g, ok_e = camera.apply_gain_and_exposure(gain_val, exp_val)
            if ok_g:
                state.user_gain_val    = gain_val
            if ok_e:
                state.user_exposure_ms = exp_val
            ui_plot.append_log(f"[DEBUG] ok_gain={ok_g}, ok_exp={ok_e}")
    except Exception as e:
        ui_plot.append_log(f"[DEBUG] gain/exp exception: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Start / Stop / Restart detection
# ─────────────────────────────────────────────────────────────────────────────


# 當在analyzing時 這些控制的UI 要鎖住，避免使用者誤操作導致錯誤或不預期的行為。停止後再解鎖。
def _lock_ui_for_detection():
    """Disable all input widgets while detection is running."""
    for w in (threshold_entry, gain_entry, exposure_entry, dec_entry, fps_input_entry):
        w.config(state="disabled")
    for w in (rb_rect_ui, rb_circle_ui):
        w.config(state="disabled")
    default_btn.state(["disabled"])
    if state.CAMERA_TYPE == "XIMEA":
        try:
            rb1.config(state="disabled")
            rb2.config(state="disabled")
        except Exception:
            pass
    start_btn.config(text="停止 / Stop")


def _unlock_ui_after_detection():
    """Re-enable all input widgets after detection stops."""
    for w in (threshold_entry, gain_entry, exposure_entry, dec_entry, fps_input_entry):
        w.config(state="normal")
    for w in (rb_rect_ui, rb_circle_ui):
        w.config(state="normal")
    default_btn.state(["!disabled"])
    try:
        if state.CAMERA_TYPE == "XIMEA":
            rb1.config(state="normal")
            rb2.config(state="normal")
        else:
            rb1.config(state="disabled")
            rb2.config(state="disabled")
    except Exception:
        pass


def start_button_handler():
    """Validate settings, confirm with user, then start analysis loop."""
    # Validate entries
    if not all([gain_entry.get().strip(), exposure_entry.get().strip(),
                threshold_entry.get().strip(), dec_entry.get().strip(),
                fps_input_entry.get().strip()]):
        messagebox.showwarning(
            "設定未填齊 / Missing settings",
            "請確認 Gain、Exposure、Threshold、Decimal places 與 FPS 都已填寫。\n"
            "Please ensure Gain, Exposure, Threshold, Decimal places and FPS are filled."
        )
        return

    try:
        fps_val = int(fps_input_entry.get().strip())
        if fps_val <= 0:
            raise ValueError
    except Exception:
        messagebox.showwarning("FPS 格式錯誤 / Invalid FPS",
                               "FPS 必須為大於 0 的整數。\nFPS must be a positive integer.")
        return

    try:
        dec_v = int(dec_entry.get().strip())
        if not 0 <= dec_v <= 10:
            raise ValueError
    except Exception:
        messagebox.showwarning("小數位錯誤 / Invalid decimal places",
                               "請輸入 0~10 的整數。\nPlease enter an integer 0~10.")
        return

    try:
        thr_v = float(threshold_entry.get().strip())
        if not 0 <= thr_v <= 255:
            raise ValueError
    except Exception:
        messagebox.showwarning("門檻值錯誤 / Invalid Threshold",
                               "Threshold 必須在 0~255。\nThreshold must be between 0 and 255.")
        return

    try:
        gain_v = float(gain_entry.get().strip())
    except Exception:
        messagebox.showwarning("Gain 格式錯誤 / Invalid Gain",
                               "Gain 必須為數字。\nGain must be a number.")
        return

    try:
        exp_v = float(exposure_entry.get().strip())
    except Exception:
        messagebox.showwarning("Exposure 格式錯誤 / Invalid Exposure",
                               "Exposure 必須為數字。\nExposure must be a number.")
        return

    if not state.rois:
        messagebox.showwarning("未選取 ROI / No ROI",
                               "請至少選取一個 ROI。\nPlease select at least one ROI.")
        return

    # Confirm summary dialog
    summary = [
        f"Gain: {gain_v}",
        f"Exposure（ms）: {exp_v}",
        f"Threshold: {thr_v}",
        f"Decimal places: {dec_v}",
        f"FPS setting: {fps_val}",
    ]
    if state.CAMERA_TYPE == "XIMEA":
        ds = downsampling_var.get()
        summary.append(f"XIMEA Downsampling: {'1x1 (2464x2056)' if ds == '1x1' else '2x2 (1232x1028)'}")
    summary += ["", "請確認以上設定再開始偵測。\nPlease confirm the settings before starting."]
    if not messagebox.askokcancel("確認設定 / Confirm settings", "\n".join(summary)):
        return

    # Apply settings to state
    # 預設的數值會在相機初始化時寫入 state.user_gain_val 和 state.user_exposure_ms，使用者修改後再覆蓋這兩個值。這樣在 Restart 時就能回到預設值。
    state.user_gain_val    = gain_v
    state.user_exposure_ms = exp_v
    state.threshold_value  = thr_v
    state.decimal_places   = dec_v
    state.user_fps_val     = fps_val
    state.settings_applied = True
    state.roi_locked       = True

    camera.apply_gain_and_exposure(gain_v, exp_v)
    _lock_ui_for_detection()

    # 開始進行analysis_loop前先初始化 plot area
    # 這樣分析執行緒裡就可以直接呼叫 ui_plot.update_plots() 來更新畫面，而不需要擔心 plot_win 還沒建立的問題。
    state.analyzing = True
    # initialize_plot_area 會建立一個新的視窗來顯示 ROI 強度的變化趨勢圖
    ui_plot.initialize_plot_area(
        len(state.rois), root,
        # 並且在視窗關閉時呼叫 confirm_close_plot 來確認是否要停止偵測。
        lambda: ui_plot.confirm_close_plot(start_btn, default_btn)
    )
    # analysis_loop 是一個無限循環的函式，裡面會不斷讀取相機影像、計算 ROI 強度、更新 plot 和 log。
    # 為了不阻塞主程式的 UI，我們把它放在一個獨立的執行緒裡跑。
    threading.Thread(
        target=analysis.analysis_loop,

        args=(ui_plot.update_plots, ui_plot.append_log),
        # daemon=True 讓這個分析執行緒在主程式結束時自動終止，避免程式關閉後還有背景執行緒在跑。
        daemon=True
    ).start()


def on_start():
    """Toggle between Start → Stop → Restart."""
    txt = start_btn["text"]
    if txt.startswith("開始") or txt.startswith("Start"):
        start_button_handler()

    elif txt.startswith("停止") or txt.startswith("Stop"):
        state.analyzing = False
        start_btn["text"] = "重新啟動偵測 / Restart Detection"

    else:   # Restart Detection
        if state.plot_win:
            if not messagebox.askokcancel(
                "確認重新開始 / Confirm restart",
                "確定要清空資料並重新偵測嗎？\nAre you sure you want to clear data and restart detection?"
            ):
                return
            try:
                state.plot_win.destroy()
            except Exception:
                pass

        # Reset state
        state.rois.clear()
        state.roi_data.clear()
        state.timestamps.clear()
        state.roi_selected   = False
        state.roi_locked     = False
        state.threshold_value = None
        state.user_gain_val   = None
        state.user_exposure_ms = None
        state.decimal_places  = None
        state.user_fps_val    = None
        state.settings_applied = False

        _unlock_ui_after_detection()

        # Reset entry values
        threshold_entry.delete(0, tk.END)
        gain_entry.delete(0, tk.END);     gain_entry.insert(0, "0.0")
        exposure_entry.delete(0, tk.END); exposure_entry.insert(0, "10.0")
        dec_entry.delete(0, tk.END)
        fps_input_entry.delete(0, tk.END)

        camera.apply_defaults_on_restart(downsampling_var)
        start_btn["text"] = "開始 / Start"
        start_btn.config(state="disabled")
        messagebox.showinfo(
            "已重置 / Restarted",
            "已清空資料並重置設定，可重新設定並選取 ROI。\nData cleared and settings reset."
        )


def on_default():
    """Reselect ROI – clear all ROIs."""
    if state.roi_locked:
        messagebox.showinfo("ROI 已鎖定 / ROI Locked",
                            "請先 Restart 才能重新選取 ROI。\nROI is locked; restart to reselect.")
        return
    state.rois.clear()
    state.roi_data.clear()
    state.timestamps.clear()
    state.roi_selected = False
    validate_start_enable()


# ─────────────────────────────────────────────────────────────────────────────
# Camera selection dialog
# ─────────────────────────────────────────────────────────────────────────────

def ask_camera_choice_and_init():
    choice_win = tk.Toplevel(root)
    choice_win.resizable(False, False)
    choice_win.title("選擇相機 / Choose Camera")
    choice_win.grab_set()
    choice_win.configure(bg="#2B2B2B")

    tk.Label(choice_win,
             text="請選擇欲使用的相機 / Please choose camera:",
             font=("Arial", 12), bg="#2B2B2B", fg="#00BFFF").pack(padx=10, pady=10)

    var = tk.StringVar(value="XIMEA")

    tk.Radiobutton(choice_win, text="XIMEA",    variable=var, value="XIMEA",
                   bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
                   activebackground="#2B2B2B", activeforeground="#00BFFF"
                   ).pack(anchor="w", padx=20, pady=5)
    tk.Radiobutton(choice_win, text="THORLABS", variable=var, value="THORLABS",
                   bg="#2B2B2B", fg="#E0E0E0", selectcolor="#2B2B2B",
                   activebackground="#2B2B2B", activeforeground="#00BFFF"
                   ).pack(anchor="w", padx=20, pady=5)

    status_label = tk.Label(choice_win,
                            text="選擇後按 Initialize 以啟動相機 / Click 'Initialize' to start camera",
                            fg="#888888", bg="#2B2B2B")
    status_label.pack(pady=(5, 10))

    def on_init():
        choice = var.get()
        try:
            if choice == "XIMEA":
                try:
                    rb1.config(state="normal");  rb2.config(state="normal")
                except Exception:
                    pass
                camera.init_camera_ximea(downsampling_var, scale_entry)
            else:
                try:
                    rb1.config(state="disabled"); rb2.config(state="disabled")
                except Exception:
                    pass
                camera.init_camera_thorlabs(scale_entry, scale_enable_var)

            state.CAMERA_TYPE = choice
            status_label.config(
                text=f"{choice} 已成功初始化。 / {choice} initialized successfully.",
                fg="#107C10"
            )
            # Reflect camera type in downsampling buttons
            try:
                if choice == "XIMEA":
                    rb1.config(state="normal");  rb2.config(state="normal")
                else:
                    rb1.config(state="disabled"); rb2.config(state="disabled")
            except Exception:
                pass
            choice_win.grab_release()
            choice_win.destroy()
        except Exception as e:
            status_label.config(text=f"初始化失敗: {e}", fg="#FF4444")
            messagebox.showerror("相機初始化錯誤 / Camera Init Error", str(e))

    ttk.Button(choice_win, text="初始化 / Initialize", command=on_init).pack(pady=(0, 10))
    root.wait_window(choice_win)


def on_close():
    if messagebox.askokcancel("退出程式 / Exit Program",
                              "確定要退出程式嗎？\nAre you sure you want to exit?"):
        state.running   = False
        state.analyzing = False
        camera.release_camera()
        root.destroy()


def start_system():
    try:
        ask_camera_choice_and_init()
    except Exception as e:
        messagebox.showerror("初始化錯誤 / Initialization Error", f"初始化過程發生錯誤: {e}")
        return

    if state.CAMERA_TYPE is None:
        messagebox.showerror("未選擇相機 / No Camera",
                             "未選擇或無法初始化相機，程式將退出。\n"
                             "No camera selected or failed to initialize.")
        root.destroy()
        return

    loop_fn = camera.video_loop_ximea if state.CAMERA_TYPE == "XIMEA" else camera.video_loop_thorlabs
    threading.Thread(target=loop_fn, daemon=True).start()

    ui_display.update_display(
        root, video_label, fps_display_label,
        scale_enable_var, scale_entry, scale_length_entry,
        distance_enable_var, lens_entry, roi_shape_var
    )


# ─────────────────────────────────────────────────────────────────────────────
# Wire events
# ─────────────────────────────────────────────────────────────────────────────

# Validate on any key release in any settings field
for _w in (gain_entry, exposure_entry, threshold_entry, dec_entry,
           fps_input_entry, roi_width_entry, roi_height_entry, roi_diameter_entry):
    _w.bind("<KeyRelease>", validate_start_enable)

gain_entry.bind("<FocusOut>",     on_gain_exposure_change)
exposure_entry.bind("<FocusOut>", on_gain_exposure_change)

rb_rect_ui.config(command=lambda:   (set_roi_shape('rect'),   validate_start_enable()))
rb_circle_ui.config(command=lambda: (set_roi_shape('circle'), validate_start_enable()))
fps_input_entry.bind("<KeyRelease>", validate_start_enable)

# Mouse bindings for ROI placement / movement
video_label.bind("<ButtonPress-1>",   lambda e: roi_events.on_mouse_down(
    e, roi_shape_var, roi_width_entry, roi_height_entry, roi_diameter_entry))
video_label.bind("<B1-Motion>",       lambda e: roi_events.on_mouse_move(e))
video_label.bind("<ButtonRelease-1>", lambda e: roi_events.on_mouse_up(e, roi_shape_var, validate_start_enable))
video_label.bind("<ButtonPress-3>",   lambda e: roi_events.on_right_mouse_down(e))
video_label.bind("<B3-Motion>",       lambda e: roi_events.on_right_mouse_move(e))
video_label.bind("<ButtonRelease-3>", lambda e: roi_events.on_right_mouse_up(e))

start_btn.config(command=on_start)
default_btn.config(command=on_default)
save_btn.config(command=lambda: analysis.save_csv(messagebox.showwarning, messagebox.showinfo))

root.protocol("WM_DELETE_WINDOW", on_close)

# ─────────────────────────────────────────────────────────────────────────────
# Launch
# ─────────────────────────────────────────────────────────────────────────────

threading.Thread(target=start_system, daemon=True).start()
validate_start_enable()
root.mainloop()

# Post-mainloop cleanup
state.running   = False
state.analyzing = False
import time; time.sleep(0.1)
camera.release_camera()
print("相機已停止並釋放資源。\nCamera stopped and resources released.")
