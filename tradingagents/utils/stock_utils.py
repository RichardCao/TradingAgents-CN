"""股票工具函数，提供股票代码识别、标准化与市场元数据。"""

import re
from typing import Dict, Tuple, Optional
from enum import Enum

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


_A_SHARE_SUFFIX_MAP = {
    ".SH": ("SSE", "上海证券交易所"),
    ".SS": ("SSE", "上海证券交易所"),
    ".SZ": ("SZSE", "深圳证券交易所"),
    ".BJ": ("BSE", "北京证券交易所"),
    ".XSHG": ("SSE", "上海证券交易所"),
    ".XSHE": ("SZSE", "深圳证券交易所"),
}

_US_SUFFIXES = (".US", ".NYSE", ".NASDAQ", ".N", ".O")

_BJ_PREFIXES = (
    "430", "440", "830", "831", "832", "833", "835", "836", "837", "838", "839",
    "870", "871", "872", "873", "874", "875", "876", "877", "878", "879",
    "880", "881", "882", "883", "884", "885", "886", "887", "888", "889",
)


class StockMarket(Enum):
    """股票市场枚举"""
    CHINA_A = "china_a"      # 中国A股
    HONG_KONG = "hong_kong"  # 港股
    US = "us"                # 美股
    UNKNOWN = "unknown"      # 未知


class StockUtils:
    """股票工具类"""

    @staticmethod
    def normalize_ticker_input(ticker: str) -> str:
        """标准化输入字符串，不改变市场语义。"""
        if ticker is None:
            return ""
        return str(ticker).strip().upper()

    @staticmethod
    def strip_exchange_suffix(ticker: str) -> str:
        """移除常见交易所后缀，保留主体代码。"""
        normalized = StockUtils.normalize_ticker_input(ticker)
        if not normalized:
            return normalized

        for suffix in sorted((*_A_SHARE_SUFFIX_MAP.keys(), ".HK", *_US_SUFFIXES), key=len, reverse=True):
            if normalized.endswith(suffix):
                return normalized[: -len(suffix)]

        if re.match(r"^(SH|SZ|BJ)\d{6}$", normalized):
            return normalized[2:]

        return normalized

    @staticmethod
    def normalize_display_symbol(ticker: str) -> str:
        """返回适合展示和大多数查询使用的标准主体代码。"""
        normalized = StockUtils.strip_exchange_suffix(ticker)
        if not normalized:
            return normalized

        market = StockUtils.identify_stock_market(ticker)
        if market == StockMarket.CHINA_A and normalized.isdigit():
            return normalized.zfill(6)
        if market == StockMarket.HONG_KONG and normalized.isdigit():
            return normalized.zfill(5)
        return normalized

    @staticmethod
    def build_qualified_ticker(ticker: str, market_hint: Optional[str] = None) -> Optional[str]:
        """构建标准代码，如 `600519.SH` / `09992.HK`。"""
        normalized = StockUtils.normalize_ticker_input(ticker)
        if not normalized:
            return None

        market = StockUtils.identify_stock_market(ticker)
        if market == StockMarket.UNKNOWN and market_hint:
            hint = str(market_hint).strip().upper()
            if hint in {"A股", "CHINA_A", "CN", "SH", "SZ", "SSE", "SZSE", "BSE"}:
                market = StockMarket.CHINA_A
            elif hint in {"港股", "HK", "HONG_KONG"}:
                market = StockMarket.HONG_KONG
            elif hint in {"美股", "US"}:
                market = StockMarket.US

        display_symbol = StockUtils.normalize_display_symbol(ticker)
        if market == StockMarket.CHINA_A and display_symbol.isdigit():
            _, exchange_code, _ = StockUtils._infer_china_a_metadata(display_symbol)
            suffix_map = {"SSE": ".SH", "SZSE": ".SZ", "BSE": ".BJ"}
            return f"{display_symbol}{suffix_map.get(exchange_code, '')}" if exchange_code else display_symbol
        if market == StockMarket.HONG_KONG and display_symbol.isdigit():
            return f"{display_symbol}.HK"
        if market == StockMarket.US:
            return display_symbol
        return normalized

    @staticmethod
    def _infer_china_a_metadata(code: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """推断 A 股的交易所与板块。"""
        normalized_code = str(code).zfill(6)

        if normalized_code.startswith(_BJ_PREFIXES) or normalized_code[:1] in {"4", "8"}:
            return "北京证券交易所", "BSE", "北交所"
        if normalized_code.startswith("68"):
            return "上海证券交易所", "SSE", "科创板"
        if normalized_code.startswith("30"):
            return "深圳证券交易所", "SZSE", "创业板"
        if normalized_code.startswith("60"):
            return "上海证券交易所", "SSE", "主板"
        if normalized_code.startswith(("00", "001", "002", "003", "20")):
            return "深圳证券交易所", "SZSE", "主板"
        return None, None, None
    
    @staticmethod
    def identify_stock_market(ticker: str) -> StockMarket:
        """
        识别股票代码所属市场

        Args:
            ticker: 股票代码

        Returns:
            StockMarket: 股票市场类型
        """
        if not ticker:
            return StockMarket.UNKNOWN

        ticker = StockUtils.normalize_ticker_input(ticker)

        # 中国A股：6位数字 / 标准后缀 / 前缀格式
        if re.match(r'^\d{6}$', ticker):
            return StockMarket.CHINA_A
        if re.match(r'^\d{6}(\.(SH|SZ|SS|BJ|XSHG|XSHE))$', ticker):
            return StockMarket.CHINA_A
        if re.match(r'^(SH|SZ|BJ)\d{6}$', ticker):
            return StockMarket.CHINA_A

        # 港股：4-5位数字.HK 或 纯4-5位数字（支持0700.HK、09988.HK、00700、9988格式）
        if re.match(r'^\d{4,5}\.HK$', ticker) or re.match(r'^\d{4,5}$', ticker):
            return StockMarket.HONG_KONG

        # 美股：字母代码或带美国市场后缀
        if any(ticker.endswith(suffix) for suffix in _US_SUFFIXES):
            return StockMarket.US
        if re.match(r'^[A-Z][A-Z0-9.\-]{0,9}$', ticker):
            return StockMarket.US

        return StockMarket.UNKNOWN
    
    @staticmethod
    def is_china_stock(ticker: str) -> bool:
        """
        判断是否为中国A股
        
        Args:
            ticker: 股票代码
            
        Returns:
            bool: 是否为中国A股
        """
        return StockUtils.identify_stock_market(ticker) == StockMarket.CHINA_A
    
    @staticmethod
    def is_hk_stock(ticker: str) -> bool:
        """
        判断是否为港股
        
        Args:
            ticker: 股票代码
            
        Returns:
            bool: 是否为港股
        """
        return StockUtils.identify_stock_market(ticker) == StockMarket.HONG_KONG
    
    @staticmethod
    def is_us_stock(ticker: str) -> bool:
        """
        判断是否为美股
        
        Args:
            ticker: 股票代码
            
        Returns:
            bool: 是否为美股
        """
        return StockUtils.identify_stock_market(ticker) == StockMarket.US
    
    @staticmethod
    def get_currency_info(ticker: str) -> Tuple[str, str]:
        """
        根据股票代码获取货币信息
        
        Args:
            ticker: 股票代码
            
        Returns:
            Tuple[str, str]: (货币名称, 货币符号)
        """
        market = StockUtils.identify_stock_market(ticker)
        
        if market == StockMarket.CHINA_A:
            return "人民币", "¥"
        elif market == StockMarket.HONG_KONG:
            return "港币", "HK$"
        elif market == StockMarket.US:
            return "美元", "$"
        else:
            return "未知", "?"
    
    @staticmethod
    def get_data_source(ticker: str) -> str:
        """
        根据股票代码获取推荐的数据源
        
        Args:
            ticker: 股票代码
            
        Returns:
            str: 数据源名称
        """
        market = StockUtils.identify_stock_market(ticker)
        
        if market == StockMarket.CHINA_A:
            return "china_unified"  # 使用统一的中国股票数据源
        elif market == StockMarket.HONG_KONG:
            return "yahoo_finance"  # 港股使用Yahoo Finance
        elif market == StockMarket.US:
            return "yahoo_finance"  # 美股使用Yahoo Finance
        else:
            return "unknown"
    
    @staticmethod
    def normalize_hk_ticker(ticker: str) -> str:
        """
        标准化港股代码格式
        
        Args:
            ticker: 原始港股代码
            
        Returns:
            str: 标准化后的港股代码
        """
        if not ticker:
            return ticker
            
        ticker = StockUtils.normalize_ticker_input(ticker)
        
        # 如果是纯4-5位数字，添加.HK后缀
        if re.match(r'^\d{4,5}$', ticker):
            return f"{ticker}.HK"

        # 如果已经是正确格式，直接返回
        if re.match(r'^\d{4,5}\.HK$', ticker):
            return ticker
            
        return ticker
    
    @staticmethod
    def get_market_info(ticker: str) -> Dict:
        """
        获取股票市场的详细信息
        
        Args:
            ticker: 股票代码
            
        Returns:
            Dict: 市场信息字典
        """
        normalized_input = StockUtils.normalize_ticker_input(ticker)
        market = StockUtils.identify_stock_market(normalized_input)
        currency_name, currency_symbol = StockUtils.get_currency_info(ticker)
        data_source = StockUtils.get_data_source(ticker)
        display_symbol = StockUtils.normalize_display_symbol(normalized_input)
        ticker_qualified = StockUtils.build_qualified_ticker(normalized_input)
        exchange = None
        exchange_code = None
        board = None

        if market == StockMarket.CHINA_A and display_symbol.isdigit():
            exchange, exchange_code, board = StockUtils._infer_china_a_metadata(display_symbol)
        elif market == StockMarket.HONG_KONG:
            exchange, exchange_code, board = "香港交易所", "SEHK", None
        elif market == StockMarket.US:
            exchange, exchange_code, board = None, None, None
        
        market_names = {
            StockMarket.CHINA_A: "中国A股",
            StockMarket.HONG_KONG: "港股",
            StockMarket.US: "美股",
            StockMarket.UNKNOWN: "未知市场"
        }
        
        return {
            "ticker": normalized_input,
            "ticker_input": normalized_input,
            "ticker_clean": display_symbol,
            "ticker_qualified": ticker_qualified,
            "display_symbol": display_symbol or normalized_input,
            "full_symbol": ticker_qualified,
            "market": market.value,
            "market_name": market_names[market],
            "currency_name": currency_name,
            "currency_symbol": currency_symbol,
            "data_source": data_source,
            "exchange": exchange,
            "exchange_code": exchange_code,
            "board": board,
            "is_china": market == StockMarket.CHINA_A,
            "is_hk": market == StockMarket.HONG_KONG,
            "is_us": market == StockMarket.US
        }


# 便捷函数，保持向后兼容
def is_china_stock(ticker: str) -> bool:
    """判断是否为中国A股（向后兼容）"""
    return StockUtils.is_china_stock(ticker)


def is_hk_stock(ticker: str) -> bool:
    """判断是否为港股"""
    return StockUtils.is_hk_stock(ticker)


def is_us_stock(ticker: str) -> bool:
    """判断是否为美股"""
    return StockUtils.is_us_stock(ticker)


def get_stock_market_info(ticker: str) -> Dict:
    """获取股票市场信息"""
    return StockUtils.get_market_info(ticker)
