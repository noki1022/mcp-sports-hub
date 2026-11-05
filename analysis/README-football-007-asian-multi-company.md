# 足球 007 真实多机构亚洲让球盘口：数据源、采集与模型边界

## 已验证的 007 官方页面和数据接口
- 网站实际手机版比赛分析页 `https://m.titan007.com/analy/Analysis/3075305.htm` 的“亚”链接指向 `https://m.titan007.com/asian/3075305.htm`。
- 007 手机版亚洲盘网页加载 `script/letgoalOverunderData.js`。其 `LoadData()` 实际请求 `/HandicapDataInterface.ashx?scheid=<007比赛ID>&type=1&oddskind=0&isHalf=0`。
- 2026-11-05 已对真实 007 比赛 ID 3075305 的请求验收：HTTP 200、16 家机构 JSON，含 `scheduleId`、`matchTime`、`companies`；每家 `companyId`、`nameCn/nameEn`、`details`；每条 `oddsId`、`num`、`firstHomeOdds`、`firstDrawOdds`、`firstAwayOdds`、`homeOdds`、`drawOdds`、`awayOdds`、`modifyTime`。
- 老 `vip.titan007.com` 的历史及单机构网页在 GitHub Runner 上有连接中断现象，**不作为当前足球采集依赖**；以实际跑通的手机官方接口为主，不猜测其他公司页参数。

## 本 PR 的新增流程
在足球 007 原有竞彩赛程/三玩法报价抓取后，单独读取 007 全场亚洲让球指数。每场 007 比赛 ID 独立请求，按原始响应先压缩归档，再解析机构数据。失败按场标记，不会因为临时封盘/单页失败而终止竞彩主模型；所有原始字节记录 SHA256、URL 和实际抓取时间，并进入足球的既有 Actions / GitHub Releases 独立归档。

严格字段规则：
- `scheduleId` 与 007 赛程比赛 ID 一致；API `matchTime`（Unix UTC 秒）必须匹配该场北京时间开球；接口在比赛开球前抓取，报价修改时间不能晚于抓取结束时刻或开球。
- 保留网页使用的“主队让球数”方向，另建统一 `signed_home_asian_handicap`：**007 源数据 +0.5 主队让半球，在统一格式里写主 -0.5**，防止盘口正负反转。
- 水位原值是**港水净赔**：例如 0.83，转换十进制赔率是 1.83，不能误作赢球概率 83%。
- `details[0]` 才是该公司展示的主线路，后续 details 是另外可展开的报价线路；**同一机构的多线路不能当作多家公司的独立共识票**。
- 007 `first*` 视为来源提供的初盘数值，但其首次生成时间在这个 JSON 中未提供，不允许伪造初盘时间；当前报价使用 `modifyTime` 作为修改时间，并额外记录实际抓取时间。
- 当前抓取全场亚洲让球，不把 007 竞彩整数让球胜平负（三项）混为两方亚洲让球；半场盘口与走地盘口不混入。

## 独立研究模块的统计量
- 统计真实机构**主线路**的中位让球、众数让球、各让球线路的公司数量及分组中位港水，避免不同让球幅度的港水被直接平均。
- 对每家公司分别比较初盘与当前盘口方向，只有**同一让球线**才比较水位数值变化。盘口 -0.5 → -0.75 不被当成单纯主队水位下降。
- 对比此前 `football_jc_euro_asian.py` 从竞彩欧赔+泊松估算的**理论公平亚洲盘**：只在完全相同的让球线上比较十进制赔率差，且明确为未经概率校准的研究差异，**绝非实际投注 EV 或价值确定信号**。
- 大面积统一升盘、盘口离散程度与理论盘口偏差先作为研究特征保存。新特征不能在没有独立赛前→赛后盲测前自动改变足球胜平负、竞彩让胜/让平/让负和总进球双选方向。

## 架构隔离
足球采集、研究数据和单独影子分析只使用足球目录及 007 官方数据；不使用 NBA/CBA 模型参数，不复用篮球定时/Cloudflare Worker/PushPlus，不改篮球生产逻辑。官方竞彩三玩法始终为面向用户的最终预测目标，多家机构亚洲盘只是额外判断证据。

## 验收依据和剩余工作
- `python3 -B -m unittest discover -s tests -p test_football_007_asian_companies.py -v`
- `python3 -B -m unittest discover -s tests -p test_football_007_asian_real_compare.py -v`
- GitHub PR 全链路跑完后，必须记录有效比赛覆盖率、机构数、原始文件完整性和盘口一致性；仅局部接通不能称所有比赛均已覆盖。
- 下一阶段利用历史快照做事件级时间外研究，检验哪些机构集体换线或水位变化确实提高预测质量，按 Brier / Log loss 及命中率评价而不是盲从热门赔率。