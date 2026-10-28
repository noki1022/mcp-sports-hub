# NBA + CBA 盘口研究系统 V1

当前可运行能力：统一快照、香港盘转十进制、去水、SQLite 存储、同盘口快照比较、Markdown 报告。

盘口比较命令示例：

```python
from src.odds.compare import compare_snapshots
changes = compare_snapshots(old_snapshot, new_snapshot)
```

比较键包含公司、市场、赔率格式、阶段和盘口分值；不同盘口不会被错误合并。
