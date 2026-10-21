"""
ui_display.py
-------------
update_display() – the main Tkinter after-loop that reads state.current_frame,
overlays ROI shapes, scale bar, drag previews, and shows it in video_label.

Call update_display() once after the camera thread has started; it re-schedules
itself every 30 ms via root.after().
"""

import cv2
import numpy as np
from PIL import Image, ImageTk

import state


def update_display(root, video_label, fps_display_label,
                   scale_enable_var, scale_entry, scale_length_entry,
                   distance_enable_var, lens_entry, roi_shape_var):
    """
    Render one frame to video_label, then schedule the next call.

    All widget references are passed as parameters so this module stays
    free of direct global UI references.
    """
    with state.frame_lock:
        frame = state.current_frame if state.current_frame is not None else None

    if frame is not None:
        # Convert to RGB for display
        if frame.ndim == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        display_frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

        # ── Update scale / lens globals ───────────────────────────────────────
        _update_scale_state(scale_enable_var, scale_entry,
                            scale_length_entry, distance_enable_var, lens_entry)

        # ── Draw committed ROIs ───────────────────────────────────────────────
        for i, r in enumerate(state.rois):
            _draw_roi(display_frame, r, i)

        # ── Left-drag preview (placing a new ROI) ─────────────────────────────
        if state.dragging:
            _draw_drag_preview(display_frame, roi_shape_var)

        # ── Right-drag preview (moving an existing ROI) ───────────────────────
        if (state.right_dragging
                and 0 <= state.right_drag_roi_index < len(state.rois)):
            _draw_move_preview(display_frame)

        # ── Scale bar ─────────────────────────────────────────────────────────
        if state.show_scale_bar and state.pixel_size_um:
            _draw_scale_bar(display_frame)

        # Push to label
        img_tk = ImageTk.PhotoImage(Image.fromarray(display_frame))
        video_label.imgtk = img_tk
        video_label.configure(image=img_tk)

    fps_display_label.config(text=f"Current FPS : {int(state.fps_value)}")
    root.after(30, lambda: update_display(
        root, video_label, fps_display_label,
        scale_enable_var, scale_entry, scale_length_entry,
        distance_enable_var, lens_entry, roi_shape_var
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _update_scale_state(scale_enable_var, scale_entry,
                        scale_length_entry, distance_enable_var, lens_entry):
    try:
        lens_val = lens_entry.get().strip()
        try:
            state.lens_magnification = max(1e-9, float(lens_val)) if lens_val else 1.0
        except ValueError:
            state.lens_magnification = 1.0

        if scale_enable_var.get() and scale_entry.get().strip():
            try:
                base_px = float(scale_entry.get().strip())
                state.pixel_size_um  = base_px / state.lens_magnification
                state.show_scale_bar = True
            except ValueError:
                state.show_scale_bar = False
                state.pixel_size_um  = None
        else:
            state.show_scale_bar = False
            state.pixel_size_um  = None

        if scale_length_entry.get().strip():
            try:
                state.scale_bar_length_um = float(scale_length_entry.get().strip())
            except ValueError:
                pass

        state.show_distance_label = distance_enable_var.get()
    except Exception:
        state.show_scale_bar      = False
        state.show_distance_label = False
        state.lens_magnification  = 1.0


def _draw_roi(display_frame, r, idx):
    kind = r[0]
    colour = (255, 255, 255)

    if kind == 'rect':
        _, x1, y1, x2, y2 = r
        cv2.rectangle(display_frame, (x1, y1), (x2, y2), colour, 2)
        _put_label(display_frame, f"Sample {idx+1}", x1, max(20, y1 - 15))

        if state.show_distance_label and state.pixel_size_um:
            w_um = (x2 - x1) * state.pixel_size_um
            h_um = (y2 - y1) * state.pixel_size_um
            txt = (f"W:{w_um:.1f}um H:{h_um:.1f}um ({state.lens_magnification:g}x)"
                   if state.lens_magnification != 1.0
                   else f"W:{w_um:.1f}um H:{h_um:.1f}um")
            _put_label(display_frame, txt, x1,
                       min(display_frame.shape[0] - 5, y2 + 20),
                       colour=(0, 255, 0), scale=0.7)

    elif kind == 'circle':
        _, cx, cy, rad = r
        cv2.circle(display_frame, (int(cx), int(cy)), int(rad), colour, 2)
        _put_label(display_frame, f"Sample {idx+1}",
                   int(cx - rad), max(20, int(cy - rad - 15)))

        if state.show_distance_label and state.pixel_size_um:
            d_um = 2 * rad * state.pixel_size_um
            txt = (f"Diameter:{d_um:.1f}um ({state.lens_magnification:g}x)"
                   if state.lens_magnification != 1.0
                   else f"Diameter:{d_um:.1f}um")
            _put_label(display_frame, txt,
                       int(cx - rad),
                       min(display_frame.shape[0] - 5, int(cy + rad + 20)),
                       colour=(0, 255, 0), scale=0.7)


def _draw_drag_preview(display_frame, roi_shape_var):
    try:
        if roi_shape_var.get() == 'rect':
            w, h = state.roi_fixed_width, state.roi_fixed_height
            x1 = max(0, min(state.disp_w - w, state.start_x))
            y1 = max(0, min(state.disp_h - h, state.start_y))
            cv2.rectangle(display_frame, (x1, y1), (x1 + w, y1 + h), (200, 200, 200), 1)
            _put_label(display_frame, f"{w}x{h}px", max(0, x1), max(15, y1 - 5),
                       colour=(200, 200, 200), scale=0.6, thickness=1)
        else:
            r  = state.roi_fixed_diameter // 2
            cx = max(r, min(state.disp_w - r, state.start_x))
            cy = max(r, min(state.disp_h - r, state.start_y))
            cv2.circle(display_frame, (cx, cy), r, (200, 200, 200), 1)
            _put_label(display_frame, f"Ø{state.roi_fixed_diameter}px",
                       max(0, cx - r), max(15, cy - r - 5),
                       colour=(200, 200, 200), scale=0.6, thickness=1)
    except Exception:
        pass


def _draw_move_preview(display_frame):
    try:
        roi = state.rois[state.right_drag_roi_index]
        c   = (100, 200, 255)
        if roi[0] == 'rect':
            _, x1, y1, x2, y2 = roi
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), c, 2)
            _put_label(display_frame, "Moving...", max(0, x1), max(15, y1 - 15),
                       colour=c, scale=0.6, thickness=1)
        elif roi[0] == 'circle':
            _, cx, cy, r = roi
            cv2.circle(display_frame, (int(cx), int(cy)), int(r), c, 2)
            _put_label(display_frame, "Moving...",
                       max(0, int(cx - r)), max(15, int(cy - r - 15)),
                       colour=c, scale=0.6, thickness=1)
    except Exception:
        pass


def _draw_scale_bar(display_frame):
    px = int(state.scale_bar_length_um / state.pixel_size_um)
    if px <= 0:
        return
    margin   = 20
    cx       = display_frame.shape[1] // 2
    xs, xe   = cx - px // 2, cx + px // 2
    y_pos    = display_frame.shape[0] - margin
    c        = (0, 255, 255)

    cv2.line(display_frame,  (xs, y_pos),     (xe, y_pos),     c, 2)
    cv2.line(display_frame,  (xs, y_pos - 5), (xs, y_pos + 5), c, 2)
    cv2.line(display_frame,  (xe, y_pos - 5), (xe, y_pos + 5), c, 2)

    lbl = (f"{state.scale_bar_length_um:.0f}um ({state.lens_magnification:.1f}x)"
           if state.lens_magnification != 1.0
           else f"{state.scale_bar_length_um:.0f}um")
    tsz = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
    tx  = cx - tsz[0] // 2
    ty  = y_pos - 15
    cv2.rectangle(display_frame, (tx - 5, ty - tsz[1] - 3), (tx + tsz[0] + 5, ty + 3), (0, 0, 0), -1)
    cv2.putText(display_frame, lbl, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)


def _put_label(display_frame, text, tx, ty,
               colour=(255, 255, 255), scale=0.8, thickness=2):
    """Draw text with a black background box."""
    tsz = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0]
    cv2.rectangle(display_frame,
                  (tx - 5, ty - tsz[1] - 5), (tx + tsz[0] + 5, ty + 5),
                  (0, 0, 0), -1)
    cv2.putText(display_frame, text, (tx, ty),
                cv2.FONT_HERSHEY_SIMPLEX, scale, colour, thickness)
