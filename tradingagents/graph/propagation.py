# TradingAgents/graph/propagation.py

from typing import Dict, Any

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self, company_name: str, trade_date: str
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        from langchain_core.messages import HumanMessage
        from tradingagents.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(company_name)
        display_symbol = market_info.get("display_symbol") or company_name
        ticker_qualified = market_info.get("ticker_qualified")
        market_name = market_info.get("market_name") or "未知市场"

        analysis_request = f"请对股票 {display_symbol} 进行全面分析，交易日期为 {trade_date}。"
        if ticker_qualified and ticker_qualified != display_symbol:
            analysis_request += f" 标准代码为 {ticker_qualified}。"
        analysis_request += f" 市场为 {market_name}。"

        return {
            "messages": [HumanMessage(content=analysis_request)],
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "ticker_input": market_info.get("ticker_input"),
            "ticker_clean": market_info.get("ticker_clean"),
            "ticker_qualified": ticker_qualified,
            "display_symbol": display_symbol,
            "market_name": market_name,
            "exchange": market_info.get("exchange"),
            "exchange_code": market_info.get("exchange_code"),
            "board": market_info.get("board"),
            "investment_debate_state": InvestDebateState(
                {"history": "", "current_response": "", "count": 0}
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "history": "",
                    "current_risky_response": "",
                    "current_safe_response": "",
                    "current_neutral_response": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
        }

    def get_graph_args(self, use_progress_callback: bool = False) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            use_progress_callback: If True, use 'updates' mode for node-level progress tracking.
                                  If False, use 'values' mode for complete state updates.
        """
        # 使用 'updates' 模式可以获取节点级别的更新，用于进度跟踪
        # 使用 'values' 模式可以获取完整的状态更新
        stream_mode = "updates" if use_progress_callback else "values"

        return {
            "stream_mode": stream_mode,
            "config": {"recursion_limit": self.max_recur_limit},
        }
