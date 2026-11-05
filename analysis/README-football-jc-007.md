# 足球竞彩三玩法独立模型 | 007 证据合约 v1

## 范围与部署边界
从现有 NBA 项目复制的是**架构与纪律**，不是 NBA 的篮球进球参数或盘口语义。足球独立预测目录 `analysis/football_jc_*`，独立工作流 `.github/workflows/football-jc-research.yml`，当前仅手动执行，不加入 NBA/Cloudflare 定时器、不会调用 NBA PushPlus，也**不读取皇冠赔率**。绝不把研究结果冒充线上验证结果。

三种模型目标（标准全场 90 分钟 + 常规伤停补时；不含加时和点球）：
- **竞彩胜平负 HAD**：主胜 / 平 / 客胜（三分类）；
- **竞彩让球胜平负 HHAD**：官方主队整数让球 `signed_home_handicap`，比较 `主队进球 + 官方让球数` 与 `客队进球`，输出让胜/让平/让负；
- **竞彩总进球数 TTG**：0/1/2/3/4/5/6/7+ 八分类。**这不是大小球盘口**，不可用大小 2.5 球代替。

## 数据来源与核验
007 是竞彩足球、球队近五场、历史交锋及伤停的目标取数站点；站点展示区块/动态接口需要逐一用实盘页面核验、抓取并留存原始响应与抓取时间。**现已核实并接通 007 的足球赛程与竞彩胜平负/整数让球胜平负公开数据接口**：/xml/bf_jc.txt 与 /xml/odds_jc.txt。其余总进球数赔率、伤停、近期战绩和交锋尚未完成自动解析；这些字段保持缺失，不能据此宣称已自动抓齐 007 数据。特别区分网站公开赔率、官方竞彩开售赔率、模型概率三者。007 动态数据接口未验证前严禁按猜想写死 URL 或把欧赔当竞彩赔率。

输入文件 JSON 的最小结构：
```json
{
  "schema_version": "football-jc-007-v1",
  "beijing_date": "2026-11-06",
  "captured_at_utc": "2026-11-05T08:00:00+00:00",
  "games": [
    {
      "match_id": "unique_007_fixture_id",
      "jc_number": "周五001",
      "league": "联赛名称",
      "home_team": "主队",
      "away_team": "客队",
      "source_url": "https://zq.titan007.com/analysis/123cn.htm",
      "kickoff_beijing": "2026-11-06T20:00:00+08:00",
      "home_last5": [
        {"match_id":"H1","played_at":"2026-10-30T12:00:00Z","goals_for":2,"goals_against":1,"venue":"HOME"}
      ],
      "away_last5": [],
      "h2h": [
        {"match_id":"X1","played_at":"2026-09-01T12:00:00Z","home_goals":2,"away_goals":1}
      ],
      "injury_report_state": "UNVERIFIED",
      "injuries": [],
      "jc_markets": {
        "had": [2.3,3.2,3.1],
        "hhad": {"signed_home_handicap":-1,"odds":[4.4,3.6,1.55]},
        "ttg": [9,5,3.3,3.8,5.5,8.5,18,28]
      }
    }
  ]
}
```
示例仅示意数据结构和**虚构值**，不是任何实际比赛。真实输入必须附每场可追溯的 007 页面，以及真实抓取/报价时间；赔率不齐可写 `null`，**官方让球未核实则整个 `hhad` 字段留空**。至少各队 3 场有效、独立的赛前近况才计算概率；理想是完整近五场。交锋与伤停有独立时间边界，禁止赛后信息进入赛前预测。队伍、比赛编号及主客顺序必须核对；同一场不能重复入样。

### 特征融合的当前实现
- 以两队过去 5 场进攻得失球与对手防守失球的时间衰减加权均值估计主/客预期进球，加入**显式先验平滑**；
- 最多 5 场对战的进球表现只给小权重，不因为交锋稀缺或阵容不同而主导结果；
- 只对状态标为 `VERIFIED`、时间在抓取前、拥有身份、位置与预计出场时间份额的伤停人员做**有界的临时启发式**调整；出场状态未核实则拒绝数值调整；
- 用同一套独立泊松进球分布得到三个玩法概率，方向和概率必须相互一致；总进球数允许 1 或 2 个不同档位（第二高概率档位达到 10% 时双选），分别给出概率及合计覆盖概率；
- 提供竞彩赔率去水概率和模型方向的概率差，市场缺失不伪造。**此阶段模型完全未校准，数值属于研发占位的可审计概率，不适合作为真钱决策依据。**

后续正式模型应加入 xG/xGA、对手强度、主客场拆分、真实首发、阵型/赛程密度、休息天数、门将影响与伤停状态可靠性；以历史时间戳样本进行扩展泊松/Dixon–Coles 或双变量进球模型，再进行概率校准（Brier、log loss、可靠性曲线）及独立时间外回测。

## 工作步骤
1. 核查 007 足球比分/竞彩官方三玩法数据接口、原始字段主客和让球方向、历史数据及伤停数据是否可稳定获取；保存原始响应、页面网址、捕获时间、SHA256。
2. 建立足球赛程编号映射、字段级缺失状态、可重试采集和快照索引；并与篮球历史归档完全隔离。对于 007 未公开/未支持的信息必须标缺失。
3. 以赛前快照训练或回测模型，按独立赛事与日期划分训练/验证/盲测，避免重复赛程、同场不同时刻和未来结果泄漏。
4. 先影子运行并对比三个玩法逐场命中率、Brier、log loss 与数据覆盖率。通过样本质量与概率校准后再申请单独的生产调度和独立 PushPlus 推送渠道，保留可回滚开关。

## 手工离线跑法
```bash
python3 -m unittest discover -s tests -p test_football_jc.py -v
python3 analysis/football_jc_probability.py --input football/fixtures/007_verified_prematch.json --out /tmp/football-jc.json
python3 analysis/football_jc_report.py --forecast /tmp/football-jc.json --html /tmp/football-jc.html
```
GitHub Actions 的 `Football JC independent research (manual only)` 在无已提交快照时只运行测试，不会制造空赛程、赔率或推送。 

## 2026-11-05 已核验的真实 GitHub 运行
- 实盘 GitHub Actions [42012737603](https://github.com/noki1022/mcp-sports-hub/actions/runs/42012737603) 已通过：27 条 007 原始赛事，26 条尚未开赛；胜平负有效报价 25 场，让球胜平负有效报价 26 场，**总进球数官方 8 档报价 0 场**（不在该公开赔率文件内）。
- 原始两个 007 文本响应 gzip、SHA256、真实抓取完成时间、独立 JSON 赛前快照、模型报告与 iPhone HTML 已经由隔离工作流生成，当前保留在 GitHub Actions artifact 90 天；**不是永久离线备份**。
- 007 手机版 match analysis 页面已能 HTTP 获取，包含“对赛往绩”“近期战绩”“伤停”页面模块，但这些模块为空容器，由前端动态加载；未验证其数据接口前，模型不会臆造球队近五场和球员伤停。
- 新建独立足球 PushPlus 发送模块 scripts/football_jc_push.py，只读取 FOOTBALL_PUSHPLUS_TOKEN；**只有完整、可验证的 LIVE_007_VERIFIED 数据才允许实际发送**，当前默认预览、不推送、不修改篮球链路。
- 两套足球离线单元测试与 007 真实采集 Action 已通过；**目前没有启用足球生产定时器或自动 PushPlus**，以免不完整报告污染用户既有篮球通知。
