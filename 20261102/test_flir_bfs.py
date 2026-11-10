# -*- coding: utf-8 -*-
"""
FLIR Blackfly S(BFS-U3-31S4)相機流程測試 —— 用「模擬 PySpin」,不需要真的相機或 Spinnaker SDK。

用法(light_intensity conda 環境):python test_flir_bfs.py

模擬相機照 PySpin 的 API(System / CameraList / 節點 SetValue·GetValue·GetMin·GetMax / GetNextImage / Release),
畫面亮度 ∝ 曝光 × 10^(增益/20),偶爾送出不完整影像。檢查:
  [1] 初始化:Mono8、關自動曝光 / 增益、關 gamma、關幀率限制、開始擷取;曝光 30 ms、增益 0 dB;解析度與 letterbox
  [2] 讀圖執行緒持續送出影像,不完整影像會被丟掉
  [3] 主面板套用曝光 / 增益 → 畫面亮度跟著變;超出範圍會被夾住
  [4] 重新量測時恢復預設曝光 / 增益
  [5] 關閉:停止擷取、DeInit、釋放 System;重複關閉不出錯
  [6] 彩色機型(不支援 Mono8)改用 BGR8 再轉灰階
  [7] 找不到相機 / 沒裝 PySpin:給出清楚的錯誤訊息
真的相機到位後,仍需實機確認(見最後的提醒)。
"""
import os, sys, time, types, threading
import numpy as np
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "20261102.py")
for _n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _n, lambda *a, **k: None)
messagebox.askokcancel = lambda *a, **k: True


# ── 模擬 PySpin ──────────────────────────────────────────────────────────────
class Node:
    def __init__(self, value, lo=None, hi=None, writable=True, log=None, name=""):
        self.v, self.lo, self.hi, self.writable, self.log, self.name = value, lo, hi, writable, log, name
    def SetValue(self, v):
        if not self.writable:
            raise RuntimeError(f"{self.name} not writable")
        if self.lo is not None and not (self.lo <= v <= self.hi):
            raise RuntimeError(f"{self.name} out of range")
        self.v = v
        if self.log is not None:
            self.log.append((self.name, v))
    def GetValue(self): return self.v
    def GetMin(self): return self.lo
    def GetMax(self): return self.hi


class FakeImage:
    def __init__(self, arr, incomplete):
        self.arr, self.incomplete, self.released = arr, incomplete, False
    def IsIncomplete(self): return self.incomplete
    def GetNDArray(self): return self.arr
    def Release(self): self.released = True


class FakeCam:
    def __init__(self, color=False):
        self.log, self.state, self.color, self.n = [], [], color, 0
        L = self.log
        self.DeviceModelName = Node("Blackfly S BFS-U3-31S4" + ("C" if color else "M"))
        self.DeviceSerialNumber = Node("24123456")
        self.DeviceFirmwareVersion = Node("2110.0.318.0")
        self.AcquisitionMode = Node(None, log=L, name="AcquisitionMode")
        self.PixelFormat = Node("BayerRG8" if color else "Mono8", log=L, name="PixelFormat")
        if color:                                                   # 彩色機型不支援 Mono8
            orig = self.PixelFormat.SetValue
            self.PixelFormat.SetValue = lambda v: (_ for _ in ()).throw(RuntimeError("Mono8 unsupported")) if v == "Mono8" else orig(v)
        self.ExposureAuto = Node("Continuous", log=L, name="ExposureAuto")
        self.GainAuto = Node("Continuous", log=L, name="GainAuto")
        self.GammaEnable = Node(True, log=L, name="GammaEnable")
        self.AcquisitionFrameRateEnable = Node(True, log=L, name="AcquisitionFrameRateEnable")
        self.ExposureTime = Node(10000.0, 13.0, 30_000_000.0, log=L, name="ExposureTime")   # µs
        self.Gain = Node(0.0, 0.0, 47.99, log=L, name="Gain")
    def Init(self): self.state.append("Init")
    def DeInit(self): self.state.append("DeInit")
    def BeginAcquisition(self): self.state.append("Begin")
    def EndAcquisition(self): self.state.append("End")
    def GetNextImage(self, timeout):
        self.n += 1
        level = 2.0 * self.ExposureTime.GetValue() / 1000.0 * 10 ** (self.Gain.GetValue() / 20)   # 30 ms, 0 dB → 60
        arr = np.full((1536, 2048), np.clip(level, 0, 255), np.uint8)
        arr[700:800, 1000:1100] = np.clip(level * 2, 0, 255)
        if self.color:
            arr = np.dstack([arr, arr, arr])
        time.sleep(0.005)
        return FakeImage(arr, incomplete=(self.n % 7 == 0))


def make_pyspin(n_cams=1, color=False):
    ps = types.ModuleType("PySpin")
    ps.AcquisitionMode_Continuous = "Continuous"
    ps.PixelFormat_Mono8, ps.PixelFormat_BGR8 = "Mono8", "BGR8"
    ps.ExposureAuto_Off, ps.GainAuto_Off = "Off", "Off"
    cams = [FakeCam(color) for _ in range(n_cams)]

    class CamList:
        cleared = False
        def GetSize(self): return len(cams)
        def GetByIndex(self, i): return cams[i]
        def Clear(self): CamList.cleared = True

    class System:
        released = False
        @staticmethod
        def GetInstance(): return System()
        def GetCameras(self): return CamList()
        def ReleaseInstance(self): System.released = True

    ps.System, ps.CamList, ps.cams = System, CamList, cams
    return ps


def load_program():
    code = open(PROG, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
    g = {"__name__": "__main__", "__file__": PROG}
    exec(compile(code, PROG, "exec"), g)
    return g


def pump(root, sec):
    t = time.time()
    while time.time() - t < sec:
        root.update(); time.sleep(0.01)


def frame_level(g):
    with g["frame_lock"]:
        f = g["current_frame"]
    y0, x0 = g["img_pad_y"], g["img_pad_x"]
    return float(np.median(f[y0 + 5:y0 + 50, x0 + 5:x0 + 50]))


# [1] 初始化
sys.modules["PySpin"] = ps = make_pyspin()
g = load_program()
root = g["root"]
g["init_camera_flir_bfs"]()
g["CAMERA_TYPE"] = "FLIR_BFS"
fc = ps.cams[0]
names = [n for n, _ in fc.log]
pump(root, 0.2)
print("[1] 初始化設定順序:", " → ".join(f"{n}={v}" for n, v in fc.log))
assert fc.PixelFormat.GetValue() == "Mono8" and fc.ExposureAuto.GetValue() == "Off" and fc.GainAuto.GetValue() == "Off"
assert fc.GammaEnable.GetValue() is False and fc.AcquisitionFrameRateEnable.GetValue() is False
assert fc.state[:2] == ["Init", "Begin"] and names.index("PixelFormat") < names.index("ExposureTime")
assert abs(fc.ExposureTime.GetValue() - 30000) < 1e-6 and fc.Gain.GetValue() == 0.0
print(f"    相機 {g['cam'].info};曝光 {fc.ExposureTime.GetValue() / 1000:g} ms、增益 {fc.Gain.GetValue()} dB;"
      f"影像 {g['orig_w']}x{g['orig_h']} → 顯示 {g['img_disp_w']}x{g['img_disp_h']};主面板曝光欄 = {g['exposure_entry'].get()}")
assert (g["orig_w"], g["orig_h"]) == (2048, 1536) and g["exposure_entry"].get() == "30"

# [2] 讀圖執行緒
threading.Thread(target=g["video_loop_flir"], daemon=True).start()
pump(root, 0.6)
seq0 = g["frame_seq"]; pump(root, 0.5); seq1 = g["frame_seq"]
print(f"[2] 讀圖執行緒 0.5 s 送出 {seq1 - seq0} 張(不完整影像已丟掉),畫面亮度 {frame_level(g):.0f}")
assert seq1 > seq0 and abs(frame_level(g) - 60) <= 1

# [3] 套用曝光 / 增益
ok = g["apply_gain_and_exposure_to_camera"](6.0, 60.0); pump(root, 0.3)
lv = frame_level(g)
print(f"[3] 套用 增益 6 dB、曝光 60 ms → {ok},畫面亮度 {lv:.0f}(預期 2×60×10^(6/20) ≈ 239)")
assert ok == (True, True) and abs(lv - 239) <= 2
g["apply_gain_and_exposure_to_camera"](99.0, 999999.0)
print(f"    超出範圍(99 dB、999999 ms)→ 夾到上限:增益 {fc.Gain.GetValue()} dB、曝光 {fc.ExposureTime.GetValue() / 1e6:g} s")
assert fc.Gain.GetValue() == 47.99 and fc.ExposureTime.GetValue() == 30_000_000.0

# [4] 重新量測恢復預設
g["apply_defaults_on_restart_camera"]()
print(f"[4] 恢復預設:增益 {fc.Gain.GetValue()} dB、曝光 {fc.ExposureTime.GetValue() / 1000:g} ms")
assert fc.Gain.GetValue() == 0.0 and abs(fc.ExposureTime.GetValue() - 30000) < 1e-6

# [5] 關閉
g["running"] = False; time.sleep(0.2)
with g["camera_lock"]:
    g["cam"].close()
g["cam"].close()                                   # 程式結束清理會再呼叫一次
print(f"[5] 關閉:相機狀態 {fc.state[-2:]},CameraList 清除 {ps.CamList.cleared},System 釋放 {ps.System.released};重複關閉 OK")
assert fc.state[-2:] == ["End", "DeInit"] and ps.CamList.cleared and ps.System.released
root.destroy()

# [6] 彩色機型
sys.modules["PySpin"] = ps = make_pyspin(color=True)
g = load_program()
g["init_camera_flir_bfs"]()
fc = ps.cams[0]
f = g["cam"].read()
print(f"[6] 彩色機型:PixelFormat → {fc.PixelFormat.GetValue()},讀出影像 {f.shape} {f.dtype}")
assert fc.PixelFormat.GetValue() == "BGR8" and f.ndim == 2 and f.dtype == np.uint8
g["cam"].close(); g["root"].destroy()

# [7] 錯誤情況
sys.modules["PySpin"] = make_pyspin(n_cams=0)
g = load_program()
try:
    g["init_camera_flir_bfs"](); msg = "沒有錯誤"
except RuntimeError as e:
    msg = str(e).splitlines()[0]
print(f"[7] 沒接相機 → {msg}")
assert "找不到 FLIR 相機" in msg
sys.modules["PySpin"] = None                       # 模擬沒裝 PySpin
try:
    g["init_camera_flir_bfs"](); msg = "沒有錯誤"
except RuntimeError as e:
    msg = str(e).splitlines()[0]
print(f"    沒裝 PySpin → {msg}")
assert "PySpin" in msg
g["root"].destroy()
print("\n全部測試通過(模擬相機)。實機到位後請再確認:SpinView 看得到相機、曝光 / 增益調整後亮度變化、關閉程式後 SpinView 能重新開啟相機。")
