# `cmb-antigravity-accounts`

獨立的零第三方依賴 Python 伴生 CLI，專門為無頭 Linux（例如透過 `systemd` 執行 `run.py --lan`、未開啟 Electron 桌面控制器）提供 Antigravity 多帳號快照管理入口，單向指向既有的 [`codex-mobile-bridge`](https://github.com/try2love/codex-mobile-bridge) 安裝。

## 設計邊界（嚴格對齊 CMB `main`）

1. **只走官方公開通道**：所有讀寫操作一律以子進程呼叫 `<cmb-dir>/desktop.py desktop-sessions --data-dir <data-dir>`（JSON stdin/stdout），不直接讀寫 CMB 的帳號索引或快照檔案。
2. **零私有匯入**：不將 CMB 加入 `sys.path`，不匯入 `bridge.*` 內部模組，CMB 內部重構不影響本工具。
3. **零越權操作**：不直接讀寫系統 Keyring、不複製 Electron Profile 目錄、不強殺進程、不刪除 `Singleton*` 鎖檔；所有安全閘道（全退出核驗、空閒斷言、條件回滾、單次安全重啟）全由 CMB 本體負責。

## 一次設定指向 CMB

```bash
# 保存預設指向（寫入 ~/.config/cmb-antigravity-accounts/config.json，權限 0600）
./cmb-agy-accounts config --cmb-dir /path/to/codex-mobile-bridge
```

亦可用 `--cmb-dir` / `--data-dir` 或環境變數 `CMB_DIR` / `CMB_DATA_DIR` 臨時覆蓋；若未設定且相鄰目錄存在 `../codex-mobile-bridge/desktop.py`，會自動偵測。

## 常用指令

```bash
# 唯讀體檢（檢查 CMB 指向、Linux Keyring 後端、Antigravity 進程、已保存帳號）
./cmb-agy-accounts doctor

# 查看當前接入與已保存帳號清單
./cmb-agy-accounts list

# 保存當前登入帳號為快照（--wait 會等待你手動關閉桌面視窗後自動交由 CMB 保存）
./cmb-agy-accounts save "主力帳號" --wait

# 透過 CMB 安全生命週期切換至指定帳號（支援 1-based 序號、ID、信箱或名稱）
./cmb-agy-accounts switch 1
./cmb-agy-accounts switch "主力帳號" --yes

# 重新命名或刪除網關保存的副本（不影響系統目前登入）
./cmb-agy-accounts rename 1 "新備註"
./cmb-agy-accounts remove 2
```

所有子命令皆支援 `--json` 輸出結構化結果。

## 測試

```bash
python3 -B -m unittest discover -s tests -v
```
