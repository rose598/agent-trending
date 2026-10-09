"""LLM 总结层：只对 Top N 项目做深度总结，分层控制成本。

兼容 OpenAI chat/completions 接口（DeepSeek / GLM / Kimi 等均可）。
无 key 或调用失败时自动降级为规则摘要，保证流程永远能出报告。
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

PROMPT = """你是资深的技术分析师，正在为一份《GitHub Agent 生态热门项目日报》撰写项目卡片。
请基于下面的仓库元数据和 README 片段，用中文输出一个 JSON 对象（不要输出任何其它文字），
字段如下：
- "positioning": 一句话定位（30字以内，说清它是什么、给谁用）
- "highlights": 2-3 个核心亮点，每条不超过 40 字，数组形式
- "architecture": 技术架构要点，1-2 句话（语言/框架/依赖的核心组件）
- "use_cases": 适用场景，1-2 句话
- "comparison": 与同类项目的差异点，1 句话（不确定就写"暂无足够信息"）
- "risk": 风险/注意点，1 句话（如成熟度、license、维护活跃度方面）

只输出 JSON，字段值全部为字符串或字符串数组。

仓库信息：
- 名称: {full_name}
- 描述: {description}
- 语言: {language} | Stars: {stars} | Forks: {forks} | 日增星: {stars_per_day}
- Topics: {topics}
- 创建于: {created_at} | 最近推送: {pushed_at}
- License: {license}

README 片段（可能被截断）：
---
{readme}
---"""


def llm_available(cfg: dict) -> bool:
    return bool(os.environ.get(cfg["llm"]["api_key_env"], "").strip())


def summarize_one(client: "LLMClient", repo: dict) -> dict:
    """单个项目总结，失败返回空 dict 由调用方降级。"""
    prompt = PROMPT.format(
        full_name=repo["full_name"],
        description=repo["description"],
        language=repo["language"],
        stars=repo["stars"],
        forks=repo["forks"],
        stars_per_day=repo["stars_per_day"],
        topics=", ".join(repo["topics"]),
        created_at=repo["created_at"][:10],
        pushed_at=repo["pushed_at"][:10],
        license=repo["license"],
        readme=repo.get("readme", "") or "（未能获取 README）",
    )
    return client.chat_json(prompt)


class LLMClient:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.api_key = os.environ.get(cfg["llm"]["api_key_env"], "").strip()
        self.base_url = cfg["llm"]["base_url"].rstrip("/")
        self.model = cfg["llm"]["model"]

    def chat_json(self, prompt: str) -> dict:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self.cfg["llm"]["max_tokens"],
                "temperature": self.cfg["llm"]["temperature"],
            },
            timeout=self.cfg["llm"]["timeout"],
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_loose(content)


def _parse_json_loose(content: str) -> dict:
    """从模型输出中尽力抠出 JSON（容忍 markdown 代码块包裹）。"""
    text = content.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def summarize_repos(repos: list[dict], cfg: dict) -> list[dict]:
    """并发总结 Top N；无 key 或逐项失败都降级为规则摘要。"""
    if not repos:
        return repos
    if not llm_available(cfg):
        for repo in repos:
            repo["analysis"] = None
        return repos

    client = LLMClient(cfg)
    todo = {repo["full_name"]: repo for repo in repos}
    for repo in repos:
        repo["analysis"] = None

    with ThreadPoolExecutor(max_workers=cfg["llm"]["max_concurrency"]) as pool:
        futures = {pool.submit(summarize_one, client, repo): repo["full_name"]
                   for repo in repos}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                result = fut.result()
            except (requests.RequestException, KeyError, json.JSONDecodeError):
                result = None
            if result:
                todo[name]["analysis"] = result
            time.sleep(0.2)
    return repos
