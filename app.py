import streamlit as st
import pandas as pd
import json
import os
import requests
from datetime import datetime, date
import io
import base64
import time

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
        elif code.startswith("0") or code.startswith("3"):
            symbol = f"sz{code}"
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

# ==================== 股票搜索（模糊匹配）====================
def search_stocks(keyword):
    """
    模糊搜索股票：支持代码、名称、拼音首字母匹配
    返回 [(code, name), ...] 最多50条
    """
    try:
        from stock_list import STOCK_LIST
    except ImportError:
        st.error("stock_list.py 未找到，请确认文件已上传到仓库")
        return []

    keyword = keyword.strip().upper()
    if not keyword:
        return []

    # 拼音首字母映射表
    PINYIN_MAP = {
        '中':'Z','国':'G','人':'R','大':'D','小':'X','上':'S','下':'X',
        '左':'Z','右':'Y','前':'Q','后':'H','东':'D','西':'X','南':'N','北':'B',
        '一':'Y','二':'E','三':'S','四':'S','五':'W','六':'L','七':'Q','八':'B',
        '九':'J','十':'S','百':'B','千':'Q','万':'W','亿':'Y',
        '元':'Y','角':'J','分':'F','个':'G',
        '日':'R','月':'Y','年':'N','时':'S','秒':'M',
        '招':'Z','商':'S','银':'Y','行':'H','兴':'X','业':'Y','平':'P','安':'A',
        '农':'N','工':'G','建':'J','交':'J','通':'T','信':'X','华':'H','夏':'X',
        '民':'M','生':'S','浦':'P','发':'F','光':'G','大':'D',
        '贵':'G','州':'Z','茅':'M','台':'T','宁':'N','德':'D','时':'S','代':'D',
        '比':'B','亚':'Y','迪':'D','长':'C','城':'C','汽':'Q','车':'C',
        '广':'G','集':'J','团':'T','北':'B','方':'F','稀':'X','土':'T',
        '京':'J','沪':'H','深':'S','津':'J','渝':'Y','冀':'J','晋':'J','辽':'L',
        '吉':'J','黑':'H','苏':'S','浙':'Z','皖':'A','闽':'M','赣':'G','鲁':'L',
        '豫':'Y','鄂':'E','湘':'X','粤':'Y','桂':'G','琼':'Q','川':'C','黔':'Q',
        '滇':'D','藏':'Z','陕':'S','甘':'G','青':'Q','宁':'N','新':'X',
        '股':'G','份':'F','有':'Y','限':'X','公':'G','司':'S',
        '科':'K','技':'J','制':'Z','造':'Z','能':'N','源':'Y','新':'X','材':'C',
        '电':'D','子':'Z','息':'X','网':'W','络':'L','软':'R','件':'J',
        '机':'J','械':'X','重':'Z','工':'G','化':'H','医':'Y','药':'Y','食':'S',
        '品':'P','酒':'J','钢':'G','铁':'T','铜':'T','铝':'L','煤':'M','石':'S',
        '油':'Y','天':'T','然':'R','气':'Q','水':'S','泥':'N','玻':'B','璃':'L',
        '房':'F','地':'D','产':'C','金':'J','融':'R','保':'B','险':'X','证':'Z',
        '券':'Q','传':'C','媒':'M','教':'J','育':'Y','文':'W','体':'T',
        '育':'Y','娱':'Y','乐':'L','旅':'L','游':'Y','零':'L','售':'S','贸':'M',
        '易':'Y','进':'J','出':'C','口':'K','环':'H','保':'B','筑':'Z','料':'L',
        '航':'H','天':'T','军':'J','船':'C','舶':'B','路':'L','运':'Y','输':'S',
        '物':'W','流':'L','港':'G','口':'K','供':'G','热':'R','燃':'R','气':'Q',
        '卫':'W','生':'S','健':'J','康':'K','立':'L','讯':'X','精':'J','密':'M',
        '海':'H','螺':'L','双':'S','汇':'H','紫':'Z','金':'J','牧':'M','原':'Y',
        '迈':'M','瑞':'R','东':'D','方':'F','免':'M','格':'G','力':'L','伊':'Y',
        '利':'L','洋':'Y','河':'H','顺':'S','丰':'F','创':'C','高':'G','德':'D',
        '红':'H','外':'W','赣':'G','锋':'F','齐':'Q','武':'W','纪':'J','澜':'L',
        '起':'Q','微':'W','控':'K','三':'S','花':'H','韵':'Y','达':'D','视':'S',
        '分':'F','众':'Z','美':'M','年':'N','通':'T','号':'H','领':'L','益':'Y',
        '宝':'B','明':'M','通':'T','动':'D','力':'L','卓':'Z','胜':'S','智':'Z',
        '慧':'H','蓝':'L','思':'S','温':'W','氏':'S','帆':'F','泰':'T','联':'L',
        '亿':'Y','网':'W','青':'Q','鸟':'N','消':'X','防':'F','昂':'A','利':'L',
        '康':'K','锐':'R','若':'R','贺':'H','大':'D','正':'Z','同':'T','兴':'X',
        '楚':'C','龙':'L','真':'Z','爱':'A','祖':'Z','名':'M','征':'Z','和':'H',
        '管':'G','桩':'Z','虹':'H','盛':'S','开':'K','普':'P','云':'Y','吉':'J',
        '南':'N','能':'N','鑫':'X','铂':'B','百':'B','亚':'Y','壶':'H','圣':'S',
        '泰':'T','坦':'T','南':'N','网':'W','能':'N','源':'Y',
    }

    def get_initials(name):
        result = []
        for ch in name:
            if '\u4e00' <= ch <= '\u9fff':
                result.append(PINYIN_MAP.get(ch, ch[0].upper()))
            elif ch.isalpha():
                result.append(ch.upper())
        return "".join(result)

    results = []
    # 对中文关键词，也生成其首字母串
    kw_initials = get_initials(keyword)

    for code, name in STOCK_LIST:
        code_u = code.upper()
        name_u = name.upper()

        # 1. 直接包含匹配（关键词在代码中 或 在名称中）
        if keyword in code_u or keyword in name_u:
            results.append((code, name))
            continue

        # 2. 反向包含匹配（如 "中石油" 在 "中国石油" 中）
        # 检查关键词是否是名称的任意子串排列
        if len(keyword) >= 2 and not keyword.isalpha():
            # 对中文关键词，检查其字符是否都在名称中
            chars_in_name = all(c in name for c in keyword if c.strip())
            if chars_in_name and len(keyword) >= 2:
                results.append((code, name))
                continue

        initials = get_initials(name)

        # 3. 拼音首字母完整匹配
        if keyword in initials:
            results.append((code, name))
            continue

        # 4. 拼音首字母子串滑动窗口匹配
        if len(keyword) >= 2 and all(c.isalpha() for c in keyword):
            for i in range(len(initials) - len(keyword) + 1):
                if initials[i:i+len(keyword)] == keyword:
                    results.append((code, name))
                    break
            if len(results) > 0 and results[-1][0] == code:
                continue

        # 5. 关键词首字母在名称首字母中作为子序列出现
        if len(kw_initials) >= 2 and all(c.isalpha() for c in kw_initials):
            # 检查 kw_initials 是否是 initials 的子序列
            it = iter(initials)
            if all(any(c == ch for ch in it) for c in kw_initials):
                results.append((code, name))
                continue

    return results[:50]

# ==================== 核心计算 ====================
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
            amount = float(d.get("amount", 0))
            stocks_info[code]["cumulative_dividends"] += amount
            if stocks_info[code]["total_shares"] > 0:
                stocks_info[code]["total_cost"] -= amount
    return stocks_info

# ==================== 主界面 ====================
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

# ==================== 持仓总览 ====================
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
            rows.append({
                "代码": code,
                "名称": info["name"],
                "持仓": info["total_shares"],
                "成本": round(info["total_cost"], 2),
                "现价": round(price, 2),
                "市值": round(market_val, 2),
                "浮动盈亏": round(profit, 2),
                "收益率%": round(profit_pct, 2),
                "已实现收益": round(info["realized_profit"], 2),
                "累计分红": round(info["cumulative_dividends"], 2)
            })
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总市值", f"{total_market:.2f}")
    col2.metric("总成本", f"{total_cost_all:.2f}")
    col3.metric("总浮动盈亏", f"{total_market - total_cost_all:.2f}")
    col4.metric("累计分红", f"{total_dividends:.2f}")

    if st.button("🔄 刷新行情"):
        st.rerun()

    df = pd.DataFrame(rows)
    st.dataframe(df, width='stretch', hide_index=True)

# ==================== 添加交易 ====================
def add_transaction_tab(data):
    st.subheader("添加交易")

    # ---- 股票搜索区域（form 外部）----
    st.write("**第一步：搜索并选择股票**")
    keyword = st.text_input(
        "输入股票名称或代码（模糊匹配）",
        key="search_keyword",
        placeholder="如：茅台、600519、招商、000001"
    )

    if st.button("🔍 搜索", key="search_btn"):
        if keyword.strip():
            results = search_stocks(keyword)
            if results:
                st.session_state.search_results = results
                st.session_state.search_done = True
            else:
                st.session_state.search_results = []
                st.session_state.search_done = True
                st.warning("未找到匹配的股票，请尝试其他关键词")
        else:
            st.warning("请输入股票名称或代码")

    # 显示搜索结果
    selected_code = ""
    selected_name = ""
    if st.session_state.get("search_done") and st.session_state.get("search_results"):
        results = st.session_state.search_results
        seen = set()
        unique_results = []
        for code, name in results:
            if code not in seen:
                seen.add(code)
                unique_results.append((code, name))
        results = unique_results
        opts = [f"{name} ({code})" for code, name in results]
        sel = st.selectbox("选择股票", opts, key="select_stock")
        for code, name in results:
            target = f"{name} ({code})"
            if target == sel:
                selected_code = code
                selected_name = name
                break
        st.success(f"已选择：**{selected_name}** ({selected_code})")
    elif st.session_state.get("search_done") and not st.session_state.get("search_results"):
        st.error("未找到匹配的股票，请检查输入是否正确")
        selected_code = st.session_state.get("manual_code", "")
        selected_name = st.session_state.get("manual_name", "")
        if selected_code or selected_name:
            st.info(f"将使用手动输入：{selected_name} ({selected_code})")
    else:
        selected_code = st.session_state.get("manual_code", "")
        selected_name = st.session_state.get("manual_name", "")

    # 手动输入备选
    with st.expander("🔧 搜索不到？手动输入"):
        col_a, col_b = st.columns(2)
        with col_a:
            manual_code = st.text_input("股票代码", value=st.session_state.get("manual_code", ""), key="manual_code_input")
        with col_b:
            manual_name = st.text_input("股票名称", value=st.session_state.get("manual_name", ""), key="manual_name_input")
        if manual_code or manual_name:
            selected_code = manual_code
            selected_name = manual_name

    st.divider()

    # ---- 交易表单（form 内部）----
    st.write("**第二步：填写交易信息**")
    with st.form("add_trade", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            action = st.selectbox("操作", ["买入", "卖出"], key="action_input")
        with col2:
            td = st.date_input("日期", value=date.today(), key="date_input")

        col3, col4, col5 = st.columns(3)
        with col3:
            shares = st.number_input(
                "数量（股）",
                min_value=100,
                step=100,
                value=100,
                key="shares_input"
            )
        with col4:
            price = st.number_input(
                "价格（元）",
                min_value=0.01,
                step=0.01,
                format="%.3f",
                key="price_input",
                value=None,
                placeholder="请输入价格"
            )
        with col5:
            fee = st.number_input(
                "手续费（元）",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                key="fee_input",
                value=5.0
            )

        submitted = st.form_submit_button("💾 保存交易")

        if submitted:
            errors = []
            if not selected_code or not selected_name:
                errors.append("请先搜索并选择股票，或手动输入股票代码和名称")
            if not price or price <= 0:
                errors.append("价格必须大于0")
            if shares < 100:
                errors.append("数量最低为100股")
            if shares % 100 != 0:
                errors.append("数量必须是100的整数倍")
            if action == "卖出":
                current_shares = get_current_shares(data, selected_code)
                if shares > current_shares:
                    errors.append(f"卖出数量({shares})超过当前持仓({current_shares})")

            if errors:
                for e in errors:
                    st.error(f"❌ {e}")
            else:
                data["transactions"].append({
                    "code": selected_code.strip(),
                    "name": selected_name.strip(),
                    "action": action,
                    "shares": int(shares),
                    "price": float(price),
                    "fee": float(fee),
                    "date": td.isoformat(),
                    "timestamp": datetime.now().isoformat()
                })
                save_data(data)
                st.success(f"✅ 交易已保存！{action} {selected_name}({selected_code}) {int(shares)}股 @ {float(price):.2f}元")
                st.session_state.pop("search_results", None)
                st.session_state.pop("search_done", None)
                st.session_state.pop("select_stock", None)
                st.balloons()
                time.sleep(1)
                st.rerun()

def get_current_shares(data, code):
    """获取当前持仓数量"""
    stocks_info = compute_portfolio(data)
    if code in stocks_info:
        return stocks_info[code]["total_shares"]
    return 0

# ==================== 交易明细 ====================
def show_transactions(data):
    st.subheader("交易明细")

    if not data["transactions"]:
        st.info("暂无交易记录")
        return

    # 构建筛选下拉框：按 "名称 (代码)" 格式，按名称排序
    code_name_map = {}
    for t in data["transactions"]:
        code_name_map[t["code"]] = t["name"]
    sorted_items = sorted(code_name_map.items(), key=lambda x: x[1])
    opts = ["全部"] + [f"{name} ({code})" for code, name in sorted_items]

    sel = st.selectbox("筛选股票", opts, key="filter_select")

    # 解析选中的代码
    if sel == "全部":
        target_code = None
    else:
        # 从 "名称 (代码)" 中提取代码
        target_code = sel.rsplit("(", 1)[-1].rstrip(")")

    # 构建表格数据
    rows = []
    for idx, t in enumerate(data["transactions"]):
        if target_code and t["code"] != target_code:
            continue
        rows.append({
            "序号": idx,
            "日期": t["date"],
            "代码": t["code"],
            "名称": t["name"],
            "操作": t["action"],
            "数量": t["shares"],
            "价格": t["price"],
            "手续费": t.get("fee", 0)
        })

    if not rows:
        st.info("当前筛选无记录")
        return

    df = pd.DataFrame(rows)
    display_df = df.drop(columns=["序号"])
    st.dataframe(display_df, width='stretch', hide_index=True)

    st.divider()
    st.write("**删除记录**")
    st.caption("从下方选择要删除的记录")

    col_del1, col_del2 = st.columns([3, 1])
    with col_del1:
        del_opts = ["— 请选择 —"] + [
            f"#{r['序号']} {r['日期']} {r['名称']}({r['代码']}) {r['操作']} {r['数量']}股 @ {r['价格']}"
            for r in rows
        ]
        del_sel = st.selectbox("选择要删除的记录", del_opts, key="del_select")

    with col_del2:
        st.write("")
        st.write("")
        if st.button("🗑️ 删除选中", type="primary", use_container_width=True):
            if del_sel and del_sel != "— 请选择 —":
                idx_to_delete = int(del_sel.split("#")[1].split(" ")[0])
                deleted = data["transactions"].pop(idx_to_delete)
                save_data(data)
                st.success(f"✅ 已删除：{deleted['name']}({deleted['code']}) {deleted['action']} {deleted['shares']}股")
                st.rerun()
            else:
                st.warning("请先选择要删除的记录")

# ==================== 分红记录 ====================
def manage_dividends(data):
    st.subheader("分红记录")
    st.info("分红功能：输入股票代码和金额，自动扣减持仓成本")

    stocks_info = compute_portfolio(data)
    if not stocks_info:
        st.warning("暂无持仓，无法添加分红记录")
        return

    stock_opts = sorted(stocks_info.items(), key=lambda x: x[1]["name"])
    opts = [f"{info['name']} ({code})" for code, info in stock_opts]

    with st.form("add_div"):
        sel = st.selectbox("选择股票", opts, key="div_stock")
        div_date = st.date_input("除权除息日", key="div_date")
        amount = st.number_input("分红金额（元）", min_value=0.0, format="%.2f", key="div_amount")
        if st.form_submit_button("添加分红"):
            if amount > 0:
                code = sel.rsplit("(", 1)[-1].rstrip(")")
                name = sel.rsplit("(", 1)[0].strip()
                data["dividends"].append({
                    "code": code,
                    "name": name,
                    "date": div_date.isoformat(),
                    "amount": amount
                })
                save_data(data)
                st.success(f"✅ 分红记录已添加：{name} {amount:.2f}元")
                st.rerun()
            else:
                st.error("分红金额必须大于0")

    if data["dividends"]:
        st.write("**已有分红记录：**")
        div_rows = []
        for idx, d in enumerate(data["dividends"]):
            div_rows.append({
                "序号": idx,
                "日期": d.get("date", ""),
                "代码": d.get("code", ""),
                "名称": d.get("name", ""),
                "金额": d.get("amount", 0)
            })
        div_df = pd.DataFrame(div_rows)
        st.dataframe(div_df.drop(columns=["序号"]), width='stretch', hide_index=True)

        st.divider()
        del_opts_div = ["— 请选择 —"] + [
            f"#{d['序号']} {d['日期']} {d['名称']} {d['金额']}元" for d in div_rows
        ]
        col_d1, col_d2 = st.columns([3, 1])
        with col_d1:
            del_div_sel = st.selectbox("选择要删除的分红记录", del_opts_div, key="del_div_select")
        with col_d2:
            st.write("")
            st.write("")
            if st.button("🗑️ 删除分红", type="primary", use_container_width=True):
                if del_div_sel and del_div_sel != "— 请选择 —":
                    idx_del = int(del_div_sel.split("#")[1].split(" ")[0])
                    data["dividends"].pop(idx_del)
                    save_data(data)
                    st.success("✅ 已删除分红记录")
                    st.rerun()

# ==================== 导出数据 ====================
def export_data(data):
    st.subheader("导出 / 导入数据")

    col1, col2 = st.columns(2)
    with col1:
        st.write("**导出为 JSON 备份文件**")
        if st.button("📥 导出备份", use_container_width=True):
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            b64 = base64.b64encode(json_str.encode()).decode()
            fname = f"stock_data_backup_{date.today().isoformat()}.json"
            href = f'<a href="data:application/json;base64,{b64}" download="{fname}">点击下载 JSON 备份</a>'
            st.markdown(href, unsafe_allow_html=True)

    with col2:
        st.write("**从 JSON 备份恢复**")
        uploaded = st.file_uploader("选择备份文件", type=["json"], key="import_upload")
        if uploaded:
            try:
                imported = json.load(uploaded)
                if "transactions" in imported and "dividends" in imported:
                    if st.button("📤 确认导入（覆盖现有数据）", type="primary", use_container_width=True):
                        data["transactions"] = imported["transactions"]
                        data["dividends"] = imported["dividends"]
                        save_data(data)
                        st.success("✅ 导入成功！")
                        st.rerun()
                else:
                    st.error("文件格式不正确，缺少必要字段")
            except Exception as e:
                st.error(f"文件解析失败: {e}")

    st.divider()
    st.write("**当前数据统计**")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("交易记录数", len(data["transactions"]))
    col_b.metric("分红记录数", len(data["dividends"]))
    col_c.metric("持仓股票数", len(compute_portfolio(data)))

if __name__ == "__main__":
    main()
