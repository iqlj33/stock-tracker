"""
ocr_parser.py — 轻量截图解析模块
依赖: rapidocr-onnxruntime (纯ONNX, ~10MB, 无PyTorch/TensorFlow)
功能: 解析券商成交截图，提取股票代码/名称/买卖方向/数量/价格/日期
"""

import re
import base64
import io
from typing import List, Dict, Optional, Tuple

# ============ 常量 ============
BUY_KEYWORDS = ["买入", "买", "B", "BUY", "买进", "增持"]
SELL_KEYWORDS = ["卖出", "卖", "S", "SELL", "卖出", "减持"]
DATE_PATTERN = re.compile(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)')
CODE_PATTERN = re.compile(r'\b(\d{6})\b')
PRICE_PATTERN = re.compile(r'(?:成交价|价格|委托价|成交均价)[：: ]*(\d+\.\d{2,3})')
SHARES_PATTERN = re.compile(r'(?:数量|股数|成交数量|委托数量)[：: ]*(\d{1,6})')
FEE_PATTERN = re.compile(r'(?:手续费|佣金|费用)[：: ]*(\d+\.\d{2})')


def _get_ocr_engine():
    """懒加载OCR引擎，避免import时就下载模型"""
    try:
        from rapidocr_onnxruntime import RapidOCR
        return RapidOCR()
    except ImportError:
        return None


def _extract_text_from_image(image_bytes: bytes) -> str:
    """用OCR从图片中提取所有文字"""
    engine = _get_ocr_engine()
    if engine is None:
        # 降级：如果没有OCR引擎，尝试用Pillow打开后返回空（触发手动模式）
        return ""
    try:
        # RapidOCR 接受 numpy array 或 bytes
        import numpy as np
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(img)
        result, _ = engine(img_array)
        if not result:
            return ""
        # result 是 list of (box, text, confidence)
        texts = [item[1] for item in result if len(item) >= 2]
        return "\n".join(texts)
    except Exception as e:
        print(f"OCR error: {e}")
        return ""


def _parse_action(text: str) -> Optional[str]:
    """从文本中识别买卖方向"""
    for kw in BUY_KEYWORDS:
        if kw in text:
            return "买入"
    for kw in SELL_KEYWORDS:
        if kw in text:
            return "卖出"
    # 尝试从上下文判断
    if "买" in text:
        return "买入"
    if "卖" in text:
        return "卖出"
    return None


def _parse_stock_code_and_name(text: str) -> Tuple[Optional[str], Optional[str]]:
    """提取股票代码和名称"""
    code = None
    name = None

    # 方法1: 直接匹配6位数字代码
    matches = CODE_PATTERN.findall(text)
    if matches:
        code = matches[0]

    # 方法2: 从 "名称(代码)" 或 "代码 名称" 格式提取
    pattern2 = re.compile(r'([\u4e00-\u9fa5]{2,5})\s*[\(（]\s*(\d{6})\s*[\)）]')
    m2 = pattern2.search(text)
    if m2:
        name = m2.group(1)
        code = m2.group(2)

    # 方法3: 代码在前
    pattern3 = re.compile(r'(\d{6})\s+([\u4e00-\u9fa5]{2,5})')
    m3 = pattern3.search(text)
    if m3:
        code = m3.group(1)
        name = m3.group(2)

    # 尝试从文本行中提取名称（紧跟代码的汉字）
    if code and not name:
        lines = text.split("\n")
        for line in lines:
            if code in line:
                # 从同一行提取中文名称
                chinese_chars = re.findall(r'[\u4e00-\u9fa5]{2,5}', line)
                # 过滤掉"成交明细""委托""买卖"等关键词
                skip_words = {"成交明细", "委托", "成交", "申报", "确认", "买入", "卖出",
                              "名称", "代码", "价格", "数量", "金额", "手续费", "佣金",
                              "日期", "时间", "合计", "摘要", "备注", "状态", "方向"}
                for word in chinese_chars:
                    if word not in skip_words and len(word) >= 2:
                        name = word
                        break
                break

    return code, name


def _parse_price(text: str) -> Optional[float]:
    """提取成交价格"""
    # 优先匹配 "成交价: XX.XX"
    m = PRICE_PATTERN.search(text)
    if m:
        return float(m.group(1))

    # 退而求其次: 找所有价格格式的数字，选最可能的
    prices = re.findall(r'(\d{1,3}\.\d{2,3})', text)
    if prices:
        # 过滤掉明显不是股价的（如百分比、日期等）
        valid = [float(p) for p in prices if 0.5 <= float(p) <= 5000]
        if valid:
            return valid[0]
    return None


def _parse_shares(text: str) -> Optional[int]:
    """提取成交数量"""
    m = SHARES_PATTERN.search(text)
    if m:
        return int(m.group(1))

    # 尝试从文本中找数量
    # 常见格式: "数量 100" 或 "100股"
    patterns = [
        re.compile(r'(\d{2,6})\s*股'),
        re.compile(r'股数[：: ]*(\d{2,6})'),
    ]
    for p in patterns:
        m = p.search(text)
        if m:
            return int(m.group(1))
    return None


def _parse_date(text: str) -> Optional[str]:
    """提取交易日期，返回 ISO 格式"""
    m = DATE_PATTERN.search(text)
    if m:
        raw = m.group(1)
        # 统一格式
        raw = raw.replace("年", "-").replace("月", "-").replace("日", "")
        raw = raw.replace("/", "-")
        parts = raw.split("-")
        if len(parts) == 3:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return None


def _parse_fee(text: str) -> float:
    """提取手续费"""
    m = FEE_PATTERN.search(text)
    if m:
        return float(m.group(1))
    return 0.0


def parse_screenshot(image_bytes: bytes) -> Dict:
    """
    解析一张成交截图，返回结构化结果
    返回格式:
    {
        "success": bool,
        "code": "600519" | None,
        "name": "贵州茅台" | None,
        "action": "买入" | "卖出" | None,
        "shares": 100 | None,
        "price": 1680.50 | None,
        "fee": 5.0,
        "date": "2026-01-15" | None,
        "raw_text": "OCR提取的原始文本",
        "confidence": 0.85  # 解析置信度 0-1
    }
    """
    raw_text = _extract_text_from_image(image_bytes)

    if not raw_text:
        return {
            "success": False,
            "code": None, "name": None, "action": None,
            "shares": None, "price": None, "fee": 0.0,
            "date": None, "raw_text": "", "confidence": 0.0,
            "error": "OCR识别失败，请检查图片清晰度或手动录入"
        }

    code, name = _parse_stock_code_and_name(raw_text)
    action = _parse_action(raw_text)
    shares = _parse_shares(raw_text)
    price = _parse_price(raw_text)
    fee = _parse_fee(raw_text)
    date_str = _parse_date(raw_text)

    # 计算置信度
    fields_found = sum(1 for v in [code, name, action, shares, price] if v is not None)
    confidence = fields_found / 5.0

    success = all([code, action, shares, price])

    return {
        "success": success,
        "code": code,
        "name": name,
        "action": action,
        "shares": shares,
        "price": price,
        "fee": fee,
        "date": date_str,
        "raw_text": raw_text,
        "confidence": confidence,
        "error": None if success else f"部分字段缺失 (置信度 {confidence:.0%})"
    }


def parse_multiple_screenshots(image_list: List[bytes]) -> List[Dict]:
    """批量解析多张截图"""
    results = []
    for img_bytes in image_list:
        result = parse_screenshot(img_bytes)
        results.append(result)
    return results


def validate_transaction(parsed: Dict, existing_shares: int = 0) -> Tuple[bool, str]:
    """
    校验解析结果是否合理
    返回: (是否通过, 提示信息)
    """
    if not parsed.get("code"):
        return False, "缺少股票代码"
    if not parsed.get("action"):
        return False, "无法识别买卖方向"
    if not parsed.get("shares") or parsed["shares"] <= 0:
        return False, "数量无效"
    if not parsed.get("price") or parsed["price"] <= 0:
        return False, "价格无效"

    # 卖出时检查持仓
    if parsed["action"] == "卖出" and parsed["shares"] > existing_shares:
        return False, f"卖出数量({parsed['shares']})超过持仓({existing_shares})"

    return True, "校验通过"


# ============ 测试用 ============
if __name__ == "__main__":
    # 简单的自检
    test_text = """
    成交明细
    贵州茅台(600519)
    买入 100股
    成交价: 1680.500
    数量: 100
    手续费: 5.00
    日期: 2026-01-15
    """
    code, name = _parse_stock_code_and_name(test_text)
    action = _parse_action(test_text)
    shares = _parse_shares(test_text)
    price = _parse_price(test_text)
    date_str = _parse_date(test_text)

    print(f"代码: {code}")
    print(f"名称: {name}")
    print(f"方向: {action}")
    print(f"数量: {shares}")
    print(f"价格: {price}")
    print(f"日期: {date_str}")
    assert code == "600519"
    assert name == "贵州茅台"
    assert action == "买入"
    assert shares == 100
    assert price == 1680.50
    print("\n✅ 所有测试通过!")
