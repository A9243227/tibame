# Git 協作規範與指令指南

## ⚠️ 注意事項與協作規則
1. **開發前務必 Pull**：每次開始寫程式前，務必先拉取最新程式碼，以避免後續產生不必要的衝突。
2. **分支命名規範**：建議使用前綴來區分分支用途，例如：
   - `feature/功能名稱` (例如：`feature/login-page`)
   - `bugfix/問題名稱` (例如：`bugfix/header-typo`)
   - `hotfix/緊急修復`
3. **Commit 訊息清楚明瞭**：必須清晰表達這次提交的修改內容。建議加上前綴標籤：
   - `[新增]` 新功能或檔案
   - `[修正]` 修復 Bug
   - `[優化]` 效能提升或程式碼重構
   - 範例：`git commit -m "[新增] 會員登入 API 實作"`
4. **小步提交 (Atomic Commits)**：不要將大量無關的更改混在同一個 commit 中，盡量保持一個 commit 只做一件事情，這對未來追蹤問題非常有幫助。
5. **謹慎處理衝突 (Merge Conflict)**：遇到衝突時，請仔細確認雙方的更改。如果不確定這段程式碼的邏輯，請務必與原作者討論，**絕對不要隨意覆蓋別人的程式碼**。
6. **標準開發與合併流程**：完成功能或者修改某片段後，請先將程式碼 push 到自己的分支。確定修改完成並經過測試後，再推送到 `develop` 分支。後續的 code review 以及執行 branch merge 會再透過 `develop` 合併到 `main` 裡面並進行升版。

---

## 🔄 基本工作流程（直接在開發分支開發）

如果您們目前的專案規模較小，允許直接在開發分支（`develop`）上開發，請參考以下步驟：

### 1. 拉取最新程式碼 (Pull)
```bash
# 開發前先拉取遠端最新進度
git pull origin develop
```

### 2. 查看狀態與加入暫存區 (Add)
```bash
# 查看目前修改了哪些檔案
git status

# 將特定檔案加入暫存區
git add <檔案名稱>

# 將所有修改的檔案加入暫存區（最常用）
git add .
```

### 3. 提交更改 (Commit)
```bash
# 提交並加上說明訊息
git commit -m "[修改類型] 您的修改詳細說明"
```

### 4. 推送到遠端 (Push)
```bash
# 在推送前，建議再拉取一次以防有人在你開發時推了新程式碼
git pull origin develop

# 將本地提交推送到遠端伺服器
git push origin develop
```

---

## 🌿 分支工作流程（強烈建議的團隊開發方式）

多人協作時，為了避免互相干擾導致主線損壞，通常會開設獨立的分支進行開發，完成後再合併。

### 1. 建立並切換分支 (Branching)
```bash
# 先切回 develop 分支並確保是最新的
git checkout develop
git pull origin develop

# 建立並同時切換到新分支 (-b 代表 branch)
git checkout -b feature/your-feature-name
```

### 2. 在分支上開發並提交
在分支上的操作跟基本流程一樣：
```bash
git status
git add .
git commit -m "[新增] 完成某某功能的第一部分"
```

### 3. 將新分支推送到遠端 (Push Branch)
```bash
# 第一次推送該分支到遠端時，需要設定上游 (upstream)
git push -u origin feature/your-feature-name

# 之後如果在同一個分支繼續開發並提交，只需輸入：
git push
```

### 4. 合併分支 (Merge to Develop)
當您的分支開發完成，且測試確認沒問題後，就可以將其合併回 `develop` 分支。
*(註：在實際工作中，這步通常會透過 GitHub/GitLab 上的 Pull Request / Merge Request 來進行。若在本地端合併則按照以下詳細步驟：)*

```bash
# 1. 先切換回 develop 分支
git checkout develop

# 2. 確保 develop 分支是最新的 (非常重要！)
git pull origin develop

# 3. 將您的開發分支合併到 develop
git merge feature/your-feature-name
```

**⚠️ 如果發生合併衝突 (Merge Conflict)：**
當 Git 提示有衝突無法自動合併時，請按照以下步驟處理：
1. 打開編輯器 (VS Code等)，找出有衝突的檔案。
2. 尋找 `<<<<<<<`, `=======`, `>>>>>>>` 標記，決定要保留哪一段程式碼（或兩者皆保留），然後刪除這些標記。
3. 存檔後，將解完衝突的檔案加入暫存區：
   ```bash
   git add 檔案名稱
   # 或 git add .
   ```
4. 完成合併的 Commit：
   ```bash
   git commit -m "Merge branch 'feature/your-feature-name' into develop"
   ```

**完成合併後推送：**
```bash
# 4. 將合併後的 develop 分支推送到遠端
git push origin develop
```

### 5. 發布新版本 (Merge to Main)
當 `develop` 分支上的功能都已準備就緒，經過 Code Review 並且確定要發布時，由負責人將 `develop` 合併至 `main`：

```bash
# 1. 切換至 main 分支並確保最新
git checkout main
git pull origin main

# 2. 將 develop 合併到 main
git merge develop

# 3. 推送到遠端
git push origin main
```
*(發布後通常還會使用 `git tag` 標記版本號，例如 `git tag v1.0.0`)*

### 6. 刪除已完成的分支 (可選)
為了保持分支列表乾淨，合併完畢後可以刪除該分支：
```bash
# 刪除本地分支
git branch -d feature/your-feature-name

# 刪除遠端分支
git push origin --delete feature/your-feature-name
```
