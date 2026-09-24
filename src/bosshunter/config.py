"""Configuration loader for BossHunter."""

import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml


# BOSS直聘城市编码映射
CITY_CODES: dict[str, str] = {
    "北京": "101010100",
    "上海": "101020100",
    "深圳": "101280600",
    "广州": "101280100",
    "杭州": "101210100",
    "成都": "101270100",
    "武汉": "101200100",
    "南京": "101190100",
    "西安": "101110100",
    "苏州": "101190400",
    "天津": "101030100",
    "重庆": "101040100",
    "郑州": "101180100",
    "长沙": "101250100",
    "东莞": "101281600",
    "佛山": "101280800",
    "合肥": "101220100",
    "厦门": "101230200",
    "青岛": "101120200",
    "大连": "101070200",
}


SUPPORTED_AI_PROVIDERS = {"anthropic", "openai_compatible"}
SUPPORTED_AI_SERVICES = {"anthropic", "deepseek", "doubao", "custom"}
AI_SERVICE_PRESETS: dict[str, dict[str, str]] = {
    "anthropic": {
        "provider": "anthropic",
        "label": "Claude / Anthropic",
        "base_url": "",
        "key_env": "ANTHROPIC_API_KEY",
    },
    "deepseek": {
        "provider": "openai_compatible",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "doubao": {
        "provider": "openai_compatible",
        "label": "豆包 / 火山方舟",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_env": "ARK_API_KEY",
    },
    "custom": {
        "provider": "openai_compatible",
        "label": "其他 OpenAI 兼容接口",
        "base_url": "",
        "key_env": "OPENAI_API_KEY",
    },
}

AI_CREDENTIAL_FIELDS = ("api_key", "auth_token")


DEFAULTS: dict[str, Any] = {
    "profile": {
        "resume_path": "./resume.md",
        "resume_output_dir": "./data/resumes",
        "target_cities": ["北京"],
        "education": "",
        "recruitment_type": "",
        "greeting_preference": "",
        "salary_min": 0,
        "salary_max": 0,
        "salary_ceil_ratio": 1.5,
        "filter_unparsed_salary": False,
        "allow_internship": False,
        "deal_breakers": [],
        "jd_deal_breakers": [],
        "blocked_companies": [],
    },
    "search": {
        "keywords": [],
        "cities": [],  # Empty = fallback to profile.target_cities
        "city_codes": {},
        "max_pages": 3,
        "sort": "default",
        "filters": {},
    },
    "collection": {
        "default_order": ["boss"],
        "auto_score_default": False,
        "daily_search_page_limit": 60,
        "daily_detail_page_limit": 150,
        "max_consecutive_page_failures": 3,
        "risk_pause_min_minutes": 5,
        "risk_pause_max_minutes": 10,
        "collection_delay_multiplier": 1.5,
        "delivery_cooldown_min_minutes": 5,
        "delivery_cooldown_max_minutes": 15,
    },
    "platforms": {
        "boss": {
            "enabled": True,
            "search": {
                "keywords": [],
                "cities": [],
                "city_codes": {},
                "max_pages": 3,
                "sort": "default",
                "filters": {},
            },
        },
        "zhilian": {
            "enabled": False,
            "search": {
                "keywords": [],
                "cities": [],
                "city_codes": {},
                "max_pages": 3,
                "sort": "default",
            },
        },
        "51job": {
            "enabled": False,
            "search": {
                "keywords": [],
                "cities": ["上海"],
                "city_codes": {"上海": "020000"},
                "max_pages": 1,
                "sort": "default",
            },
        },
        "liepin": {
            "enabled": False,
            "search": {
                "keywords": [],
                "cities": [],
                "city_codes": {},
                "max_pages": 1,
                "sort": "default",
            },
        },
    },
    "scoring": {
        "threshold": 71,
        "max_candidates": 20,
    },
    "throttle": {
        "daily_limit": 30,
        "interval_min": 60,
        "interval_max": 180,
        "browse_before_greet": True,
        "browse_duration_min": 15,
        "browse_duration_max": 30,
        "send_window_enabled": False,
        "send_windows": [],
        "day_off_probability": 0.05,
    },
    "ai": {
        "provider": "anthropic",
        "service": "anthropic",
        "model": "claude-sonnet-4-6",
        "thinking": "auto",
        "thinking_budget": 2048,
        "timeout_seconds": 180,
        "input_cost_per_million": 0.0,
        "output_cost_per_million": 0.0,
        "scoring_max_tokens": 8192,
        "scoring_max_attempts": 2,
        "scoring_concurrency": 1,
        "scoring_second_review": False,
        "greeting_max_tokens": 8192,
        "greeting_review_max_tokens": 4096,
        "greeting_max_attempts": 2,
        "greeting_review_threshold": 7.0,
        "greeting_max_iterations": 2,
        "greeting_style_suggestions": True,
        "greeting_auto_apply_style": False,
    },
    "monitor": {
        "interval": 30,  # 分钟
        "initial_cooldown_minutes": 10,
        "chat_url": "https://www.zhipin.com/web/geek/chat",
        "max_conversations_per_cycle": 5,
        "max_consecutive_page_failures": 3,
        "max_resume_sends_per_cycle": 5,
        "auto_reply_hr_questions": False,
        # Hard safety gate: platform messages require an explicit human approval.
        "require_human_confirmation": True,
    },
    "notifications": {
        "email": {
            "enabled": False,
            "auto_send": False,
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
            "use_tls": True,
            "username": "",
            "from_email": "",
            "to_email": "",
            "notification_types": ["salary", "interview", "offer", "wechat"],
            "confidence_threshold": 0.8,
        },
        "daily_summary": {
            "enabled": False,
            "auto_send": False,
            "send_time": "20:00",
            "timezone": "Asia/Shanghai",
            "top_jobs_limit": 3,
            "include_job_count": True,
            "include_conversation_count": True,
            "include_interested_hr": True,
            "include_top_jobs": True,
            "detail_level": "compact",
        },
    },
    "follow_up": {
        "enabled": False,
        "interval_hours": 48,
        "skip_weekends": True,
    },
    "dedup": {
        "history_file": "./data/history.jsonl",
    },
    "safety": {
        "daily_platform_page_limit": 500,
        "risk_lock_minutes": 10,
    },
    "browser": {
        "runtime": "builtin",
        "proxy_host": "127.0.0.1",
        "proxy_port": 3456,
        "chrome_ports": [9222, 9229, 9333],
        "auto_start_proxy": True,
        "enable_port_guard": True,
        "site_patterns": True,
    },
}


def credentials_path_for(config_path: Path | None = None) -> Path:
    """Return the local credentials file paired with a config file."""
    config_path = Path(config_path or "config.yaml")
    stem = config_path.stem.lstrip(".") or "config"
    return config_path.with_name(f".{stem}.credentials.yaml")


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load public settings plus local credentials, falling back to defaults."""
    cfg = _deep_copy_dict(DEFAULTS)
    config_path = Path(config_path or "config.yaml")

    # Load the private file first so a not-yet-migrated config.yaml remains the
    # source of truth until startup moves its legacy credential fields.
    credentials = _load_yaml_mapping(credentials_path_for(config_path))
    if credentials:
        _deep_merge(cfg, credentials)

    user_cfg = _load_yaml_mapping(config_path)
    if user_cfg:
        user_throttle = user_cfg.get("throttle")
        if (
            isinstance(user_throttle, dict)
            and "send_window_enabled" not in user_throttle
            and isinstance(user_throttle.get("send_windows"), list)
            and user_throttle["send_windows"]
        ):
            # Migrate legacy configs before defaults fill the new switch in.
            user_throttle["send_window_enabled"] = True
        _deep_merge(cfg, user_cfg)
    _normalize_config_sections(cfg)
    _validate_ai_provider(cfg)
    return cfg


def save_config(config: dict[str, Any], config_path: Path | None = None) -> None:
    """Persist settings without writing AI credentials to config.yaml."""
    config_path = Path(config_path or "config.yaml")
    public_config = _deep_copy_dict(config)
    ai_cfg = public_config.get("ai")
    credentials: dict[str, Any] = {}
    if isinstance(ai_cfg, dict):
        for field in AI_CREDENTIAL_FIELDS:
            value = ai_cfg.pop(field, None)
            if value is not None and str(value).strip():
                credentials[field] = value

    private_path = credentials_path_for(config_path)
    if credentials:
        _write_yaml_atomic(private_path, {"ai": credentials})

    _write_yaml_atomic(config_path, public_config)

    if not credentials:
        try:
            private_path.unlink()
        except FileNotFoundError:
            pass


def migrate_legacy_credentials(config_path: Path | None = None) -> bool:
    """Move credentials out of an existing config.yaml on the next startup."""
    config_path = Path(config_path or "config.yaml")
    public_config = _load_yaml_mapping(config_path)
    ai_cfg = public_config.get("ai")
    if not isinstance(ai_cfg, dict):
        return False

    legacy_values = {field: ai_cfg.pop(field) for field in AI_CREDENTIAL_FIELDS if field in ai_cfg}
    if not legacy_values:
        return False

    private_path = credentials_path_for(config_path)
    private_config = _load_yaml_mapping(private_path)
    private_ai = private_config.setdefault("ai", {})
    if not isinstance(private_ai, dict):
        private_ai = {}
        private_config["ai"] = private_ai
    for field, value in legacy_values.items():
        if value is not None and str(value).strip():
            private_ai[field] = value
        else:
            private_ai.pop(field, None)

    if private_ai:
        _write_yaml_atomic(private_path, private_config)
    _write_yaml_atomic(config_path, public_config)
    if not private_ai:
        try:
            private_path.unlink()
        except FileNotFoundError:
            pass
    return True


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        content = yaml.safe_load(f) or {}
    return content if isinstance(content, dict) else {}


def _write_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    """Atomically write a local YAML file with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            yaml.safe_dump(data, temporary, allow_unicode=True, default_flow_style=False, sort_keys=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _normalize_config_sections(config: dict[str, Any]) -> dict[str, Any]:
    """Replace malformed sections and discard retired collection-count settings."""
    for section, defaults in DEFAULTS.items():
        if isinstance(defaults, dict) and not isinstance(config.get(section), dict):
            config[section] = _deep_copy_dict(defaults)

    _normalize_throttle(config)
    return remove_retired_collection_settings(config)


def _normalize_throttle(config: dict[str, Any]) -> None:
    """Normalize optional send-window settings while preserving legacy configs."""
    throttle = config.get("throttle")
    if not isinstance(throttle, dict):
        return

    windows = throttle.get("send_windows")
    if not isinstance(windows, list):
        windows = []
        throttle["send_windows"] = windows
    else:
        throttle["send_windows"] = [str(window).strip() for window in windows if str(window).strip()]

    if "send_window_enabled" not in throttle:
        # Legacy configurations used a non-empty window list as the switch.
        throttle["send_window_enabled"] = bool(throttle["send_windows"])
    else:
        throttle["send_window_enabled"] = _coerce_bool(throttle["send_window_enabled"])


def _coerce_bool(value: Any) -> bool:
    """Parse common YAML/API boolean representations without truthy strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0", ""}:
            return False
    return bool(value)


def effective_send_windows(config: dict[str, Any] | None) -> list[str]:
    """Return configured windows only when the explicit window guard is enabled."""
    throttle = config.get("throttle", {}) if isinstance(config, dict) else {}
    if not isinstance(throttle, dict) or not throttle.get("send_window_enabled", False):
        return []
    windows = throttle.get("send_windows", [])
    return list(windows) if isinstance(windows, list) else []


def validate_runtime_settings(config: dict[str, Any]) -> None:
    """Reject invalid throttle and platform-safety values before persistence."""
    for section in ("throttle", "collection", "safety"):
        if section in config and not isinstance(config[section], dict):
            raise ValueError(f"{section} 必须是对象")

    throttle = config.get("throttle")
    if isinstance(throttle, dict):
        if "send_window_enabled" in throttle and not isinstance(throttle["send_window_enabled"], bool):
            raise ValueError("throttle.send_window_enabled 必须是布尔值")

        windows = throttle.get("send_windows", [])
        if not isinstance(windows, list):
            raise ValueError("throttle.send_windows 必须是时间段数组")
        for index, window in enumerate(windows):
            if not isinstance(window, str):
                raise ValueError(f"throttle.send_windows[{index}] 必须是 HH:MM-HH:MM 格式")
            match = re.fullmatch(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", window.strip())
            if not match:
                raise ValueError(f"时间段“{window}”格式错误，请使用 HH:MM-HH:MM")
            start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
            if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
                raise ValueError(f"时间段“{window}”超出有效时间范围")
            if start_hour * 60 + start_minute >= end_hour * 60 + end_minute:
                raise ValueError(f"时间段“{window}”结束时间必须晚于开始时间")

        windows_enabled = throttle.get("send_window_enabled")
        if windows_enabled is None:
            # Preserve legacy API clients: a non-empty windows list implied enabled.
            windows_enabled = bool(windows)
        if windows_enabled and not windows:
            raise ValueError("启用发送时间限制时，至少需要配置一个有效时间段")

        def validate_number(
            key: str,
            label: str,
            minimum: float,
            maximum: float,
            *,
            integer: bool = False,
        ) -> float | None:
            value = throttle.get(key)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"throttle.{key} 必须是有效数字")
            if integer and not float(value).is_integer():
                raise ValueError(f"throttle.{key} 必须是整数")
            if not minimum <= value <= maximum:
                raise ValueError(f"{label}必须在 {minimum:g} 到 {maximum:g} 之间")
            return float(value)

        validate_number("daily_limit", "每日发送上限", 1, 200, integer=True)
        interval_min = validate_number("interval_min", "发送最短间隔", 10, 600, integer=True)
        interval_max = validate_number("interval_max", "发送最长间隔", 10, 600, integer=True)
        validate_number("day_off_probability", "随机休息概率", 0, 1)
        browse_min = validate_number("browse_duration_min", "模拟浏览最短时长", 5, 120, integer=True)
        browse_max = validate_number("browse_duration_max", "模拟浏览最长时长", 5, 120, integer=True)
        if interval_min is not None and interval_max is not None and interval_min > interval_max:
            raise ValueError("发送最短间隔不能大于发送最长间隔")
        if browse_min is not None and browse_max is not None and browse_min > browse_max:
            raise ValueError("模拟浏览最短时长不能大于最长时长")

    collection = config.get("collection")
    if isinstance(collection, dict):
        risk_min = collection.get("risk_pause_min_minutes")
        risk_max = collection.get("risk_pause_max_minutes")
        for key, value in (("risk_pause_min_minutes", risk_min), ("risk_pause_max_minutes", risk_max)):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not float(value).is_integer() or not 1 <= value <= 60
            ):
                raise ValueError(f"collection.{key} 必须在 1 到 60 分钟之间")
        if risk_min is not None and risk_max is not None and risk_min > risk_max:
            raise ValueError("BOSS 风险暂停最短时间不能大于最长时间")

    safety = config.get("safety")
    if isinstance(safety, dict):
        for key, label, minimum, maximum in (
            ("daily_platform_page_limit", "平台每日页面访问上限", 1, 2000),
            ("risk_lock_minutes", "平台风控冷却时长", 1, 1440),
        ):
            value = safety.get(key)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not float(value).is_integer() or not minimum <= value <= maximum
            ):
                raise ValueError(f"{label}必须在 {minimum} 到 {maximum} 之间")



def remove_retired_collection_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Remove collection-count settings that are no longer supported."""

    # These settings existed briefly, but a result-count limit is not a page-access
    # safety control. Ignore stale values so old config files cannot re-enable it or
    # make the removed fields reappear in the Web UI/API.
    collection = config.get("collection", {})
    collection.pop("daily_new_jobs_limit", None)
    collection.pop("default_target_count", None)
    if "delivery_cooldown_min_minutes" in collection or "delivery_cooldown_max_minutes" in collection:
        collection.pop("delivery_cooldown_minutes", None)
    search = config.get("search", {})
    search.pop("target_count", None)
    platforms = config.get("platforms", {})
    for platform_config in platforms.values():
        if isinstance(platform_config, dict):
            platform_search = platform_config.get("search", {})
            if isinstance(platform_search, dict):
                platform_search.pop("target_count", None)
    return config


def _validate_ai_provider(config: dict[str, Any]) -> None:
    """Fail fast when the configured AI provider is not supported."""
    ai_cfg = config.get("ai", {})
    provider = ai_cfg.get("provider", "anthropic")
    if provider not in SUPPORTED_AI_PROVIDERS:
        raise ValueError("当前版本支持 Anthropic 或 OpenAI 兼容接口。")
    service = ai_cfg.get("service", "anthropic")
    if provider == "openai_compatible" and service == "anthropic":
        # Legacy configs only had `provider`; preserve them as custom OpenAI-compatible.
        ai_cfg["service"] = "custom"
        service = "custom"
    if service not in SUPPORTED_AI_SERVICES:
        raise ValueError("当前版本支持 Claude、DeepSeek、豆包或自定义 OpenAI 兼容接口。")
    expected_provider = AI_SERVICE_PRESETS[service]["provider"]
    if provider != expected_provider:
        ai_cfg["provider"] = expected_provider


def _deep_copy_dict(d: dict) -> dict:
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _deep_copy_dict(v)
        elif isinstance(v, list):
            result[k] = v[:]
        else:
            result[k] = v
    return result


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
