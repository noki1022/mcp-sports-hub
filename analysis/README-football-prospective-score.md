# 足球竞彩：赛前冻结与赛后评分契约 v1

## 作用和部署边界
从已归档的真实 007 赛前快照、旧泊松概率和 Dixon–Coles 足球候选概率出发，必须匹配比赛结束后单独采集、带原始证据的 90 分钟终场结果，才能形成比较指标。这个工具不训练模型、不触碰 NBA/CBA、不开启足球定时推送，也不升级任何候选模型。

## 输入约定
1. 同轮原始 football_007_snapshot.json，具有真实赛前 captured_at_utc。
2. football_jc_forecast.json：基线报告的 source_sha256 必须匹配赛前快照。
3. football_dc_candidate.json：影子报告的 source_snapshot_sha256 必须匹配同一赛前快照。
4. 新的 football_007_finals.json：结构标识为 football-007-final-results-v1，记录 result_observed_at_utc、final_status=FT、score_scope=REGULATION_90_PLUS_STOPPAGE、比赛 ID、竞彩编号、开球时间、主客球队 ID、90分钟比分和原始页面来源 URL。
5. 独立归档的赛后 007 原始响应字节，每场文件名 final_<match-id>.txt，要求 SHA256 与对应 JSON 的 raw_sha256 一致。

请注意：原始字节的 SHA256 校验只能证明字节与声明一致，不能证明赛果 JSON 中的 FT 状态与比分确实来自原始内容。**本 PR 尚未实现 007 终场字段的独立解析与语义核对**，所以不能宣称真实赛后数据验证已完成。不得把未完赛比分当作赛果。

## 验收和指标
- 匹配比赛 ID、竞彩编号、开球北京时间、主客球队 ID；任何不一致拒绝入样。
- 两套预测必须在比赛开始前生成；赛后结果捕获时间必须晚于开球和模型报告。未达到完整比赛时间不得评分。
- 胜平负、官方整数让球胜平负、总进球 0~7+ 三玩法分别统计 log loss、Brier 和最高概率方向命中率。
- 只有两个模型都在同一场同玩法有概率，才计入模型间的公平对比；竞彩普通胜平负未开售不会删除这场，缺少官方整数让球数则不能计算 HHAD 命中。
- 总进球 1~2 个号码统计覆盖率，比较时必须保证双方选项同时有效。
- 不满 100 场明确标记小样本，不报告盈利保证，不自动晋级、不推送。

## 手工运行（须先接通并校验真实 FT 数据）
python3 -B -m unittest discover -s tests -p test_football_jc_prospective_score.py -v
python3 -B analysis/football_jc_prospective_score.py --snapshot football-output/football_007_snapshot.json --baseline football-output/football_jc_forecast.json --shadow football-shadow/football_dc_candidate.json --finals football-results/football_007_finals.json --evidence-dir football-results/raw --out football-results/football_model_comparison.json

**当前进展：评分契约及模拟测试已实现；007 FT 自动采集、独立语义校验和长期多日期样本评价仍然未完成。**