# 请复制以下全部内容
import streamlit as st
import pandas as pd
import json
import os
import requests
from datetime import datetime, date
import io
import base64
from PIL import Image

st.set_page_config(page_title="股票持仓管家", layout="wide", initial_sidebar_state="collapsed")

DATA_FILE = "stock_data.json"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_OWNER = os.environ.get("REPO_OWNER", "")
REPO_NAME = os.environ.get("REPO_NAME", "")

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

def get_realtime_price(stock_code):
    try:
        code = str(stock_code).strip()
        if code.startswith("6"):
            symbol = f"sh{code}"
        elif code.startswith("0") or code.startswith("3"):
            symbol = f"sz{code}"
        elif code.startswith("688"):
            symbol = f"sh{code}"
        else:
            return None, None
        url = f"https://qt.gtimg.cn/q={symbol}"
        r = requests.get(url, timeout=5)
        r.encoding = "gbk"
        text = r.text
        parts = text.split("~")
        if len(parts) >= 40:
            price = float(parts[3]) if parts[3] else None
            change_pct = float(parts[32]) if parts[32] else None
            return price, change_pct
        return None, None
    except:
        return None, None

def search_stocks(keyword):
    try:
        from stock_list import STOCK_LIST
        keyword = keyword.strip().upper()
        results = []
        for code, name in STOCK_LIST:
            if keyword in code or keyword in name:
                results.append((code, name))
        return results[:50]
    except:
        return []

def compute_portfolio(data):
    stocks_info = {}
    transactions = data.get("transactions", [])
    dividends = data.get("dividends", [])
    for t in transactions:
        code = t["code"]
        name = t["name"]
        if code not in stocks_info:
            stocks_info[code] = {"name": name, "total_shares": 0, "total_cost": 0.0, "realized_profit": 0.0, "cumulative_dividends": 0.0}
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

def main():
    st.title("📈 股票持仓管家")
    data = load_data()
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 持仓总览", "➕ 添加交易", "📋 交易明细", "💰 分红记录", "📤 导出数据"])
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

def show_overview(data):
    st.subheader("持仓总览")
    stocks_info = compute_portfolio(data)
    if not stocks_info:
        st.info("暂无持仓，请在「添加交易」中录入")
        return
    rows = []
    total_market = 0
    total_cost_all = 0
    total_dividends = 0
    for code, info in stocks_info.items():
        price, change = get_realtime_price(code)
        if price:
            market_val = info["total_shares"] * price
            profit = market_val - info["total_cost"]
            profit_pct = (profit / info["total_cost"] * 100) if info["total_cost"] > 0 else 0
            total_market += market_val
            total_cost_all += info["total_cost"]
            total_dividends += info["cumulative_dividends"]
            rows.append({"代码": code, "名称": info["name"], "持仓": info["total_shares"], "成本": round(info["total_cost"], 2), "现价": round(price, 2), "市值": round(market_val, 2), "浮动盈亏": round(profit, 2), "收益率%": round(profit_pct, 2), "已实现收益": round(info["realized_profit"], 2), "累计分红": round(info["cumulative_dividends"], 2)})
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总市值", f"{total_market:.2f}")
    col2.metric("总成本", f"{total_cost_all:.2f}")
    col3.metric("总浮动盈亏", f"{total_market - total_cost_all:.2f}")
    col4.metric("累计分红", f"{total_dividends:.2f}")
    df = pd.DataFrame(rows)
    st.dataframe(df, width='stretch', hide_index=True)

def add_transaction_tab(data):
    sub_tabs = st.tabs(["✏️ 手动录入", "📸 截图录入"])
    with sub_tabs[0]:
        manual_add_transaction(data)
    with sub_tabs[1]:
        screenshot_add_transaction(data)

def manual_add_transaction(data):
    st.subheader("手动添加交易")
    
    # 搜索部分放在 form 外部
    keyword = st.text_input("搜索股票（代码或名称）", key="search_keyword")
    col1, col2 = st.columns([3, 1])
    if col1.button("搜索", key="search_btn"):
        results = search_stocks(keyword)
        if results:
            st.session_state.results = results
        else:
            st.warning("未找到")
    
    if "results" in st.session_state and st.session_state.results:
        opts = [f"{c} - {n}" for c, n in st.session_state.results]
        sel = st.selectbox("选择股票", opts, key="select_stock")
        code = sel.split(" - ")[0]
        name = sel.split(" - ")[1]
    else:
        code = st.text_input("代码", key="manual_code")
        name = st.text_input("名称", key="manual_name")
    
    with st.form("add_trade"):
        action = st.selectbox("操作", ["买入", "卖出"])
        shares = st.number_input("数量", min_value=1, step=100)
        price = st.number_input("价格", min_value=0.01, format="%.3f")
        fee = st.number_input("手续费", min_value=0.0, format="%.2f")
        td = st.date_input("日期", value=date.today())
        if st.form_submit_button("保存"):
            if code and name:
                data["transactions"].append({
                    "code": code, "name": name, "action": action,
                    "shares": shares, "price": price, "fee": fee,
                    "date": td.isoformat(), "timestamp": datetime.now().isoformat()
                })
                save_data(data)
                st.success("已保存")
                st.rerun()

def screenshot_add_transaction(data):
    st.subheader("截图批量导入")
    st.info("上传券商成交截图（支持png/jpg），系统将自动识别交易信息。识别结果请人工核对后导入。")
    uploaded_files = st.file_uploader("选择截图（可多选）", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
    if not uploaded_files:
        st.stop()
    if st.button("🔍 开始识别"):
        try:
            from ocr_parser import extract_text_from_image, parse_stock_screenshot
        except ImportError:
            st.error("OCR 解析模块未正确安装，请检查依赖。")
            st.stop()
        all_records = []
        progress_bar = st.progress(0, text="正在识别...")
        for i, uploaded_file in enumerate(uploaded_files):
            progress_bar.progress((i+1)/len(uploaded_files), text=f"识别第 {i+1}/{len(uploaded_files)} 张...")
            try:
                image = Image.open(uploaded_file)
                boxes, texts = extract_text_from_image(image)
                if not texts:
                    st.warning(f"第 {i+1} 张图片未能识别出文字，请检查图片质量。")
                    continue
                parsed = parse_stock_screenshot(boxes, texts)
                parsed["source"] = uploaded_file.name
                all_records.append(parsed)
            except Exception as e:
                st.error(f"第 {i+1} 张图片处理出错: {e}")
        if not all_records:
            st.warning("没有成功识别出任何交易记录。")
            st.stop()
        st.success(f"共识别出 {len(all_records)} 条可能的交易记录，请核对：")
        edited_records = []
        for idx, rec in enumerate(all_records):
            with st.expander(f"记录 {idx+1} - {rec.get('source', '未知来源')}", expanded=(idx==0)):
                col1, col2 = st.columns(2)
                with col1:
                    code = st.text_input(f"股票代码 {idx+1}", value=rec.get("stock_code",""), key=f"code_{idx}")
                    name = st.text_input(f"股票名称 {idx+1}", value=rec.get("stock_name",""), key=f"name_{idx}")
                    action = st.selectbox(f"操作 {idx+1}", ["买入", "卖出"], index=0 if rec.get("direction") in ["买入","买"] else 1, key=f"act_{idx}")
                with col2:
                    qty = st.text_input(f"数量 {idx+1}", value=rec.get("quantity",""), key=f"qty_{idx}")
                    prc = st.text_input(f"价格 {idx+1}", value=rec.get("price",""), key=f"prc_{idx}")
                edited_records.append({"code": code, "name": name, "action": action, "shares": qty, "price": prc})
        if st.button("🚀 确认批量导入"):
            success_count = 0
            for rec in edited_records:
                try:
                    code = rec["code"].strip()
                    name = rec["name"].strip()
                    action = rec["action"]
                    shares = int(float(rec["shares"]))
                    price = float(rec["price"])
                    if not code or not name or shares <= 0 or price <= 0:
                        st.warning(f"跳过无效记录: {rec}")
                        continue
                    data["transactions"].append({
                        "code": code, "name": name, "action": action,
                        "shares": shares, "price": price, "fee": 0.0,
                        "date": date.today().isoformat(), "timestamp": datetime.now().isoformat()
                    })
                    success_count += 1
                except Exception as e:
                    st.error(f"导入失败: {rec}, 错误: {e}")
            save_data(data)
            st.success(f"成功导入 {success_count} 条交易记录！")
            st.rerun()

def show_transactions(data):
    st.subheader("交易明细")
    if not data["transactions"]:
        st.info("暂无记录")
        return
    codes = sorted(set(t["code"] for t in data["transactions"]))
    sel = st.selectbox("筛选", ["全部"] + codes)
    filtered = data["transactions"] if sel == "全部" else [t for t in data["transactions"] if t["code"] == sel]
    df = pd.DataFrame(filtered)
    if not df.empty:
        df = df[["date", "code", "name", "action", "shares", "price", "fee"]]
        df.columns = ["日期", "代码", "名称", "操作", "数量", "价格", "手续费"]
        st.dataframe(df, width='stretch', hide_index=True)

def manage_dividends(data):
    st.subheader("分红记录")
    st.info("分红功能：输入股票代码和金额，自动扣减持仓成本")
    with st.form("add_div"):
        code = st.text_input("股票代码")
        div_date = st.date_input("除权除息日")
        amount = st.number_input("分红金额（元）", min_value=0.0, format="%.2f")
        if st.form_submit_button("添加分红"):
            if code and amount > 0:
                data["dividends"].append({"code": code, "date": div_date.isoformat(), "amount": amount})
                save_data(data)
                st.success("已添加")
                st.rerun()
    if data["dividends"]:
        st.write("已有分红记录：")
        df = pd.DataFrame(data["dividends"])
        st.dataframe(df, width='stretch', hide_index=True)

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
