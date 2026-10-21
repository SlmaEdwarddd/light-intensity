"""
camera.py
---------
Camera initialisation and per-camera video-capture loops.

Supported cameras
  - XIMEA  (ximea / xiapi)
  - Thorlabs (pylablib)

Each video_loop_* function runs in its own daemon thread (started by
main.py).  It reads frames from the hardware and writes them into
state.current_frame under state.frame_lock so the UI thread can safely
consume them.
"""

import os
import cv2
import numpy as np
import time

import state


# ─────────────────────────────────────────────────────────────────────────────
# XIMEA
# ─────────────────────────────────────────────────────────────────────────────

def init_camera_ximea(downsampling_var, scale_entry):
    """
    Initialise the XIMEA camera.

    Parameters
    ----------
    downsampling_var : tk.StringVar  – '1x1' or '2x2'
    scale_entry      : ttk.Entry    – scale-bar entry widget (enabled after init)
    """
    try:
        from ximea import xiapi
    except Exception:
        raise RuntimeError(
            "無法載入 ximea 模組；請安裝 XIMEA SDK 與 Python binding。\n"
            "Cannot import ximea module; please install XIMEA SDK and Python bindings."
        )

    state.cam = xiapi.Camera()
    state.cam.open_device()

    # Image format
    try:
        state.cam.set_imgdataformat("XI_MONO8")
    except Exception:
        pass

    # Downsampling
    try:
        ds = downsampling_var.get()
        if hasattr(state.cam, "set_downsampling"):
            state.cam.set_downsampling('XI_DWN_1x1' if ds == '1x1' else 'XI_DWN_2x2')
    except Exception:
        pass

    # Exposure (XIMEA uses microseconds)
    try:
        if hasattr(state.cam, "set_exposure"):
            state.cam.set_exposure(state.user_exposure_ms * 1e3)
    except Exception:
        pass

    state.xi_img = xiapi.Image()

    try:
        state.cam.start_acquisition()
    except Exception:
        pass

    # Test frame
    try:
        state.cam.get_image(state.xi_img)
        frame = state.xi_img.get_image_data_numpy()
    except Exception as e:
        raise RuntimeError(
            f"無法讀取 XIMEA 影像: {e}\nCannot get XIMEA image: {e}"
        )

    if frame is None:
        raise RuntimeError("無法讀取 XIMEA 影像\nCannot get XIMEA image")

    if frame.dtype != np.uint8:
        try:
            frame = frame.astype(np.uint8)
        except Exception:
            frame = np.clip(frame, 0, 255).astype(np.uint8)

    state.orig_h, state.orig_w = frame.shape[:2]
    state.bit_depth = 8

    # Allow user to edit scale entry for XIMEA
    try:
        scale_entry.config(state="normal")
    except Exception:
        pass


def video_loop_ximea():
    """Capture loop for XIMEA — runs in a daemon thread."""
    try:
        from ximea import xiapi
    except Exception:
        return

    state.xi_img = xiapi.Image()

    while state.running:
        try:
            state.cam.get_image(state.xi_img)
            frame = state.xi_img.get_image_data_numpy()
        except Exception:
            continue

        if frame is None:
            continue

        now_sec = int(time.time())
        if now_sec != state.last_sec_time:
            state.fps_value = state.valid_frame_count
            state.valid_frame_count = 0
            state.last_sec_time = now_sec

        if state.user_fps_val is not None and state.valid_frame_count >= int(state.user_fps_val):
            continue

        if frame.dtype != np.uint8:
            try:
                frame = frame.astype(np.uint8)
            except Exception:
                frame = np.clip(frame, 0, 255).astype(np.uint8)

        try:
            frame_resized = cv2.resize(frame, (state.disp_w, state.disp_h))
        except Exception:
            frame_resized = frame

        with state.frame_lock:
            state.current_frame = frame_resized

        state.valid_frame_count += 1


# ─────────────────────────────────────────────────────────────────────────────
# Thorlabs
# ─────────────────────────────────────────────────────────────────────────────

def init_camera_thorlabs(scale_entry, scale_enable_var):
    """
    Initialise the Thorlabs TL camera.

    Parameters
    ----------
    scale_entry      : ttk.Entry     – pre-filled with 3.45 µm/px then locked
    scale_enable_var : tk.BooleanVar – set True automatically
    """
    import pylablib as pll
    from pylablib.devices import Thorlabs

    # --- Locate the DLL ---
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

    if not dll_found and os.path.exists(r"C:\Program Files\Thorlabs"):
        for root_dir, _, files in os.walk(r"C:\Program Files\Thorlabs"):
            if "thorlabs_tsi_camera_sdk.dll" in files:
                pll.par["devices/dlls/thorlabs_tlcam"] = root_dir
                dll_found = True
                break

    if not dll_found:
        raise RuntimeError(
            "找不到 thorlabs_tsi_camera_sdk.dll，請確認已安裝 ThorCam 軟體。\n"
            "Cannot find thorlabs_tsi_camera_sdk.dll. Please ensure ThorCam software is installed."
        )

    cams = Thorlabs.list_cameras_tlcam()
    if not cams:
        raise RuntimeError(
            "找不到 Thorlabs 相機，請確認連線與驅動\n"
            "No Thorlabs cameras found. Please check connection and drivers."
        )

    serial = cams[0]
    state.cam = Thorlabs.ThorlabsTLCamera(serial=serial)

    try:
        state.cam.set_exposure(state.user_exposure_ms / 1e3)
    except Exception:
        pass

    try:
        state.cam.setup_acquisition(nframes=100)
        state.cam.start_acquisition()
    except Exception:
        pass

    try:
        _, bit_depth_local = state.cam.get_sensor_info()
        state.bit_depth = bit_depth_local if bit_depth_local is not None else 8
    except Exception:
        state.bit_depth = 8

    # Test frame
    try:
        state.cam.wait_for_frame(timeout=2.0)
        frame = state.cam.read_oldest_image()
    except Exception as e:
        raise RuntimeError(
            f"無法讀取 Thorlabs 影像: {e} / Cannot read Thorlabs image: {e}"
        )

    if frame is None:
        raise RuntimeError("無法讀取 Thorlabs 影像 / Cannot read Thorlabs image")

    if state.bit_depth > 8:
        frame = (frame >> (state.bit_depth - 8)).astype(np.uint8)
    else:
        frame = frame.astype(np.uint8)

    if frame.ndim == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    state.orig_h, state.orig_w = frame.shape[:2]

    # Thorlabs: 3.45 µm/px – fixed, user cannot edit
    try:
        import tkinter as tk
        scale_entry.delete(0, tk.END)
        scale_entry.insert(0, "3.45")
        scale_entry.config(state="disabled")
        scale_enable_var.set(True)
    except Exception:
        pass


def video_loop_thorlabs():
    """Capture loop for Thorlabs — runs in a daemon thread."""
    while state.running:
        try:
            state.cam.wait_for_frame(timeout=1.0)
            frame = state.cam.read_oldest_image()
        except Exception:
            continue

        if frame is None:
            continue

        if state.bit_depth > 8:
            frame = (frame >> (state.bit_depth - 8)).astype(np.uint8)
        else:
            frame = frame.astype(np.uint8)

        now_sec = int(time.time())
        if now_sec != state.last_sec_time:
            state.fps_value = state.valid_frame_count
            state.valid_frame_count = 0
            state.last_sec_time = now_sec

        if state.user_fps_val is not None and state.valid_frame_count >= int(state.user_fps_val):
            continue

        if frame.ndim == 3 and frame.shape[2] == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        try:
            frame_resized = cv2.resize(frame, (state.disp_w, state.disp_h))
        except Exception:
            frame_resized = frame

        with state.frame_lock:
            state.current_frame = frame_resized

        state.valid_frame_count += 1


# ─────────────────────────────────────────────────────────────────────────────
# Shared camera helpers
# ─────────────────────────────────────────────────────────────────────────────

def apply_gain_and_exposure(gain_val, exposure_ms):
    """
    Push gain and exposure values to the active camera.

    Returns
    -------
    (ok_gain: bool, ok_exp: bool)
    """
    ok_gain = ok_exp = False

    try:
        if hasattr(state.cam, "set_gain"):
            state.cam.set_gain(float(gain_val))
            ok_gain = True
        elif hasattr(state.cam, "gain"):
            state.cam.gain = float(gain_val)
            ok_gain = True
    except Exception as e:
        print(f"[camera] Failed to apply gain: {e}")

    try:
        if state.CAMERA_TYPE == "XIMEA" and hasattr(state.cam, "set_exposure"):
            state.cam.set_exposure(int(exposure_ms * 1000))   # µs
            ok_exp = True
        elif state.CAMERA_TYPE == "THORLABS" and hasattr(state.cam, "set_exposure"):
            state.cam.set_exposure(exposure_ms / 1000.0)      # s
            ok_exp = True
    except Exception as e:
        print(f"[camera] Failed to apply exposure: {e}")

    print(f"[camera] Applied gain={gain_val}, exposure={exposure_ms} ms")
    return ok_gain, ok_exp


def apply_defaults_on_restart(downsampling_var):
    """Reset camera to safe defaults when the user restarts detection."""
    if state.cam is None:
        return
    try:
        if hasattr(state.cam, "set_gain"):
            state.cam.set_gain(0.0)
    except Exception:
        pass

    try:
        default_exp = 10.0
        if state.CAMERA_TYPE == "XIMEA":
            state.cam.set_exposure(int(default_exp) * 1000)
        else:
            state.cam.set_exposure(default_exp / 1000.0)
    except Exception:
        pass

    if state.CAMERA_TYPE == "XIMEA" and hasattr(state.cam, "set_downsampling"):
        try:
            ds = downsampling_var.get()
            state.cam.set_downsampling('XI_DWN_1x1' if ds == '1x1' else 'XI_DWN_2x2')
        except Exception:
            pass


def release_camera():
    """Safely stop acquisition and close the active camera."""
    try:
        if state.CAMERA_TYPE == "XIMEA" and state.cam is not None:
            try:
                state.cam.stop_acquisition()
            except Exception:
                pass
            try:
                state.cam.close_device()
            except Exception:
                pass
        elif state.CAMERA_TYPE == "THORLABS" and state.cam is not None:
            try:
                state.cam.stop_acquisition()
            except Exception:
                pass
            try:
                state.cam.close()
            except Exception:
                pass
    except Exception:
        pass
