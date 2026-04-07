# A 股原生社媒数据源接入方案

## 当前已实现状态

截至当前仓库状态，下面这些能力已经落地，不再只是方案：

- 已提供两条显式同步入口：
  - A 股原生社媒同步
  - 新闻回退生成社媒快照
- A 股原生社媒同步已支持：
  - 官方互动问答：`stock_irm_cninfo`、`stock_sns_sseinfo`
  - `cninfo` 回答详情回补：`stock_irm_ans_cninfo`
  - 社区热度 / 趋势：
    - `stock_hot_rank_em`
    - `stock_hot_rank_detail_em`
    - `stock_hot_rank_latest_em`
    - `stock_hot_rank_detail_realtime_em`
    - `stock_hot_keyword_em`
    - `stock_hot_rank_relate_em`
    - `stock_hot_up_em`
    - `stock_hot_follow_xq`
    - `stock_hot_tweet_xq`
    - `stock_hot_deal_xq`
    - `stock_hot_search_baidu`
- A 股原生同步现在会聚合多个可用官方源，而不是命中第一个后停止。
- 分析前预同步已经收口为：
  - 优先原生社媒数据
  - 分析阶段只读
  - `news_proxy` 不再默认代表“原生社媒已准备完成”
- 前端“内容数据”页已经能直接查看：
  - 已同步新闻
  - 互动问答
  - 社媒热度
  - 新闻回退
- 前端“内容数据”页已支持：
  - 来源中文标签
  - 来源分布概览
  - 来源 / 关键词筛选
  - 跳转同步历史
  - 跳转数据清理

因此，本文档后面的内容应理解为：

- 一部分已经完成
- 一部分仍是后续可以继续增强的方向
- 不是“当前仓库仍完全停留在新闻代理阶段”

## 背景

当前仓库里的 A 股“社媒同步”主链路，本质上仍是：

1. 先同步 `stock_news`
2. 再把新闻转写为 `social_media_messages`
3. 由社媒分析师在分析阶段只读这些“新闻代理舆情”

这条链路可以跑通流程，但它并不是原生社媒数据：

- 它本质上还是新闻
- 很难区分“投资者讨论”与“媒体报道”
- 无法回答“散户在聊什么”“董秘回复了什么”“个股热度是否异动”这类更接近情绪分析的问题

因此，A 股社媒链路应该改成：

- 原生社媒 / 互动数据优先
- 新闻只做辅助上下文
- 分析阶段只读，不在运行中现抓
- 原生社媒同步与“新闻回退快照同步”分成两条显式入口，不做透明混用

## 当前代码现状

- `app/services/social_media_sync_service.py`
  - 当前只支持 `sync_social_media_from_news_proxy(...)`
  - 数据源写入为 `stock_news_proxy`
- `tradingagents/agents/analysts/social_media_analyst.py`
  - 已切到“分析阶段只读”
- `app/services/analysis_presync_service.py`
  - 已能在分析前阻断缺失社媒数据的任务

这意味着主链路的“只读化”已经具备，真正缺的是原生数据源。

## 推荐源分层

### 第一层：官方互动问答，作为主社媒源

这层是最值得先接入的。

#### 1. 深证互动易 / 互动易

- 官方站点：`https://irm.cninfo.com.cn/`
- Tushare：
  - `irm_qa_sz`
  - `irm_qa_sh`
- AKShare：
  - `stock_irm_cninfo`
  - `stock_irm_ans_cninfo`
  - `stock_sns_sseinfo`

这类数据的价值最高，因为它有几个关键特征：

- 是 A 股原生语境，不是海外社媒迁移物
- 问题与回答都围绕具体上市公司
- 文本质量通常高于股吧短帖
- 对事件、产能、订单、业务、政策反馈非常敏感
- 对于分析师来说，可直接形成“投资者关注焦点”和“公司回应口径”

建议把这类数据定义为：

- `platform=cninfo_irm`
- `platform=sse_einteractive`
- `message_type=investor_question`
- `message_type=company_answer`

#### 2. 为什么它应该是第一优先级

原因很简单：

- 它是官方平台或交易所互动平台
- 数据结构稳定
- 噪声远小于开放社区
- 与具体股票的相关性最高
- 最容易在当前项目里稳定落地

如果只做一版最值钱的 A 股原生社媒能力，优先做这一层是对的。

## 第二层：社区热度和讨论热度，作为情绪强度信号

这层负责回答“市场正在不正在关注这只股票”。

### 1. 东方财富股吧热度

AKShare 已有一批成熟接口：

- `stock_hot_rank_em`
- `stock_hot_rank_detail_em`
- `stock_hot_rank_detail_realtime_em`
- `stock_hot_keyword_em`
- `stock_hot_rank_latest_em`
- `stock_hot_rank_relate_em`

这类数据虽然不直接给帖文全文，但已经足够提供：

- 当前热度排名
- 历史热度趋势
- 盘中热度变动
- 相关热门关键词
- 相关联个股

它很适合作为“社区热度侧”的稳定信号层。

建议不要把它强行塞成普通 message，而是单独定义为：

- `social_media_snapshots`
  - `platform=eastmoney_guba`
  - `metric_type=rank`
  - `metric_type=rank_realtime`
  - `metric_type=keyword`
  - `metric_type=related_stock`

如果为了最小代价先不加新集合，也可以先写入 `social_media_messages`，但长期更建议拆出快照表。

### 2. 雪球热度

AKShare 文档里也有现成热度接口：

- `stock_hot_follow_xq`
- `stock_hot_tweet_xq`
- `stock_hot_deal_xq`

它们的意义分别接近：

- 关注度
- 讨论热度
- 交易热度

这类数据的优点是：

- 指标干净
- 易于做时间序列对比
- 对“市场情绪抬升/退潮”很敏感

缺点是：

- 更像热度排行，不是原始帖子文本
- 单靠它不足以支撑完整“社媒观点摘要”

因此，雪球更适合作为第二层量化信号，而不是唯一主源。

## 第三层：新闻，只做辅助，不再伪装成社媒本体

这一层仍然有价值，但定位要变。

推荐继续使用：

- Tushare `news`
- Tushare `major_news`
- AKShare `stock_news_em`

它们应该服务于：

- 事件背景补充
- 时间线校对
- 解释热度异动原因
- 给社媒分析师补充“媒体叙事”

但不应该再作为 A 股社媒的默认主源。

换句话说：

- `stock_news_proxy` 可以保留
- 但只能作为 fallback
- 不能再代表“原生社媒已就绪”
- 更不应伪装成原生社媒同步的默认行为

## 不建议优先接入的方向

### 1. 微博原生抓取

不建议作为第一阶段主方案，原因：

- 接口稳定性和授权问题都比较麻烦
- 抓取成本高
- 反爬风险高
- 噪声显著高于官方互动问答
- 对当前项目落地性不如互动易 / 上证 e 互动 / 东方财富热度

### 2. 自写股吧帖子全文爬虫

这条路长期可以做，但不建议现在就把它放进主链路：

- 反爬和维护成本高
- 帖文清洗成本高
- 风险大于收益
- 当前项目先做“问答 + 热度 + 新闻辅助”就已经能明显超过 `stock_news_proxy`

## 建议落地顺序

### Phase 1：先落官方互动问答

目标：

- 让社媒分析师真正看到“投资者提问 + 公司回答”

建议实现：

1. 新增 A 股原生社媒同步服务，例如：
   - `sync_a_share_native_social(...)`
2. 按股票所属交易所分流：
   - 深市：优先 `irm_qa_sz` 或 `stock_irm_cninfo`
   - 沪市：优先 `irm_qa_sh` 或 `stock_sns_sseinfo`
3. 将问答文本标准化写入 `social_media_messages`
4. 在同步历史里把来源明确显示为：
   - `irm_qa_sz`
   - `irm_qa_sh`
   - `stock_irm_cninfo`
   - `stock_sns_sseinfo`

这是最重要、也最可落地的一步。

### Phase 2：补社区热度快照

目标：

- 让社媒分析师不只知道“说了什么”，还知道“热度有没有异常”

建议实现：

1. 同步东方财富热度：
   - 最新排名
   - 历史趋势
   - 盘中变动
   - 热门关键词
2. 同步雪球热度：
   - 关注
   - 讨论
   - 交易
3. 写入 `social_media_snapshots` 或等价结构化集合

### Phase 3：保留新闻辅助，但降级为 fallback

目标：

- 继续利用新闻做事件补充
- 不再把它当社媒本体

建议实现：

1. `stock_news_proxy` 从“主同步源”改为“补充源”
2. 分析 prompt 中分开展示：
   - 官方互动问答
   - 社区热度
   - 新闻背景
3. 前端与预同步调用里显式区分：
   - 原生社媒同步
   - 新闻回退生成社媒快照

## 对当前项目最合适的最终形态

如果按“价值 / 稳定性 / 成本 / 维护复杂度”综合排序，最推荐的 A 股社媒主链路是：

1. 官方互动问答
   - 深证互动易 / 上证 e 互动
2. 社区热度
   - 东方财富股吧热度
   - 雪球热度
3. 新闻辅助
   - Tushare / AKShare 新闻
4. 最后 fallback
   - `stock_news_proxy`

## 数据模型建议

### 方案 A：最小改动版

继续使用现有 `social_media_messages`，但扩展字段约定：

- `platform`
  - `cninfo_irm`
  - `sse_einteractive`
  - `eastmoney_guba`
  - `xueqiu`
- `message_type`
  - `investor_question`
  - `company_answer`
  - `heat_snapshot`
  - `keyword_snapshot`
- `data_source`
  - `irm_qa_sz`
  - `irm_qa_sh`
  - `stock_irm_cninfo`
  - `stock_sns_sseinfo`
  - `stock_hot_rank_em`
  - `stock_hot_keyword_em`
  - `stock_hot_follow_xq`
  - `stock_hot_tweet_xq`
  - `stock_hot_deal_xq`

优点：

- 复用现有查询和分析链路
- 上线快

缺点：

- 结构化热度数据会被 message 化

### 方案 B：更合理版

拆成两类集合：

- `social_media_messages`
  - 放问答文本、社区文本
- `social_media_snapshots`
  - 放热度排名、关键词、排行趋势等结构化指标

优点：

- 数据语义更清晰
- 后续扩展更好

缺点：

- 改动面稍大

对当前仓库，我建议：

- 第一步先上方案 A
- 第二步再演进到方案 B

## 分析链路建议

社媒分析师的输入不要再只看一段混合文本，而应该按来源分块：

1. 官方互动问答
2. 社区热度指标
3. 新闻背景

输出则更适合拆成三部分：

- 投资者关注点
- 公司回应与预期差
- 热度/情绪变化是否异常

## 明确结论

对于当前 TradingAgents-CN：

- `stock_news_proxy` 不应该继续充当 A 股社媒主源
- A 股原生社媒最值得接的是：
  - 深证互动易 / 上证 e 互动问答
  - 东方财富股吧热度
  - 雪球热度
- 新闻源应当降级成辅助和 fallback

## 参考来源

- AKShare 股票数据文档：
  - `https://akshare.akfamily.xyz/data/stock/stock.html`
- AKShare 接口：
  - `stock_irm_cninfo`
  - `stock_irm_ans_cninfo`
  - `stock_sns_sseinfo`
  - `stock_hot_rank_em`
  - `stock_hot_rank_detail_realtime_em`
  - `stock_hot_keyword_em`
  - `stock_hot_follow_xq`
  - `stock_hot_tweet_xq`
  - `stock_hot_deal_xq`
  - `stock_news_em`
- Tushare 文档：
  - `https://www.tushare.pro/document/2?doc_id=366`
  - `https://www.tushare.pro/document/2?doc_id=367`
  - `https://www.tushare.pro/document/2?doc_id=143`
  - `https://www.tushare.pro/document/2?doc_id=195`
- 互动易官方站点：
  - `https://irm.cninfo.com.cn/`
