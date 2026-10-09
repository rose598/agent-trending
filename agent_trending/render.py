"""报告渲染：生成中文 Markdown 日报。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .analyzer import fallback_summary


def _stars(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def render_report(ranked: list[dict], cfg: dict, today: str) -> str:
    lines: list[str] = []
    lines.append(f"# GitHub Agent 生态热门项目日报 · {today}")
    lines.append("")
    lines.append(
        f"> 抓取窗口：最近 {cfg['created_since_days']} 天创建、Stars ≥ {cfg['min_stars']} 的 "
        f"agent / agent infra 相关仓库；共命中 **{len(ranked)}** 个，按热度评分排序。"
    )
    lines.append("")

    # ── Top 总览表 ──
    lines.append("## 📊 今日 Top 总览")
    lines.append("")
    lines.append("| # | 项目 | 语言 | Stars | 日增星 | 评分 | 标签 |")
    lines.append("|---|------|------|-------|--------|------|------|")
    for i, repo in enumerate(ranked[: cfg["top_n_table"]], 1):
        badge = "🆕 " if repo["is_new"] else ""
        topics = " ".join(f"`{t}`" for t in repo["topics"][:3])
        # 新上榜项目当日 delta = 总星数，改用日均增速更直观
        delta = repo["stars_per_day"] if repo["is_new"] else repo["star_delta"]
        lines.append(
            f"| {i} | {badge}[{repo['full_name']}]({repo['url']}) | {repo['language']} "
            f"| {_stars(repo['stars'])} | +{delta} "
            f"| {repo['score']} | {topics} |"
        )
    lines.append("")

    # ── 逐项目深度分析 ──
    lines.append("## 🔍 深度分析")
    lines.append("")
    for i, repo in enumerate(ranked[: cfg["top_n_readme"]], 1):
        lines.append(f"### {i}. [{repo['full_name']}]({repo['url']})")
        meta = (
            f"⭐ {_stars(repo['stars'])} · 日增星 {repo['stars_per_day']} · "
            f"🍴 {repo['forks']} · {repo['language']} · 创建 {repo['created_at'][:10]} · "
            f"License {repo['license']}"
        )
        if repo["is_new"]:
            meta += " · 🆕 新上榜"
        lines.append("")
        lines.append(f"> {meta}")
        lines.append("")
        analysis = repo.get("analysis")
        if analysis:
            lines.append(f"**定位**：{analysis.get('positioning', '—')}")
            lines.append("")
            highlights = analysis.get("highlights") or []
            if isinstance(highlights, str):
                highlights = [highlights]
            for h in highlights[:3]:
                lines.append(f"- 💡 {h}")
            lines.append("")
            lines.append(f"**架构**：{analysis.get('architecture', '—')}")
            lines.append("")
            lines.append(f"**适用场景**：{analysis.get('use_cases', '—')}")
            lines.append("")
            lines.append(f"**对比**：{analysis.get('comparison', '—')}")
            lines.append("")
            lines.append(f"**风险**：{analysis.get('risk', '—')}")
        else:
            lines.append(fallback_summary(repo))
        lines.append("")

    # ── 趋势观察 ──
    lines.append("## 📈 趋势观察")
    lines.append("")
    new_count = sum(1 for r in ranked if r["is_new"])
    langs: dict[str, int] = {}
    for repo in ranked[: cfg["top_n_table"]]:
        langs[repo["language"]] = langs.get(repo["language"], 0) + 1
    top_langs = sorted(langs.items(), key=lambda kv: -kv[1])[:3]
    lang_text = "、".join(f"{l}({n})" for l, n in top_langs) if top_langs else "—"
    hottest = ranked[0]["full_name"] if ranked else "—"
    fastest = max(ranked, key=lambda r: r["stars_per_day"]) if ranked else None
    lines.append(f"- 本期共 {len(ranked)} 个项目在榜，其中 **{new_count} 个新上榜**")
    lines.append(f"- 今日最热：**{hottest}**")
    if fastest:
        lines.append(
            f"- 增速最快：**{fastest['full_name']}**（日均 +{fastest['stars_per_day']} 星）"
        )
    lines.append(f"- Top 20 主语言分布：{lang_text}")
    lines.append("")
    lines.append("---")
    lines.append(
        f"*由 agent-trending pipeline 自动生成于 "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*"
    )
    return "\n".join(lines)


def write_report(ranked: list[dict], cfg: dict, today: str) -> Path:
    out_dir = Path(cfg["reports_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"daily-{today}.md"
    path.write_text(render_report(ranked, cfg, today), encoding="utf-8")
    return path
