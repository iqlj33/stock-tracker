import streamlit as st
import pandas as pd
import json
import os
import requests
from datetime import datetime, date
import io
import base64

st.set_page_config(page_title="股票持仓管家", layout="wide", initial_sidebar_state="collapsed")

DATA_FILE = "stock_data.json"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_OWNER = os.environ.get("REPO_OWNER", "")
REPO_NAME = os.environ.get("REPO_NAME", "")

# ==================== 数据持久化 ====================
def load_data():
    if not os.path.exists(DATA_FILE):
        default = {"stocks": {}, "transactions": [], "dividends": []}
        save_data(default)
        return default
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if GITHUB_TOKEN and REPO_OWNER and REPO_NAME:
        try:
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{DATA_FILE}"
            headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
            with open(DATA_FILE, "rb") as f:
                content = base64.b64encode(f.read()).decode()
            r = requests.get(url, headers=headers)
            sha = r.json().get("sha") if r.status_code == 200 else None
            payload = {"message": f"Update data {datetime.now().isoformat()}", "content": content, "branch": "main"}
            if sha:
                payload["sha"] = sha
            requests.put(url, headers=headers, json=payload)
        except:
            pass

# ==================== 行情接口 ====================
def get_realtime_price(stock_code):
    try:
        code = str(stock_code).strip()
        if code.startswith("6") or code.startswith("688"):
            symbol = f"sh{code}"
        elif code.startswith("0") or code.startswith("3") or code.startswith("8") or code.startswith("4"):
            symbol = f"sz{code}"
        else:
            # 尝试默认
            symbol = f"sh{code}"
        url = f"https://qt.gtimg.cn/q={symbol}"
        r = requests.get(url, timeout=5)
        r.encoding = "gbk"
        text = r.text
        parts = text.split("~")
        if len(parts) >= 40:
            price = float(parts[3]) if parts[3] else None
            change_pct = float(parts[32]) if parts[32] else None
            name_from_api = parts[1] if len(parts) > 1 else ""
            return price, change_pct, name_from_api
        return None, None, ""
    except:
        return None, None, ""

def search_stocks(keyword):
    """模糊搜索股票，返回 [(code, name), ...]"""
    try:
        from stock_list import STOCK_LIST
        keyword = keyword.strip().upper()
        results = []
        for code, name in STOCK_LIST:
            if keyword in code.upper() or keyword.upper() in name.upper() or keyword in name:
                results.append((code, name))
        return results[:30]
    except:
        return []

# ==================== 核心计算 ====================
def compute_portfolio(data):
    stocks_info = {}
    transactions = data.get("transactions", [])
    dividends = data.get("dividends", [])
    for t in transactions:
        code = t["code"]
        name = t["name"]
        if code not in stocks_info:
            stocks_info[code] = {"name": name, "total_shares": 0, "total_cost": 0.0,
                                 "realized_profit": 0.0, "cumulative_dividends": 0.0}
        info = stocks_info[code]
        if t["action"] == "买入":
            shares = int(t["shares"])
            price = float(t["price"])
            fee = float(t.get("fee", 0))
            cost = shares * price + fee
            if info["total_shares"] == 0:
                info["total_cost"] = cost
            else:
                avg = info["total_cost"] / info["total_shares"]
                info["total_cost"] = avg * info["total_shares"] + cost
            info["total_shares"] += shares
        elif t["action"] == "卖出":
            shares = int(t["shares"])
            price = float(t["price"])
            fee = float(t.get("fee", 0))
            sell_value = shares * price - fee
            if info["total_shares"] > 0:
                avg = info["total_cost"] / info["total_shares"]
                sold_cost = avg * shares
                info["total_cost"] -= sold_cost
                info["total_shares"] -= shares
                info["realized_profit"] += (sell_value - sold_cost)
    for d in dividends:
        code = d["code"]
        if code in stocks_info:
            amount = float(d["amount"])
            stocks_info[code]["cumulative_dividends"] += amount
            if stocks_info[code]["total_shares"] > 0:
                stocks_info[code]["total_cost"] -= amount
    return stocks_info

# ==================== 主界面 ====================
def main():
    st.title("📈 股票持仓管家")
    data = load_data()
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 持仓总览", "➕ 添加交易", "📋 交易明细", "💰 分红记录", "📤 导出数据"
    ])
    with tab1:
        show_overview(data)
    with tab2:
        add_transaction_tab(data)
    with tab3:
        show_transactions(data)
    with tab4:
        manage_dividends(data)
    with tab5:
        export_data(data)

# ==================== 持仓总览 ====================
def show_overview(data):
    st.subheader("持仓总览")
    if st.button("🔄 刷新行情"):
        st.rerun()
    stocks_info = compute_portfolio(data)
    if not stocks_info:
        st.info("暂无持仓，请在「添加交易」中录入")
        return
    rows = []
    total_market = 0
    total_cost_all = 0
    total_dividends = 0
    for code, info in stocks_info.items():
        price, change, _ = get_realtime_price(code)
        if price:
            market_val = info["total_shares"] * price
            profit = market_val - info["total_cost"]
            profit_pct = (profit / info["total_cost"] * 100) if info["total_cost"] > 0 else 0
            total_market += market_val
            total_cost_all += info["total_cost"]
            total_dividends += info["cumulative_dividends"]
            rows.append({
                "代码": code, "名称": info["name"],
                "持仓": info["total_shares"], "成本": round(info["total_cost"], 2),
                "现价": round(price, 2), "市值": round(market_val, 2),
                "浮动盈亏": round(profit, 2), "收益率%": round(profit_pct, 2),
                "已实现收益": round(info["realized_profit"], 2),
                "累计分红": round(info["cumulative_dividends"], 2)
            })
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总市值", f"{total_market:.2f}")
    col2.metric("总成本", f"{total_cost_all:.2f}")
    col3.metric("总浮动盈亏", f"{total_market - total_cost_all:.2f}")
    col4.metric("累计分红", f"{total_dividends:.2f}")
    df = pd.DataFrame(rows)
    st.dataframe(df, width='stretch', hide_index=True)

# ==================== 添加交易 ====================
def add_transaction_tab(data):
    st.subheader("添加交易")
    with st.form("add_trade", clear_on_submit=False):
        # ---- 股票搜索/选择 ----
        st.markdown("**股票搜索**")
        keyword = st.text_input(
            "输入股票名称或代码（模糊匹配）",
            key="keyword_input",
            placeholder="如：茅台、600519、宁德、300750"
        )
        # 搜索按钮
        search_clicked = st.form_submit_button("🔍 搜索股票")
        if search_clicked and keyword:
            results = search_stocks(keyword)
            if results:
                st.session_state.search_results = results
                st.session_state.selected_stock = None  # 重置选择
            else:
                st.session_state.search_results = []
                st.warning("未找到匹配的股票，请尝试其他关键词")

        # 显示搜索结果供选择
        selected_code = ""
        selected_name = ""
        if "search_results" in st.session_state and st.session_state.search_results:
            results = st.session_state.search_results
            # 用 selectbox 展示
            opts = [f"{c} - {n}" for c, n in results]
            chosen = st.selectbox("选择股票", opts, key="stock_select")
            if chosen:
                selected_code = chosen.split(" - ")[0].strip()
                selected_name = chosen.split(" - ")[1].strip()
                st.caption(f"✅ 已选择：**{selected_name}**（{selected_code}）")
        else:
            # 如果没有搜索，允许手动输入
            col_a, col_b = st.columns(2)
            selected_code = col_a.text_input("股票代码", key="manual_code", placeholder="如 600519")
            selected_name = col_b.text_input("股票名称", key="manual_name", placeholder="如 贵州茅台")

        st.divider()

        # ---- 交易信息 ----
        col1, col2 = st.columns(2)
        with col1:
            action = st.selectbox("操作", ["买入", "卖出"], key="action_select")
        with col2:
            # 数量：最低100，步长100，默认100
            shares = st.number_input(
                "数量（股）", min_value=100, step=100, value=100,
                key="shares_input"
            )

        col3, col4 = st.columns(2)
        with col3:
            price = st.number_input(
                "价格（元）", min_value=0.01, step=0.01, format="%.3f",
                key="price_input", value=0.01
            )
        with col4:
            # 手续费默认5
            fee = st.number_input(
                "手续费（元）", min_value=0.0, step=0.01, format="%.2f",
                key="fee_input", value=5.0
            )

        td = st.date_input("交易日期", value=date.today(), key="date_input")

        # ---- 实时预览 ----
        if price > 0 and shares >= 100:
            total = shares * price + fee
            st.caption(f"💰 本次交易总额：**{total:.2f} 元**（含手续费 {fee:.2f} 元）")

        st.divider()

        # ---- 提交按钮 ----
        submitted = st.form_submit_button("💾 保存交易")
        if submitted:
            code = selected_code.strip()
            name = selected_name.strip()

            # 校验
            errors = []
            if not code:
                errors.append("请选择或输入股票代码")
            if not name:
                errors.append("请选择或输入股票名称")
            if shares < 100:
                errors.append("数量不能低于100股")
            if shares % 100 != 0:
                errors.append("数量必须是100的整数倍")
            if price <= 0:
                errors.append("价格必须大于0")
            if fee < 0:
                errors.append("手续费不能为负数")

            # 卖出时检查持仓
            if not errors and action == "卖出":
                portfolio = compute_portfolio(data)
                current = portfolio.get(code, {}).get("total_shares", 0)
                if shares > current:
                    errors.append(f"卖出数量({shares})超过当前持仓({current})")

            if errors:
                for e in errors:
                    st.error(f"❌ {e}")
                # 不 return，保持表单内已填信息
            else:
                data["transactions"].append({
                    "code": code, "name": name, "action": action,
                    "shares": shares, "price": price, "fee": fee,
                    "date": td.isoformat(), "timestamp": datetime.now().isoformat()
                })
                save_data(data)
                st.success(f"✅ 已保存：{action} {name}({code}) {shares}股 @ {price}元")
                # 清空搜索结果，方便下次录入
                if "search_results" in st.session_state:
                    del st.session_state.search_results
                if "stock_select" in st.session_state:
                    del st.session_state.stock_select
                st.rerun()

# ==================== 交易明细 ====================
def show_transactions(data):
    st.subheader("交易明细")
    if not data["transactions"]:
        st.info("暂无记录")
        return

    # 构建筛选选项：按 "名称 (代码)" 格式显示
    code_name_map = {}
    for t in data["transactions"]:
        code_name_map[t["code"]] = t["name"]
    filter_options = ["全部"] + [f"{n} ({c})" for c, n in sorted(code_name_map.items(), key=lambda x: x[1])]

    sel = st.selectbox("筛选股票", filter_options, key="filter_select")
    if sel == "全部":
        filtered = data["transactions"]
    else:
        # 从 "名称 (代码)" 中提取代码
        code = sel.split("(")[-1].rstrip(")")
        filtered = [t for t in data["transactions"] if t["code"] == code]

    if not filtered:
        st.info("该股票暂无交易记录")
        return

    # 按日期倒序
    filtered_sorted = sorted(filtered, key=lambda x: x.get("date", ""), reverse=True)

    # 展示
    rows = []
    for t in filtered_sorted:
        rows.append({
            "日期": t["date"],
            "代码": t["code"],
            "名称": t["name"],
            "操作": t["action"],
            "数量": t["shares"],
            "价格": t["price"],
            "手续费": t.get("fee", 0),
            "总额": round(t["shares"] * t["price"] + t.get("fee", 0), 2)
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, width='stretch', hide_index=True)

    # 删除功能
    st.divider()
    st.markdown("**删除交易记录**")
    del_idx = st.number_input("输入要删除的记录序号（从上往下数，从1开始）",
                               min_value=0, step=1, value=0, key="del_idx")
    if st.button("🗑️ 删除该记录", key="del_btn"):
        if del_idx > 0 and del_idx <= len(filtered_sorted):
            target = filtered_sorted[del_idx - 1]
            data["transactions"].remove(target)
            save_data(data)
            st.success(f"已删除：{target['name']}({target['code']}) {target['action']} {target['shares']}股")
            st.rerun()
        elif del_idx > 0:
            st.error("序号超出范围")

# ==================== 分红记录 ====================
def manage_dividends(data):
    st.subheader("分红记录")
    st.info("分红功能：输入股票代码和金额，自动扣减持仓成本")
    with st.form("add_div"):
        code = st.text_input("股票代码")
        div_date = st.date_input("除权除息日")
        amount = st.number_input("分红金额（元）", min_value=0.0, format="%.2f")
        if st.form_submit_button("添加分红"):
            if code and amount > 0:
                data["dividends"].append({
                    "code": code, "date": div_date.isoformat(), "amount": amount
                })
                save_data(data)
                st.success("已添加")
                st.rerun()
    if data["dividends"]:
        st.write("已有分红记录：")
        df = pd.DataFrame(data["dividends"])
        st.dataframe(df, width='stretch', hide_index=True)

# ==================== 导出数据 ====================
def export_data(data):
    st.subheader("导出数据")
    if st.button("导出为JSON"):
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        b64 = base64.b64encode(json_str.encode()).decode()
        href = f'<a href="data:application/json;base64,{b64}" download="stock_data_backup.json">点击下载JSON备份</a>'
        st.markdown(href, unsafe_allow_html=True)
    uploaded = st.file_uploader("导入JSON备份", type=["json"])
    if uploaded:
        try:
            imported = json.load(uploaded)
            if "transactions" in imported and "dividends" in imported:
                data["transactions"] = imported["transactions"]
                data["dividends"] = imported["dividends"]
                save_data(data)
                st.success("导入成功！")
                st.rerun()
        except:
            st.error("文件格式错误")

if __name__ == "__main__":
    main()
