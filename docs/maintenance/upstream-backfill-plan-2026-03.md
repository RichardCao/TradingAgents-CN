# 上游能力回补方案（2026-03）

本文档是在 [upstream-review-2026-03.md](/Users/create/.codex/repo-compare/TradingAgents-CN/docs/maintenance/upstream-review-2026-03.md) 的基础上，进一步把“值得回补但暂不执行”的能力整理成可实施方案。

约束：

- 当前阶段只做方案，不落代码
- 优先选择“局部回补”，不做大规模跟随式同步
- 不为了对齐上游而破坏现有前后端、MongoDB/Redis、配置管理与中文报告体系

补充说明：

- 本文档最初写于“开始回补之前”
- 到 2026-03-29 为止，其中多项已在当前仓库落地，不应再按本文原始顺序重复执行
- 实际推进前，应先看本仓库近期 `backfill:` 提交记录

## 0. 当前现状与剩余 checklist

### 0.1 已经完成的回补项

根据当前仓库 commit 历史，以下上游能力已经落地：

- `Responses API` 灰度接入
- `yfinance` retry/backoff
- `exchange-qualified tickers`
- `Anthropic effort / thinking`
- `initialize all debate state fields`
- `comma-separated indicators`
- `malformed CSV / NaN parsing hardening`
- `http_client / SSL customization`

另外，`debate round config to ConditionalLogic` 也已经由当前主链路覆盖：

- `tradingagents/graph/trading_graph.py` 已将配置显式传入 `ConditionalLogic`
- `tests/test_conditional_logic_config.py`
- `tests/test_debate_flow_simulation.py`

### 0.2 当前不要重复做的项

如果继续回补，上面这些能力都不应再次作为新任务执行，除非只是补测试、补文档或做局部收口。

### 0.3 当前剩余待执行的 shortlist

截至 2026-03-30，这一轮稳定性回补已基本清空，当前不再建议把以下三项继续列为待办：

- `comma-separated indicators`
- `malformed CSV / NaN parsing hardening`
- `http_client / SSL customization`

当前如果还要继续做“上游回补”，更合理的是：

1. 保持这批已回补能力的回归测试和真实任务验证
2. 只在确有收益时，再评估 `UTF-8` 进程级默认值之类的低优先级对齐项
3. 更高风险的行为层改动仍然维持“先方案、暂不直接落代码”

### 0.4 建议执行顺序

建议下一步不再按“继续补 bugfix”的思路推进，而是按下面顺序：

1. 回归验证和文档收口
2. 观察真实分析任务与多模型调用链路
3. 再决定是否评估更高层的上游能力回补

## 1. 总体策略

建议采用“三段式回补”：

1. **调用链稳定性优先**
   - OpenAI Responses API
   - yfinance 指数退避
2. **身份一致性优先**
   - exchange-qualified ticker 透传
3. **模型能力增强择机做**
   - Anthropic effort level
   - debate / state 初始化类修复

不建议作为近期主目标的上游能力：

- 五档评级体系
- portfolio manager 结构重写
- 上游 CLI / 安装链路整体迁移

## 2. 回补候选 1：OpenAI Responses API

### 2.1 目标

把当前“原生 OpenAI 模型”的调用链，从部分 `ChatOpenAI.invoke()/stream()` 迁移为可控的 Responses API 路径，但只做**小范围灰度接入**。

### 2.2 为什么值得做

中文仓库当前已经在处理：

- 长文本报告阶段的稳定性
- 流式 / 非流式切换
- 错误可观测性

而仓库内已经存在 Responses API 的使用痕迹，例如：

- `tradingagents/dataflows/interface.py`

这说明：

- 当前代码库并不是完全没有 Responses API 基础
- 更合理的做法是“复用已有经验，向主分析链路局部推广”

### 2.3 建议范围

建议只覆盖：

- `provider = openai`
- 明确使用原生 OpenAI 兼容能力、且不是特殊聚合网关的模型

暂不直接覆盖：

- 自定义 OpenAI 兼容网关
- DashScope / Zhipu / Google / Qianfan 等各类适配器
- Memory、embeddings、配置测试等外围链路

### 2.4 建议落点

优先评估这些模块：

- `tradingagents/graph/trading_graph.py`
- `tradingagents/agents/utils/streaming_utils.py`
- `tradingagents/llm_adapters/openai_compatible_base.py`
- `app/services/simple_analysis_service.py`

### 2.5 实施方式

建议按以下顺序：

1. 新增一个非常窄的 Responses API 包装层
   - 输入：模型名、消息、是否流式、超时、温度、max_tokens
   - 输出：与当前主链路兼容的文本 / chunk 结构

2. 增加“能力探测 + 配置开关”
   - 例如仅当：
     - provider = `openai`
     - base_url 为官方 OpenAI 或显式标记支持 Responses API
   - 才进入新路径

3. 保留旧路径作为 fallback
   - Responses API 失败时回退到当前 `invoke()/stream()`

4. 先只切一个长文本阶段
   - 比如报告中最容易超时的分析节点
   - 不要一开始把全部 analyst 节点都切过去

### 2.6 风险

- 各家 OpenAI 兼容网关对 Responses API 的支持并不一致
- 现有前端和日志系统对返回结构有既定预期
- LangChain 与原生 OpenAI SDK 混用时，错误处理和 token 统计口径可能不同

### 2.7 验证建议

- 单测：
  - 新增 Responses API 包装层测试
  - fallback 测试
- 集成：
  - 选一个中文单股分析任务
  - 观察阶段级耗时、失败点和输出格式
- 回归：
  - 报告生成
  - 流式阶段日志
  - 错误提示是否仍能带阶段信息

## 3. 回补候选 2：yfinance 指数退避

### 3.1 目标

统一处理港股 / 美股 yfinance 的限流与短暂失败场景，避免出现：

- 部分成功、部分失败
- 有价格没涨跌幅
- 有缓存但展示口径不一致

### 3.2 为什么值得做

当前仓库中 yfinance 入口比较分散，主要在：

- `app/services/foreign_stock_service.py`
- `tradingagents/dataflows/providers/hk/hk_stock.py`
- `tradingagents/dataflows/providers/us/yfinance.py`
- `tradingagents/dataflows/interface.py`
- `tradingagents/dataflows/providers/us/optimized.py`

现状问题是：

- 有的地方有 sleep / 简单重试
- 有的地方没有统一指数退避
- 同一类错误在不同入口处理方式不同

### 3.3 建议范围

第一阶段只覆盖：

- 港股实时行情
- 港股 / 美股基础信息
- 港股 / 美股 K 线

第二阶段再考虑：

- 基本面辅助读取
- 技术指标链路

### 3.4 建议落点

建议抽一个统一 helper，例如：

- `tradingagents/dataflows/providers/common/yfinance_client.py`

职责：

- 封装 `yf.Ticker(...)`
- 封装 `info` / `history()` 调用
- 识别限流、超时、空数据、瞬时网络失败
- 统一指数退避和最大重试次数

现有入口改为调用该 helper，而不是各自直接裸调 `Ticker().history()`。

### 3.5 实施方式

建议做法：

1. 新增统一重试策略
   - 最大重试 3 到 4 次
   - 间隔 1s / 2s / 4s / 8s
   - 只对明确瞬时错误重试

2. 区分错误类型
   - 空数据：不重试或只轻微重试
   - rate limit / connection reset / timeout：指数退避
   - 明确无效代码：直接失败

3. 把缓存口径一起统一
   - 成功拿到实时值才更新实时展示缓存
   - 失败时只读旧缓存，不写入半成品

4. 给日志加结构化字段
   - `symbol`
   - `market`
   - `source=yfinance`
   - `attempt`
   - `backoff_seconds`

### 3.6 风险

- yfinance 错误类型并不完全稳定，异常文本可能变化
- 过度重试会拖慢请求，影响前端体验
- 一些接口不是 rate limit，而是数据本身没有更新

### 3.7 验证建议

- 单测：
  - mock `Ticker.history/info` 的 transient error
  - 验证重试次数和 fallback
- 回归：
  - 港股 09992 / 06166
  - 美股热门标的
  - 有缓存 / 无缓存两条路径

## 4. 回补候选 3：exchange-qualified ticker 透传

### 4.1 目标

把股票身份从“字符串 ticker”升级为“输入代码 + 标准代码 + 市场/交易所信息”的组合，减少多市场分析中代码被清洗错、提示词里丢后缀、工具误选的问题。

### 4.2 为什么值得做

当前仓库已经有多处 ticker 处理逻辑：

- `tradingagents.utils.stock_utils.StockUtils`
- `app/services/simple_analysis_service.py`
- `tradingagents/dataflows/news/realtime_news.py`
- `app/services/favorites_service.py`
- `app/routers/stocks.py`
- `app/routers/stock_sync.py`

问题不是“完全没有标准化”，而是：

- 标准化入口不唯一
- 有些地方仍在手工 `replace('.HK')`、`replace('.SH')`
- prompt、工具层、缓存层用的可能不是同一个口径

### 4.3 建议范围

第一阶段只要求“贯穿主分析链路”：

- 用户输入
- 任务入队
- graph state
- analyst prompt
- 关键工具调用

第二阶段再扩展到：

- 数据同步
- 报告展示
- 历史记录 / 数据清理

### 4.4 建议落点

建议新增一个标准结构，例如：

```python
{
  "ticker_input": "09992",
  "ticker_qualified": "09992.HK",
  "market": "HK",
  "exchange": "HKEX",
  "display_symbol": "09992"
}
```

优先在这些地方贯穿：

- `app/services/simple_analysis_service.py`
- `tradingagents/graph/*`
- `tradingagents/agents/analysts/*`
- `tradingagents/tools/unified_news_tool.py`
- `tradingagents/dataflows/news/realtime_news.py`

### 4.5 实施方式

建议做法：

1. 统一一个“ticker 规范化入口”
   - 不允许每个 analyst 自己 `replace('.HK')`

2. graph state 保存两个字段
   - `ticker_input`
   - `ticker_qualified`

3. prompt 默认使用 `ticker_qualified`
   - 只有面向用户显示时再用 `display_symbol`

4. 工具调用按市场转换
   - A 股工具可用 `display_symbol`
   - 港股 / 美股工具优先保留合格后缀

### 4.6 风险

- 老代码大量直接假设 `ticker` 是字符串
- 全面替换字段名会引发大范围回归

因此建议：

- 第一阶段不要重命名大量已有字段
- 先“增加” `ticker_qualified`
- 再逐步把关键链路切换过去

### 4.7 验证建议

- 港股：
  - `09992`
  - `09992.HK`
  - `0700.HK`
- A 股：
  - `600519`
  - `600519.SH`
- 美股：
  - `AAPL`

重点验证：

- prompt 中代码是否正确
- analyst 选用工具是否正确
- 报告标题与展示是否仍符合中文界面预期

## 5. 回补候选 4：Anthropic effort level

### 5.1 目标

为 Claude 系列模型增加可选的 `effort level` / `thinking budget` 参数支持，但保持为**可选增强**，不改变当前默认 GPT 主链路。

### 5.2 建议范围

仅做配置层和适配层：

- `app/services/config_service.py`
- `tradingagents/graph/trading_graph.py`
- 可能涉及 `tradingagents/llm_adapters/`

### 5.3 建议方式

- 配置项默认关闭
- 只有 provider = `anthropic` 时才展示
- 没有显式设置时完全保持当前行为

### 5.4 为什么不是近期优先级

- 你当前主要使用 GPT 路线
- 对当前港股/A股数据链路稳定性没有直接帮助

## 6. 不建议直接回补的内容

以下能力暂不建议直接照搬：

### 6.1 五档评级体系

不建议原因：

- 这会碰提示词
- 会碰前端展示
- 会碰报告结构
- 会碰当前已有中文标题与报告模块映射

它的风险明显高于收益。

### 6.2 portfolio manager 标准化重写

不建议原因：

- 中文仓库当前不是纯 CLI graph 项目
- 已经有任务中心、报告页、配置管理与多市场逻辑
- 直接套上游的 manager 结构会牵一发动全身

## 7. 推荐实施顺序

如果后续你决定真的开始做，我建议严格按下面顺序推进：

1. `yfinance` 指数退避
   - 改动局部
   - 风险低
   - 对港股/美股实际价值最高

2. `ticker_qualified` 贯穿
   - 先加字段，不删旧字段
   - 控制回归范围

3. OpenAI Responses API 灰度接入
   - 先单阶段、单 provider
   - 保留 fallback

4. Anthropic effort level
   - 放到最后

## 8. 建议的交付方式

建议不要一次做成一个大 PR，而是拆成 3 到 4 个小 PR：

1. `fix: add yfinance retry/backoff for hk/us quotes`
2. `refactor: preserve qualified tickers in analysis pipeline`
3. `feat: add responses-api pilot for native openai models`
4. `feat: add optional anthropic effort level support`

这样更容易验证，也更容易回滚。

## 9. 当前结论

截至 2026-03-28，我建议的“先设计、不执行”结论是：

- **最值得回补的是**：
  - `yfinance` 指数退避
  - `exchange-qualified ticker` 透传
  - OpenAI Responses API 灰度接入
- **最不建议现在动的是**：
  - 五档评级体系
  - portfolio manager 重写
- **最佳推进方式**：
  - 小步分批
  - 每步都带单测和真实市场回归
  - 先解决稳定性，再做模型能力增强
