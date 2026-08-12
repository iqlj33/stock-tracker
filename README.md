# 📈 股票持仓管家 (稳定版)

纯云端运行的股票持仓管理工具，手机浏览器即可操作。

## 功能

- 📊 持仓总览：自动抓取实时行情，计算成本/浮盈/收益率
- ➕ 添加交易：搜索股票 → 选买入/卖出 → 填数量价格 → 保存
- 📋 交易明细：查看每只股票的历史流水，支持删除
- 💰 分红记录：手动添加分红，自动扣减持仓成本
- 📤 导出导入：Excel(3个Sheet) / JSON 备份恢复

## 部署步骤

### 1. 创建 GitHub 仓库
- 访问 https://github.com/new
- 仓库名：`stock-tracker`，选 Public

### 2. 上传文件
将以下文件上传到仓库：
- `app.py`
- `stock_list.py`
- `requirements.txt`
- `.streamlit/config.toml`
- `stock_data.json`

### 3. 创建 GitHub Token
- 访问 https://github.com/settings/tokens
- 点 Generate new token (classic)
- Note 填 `stock-deploy`
- Expiration 选 No expiration
- 勾选 `repo` 权限
- 生成后**立即复制** `ghp_xxx` 字符串

### 4. 部署到 Streamlit Cloud
- 访问 https://share.streamlit.io
- 用 GitHub 登录 → New app
- Repository 选你的 `stock-tracker`
- Branch: `main`，Main file: `app.py`
- Advanced settings → Secrets 填入：
  ```
  REPO_OWNER = "你的GitHub用户名"
  REPO_NAME = "stock-tracker"
  GITHUB_TOKEN = "ghp_刚才复制的token"
  ```
- 点 Deploy → 等 2-3 分钟

### 5. 手机访问
浏览器打开生成的 `https://xxx.streamlit.app` → 添加到主屏幕

## 数据说明

- 数据存储在 GitHub 仓库的 `stock_data.json` 中
- 每次操作自动同步到仓库
- 支持 JSON 备份和恢复

## 风险提示

本工具仅提供数据记录与计算功能，不构成任何投资建议。行情数据来自公开接口，可能存在延迟。
