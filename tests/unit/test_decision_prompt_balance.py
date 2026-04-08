from tradingagents.agents.managers.research_manager import _build_research_manager_prompt
from tradingagents.agents.managers.risk_manager import _build_risk_manager_prompt


def test_research_manager_prompt_treats_hold_as_valid_outcome() -> None:
    prompt = _build_research_manager_prompt(
        past_memory_str="过去曾因过度悲观而错过反弹。",
        market_research_report="市场报告",
        sentiment_report="情绪报告",
        news_report="新闻报告",
        fundamentals_report="基本面报告",
        history="辩论历史",
    )

    assert "持有不是“后备选项”" in prompt
    assert "优先考虑持有，而不是机械地下调为卖出" in prompt
    assert "卖出也不是默认的保守答案" in prompt
    assert "仅在基于所提出论点有强有力理由时选择持有" not in prompt


def test_risk_manager_prompt_does_not_treat_sell_as_default_conservative_choice() -> None:
    prompt = _build_risk_manager_prompt(
        trader_plan="建议买入并分批建仓。",
        past_memory_str="过去曾在一般性风险下过度保守。",
        history="风险辩论历史",
    )

    assert "持有是有效结论之一" in prompt
    assert "卖出不是默认保守答案" in prompt
    assert "不要因为存在一般性风险、短期波动或信息不完整，就把结果自动压成卖出" in prompt
    assert "只有在有具体论据强烈支持时才选择持有" not in prompt
