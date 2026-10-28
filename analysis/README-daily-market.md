# Titan007 公开盘口日常分析：部署说明

## 现已实现
现有 `.github/workflows/titan007-daily-free.yml` 原定时采集无需修改时间（北京时间 22:00 和次日 05:30），在成功采集比分、赛程和 Crow* 盘口之后，额外输出 `daily_market_analysis.json`、`.csv`、`.html`：
- 007 全场让分、总分初盘与即时盘口的香港水位转十进制，归一化去水市场概率。
- 通过公开单场 Crow* 样本复核数据；如果两次采样期间价格变化，将相应盘口标记为 `QUOTE_DRIFT_OR_UNVERIFIED`，不会误写成完整一致。
- 尝试读取 NBA 官方公开伤停 PDF，并按比赛缩写 `MIA@ATL` 精确匹配；官方尚未发布、读取失败或名单未提交时标记 `NOT_LISTED` / `NOT_SUBMITTED`。
- 缺少 NBA/CBA 比赛时生成空报告，而不是伪造比赛。
- **不输出下注建议或声称真实 EV**。

## 尚未实现（不能冒充自动化完成）
当前独立 NBA 球队效率样本和近期赛果仍为 2026-10-28 的历史快照。StatsHawk 的连接数据只在互动研究时获取，当前 GitHub Actions 并没有获许可的持续访问接口。直到找到适当允许的官方或第三方数据通道、实现赛季数据持续刷新和赛前历史回测之前：
- 每日流水线只发布市场隐含概率、盘口变动和有来源的官方伤停。
- `real_ev_status = DISABLED_PENDING_OUT_OF_SAMPLE_CALIBRATION_AND_FRESH_STATS`，`recommendations = []`。
- 旧 `.github/workflows/titan007-ev-accept.yml` 是固定日期实验性验收，不应当被当作每日预测或在正式场次上投注。

## 验证清单
1. GitHub Actions 任务完成，并同时有盘口 JSON、CSV、HTML 文件。
2. 所有 `market_status=OK` 的去水概率两侧之和为 1；不满足的数据不能标记有效。
3. 差异盘口标记报价漂移，绝不被默认为已经交叉验证。
4. 官方伤停数据会随着发布时间更新，不等于赛前首发确认。
5. npm 锁文件修复通过 `npm ci`、`npm audit --audit-level=low`、类型检查与全量测试。

## 费用与许可
不需要付费 API、不需要登录球探或皇冠；遵守公开资源现有访问规则，避免循环高频访问。GitHub Actions 的免费分钟数等使用限制仍以账户和仓库设置为准。

## 代码审核
本分支只提交可审查的源代码与依赖锁文件。不自动合并到 `main`，不创建后台机器人或下注行为。
