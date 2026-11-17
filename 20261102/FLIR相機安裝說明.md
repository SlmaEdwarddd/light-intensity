# FLIR 相機安裝說明(驅動程式與 Spinnaker SDK)

給第一次在自己電腦上使用 `light_intensity.exe` + FLIR Blackfly S 相機的人。
每台電腦只需要做一次。

## 一、需要準備的東西

| 項目 | 說明 |
|---|---|
| `light_intensity.exe` | **2026-11-11 之後打包的新版**。更早的舊版不支援 FLIR,請刪掉 |
| `SpinnakerSDK_FULL_4.4.0.246_x64.exe` | Teledyne FLIR 官方的 Spinnaker SDK 安裝程式,相機驅動就在裡面 |
| FLIR Blackfly S 相機 + 原廠 USB3 線 | |

**不需要**安裝 Python,也**不需要** `spinnaker_python-…whl`(PySpin)。這些已經包在 exe 裡了。

## 二、安裝步驟

1. **先不要接相機。**
2. 對 `SpinnakerSDK_FULL_4.4.0.246_x64.exe` 按右鍵 →「以系統管理員身分執行」。
3. 選項全部照預設,一路按 Next 到完成。
4. **重新開機。**(沒重開機,驅動和系統設定不會生效。)
5. 把相機接到電腦本體的 **USB 3.0 孔(藍色)**,不要經過 Hub 或延長線。
6. 開 **SpinView**(開始功能表裡找得到,SDK 附的程式):
   - 左邊清單有出現相機,點兩下看得到畫面 → 驅動安裝成功。
   - 看不到相機 → 見第三節。
7. **關掉 SpinView。** 相機一次只能給一個程式用。
8. 開 `light_intensity.exe` → 選「FLIR Blackfly S」→ 按 **Initialize / 初始化**。

## 三、常見錯誤與處理

| 看到的訊息或狀況 | 原因 | 處理方式 |
|---|---|---|
| `Could not load producer… SPINNAKER_GENTL64_CTI_VS140… [-1012]` | Spinnaker SDK 沒安裝,或裝完沒重開機 | 做第二節的步驟 2~4 |
| `Cannot import PySpin: No module named 'PySpin'` | 用到舊版的 exe | 換成新版的 `light_intensity.exe` |
| `找不到 FLIR 相機 / No FLIR camera found` | 程式正常,但沒偵測到相機 | 先確認 SpinView 已關閉;再用 SpinView 檢查看不看得到相機 |
| SpinView 也看不到相機 | 線、USB 孔或驅動的問題 | 見下方檢查清單 |

**SpinView 看不到相機時的檢查清單:**

1. 相機背面的燈有沒有亮。不亮代表沒供電,換一個 USB 孔或換線。
2. 是否插在電腦本體的 USB 3.0 孔,而且沒有經過 Hub。
3. 線是否為原廠 USB3 線,相機端有沒有鎖緊。
4. 開「裝置管理員」看相機的狀態:
   - 有黃色驚嘆號,或出現在「其他裝置」→ 驅動沒裝好,重新執行一次 Spinnaker SDK 安裝程式,然後重開機。
   - 完全沒出現 → 線或 USB 孔的問題。

## 四、回報問題時請附上

- 錯誤視窗的截圖(要看得到完整文字)
- 程式後面那個黑色視窗的截圖
- SpinView 看不看得到相機
