# -*- coding: utf-8 -*-
"""
OCR 解析引擎 - 从券商截图文本中提取结构化交易记录
支持多种券商APP截图格式
"""

import re
from datetime import datetime, date


# ==================== 工具函数 ====================

def extract_stock_code(text):
    """从文本中提取6位股票代码"""
    # 匹配 6位数字，前后可能有括号、空格
    patterns = [
        r'[（(]\s*(\d{6})\s*[）)]',   # (600519) 或 （600519）
        r'(\d{6})\s*[）)]',             # 600519）
        r'[（(]\s*(\d{6})',             # (600519
        r'(?<![/\d])(\d{6})(?![/\d])', # 独立的6位数字
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            code = m.group(1)
            # 验证是合法A股代码
            if code.startswith(("0", "3", "6", "688", "8")):
                return code
    return None


def extract_stock_name(text, exclude_words=None):
    """从文本中提取中文股票名称"""
    if exclude_words is None:
        exclude_words = set()

    # 常见的非股票名称关键词
    stop_words = {
        "成交明细", "委托成交", "历史成交", "当日成交", "交易记录",
        "买入", "卖出", "买", "卖", "交易", "委托", "成交",
        "价格", "数量", "金额", "手续费", "印花税", "过户费",
        "日期", "时间", "状态", "已成交", "未成交", "撤单",
        "持仓", "可用", "冻结", "成本", "现价", "盈亏",
        "合计", "总计", "小计", "确认", "取消", "提交",
        "详情", "更多", "返回", "刷新", "搜索", "筛选",
        "全部", "股票", "代码", "名称", "序号",
    }
    stop_words.update(exclude_words)

    # 匹配2-4个连续中文字符
    chinese_pattern = re.compile(r'[\u4e00-\u9fa5]{2,5}')
    matches = chinese_pattern.findall(text)

    for m in matches:
        if m not in stop_words and len(m) >= 2:
            # 排除包含数字或符号的
            if not re.search(r'[0-9()（）/]', m):
                return m
    return ""


def extract_price(text):
    """从文本中提取价格（通常是小数点后2-3位的数字）"""
    # 价格通常在 0.01 ~ 9999.99 之间
    patterns = [
        r'价格[：:]\s*(\d+\.\d{2,3})',
        r'成交价[：:]\s*(\d+\.\d{2,3})',
        r'@\s*(\d+\.\d{2,3})',
        r'(\d{1,4}\.\d{2,3})',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            val = float(m.group(1))
            if 0.01 <= val <= 99999:
                return val
    return 0.0


def extract_quantity(text):
    """从文本中提取数量（股数，通常是100的整数倍）"""
    patterns = [
        r'数量[：:]\s*(\d+)',
        r'股数[：:]\s*(\d+)',
        r'(\d+)\s*股',
        r'(\d{3,7})',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            val = int(m.group(1))
            if 100 <= val <= 10000000:
                return val
    return 0


def extract_date(text):
    """从文本中提取日期，返回 YYYY-MM-DD 格式"""
    patterns = [
        (r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日]?', "%Y-%m-%d"),
        (r'(\d{4})(\d{2})(\d{2})', "%Y-%m-%d"),
    ]
    for p, fmt in patterns:
        m = re.search(p, text)
        if m:
            try:
                if len(m.groups()) == 3:
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            except:
                pass
    return date.today().isoformat()


def detect_action(text):
    """检测交易方向"""
    if re.search(r'卖出|卖\b|SELL|Sell', text, re.IGNORECASE):
        return "卖出"
    elif re.search(r'买入|买\b|BUY|Buy', text, re.IGNORECASE):
        return "买入"
    return None


# ==================== 主解析函数 ====================

def parse_trade_from_text(lines, stock_code_hint=""):
    """
    从 OCR 文本行列表中解析交易记录

    策略（状态机）：
    1. 全局预扫：建立 code <-> name 映射
    2. 逐行扫描，维护一个 current_trade 草稿
    3. 遇到新股票代码/新动作 -> 完成上一笔，开启新一笔
    4. 每行提取能提取的字段，填充到当前草稿

    返回：交易记录列表
    """
    trades = []

    # ---- 全局预扫：code <-> name ----
    code_name_map = {}
    name_code_map = {}
    for line in lines:
        code = extract_stock_code(line)
        if code:
            name = extract_stock_name(line)
            if code not in code_name_map:
                code_name_map[code] = name
            if name and name not in name_code_map:
                name_code_map[name] = code

    def flush(trade, lst):
        """将草稿判定是否合格，合格则加入列表"""
        if not trade:
            return
        score = 0
        if trade.get("code"): score += 1
        if trade.get("name"): score += 1
        if trade.get("price", 0) > 0: score += 1
        if trade.get("shares", 0) >= 100: score += 1
        if trade.get("action") in ("买入", "卖出"): score += 1

        if score >= 3:  # 至少代码+价格+数量 或 名称+价格+数量
            if score >= 4:
                trade["confidence"] = "high"
            elif score >= 3:
                trade["confidence"] = "medium"
            else:
                trade["confidence"] = "low"
            lst.append(trade)

    current = None
    last_code = None   # 最近见过的代码（用于跨行补全）
    last_name = None
    last_date = None   # 最近见过的日期

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # 跳过纯装饰行
        if re.match(r'^[=~\-_\s]+$', line_stripped):
            continue

        # 跳过表头行（含关键词且无股票代码）
        header_kws = ["成交明细", "委托成交", "历史成交", "交易记录", "序号", "合计", "总计"]
        if any(kw in line_stripped for kw in header_kws):
            if not re.search(r'\d{6}', line_stripped):
                continue

        # 本行能提取的字段
        code = extract_stock_code(line_stripped)
        name = extract_stock_name(line_stripped)
        action = detect_action(line_stripped)
        price = extract_price(line_stripped)
        qty = extract_quantity(line_stripped)
        dt = extract_date(line_stripped)

        # 更新全局最近值
        if code: last_code = code
        if name: last_name = name
        if dt != date.today().isoformat():  # 如果不是默认值
            last_date = dt

        # 判断是否开启新交易
        is_new = False
        if code and code != (current.get("code") if current else None):
            is_new = True
        elif action and current is None:
            is_new = True
        elif price > 0 and qty >= 100 and current is None:
            is_new = True

        if is_new:
            # 先把旧的 flush
            if current:
                flush(current, trades)
            # 开新
            current = {
                "code": code or last_code or stock_code_hint,
                "name": name or (code_name_map.get(code, "") if code else "") or last_name or "",
                "action": action or "买入",
                "shares": qty,
                "price": price,
                "fee": 0.0,
                "date": dt if dt != date.today().isoformat() else (last_date or dt),
                "note": "OCR导入",
                "confidence": "low"
            }
        else:
            # 填充到当前草稿
            if current is None:
                current = {
                    "code": code or last_code or stock_code_hint,
                    "name": name or last_name or "",
                    "action": action or "买入",
                    "shares": qty,
                    "price": price,
                    "fee": 0.0,
                    "date": dt if dt != date.today().isoformat() else (last_date or dt),
                    "note": "OCR导入",
                    "confidence": "low"
                }
            if code: current["code"] = code
            if name: current["name"] = name
            if action: current["action"] = action
            if price > 0: current["price"] = price
            if qty >= 100: current["shares"] = qty
            if dt != date.today().isoformat(): current["date"] = dt

        # 如果当前草稿已"完整"，flush 并重置（为下一条做准备）
        if current and current.get("price", 0) > 0 and current.get("shares", 0) >= 100:
            flush(current, trades)
            current = None

    # 最后一条
    if current:
        flush(current, trades)

    # 去重
    seen = set()
    unique = []
    for t in trades:
        key = (t["code"], t["price"], t["shares"], t["action"])
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique


def parse_trade_table(lines):
    """
    解析表格形式的截图（如券商的历史成交列表）
    每行包含：代码 名称 日期 价格 数量 金额
    """
    trades = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 必须有6位数字代码
        code_m = re.search(r'\d{6}', line)
        if not code_m:
            continue

        code = code_m.group()

        # 提取名称（代码前面的中文）
        name_m = re.search(r'([\u4e00-\u9fa5]{2,4})\s*' + re.escape(code), line)
        name = name_m.group(1) if name_m else ""

        # 判断买卖
        if re.search(r'卖出|SELL', line, re.IGNORECASE):
            action = "卖出"
        elif re.search(r'买入|BUY', line, re.IGNORECASE):
            action = "买入"
        else:
            action = "买入"  # 默认

        # 提取所有数字
        numbers = re.findall(r'\d+\.?\d*', line)
        numbers = [float(n) for n in numbers if n.replace('.', '').isdigit()]

        price = 0.0
        shares = 0
        for n in numbers:
            if 0.01 <= n <= 99999 and price == 0:
                price = n
            elif 100 <= n <= 10000000 and shares == 0 and n == int(n):
                shares = int(n)

        if price > 0 or shares > 0:
            trades.append({
                "code": code,
                "name": name,
                "action": action,
                "shares": shares,
                "price": price,
                "fee": 0.0,
                "date": date.today().isoformat(),
                "note": "OCR表格导入",
                "confidence": "medium" if price > 0 and shares > 0 else "low"
            })

    return trades


def parse_multi_stock_screenshot(lines):
    """
    高级解析：针对一整屏多只股票的持仓/成交截图
    自动识别每只股票的区块并分别解析
    """
    # 先按空行分割成多个区块
    blocks = []
    current = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)

    all_trades = []
    for block in blocks:
        block_text = "\n".join(block)
        trades = parse_trade_from_text(block)
        all_trades.extend(trades)

    return all_trades


# ==================== 辅助：生成测试图片 ====================

def create_test_screenshot():
    """生成一张模拟的券商成交截图（用于测试OCR）"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import os

        img = Image.new('RGB', (800, 600), color='white')
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 20)
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 24)
        except:
            font = ImageFont.load_default()
            font_large = font

        # 标题
        draw.text((300, 20), "成交明细", fill='black', font=font_large)

        # 表头
        y = 80
        headers = ["代码", "名称", "操作", "价格", "数量"]
        x_positions = [50, 150, 300, 400, 550]
        for h, x in zip(headers, x_positions):
            draw.text((x, y), h, fill='gray', font=font)

        # 数据行
        rows = [
            ("600519", "贵州茅台", "买入", "1685.50", "100"),
            ("002594", "比亚迪", "买入", "198.30", "200"),
            ("300750", "宁德时代", "卖出", "215.80", "100"),
        ]

        y = 120
        for code, name, action, price, qty in rows:
            draw.text((50, y), code, fill='black', font=font)
            draw.text((150, y), name, fill='black', font=font)
            draw.text((300, y), action, fill='red' if action == "买入" else 'green', font=font)
            draw.text((400, y), price, fill='black', font=font)
            draw.text((550, y), qty, fill='black', font=font)
            y += 50

        output_path = "/data/workspace/stock_tracker/test_screenshot.png"
        img.save(output_path)
        return output_path
    except ImportError:
        return None
