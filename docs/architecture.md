# 系统架构

## 总体架构

```mermaid
flowchart LR
    subgraph Input[资料层]
        EX[车辆 Excel]
        LI[行驶证图片]
        IN[现场核查]
    end

    subgraph Intake[资料处理]
        OCR[RapidOCR]
        CAL[字段级校准]
        CHECK[Pydantic + 跨来源核对]
    end

    subgraph Search[市场搜索]
        MAP[法定型号映射]
        LG[LangGraph]
        WEB[Playwright]
        SCORE[质量/相似度硬门槛]
        TOP3[自动 Top 3]
    end

    subgraph Valuation[估值]
        LLM[Qwen结构化建议]
        RULE[规则校验]
        FORMULA[Decimal公式]
    end

    subgraph Report[报告]
        RAG[BM25 / FAISS / RRF]
        GEN[有引用约束的章节生成]
        OUT[Excel / Word]
        VALIDATE[一致性检查]
    end

    EX --> CHECK
    LI --> OCR --> CAL --> CHECK
    IN --> CHECK
    CHECK --> MAP --> LG --> WEB --> SCORE --> TOP3
    TOP3 --> LLM --> RULE --> FORMULA
    FORMULA --> OUT
    FORMULA --> RAG --> GEN --> OUT --> VALIDATE
```

## 自动化与人工边界

```mermaid
stateDiagram-v2
    [*] --> 自动资料处理
    自动资料处理 --> 人工资料处理: 缺失/低置信且无可信匹配/实质冲突
    人工资料处理 --> 自动资料处理: 修正后重检
    自动资料处理 --> 自动市场搜索: 核对通过
    自动市场搜索 --> 自动选择Top3: 3个完整案例达标
    自动市场搜索 --> 人工补充案例: 搜索预算耗尽或证据不足
    人工补充案例 --> 自动市场搜索: checkpoint恢复
    自动选择Top3 --> 自动估值
    自动估值 --> 人工调整复核: 规则发现异常
    自动估值 --> 输出检查: 无异常
    人工调整复核 --> 输出检查
    输出检查 --> 最终专业复核
    最终专业复核 --> [*]
```

人工介入不是固定步骤，而是异常分支。正常输入会自动完成 OCR 校准、资料比对、市场搜索和 Top 3 采用。

## LangGraph 内部职责

LangGraph 只编排市场搜索。`plan_next_action` 根据状态请求 Planner 提议动作，Policy 用 `allowed_tools` 和预算再次约束，工具节点执行确定性代码并更新 `MarketAgentState`。

```text
checkpoint state
      ↓
plan_next_action → Policy → one whitelisted tool
      ↑                         ↓
      └──────── updated state ──┘
                                ↓
              candidates_ready / interrupt / failed
```

关键状态：

| 状态 | 含义 | 下一步 |
|---|---|---|
| `running` | 仍有安全动作和预算 | 继续图循环 |
| `candidates_ready` | 至少 3 个候选通过硬门槛 | 自动完整性检查与 Top 3 |
| `awaiting_human_input` | 资源耗尽仍不足 | interrupt，等待补充 |
| `completed` | 案例已采用 | 进入调整与估值 |
| `failed` | 达到最大步骤或执行失败 | 安全停止并保留轨迹 |

## 确定性安全边界

以下行为不能由 LLM 绕过：

- 只能调用注册过的市场工具；
- 只搜索配置中的城市和数据源；
- 年份、里程、轮次和重试都有上限；
- 质量分和相似度不得低于 60；
- 案例必须有详情与同次读取截图；
- 金额与修正系数由 Python `Decimal` 计算；
- RAG 引用必须来自本轮召回的 `chunk_id`；
- 输出在下载前执行结构与残留检查。

## 可观测与恢复

- 每次工具调用记录动作、Planner 理由、Policy 说明、结果、候选数量和耗时；
- OCR 保存原文、字段置信度和校准规则；
- 被拒绝市场案例保存具体原因；
- SQLite 保存 LangGraph checkpoint；
- Excel 保留案例来源与截图，Word 保留检索证据形成的章节；
- 离线评测覆盖正常路径、异常路径、暂停和恢复。
