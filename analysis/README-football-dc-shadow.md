# 007 竞彩足球独立 Dixon–Coles 影子模型 v1

## 开源研究选择（GitHub 已核实的许可证）
- [martineastwood/penaltyblog](https://github.com/martineastwood/penaltyblog) ：MIT（库内 LICENCE）。参考其足球泊松/低比分模型研究体系；整个包依赖 Cython、NumPy、SciPy 等，**不会直接安装到已有足球主采集任务**。
- [callumfm/dixon-coles](https://github.com/callumfm/dixon-coles)：MIT（LICENSE）。参考球队实力、时间衰减与 Dixon–Coles 核心数学定义，当前项目依赖 numpy/numba/scipy，不直接导入。
- [JetQiao/football-prediction-skill](https://github.com/JetQiao/football-prediction-skill)：MIT（LICENSE）。参考时间戳纪律、竞彩缺盘不漏场、champion/challenger 互相隔离、校准与 walk-forward 回测框架；不引入其自动采集、付费数据源、调度或通知。
- Dixon–Coles tau 公式是公开的标准数学方法；此仓库由我们自行编写独立纯 Python 实现，未复制第三方源代码。不将上述项目声称的回测表现当作我们模型的命中率。

## 实际集成
足球专属分析模块：analysis/football_jc_dc_shadow.py。

- **输入**：007 足球实盘赛前 snapshot、同一轮采集的 analysis_{007-match-id}.html.gz、原始页面 SHA256。源码仅解析 JSON，不执行网页 JavaScript，不从其他网站补全数据。
- **学习**：由 007 赛前已完赛比赛列表提取主客球队真实 ID、赛程 ID、开球时间、全场比分。去重、剔除比分异常/未完赛/未来比赛及 420 天外数据；180 天半衰期，攻击/防守正则化泊松拟合。严禁把待预测比赛的竞彩赔率当成训练特征。
- **概率**：在进球 λ 上计算标准 Dixon–Coles 0:0、0:1、1:0、1:1 低比分校正，统一比分网格汇总 HAD、官方整数让球 HHAD、总进球 0–7+（最多双选）。
- **rho**：从按比赛发生时间划分的历史验证集选择，若训练/验证样本或交叉球队覆盖不足，自动退回 rho=0；有验证集也必须先胜过 rho=0 足够幅度才启用。**这个历史验证不是独立真实赛前回测**，因为结果数据来自同一份当前采集的静态历史视图，尚无完整逐时点历史快照用于前瞻模型评估。
- **伤停**：已采到 007 公共伤停事实，但缺乏明确球员可出场确认、预计分钟份额与准确观测时间，因此本版不调整进球 λ。不把 007 的“伤停名单中有名字”自动解释为“必定缺阵”。
- **输出**：独立 football-dc-shadow-model artifact，不影响 football_jc_forecast.json、足球现有 HTML 或任何篮球报告。仅当已有主足球采集任务成功后运行，故障不会阻断原始归档；不用 PushPlus，不开新定时器。
- **训练门槛**：完整历史比赛至少 80 场；球队至少 4 场历史；ρ 时间留出需要至少 40 场已覆盖验证比赛。球队历史不足或源证据失效，则该场 shadow 标注 UNAVAILABLE。
- **未实现**：独立滚动 as-of 回测、跨赛季留出集、可靠性曲线与概率校准、正式伤停概率修正。模型概率**尚无准确率或盈利率背书**，不可视为已晋级生产模型。

## 下一步验收
1. 连续保存多轮 007 赛前原始快照与赛后终场比分，并校验每场预测哈希先于比分。
2. 多轮 walk-forward：对比旧泊松与 Dixon–Coles 的 HAD Log loss、Brier、HHAD RPS、TTG log loss；同时检验每档概率校准及样本独立性。
3. 使用匹配时刻的**竞彩报价**（不是博彩网站收盘价格）作单独对照，仅在概率通过样本外验证后比较概率优势。
4. 影子模型要先连续通过稳定性、覆盖率和概率误差验收，再决定是否替换现有足球基线。绝不直接变更篮球/NBA 相关链路。

运行：
\`\`\`bash
python3 -B -m unittest discover -s tests -p test_football_jc_dc_shadow.py -v
python3 -B analysis/football_jc_dc_shadow.py \
  --snapshot football-output/football_007_snapshot.json \
  --analysis-dir football-output/raw \
  --out football-shadow/football_dc_candidate.json
\`\`\`
