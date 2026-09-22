"""Shared job filtering helpers."""

import math
import re


def matching_deal_breaker(text: str, deal_breakers: list[str]) -> str | None:
    """Return the first deal-breaker keyword found in text."""
    text_lower = text.lower()
    for keyword in deal_breakers:
        cleaned_keyword = keyword.strip()
        if cleaned_keyword and cleaned_keyword.lower() in text_lower:
            return keyword
    return None


def matching_blocked_company(company: str, blocked_companies: list[str]) -> str | None:
    """Return the first blocked-company rule contained in a company name."""
    company_lower = str(company or "").strip().lower()
    for rule in blocked_companies or []:
        cleaned_rule = str(rule or "").strip()
        if cleaned_rule and cleaned_rule.lower() in company_lower:
            return cleaned_rule
    return None


def parse_monthly_salary_k(salary: str) -> tuple[float, float] | None:
    """Parse monthly salary labels from all supported collectors into K/month.

    Supported examples include ``10-15K``, ``8000-12000元/月``, ``8千-12千``,
    ``1.5-2.5万`` and open-ended labels such as ``15K以上``.  Daily/hourly
    wages and 面议 are intentionally not treated as monthly salary.
    """
    normalized = str(salary or "").strip().replace("，", ",")
    if not normalized or "面议" in normalized or re.search(r"/(?:天|日|小时|时)", normalized):
        return None

    number = r"(\d+(?:\.\d+)?)"
    unit = r"(?P<unit>[kK万千]?)"
    range_match = re.search(
        rf"{number}\s*{unit}\s*[-~至到]\s*{number}\s*(?P<unit2>[kK万千]?)",
        normalized,
    )
    if range_match:
        left, right = float(range_match.group(1)), float(range_match.group(3))
        left_unit = range_match.group("unit") or range_match.group("unit2")
        right_unit = range_match.group("unit2") or left_unit
        left_value = _salary_value_to_k(left, left_unit, normalized)
        right_value = _salary_value_to_k(right, right_unit, normalized)
        if left_value is not None and right_value is not None:
            return min(left_value, right_value), max(left_value, right_value)

    single_match = re.search(rf"{number}\s*(?P<unit>[kK万千])", normalized)
    if single_match:
        value = _salary_value_to_k(float(single_match.group(1)), single_match.group("unit"), normalized)
        if value is not None:
            if re.search(r"(?:以上|起|底薪)", normalized):
                return value, math.inf
            return value, value

    # Plain yuan/month labels without a unit suffix, e.g. 8000-12000元/月.
    plain_range = re.search(rf"{number}\s*[-~至到]\s*{number}\s*(?:元|块)?\s*/?\s*月", normalized)
    if plain_range:
        left, right = (float(plain_range.group(i)) / 1000 for i in (1, 2))
        return min(left, right), max(left, right)
    plain_single = re.search(rf"{number}\s*(?:元|块)\s*/?\s*月", normalized)
    if plain_single:
        value = float(plain_single.group(1)) / 1000
        return value, value
    return None


def _salary_value_to_k(value: float, unit: str, original: str) -> float | None:
    if unit in {"k", "K"}:
        return value
    if unit == "万":
        return value * 10
    if unit == "千":
        return value
    if "元/月" in original or "元／月" in original or "块/月" in original:
        return value / 1000
    # A unitless value is ambiguous; only accept it when the label explicitly
    # says monthly salary, otherwise avoid filtering on an unsafe conversion.
    return value / 1000 if re.search(r"(?:月薪|每月|月工资)", original) else None
