from __future__ import annotations

from threading import Event

from bosshunter.automation.monitor import run_monitor_cycle


def test_failed_generation_is_retried_without_a_second_new_hr_message():
    card = _conversation('retry', 'boss', activity='2026-10-10T01:00:00+00:00')
    message = {'id': 123, 'sender_type': 'hr', 'content': '普通问题'}
    pending = {}
    sent = []
    common = dict(conversations=[card], delivery_scope=_scope(('boss', 'job-1')),
                  auto_reply_enabled=True, pending_replies=pending,
                  send_reply=lambda c, text, sync: sent.append(text) or {'success': True, 'verified': True})
    result = run_monitor_cycle(**common,
        sync_one=lambda c: {'status': 'synced', 'inserted': [message], 'messages': [message]},
        generate_reply=lambda c, m: None)
    assert result['failed'] == 1 and pending['retry'] == [message]
    result = run_monitor_cycle(**common,
        sync_one=lambda c: {'status': 'synced', 'inserted': [], 'messages': [message]},
        generate_reply=lambda c, m: '您好')
    assert result['replied'] == 1 and result['new_hr_messages'] == 0
    assert pending == {} and sent == ['您好']


def test_manual_response_clears_pending_auto_reply():
    card = _conversation('manual', 'boss', activity='2026-10-10T01:00:00+00:00')
    hr = {'id': 1, 'sender_type': 'hr', 'content': '问题'}
    pending = {'manual': [hr]}
    generated = []
    result = run_monitor_cycle([card], delivery_scope=_scope(('boss', 'job-1')),
        auto_reply_enabled=True, pending_replies=pending,
        sync_one=lambda c: {'status': 'synced', 'inserted': [], 'messages': [hr, {'sender_type': 'user', 'content': '已处理'}]},
        generate_reply=lambda c, m: generated.append(True), send_reply=lambda *a: True)
    assert result['replied'] == 0 and pending == {} and generated == []


def _conversation(
    conversation_id: str,
    platform: str,
    *,
    activity: str,
    job_id: str = "job-1",
    status: str = "active",
    enabled: bool = True,
) -> dict:
    return {
        "id": conversation_id,
        "platform": platform,
        "job_id": job_id,
        "status": status,
        "automatic_monitoring_enabled": enabled,
        "last_activity_at": activity,
        "job_title": f"岗位-{conversation_id}",
        "job_company": f"公司-{conversation_id}",
    }


def _scope(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"platform": platform, "job_id": job_id} for platform, job_id in pairs]


def test_mixed_platforms_are_recent_first_and_context_isolated():
    conversations = [
        _conversation("boss-old", "boss", activity="2026-10-01T08:00:00+00:00"),
        _conversation("zhilian-new", "zhilian", activity="2026-10-01T10:00:00+00:00"),
    ]
    sync_order: list[str] = []
    generated: list[tuple[str, list[str]]] = []
    sent: list[tuple[str, str]] = []

    def sync_one(conversation):
        sync_order.append(conversation["id"])
        return {
            "status": "synced",
            "inserted": [{"sender_type": "hr", "content": f"HR-{conversation['id']}"}],
            "messages": [
                {"sender_type": "hr", "content": f"HR-{conversation['id']}"},
            ],
        }

    def generate_reply(conversation, messages):
        generated.append((conversation["id"], [item["content"] for item in messages]))
        return f"回复-{conversation['id']}"

    def send_reply(conversation, reply, _synced):
        sent.append((conversation["id"], reply))
        return {"success": True, "verified": True, "status": "sent"}

    result = run_monitor_cycle(
        conversations,
        sync_one=sync_one,
        generate_reply=generate_reply,
        send_reply=send_reply,
        auto_reply_enabled=True,
        delivery_scope=_scope(("boss", "job-1"), ("zhilian", "job-1")),
    )

    assert result["stop_reason"] is None
    assert result["replied"] == 2
    assert sync_order == ["zhilian-new", "boss-old"]
    assert generated == [
        ("zhilian-new", ["HR-zhilian-new"]),
        ("boss-old", ["HR-boss-old"]),
    ]
    assert sent == [
        ("zhilian-new", "回复-zhilian-new"),
        ("boss-old", "回复-boss-old"),
    ]


def test_closed_unsupported_and_disabled_cards_are_skipped():
    conversations = [
        _conversation("closed", "boss", activity="2026-10-01T10:00:00+00:00", status="closed"),
        _conversation("paused", "zhilian", activity="2026-10-01T09:00:00+00:00", status="paused_manual"),
        _conversation("disabled", "boss", activity="2026-10-01T08:00:00+00:00", enabled=False),
        _conversation("old", "51job", activity="2026-10-01T07:00:00+00:00"),
        _conversation("legacy", "boss", activity="2026-10-01T06:00:00+00:00", job_id="sync:legacy"),
    ]
    called = []
    result = run_monitor_cycle(
        conversations,
        sync_one=lambda card: called.append(card["id"]) or {"status": "synced"},
        generate_reply=lambda *_: "never",
        send_reply=lambda *_: {"success": True, "verified": True},
        delivery_scope=_scope(("boss", "job-1"), ("zhilian", "job-1")),
    )

    assert called == []
    assert result["processed"] == 0
    assert result["skipped"] == 5
    assert {item["status"] for item in result["details"]} == {
        "skipped",
    }


def test_no_new_hr_message_does_not_call_ai_or_send():
    calls = []
    result = run_monitor_cycle(
        [_conversation("boss-1", "boss", activity="2026-10-01T10:00:00+00:00")],
        sync_one=lambda _: {
            "status": "synced",
            "inserted": [{"sender_type": "user", "content": "我已回复"}],
            "messages": [{"sender_type": "user", "content": "我已回复"}],
        },
        generate_reply=lambda *_: calls.append("generate") or "不应发送",
        send_reply=lambda *_: calls.append("send") or {"success": True, "verified": True},
        delivery_scope=_scope(("boss", "job-1")),
    )

    assert result["new_hr_messages"] == 0
    assert result["replied"] == 0
    assert calls == []


def test_unverified_send_stops_queue_and_never_processes_next_card():
    sync_order: list[str] = []
    conversations = [
        _conversation("first", "boss", activity="2026-10-01T10:00:00+00:00"),
        _conversation("second", "zhilian", activity="2026-10-01T09:00:00+00:00"),
    ]

    def sync_one(card):
        sync_order.append(card["id"])
        return {
            "status": "synced",
            "inserted": [{"sender_type": "hr", "content": "新消息"}],
            "messages": [{"sender_type": "hr", "content": "新消息"}],
        }

    result = run_monitor_cycle(
        conversations,
        sync_one=sync_one,
        generate_reply=lambda *_: "您好",
        send_reply=lambda *_: {
            "success": False,
            "verified": False,
            "status": "send_not_verified",
        },
        auto_reply_enabled=True,
        delivery_scope=_scope(("boss", "job-1"), ("zhilian", "job-1")),
    )

    assert sync_order == ["first"]
    assert result["replied"] == 0
    assert result["stop_reason"] == "send_send_not_verified"


def test_user_stop_event_is_honored_between_cards():
    stop = Event()
    calls = []

    def sync_one(card):
        calls.append(card["id"])
        stop.set()
        return {"status": "synced", "inserted": [], "messages": []}

    result = run_monitor_cycle(
        [
            _conversation("first", "boss", activity="2026-10-01T10:00:00+00:00"),
            _conversation("second", "zhilian", activity="2026-10-01T09:00:00+00:00"),
        ],
        sync_one=sync_one,
        generate_reply=lambda *_: "不应调用",
        send_reply=lambda *_: {"success": True, "verified": True},
        delivery_scope=_scope(("boss", "job-1"), ("zhilian", "job-1")),
        stop_event=stop,
    )

    assert calls == ["first"]
    assert result["stop_reason"] == "user_stopped"


def test_missing_job_id_and_sync_legacy_cards_never_reach_platform():
    calls = []
    cards = [
        _conversation("missing", "boss", activity="2026-10-01T10:00:00+00:00", job_id=""),
        _conversation("legacy", "zhilian", activity="2026-10-01T09:00:00+00:00", job_id="sync:abc"),
    ]
    result = run_monitor_cycle(
        cards,
        sync_one=lambda card: calls.append(card["id"]) or {"status": "synced"},
        generate_reply=lambda *_: "never",
        send_reply=lambda *_: {"success": True, "verified": True},
        delivery_scope=_scope(("boss", "job-1"), ("zhilian", "job-1")),
    )
    assert calls == []
    assert result["skipped"] == 2
