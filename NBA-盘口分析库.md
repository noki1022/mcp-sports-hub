# NBA 盘口分析库

手机阅读入口：

- [最新比赛报告](reports/games/2026/10/2026-10-29_CLE_WAS.md)

## 固定目录

```
data/
├── games/YYYY/MM/        比赛主记录
├── snapshots/YYYY/MM/    每次截图识别后的盘口快照
└── results/YYYY/MM/      比赛结束后的赛果

reports/
└── games/YYYY/MM/        手机友好版比赛报告

schemas/                  JSON 数据协议
scripts/                  计算与复盘脚本
```

## 命名规则

- 比赛：`YYYY-MM-DD_AWAY_HOME.json`
- 快照：同一比赛使用相同文件名；有多次抓取时追加时间戳
- 报告：与比赛文件同名，扩展名为 `.md`
- 年月目录按比赛日期归档，便于手机和程序按日期查找

## 当前样本

- [比赛记录](data/games/2026/10/2026-10-29_CLE_WAS.json)
- [盘口快照](data/snapshots/2026/10/2026-10-29_CLE_WAS.json)
- [手机报告](reports/games/2026/10/2026-10-29_CLE_WAS.md)
