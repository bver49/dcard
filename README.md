# Dcard 看板文章統計

依指定看板與天數，抓取 Dcard 每日文章數量並輸出 CSV。

## Windows 使用者

一般使用者不需要安裝 Python。從 GitHub Actions 下載最新的 Windows ZIP，解壓縮後雙擊：

```text
Dcard文章統計.exe
```

程式會以可見 Chrome 執行，依提示輸入：

- 天數（1～90，不包含今天）
- 看板編號：1 心情、2 感情、3 MLB、4 NBA、5 中職、6 棒球、7 籃球、8 大型賽事

CSV 會寫入程式所在資料夾的 `result.csv`。
每次執行的詳細紀錄會寫入程式所在資料夾的 `logs/`；若失敗，畫面會顯示對應的 log 路徑。

使用者電腦仍需安裝 Google Chrome，且第一次執行需要網路連線，以便取得相容的 ChromeDriver。

## macOS 使用者

從 GitHub Actions 下載 `Dcard文章統計-macOS` artifact，解壓縮後雙擊：

```text
Dcard文章統計-Mac.command
```

macOS 版本同樣不需要安裝 Python，但仍需安裝 Google Chrome。
執行紀錄會寫入 `logs/` 資料夾。

## 開發者執行

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python dcardParserNew.py
```

程式會在頁面 context 內使用 JavaScript `fetch` 呼叫 Dcard API，不會直接以瀏覽器開啟 API URL。

## GitHub Actions 建置

在 GitHub 的 Actions 執行 `Build Windows App`，完成後下載 artifact：

```text
Dcard文章統計-Windows.zip
```

Workflow 會在 Windows runner 上以 PyInstaller 建置，因此使用者端不需要安裝 Python。
