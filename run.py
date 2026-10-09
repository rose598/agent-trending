"""主入口：fetch → dedupe → enrich → filter → llm_summarize → render。

用法：
    python run.py                 # 按默认 config.yaml 跑一次
    python run.py --config x.yaml # 指定配置
    python run.py --dry-run       # 抓取+排序但不写 seen.json（试跑不污染增量状态）
    python run.py --no-llm        # 跳过 LLM 总结层
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_trending.analyzer import (
    dedupe_and_rank,
    load_seen,
    merge_query_results,
    save_seen,
    update_seen,
)
from agent_trending.config import ROOT, load_config
from agent_trending.fetcher import fetch_readme, make_session, search_repos
from agent_trending.llm import llm_available, summarize_repos
from agent_trending.render import write_report


def _load_dotenv() -> None:
    """加载本机 .env 文件（存在才生效）；未安装 python-dotenv 时静默跳过。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def main() -> int:
    # Windows 控制台默认 GBK，统一成 UTF-8 避免中文乱码
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    _load_dotenv()
    parser = argparse.ArgumentParser(description="GitHub Agent 生态热门项目日报")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--dry-run", action="store_true", help="试跑：不更新 seen.json")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 总结")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个项目（调试用）")
    args = parser.parse_args()

    cfg = load_config(args.config)
    token = os.environ.get("GITHUB_TOKEN", "").strip() or None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seen_path = Path(cfg["data_dir"]) / "seen.json"

    # 1) fetch：多 query 并行搜索
    s = make_session(token)
    raw_items: list[dict] = []
    for query in cfg["queries"]:
        try:
            batch = search_repos(s, query, cfg)
            print(f"[fetch] {query!r}: {len(batch)} 个仓库")
            raw_items.extend(batch)
        except Exception as exc:  # 单个 query 失败不拖垮全局
            print(f"[fetch] {query!r} 失败: {exc}", file=sys.stderr)

    if not raw_items:
        print("[error] 所有 query 都没有返回结果，未生成报告", file=sys.stderr)
        return 1

    # 2) dedupe + 3) enrich
    merged = merge_query_results(raw_items)
    seen = load_seen(seen_path)
    ranked = dedupe_and_rank(merged, seen, today)
    print(f"[rank] 合并后共 {len(ranked)} 个项目")

    limit = args.limit or cfg["top_n_readme"]
    for repo in ranked[:limit]:
        repo["readme"] = fetch_readme(s, repo["full_name"], cfg["readme_max_chars"])

    # 4) filter（评分排序已完成）+ 5) llm summarize
    top_for_llm = ranked[: cfg["top_n_llm"]]
    if args.no_llm or not llm_available(cfg):
        reason = "--no-llm" if args.no_llm else "未设置 LLM_API_KEY"
        print(f"[llm] 跳过总结（{reason}），使用规则摘要")
    else:
        print(f"[llm] 总结 Top {len(top_for_llm)} 个项目 "
              f"({cfg['llm']['model']} @ {cfg['llm']['base_url']})")
        summarize_repos(top_for_llm, cfg)
        done = sum(1 for r in top_for_llm if r.get("analysis"))
        print(f"[llm] 完成 {done}/{len(top_for_llm)}")

    # 6) render
    report_path = write_report(ranked, cfg, today)
    print(f"[render] 报告已生成: {report_path}")

    # 7) 更新增量状态（dry-run 时跳过）
    if not args.dry_run:
        save_seen(seen_path, update_seen(seen, ranked, today))
        print(f"[state] seen.json 已更新 ({len(seen)} 个仓库)")

    # 快照数据留档，方便后续画趋势图
    data_dir = Path(cfg["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot = [
        {k: v for k, v in repo.items() if k != "readme"} for repo in ranked
    ]
    (data_dir / f"snapshot-{today}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
