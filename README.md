# 光強度偵測 / Light Intensity Detection

以 Tkinter + OpenCV 量測樣本灰階光強度的工具。支援 XIMEA(MC050MG-SY、MC023MG-SY)與 Thorlabs 相機,也可以匯入圖片分析。

主要功能:
- 手動或自動放置 ROI(實心亮點 / 方框輪廓兩種偵測模式),ROI 座標可存檔、載入沿用
- 固定 ROI:樣本座標固定時,ROI 位置與大小鎖定,開程式自動載入
- 灰塵與反光濾除:Median Filter(3×3)、White Top-hat 去亮反光(只處理 ROI,K 值可調,主畫面可標紅被去除的像素)
- Threshold、門檻預覽、灰階分佈與對比拉伸(僅影響顯示)、比例尺
- 每秒輸出各 ROI 平均值;CSV 附統計(t > 10 s 的 Mean / Std / CV / Max / Min)
- 存 CSV 後可輸入濃度(自訂或對半稀釋),輸出濃度-光強度線性圖與 R²(可選 X 軸取 log)

## 版本

每個日期資料夾是當時的一個版本,保留當時的程式、打包設定(`.spec`)、測試圖與量測結果。

| 資料夾 | 內容 |
|---|---|
| `20261022/20261022.py` | **最新版**。固定 ROI(座標與大小鎖定、開程式自動載入);去反光改成只處理 ROI,門檻改用 median + K·1.4826·MAD(K 預設 4)。測試:`test_20261022.py`、`deglint_compare.png` |
| `20260928/20261006.py` | 主面板只留相機設定、ROI、對比、濾波;其餘移到「進階設定」視窗 |
| `20260928/20261002.py` | 精簡版(移除 Threshold、Median、比例尺、FPS、門檻預覽);CSV 另存新檔、ROI 座標檔選擇 |
| `20260928/20260928.py` | 新增量測後製作線性圖、ROI 座標記錄 |
| `20260908/` | De-glint(White Top-hat)、即時標紅、相機初始化卡住修正 |
| `20260811/` | 量測正確性修正、自動 ROI 與各種演算法實驗(含 `tophat_demo.py`、`concentration_plot.py`) |
| `20260129/` ~ `20260716/` | 更早的版本 |
| `LightIntensity/` | 早期版本的 `main.py` |

開發紀錄:`20260908/20260903_dev_notes.md`

## 執行

```bash
conda activate light_intensity
python 20261022/20261022.py
```

需要 `opencv-python`、`numpy`、`pillow`、`matplotlib`;接相機另需 XIMEA API(`ximea`)或 `pylablib`(Thorlabs)。

## 打包

用 PyInstaller 搭配各資料夾的 `.spec`,例如 `pyinstaller light_intensity_20260928.spec`(先把 spec 裡的程式檔名改成要打包的版本)。打包產物(`build/`、`dist/`、`*.zip`、`*.exe`)不放進版本控制。
