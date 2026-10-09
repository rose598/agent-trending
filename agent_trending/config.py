"""配置加载：config.yaml + 代码内默认值。"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "queries": [],
    "min_stars": 50,
    "created_since_days": 90,
    "per_page": 30,
    "max_pages": 2,
    "top_n_table": 20,
    "top_n_readme": 30,
    "top_n_llm": 12,
    "readme_max_chars": 4000,
    "reports_dir": "reports",
    "data_dir": "data",
    "llm": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "LLM_API_KEY",
        "max_concurrency": 4,
        "timeout": 60,
        "max_tokens": 900,
        "temperature": 0.3,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | None = None) -> dict:
    """读取 yaml 配置并与默认值合并；环境变量优先级最高。"""
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    raw: dict = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    cfg = _deep_merge(DEFAULTS, raw)

    # 关键路径一律相对仓库根目录解析
    for key in ("reports_dir", "data_dir"):
        p = Path(cfg[key])
        cfg[key] = str(p if p.is_absolute() else ROOT / p)

    # 环境变量覆盖（方便本地不改文件切换 provider）
    if os_env_base := _env_nonempty("LLM_BASE_URL"):
        cfg["llm"]["base_url"] = os_env_base
    if os_env_model := _env_nonempty("LLM_MODEL"):
        cfg["llm"]["model"] = os_env_model
    return cfg


def _env_nonempty(name: str) -> str | None:
    import os

    value = os.environ.get(name, "").strip()
    return value or None
