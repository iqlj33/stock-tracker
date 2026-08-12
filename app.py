import streamlit as st
import pandas as pd
import json
import os
import requests
import base64
from datetime import datetime, date
import time
import io

# ==================== 配置 ====================
st.set_page_config(page_title="股票持仓管家", layout="wide", initial_sidebar_state="collapsed")

DATA_FILE = "stock_data.json"
GITHUB_REPO = f"{os.environ.get('REPO_OWNER','')}/{os.environ.get('REPO_NAME','')}"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ==================== 数据持久化 ====================
def load_data():
    if not os.path.exists(DATA_FILE):
        default = {"stocks": {}, "transactions": [], "dividends": []}
        save_data(default)
        return default
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        default = {"stocks": {}, "transactions": [], "dividends": []}
        return default

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            with open(DATA_FILE, "rb") as f:
                content = base64.b64encode(f.read()).decode()
            r = requests.get(url, headers=headers, timeout=10)
            sha = r.json().get("sha") if r.status_code == 200 else None
            payload = {
                "message": f"Update data {datetime.now().isoformat()}",
                "content": content,
                "branch": "main"
            }
            if sha:
                payload["sha"] = sha
            requests.put(url, headers=headers, json=payload, timeout=15)
        except Exception as e:
            print(f"GitHub sync failed: {e}")

# ==================== 行情接口 ====================
def get_realtime_price(stock_code):
    try:
        code_str = str(stock_code).strip()
        if code_str.startswith("6") or code_str.startswith("688"):
            symbol = f"sh{code_str}"
        elif code_str.startswith("0") or code_str.startswith("3"):
            symbol = f"sz{code_str}"
        else:
            return None, None
        url = f"https://qt.gtimg.cn/q={symbol}"
        resp = requests.get(url, timeout=5)
        resp.encoding = "gbk"
        text = resp.text
        parts = text.split("~")
        if len(parts) < 10:
            return None, None
        price = float(parts[3])
        change_pct = float(parts[32]) if len(parts) > 32 else 0
        return price, change_pct
    except Exception as e:
        return None, None

def search_stocks(keyword):
    try:
        from stock_list import STOCK_LIST
    except ImportError:
        return []
    keyword = keyword.strip().upper()
    results = []
    for code, name in STOCK_LIST:
        if keyword in code.upper() or keyword in name.upper():
            results.append((code, name))
        if len(results) >= 20:
            break
    return results

# ==================== 核心计算 ====================
def compute_portfolio(data):
    stocks_info = {}
    transactions = data.get("transactions", [])
    dividends = data.get("dividends", [])

    for t in sorted(transactions, key=lambda x: x.get("timestamp", "")):
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
                info["total_cost"] -= sold_cost
                info["total_shares"] -= shares
                info["realized_profit"] += (sell_value - sold_cost)

    for d in dividends:
        code = d["code"]
        if code in stocks_info:
            amount = float(d.get("amount", 0))
            stocks_info[code]["cumulative_dividends"] += amount
            if stocks_info[code]["total_shares"] > 0:
                stocks_info[code]["total_cost"] -= amount

    return stocks_info

def get_current_shares(data, code):
    """获取某只股票当前持仓"""
    shares = 0
    for t in data.get("transactions", []):
        if t["code"] == code:
            if t["action"] == "买入":
                shares += t["shares"]
            else:
                shares -= t["shares"]
    return shares

# ==================== UI 页面 ====================
def main():
    st.title("📈 股票持仓管家")
    st.caption("数据自动同步至GitHub · 多设备共享")

    data = load_data()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 持仓总览", "➕ 添加交易", "📋 交易明细", "💰 分红记录", "📤 导出/导入"
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
        export_import(data)

# ==================== 持仓总览 ====================
def show_overview(data):
    st.subheader("📊 持仓总览")

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 刷新行情", use_container_width=True):
            st.rerun()

    stocks_info = compute_portfolio(data)
    if not stocks_info:
        st.info("📭 暂无持仓，请在「➕ 添加交易」中录入第一笔操作。")
        return

    rows = []
    total_market = 0.0
    total_cost_all = 0.0
    total_profit = 0.0
    total_dividends = 0.0
    total_realized = 0.0

    progress = st.progress(0)
    codes = list(stocks_info.keys())

    for i, code in enumerate(codes):
        info = stocks_info[code]
        progress.progress((i + 1) / len(codes), text=f"获取 {info['name']}({code}) 行情...")
        price, change = get_realtime_price(code)

        if price is not None and price > 0:
            market_val = info["total_shares"] * price
            cost_total = info["total_cost"]
            profit = market_val - cost_total
            profit_pct = (profit / cost_total * 100) if cost_total > 0 else 0
            total_market += market_val
            total_cost_all += cost_total
            total_profit += profit
            price_display = f"{price:.2f}"
            change_display = f"{change:+.2f}%" if change else "N/A"
        else:
            market_val = 0
            profit = 0
            profit_pct = 0
            price_display = "获取失败"
            change_display = "-"

        total_dividends += info["cumulative_dividends"]
        total_realized += info["realized_profit"]

        rows.append({
            "代码": code,
            "名称": info["name"],
            "持仓(股)": info["total_shares"],
            "成本(元)": round(info["total_cost"], 2),
            "现价": price_display,
            "涨跌幅": change_display,
            "市值(元)": round(market_val, 2),
            "浮动盈亏": round(profit, 2),
            "收益率%": round(profit_pct, 2),
            "已实现收益": round(info["realized_profit"], 2),
            "累计分红": round(info["cumulative_dividends"], 2)
        })

    progress.empty()

    st.divider()
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("总市值", f"{total_market:,.2f}")
    col2.metric("总成本", f"{total_cost_all:,.2f}")
    col3.metric("浮动盈亏", f"{total_profit:,.2f}",
                delta=f"{(total_profit/total_cost_all*100) if total_cost_all>0 else 0:.2f}%" if total_cost_all > 0 else None)
    col4.metric("已实现收益", f"{total_realized:,.2f}")
    col5.metric("累计分红", f"{total_dividends:,.2f}")

    st.divider()
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "成本(元)": st.column_config.NumberColumn(format="%.2f"),
            "现价": st.column_config.TextColumn(),
            "市值(元)": st.column_config.NumberColumn(format="%.2f"),
            "浮动盈亏": st.column_config.NumberColumn(format="%.2f"),
            "收益率%": st.column_config.NumberColumn(format="%.2f"),
            "已实现收益": st.column_config.NumberColumn(format="%.2f"),
            "累计分红": st.column_config.NumberColumn(format="%.2f"),
        }
    )

    grand_total = total_profit + total_realized + total_dividends
    st.success(
        f"💰 **总收益 = 浮动盈亏 + 已实现 + 累计分红 = "
        f"{total_profit:,.2f} + {total_realized:,.2f} + {total_dividends:,.2f} = {grand_total:,.2f} 元**"
    )

# ==================== 添加交易（含截图录入子标签） ====================
def add_transaction_tab(data):
    """添加交易主页面，含手动录入和截图录入两个子标签"""
    sub_tab1, sub_tab2 = st.tabs(["✏️ 手动录入", "📸 截图录入"])

    with sub_tab1:
        manual_add_transaction(data)
    with sub_tab2:
        screenshot_add_transaction(data)

def manual_add_transaction(data):
    """原有的手动录入表单"""
    st.subheader("✏️ 手动录入交易")

    with st.form("add_trade_form", clear_on_submit=True):
        st.write("**第一步：选择股票**")
        keyword = st.text_input("🔍 搜索股票（代码或名称）", placeholder="例如 600519 或 茅台")

        if keyword:
            results = search_stocks(keyword)
            if results:
                options = [f"{c} - {n}" for c, n in results]
                selected = st.selectbox("匹配结果", options, key="stock_select_manual")
                code = selected.split(" - ")[0]
                name = selected.split(" - ")[1]
                st.caption(f"已选择：**{name}** ({code})")
            else:
                st.warning("未找到匹配，可手动输入")
                code = st.text_input("股票代码", key="manual_code2")
                name = st.text_input("股票名称", key="manual_name2")
        else:
            st.info("输入关键词搜索，或展开下方手动输入")
            with st.expander("手动输入股票"):
                code = st.text_input("股票代码", key="m_code2")
                name = st.text_input("股票名称", key="m_name2")

        st.divider()
        st.write("**第二步：填写交易信息**")
        col1, col2 = st.columns(2)
        with col1:
            action = st.selectbox("操作类型", ["买入", "卖出"])
        with col2:
            trade_date = st.date_input("交易日期", value=date.today())

        col3, col4, col5 = st.columns(3)
        with col3:
            shares = st.number_input("数量（股）", min_value=1, step=100, value=100)
        with col4:
            price = st.number_input("成交价（元）", min_value=0.01, format="%.3f", value=10.0)
        with col5:
            fee = st.number_input("手续费（元）", min_value=0.0, format="%.2f", value=0.0)

        # 实时预览
        if shares > 0 and price > 0:
            total = shares * price
            fee_val = fee if fee > 0 else total * 0.0003
            actual_fee = fee if fee > 0 else fee_val
            if action == "买入":
                cost = total + actual_fee
                st.caption(f"📌 买入总额：{cost:.2f} 元（含手续费约 {actual_fee:.2f}）")
            else:
                net = total - actual_fee
                st.caption(f"📌 卖出到账：{net:.2f} 元（扣手续费约 {actual_fee:.2f}）")

        submitted = st.form_submit_button("💾 保存交易", use_container_width=True)

        if submitted:
            if not code or not name:
                st.error("❌ 请填写股票代码和名称")
            elif shares <= 0 or price <= 0:
                st.error("❌ 数量和价格必须大于0")
            else:
                if action == "卖出":
                    current_shares = get_current_shares(data, code)
                    if shares > current_shares:
                        st.error(f"❌ 卖出数量({shares})超过当前持仓({current_shares})")
                        return

                transaction = {
                    "code": code,
                    "name": name,
                    "action": action,
                    "shares": int(shares),
                    "price": float(price),
                    "fee": float(fee),
                    "date": trade_date.isoformat(),
                    "timestamp": datetime.now().isoformat()
                }
                data["transactions"].append(transaction)
                save_data(data)
                st.success(f"✅ 已记录：**{action} {name}({code}) {shares}股 @ {price}元**")
                time.sleep(1)
                st.rerun()

def screenshot_add_transaction(data):
    """截图录入：上传截图 → OCR识别 → 核对 → 批量导入"""
    st.subheader("📸 截图批量录入")
    st.caption("上传券商成交截图，自动识别交易信息")

    # 检查OCR是否可用
    ocr_available = True
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        ocr_available = False

    if not ocr_available:
        st.warning("⚠️ OCR引擎未安装，当前为手动辅助模式。请检查 requirements.txt 是否包含 rapidocr-onnxruntime")
        st.info("💡 你也可以先手动录入，OCR功能后续启用后自动生效。")
        # 降级：显示手动辅助表单
        _show_screenshot_fallback_form(data)
        return

    # 上传截图
    uploaded_files = st.file_uploader(
        "📎 上传成交截图（支持多张）",
        type=["png", "jpg", "jpeg", "bmp"],
        accept_multiple_files=True,
        help="支持券商APP的成交明细截图，可一次选多张"
    )

    if not uploaded_files:
        st.info("👆 请上传至少一张成交截图")
        # 显示使用提示
        with st.expander("📖 使用说明和技巧"):
            st.markdown("""
            **支持的截图类型：**
            - 券商APP的成交回报/成交明细截图
            - 包含：股票名称、代码、买卖方向、成交价格、成交数量

            **提高识别率的技巧：**
            - 截图尽量清晰，文字不要模糊
            - 避免反光和遮挡
            - 横屏截图效果通常更好
            - 一次只截一只股票的交易记录

            **识别后流程：**
            1. 系统自动OCR识别 → 显示识别结果
            2. 你核对/修改每条记录 → 点确认导入
            3. 数据自动保存到持仓
            """)
        return

    # 解析所有截图
    if st.button("🔍 开始识别", use_container_width=True, type="primary"):
        _process_screenshots(uploaded_files, data)

def _process_screenshots(uploaded_files, data):
    """处理上传的截图并解析"""
    from ocr_parser import parse_screenshot, validate_transaction

    results = []
    progress = st.progress(0, text="正在识别...")

    for i, uploaded in enumerate(uploaded_files):
        progress.progress((i + 1) / len(uploaded_files), text=f"识别第 {i+1}/{len(uploaded_files)} 张...")
        img_bytes = uploaded.read()
        parsed = parse_screenshot(img_bytes)
        parsed["_filename"] = uploaded.name
        results.append(parsed)

    progress.empty()

    # 检查是否有成功解析的
    success_count = sum(1 for r in results if r.get("success"))
    if success_count == 0:
        st.error("❌ 所有截图均识别失败，请尝试：")
        st.markdown("""
        - 确保截图清晰可读
        - 检查截图中是否包含完整的交易信息
        - 使用下方「手动辅助录入」手动填写
        """)
        # 显示原始OCR文本帮助调试
        for r in results:
            if r.get("raw_text"):
                with st.expander(f"🔍 {r.get('_filename','')} - OCR原始文本"):
                    st.text(r["raw_text"][:500])
        # 降级到手动表单
        _show_screenshot_fallback_form(data)
        return

    st.success(f"✅ 成功识别 {success_count}/{len(results)} 张截图")

    # 展示识别结果，让用户核对和修改
    st.divider()
    st.write("**📋 请核对识别结果，确认无误后批量导入**")

    confirmed = []
    for idx, result in enumerate(results):
        if not result.get("success"):
            st.warning(f"❌ 第{idx+1}张({result.get('_filename','')})识别失败: {result.get('error','')}")
            continue

        conf = result.get("confidence", 0)
        if conf >= 0.8:
            badge = "🟢 高置信度"
        elif conf >= 0.5:
            badge = "🟡 中等置信度（请仔细核对）"
        else:
            badge = "🔴 低置信度（强烈建议修改）"

        with st.expander(f"第{idx+1}条: {result.get('name','?')}({result.get('code','?')}) {result.get('action','?')} {result.get('shares','?')}股 @ {result.get('price','?')}元 — {badge}", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                code = st.text_input("股票代码", value=result.get("code", ""), key=f"ocr_code_{idx}")
                name = st.text_input("股票名称", value=result.get("name", ""), key=f"ocr_name_{idx}")
                action = st.selectbox("操作", ["买入", "卖出"], index=0 if result.get("action") == "买入" else 1, key=f"ocr_act_{idx}")
            with col2:
                shares = st.number_input("数量(股)", min_value=1, step=100, value=int(result.get("shares") or 100), key=f"ocr_shares_{idx}")
                price = st.number_input("成交价", min_value=0.01, format="%.3f", value=float(result.get("price") or 0.01), key=f"ocr_price_{idx}")
                fee = st.number_input("手续费", min_value=0.0, format="%.2f", value=float(result.get("fee") or 0.0), key=f"ocr_fee_{idx}")

            # 校验
            check_shares = get_current_shares(data, code) if code else 0
            if action == "卖出" and shares > check_shares:
                st.error(f"⚠️ 卖出数量({shares})超过当前持仓({check_shares})")
            else:
                st.caption(f"📌 预览：{action} {name}({code}) {shares}股 × {price}元")

            confirmed.append({
                "code": code,
                "name": name,
                "action": action,
                "shares": shares,
                "price": price,
                "fee": fee,
                "date": result.get("date") or date.today().isoformat(),
                "_idx": idx
            })

    if not confirmed:
        st.warning("没有可导入的记录")
        return

    st.divider()
    # 二次确认
    st.write(f"**即将导入 {len(confirmed)} 条交易记录**")
    # 预览表格
    preview_rows = [{"序号": i+1, "代码": c["code"], "名称": c["name"], "操作": c["action"], "数量": c["shares"], "价格": c["price"], "手续费": c["fee"]} for i, c in enumerate(confirmed)]
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

    col_confirm, col_cancel = st.columns([3, 1])
    with col_confirm:
        if st.button("🚀 确认批量导入", type="primary", use_container_width=True):
            _import_confirmed_transactions(confirmed, data)
    with col_cancel:
        if st.button("❌ 取消", use_container_width=True):
            st.rerun()

def _import_confirmed_transactions(confirmed, data):
    """将确认后的交易写入数据"""
    imported = 0
    errors = []
    for c in confirmed:
        try:
            # 最终校验
            check_shares = get_current_shares(data, c["code"])
            if c["action"] == "卖出" and c["shares"] > check_shares:
                errors.append(f"{c['name']}({c['code']}): 卖出数量超过持仓")
                continue

            transaction = {
                "code": c["code"],
                "name": c["name"],
                "action": c["action"],
                "shares": int(c["shares"]),
                "price": float(c["price"]),
                "fee": float(c.get("fee", 0)),
                "date": c.get("date") or date.today().isoformat(),
                "timestamp": datetime.now().isoformat(),
                "source": "screenshot_ocr"
            }
            data["transactions"].append(transaction)
            imported += 1
        except Exception as e:
            errors.append(f"{c.get('name','?')}: {e}")

    if imported > 0:
        save_data(data)

    if imported > 0:
        st.success(f"✅ 成功导入 {imported} 条交易记录！")
    if errors:
        st.error(f"❌ {len(errors)} 条导入失败：")
        for e in errors:
            st.write(f"  - {e}")

    if imported > 0:
        time.sleep(1)
        st.rerun()

def _show_screenshot_fallback_form(data):
    """OCR不可用时的手动辅助表单"""
    st.divider()
    st.write("**✏️ 手动辅助录入（OCR不可用时的备选方案）**")
    with st.form("screenshot_fallback_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            code = st.text_input("股票代码")
            name = st.text_input("股票名称")
        with col2:
            action = st.selectbox("操作", ["买入", "卖出"])
            trade_date = st.date_input("交易日期", value=date.today())

        col3, col4, col5 = st.columns(3)
        with col3:
            shares = st.number_input("数量(股)", min_value=1, step=100, value=100)
        with col4:
            price = st.number_input("成交价(元)", min_value=0.01, format="%.3f")
        with col5:
            fee = st.number_input("手续费(元)", min_value=0.0, format="%.2f")

        if st.form_submit_button("💾 保存"):
            if not code or not name:
                st.error("请填写代码和名称")
            else:
                if action == "卖出":
                    cur = get_current_shares(data, code)
                    if shares > cur:
                        st.error(f"卖出数量超过持仓({cur})")
                        return
                data["transactions"].append({
                    "code": code, "name": name, "action": action,
                    "shares": int(shares), "price": float(price), "fee": float(fee),
                    "date": trade_date.isoformat(), "timestamp": datetime.now().isoformat(),
                    "source": "manual_fallback"
                })
                save_data(data)
                st.success(f"✅ 已保存 {action} {name} {shares}股")
                st.rerun()

# ==================== 交易明细 ====================
def show_transactions(data):
    st.subheader("📋 交易明细")

    transactions = data.get("transactions", [])
    if not transactions:
        st.info("📭 暂无交易记录")
        return

    codes = sorted(set(t["code"] for t in transactions))
    col_filter, col_sort = st.columns([2, 1])
    with col_filter:
        selected_code = st.selectbox("🔎 筛选股票", ["全部"] + [f"{c}" for c in codes])
    with col_sort:
        sort_order = st.selectbox("排序", ["时间倒序", "时间正序"])

    filtered = transactions
    if selected_code != "全部":
        filtered = [t for t in filtered if t["code"] == selected_code]
    if sort_order == "时间倒序":
        filtered = sorted(filtered, key=lambda x: x.get("timestamp", ""), reverse=True)
    else:
        filtered = sorted(filtered, key=lambda x: x.get("timestamp", ""))

    rows = []
    for t in filtered:
        rows.append({
            "序号": transactions.index(t),
            "日期": t["date"],
            "代码": t["code"],
            "名称": t["name"],
            "操作": t["action"],
            "数量": t["shares"],
            "价格": t["price"],
            "手续费": t.get("fee", 0),
            "金额": t["shares"] * t["price"],
            "来源": t.get("source", "manual")
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "价格": st.column_config.NumberColumn(format="%.3f"),
                "手续费": st.column_config.NumberColumn(format="%.2f"),
                "金额": st.column_config.NumberColumn(format="%.2f"),
            }
        )

    # 持仓变动日志
    st.divider()
    with st.expander("📊 持仓变动日志"):
        running_shares = {}
        for t in sorted(transactions, key=lambda x: x.get("timestamp", "")):
            code = t["code"]
            if code not in running_shares:
                running_shares[code] = 0
            if t["action"] == "买入":
                running_shares[code] += t["shares"]
            else:
                running_shares[code] -= t["shares"]

        log_rows = []
        for code in sorted(running_shares.keys()):
            if running_shares[code] > 0:
                cost = 0
                shares = 0
                for t in sorted(transactions, key=lambda x: x.get("timestamp", "")):
                    if t["code"] == code:
                        if t["action"] == "买入":
                            cost += t["shares"] * t["price"] + t.get("fee", 0)
                            shares += t["shares"]
                        else:
                            if shares > 0:
                                avg = cost / shares
                                sold_cost = avg * t["shares"]
                                cost -= sold_cost
                                shares -= t["shares"]
                avg_cost = cost / shares if shares > 0 else 0
                log_rows.append({
                    "代码": code,
                    "名称": next((t["name"] for t in transactions if t["code"] == code), ""),
                    "当前持仓": running_shares[code],
                    "持仓成本": round(cost, 2),
                    "每股成本": round(avg_cost, 2)
                })
        if log_rows:
            st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)

    # 删除记录
    st.divider()
    with st.expander("🗑️ 删除交易记录"):
        st.warning("⚠️ 删除后不可恢复，请谨慎操作")
        del_idx = st.number_input("输入要删除的交易序号", min_value=0, max_value=len(transactions)-1, step=1)
        st.caption(f"该记录：{transactions[del_idx]['date']} {transactions[del_idx]['name']} {transactions[del_idx]['action']} {transactions[del_idx]['shares']}股")
        if st.button("🗑️ 确认删除", type="primary"):
            del data["transactions"][del_idx]
            save_data(data)
            st.success("✅ 已删除")
            time.sleep(1)
            st.rerun()

# ==================== 分红管理 ====================
def manage_dividends(data):
    st.subheader("💰 分红记录管理")

    transactions = data.get("transactions", [])
    codes_in_portfolio = sorted(set(t["code"] for t in transactions))

    if not codes_in_portfolio:
        st.info("📭 暂无持仓股票，先添加交易记录吧")
        return

    with st.expander("➕ 手动添加分红记录", expanded=True):
        with st.form("add_dividend_form"):
            col1, col2 = st.columns(2)
            with col1:
                div_code = st.selectbox("股票代码", codes_in_portfolio)
                div_name = ""
                for t in transactions:
                    if t["code"] == div_code:
                        div_name = t["name"]
                        break
                st.caption(f"名称：{div_name}")
            with col2:
                div_date = st.date_input("除权除息日", value=date.today())
                per_share = st.number_input("每股分红（元）", min_value=0.0, format="%.4f")

            col3, col4 = st.columns(2)
            with col3:
                current_shares = get_current_shares(data, div_code)
                st.caption(f"当前持仓：{max(current_shares, 0)}股")
            with col4:
                auto_amount = per_share * max(current_shares, 0)
                amount = st.number_input("分红金额（元）", min_value=0.0, format="%.2f", value=auto_amount)

            if st.form_submit_button("💾 保存分红记录"):
                if amount <= 0:
                    st.error("金额需大于0")
                else:
                    data["dividends"].append({
                        "code": div_code,
                        "name": div_name,
                        "date": div_date.isoformat(),
                        "per_share": per_share,
                        "amount": amount,
                        "timestamp": datetime.now().isoformat()
                    })
                    save_data(data)
                    st.success(f"✅ 已记录 {div_name}({div_code}) 分红 {amount:.2f}元")
                    st.rerun()

    st.divider()
    dividends = data.get("dividends", [])
    if dividends:
        st.write(f"**已有 {len(dividends)} 条分红记录：**")
        div_rows = []
        for i, d in enumerate(dividends):
            div_rows.append({
                "序号": i,
                "日期": d.get("date", ""),
                "代码": d["code"],
                "名称": d.get("name", ""),
                "每股分红": d.get("per_share", 0),
                "金额": d.get("amount", 0)
            })
        st.dataframe(pd.DataFrame(div_rows), use_container_width=True, hide_index=True)

        with st.expander("🗑️ 删除分红记录"):
            del_idx = st.number_input("输入要删除的序号", min_value=0, max_value=len(dividends)-1, step=1)
            if st.button("🗑️ 确认删除分红记录"):
                del data["dividends"][del_idx]
                save_data(data)
                st.success("✅ 已删除")
                st.rerun()
    else:
        st.info("📭 暂无分红记录")

    st.divider()
    with st.expander("ℹ️ 分红如何影响持仓成本？"):
        st.markdown("""
        **现金分红对持仓的影响：**

        1. **分红到账**：分红金额会进入你的现金账户
        2. **持仓成本扣减**：本工具会自动将分红金额从持仓总成本中扣除
        3. **效果 = 除权**：股数不变，每股成本降低，总市值不变

        **举例：**
        - 持有 1000股，成本 10元/股，总成本 10000元
        - 每股分红 0.5元，到账 500元
        - 分红后成本变为：(10000 - 500) / 1000 = **9.5元/股**
        """)

# ==================== 导出导入 ====================
def export_import(data):
    st.subheader("📤 导出 / 导入数据")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**📥 导出为 Excel**")
        st.caption("包含：持仓总览 + 交易明细 + 分红记录")
        if st.button("📊 生成 Excel 文件", use_container_width=True):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                stocks_info = compute_portfolio(data)
                overview_rows = []
                for code, info in stocks_info.items():
                    price, _ = get_realtime_price(code)
                    market_val = info["total_shares"] * price if price else 0
                    overview_rows.append({
                        "代码": code, "名称": info["name"],
                        "持仓(股)": info["total_shares"],
                        "成本(元)": round(info["total_cost"], 2),
                        "现价": round(price, 2) if price else "N/A",
                        "市值(元)": round(market_val, 2),
                        "浮动盈亏": round(market_val - info["total_cost"], 2),
                        "已实现收益": round(info["realized_profit"], 2),
                        "累计分红": round(info["cumulative_dividends"], 2)
                    })
                pd.DataFrame(overview_rows).to_excel(writer, sheet_name="持仓总览", index=False)

                tx_rows = []
                for t in sorted(data["transactions"], key=lambda x: x.get("timestamp", "")):
                    tx_rows.append({
                        "日期": t["date"], "代码": t["code"], "名称": t["name"],
                        "操作": t["action"], "数量": t["shares"], "价格": t["price"],
                        "手续费": t.get("fee", 0), "金额": t["shares"] * t["price"],
                        "来源": t.get("source", "manual")
                    })
                pd.DataFrame(tx_rows).to_excel(writer, sheet_name="交易明细", index=False)

                div_rows = []
                for d in data["dividends"]:
                    div_rows.append({
                        "日期": d.get("date", ""), "代码": d["code"],
                        "名称": d.get("name", ""), "每股分红": d.get("per_share", 0),
                        "金额": d.get("amount", 0)
                    })
                pd.DataFrame(div_rows).to_excel(writer, sheet_name="分红记录", index=False)

            output.seek(0)
            st.download_button(
                label="⬇️ 下载 Excel",
                data=output,
                file_name=f"stock_data_{date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            st.success("✅ Excel 已生成")

    with col2:
        st.write("**📥 导出为 JSON**")
        st.caption("适合备份或迁移到其他设备")
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        st.download_button(
            label="⬇️ 下载 JSON 备份",
            data=json_str,
            file_name=f"stock_data_{date.today()}.json",
            mime="application/json",
            use_container_width=True
        )

    st.divider()

    with st.expander("📤 从 JSON 恢复数据"):
        st.warning("⚠️ 导入会覆盖当前所有数据！")
        uploaded = st.file_uploader("选择 JSON 备份文件", type=["json"])
        if uploaded is not None:
            try:
                imported = json.load(uploaded)
                if st.button("🔄 确认恢复"):
                    save_data(imported)
                    st.success("✅ 数据已恢复")
                    time.sleep(1)
                    st.rerun()
            except Exception as e:
                st.error(f"❌ 文件格式错误：{e}")

    st.divider()
    st.write("**📊 当前数据统计**")
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("交易记录", len(data.get("transactions", [])))
    col_b.metric("分红记录", len(data.get("dividends", [])))
    col_c.metric("涉及股票", len(set(t["code"] for t in data.get("transactions", []))))
    col_d.metric("数据文件大小", f"{os.path.getsize(DATA_FILE)/1024:.1f} KB" if os.path.exists(DATA_FILE) else "N/A")

# ==================== 启动 ====================
if __name__ == "__main__":
    main()
