"""Small browser-DOM helpers shared only by platform delivery adapters."""

from __future__ import annotations

import json
import time
from typing import Any

from bosshunter.browser import close_tab, evaluate, new_tab, press_key, type_text, wait_for_load


def parse_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"success": False, "error": "invalid_dom_result"}
        except json.JSONDecodeError:
            return {"success": False, "error": "invalid_dom_result"}
    return {"success": False, "error": "empty_dom_result"}


def open_job(job: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    target_id = new_tab(str(job.get("url") or ""), background=True)
    if not target_id:
        return None, {"success": False, "error": "open_page_failed", "history_detail": "无法打开岗位页面"}
    if not wait_for_load(target_id, timeout=15):
        close_tab(target_id)
        return None, {"success": False, "error": "page_load_timeout", "history_detail": "岗位页面加载超时"}
    return target_id, None


def inspect_page(target_id: str, platform: str) -> dict[str, Any]:
    return parse_result(evaluate(target_id, f"""
    (() => {{
      const text = document.body ? (document.body.innerText || '') : '';
      const title = document.title || '';
      const login = /登录|注册|扫码登录|登录失效|请先登录/.test(text);
      const platform = {json.dumps(platform, ensure_ascii=False)};
      return JSON.stringify({{success:true, platform, title, url:location.href,
        login_required: login && !/退出|我的简历|个人中心|消息/.test(text),
        text: text.slice(0, 1600)}});
    }})()
    """, timeout=10))


def click_text_or_selectors(target_id: str, texts: list[str], selectors: list[str]) -> dict[str, Any]:
    return parse_result(evaluate(target_id, f"""
    (() => {{
      const visible = e => {{ const r=e.getBoundingClientRect(), s=getComputedStyle(e);
        return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden' && s.pointerEvents !== 'none'); }};
      const texts = {json.dumps(texts, ensure_ascii=False)};
      const selectors = {json.dumps(selectors, ensure_ascii=False)};
      const candidates = [
        ...selectors.flatMap(s => Array.from(document.querySelectorAll(s))),
        ...Array.from(document.querySelectorAll('button,a,[role="button"]'))
      ].filter((el, i, all) => all.indexOf(el) === i && visible(el));
      const target = candidates.find(el => {{
        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
        return texts.some(value => text.includes(String(value).replace(/\\s+/g, '')));
      }});
      if (!target) return JSON.stringify({{success:false,error:'action_button_missing'}});
      target.scrollIntoView({{block:'center'}}); target.click();
      return JSON.stringify({{success:true, text:(target.innerText||target.textContent||'').trim().slice(0,100), tag:target.tagName, className:String(target.className||'')}});
    }})()
    """, timeout=10))


def find_text_or_selectors(target_id: str, texts: list[str], selectors: list[str]) -> dict[str, Any]:
    """Inspect an action without clicking it (important for preset greetings)."""
    return parse_result(evaluate(target_id, f"""
    (() => {{
      const visible = e => {{ const r=e.getBoundingClientRect(), s=getComputedStyle(e);
        return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden' && s.pointerEvents !== 'none');
      }};
      const texts = {json.dumps(texts, ensure_ascii=False)};
      const selectors = {json.dumps(selectors, ensure_ascii=False)};
      const candidates = [
        ...selectors.flatMap(s => Array.from(document.querySelectorAll(s))),
        ...Array.from(document.querySelectorAll('button,a,[role="button"]'))
      ].filter((el, i, all) => all.indexOf(el) === i && visible(el));
      const target = candidates.find(el => {{
        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
        return texts.some(value => text.includes(String(value).replace(/\\s+/g, '')));
      }});
      if (!target) return JSON.stringify({{success:false,error:'action_button_missing'}});
      return JSON.stringify({{success:true, text:(target.innerText||target.textContent||'').trim().slice(0,100), tag:target.tagName, className:String(target.className||'')}});
    }})()
    """, timeout=10))


def fill_first_visible_input(target_id: str, selectors: list[str], message: str) -> dict[str, Any]:
    result = parse_result(evaluate(target_id, f"""
    (() => {{
      const visible = e => {{ const r=e.getBoundingClientRect(), s=getComputedStyle(e);
        return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden'); }};
      const selectors = {json.dumps(selectors, ensure_ascii=False)};
      const input = selectors.flatMap(s => Array.from(document.querySelectorAll(s))).find(visible);
      if (!input) return JSON.stringify({{success:false,error:'message_input_missing'}});
      input.focus(); input.scrollIntoView({{block:'center'}});
      return JSON.stringify({{success:true, selector:input.tagName + '.' + String(input.className || '')}});
    }})()
    """, timeout=10))
    if not result.get("success"):
        return result
    if not press_key(target_id, "SelectAll") or not press_key(target_id, "Backspace"):
        return {"success": False, "error": "message_input_clear_failed"}
    if not type_text(target_id, message, human=True):
        return {"success": False, "error": "message_input_fill_failed"}
    return {"success": True}


def verify_sent(target_id: str, message: str, platform: str) -> dict[str, Any]:
    time.sleep(1.5)
    return parse_result(evaluate(target_id, f"""
    (() => {{
      const text = document.body ? (document.body.innerText || '') : '';
      const message = {json.dumps(message, ensure_ascii=False)};
      const failure = /发送失败|发送异常|请重试|登录失效|验证码|风控/.test(text);
      const found = text.includes(message);
      return JSON.stringify({{success: found && !failure, verified: found && !failure,
        error: failure ? 'platform_send_failed' : (found ? null : 'send_success_not_verified'),
        history_detail: found && !failure ? `${platform} 页面已出现发送内容` : `${platform} 未检测到可验证的发送成功信号`}});
    }})()
    """, timeout=10))
