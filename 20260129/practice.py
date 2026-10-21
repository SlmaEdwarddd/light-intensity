import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import numpy as np

# ============= 全局變數 =============
root = tk.Tk()
root.title("光強度偵測 / Light Intensity Detection")
root['bg'] = '#1E1E1E'

# ============= 字體設定 =============
SETTINGS_LABEL_FONT = ("times new roman", 18, "bold")
SETTINGS_TYPE_FONT = ("times new roman", 12, "bold")
SETTINGS_ITEM_FONT = ("times new roman", 12)
ENTRY_FONT = ("times new roman", 12)
FRAME_PADX = 8
FRAME_PADY = 6

# ============= UI 創建 =============
# 主容器：分成左右兩部分
main_frame = tk.Frame(root, bg='#1E1E1E')
main_frame.pack(fill='both', expand=True, padx=4, pady=4)

# ===== 左側：視頻顯示區域 =====
left_frame = tk.Frame(main_frame, bg='#2B2B2B', relief='solid', borderwidth=2)
left_frame.pack(side='left', fill='both', expand=True, padx=(0, 4))

video_label = tk.Label(left_frame, text="視頻顯示區域\n(Video Display Area)", 
                       font=("Arial", 20), bg='#1E1E1E', fg='#888888')
video_label.pack(fill='both', expand=True, padx=10, pady=10)

# ===== 右側：設置面板 =====
right_frame = tk.Frame(main_frame, bg='#1E1E1E')
right_frame.pack(side='right', fill='y', padx=4)

# 標題
title_label = tk.Label(right_frame, text="相機設定\nCamera Settings", 
                       font=SETTINGS_LABEL_FONT, bg='#1E1E1E', fg='#00BFFF')
title_label.pack(pady=10)

# ===== 相機選擇 =====
camera_frame = tk.LabelFrame(right_frame, text="相機選擇 / Camera Type", 
                              padx=FRAME_PADX, pady=FRAME_PADY, 
                              font=SETTINGS_TYPE_FONT, bg='#2B2B2B', fg='#00BFFF', 
                              borderwidth=2, relief='solid')
camera_frame.pack(fill='x', padx=6, pady=4)

camera_var = tk.StringVar(value='XIMEA')
rb_ximea = ttk.Radiobutton(camera_frame, text='XIMEA', variable=camera_var, value='XIMEA')
rb_ximea.pack(anchor='w', padx=4, pady=2)

rb_thorlabs = ttk.Radiobutton(camera_frame, text='Thorlabs', variable=camera_var, value='Thorlabs')
rb_thorlabs.pack(anchor='w', padx=4, pady=2)

# ===== 相機參數：Gain 和 Exposure =====
ge_frame = tk.LabelFrame(right_frame, text="相機參數 / Camera Parameters", 
                         padx=FRAME_PADX, pady=FRAME_PADY, 
                         font=SETTINGS_TYPE_FONT, bg='#2B2B2B', fg='#00BFFF', 
                         borderwidth=2, relief='solid')
ge_frame.pack(fill='x', padx=6, pady=4)

# Gain
gain_label = tk.Label(ge_frame, text="Gain :", font=SETTINGS_ITEM_FONT, 
                      bg='#2B2B2B', fg='#E0E0E0')
gain_label.grid(row=0, column=0, sticky='w', padx=2, pady=6)

gain_entry = ttk.Entry(ge_frame, width=12, font=ENTRY_FONT)
gain_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
gain_entry.insert(0, "0.0")

# Exposure
exp_label = tk.Label(ge_frame, text="Exposure(ms) :", font=SETTINGS_ITEM_FONT, 
                     bg='#2B2B2B', fg='#E0E0E0')
exp_label.grid(row=1, column=0, sticky='w', padx=2, pady=6)

exposure_entry = ttk.Entry(ge_frame, width=12, font=ENTRY_FONT)
exposure_entry.grid(row=1, column=1, sticky='w', padx=2, pady=6)
exposure_entry.insert(0, "10.0")

# ===== ROI 設定 =====
roi_frame = tk.LabelFrame(right_frame,  ext="ROI 設定 / ROI Settings", 
                          padx=FRAME_PADX, pady=FRAME_PADY, 
                          font=SETTINGS_TYPE_FONT, bg='#2B2B2B', fg='#00BFFF', 
                          borderwidth=2, relief='solid')
roi_frame.pack(fill='x', padx=6, pady=4)

# ROI 形狀選擇
roi_shape_var = tk.StringVar(value='rect')
rb_rect = ttk.Radiobutton(roi_frame, text='Rectangle (矩形)', variable=roi_shape_var, value='rect')
rb_rect.pack(anchor='w', padx=4, pady=2)

rb_circle = ttk.Radiobutton(roi_frame, text='Circle (圓形)', variable=roi_shape_var, value='circle')
rb_circle.pack(anchor='w', padx=4, pady=2)

# ROI 參數容器（使用 grid 佈局）
roi_param_frame = tk.Frame(roi_frame, bg='#2B2B2B')
roi_param_frame.pack(fill='x', padx=2, pady=4)

# ROI 寬度（矩形用）
roi_width_label = tk.Label(roi_param_frame, text="Width(px) :", font=SETTINGS_ITEM_FONT, 
                           bg='#2B2B2B', fg='#E0E0E0')
roi_width_label.grid(row=0, column=0, sticky='w', padx=2, pady=4)

roi_width_entry = ttk.Entry(roi_param_frame, width=12, font=ENTRY_FONT)
roi_width_entry.grid(row=0, column=1, sticky='w', padx=2, pady=4)
roi_width_entry.insert(0, "50")

# ROI 高度（矩形用）
roi_height_label = tk.Label(roi_param_frame, text="Height(px) :", font=SETTINGS_ITEM_FONT, 
                            bg='#2B2B2B', fg='#E0E0E0')
roi_height_label.grid(row=1, column=0, sticky='w', padx=2, pady=4)

roi_height_entry = ttk.Entry(roi_param_frame, width=12, font=ENTRY_FONT)
roi_height_entry.grid(row=1, column=1, sticky='w', padx=2, pady=4)
roi_height_entry.insert(0, "50")

# ===== 閾值和其他參數 =====
param_frame = tk.LabelFrame(right_frame, text="分析參數 / Analysis Parameters", 
                            padx=FRAME_PADX, pady=FRAME_PADY, 
                            font=SETTINGS_TYPE_FONT, bg='#2B2B2B', fg='#00BFFF', 
                            borderwidth=2, relief='solid')
param_frame.pack(fill='x', padx=6, pady=4)

# Threshold
thr_label = tk.Label(param_frame, text="Threshold :", font=SETTINGS_ITEM_FONT, 
                     bg='#2B2B2B', fg='#E0E0E0')
thr_label.grid(row=0, column=0, sticky='w', padx=2, pady=6)

threshold_entry = ttk.Entry(param_frame, width=12, font=ENTRY_FONT)
threshold_entry.grid(row=0, column=1, sticky='w', padx=2, pady=6)
threshold_entry.insert(0, "100")

# Decimal Places
dec_label = tk.Label(param_frame, text="Decimal Places :", font=SETTINGS_ITEM_FONT, 
                     bg='#2B2B2B', fg='#E0E0E0')
dec_label.grid(row=1, column=0, sticky='w', padx=2, pady=6)

dec_entry = ttk.Entry(param_frame, width=12, font=ENTRY_FONT)
dec_entry.grid(row=1, column=1, sticky='w', padx=2, pady=6)
dec_entry.insert(0, "2")

# FPS
fps_label = tk.Label(param_frame, text="FPS :", font=SETTINGS_ITEM_FONT, 
                    bg='#2B2B2B', fg='#E0E0E0')
fps_label.grid(row=2, column=0, sticky='w', padx=2, pady=6)

fps_entry = ttk.Entry(param_frame, width=12, font=ENTRY_FONT)
fps_entry.grid(row=2, column=1, sticky='w', padx=2, pady=6)
fps_entry.insert(0, "30")

# ===== 控制按鈕 =====
button_frame = tk.Frame(right_frame, bg='#1E1E1E')
button_frame.pack(fill='x', padx=6, pady=8)

start_btn = ttk.Button(button_frame, text="開始 / Start", 
                       command=lambda: messagebox.showinfo("提示", "Start 按鈕被點擊"))
start_btn.pack(side='left', padx=4)

stop_btn = ttk.Button(button_frame, text="停止 / Stop", 
                      command=lambda: messagebox.showinfo("提示", "Stop 按鈕被點擊"))
stop_btn.pack(side='left', padx=4)

# 狀態標籤
status_label = tk.Label(right_frame, text="Status: Ready", 
                        font=("Arial", 10), bg='#1E1E1E', fg='#00FF00')
status_label.pack(pady=4)

# FPS 顯示
fps_display = tk.Label(right_frame, text="FPS: 0", 
                       font=("Arial", 10), bg='#1E1E1E', fg='#FFD700')
fps_display.pack(pady=4)

# ===== 底部：日誌區域 =====
log_frame = tk.LabelFrame(root, text="日誌 / Log", 
                          font=SETTINGS_TYPE_FONT, bg='#1E1E1E', fg='#00BFFF', 
                          borderwidth=2, relief='solid')
log_frame.pack(fill='x', padx=4, pady=4)

log_text = tk.Text(log_frame, height=8, font=("Courier", 10), 
                   bg='#2B2B2B', fg='#00FF00', state='disabled')
log_text.pack(fill='both', expand=True, padx=4, pady=4)

# 日誌滾動條
scrollbar = ttk.Scrollbar(log_frame, command=log_text.yview)
log_text.config(yscrollcommand=scrollbar.set)

# ===== 主函數 =====
def append_log(text):
    """添加日誌信息"""
    log_text.config(state='normal')
    log_text.insert(tk.END, text + '\n')
    log_text.see(tk.END)
    log_text.config(state='disabled')

def on_start():
    """開始按鈕事件"""
    camera = camera_var.get()
    gain = gain_entry.get()
    exposure = exposure_entry.get()
    threshold = threshold_entry.get()
    decimal = dec_entry.get()
    fps = fps_entry.get()
    
    append_log(f"[INFO] 啟動偵測")
    append_log(f"  - 相機: {camera}")
    append_log(f"  - Gain: {gain}")
    append_log(f"  - Exposure: {exposure} ms")
    append_log(f"  - Threshold: {threshold}")
    append_log(f"  - Decimal Places: {decimal}")
    append_log(f"  - FPS: {fps}")
    status_label.config(text="Status: Running", fg='#00FF00')

def on_stop():
    """停止按鈕事件"""
    append_log(f"[INFO] 停止偵測")
    status_label.config(text="Status: Stopped", fg='#FF0000')

# 更新按鈕事件
start_btn.config(command=on_start)
stop_btn.config(command=on_stop)

# ===== 設置窗口大小 =====
root.geometry("1680x960")

# ===== 主迴圈 =====
if __name__ == "__main__":
    append_log("[INFO] 程序已啟動")
    append_log("[INFO] 請選擇相機並填寫參數")
    root.mainloop()