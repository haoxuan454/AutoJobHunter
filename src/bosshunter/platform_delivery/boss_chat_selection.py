"""Select a unique rendered BOSS row and verify its active identity."""

from __future__ import annotations

import json
import time
from collections.abc import Callable


def _parse(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def _script(row: dict, *, click: bool = False) -> str:
    wanted_id = str(row.get("conversation_id") or row.get("contact_id") or "").strip()
    wanted_name = str(row.get("hr_name") or row.get("name") or "").strip()
    wanted_company = str(row.get("company") or row.get("company_role") or "").strip()
    return rf"""(() => {{
      const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
      const wantedId = {json.dumps(wanted_id, ensure_ascii=False)};
      const wantedName = normalize({json.dumps(wanted_name, ensure_ascii=False)});
      const wantedCompany = normalize({json.dumps(wanted_company, ensure_ascii=False)});
      const rows = [...document.querySelectorAll('li[role=listitem]')];
      const getId = item => item.getAttribute('data-id') || item.getAttribute('data-conversation-id') || item.getAttribute('data-uid') || item.getAttribute('data-user-id') || item.getAttribute('data-geek-id') || '';
      const getName = item => normalize(item.querySelector('.name-text')?.innerText || '');
      const getCompany = item => normalize(item.querySelector('.name-box span:nth-child(2)')?.innerText || '');
      const identity = item => (!wantedName || getName(item) === wantedName) && (!wantedCompany || getCompany(item) === wantedCompany);
      let matches = wantedId ? rows.filter(item => getId(item) === wantedId && identity(item)) : [];
      if (!matches.length && wantedName && wantedCompany) matches = rows.filter(item => getName(item) === wantedName && getCompany(item) === wantedCompany);
      if (!matches.length) return JSON.stringify({{success:false,status:'row_not_found'}});
      if (matches.length !== 1) return JSON.stringify({{success:false,status:'row_ambiguous',count:matches.length}});
      const item = matches[0];
      item.scrollIntoView({{block:'nearest'}});
      {'(item.querySelector(".friend-content") || item).click();' if click else ''}
      const rect = (item.querySelector('.friend-content') || item).getBoundingClientRect();
      return JSON.stringify({{success:true,active:item.getAttribute('aria-selected') === 'true' || item.classList.contains('active') || item.classList.contains('selected') || !!item.querySelector('.friend-content.selected'),x:rect.left + rect.width / 2,y:rect.top + rect.height / 2}});
    }})()"""


def _active_identity(row: dict, wanted: dict) -> bool:
    if not row.get("active"):
        return False
    compact = lambda value: " ".join(str(value or "").split())
    wanted_id = compact(wanted.get("conversation_id") or wanted.get("contact_id"))
    row_id = compact(row.get("conversation_id") or row.get("contact_id"))
    name = compact(wanted.get("hr_name") or wanted.get("name"))
    company = compact(wanted.get("company") or wanted.get("company_role"))
    if wanted_id and row_id and wanted_id != row_id:
        return False
    if name and compact(row.get("hr_name") or row.get("name")) != name:
        return False
    if company and compact(row.get("company") or row.get("company_role")) != company:
        return False
    return bool((wanted_id and row_id == wanted_id) or (name and company))


def _content_ready_script(row: dict) -> str:
    """Verify the message panel belongs to this row and has finished loading."""
    name = str(row.get("hr_name") or row.get("name") or "").strip()
    company = str(row.get("company") or row.get("company_role") or "").strip()
    return rf"""(() => {{
      const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
      const name = normalize({json.dumps(name, ensure_ascii=False)});
      const company = normalize({json.dumps(company, ensure_ascii=False)});
      const panel = document.querySelector('.chat-record');
      if (!panel) return JSON.stringify({{ready:false}});
      const vm = panel.__vue__;
      const boss = vm && vm.boss;
      // Current platform exposes selected recruiter and loading in its panel.
      // A selected sidebar row alone cannot prove old messages have switched.
      if (!boss || !name || !company || normalize(boss.name) !== name ||
          normalize(boss.brandName) !== company || vm.loading !== false)
        return JSON.stringify({{ready:false}});
      const visible = node => node.getClientRects().length > 0 &&
        getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none';
      if ([...panel.querySelectorAll('.pre-loading')].some(visible))
        return JSON.stringify({{ready:false}});
      return JSON.stringify({{ready:true}});
    }})()"""


def select_boss_chat_row(
    target_id: str, row: dict, *, evaluate: Callable, click_at: Callable,
    list_script: str, timeout: float = 5.0,
) -> dict:
    if not (row.get("conversation_id") or row.get("contact_id") or (row.get("hr_name") or row.get("name"))):
        return {"status": "row_identity_missing", "opened": False}
    located = _parse(evaluate(target_id, _script(row), timeout=10))
    if not isinstance(located, dict) or not located.get("success"):
        return {"status": str((located or {}).get("status") or "row_not_found") if isinstance(located, dict) else "row_not_found", "opened": False}
    if not located.get("active"):
        click_at(target_id, f"{located.get('x')},{located.get('y')}")
    # Verify even an already-selected row against current DOM, not stale input.
    # One DOM fallback repairs coordinate interception; never retry sending.
    for fallback in (False, True):
        if fallback:
            clicked = _parse(evaluate(target_id, _script(row, click=True), timeout=10))
            if not isinstance(clicked, dict) or not clicked.get("success"):
                return {"status": str(clicked.get("status") or "row_click_failed") if isinstance(clicked, dict) else "row_click_failed", "opened": False}
        deadline = time.monotonic() + max(timeout, 0)
        matched = False
        while True:
            rows = _parse(evaluate(target_id, list_script, timeout=10))
            matches = [item for item in rows if isinstance(item, dict) and _active_identity(item, row)] if isinstance(rows, list) else []
            if len(matches) == 1:
                matched = True
                ready = _parse(evaluate(target_id, _content_ready_script(matches[0]), timeout=10))
                if isinstance(ready, dict) and ready.get("ready") is True:
                    return {"status": "matched_chat_loaded", "opened": True, "row": matches[0]}
            if len(matches) > 1:
                return {"status": "row_ambiguous", "opened": False}
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        if matched:
            # Do not re-click/reload a correctly selected but slow conversation.
            return {"status": "chat_content_not_ready", "opened": False}
    return {"status": "chat_open_not_verified", "opened": False}
