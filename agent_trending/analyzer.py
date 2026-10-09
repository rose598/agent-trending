"""分析与排序：增量去重 + 热度评分。"""

from __future__ import annotations

import json
from pathlib import Path

from .fetcher import normalize_repo


def load_seen(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_seen(path: Path, seen: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")


def merge_query_results(raw_items: list[dict]) -> dict[str, dict]:
    """多个 query 的结果按仓库合并，并统计每个仓库命中的 query 数。"""
    merged: dict[str, dict] = {}
    for item in raw_items:
        repo = normalize_repo(item)
        entry = merged.setdefault(repo["full_name"], {"repo": repo, "query_hits": 0})
        entry["query_hits"] += 1
    return merged


def score(repo: dict, query_hits: int) -> float:
    """热度评分：星速为主，活跃度、绝对热度、社区关注、命中面为辅。"""
    heat = min(repo["stars_per_day"], 50)          # 星速封顶，防畸形值主导
    activity = 10 if repo["recency_days"] <= 3 else (5 if repo["recency_days"] <= 7 else 0)
    size = min(repo["stars"] / 200, 20)
    community = min(repo["watchers"] / 50, 10)
    return round(heat * 2 + size + activity + community + query_hits * 3, 1)


def dedupe_and_rank(merged: dict[str, dict], seen: dict, today: str) -> list[dict]:
    """对照 seen.json 计算是否新上榜、今日星增量，然后排序。"""
    ranked: list[dict] = []
    for full_name, entry in merged.items():
        repo = dict(entry["repo"])
        prev = seen.get(full_name)
        repo["is_new"] = prev is None
        repo["first_seen"] = prev["first_seen"] if prev else today
        repo["star_delta"] = repo["stars"] - prev["stars"] if prev else repo["stars"]
        repo["query_hits"] = entry["query_hits"]
        repo["score"] = score(repo, entry["query_hits"])
        ranked.append(repo)
    ranked.sort(key=lambda r: (-r["score"], -r["stars"]))
    return ranked


def update_seen(seen: dict, ranked: list[dict], today: str) -> dict:
    """把本次抓到的所有仓库写回 seen.json（含 first_seen/last_seen）。"""
    for repo in ranked:
        seen[repo["full_name"]] = {
            "stars": repo["stars"],
            "first_seen": repo["first_seen"],
            "last_seen": today,
        }
    return seen


def fallback_summary(repo: dict) -> str:
    """无 LLM 时的规则摘要：描述 + 语言 + 活跃度提示。"""
    parts = [repo["description"] or "（无描述）"]
    parts.append(f"主语言 {repo['language']}，近 {repo['recency_days']} 天内有推送")
    if repo["topics"]:
        parts.append("topics: " + " ".join(f"`{t}`" for t in repo["topics"][:5]))
    return "；".join(parts)
