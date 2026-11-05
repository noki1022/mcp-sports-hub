# 007 足球竞彩：赛前影子模型逐场赛后验收 v1

本模块只评估已经保存的**赛前**正式足球基线报告与独立 Dixon–Coles 影子报告。不与篮球调度、现有足球抓取、PushPlus 推送交叉，不会在赛后生成「赛前预测」。

## 接受的真实数据
同一次足球抓取归档的三个文件：
- \`football_007_snapshot.json\`：007 赛程、竞彩胜平负 / 官方整数让球胜平负 / 总进球八档的赛前快照，含比赛 ID、主客球队 ID、竞彩编号、开赛时间和抓取时间。
- \`football_jc_forecast.json\`：泊松主模型报告（必须与赛前快照 SHA256 匹配）。
- \`football_dc_candidate.json\`：足球影子报告（必须与**同一**赛前快照 SHA256 匹配）。

第四个文件 \`football_007_final_results.json\` 只能由**实际赛后已完赛**的 007 来源数据生成，遵循：

\`\`\`json
{
  "schema_version": "football-007-final-results-v1",
  "results": [
    {
      "match_id": "3075305",
      "jc_number": "周四002",
      "kickoff_beijing": "2026-11-06T01:45:00+08:00",
      "home_team_id_007": 35,
      "away_team_id_007": 1078,
      "final_status": "FT",
      "home_goals": 2,
      "away_goals": 1,
      "result_observed_at_utc": "2026-11-06T01:00:00+00:00",
      "source_url": "https://live.titan007.com/detail/3075305.htm",
      "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
\`\`\`

上述是**虚构数据结构演示**，不是比分、实时赛果或已验证 007 地址的证据。后续自动结果采集器必须从真实可验证的 007 终场状态和原始响应生成该文件，并归档原文 SHA256；此模块不会假定网站一旦经过 90 分钟就已经完赛。

## 强制校验
- 赛前快照散列与两个模型的输入散列必须相同，且每场预测真正生成于开球以前。
- 007 比赛 ID、竞彩编号、北京时间、主客球队数字 ID 全部精确匹配；禁止按球队中文译名模糊关联。
- 赛果只接受 007 原始来源、有效 SHA256、确定的 \`FT\` 终场标记，赛果抓取时间至少晚于开球 90 分钟。
- 除了 JSON 中的来源 SHA256，还必须提供 \`--raw-results-dir\` 下以真实 007 比赛 ID 命名的 gzip 原始响应（例如 \`3075305.html.gz\`）。逐场解压并与 JSON 的 SHA256 比对；**仅提供自称正确的散列不够，缺原文则拒绝评分**。这证明归档字节和声明一致，但终场状态与比分字段真实性仍依赖未来独立核验的 007 赛果解析器。
- 非竞彩在售玩法不计算该市场的「命中率」。例如 007 本菲卡比赛普通胜平负缺失，则只评估让球胜平负和总进球，不将胜平负缺价视为采集失败，也不记成错盘。
- 所有正式概率分布必须验证概率和为 1；禁止用赛果重造模型数据或篡改已有概率。
- 单场总进球最多两项，正确计算「两项任一命中」概率与命中率。全场结果只统计常规90分钟和补时，不含加时及点球。

## 指标
每个玩法逐场记录：
- \`top1_hit\`：单项最高预测概率方向命中
- \`brier\`、\`log_loss\`：概率质量
- \`rps\`：按分类次序的累计概率误差
- 总进球 \`dual_hit\`：1–2 个进球数字任选一项命中
- 仅在同一场同一玩法双模型均有有效赛前概率时，计算 **paired baseline minus shadow** 差值

所有聚合指标都带有样本量。小样本的差值不能证明长期增益，不做 ROI 宣称，不自动晋级影子。

## 离线运行
\`\`\`bash
python3 -B -m unittest discover -s tests -p test_football_jc_prospective_score.py -v
python3 analysis/football_jc_prospective_score.py \
  --snapshot football_007_snapshot.json \
  --baseline football_jc_forecast.json \
  --shadow football_dc_candidate.json \
  --results football_007_final_results.json \
  --raw-results-dir verified-007-final-html/ \
  --out football_jc_prospective_audit.json
\`\`\`

GitHub \`Football JC prospective scoring (research only)\` 工作流目前只运行离线模拟测试；**尚未接入赛后自动抓取**，没有真实的多场赛前—赛后匹配指标时不会声称已经提高预测准确率。

下一阶段必须先核实 007 足球完赛比分源的字段、终场标记、抓取时间戳与身份关联，再通过单独的足球任务更新比赛结果、自动每日评分与时间外校准。原始快照长期保存在足球独立 GitHub Releases / Artifacts，避免仓库膨胀；R2 仍属于未来独立备份，不能称为已经生效。
