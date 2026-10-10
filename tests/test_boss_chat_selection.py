import json
from unittest.mock import Mock

import pytest

from bosshunter.collection.recruiter_identity import normalize_boss_recruiter_name
from bosshunter.platform_delivery.boss_chat_selection import select_boss_chat_row


@pytest.mark.parametrize("value,expected", [
    ("陈维\n 半年前活跃", "陈维"),
    ("刘先生 3天前活跃", "刘先生"),
    ("冯女士\n                                    \n                                    在线", "冯女士"),
    ("萧先生\n 今日活跃", "萧先生"),
    ("在线科技", "在线科技"),
    ("John Smith", "John Smith"),
    ("陈维 其他公司", "陈维 其他公司"),
    ("活跃科技", "活跃科技"),
    ("陈维半年前活跃", "陈维半年前活跃"),
])
def test_only_known_separated_activity_suffix_removed(value, expected):
    assert normalize_boss_recruiter_name(value) == expected


def test_dom_fallback_after_coordinate_miss_requires_name_and_company():
    wanted = {"hr_name": "陈维", "company": "麦东信息技术"}
    active = {**wanted, "active": True}
    evaluate = Mock(side_effect=[{"success": True, "x": 1, "y": 2}, [], {"success": True}, [active], {"ready": True}])
    clicked = Mock(return_value=True)
    result = select_boss_chat_row("tab", wanted, evaluate=evaluate, click_at=clicked, list_script="LIST", timeout=0)
    assert result == {"status": "matched_chat_loaded", "opened": True, "row": active}
    assert '.click();' in evaluate.call_args_list[2].args[1]
    clicked.assert_called_once()


def test_same_name_wrong_company_never_passes_active_verification():
    wanted = {"hr_name": "陈维", "company": "A公司"}
    evaluate = Mock(side_effect=[{"success": True, "active": True}, [{"hr_name": "陈维", "company": "B公司", "active": True}], {"success": True}, [{"hr_name": "陈维", "company": "B公司", "active": True}]])
    result = select_boss_chat_row("tab", wanted, evaluate=evaluate, click_at=Mock(), list_script="LIST", timeout=0)
    assert result["status"] == "chat_open_not_verified"
    assert not result["opened"]


def test_ambiguous_rendered_row_does_not_click():
    clicked = Mock()
    result = select_boss_chat_row("tab", {"hr_name": "同名", "company": "公司"}, evaluate=Mock(return_value={"success": False, "status": "row_ambiguous"}), click_at=clicked, list_script="LIST", timeout=0)
    assert result["status"] == "row_ambiguous"
    clicked.assert_not_called()


@pytest.mark.parametrize("panel", [{"ready": False}, None, {"ready": "true"}])
def test_active_row_without_ready_target_messages_never_passes_or_reclicks(panel):
    wanted = {"hr_name": "陈维", "company": "麦东信息技术", "active": True}
    evaluate = Mock(side_effect=[{"success": True, "active": True}, [wanted], panel])
    clicked = Mock()
    result = select_boss_chat_row("tab", wanted, evaluate=evaluate,
                                  click_at=clicked, list_script="LIST", timeout=0)
    assert result == {"status": "chat_content_not_ready", "opened": False}
    clicked.assert_not_called()
    assert evaluate.call_count == 3


def test_real_local_async_panel_waits_for_target_and_extracts_leaf_messages():
    from patchright.sync_api import sync_playwright
    from bosshunter.executor.monitor import JS_EXTRACT_CHAT_LIST, JS_EXTRACT_CONVERSATION

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content('''<ul><li role="listitem" aria-selected="true">
                <div class="name-box"><span class="name-text">陈维</span><span>麦东信息技术</span></div>
                </li></ul><div class="chat-record"><div class="pre-loading">加载中</div>
                <div class="chat-message"><div class="message-item item-friend">
                <div class="text-content">另一会话的旧消息</div></div></div></div>''')
            page.evaluate("""() => {
                const panel = document.querySelector('.chat-record');
                panel.__vue__ = {loading:true,boss:{name:'别的HR',brandName:'别家公司'}};
                setTimeout(() => {
                    panel.innerHTML = `<div class="chat-message">
                        <div class="message-item item-myself"><div class="text">送达
                            <div class="text-content">您好</div></div></div>
                        <div class="message-item item-myself"><div class="text">已读
                            <div class="text-content">您好</div></div></div>
                        <div class="message-item item-friend"><div class="text-content">请介绍经验</div></div>
                        <div class="message-item item-friend"><div class="resume-card">我想要一份您的附件简历，是否同意？<button>同意</button></div></div>
                        </div>`;
                    panel.__vue__ = {loading:false,boss:{name:'陈维',brandName:'麦东信息技术'}};
                    panel.querySelectorAll('.message-item').forEach((node, i) => {
                        node.__vue__ = {$props:{message:{mid:'native-' + i,time:1791619200000 + i*1000}}};
                    });
                }, 100);
            }""")
            wanted = {"hr_name": "陈维", "company": "麦东信息技术"}
            result = select_boss_chat_row("local", wanted,
                evaluate=lambda target, script, **kw: page.evaluate(script),
                click_at=Mock(), list_script=JS_EXTRACT_CHAT_LIST, timeout=1)
            assert result["status"] == "matched_chat_loaded"
            messages = json.loads(page.evaluate(JS_EXTRACT_CONVERSATION))
            assert len(messages) == 4
            assert [m["text"] for m in messages[:3]] == ["您好", "您好", "请介绍经验"]
            assert [m["sender"] for m in messages] == ["me", "me", "hr", "hr"]
            assert messages[-1]["kind"] == "resume_request_card"
            assert [m["message_id"] for m in messages] == ['native-0','native-1','native-2','native-3']
            assert messages[0]["message_time"] == '2026-10-10T08:00:00.000Z'
            assert not any("旧消息" in m["text"] for m in messages)
            # A stale panel with loading=false but wrong identity stays blocked.
            page.evaluate("document.querySelector('.chat-record').__vue__.boss.brandName='别家公司'")
            wrong = select_boss_chat_row("local", wanted,
                evaluate=lambda target, script, **kw: page.evaluate(script),
                click_at=Mock(), list_script=JS_EXTRACT_CHAT_LIST, timeout=0)
            assert wrong["status"] == "chat_content_not_ready"
        finally:
            browser.close()


def test_real_local_dom_extraction_and_selection_without_platform_network():
    from patchright.sync_api import sync_playwright
    from bosshunter.collection.platforms.boss import JS_EXTRACT_DETAIL
    from bosshunter.executor.monitor import JS_EXTRACT_CHAT_LIST

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content('''<div class="job-boss-info"><div class="name">陈维<span class="boss-active-time">半年前活跃</span></div></div>
            <div class="chat-record"></div>
            <ul><li role="listitem"><div class="friend-content"><div class="name-box"><span class="name-text">陈维</span><span>麦东信息技术</span><span>HR</span></div></div></li>
            <li role="listitem"><div class="friend-content"><div class="name-box"><span class="name-text">陈维</span><span>别家公司</span></div></div></li></ul>''')
            page.evaluate("document.querySelectorAll('.friend-content').forEach(el => el.onclick = () => {document.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));el.classList.add('selected')})")
            page.evaluate("document.querySelector('.chat-record').__vue__ = {loading:false,boss:{name:'陈维',brandName:'麦东信息技术'}}")
            detail = json.loads(page.evaluate(JS_EXTRACT_DETAIL))
            assert detail["hr_name"] == "陈维"
            assert detail["hr_active"] == "半年前活跃"
            # Simulate intercepted coordinate clicks, then execute production DOM fallback.
            result = select_boss_chat_row("local", {"hr_name": "陈维", "company": "麦东信息技术"}, evaluate=lambda target, script, **kw: page.evaluate(script), click_at=lambda *a: True, list_script=JS_EXTRACT_CHAT_LIST, timeout=0)
            assert result["status"] == "matched_chat_loaded"
            assert result["row"]["company"] == "麦东信息技术"
            # A second identical row makes even a selected chat unsafe to choose.
            page.evaluate("document.querySelector('ul').append(document.querySelector('li').cloneNode(true))")
            ambiguous = select_boss_chat_row("local", {"hr_name": "陈维", "company": "麦东信息技术"}, evaluate=lambda target, script, **kw: page.evaluate(script), click_at=Mock(), list_script=JS_EXTRACT_CHAT_LIST, timeout=0)
            assert ambiguous["status"] == "row_ambiguous"
        finally:
            browser.close()
