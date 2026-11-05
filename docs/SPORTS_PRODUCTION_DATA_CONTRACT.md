# NBA + 足球：自动化完整性与防泄露生产契约（2026-11-06）

此文档描述本仓库的证据约束和验收标准，不声称已经跑通每个定时推送或设备端必达。

## 链路边界

1. **抓取**：篮球和足球各自采集真实赛程、盘口、水位、可验证伤停，保存「计划时段」「实际 UTC 时刻」「比赛 ID」「完整主客」「来源」「源内容 SHA256」。每次采集独立留档，第一次 12:00 不依赖历史快照。盘口无变化也保留一条真实采样，但不把它误当作独立比赛。
2. **赛前分析**：只读取模型决策时刻之前已可获得的材料；不能读取同场已结束比分、赛后复盘、后抓取盘口、未来伤停、同赛季未来训练特征。模型权重与校准需有独立、预先声明的时序验证，未获证据不晋级。竞彩/皇冠应保留来源、主客与 +/- 符号；皇冠 ID3 视作已约定机构。
3. **赛前最终答案**：以同一比赛 ID + 主客 + 开赛 UTC 为键；只有已归档的、赛前捕获并生成的预测可选。21:30 可保存历史基准，但正式逐场评分使用经验证的开赛前最后有效封存；所有快照归档不能因为新预测而被覆盖。
4. **推送**：推送须先通过数据完整性与时间闸门；单时段防重并保留 API 接收回执。GitHub cron 并不准点，迟到需记录计划/实际时间，不能伪称准时。API 接受不等于 iPhone 已收到。夜间静默时段不得意外 PushPlus。篮球五玩法、足球竞彩三玩法遵循独立质量状态。
5. **复盘**：仅复用封存预测，赛后比分从官方 / 已通过原始 FT 字节和 ID 匹配验证的独立渠道获取；按市场分别统计 HIT/MISS/PUSH/未开盘/未结算，严格去重，同场不能用 21:30 与赛前最终同时记分。足球未核准真实终场字段前不得宣称真实命中率。CBA 不属于已有 NBA 逐场评分实现，不得冒充。
6. **数据层**：原始字节不覆盖、校验 SHA256、分离研究结果和在线生产主分支。GitHub artifact 90 天只是临时缓存；NBA 独立 archive 分支和足球 Release 是可验证现有渠道，但不等于异地冗余。R2 尚未开启时显示 OFFSITE_BACKUP_NOT_ENABLED。仓库大文件增长与存储成本需长期监控。
7. **事故恢复**：先查原始 run ID、计划和实际时刻、archive 清单、消息 claim 与 accepted 回执。失败不可生成假快照补洞；应补抓并标记 LATE/RECONSTRUCTED，永远不可改写历史赛前预测。

## 可运行的只读审计

`.github/workflows/sports-integrity-and-leakage-gates.yml` 每六小时审计最近成熟时段的 GitHub 真实 schedule runs 和足球按 run ID 命名的 Release zip，同时核对 NBA 长期存档分支存在性。报告为 `sports-cross-chain-health.json`。该审计不调用赔率源、不触发推送、不改动模型权重，也不能仅靠成功徽章证明消息投递或原始内容字节正确。

默认匹配窗口为计划时点后 30 分钟，超时被视为需要排查的缺失，不把更晚别的时段运行误归于本时段。所有缺失以 CRITICAL 失败，让 Actions 看板可见。足球 Release 仍需另行按 SHA256 解压验证；NBA 存档须逐 run 对账，不能仅检查分支存在。

## 训练样本准入（研究，暂不接入在线模型）

`analysis/sports_point_in_time_admission.py` 的输入文件是两份 **独立 JSONL**：

- `features.jsonl`：每行只含 `sport,match_id,kickoff_utc,decision_utc,source_sha256,capture_run_id,model_version,features`。每个 feature 是 `{"value":..., "observed_at_utc": "...", "available_at_utc": "..."}`，所有时间为 UTC 可解析时区；观察时间不得晚于可用时间，可用时间不得晚于预测决策时刻，且必须早于开赛。
- `results.jsonl`：只含 `sport,match_id,result_verified_utc,result_source_sha256,verified_final,outcome`，且来自独立已核验的赛后结果。此文件严格禁止传入预测工作流；只有完成封存和准入校验后才可在隔离训练执行器中联合。
- `splits.json`：预先固定 `fit_before_utc,tune_before_utc,calibration_before_utc,holdout_before_utc,embargo_days`。四阶段按完整比赛 ID 分配，切分边界之间至少 1–30 天 embargo，不能用回测后表现调参再次选择同一 holdout。

示例命令：

```bash
python3 analysis/sports_point_in_time_admission.py \
  --features-jsonl features.jsonl --results-jsonl results.jsonl \
  --split-config splits.json --out training-admission-manifest.json
```

输出 **仅包含哈希、数据来源、时戳、分区、排除统计**，绝不把真实赛后结果写回预测样本或生产模型。这个版本是准入验证器，尚未打通全部现有原始资料的转换，也没有声称实际新增训练样本。

### 特别防范

- 时间戳缺失、来源哈希不全、比赛 ID 重复、主客身份不一致、同场赛后特征、最终赔率冒充初盘、未来伤停、训练/验证/校准/测试跨区间污染 => 拒绝准入。
- 同场每小时不同盘口属于相关测量，训练/验证按比赛分组，不能把一场比赛 20 个快照当成 20 场独立样本。
- 模型评估需至少报告 **N 独立比赛**、命中率和 Wilson CI、Brier / log loss、校准误差、按联赛/年份的分层结果、样本缺失率和基线比较；涨权重需未来外样本增量成立才允许晋级。
- 若决定采用滚动更新，滚动训练时刻之前应已完成标签验证；特征构建、标准化、补缺规则和特征选择只许在训练段拟合，在每个时点重新执行 as-of join；完整未触及 holdout 只验收一次。
- 保持密钥仅在 Actions secrets 内；所有上传到公开仓库和 Release 的 JSON、日志、HTML 都须先脱敏检测 token、API key、用户信息；审计只读且不需要 PushPlus token。

## 上线验收矩阵（不可跳过）

| 验收项 | 验证证据 | 当前含义 |
| --- | --- | --- |
| 单元测试和静态契约 | PR CI 成功 | 仅证明实现受测部分 |
| 真实篮球/足球抓取 | schedule run ID + 日期 + 原始快照哈希 | 必须逐小时验证 |
| 真实原始数据持久化 | Release / 长期分支 + 重新下载校验 | 无原始字节不可称完成 |
| PushPlus 送达 | 同时段 claim + API receipt + 手机实际收到 | API 回执不等于手机收到 |
| 赛前封存 | source SHA、生成 UTC、开赛 UTC 和 sealed final | 无法使用未来信息 |
| 真实复盘 | 官方比分 + 完整独立开赛前封存 + 一次评分 | 尚不能将测试当实盘 |
| 训练/回测 | 准入清单 + 时序隔离 + 独立样本 + 盲测指标 | 无真实样本不得宣传准确率提升 |

此 PR 不删除既有独立研究/历史入口，不直接修改篮球和足球正式抓取/推送，避免一次性替换大范围系统引入生产事故。
