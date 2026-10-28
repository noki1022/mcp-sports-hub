# 数据源适配器

适配器只负责把外部响应转换为统一 `Game`，不负责盘口计算、模型或报告。

- NBA：StatsHawk / nba_api
- CBA：ApiZero / CBA official
- 认证信息由运行环境注入，不写入仓库。
- 外部响应缺失字段时写入 `UNKNOWN`，不推断。
