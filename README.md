# agent-trending · GitHub Agent 生态热门项目日报

自动抓取 GitHub 上最近创建、快速涨星的 **Agent / Agent Infra** 相关项目，用 LLM 做总结分析，
每天生成一份中文 Markdown 日报。不需要云服务器。

## 架构

```
fetch (Search API 多 query) → dedupe (seen.json 增量) → enrich (README + 星速)
→ filter (规则评分排序) → llm_summarize (只总结 Top 12, 控制成本) → render (Markdown 日报)
```

特点：

- **不写传统爬虫**：全部走 GitHub 官方 API，带 PAT 限流 5000 次/小时
- **增量去重**：`data/seen.json` 记录已见仓库，每天 diff 出新上榜项目和星增量
- **分层预算**：规则先筛，只对 Top N 送 LLM，每天成本 < ¥1
- **自动降级**：没配 LLM key 也能跑，退化为规则摘要榜单
- **零服务器**：本机定时任务或 GitHub Actions 白嫖云端定时

## 快速开始（本机运行）

```powershell
pip install -r requirements.txt

# 配置 key：复制模板为 .env，填入你的 LLM key（配一次一直生效）
copy .env.example .env
# 编辑 .env 填入 LLM_API_KEY=sk-xxx（DeepSeek / GLM / Kimi 任一）
# 可选：GITHUB_TOKEN=ghp_xxx 可提高 GitHub API 限流到 5000 次/小时

# 试跑一次（不写增量状态、不调 LLM）
python run.py --dry-run --no-llm

# 正式跑（会自动读取 .env）
python run.py
```

报告输出在 `reports/daily-YYYY-MM-DD.md`，数据快照在 `data/`。

> 不想用 `.env` 也可以用系统环境变量（`$env:LLM_API_KEY = "sk-xxx"`），
> 系统环境变量优先级高于 `.env` 文件。

## 换 LLM 供应商

改 `config.yaml`（或用环境变量 `LLM_BASE_URL` / `LLM_MODEL` 覆盖）：

| 供应商 | base_url | model |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| Moonshot Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |

## GitHub Actions 定时（推荐，零服务器）

1. 在 GitHub 新建一个 **public 仓库**，把本目录推上去
2. 仓库 Settings → Secrets and variables → Actions：
   - Secret `LLM_API_KEY` = 你的 LLM key（不配则自动降级为规则榜单）
   - Variable `LLM_BASE_URL` / `LLM_MODEL` = 供应商地址和模型（用 DeepSeek 可不配）
3. `GITHUB_TOKEN` 是 Actions 自带的，不用配
4. Actions 会每天北京时间 09:30 自动运行，报告 commit 回仓库；也可在 Actions 页手动 Run workflow

## 本机定时（Windows）

```powershell
# 每天 09:30 跑一次（需保持开机；关机当天会跳过）
# 注意用 python.exe 的完整路径（where python 可查）
schtasks /create /tn "agent-trending" /tr "C:\miniconda3\python.exe D:\python\githubxuexi\run.py" /sc daily /st 09:30
```

## 调整抓取范围

编辑 `config.yaml`：

- 想看更成熟的项目：调高 `min_stars`（如 200），拉长 `created_since_days`（如 365）
- 想覆盖更多 infra：往 `queries` 里加 `topic:rag`、`topic:vector-database`、`topic:llm-ops` 等
- 想控制 LLM 成本：调低 `top_n_llm`

## 网络问题排查

国内直连 `api.github.com` 偶尔会被瞬时重置（`SSLEOFError` / `Connection reset`），
脚本已内置退避重试，一般能自愈。如果持续失败：

```powershell
# 有代理（Clash/v2ray 等）时，让脚本走代理（也可以写进 .env）：
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
python run.py
```

## 目录结构

```
├── run.py                  # 主入口
├── config.yaml             # 配置（query / 预算 / LLM）
├── .env.example            # key 模板，复制为 .env 使用
├── requirements.txt
├── agent_trending/
│   ├── fetcher.py          # Search API + README 抓取
│   ├── analyzer.py         # 去重 + 热度评分
│   ├── llm.py              # LLM 总结（失败自动降级）
│   └── render.py           # Markdown 日报渲染
├── .github/workflows/daily.yml   # GitHub Actions 定时
├── reports/                # 生成的日报
└── data/                   # seen.json 增量状态 + 每日快照
```
