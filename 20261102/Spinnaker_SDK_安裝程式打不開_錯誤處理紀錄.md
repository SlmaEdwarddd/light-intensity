# Spinnaker SDK 安裝程式打不開:錯誤處理紀錄

- 日期:2026-11-16 發生並排查,2026-11-17 確認安裝成功
- 相關文件:《FLIR 相機安裝說明(驅動程式與 Spinnaker SDK)》第二節步驟 2
- 用途:補充原說明文件第三節沒有涵蓋的狀況,供其他 session 參考

## 一、結論

`SpinnakerSDK_FULL_4.4.0.246_x64.exe` 按「是」之後沒有安裝畫面,原因不在安裝檔,而是**該電腦的 Windows 系統檔 `C:\Windows\SysWOW64\D3D12Core.dll` 損毀讀不出來**。安裝程式要畫出視窗時載入這個檔案就當掉。

執行 `sfc /scannow` 修復系統檔後,安裝成功。

## 二、環境

| 項目 | 內容 |
|---|---|
| 作業系統 | Windows 10 64 位元(映像版本 10.0.19045.6456) |
| CPU / RAM | Intel Core i3-14100 / 8 GB |
| 儲存體 | 224 GB SSD(KLEVV NEO N400)+ 932 GB HDD(HGST HTS721010A9E630) |
| 防毒軟體 | Avast Free |
| 安裝檔 | `SpinnakerSDK_FULL_4.4.0.246_x64.exe` |

## 三、症狀

1. 對安裝檔按右鍵 →「以系統管理員身分執行」→ 使用者帳戶控制視窗按「是」。
2. 沒有出現安裝畫面,也沒有任何錯誤訊息。
3. 工作管理員裡安裝程式出現一下就消失,只留下 `Teledyne Log Server (32-bit)`。

## 四、診斷依據

事件檢視器 →「Windows 記錄」→「應用程式」,在執行安裝程式的時間點有三筆錯誤:

| 事件 | 來源 | 重點內容 |
|---|---|---|
| 1000 | Application Error | 失敗的應用程式:`SpinnakerSDK_FULL_4.4.0.246_x64.exe`;失敗的模組:`D3D12Core.dll`(版本 10.0.19041.5794);例外狀況代碼:`0xc0000006` |
| 1005 | Application Error | Windows 無法存取檔案 `C:\Windows\SysWOW64\D3D12Core.dll`(網路連線、儲存檔案的磁碟、存放驅動程式發生問題,或遺失磁碟) |
| 1026 | .NET Runtime | 同一時間點的 .NET 執行階段錯誤 |

判讀:

- `0xc0000006` 是讀取檔案分頁失敗,代表 Windows 從磁碟讀這個 DLL 時讀不出來。
- `D3D12Core.dll` 是 Windows 內建的 DirectX 12 元件,不屬於 Spinnaker SDK。
- 所以換安裝檔、換執行位置(例如 D 槽)都沒用,要修的是 Windows。

## 五、處理過程

以系統管理員身分開啟命令提示字元後執行。

| 順序 | 指令 | 結果 |
|---|---|---|
| 1 | `DISM /Online /Cleanup-Image /RestoreHealth` | 跑到 16.8% 失敗,**錯誤 1392**「檔案或目錄損毀而且無法讀取」 |
| 2 | `DISM /Online /Cleanup-Image /RestoreHealth`(再跑一次) | 跑完 100%,**錯誤 0x800f081f**「找不到來源檔案」 |
| 3 | `sfc /scannow` | 「Windows 資源保護發現受損檔案,且已順利修復這些檔案」 |
| 4 | 重新開機後再執行 SDK 安裝程式 | **安裝成功** |

說明:

- 錯誤 1392 表示 C 槽的檔案系統有損毀或有讀不出來的區塊。
- 錯誤 0x800f081f 表示 DISM 找不到乾淨的來源檔來修補元件存放區,通常是電腦沒連網或連不到 Windows Update。它沒有阻礙 SDK 安裝。
- 實際解決問題的是第 3 步的 `sfc /scannow`。

## 六、沒有確認的事

以下事項在排查過程中沒有得到回報,其他 session 不要當成已知事實:

- 第 1 次和第 2 次 DISM 之間有沒有執行 `chkdsk C: /f /r`。兩次錯誤不同(1392 → 0x800f081f),中間可能做過磁碟修復,但沒有紀錄。
- `sfc` 實際修復了哪些檔案(需看 `C:\Windows\Logs\CBS\CBS.log`)。`D3D12Core.dll` 在其中是推斷,依據是修復後安裝就成功了。
- 磁碟健康狀態(`wmic diskdrive get model,status` 或 CrystalDiskInfo 的結果)。
- 系統碟是 SSD 還是 HDD。
- 暫時停用 Avast 是否有試過、是否有影響。
- 系統檔損毀的根本原因。

## 七、這台電腦的後續待辦

1. **檢查磁碟健康**:`wmic diskdrive get model,status`,或用 CrystalDiskInfo 看 SMART。系統檔損毀加上錯誤 1392,有可能是系統碟開始故障。
2. **備份重要資料**,在確認磁碟沒問題之前不要把量測資料只存在這台。
3. **修好 DISM**:連上網路後重跑 `DISM /Online /Cleanup-Image /RestoreHealth`。仍是 0x800f081f 的話,要用 Windows 10 22H2 安裝映像檔當來源。
4. 若之後又出現檔案損毀或 `0xc0000006`,考慮更換系統碟並重灌 Windows。

## 八、之後遇到「安裝程式打不開」的排查流程

1. **先排除簡單原因**
   - 等 1~2 分鐘,用 `Alt + Tab` 確認視窗沒有藏在後面。
   - 檔案大小與原始檔一致;右鍵 →「內容」若有「解除封鎖」就勾選。
   - 安裝檔放在本機路徑(例如 `C:\Temp\`),不要從隨身碟、網路磁碟或壓縮檔內執行。
   - 作業系統是 Windows 10 或 11 的 64 位元版本(Spinnaker 4.x 不支援 Windows 7)。
   - 檢查防毒軟體與「Windows 安全性」→「保護歷程記錄」有沒有攔截紀錄。
2. **看工作管理員**:安裝程式是持續在跑(還在解壓縮)、有好幾個(結束後重開機再試),還是一閃就消失(當掉)。
3. **一閃就消失 → 看事件檢視器**:`Win + R` 輸入 `eventvwr` →「Windows 記錄」→「應用程式」,找該時間點來源為 `Application Error` 或 `.NET Runtime` 的錯誤,記下「失敗的模組名稱」和「例外狀況代碼」。
4. **失敗的模組在 `C:\Windows\` 底下,或例外代碼是 `0xc0000006`** → 是 Windows 系統檔的問題,以系統管理員身分執行:
   ```
   DISM /Online /Cleanup-Image /RestoreHealth
   sfc /scannow
   ```
   DISM 失敗也要繼續跑 `sfc`。跑完重新開機再裝。
5. **DISM 出現錯誤 1392,或 sfc 無法修復** → 先備份資料,再執行 `chkdsk C: /f /r`(重開機後檢查,可能要跑一小時以上),完成後回到步驟 4。
6. **繞過安裝畫面的備案(這次沒有實際測試)**:
   ```
   SpinnakerSDK_FULL_4.4.0.246_x64.exe /install /silent
   ```
   過程沒有畫面,等 5~10 分鐘後重開機,用 SpinView 確認相機看不看得到。預設安裝的元件是否包含 USB3 驅動沒有確認過。

## 九、建議補進原說明文件第三節的內容

| 看到的訊息或狀況 | 原因 | 處理方式 |
|---|---|---|
| SDK 安裝程式按「是」之後沒有畫面,工作管理員裡只剩 `Teledyne Log Server` | Windows 系統檔損毀(這次是 `D3D12Core.dll`,例外代碼 `0xc0000006`),安裝畫面一出現就當掉 | 用系統管理員身分開命令提示字元,執行 `sfc /scannow`,完成後重開機再安裝。仍失敗就到事件檢視器查看錯誤內容 |

第四節「回報問題時請附上」可以加一項:

- 安裝程式打不開時,附上事件檢視器 →「Windows 記錄」→「應用程式」裡該時間點錯誤的截圖
