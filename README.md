# 名古屋・高山・上高地 家族旅行 — 專案說明

單一 HTML 檔案的旅遊行程頁面，內容經瀏覽器端加密保護。純 HTML/CSS/JS，無框架、無建置工具鏈（除了 Python 加密腳本）。

## 檔案說明

- `itinerary.md` — **行程內容的來源（人類可讀、直接編輯這份）**。每天一個區塊，用簡單的標記語法描述時間軸事件、住宿、航班。
- `template.html` — 頁面外殼：CSS 樣式、封面照片、密碼鎖畫面、解密用的 JS，都是明文，直接改這份檔案調整外觀。
- `build.py` — 讀取 `itinerary.md` + `template.html`，把行程內容加密後產生最終檔案。改完 `itinerary.md` 後執行：
  ```
  python3 build.py
  ```
  需要 `pip3 install cryptography`（只需裝一次）。
- `2026名古屋上高地旅行.html` — **建置產物**，實際部署/分享的檔案，由 `build.py` 產生，不要手動改這份。
- 封面照片放在上一層 `../ak0604202041夏の穂高岳と河童橋・８月（上高地）.webp`（`build.py` 會自動讀取嵌入）。

## 密碼

**不寫在這份文件或任何會被 git 追蹤的檔案裡**（舊密碼曾經明文寫在這裡跟 `itinerary.md`，因為要公開 repo 才發現這個問題，已經換過密碼，並把作法改掉）。

密碼實際存放在 `.secret_password`（本機檔案，`.gitignore` 已排除，不會被 commit）。`build.py` 執行時會自動讀取這個檔案。如果要在新機器上重新設定，執行：

```
echo -n '你的密碼' > .secret_password
```

## 加密架構

- AES-256-GCM，金鑰透過 PBKDF2（SHA-256，250,000 次迭代）從密碼推導
- 加密範圍：整個 `<main>` 行程內容 + 總覽頁用的 `days` 中繼資料（一起序列化成 JSON 再加密）
- 封面標題、CSS 樣式、JS 解密邏輯都是明文
- `build.py` 每次都會做一次完整加解密驗證（round-trip），確保密文解得回一模一樣的內容

## 修改行程內容的標準流程

1. 編輯 `itinerary.md`（文字內容、時間、TBD 標記等）
2. 執行 `python3 build.py`（會同時產生 `2026名古屋上高地旅行.html` 和 `index.html`，兩份內容一樣）
3. `git add -A && git commit -m "..."` 記錄這次變動
4. `git push` 推到 GitHub（`origin/master`），GitHub Pages 會自動抓 `index.html` 更新網頁
5. 也可以把 `2026名古屋上高地旅行.html` 交給 Claude Code 重新發布到 Artifact，兩個連結並存

## 部署（GitHub Pages）

Repo：https://github.com/oliviayylin/japan

推送用 SSH（金鑰在 `~/.ssh/id_ed25519_japan_trip`，`~/.ssh/config` 裡已設定 `github.com` 專用這把鑰匙）：

```
git push origin master
```

GitHub Pages 網址設定完成後會是固定的、不會變動，跟 Artifact 連結不同但內容同步——這樣就算 Artifact 平台不支援 localStorage，GitHub Pages 是一般網頁環境，「記住裝置」功能可以正常運作。

## itinerary.md 語法

```
# Day N · MM/DD 週X
標題: 頁面大標題
摘要: 總覽頁卡片的一行摘要
標籤: 標籤1, 標籤2
備註: （選填）補充建議 banner 的說明文字

## 航班
去程 | CODE 地點 T2 HH:MM → CODE 地點 T1 HH:MM | 航空公司 班機號碼

## 行程
- HH:MM [景點|餐飲|住宿|購物|交通] 標題 (TBD)? — 補充小字
（時間可以是範圍，例如 10:00–14:00；(TBD) 是選填，加了會在標題旁多一個虛線 TBD 標籤）

## 住宿
名稱 (TBD)? — 補充小字
（名稱留空 + 沒有名稱時，會自動顯示成「住宿未定」，不會出現 TBD 標籤）
```

天與天之間用 `---` 分隔。

## 修改外觀

CSS 全是明文，直接改 `template.html` 的 `<style>` 就好，不用碰加密流程。配色變數在 `:root` 裡（`--accent` 系列是主色、`--pine`/`--stay`/`--shop`/`--ink-soft` 是各類別圖示顏色）。

## 圖示系統

單色圓潤剪影風格，每個都是 `fill="currentColor"`，顏色由外層 `.icon-sight` / `.icon-food` / `.icon-stay` / `.icon-shop` / `.icon-move` 這幾個 class 決定。圖示的 SVG 定義集中在 `build.py` 的 `ICONS` 字典裡，改一次全站套用（不用像純手改 html 那樣要找到每一處重複貼上的地方替換）。

## 已知限制

- 「記住這台裝置」用的是 `window.storage`（claude.ai artifact 平台專屬 API），但這個能力目前**不在**這個 Artifact 環境開放的 capability 清單裡（只有 `downloads` 和 `mcp`），所以目前這個功能會靜默失效、退回成每次都要輸入密碼——程式碼保留著（未來如果平台開放了這個能力就能直接生效），但現階段不要predict它會動。
- 交通時間地理示意圖（`## 交通時間參考`章節、地圖节点座標）目前不是從 `itinerary.md` 動態產生，是寫死在 `build.py` 的 `GEO_SECTION` 常數裡（因為節點座標是手動排版的視覺效果，不適合用文字格式描述）。要改地圖版面要直接改 `build.py`。
