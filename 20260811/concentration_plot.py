# -*- coding: utf-8 -*-
"""
濃度 vs 光強度 線性檢視 / Concentration vs Intensity linearity check

X 軸:樣本濃度(第一筆 4.108e-9,之後對半四次,最後一筆空白=0)
Y 軸:光強度(灰階值)
輸出:散點 + 最佳擬合直線,標註方程式與 R²
"""
import numpy as np
import matplotlib
import matplotlib.pyplot as plt

# ── 濃度(已依規則算好,勿改)────────────────────────────────
C0 = 4.108e-9
concentration = [C0, C0/2, C0/4, C0/8, C0/16, 0.0]   # 最後一筆為空白
UNIT = "M"                                            # 濃度單位,可自行改

# ── 光強度(灰階值)：把你的 6 筆量測值填進去 ──────────────────
#    順序要對應上面的濃度(高→低,最後一筆為空白)
intensity = [243.2, 203.32, 150.64, 122.7,112.63, 88.09]               # ← 改成你的量測值


def fit_r2(x, y):
    """線性擬合,回傳 (slope, intercept, R^2)。"""
    x = np.asarray(x, float); y = np.asarray(y, float)
    a, b = np.polyfit(x, y, 1)
    yhat = a * x + b
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return a, b, r2


def main():
    x = np.asarray(concentration, float)
    y = np.asarray(intensity, float)
    if len(x) != len(y):
        raise SystemExit(f"濃度({len(x)})與光強度({len(y)})筆數不符,請檢查 intensity。")

    a, b, r2 = fit_r2(x, y)                    # 含空白
    # 不含空白(有時空白/0 點會偏離線性,一起看比較準)
    a2, b2, r2b = fit_r2(x[:-1], y[:-1])

    print("濃度 (X)        光強度 (Y)")
    for xi, yi in zip(x, y):
        print(f"{xi:.4e}    {yi:g}")
    print(f"\n含空白  : y = {a:.4e} * x + {b:.3f}   R^2 = {r2:.4f}")
    print(f"不含空白: y = {a2:.4e} * x + {b2:.3f}   R^2 = {r2b:.4f}")

    # ── 繪圖 ────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(x, y, s=70, color="#0078D4", zorder=3, label="Data")
    xs = np.linspace(x.min(), x.max(), 100)
    ax.plot(xs, a * xs + b, color="#D83B01", lw=2,
            label=f"Fit: y = {a:.3e}·x + {b:.2f}")
    # 標出空白點
    ax.scatter([x[-1]], [y[-1]], s=90, facecolors="none",
               edgecolors="#333333", linewidths=1.5, zorder=4, label="Blank")

    ax.set_xlabel(f"Concentration ({UNIT})")
    ax.set_ylabel("Intensity (grayscale)")
    ax.set_title("Concentration vs Intensity")
    ax.grid(True, alpha=0.3)
    ax.text(0.05, 0.90,
            f"$R^2$ = {r2:.4f}  (with blank)\n$R^2$ = {r2b:.4f}  (no blank)",
            transform=ax.transAxes, fontsize=11, va="top",
            bbox=dict(boxstyle="round", fc="#FFF7E6", ec="#D83B01"))
    ax.legend(loc="lower right")
    fig.tight_layout()

    fig.savefig("concentration_plot.png", dpi=150)
    print("\n已存圖:concentration_plot.png")
    plt.show()


if __name__ == "__main__":
    main()
