# -*- coding: utf-8 -*-
"""
從 AutoCAD 輸出的 PDF(1:1 列印)抽出載玻片佈局:外框 + 每個正方形樣本格的中心與大小(mm)。

用法:python cad_pdf_layout.py ["76-26  載玻片-模型.pdf"]
輸出:slide_layout.json(程式「依載玻片佈局放置 ROI」讀這個檔)、slide_layout_preview.png(核對用)

座標:原點 = 外框左下角,x 向右、y 向上(與圖面相同),單位 mm。
格子編號:上排 T1..、中排 M1..、下排 B1..,各排由左到右。
ponytail: 只解析未壓縮/Flate 壓縮的單一頁面、m/l/S 構成的直線與矩形;圖面若改用曲線或圓,需擴充。
"""
import os, re, sys, json, zlib
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "76-26  載玻片-模型.pdf")
PT2MM = 25.4 / 72.0


def content_ops(path):
    data = open(path, "rb").read()
    streams = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = m.group(1)
        try:
            streams.append(zlib.decompress(raw).decode("latin1"))
        except zlib.error:
            streams.append(raw.decode("latin1"))
    return "\n".join(streams)


def parse_paths(text):
    """回傳 (縮放係數, [路徑點列表]);每個路徑 = 一次 m ... S 之間的點。"""
    scale = 1.0
    m = re.search(r"([\d.]+)\s+0\s+0\s+([\d.]+)\s+0\s+0\s+cm", text)
    if m:
        scale = float(m.group(1))                         # 內容座標 → PDF point
    paths, cur = [], []
    for line in text.splitlines():
        t = line.split()
        if len(t) == 3 and t[2] == "m":
            cur = [(float(t[0]), float(t[1]))]
        elif len(t) == 3 and t[2] == "l" and cur:
            cur.append((float(t[0]), float(t[1])))
        elif t and t[-1] in ("S", "s") and cur:
            paths.append(cur); cur = []
    return scale, paths


def to_mm(v, scale):
    return v * scale * PT2MM


def extract(path):
    scale, paths = parse_paths(content_ops(path))
    squares, segs = [], []
    for p in paths:
        xs, ys = [q[0] for q in p], [q[1] for q in p]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        closed = len(p) == 5 and p[0] == p[-1]
        if closed and w > 0 and abs(w - h) <= 0.02 * max(w, h):
            squares.append((min(xs), min(ys), max(xs), max(ys)))
        else:
            segs.extend(zip(p[:-1], p[1:]))
    # 外框 = 其餘線段(含倒角)的外接矩形
    ox = [q[0] for s in segs for q in s]; oy = [q[1] for s in segs for q in s]
    x0, y0, x1, y1 = min(ox), min(oy), max(ox), max(oy)
    # 依 y 分排(由上到下),排內依 x 由左到右
    rows = defaultdict(list)
    for sq in squares:
        cy = (sq[1] + sq[3]) / 2
        key = next((k for k in rows if abs(k - cy) < (sq[3] - sq[1]) / 2), cy)
        rows[key].append(sq)
    row_keys = sorted(rows, reverse=True)                  # y 大 = 上排
    names = ["T", "M", "B"] if len(row_keys) == 3 else [f"R{i+1}_" for i in range(len(row_keys))]
    wells = []
    for rn, k in zip(names, row_keys):
        for i, sq in enumerate(sorted(rows[k], key=lambda s: s[0])):
            cx, cy = (sq[0] + sq[2]) / 2, (sq[1] + sq[3]) / 2
            wells.append({"name": f"{rn}{i+1}",
                          "x_mm": round(to_mm(cx - x0, scale), 3), "y_mm": round(to_mm(cy - y0, scale), 3),
                          "w_mm": round(to_mm(sq[2] - sq[0], scale), 3), "h_mm": round(to_mm(sq[3] - sq[1], scale), 3)})
    return {"source": os.path.basename(path),
            "units": "mm", "origin": "外框左下角,x 向右、y 向上",
            "slide_w_mm": round(to_mm(x1 - x0, scale), 3), "slide_h_mm": round(to_mm(y1 - y0, scale), 3),
            "wells": wells}


def preview(layout, out):
    import cv2, numpy as np
    S = 12                                                  # px / mm
    W, H = int(layout["slide_w_mm"] * S) + 80, int(layout["slide_h_mm"] * S) + 80
    im = np.full((H, W, 3), 255, np.uint8)
    X = lambda x: int(40 + x * S); Y = lambda y: int(H - 40 - y * S)
    cv2.rectangle(im, (X(0), Y(0)), (X(layout["slide_w_mm"]), Y(layout["slide_h_mm"])), (0, 0, 0), 1)
    for w in layout["wells"]:
        hw, hh = w["w_mm"] / 2, w["h_mm"] / 2
        cv2.rectangle(im, (X(w["x_mm"] - hw), Y(w["y_mm"] - hh)), (X(w["x_mm"] + hw), Y(w["y_mm"] + hh)), (200, 80, 0), 1)
        cv2.putText(im, w["name"], (X(w["x_mm"]) - 10, Y(w["y_mm"] + hh) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 200), 1)
    cv2.putText(im, f"{layout['slide_w_mm']} x {layout['slide_h_mm']} mm, {len(layout['wells'])} wells",
                (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.imwrite(out, im)


if __name__ == "__main__":
    lay = extract(PDF)
    json.dump(lay, open(os.path.join(HERE, "slide_layout.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"外框 {lay['slide_w_mm']} x {lay['slide_h_mm']} mm,{len(lay['wells'])} 格")
    for w in lay["wells"]:
        print(f"  {w['name']:4s} 中心 ({w['x_mm']:7.3f}, {w['y_mm']:6.3f}) mm  大小 {w['w_mm']} x {w['h_mm']} mm")
    try:
        preview(lay, os.path.join(HERE, "slide_layout_preview.png"))
    except ImportError:
        pass
