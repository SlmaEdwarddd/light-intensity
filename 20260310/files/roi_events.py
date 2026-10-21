"""
roi_events.py
-------------
All mouse-event handlers for placing, previewing, and repositioning ROIs on
the video_label canvas.

Left-click drag  → place a new fixed-size ROI
Right-click drag → move an existing ROI
"""

from tkinter import messagebox

import state


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_roi_at_point(x, y):
    """Return the index of the ROI containing (x, y), or -1."""
    for idx, roi in enumerate(state.rois):
        if roi[0] == 'rect':
            _, x1, y1, x2, y2 = roi
            if x1 <= x <= x2 and y1 <= y <= y2:
                return idx
        elif roi[0] == 'circle':
            _, cx, cy, r = roi
            if ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 <= r:
                return idx
    return -1


# ─────────────────────────────────────────────────────────────────────────────
# Left-button – place ROI
# ─────────────────────────────────────────────────────────────────────────────

def on_mouse_down(event, roi_shape_var,
                  roi_width_entry, roi_height_entry, roi_diameter_entry):
    if state.analyzing or state.roi_locked:
        return

    try:
        if roi_shape_var.get() == 'rect':
            state.roi_fixed_width  = int(roi_width_entry.get())
            state.roi_fixed_height = int(roi_height_entry.get())
            if state.roi_fixed_width <= 0 or state.roi_fixed_height <= 0:
                messagebox.showwarning(
                    "無效輸入 / Invalid Input",
                    "寬度和高度必須大於0。\nWidth and height must be > 0."
                )
                return
        else:
            state.roi_fixed_diameter = int(roi_diameter_entry.get())
            if state.roi_fixed_diameter <= 0:
                messagebox.showwarning(
                    "無效輸入 / Invalid Input",
                    "直徑必須大於0。\nDiameter must be > 0."
                )
                return
    except ValueError:
        messagebox.showwarning(
            "無效輸入 / Invalid Input",
            "請輸入有效的數字。\nPlease enter valid numbers."
        )
        return

    state.start_x = event.x
    state.start_y = event.y
    state.dragging = True
    state.roi_dragging_offset_x = 0
    state.roi_dragging_offset_y = 0


def on_mouse_move(event):
    if state.dragging:
        state.roi_dragging_offset_x = event.x - state.start_x
        state.roi_dragging_offset_y = event.y - state.start_y


def on_mouse_up(event, roi_shape_var, validate_cb):
    if not state.dragging:
        return
    state.dragging = False

    try:
        if roi_shape_var.get() == 'rect':
            x1 = max(0, min(state.disp_w - state.roi_fixed_width,  state.start_x))
            y1 = max(0, min(state.disp_h - state.roi_fixed_height, state.start_y))
            state.rois.append(('rect', x1, y1, x1 + state.roi_fixed_width, y1 + state.roi_fixed_height))
        else:
            r  = state.roi_fixed_diameter // 2
            cx = max(r, min(state.disp_w - r, state.start_x))
            cy = max(r, min(state.disp_h - r, state.start_y))
            state.rois.append(('circle', cx, cy, r))
        state.roi_selected = True
    except Exception as e:
        messagebox.showerror(
            "錯誤 / Error",
            f"建立ROI時發生錯誤：{e}\nError creating ROI: {e}"
        )
        return

    validate_cb()


# ─────────────────────────────────────────────────────────────────────────────
# Right-button – move existing ROI
# ─────────────────────────────────────────────────────────────────────────────

def on_right_mouse_down(event):
    if state.analyzing or state.roi_locked or not state.rois:
        return
    idx = get_roi_at_point(event.x, event.y)
    if idx >= 0:
        state.right_dragging           = True
        state.right_drag_roi_index     = idx
        state.right_drag_start_x       = event.x
        state.right_drag_start_y       = event.y
        state.right_drag_roi_start_pos = state.rois[idx]


def on_right_mouse_move(event):
    if not (state.right_dragging
            and 0 <= state.right_drag_roi_index < len(state.rois)):
        return

    dx = event.x - state.right_drag_start_x
    dy = event.y - state.right_drag_start_y
    roi = state.right_drag_roi_start_pos

    try:
        if roi[0] == 'rect':
            _, x1, y1, x2, y2 = roi
            w, h = x2 - x1, y2 - y1
            nx1 = max(0, x1 + dx);  nx2 = nx1 + w
            ny1 = max(0, y1 + dy);  ny2 = ny1 + h
            if nx2 > state.disp_w:
                nx2 = state.disp_w;  nx1 = nx2 - w
            if ny2 > state.disp_h:
                ny2 = state.disp_h;  ny1 = ny2 - h
            state.rois[state.right_drag_roi_index] = ('rect', nx1, ny1, nx2, ny2)

        elif roi[0] == 'circle':
            _, cx, cy, r = roi
            ncx = max(r, min(state.disp_w - r, cx + dx))
            ncy = max(r, min(state.disp_h - r, cy + dy))
            state.rois[state.right_drag_roi_index] = ('circle', ncx, ncy, r)
    except Exception:
        pass


def on_right_mouse_up(event):
    state.right_dragging           = False
    state.right_drag_roi_index     = -1
    state.right_drag_roi_start_pos = None
