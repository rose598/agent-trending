"""数据获取：GitHub Search API + Repo 元数据 + README。

不写传统爬虫：全部走官方 API，带 token 限流 5000 次/小时，
无 token 也有 60 次/小时 + 10 次搜索/分钟，足够日常增量使用。
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.github.com"


def make_session(token: str | None) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-trending-bot/0.1",
        }
    )
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def _get_with_retry(s: requests.Session, url: str, params: dict | None = None,
                    max_retries: int = 4) -> requests.Response:
    """带退避的 GET：覆盖 SSL/连接抖动 + 限流（Retry-After / X-RateLimit-Reset）。

    国内直连 api.github.com 时连接被瞬时重置很常见，重试通常能恢复。
    """
    resp = None
    for attempt in range(max_retries):
        try:
            resp = s.get(url, params=params, timeout=30)
        except requests.RequestException:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt * 2)  # 2s, 4s, 8s
                continue
            raise
        if resp.status_code in (403, 429):
            retry_after = resp.headers.get("Retry-After")
            reset = resp.headers.get("X-RateLimit-Reset")
            if retry_after:
                wait = int(retry_after)
            elif reset:
                wait = max(int(reset) - int(time.time()), 1)
            else:
                wait = 2 ** attempt * 2
            if attempt < max_retries - 1:
                time.sleep(min(wait, 90))
                continue
        break
    resp.raise_for_status()
    return resp


def search_repos(s: requests.Session, query: str, cfg: dict) -> list[dict]:
    """按 '关键词 + 最低星数 + 创建时间窗口' 搜索，按星数降序。"""
    since = (datetime.now(timezone.utc) - timedelta(days=cfg["created_since_days"])).strftime("%Y-%m-%d")
    q = f"{query} stars:>={cfg['min_stars']} created:>={since}"
    items: list[dict] = []
    authed = bool(s.headers.get("Authorization"))
    for page in range(1, cfg["max_pages"] + 1):
        resp = _get_with_retry(
            s,
            f"{API}/search/repositories",
            params={"q": q, "sort": "stars", "order": "desc",
                    "per_page": cfg["per_page"], "page": page},
        )
        batch = resp.json().get("items", [])
        items.extend(batch)
        if len(batch) < cfg["per_page"]:
            break
        time.sleep(1 if authed else 6)  # 搜索接口匿名 10 次/分钟
    return items


def normalize_repo(item: dict) -> dict:
    """把 API 返回压成小字典，并计算热度和活跃度代理指标。"""
    created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
    pushed = datetime.fromisoformat(item["pushed_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age_days = max((now - created).days, 1)
    recency_days = max((now - pushed).days, 0)
    stars = item["stargazers_count"]
    return {
        "full_name": item["full_name"],
        "url": item["html_url"],
        "description": (item.get("description") or "").strip()[:300],
        "language": item.get("language") or "未知",
        "stars": stars,
        "forks": item.get("forks_count", 0),
        "open_issues": item.get("open_issues_count", 0),
        "watchers": item.get("subscribers_count") or 0,
        "topics": (item.get("topics") or [])[:10],
        "created_at": item["created_at"],
        "pushed_at": item["pushed_at"],
        "age_days": age_days,
        "recency_days": recency_days,
        "stars_per_day": round(stars / age_days, 2),
        "license": (item.get("license") or {}).get("spdx_id") or "无",
    }


def fetch_readme(s: requests.Session, full_name: str, max_chars: int = 4000) -> str:
    """抓 README 原文（截断），失败返回空串不中断整个流程。"""
    try:
        resp = _get_with_retry(s, f"{API}/repos/{full_name}/readme")
        data = resp.json()
        text = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return text[:max_chars]
    except requests.RequestException:
        return ""
