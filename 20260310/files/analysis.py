"""
analysis.py
-----------
Background analysis loop (runs in a daemon thread while state.analyzing is True)
and CSV export helper.

The loop reads frames from state.current_frame, computes the mean pixel
intensity inside each ROI every second, appends the result to state.roi_data /
state.timestamps, and fires update_plots() + append_log() callbacks so the UI
stays up to date.
"""

import time
import datetime

import cv2
import numpy as np
import pandas as pd

import state


def analysis_loop(update_plots_cb, append_log_cb):
    """
    Main intensity-measurement loop.

    Parameters
    ----------
    update_plots_cb : callable() – called once per second to redraw charts
    append_log_cb   : callable(str) – called once per second to append text log
    """
    state.roi_data  = [[] for _ in state.rois]
    state.timestamps = []

    start_time      = time.time()
    buffer_vals     = [[] for _ in state.rois]
    last_logged_sec = -1

    while state.analyzing:
        with state.frame_lock:
            frame = state.current_frame if state.current_frame is not None else None

        if frame is None:
            time.sleep(0.01)
            continue

        elapsed = int(time.time() - start_time)

        # ── Compute per-ROI intensity for this frame ──────────────────────────
        for i, r in enumerate(state.rois):
            avg_val = _compute_roi_intensity(frame, r)
            buffer_vals[i].append(avg_val)

        # ── Log once per second ───────────────────────────────────────────────
        if elapsed > last_logged_sec:
            log_message = ""
            for i in range(len(state.rois)):
                avg_sec = float(np.mean(buffer_vals[i])) if buffer_vals[i] else 0.0
                rounded = (
                    round(avg_sec, state.decimal_places)
                    if state.decimal_places is not None
                    else avg_sec
                )
                state.roi_data[i].append(rounded)
                buffer_vals[i] = []
                log_message += f"At {elapsed} sec, Sample {i+1} = {rounded}\n"

            state.timestamps.append(elapsed)

            try:
                update_plots_cb()
            except Exception:
                pass

            append_log_cb(log_message.strip())
            last_logged_sec = elapsed
        else:
            time.sleep(0.01)


def _compute_roi_intensity(frame, r):
    """Return mean pixel value inside ROI r, respecting state.threshold_value."""
    kind = r[0]

    if kind == 'rect':
        _, x1, y1, x2, y2 = r
        hx1 = max(0, int(x1));  hy1 = max(0, int(y1))
        hx2 = min(frame.shape[1], int(x2));  hy2 = min(frame.shape[0], int(y2))
        if hx2 <= hx1 or hy2 <= hy1:
            return 0.0
        patch = frame[hy1:hy2, hx1:hx2]
        return _mean_with_threshold(patch)

    elif kind == 'circle':
        _, cx, cy, rad = r
        cx_i, cy_i, rad_i = int(round(cx)), int(round(cy)), int(round(rad))
        x1 = max(0, cx_i - rad_i);  x2 = min(frame.shape[1], cx_i + rad_i)
        y1 = max(0, cy_i - rad_i);  y2 = min(frame.shape[0], cy_i + rad_i)
        if x2 <= x1 or y2 <= y1 or rad_i <= 0:
            return 0.0
        patch = frame[y1:y2, x1:x2]
        mask  = np.zeros_like(patch, dtype=np.uint8)
        cv2.circle(mask, (cx_i - x1, cy_i - y1), rad_i, 1, -1)
        pixels = patch[mask == 1]
        if state.threshold_value is not None:
            pixels = pixels[pixels <= state.threshold_value]
        return float(np.mean(pixels)) if pixels.size > 0 else 0.0

    return 0.0


def _mean_with_threshold(patch):
    if state.threshold_value is not None:
        pixels = patch[patch <= state.threshold_value]
        return float(np.mean(pixels)) if pixels.size > 0 else 0.0
    return float(np.mean(patch))


# ─────────────────────────────────────────────────────────────────────────────
# CSV export
# ─────────────────────────────────────────────────────────────────────────────

def save_csv(show_warning_cb, show_info_cb):
    """
    Write state.roi_data + state.timestamps to a timestamped CSV file.

    Parameters
    ----------
    show_warning_cb : callable(title, msg) – e.g. messagebox.showwarning
    show_info_cb    : callable(title, msg) – e.g. messagebox.showinfo
    """
    if not state.roi_data or not state.timestamps:
        show_warning_cb(
            "無資料 / No Data",
            "尚未產生資料，無法儲存。\nNo data to save."
        )
        return

    now      = datetime.datetime.now()
    filename = f"Light intensity_{now:%Y_%m_%d_%H_%M_%S}.csv"
    df       = pd.DataFrame({"Time (s)": state.timestamps})
    for i, values in enumerate(state.roi_data):
        df[f"Sample {i+1}"] = values
    df.to_csv(filename, index=False)
    show_info_cb(
        "儲存成功 / Saved",
        f"數值已儲存為 {filename}\nValues Saved as {filename}"
    )
