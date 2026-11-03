# NBA/CBA 原始盘口数据：可检索、可验证、可恢复长期备份

## 数据分层

- **生产主分支** `main`：模型与推送逻辑，保持原样；此系统不清理 `reports/`，不覆盖源数据。
- **原始证据分支** `archive/nba-market-captures`：既有每次原始抓取文件的 gzip + SHA-256 manifest，独立于 Actions 的短期 Artifacts。所有覆盖、重写、删除均禁止。
- **检索索引分支** `audit/nba-raw-search-catalog`：每月 `catalog/YYYY-MM.jsonl`，从原始文件完整性校验后重建，包含北京时间比赛日期、任务 run ID/attempt、源文件、比赛 ID、球队、赔率抓取时间和 SHA-256。索引不是原始数据，也不是异地备份。
- **独立对象副本（须配置）**：Cloudflare R2 私有 bucket，键名 `nba-market-captures/v1/reports/market-captures/...`。每个原始 gzip 和 manifest 均独立存放；`If-None-Match: *` 防止意外覆盖，上传/已存在对象均用 `GetObject` 下载校验 SHA-256。R2 仅作为镜像，不替代原始 Git 仓库。

## 归档检索与本地恢复

电脑或 GitHub Actions Linux runner 克隆本仓库并取原始分支：

```bash
git fetch origin archive/nba-market-captures
git worktree add --detach /tmp/nba-evidence origin/archive/nba-market-captures

# 完整验证所有 manifest、gzip 和原文 SHA-256
python3 ops/nba_raw_vault.py --archive-root /tmp/nba-evidence audit

# 按日期、原始文件名、比赛 ID 查询
python3 ops/nba_raw_vault.py --archive-root /tmp/nba-evidence search --day 2026-11-03 --source jingcai --verify
python3 ops/nba_raw_vault.py --archive-root /tmp/nba-evidence search --game-id 728298 --verify

# 从原始证据重新建立月份索引
python3 ops/nba_raw_catalog.py build --archive-root /tmp/nba-evidence --catalog /tmp/nba-catalog

# 速度快：只从索引查询
python3 ops/nba_raw_catalog.py query --catalog /tmp/nba-catalog --day 2026-11-03 --game-id 728298

# 按搜索结果给出的 EXACT manifest + source 恢复成原文，禁止覆盖
python3 ops/nba_raw_vault.py --archive-root /tmp/nba-evidence restore \
  --manifest reports/market-captures/2026-11-03/main-existing-historical-backfill/manifest.json \
  --source reports/daily/2026-11-03/2130/nba_jingcai_three_market.json \
  --output /tmp/recovered_jingcai.json
```

注意：用户使用 iPhone 时不必本地安装工具。合并后的 Actions 可在云端运行并在 `audit/nba-raw-search-catalog` 浏览/检索索引；如果需指定一场比赛的完整原始恢复，可以手动触发工作流，或之后添加只读查询工作流。

## 配置私有 Cloudflare R2 双份备份（必要）

在 Cloudflare 面板中**创建私有 R2 bucket**，为它创建限定存储桶的 S3 API 读写密钥（应用程序使用的 Key，仅允许所需 bucket；严禁公有读权限）。在 GitHub 仓库 **Settings → Secrets and variables → Actions** 配置：

| GitHub 位置 | 名称 | 说明 |
| --- | --- | --- |
| Secrets | `R2_ACCOUNT_ID` | Cloudflare Account ID |
| Secrets | `R2_ACCESS_KEY_ID` | R2 API Access Key ID |
| Secrets | `R2_SECRET_ACCESS_KEY` | R2 API Secret Access Key |
| Variables | `R2_BACKUP_BUCKET` | 私有 R2 bucket 名称 |

仓库保存的只会是密钥名，不会保存密钥值。配置完毕后在 GitHub Actions 手动执行 **NBA immutable raw vault index audit and optional independent R2 mirror**，首次将所有已归档数据复制到 R2，并用 `GetObject` 读回确认。之后计划北京时间每日 13:10 检查；如果独立备份密钥未配置，工作流会明确失败而不会假称备份完成。工作流失败将尝试调用既有 PushPlus 发出异常告警。

初次验证后，还应在 Cloudflare 配置合适的 **Bucket Lock / 保留规则、独立权限账户、账单预警**；防止有删除权限的凭据删掉整桶。仅在你已经通过实际恢复测试、且 R2 对象得到可靠保留保护后，才能把它称为可靠异地副本。

## 可靠性边界

- **绝不自动清理、压缩重写或迁移出原始 Git 数据**。索引可以重建，原始原文必须逐字节保存。
- 按赛事 ID 或球队名称检索，取决于抓取源 JSON 中是否带有可识别字段；没有这些字段则仍可按日期/路径检索。
- **录入归档的文件不代表每次抓取都完整**：manifest 标识 `PARTIAL_OR_MISSING_SOURCES` 时按缺失处理。归档流程在主 Action 没有产生可下载 Artifact 时可能漏存，需扩充采集与归档交叉核对。
- 对象存储不是源 Git 历史的 `git clone --mirror`；本方案保留每次采集的完整原始文件，不负责备份 GitHub 仓库里所有源代码和历史提交。若要求连源代码与 Git 历史完整灾备，需要独立的 Git 镜像/Bundle。
- 长期连续监控所有数据与容量；GitHub API tree 数据量不等于仓库历史总量。保留与费用须定期核查。

## 上线测试

```bash
python3 ops/nba_raw_vault.py selftest
python3 ops/nba_r2_offsite_mirror.py --selftest
```

PR CI 从真实 `archive/nba-market-captures` 分支读取全部证据，校验每份原始文件并生成索引，不接触生产分支、R2 密钥或 PushPlus 推送。
