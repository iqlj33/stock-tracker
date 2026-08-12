# -*- coding: utf-8 -*-
"""
📈 股票持仓管家 - 云端版 v2.1
新增功能：截图批量导入交易记录（OCR识别 + 手动修正双轨制）
完全在手机浏览器中运行，数据自动同步到 GitHub
"""

import streamlit as st
import pandas as pd
import json
import os
import re
import requests
import base64
import io
import time
import tempfile
from datetime import datetime, date

# ==================== 页面配置 ====================
st.set_page_config(
    page_title="📈 股票持仓管家",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': "📈 股票持仓管家 v2.1 - 支持截图批量导入"
    }
)

# ==================== 配置 ====================
DATA_FILE = "stock_data.json"
REPO_OWNER = os.environ.get("REPO_OWNER", "")
REPO_NAME = os.environ.get("REPO_NAME", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = f"{REPO_OWNER}/{REPO_NAME}" if REPO_OWNER and REPO_NAME else ""

# 导入本地股票列表
try:
    from stock_list import STOCK_LIST
except ImportError:
    STOCK_LIST = []

# 导入 OCR 解析引擎
try:
    from ocr_parser import (
        parse_trade_from_text,
        parse_trade_table,
        parse_multi_stock_screenshot,
        extract_stock_code,
        extract_stock_name,
        extract_price,
        extract_quantity,
        extract_date,
        detect_action,
        create_test_screenshot,
    )
    PARSER_AVAILABLE = True
except ImportError:
    PARSER_AVAILABLE = False

# ==================== OCR 引擎（懒加载） ====================
@st.cache_resource
def load_ocr_reader():
    """懒加载 OCR 引擎，Streamlit Cloud 环境可能安装失败，需优雅降级"""
    try:
        import easyocr
        reader = easyocr.Reader(['ch_sim', 'en'], verbose=False, gpu=False)
        return reader, True
    except Exception:
        return None, False

def ocr_image(image_path):
    """对图片做 OCR，返回识别出的文本行列表"""
    reader, available = load_ocr_reader()
    if not available:
        return None
    try:
        results = reader.readtext(image_path)
        lines = [text for (_, text, _) in results]
        return lines
    except Exception:
        return None

# ==================== 数据持久化 ====================
@st.cache_data(ttl=30)
def load_data():
    """优先从GitHub拉取最新数据"""
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
            headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                content_b64 = r.json().get("content", "")
                content = base64.b64decode(content_b64).decode("utf-8")
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    f.write(content)
                return json.loads(content)
        except Exception:
            pass

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return {"stocks": {}, "transactions": [], "dividends": []}


def save_data(data):
    """保存到本地并推送到GitHub"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
            headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
            with open(DATA_FILE, "rb") as f:
                content_b64 = base64.b64encode(f.read()).decode()

            r = requests.get(url, headers=headers, timeout=10)
            sha = r.json().get("sha") if r.status_code == 200 else None

            payload = {
                "message": f"📊 数据更新 {datetime.now().strftime('%m-%d %H:%M')}",
                "content": content_b64,
                "branch": "main"
            }
            if sha:
                payload["sha"] = sha

            resp = requests.put(url, headers=headers, json=payload, timeout=15)
            if resp.status_code in (200, 201):
                st.toast("☁️ 已同步到GitHub", icon="✅")
            else:
                st.warning(f"GitHub同步失败(code:{resp.status_code})，数据保存在本地")
        except Exception as e:
            st.warning(f"GitHub同步异常: {e}")


# ==================== 行情接口 ====================
@st.cache_data(ttl=60)
def get_realtime_price(stock_code):
    """通过新浪财经接口获取实时行情"""
    try:
        code = str(stock_code).strip()
        if code.startswith(("6", "688")):
            prefix = "sh"
        elif code.startswith(("0", "3", "8")):
            prefix = "sz"
        else:
            prefix = "sh"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        headers = {"Referer": "https://finance.sina.com.cn"}
        r = requests.get(url, headers=headers, timeout=8)
        r.encoding = "gbk"
        text = r.text
        if "=" not in text or '""' in text.split("=")[1]:
            return None, None
        parts = text.split('"')[1].split(",")
        if len(parts) < 6:
            return None, None
        current_price = float(parts[3]) if parts[3] else None
        prev_close = float(parts[2]) if parts[2] else None
        change_pct = round((current_price - prev_close) / prev_close * 100, 2) if current_price and prev_close else None
        return current_price, change_pct
    except Exception:
        return None, None


@st.cache_data(ttl=3600)
def search_stocks_local(keyword):
    """本地股票列表搜索"""
    if not keyword:
        return []
    kw = keyword.strip().upper()
    results = []
    for code, name in STOCK_LIST:
        if kw in code or kw in name.upper():
            results.append((code, name))
        if len(results) >= 20:
            break
    return results


@st.cache_data(ttl=3600)
def fetch_dividend_history(stock_code):
    """通过东方财富接口获取分红历史"""
    try:
        code = str(stock_code).strip()
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_SHAREBONUS_DET",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{code}")',
            "pageNumber": "1",
            "pageSize": "50",
            "sortColumns": "EX_DIVIDEND_DATE",
            "sortTypes": "-1"
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return []
        json_data = r.json()
        records = []
        if json_data.get("result") and json_data["result"].get("data"):
            for item in json_data["result"]["data"]:
                date_str = item.get("EX_DIVIDEND_DATE", "")
                bonus = item.get("PRETAX_BONUS_RMB") or item.get("BONUS_IT_RATIO") or 0
                if date_str and bonus:
                    try:
                        records.append((date_str[:10], float(bonus)))
                    except:
                        pass
        return records
    except Exception:
        return []


# ==================== 核心计算 ====================
def compute_portfolio(data):
    """计算每只股票的持仓信息"""
    stocks_info = {}
    transactions = data.get("transactions", [])
    dividends = data.get("dividends", [])

    for t in transactions:
        code = t["code"]
        name = t["name"]
        if code not in stocks_info:
            stocks_info[code] = {
                "name": name,
                "total_shares": 0,
                "total_cost": 0.0,
                "realized_profit": 0.0,
                "cumulative_dividends": 0.0,
                "transactions": []
            }
        info = stocks_info[code]
        info["transactions"].append(t)

        if t["action"] == "买入":
            shares = int(t["shares"])
            price = float(t["price"])
            fee = float(t.get("fee", 0))
            cost = shares * price + fee
            info["total_cost"] += cost
            info["total_shares"] += shares
        elif t["action"] == "卖出":
            shares = int(t["shares"])
            price = float(t["price"])
            fee = float(t.get("fee", 0))
            sell_value = shares * price - fee
            if info["total_shares"] > 0:
                avg_cost = info["total_cost"] / info["total_shares"]
                sold_cost = avg_cost * shares
                info["total_cost"] = max(0, info["total_cost"] - sold_cost)
                info["total_shares"] -= shares
                info["realized_profit"] += (sell_value - sold_cost)

    for d in dividends:
        code = d["code"]
        if code in stocks_info:
            info = stocks_info[code]
            amount = float(d.get("amount", 0))
            info["cumulative_dividends"] += amount
            if info["total_shares"] > 0:
                info["total_cost"] = max(0, info["total_cost"] - amount)

    return stocks_info


def get_current_holdings(data):
    """获取当前持仓"""
    stocks_info = compute_portfolio(data)
    return {k: v for k, v in stocks_info.items() if v["total_shares"] > 0}


# ==================== OCR 解析引擎 ====================

def parse_trade_from_text(lines, stock_code_hint=""):
    """
    从 OCR 文本行中解析交易记录
    支持常见券商APP截图格式，返回列表 of dict
    """
    trades = []

    # 常见关键词映射
    action_map = {
        "买入": "买入", "买": "买入", "BUY": "买入", "Buy": "买入",
        "卖出": "卖出", "卖": "卖出", "SELL": "卖出", "Sell": "卖出",
    }

    # 合并所有文本，按行处理
    full_text = "\n".join(lines)

    # 尝试匹配股票代码（6位数字）
    code_pattern = re.compile(r'[（(]?\s*(\d{6})\s*[）)]?')
    # 尝试匹配股票名称（2-4个中文字符）
    name_pattern = re.compile(r'[\u4e00-\u9fa5]{2,4}')

    # 尝试匹配日期
    date_patterns = [
        re.compile(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})'),
        re.compile(r'(\d{4}年\d{1,2}月\d{1,2}日)'),
    ]

    # 尝试匹配价格（数字+小数点）
    price_pattern = re.compile(r'(\d+\.\d{2,3})')

    # 尝试匹配数量（整数，通常>=100）
    qty_pattern = re.compile(r'(\d{3,7})')

    # 尝试匹配金额
    amount_pattern = re.compile(r'[¥￥]?\s*(\d{4,8}\.\d{2})')

    # 简单策略：按行扫描，寻找包含交易关键词的行
    current_trade = None
    found_code = None
    found_name = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 检查是否有股票代码
        code_match = code_pattern.search(line)
        if code_match:
            found_code = code_match.group(1)

        # 检查是否有股票名称
        name_match = name_pattern.search(line)
        if name_match and not found_name:
            found_name = name_match.group()

        # 检查是否包含交易动作关键词
        action = None
        for kw, act in action_map.items():
            if kw in line:
                action = act
                break

        if action:
            # 开始一条新交易记录
            trade = {
                "code": found_code or stock_code_hint,
                "name": found_name or "",
                "action": action,
                "shares": 0,
                "price": 0.0,
                "fee": 0.0,
                "date": date.today().isoformat(),
                "note": "OCR导入",
                "confidence": "low"  # low/medium/high
            }

            # 尝试从同行提取价格
            prices = price_pattern.findall(line)
            if prices:
                # 第一个价格通常是成交价
                try:
                    trade["price"] = float(prices[0])
                    trade["confidence"] = "medium"
                except:
                    pass

            # 尝试提取数量
            # 在价格之后寻找数量
            qtys = qty_pattern.findall(line)
            if qtys:
                for q in qtys:
                    val = int(q)
                    if val >= 100 and val <= 10000000:
                        trade["shares"] = val
                        break

            # 尝试提取日期
            for dp in date_patterns:
                dm = dp.search(line)
                if dm:
                    raw = dm.group(1)
                    # 统一格式
                    raw = raw.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
                    parts = raw.split("-")
                    if len(parts) == 3:
                        trade["date"] = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                    break

            # 如果代码和名称都有，提高置信度
            if trade["code"] and trade["name"]:
                trade["confidence"] = "high"

            trades.append(trade)

    # 后处理：如果没找到动作但有代码，尝试整块解析
    if not trades:
        # 退化策略：从全文提取所有数字组合，让用户手动映射
        pass

    return trades


def parse_trade_table(df_text):
    """
    解析表格形式的截图（如券商的历史成交列表）
    输入：OCR识别出的多行文本
    输出：交易记录列表
    """
    trades = []
    # 尝试按表格行解析
    for line in df_text:
        # 去除多余空格
        cleaned = re.sub(r'\s+', ' ', line).strip()
        if not cleaned:
            continue

        # 尝试提取6位股票代码
        code_m = re.search(r'\d{6}', cleaned)
        if not code_m:
            continue

        code = code_m.group()
        # 提取名称（代码前面的中文）
        name_m = re.search(r'([\u4e00-\u9fa5]{2,4})\s*' + code, cleaned)
        name = name_m.group(1) if name_m else ""

        # 判断买卖
        action = "买入"  # 默认
        if any(k in cleaned for k in ["卖出", "卖", "SELL"]):
            action = "卖出"
        elif any(k in cleaned for k in ["买入", "买", "BUY"]):
            action = "买入"

        # 提取所有数字
        numbers = re.findall(r'\d+\.?\d*', cleaned)
        numbers = [float(n) for n in numbers]

        # 启发式分配：通常格式为 代码 名称 日期 价格 数量 金额
        price = 0.0
        shares = 0
        for n in numbers:
            if 1 <= n <= 1000 and price == 0:
                price = n
            elif n >= 100 and n == int(n) and shares == 0:
                shares = int(n)

        trades.append({
            "code": code,
            "name": name,
            "action": action,
            "shares": shares,
            "price": price,
            "fee": 0.0,
            "date": date.today().isoformat(),
            "note": "OCR表格导入",
            "confidence": "medium"
        })

    return trades


# ==================== UI 组件 ====================
def render_header():
    """渲染顶部标题栏"""
    st.markdown("""
    <div style='background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
                padding: 16px 20px; border-radius: 12px; margin-bottom: 16px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);'>
        <h1 style='color: white; margin: 0; font-size: 22px; font-weight: 700;'>
            📈 股票持仓管家
        </h1>
        <p style='color: rgba(255,255,255,0.7); margin: 4px 0 0 0; font-size: 12px;'>
            云端同步 · 实时行情 · 成本计算 · 分红除权 · 截图导入
        </p>
    </div>
    """, unsafe_allow_html=True)


def show_overview(data):
    """持仓总览页面"""
    st.subheader("📊 持仓总览")

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 刷新行情", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    stocks_info = compute_portfolio(data)
    holdings = {k: v for k, v in stocks_info.items() if v["total_shares"] > 0}

    if not holdings:
        st.info("📭 暂无持仓，请到「➕ 交易」页面录入第一笔操作。")
        closed = {k: v for k, v in stocks_info.items() if v["total_shares"] == 0 and v["realized_profit"] != 0}
        if closed:
            st.write("**已清仓股票收益：**")
            for code, info in closed.items():
                st.caption(f"  {code} {info['name']}: 已实现 {info['realized_profit']:.2f} 元")
        return

    rows = []
    total_market = 0.0
    total_cost_all = 0.0
    total_profit = 0.0
    total_realized = 0.0
    total_dividends = 0.0

    progress = st.progress(0, text="正在获取行情...")
    codes = list(holdings.keys())

    for i, code in enumerate(codes):
        info = holdings[code]
        progress.progress((i + 1) / len(codes), text=f"正在获取 {code} {info['name']}...")
        price, change_pct = get_realtime_price(code)

        market_val = info["total_shares"] * price if price else 0
        cost_total = info["total_cost"]
        profit = market_val - cost_total if price else 0
        profit_pct = (profit / cost_total * 100) if cost_total > 0 else 0

        if price:
            total_market += market_val
            total_cost_all += cost_total
            total_profit += profit
        total_realized += info["realized_profit"]
        total_dividends += info["cumulative_dividends"]

        avg_cost = cost_total / info["total_shares"] if info["total_shares"] > 0 else 0

        rows.append({
            "代码": code,
            "名称": info["name"],
            "持仓": info["total_shares"],
            "成本均价": round(avg_cost, 2),
            "现价": round(price, 2) if price else "—",
            "涨跌%": change_pct if change_pct is not None else "—",
            "市值": round(market_val, 2) if price else "—",
            "浮盈": round(profit, 2) if price else "—",
            "收益率%": round(profit_pct, 2) if price else "—",
            "已实现": round(info["realized_profit"], 2),
            "分红": round(info["cumulative_dividends"], 2),
        })

    progress.empty()

    st.markdown("### 💼 资产汇总")
    c1, c2, c3 = st.columns(3)
    c1.metric("总市值", f"{total_market:.2f} 元")
    c2.metric("总成本", f"{total_cost_all:.2f} 元")
    total_return_pct = (total_profit / total_cost_all * 100) if total_cost_all > 0 else 0
    c3.metric("浮动盈亏", f"{total_profit:.2f} 元",
              delta=f"{total_return_pct:.2f}%" if total_cost_all > 0 else "0%")

    c4, c5, c6 = st.columns(3)
    c4.metric("已实现收益", f"{total_realized:.2f} 元")
    c5.metric("累计分红", f"{total_dividends:.2f} 元")
    c6.metric("总收益", f"{total_profit + total_realized + total_dividends:.2f} 元")

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "现价": st.column_config.NumberColumn(format="%.2f"),
            "涨跌%": st.column_config.NumberColumn(format="%.2f%%"),
            "市值": st.column_config.NumberColumn(format="%.2f"),
            "浮盈": st.column_config.NumberColumn(format="%.2f"),
            "收益率%": st.column_config.NumberColumn(format="%.2f%%"),
            "已实现": st.column_config.NumberColumn(format="%.2f"),
            "分红": st.column_config.NumberColumn(format="%.2f"),
        }
    )


def add_transaction(data):
    """添加交易记录"""
    st.subheader("➕ 添加交易")

    with st.container(border=True):
        st.write("**🔍 选择股票**")
        keyword = st.text_input("输入股票代码或名称搜索",
                                placeholder="例如: 600519 或 茅台",
                                label_visibility="collapsed")

        if keyword:
            results = search_stocks_local(keyword)
            if results:
                options = [f"{c} - {n}" for c, n in results]
                selected = st.selectbox("搜索结果", options, label_visibility="collapsed")
                idx = options.index(selected)
                code = results[idx][0]
                name = results[idx][1]
                st.success(f"✅ {code} {name}")
            else:
                st.warning("未找到匹配的股票，可手动输入下方")
                code = st.text_input("股票代码（手动）", key="manual_code")
                name = st.text_input("股票名称（手动）", key="manual_name")
        else:
            code = ""
            name = ""

    st.divider()

    with st.form("trade_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        action = col1.selectbox("操作类型", ["买入", "卖出"])

        holdings = get_current_holdings(data)
        current_shares = holdings.get(code, {}).get("total_shares", 0) if code else 0
        if code and current_shares > 0:
            col2.write(f"当前持仓: **{current_shares}** 股")

        shares = st.number_input("数量（股）", min_value=1, step=100, value=100)
        col3, col4 = st.columns(2)
        price = col3.number_input("成交价格（元）", min_value=0.01, format="%.3f", value=10.0)
        fee = col4.number_input("手续费（元）", min_value=0.0, format="%.2f", value=0.0)

        trade_date = st.date_input("交易日期", value=date.today())
        note = st.text_input("备注（可选）")

        submitted = st.form_submit_button("💾 保存交易", use_container_width=True)

        if submitted:
            if not code or not name:
                st.error("❌ 请先选择或输入股票")
            elif shares <= 0:
                st.error("❌ 数量必须大于0")
            elif price <= 0:
                st.error("❌ 价格必须大于0")
            elif action == "卖出" and shares > current_shares:
                st.error(f"❌ 卖出数量({shares})超过当前持仓({current_shares})")
            else:
                transaction = {
                    "code": code,
                    "name": name,
                    "action": action,
                    "shares": int(shares),
                    "price": float(price),
                    "fee": float(fee),
                    "date": trade_date.isoformat(),
                    "note": note,
                    "timestamp": datetime.now().isoformat()
                }
                data["transactions"].append(transaction)
                save_data(data)
                st.success(f"✅ 已记录: {action} {name}({code}) {shares}股 @ {price}元")
                time.sleep(1)
                st.rerun()


def show_transactions(data):
    """交易明细页面"""
    st.subheader("📋 交易明细")

    if not data["transactions"]:
        st.info("📭 暂无交易记录")
        return

    codes = sorted(set(t["code"] for t in data["transactions"]))
    name_map = {t["code"]: t["name"] for t in data["transactions"]}
    options = ["全部"] + [f"{c} - {name_map[c]}" for c in codes]
    selected = st.selectbox("筛选股票", options)

    if selected == "全部":
        filtered = list(enumerate(data["transactions"]))
    else:
        code = selected.split(" - ")[0]
        filtered = [(i, t) for i, t in enumerate(data["transactions"]) if t["code"] == code]

    rows = []
    for i, t in filtered:
        rows.append({
            "#": i,
            "日期": t["date"],
            "代码": t["code"],
            "名称": t["name"],
            "操作": t["action"],
            "数量": t["shares"],
            "价格": t["price"],
            "手续费": t.get("fee", 0),
            "备注": t.get("note", ""),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("🗑️ 删除交易记录（不可恢复）"):
        del_idx = st.number_input("输入要删除的交易序号(#)",
                                   min_value=0,
                                   max_value=len(data["transactions"]) - 1,
                                   step=1)
        st.write(f"将删除: `{data['transactions'][del_idx]}`")
        if st.button("⚠️ 确认删除", type="primary"):
            del data["transactions"][del_idx]
            save_data(data)
            st.success("✅ 已删除")
            time.sleep(1)
            st.rerun()


def manage_dividends(data):
    """分红管理页面"""
    st.subheader("💰 分红记录")

    codes_in_portfolio = sorted(set(t["code"] for t in data["transactions"]))

    if codes_in_portfolio:
        st.write("**一键查询持仓股票分红历史：**")
        cols = st.columns(min(len(codes_in_portfolio), 3))
        for i, code in enumerate(codes_in_portfolio):
            name = next(t["name"] for t in data["transactions"] if t["code"] == code)
            with cols[i % 3]:
                if st.button(f"🔍 {code} {name}", use_container_width=True):
                    with st.spinner(f"查询 {code} 分红..."):
                        records = fetch_dividend_history(code)
                    if records:
                        added = 0
                        for date_str, per_share in records:
                            exists = any(d["code"] == code and d["date"] == date_str
                                         for d in data["dividends"])
                            if not exists:
                                data["dividends"].append({
                                    "code": code,
                                    "date": date_str,
                                    "per_share": per_share,
                                    "amount": 0,
                                    "note": ""
                                })
                                added += 1
                        save_data(data)
                        st.success(f"✅ 新增 {added} 条记录，请填写金额")
                        st.rerun()
                    else:
                        st.warning("未查到分红数据")

    st.divider()

    if data["dividends"]:
        st.write("**已有分红记录：**")
        rows = []
        for i, d in enumerate(data["dividends"]):
            rows.append({
                "#": i,
                "代码": d["code"],
                "除权除息日": d["date"],
                "每股分红": d.get("per_share", 0),
                "实际金额": d.get("amount", 0),
                "备注": d.get("note", ""),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        with st.expander("✏️ 编辑分红金额"):
            edit_idx = st.number_input("选择记录序号(#)",
                                        min_value=0,
                                        max_value=len(data["dividends"]) - 1,
                                        step=1)
            record = data["dividends"][edit_idx]
            st.caption(f"当前: {record}")
            col1, col2 = st.columns(2)
            new_amount = col1.number_input("实际到手金额（元）",
                                            value=float(record.get("amount", 0)),
                                            format="%.2f")
            new_note = col2.text_input("备注", value=record.get("note", ""))
            c1, c2 = st.columns(2)
            if c1.button("💾 更新"):
                data["dividends"][edit_idx]["amount"] = new_amount
                data["dividends"][edit_idx]["note"] = new_note
                save_data(data)
                st.success("✅ 已更新")
                st.rerun()
            if c2.button("🗑️ 删除", type="primary"):
                del data["dividends"][edit_idx]
                save_data(data)
                st.success("✅ 已删除")
                st.rerun()
    else:
        st.info("暂无分红记录")

    with st.expander("➕ 手动添加分红"):
        col1, col2 = st.columns(2)
        code = col1.text_input("股票代码")
        div_date = col2.date_input("除权除息日")
        col3, col4 = st.columns(2)
        per_share = col3.number_input("每股分红（元）", min_value=0.0, format="%.4f")
        amount = col4.number_input("实际到手金额（元）", min_value=0.0, format="%.2f")
        note = st.text_input("备注")
        if st.button("💾 添加分红记录"):
            if not code:
                st.error("请输入股票代码")
            else:
                data["dividends"].append({
                    "code": code,
                    "date": div_date.isoformat(),
                    "per_share": per_share,
                    "amount": amount,
                    "note": note
                })
                save_data(data)
                st.success("✅ 已添加")
                st.rerun()


def screenshot_import(data):
    """
    📸 截图批量导入交易记录
    支持：拍照上传 / 相册选择 → OCR识别 → 手动修正 → 批量确认导入
    """
    st.subheader("📸 截图批量导入")
    st.caption("上传券商APP的交易截图，自动识别交易信息，确认后批量导入")

    # ---- 检查OCR可用性 ----
    reader, ocr_available = load_ocr_reader()
    if not ocr_available:
        st.warning("""
        ⚠️ **当前环境未安装 OCR 引擎**

        已为你启用「手动录入模式」：上传截图后，可以手动逐条录入交易信息。
        如需自动识别，请在本地安装 `easyocr` 后部署。

        ```bash
        pip install easyocr
        ```
        """)
    else:
        st.success("✅ OCR 引擎已就绪，可自动识别截图内容")

    st.divider()

    # ---- 上传区域 ----
    uploaded_files = st.file_uploader(
        "📷 上传交易截图（支持多张）",
        type=["png", "jpg", "jpeg", "bmp", "webp"],
        accept_multiple_files=True,
        help="支持券商APP的成交明细、持仓截图等"
    )

    if not uploaded_files:
        with st.expander("📖 使用说明（点击展开）", expanded=True):
            st.markdown("""
            ### 操作步骤

            **方式A：自动识别（推荐）**
            1. 在券商APP截图交易记录页面
            2. 上传截图 → 系统自动OCR识别
            3. 检查识别结果，修正错误字段
            4. 点击「批量导入」完成

            **方式B：手动录入**
            1. 上传截图作为参考（可选）
            2. 手动填写每只股票的代码、操作、数量、价格
            3. 逐条添加或批量导入

            ### 📱 截图技巧
            - 尽量截取**单只股票**的成交明细，避免多只混排
            - 确保文字清晰，光线充足
            - 横屏截图效果更好
            - 支持的券商APP：同花顺、东方财富、华泰、中信等主流APP

            ### ⚠️ 注意事项
            - OCR识别率约 70-90%，**务必人工核对**
            - 价格、数量是最关键的字段，请重点检查
            - 识别错误时可直接在表格中修改
            """)
        return

    # ---- 处理每张图片 ----
    # 用 session_state 累积跨图片的交易
    if "parsed_trades_all" not in st.session_state:
        st.session_state.parsed_trades_all = []

    for img_idx, uploaded_file in enumerate(uploaded_files):
        st.markdown(f"### 🖼️ 图片 {img_idx + 1}: `{uploaded_file.name}`")

        image_bytes = uploaded_file.read()
        uploaded_file.seek(0)

        col_img, col_actions = st.columns([1, 1])
        with col_img:
            st.image(image_bytes, use_container_width=True)

        # 保存临时文件
        tmp_path = os.path.join(tempfile.gettempdir(), f"ocr_input_{img_idx}.png")
        with open(tmp_path, "wb") as f:
            f.write(image_bytes)

        # OCR识别 + 解析
        parsed_trades = []
        if ocr_available and PARSER_AVAILABLE:
            with st.spinner("🔍 正在识别图片内容..."):
                lines = ocr_image(tmp_path)
                if lines:
                    st.caption(f"识别出 {len(lines)} 行文本：")
                    with st.expander("查看原始识别文本", expanded=False):
                        for i, line in enumerate(lines):
                            st.text(f"[{i}] {line}")

                    # 先尝试精确解析
                    parsed_trades = parse_trade_from_text(lines)
                    if not parsed_trades:
                        parsed_trades = parse_trade_table(lines)
                    if not parsed_trades:
                        # 最后尝试多股票截图解析
                        parsed_trades = parse_multi_stock_screenshot(lines)

        with col_actions:
            if parsed_trades:
                st.success(f"✅ 识别到 {len(parsed_trades)} 条交易记录")
                conf_color = {"high": "🟢", "medium": "🟡", "low": "🔴"}
                for i, t in enumerate(parsed_trades):
                    st.caption(f"{conf_color.get(t.get('confidence','low'), '⚪')} "
                              f"{t['action']} {t['code']} {t['name']} "
                              f"{t['shares']}股 @ {t['price']}元")
            else:
                if ocr_available:
                    st.warning("⚠️ 未能自动识别，请手动录入")
                else:
                    st.info("请手动录入交易信息")

        # ---- 编辑区域 ----
        st.write("**编辑交易信息（确认无误后导入）：**")

        if parsed_trades:
            # 编辑识别结果
            edited_trades = []
            for t_idx, trade in enumerate(parsed_trades):
                with st.container(border=True):
                    c1, c2 = st.columns([2, 2])
                    search_kw = c1.text_input(
                        f"股票搜索##{img_idx}_{t_idx}",
                        value=trade.get("name", ""),
                        placeholder="搜索股票名称/代码"
                    )
                    selected_code = trade.get("code", "")
                    selected_name = trade.get("name", "")
                    if search_kw:
                        results = search_stocks_local(search_kw)
                        if results:
                            opts = [f"{c} - {n}" for c, n in results]
                            sel = c2.selectbox(f"选择##{img_idx}_{t_idx}", opts, label_visibility="collapsed")
                            if sel:
                                selected_code = sel.split(" - ")[0]
                                selected_name = sel.split(" - ")[1]

                    c3, c4, c5, c6 = st.columns(4)
                    action = c3.selectbox(
                        f"操作##{img_idx}_{t_idx}",
                        ["买入", "卖出"],
                        index=0 if trade.get("action", "买入") == "买入" else 1
                    )
                    shares = c4.number_input(
                        f"数量##{img_idx}_{t_idx}",
                        min_value=0, step=100,
                        value=int(trade.get("shares", 100) or 100)
                    )
                    price = c5.number_input(
                        f"价格##{img_idx}_{t_idx}",
                        min_value=0.0, format="%.3f",
                        value=float(trade.get("price", 0) or 0)
                    )
                    fee = c6.number_input(
                        f"手续费##{img_idx}_{t_idx}",
                        min_value=0.0, format="%.2f",
                        value=float(trade.get("fee", 0) or 0)
                    )
                    trade_date = c1.date_input(
                        f"日期##{img_idx}_{t_idx}",
                        value=datetime.strptime(
                            trade.get("date", date.today().isoformat())[:10], "%Y-%m-%d"
                        ).date()
                    )

                    edited_trades.append({
                        "code": selected_code,
                        "name": selected_name,
                        "action": action,
                        "shares": int(shares),
                        "price": float(price),
                        "fee": float(fee),
                        "date": trade_date.isoformat(),
                        "note": f"OCR导入(图{img_idx+1})",
                        "confidence": trade.get("confidence", "low")
                    })

                    if st.button(f"🗑️ 删除此条##{img_idx}_{t_idx}", key=f"del_{img_idx}_{t_idx}"):
                        edited_trades.pop()
                        st.rerun()

            st.session_state.parsed_trades_all.extend(edited_trades)
        else:
            # 纯手动录入
            with st.form(key=f"manual_form_{img_idx}"):
                st.write("**手动录入交易信息：**")
                mc1, mc2 = st.columns(2)
                search_kw = mc1.text_input(f"搜索股票##manual_{img_idx}", placeholder="输入名称或代码")
                selected_code = ""
                selected_name = ""
                if search_kw:
                    results = search_stocks_local(search_kw)
                    if results:
                        opts = [f"{c} - {n}" for c, n in results]
                        sel = mc2.selectbox(f"选择##manual_{img_idx}", opts, label_visibility="collapsed")
                        if sel:
                            selected_code = sel.split(" - ")[0]
                            selected_name = sel.split(" - ")[1]

                mc3, mc4, mc5, mc6 = st.columns(4)
                m_action = mc3.selectbox(f"操作##manual_a_{img_idx}", ["买入", "卖出"])
                m_shares = mc4.number_input(f"数量##manual_s_{img_idx}", min_value=0, step=100, value=100)
                m_price = mc5.number_input(f"价格##manual_p_{img_idx}", min_value=0.0, format="%.3f", value=10.0)
                m_fee = mc6.number_input(f"手续费##manual_f_{img_idx}", min_value=0.0, format="%.2f", value=0.0)
                m_date = mc1.date_input(f"日期##manual_d_{img_idx}", value=date.today())

                if st.form_submit_button("➕ 添加到导入列表", use_container_width=True):
                    if selected_code and selected_name:
                        st.session_state.parsed_trades_all.append({
                            "code": selected_code,
                            "name": selected_name,
                            "action": m_action,
                            "shares": int(m_shares),
                            "price": float(m_price),
                            "fee": float(m_fee),
                            "date": m_date.isoformat(),
                            "note": f"手动录入(图{img_idx+1})",
                            "confidence": "high"
                        })
                        st.success(f"✅ 已添加: {m_action} {selected_name} {m_shares}股")
                        st.rerun()
                    else:
                        st.error("请先搜索并选择股票")

        st.divider()

    # ---- 汇总确认导入 ----
    all_trades = st.session_state.parsed_trades_all
    if all_trades:
        st.markdown("---")
        st.markdown(f"### ✅ 待导入交易 ({len(all_trades)} 条)")

        preview_rows = []
        for i, t in enumerate(all_trades):
            preview_rows.append({
                "#": i,
                "日期": t["date"],
                "代码": t["code"],
                "名称": t["name"],
                "操作": t["action"],
                "数量": t["shares"],
                "价格": t["price"],
                "手续费": t.get("fee", 0),
                "备注": t.get("note", ""),
            })
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

        # 持仓冲突检查
        holdings = get_current_holdings(data)
        warnings = []
        for t in all_trades:
            if t["action"] == "卖出":
                cur = holdings.get(t["code"], {}).get("total_shares", 0)
                if t["shares"] > cur:
                    warnings.append(f"⚠️ {t['code']} {t['name']}: 卖出{t['shares']}股但仅持仓{cur}股")

        for w in warnings:
            st.warning(w)

        col_confirm, col_clear = st.columns(2)
        with col_confirm:
            btn_label = "🚀 确认批量导入" if "confirm_import" not in st.session_state else "⚠️ 再次点击确认导入"
            if st.button(btn_label, type="primary", use_container_width=True):
                if "confirm_import" not in st.session_state:
                    st.session_state.confirm_import = True
                    st.rerun()
                else:
                    for t in all_trades:
                        data["transactions"].append({
                            "code": t["code"],
                            "name": t["name"],
                            "action": t["action"],
                            "shares": int(t["shares"]),
                            "price": float(t["price"]),
                            "fee": float(t.get("fee", 0)),
                            "date": t["date"],
                            "note": t.get("note", ""),
                            "timestamp": datetime.now().isoformat()
                        })
                    save_data(data)
                    st.session_state.parsed_trades_all = []
                    st.session_state.pop("confirm_import", None)
                    st.success(f"🎉 成功导入 {len(all_trades)} 条交易记录！")
                    time.sleep(1)
                    st.rerun()

        with col_clear:
            if st.button("🗑️ 清空列表", use_container_width=True):
                st.session_state.parsed_trades_all = []
                st.session_state.pop("confirm_import", None)
                st.rerun()


def export_import_page(data):
    """导出导入页面"""
    st.subheader("📤 导出 / 导入")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**导出为 Excel**")
        if st.button("📊 生成 Excel 文件", use_container_width=True):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                stocks_info = compute_portfolio(data)
                overview_rows = []
                for code, info in stocks_info.items():
                    price, _ = get_realtime_price(code)
                    cost_total = info["total_cost"]
                    market_val = info["total_shares"] * price if price else 0
                    avg_cost = cost_total / info["total_shares"] if info["total_shares"] > 0 else 0
                    overview_rows.append({
                        "代码": code,
                        "名称": info["name"],
                        "持仓(股)": info["total_shares"],
                        "平均成本": round(avg_cost, 2),
                        "现价": price if price else "N/A",
                        "市值": round(market_val, 2) if price else "N/A",
                        "浮动盈亏": round(market_val - cost_total, 2) if price else "N/A",
                        "已实现收益": round(info["realized_profit"], 2),
                        "累计分红": round(info["cumulative_dividends"], 2),
                    })
                pd.DataFrame(overview_rows).to_excel(writer, sheet_name="持仓总览", index=False)

                tx_rows = []
                for t in data["transactions"]:
                    tx_rows.append({
                        "日期": t["date"], "代码": t["code"], "名称": t["name"],
                        "操作": t["action"], "数量": t["shares"], "价格": t["price"],
                        "手续费": t.get("fee", 0), "备注": t.get("note", ""),
                    })
                pd.DataFrame(tx_rows).to_excel(writer, sheet_name="交易明细", index=False)

                div_rows = []
                for d in data["dividends"]:
                    div_rows.append({
                        "代码": d["code"], "除权除息日": d["date"],
                        "每股分红": d.get("per_share", 0),
                        "实际金额": d.get("amount", 0), "备注": d.get("note", ""),
                    })
                pd.DataFrame(div_rows).to_excel(writer, sheet_name="分红记录", index=False)

            output.seek(0)
            st.download_button(
                "📥 下载 Excel",
                data=output,
                file_name=f"股票持仓_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    with col2:
        st.write("**导出为 JSON 备份**")
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        st.download_button(
            "📥 下载 JSON 备份",
            data=json_str,
            file_name=f"stock_backup_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json",
            use_container_width=True
        )

        st.divider()
        st.write("**从 JSON 恢复**")
        uploaded = st.file_uploader("上传备份文件", type=["json"])
        if uploaded is not None:
            try:
                restored = json.loads(uploaded.read().decode("utf-8"))
                if st.button("⚠️ 确认恢复（覆盖当前数据）", type="primary"):
                    save_data(restored)
                    st.success("✅ 数据已恢复")
                    st.rerun()
            except Exception as e:
                st.error(f"文件解析失败: {e}")


# ==================== 主程序 ====================
def main():
    render_header()
    data = load_data()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 持仓", "➕ 交易", "📋 明细", "💰 分红", "📸 截图导入", "📤 备份"
    ])

    with tab1:
        show_overview(data)
    with tab2:
        add_transaction(data)
    with tab3:
        show_transactions(data)
    with tab4:
        manage_dividends(data)
    with tab5:
        screenshot_import(data)
    with tab6:
        export_import_page(data)

    st.divider()
    st.caption(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
               f"⚠️ 数据仅供参考，不构成投资建议")

if __name__ == "__main__":
    main()
