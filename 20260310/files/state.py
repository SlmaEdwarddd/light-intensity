"""
state.py
--------
All shared global variables for the Light Intensity Detection app.
Every other module imports from here — never store shared state elsewhere.
"""

import threading
import time

# ── ROI data ──────────────────────────────────────────────────────────────────
rois        = []    # ('rect', x1,y1,x2,y2) or ('circle', cx,cy,r)
roi_data    = []    # list of per-ROI value lists
timestamps  = []

roi_selected     = False
roi_locked       = False
roi_shape_choice = 'rect'   # 'rect' | 'circle'

roi_fixed_width      = 50   # px – rectangle
roi_fixed_height     = 50   # px – rectangle
roi_fixed_diameter   = 50   # px – circle
roi_dragging_offset_x = 0
roi_dragging_offset_y = 0

# ── Mouse drag ────────────────────────────────────────────────────────────────
start_x = start_y = end_x = end_y = 0
dragging = False

right_dragging           = False
right_drag_roi_index     = -1
right_drag_start_x       = 0
right_drag_start_y       = 0
right_drag_roi_start_pos = None

# ── Camera ────────────────────────────────────────────────────────────────────
CAMERA_TYPE = None      # "XIMEA" | "THORLABS"
cam         = None
xi_img      = None
bit_depth   = 8
orig_w = orig_h = 0

# ── Frame / FPS ───────────────────────────────────────────────────────────────
current_frame     = None
frame_lock        = threading.Lock()
running           = True
analyzing         = False
valid_frame_count = 0
last_sec_time     = int(time.time())
fps_value         = 0

# ── Settings ──────────────────────────────────────────────────────────────────
user_gain_val    = 0.0
user_exposure_ms = 10.0   # ms
user_fps_val     = None
threshold_value  = None
decimal_places   = None

gain_locked      = False
exposure_locked  = False
fps_locked       = False
decimal_locked   = False
settings_applied = False

# ── Scale bar / optics ────────────────────────────────────────────────────────
pixel_size_um       = None
show_scale_bar      = False
scale_bar_length_um = 50.0
show_distance_label = False
lens_magnification  = 1.0

# ── Display geometry ──────────────────────────────────────────────────────────
disp_w, disp_h = 1280, 920

# ── Plot / log ────────────────────────────────────────────────────────────────
plot_win         = None
log_text_widget  = None
plot_canvases    = []
plot_axes        = []
plot_figures     = []
canvas_frame     = None
scrollable_frame = None
text_follow      = True   # auto-scroll log to bottom
