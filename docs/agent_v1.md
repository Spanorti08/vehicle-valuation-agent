# 市场案例搜索 Tool-calling Agent

本项目只有市场案例搜索环节使用 Agent。资料读取与冲突处理、案例质量评分、调节指数计算、估值、RAG 报告、Excel/Word 输出及最终一致性检查均由确定性 Python 流程和人工确认控制。

## 状态

`MarketAgentState` 持久记录：

- 市场车型关键词、目标年份和目标里程；
- 初始城市、已搜索城市、已使用关键词和已搜索来源；
- 找到的车源、合格案例、淘汰案例及淘汰原因；
- 网页失败记录、当前轮次、每城市重试次数和剩余重试次数；
- 当前年份与里程容差、详情字段、同次读取截图和完整执行轨迹。

## 白名单工具

| 工具 | 确定性职责 |
|---|---|
| `search_market_cases` | 按用户确认的初始条件搜索 |
| `evaluate_case_quality` | 调用 Python 质量评分和硬门槛 |
| `expand_search_city` | 搜索下一批白名单城市 |
| `adjust_year_range` | 在上限内放宽年份范围 |
| `adjust_mileage_range` | 在上限内放宽里程范围 |
| `refine_search_keyword` | 记录并使用调整后的关键词 |
| `retry_failed_search` | 在每城市预算内重试失败请求 |
| `switch_data_source` | 只切换到已配置的白名单来源 |
| `request_human_approval` | 至少 3 个合格案例后暂停 |
| `stop_safely` | 达到轮次、步骤或资源边界时安全停止 |

Planner 只能选择 Policy 当前允许的工具，不能传入任意 URL、Shell 命令或 Python 函数，也不能采用案例或决定估值。Ollama 不可用、输出不合法或越权时，系统降级到确定性 Planner。

## 质量门槛与人工确认

Python 按车型、年份、里程、字段完整度、详情页与截图有效性、重复车源、价格异常和地区相关性评分，并保存风险和拒绝原因。达到至少 3 个合格案例后 Agent 暂停，由用户选择。价格、详情字段和截图来自同一次详情页读取；若人工复核后完整案例不足 3 个，状态退回搜索 Agent。

## 测试

```bash
python -m pytest -q -p no:cacheprovider
```

测试覆盖工具白名单、扩城、有限重试、硬质量评分、淘汰原因、策略越权拦截、人工确认、案例不足退回、最大步数、URL 去重与安全停止。
