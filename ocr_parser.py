import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

# 全局引擎变量，延迟加载
_ocr_engine = None

def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            _ocr_engine = RapidOCR()
        except Exception as e:
            print(f"OCR 引擎初始化失败: {e}")
            _ocr_engine = None
    return _ocr_engine

def extract_text_from_image(image):
    """
    从图片中提取文本和坐标
    image: PIL.Image 对象
    返回 (boxes, texts)
    """
    engine = get_ocr_engine()
    if engine is None:
        return [], []

    if image.mode != 'RGB':
        image = image.convert('RGB')
    img_np = np.array(image)

    result, elapse = engine(img_np)
    if result:
        boxes = [item[0] for item in result]
        texts = [item[1] for item in result]
        return boxes, texts
    else:
        return [], []

def parse_stock_screenshot(boxes, texts):
    """
    简单解析股票成交截图的关键信息
    返回字典：stock_code, stock_name, direction, quantity, price
    """
    # 按垂直位置排序
    combined = list(zip(boxes, texts))
    combined.sort(key=lambda x: x[0][:, 1].mean())  # 按 y 坐标排序
    sorted_texts = [item[1] for item in combined]

    stock_code = ""
    stock_name = ""
    direction = ""
    quantity = ""
    price = ""

    for text in sorted_texts:
        t = text.strip()
        # 股票代码：6位数字
        if not stock_code and len(t) == 6 and t.isdigit():
            stock_code = t
        # 买卖方向
        if t in ["买入", "卖出", "买", "卖"]:
            direction = t
        # 尝试提取价格和数量（包含小数点或逗号的数字）
        if ("." in t or "," in t) and any(c.isdigit() for c in t):
            try:
                num = float(t.replace(",", ""))
                # 简单启发：价格一般在 0.01~9999 之间，数量通常是整数
                if not price and num < 10000:
                    price = t
                elif not quantity and num >= 100:
                    quantity = t
            except:
                pass

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "direction": direction,
        "quantity": quantity,
        "price": price
    }
