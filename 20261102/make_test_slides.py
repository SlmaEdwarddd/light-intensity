# -*- coding: utf-8 -*-
"""
產生測試用的載玻片影像(依 slide_layout.json),並幫它們建立校正 → 用「匯入圖片」載入就會自動放好 19 個 ROI。

用法(light_intensity conda 環境):python make_test_slides.py
輸出:
  test_images/slide_test_A.png        載玻片水平、置中
  test_images/slide_test_B_shift.png  同一片載玻片放偏 (+24, −14) px(顯示座標 +12, −7;看開程式時的自動微調)
  slide_calibration.json              加入 "IMAGE_2048x1536" 這一筆(不影響相機的校正)

影像:2048x1536(同相機視野)、23 px/mm、水平、綠色螢光樣 RGBA PNG;19 格亮度各不同,格子內外都有灰塵亮點(給 Median / De-glint 測試)。
這是合成影像,只用來測試程式流程;實際量測請用相機或實驗室拍的影像。
"""
import os, json
import numpy as np
import cv2
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = json.load(open(os.path.join(HERE, "slide_layout.json"), encoding="utf-8"))
OUT = os.path.join(HERE, "test_images")
W, H, PPM = 2048, 1536, 23.0          # 與 FLIR BFS-U3-31S4 視野相同;程式縮成 1024x768(11.5 px/mm)


def affine(shift=(0, 0)):
    """mm(圖面,y 向上)→ 影像 px(y 向下),載玻片置中再加位移。"""
    R = np.diag([PPM, -PPM])
    t = np.array([W / 2 + shift[0], H / 2 + shift[1]]) - R @ [LAYOUT["slide_w_mm"] / 2, LAYOUT["slide_h_mm"] / 2]
    return np.hstack([R, t[:, None]])


def make(path, shift, seed):
    A = affine(shift)
    rng = np.random.default_rng(seed)
    img = np.full((H, W), 10.0, np.float32)
    P = lambda pts: np.int32(np.round([A @ [x, y, 1] for x, y in pts]))
    sw, sh = LAYOUT["slide_w_mm"], LAYOUT["slide_h_mm"]
    cv2.fillPoly(img, [P([(0, 0), (sw, 0), (sw, sh), (0, sh)])], 22.0)
    for i, w in enumerate(LAYOUT["wells"]):
        level = 35.0 + 6.0 * i                               # 各格亮度不同
        hw, hh = w["w_mm"] / 2, w["h_mm"] / 2
        cv2.fillPoly(img, [P([(w["x_mm"] - hw, w["y_mm"] - hh), (w["x_mm"] + hw, w["y_mm"] - hh),
                              (w["x_mm"] + hw, w["y_mm"] + hh), (w["x_mm"] - hw, w["y_mm"] + hh)])], level)
    img = cv2.GaussianBlur(img, (0, 0), 1.2) + rng.normal(0, 2.0, img.shape)
    for _ in range(260):                                     # 灰塵亮點,部分落在格子內
        if rng.random() < 0.35:
            w = LAYOUT["wells"][rng.integers(len(LAYOUT["wells"]))]
            x, y = A @ [w["x_mm"] + rng.uniform(-1.3, 1.3), w["y_mm"] + rng.uniform(-1.3, 1.3), 1]
        else:
            x, y = rng.uniform(0, W), rng.uniform(0, H)
        cv2.circle(img, (int(x), int(y)), int(rng.integers(1, 3)), float(rng.uniform(120, 240)), -1)
    g = np.clip(img, 0, 255).astype(np.uint8)
    cv2.imencode(".png", cv2.merge([g // 4, g, g // 5, np.full_like(g, 255)]))[1].tofile(path)
    return A


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    pa, pb = os.path.join(OUT, "slide_test_A.png"), os.path.join(OUT, "slide_test_B_shift.png")
    A = make(pa, (0, 0), 1)
    make(pb, (24, -14), 2)

    # 用程式本身的校正流程(等同管理者在 slide_test_A 上點 T1 / T8 / B1)
    for n in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, n, lambda *a, **k: None)
    messagebox.askokcancel = lambda *a, **k: True
    prog = os.path.join(HERE, "20261102.py")
    code = open(prog, encoding="utf-8").read().split("root.mainloop()")[0].replace("root.after(100, start_system)", "pass")
    g = {"__name__": "__main__", "__file__": prog}
    exec(compile(code, prog, "exec"), g)
    g["CAMERA_TYPE"] = "IMAGE"
    assert g["load_image_file"](pa)
    g["_publish_frame"](g["source_image_gray"])
    g["cad_layout"] = g["_load_slide_layout"]()
    by = {w["name"]: w for w in LAYOUT["wells"]}
    k = g["img_disp_w"] / W                                 # 原始影像 → 顯示座標的縮放
    clicks = [tuple(k * (A @ [by[n]["x_mm"], by[n]["y_mm"], 1]) + [g["img_pad_x"], g["img_pad_y"]]) for n in g["CAD_REFS"]]
    g["calibrate_from_clicks"](g["cad_layout"], clicks)
    print(f"已產生 {os.path.relpath(pa, HERE)}、{os.path.relpath(pb, HERE)}({W}x{H}, {PPM:g} px/mm)"
          f" → 程式內 {g['img_disp_w']}x{g['img_disp_h']}、黑邊 ({g['img_pad_x']}, {g['img_pad_y']})")
    print(f"已在 slide_calibration.json 加入 {g['_cal_key']()};放置 {len(g['rois'])} 個 ROI")
    g["root"].destroy()
