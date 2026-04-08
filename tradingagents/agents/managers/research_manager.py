import time
import json

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
from tradingagents.agents.utils.streaming_utils import stream_text_response
logger = get_logger("default")


def _build_research_manager_prompt(
    *,
    past_memory_str: str,
    market_research_report: str,
    sentiment_report: str,
    news_report: str,
    fundamentals_report: str,
    history: str,
) -> str:
    return f"""作为投资组合经理和辩论主持人，您的职责是批判性地评估这轮辩论，并在买入、持有、卖出之间做出明确且证据驱动的决策。

持有不是“后备选项”，而是一个正常且有效的结论。当上涨空间不够清晰、下行风险尚未显著失控、估值大体合理、催化剂时点不明确，或者多空证据质量相近时，应当明确选择持有，并说明继续观察的条件。

卖出也不是默认的保守答案。只有在以下情况之一成立时，才应建议卖出：
- 基本面或投资逻辑已经明显恶化
- 估值显著透支且缺乏足够支撑
- 下行风险相对上行空间明显更大
- 存在高概率、近期限内会兑现的重要负面催化剂

如果只是存在一般性风险、信息仍不充分，或多空因素尚未拉开明显差距，请优先考虑持有，而不是机械地下调为卖出。

请完成以下交付：
1. 您的建议：买入 / 持有 / 卖出
2. 理由：说明哪些证据最能支持该结论
3. 战略行动：下一步执行或观察计划
4. 目标价格分析：基于所有可用报告（基本面、新闻、情绪），给出价格区间和具体目标。考虑：
- 基本面报告中的基本估值
- 新闻对价格预期的影响
- 情绪驱动的价格调整
- 技术支撑/阻力位
- 风险调整后的保守 / 基准 / 乐观情景
- 1个月、3个月、6个月的时间范围

请提供具体目标价格；如果结论为持有，也要给出继续持有的合理区间与触发条件。

以下是您对错误的过去反思：
\"{past_memory_str}\"

以下是综合分析报告：
市场研究：{market_research_report}

情绪分析：{sentiment_report}

新闻分析：{news_report}

基本面分析：{fundamentals_report}

以下是辩论：
辩论历史：
{history}

请用中文撰写所有分析内容和建议。"""


def create_research_manager(llm, memory):
    def research_manager_node(state) -> dict:
        history = state["investment_debate_state"].get("history", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        investment_debate_state = state["investment_debate_state"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"

        # 安全检查：确保memory不为None
        if memory is not None:
            past_memories = memory.get_memories(curr_situation, n_matches=2)
        else:
            logger.warning(f"⚠️ [DEBUG] memory为None，跳过历史记忆检索")
            past_memories = []

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        prompt = _build_research_manager_prompt(
            past_memory_str=past_memory_str,
            market_research_report=market_research_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            history=history,
        )

        # 📊 统计 prompt 大小
        prompt_length = len(prompt)
        estimated_tokens = int(prompt_length / 1.8)

        logger.info(f"📊 [Research Manager] Prompt 统计:")
        logger.info(f"   - 辩论历史长度: {len(history)} 字符")
        logger.info(f"   - 总 Prompt 长度: {prompt_length} 字符")
        logger.info(f"   - 估算输入 Token: ~{estimated_tokens} tokens")

        # ⏱️ 记录开始时间
        start_time = time.time()

        response = stream_text_response(llm, prompt, "Research Manager")

        # ⏱️ 记录结束时间
        elapsed_time = time.time() - start_time

        # 📊 统计响应信息
        response_length = len(response.content) if response and hasattr(response, 'content') else 0
        estimated_output_tokens = int(response_length / 1.8)

        logger.info(f"⏱️ [Research Manager] LLM调用耗时: {elapsed_time:.2f}秒")
        logger.info(f"📊 [Research Manager] 响应统计: {response_length} 字符, 估算~{estimated_output_tokens} tokens")

        new_investment_debate_state = {
            "judge_decision": response.content,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": response.content,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": response.content,
        }

    return research_manager_node
