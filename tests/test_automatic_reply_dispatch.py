from threading import Event
from unittest.mock import Mock, patch

import pytest
import sqlite3

from bosshunter.automation.reply_dispatch import dispatch_automatic_reply
from bosshunter.conversations import ConversationRepository, IncomingMessage


def setup():
    card = {'id': 'c1', 'user_id': 'local', 'platform': 'boss', 'job_id': 'j1', 'status': 'active'}
    messages = [{'id': 1, 'sender_type': 'hr', 'content': '你好', 'platform_message_id': 'm1'}]
    repo = Mock()
    repo.get_conversation.return_value = dict(card)
    repo.list_messages.return_value = messages
    repo.claim_send_attempt.side_effect = lambda **kwargs: ({**kwargs, 'status': 'pending'}, True)
    synced = {'conversation_id': 'c1', 'messages': messages}
    return repo, card, synced


def dispatch(repo, card, synced, *, stop=None, send=None, locked=False):
    with patch('bosshunter.automation.reply_dispatch.random.uniform', return_value=0):
        return dispatch_automatic_reply(repo, card, '您好', synced,
            config={}, stop_event=stop or Event(), send=send or Mock(),
            risk_locked=lambda: locked)


@pytest.mark.parametrize('change,reason', [
    ({'status': 'paused_manual'}, 'conversation_paused'),
    ({'automatic_monitoring_enabled': False}, 'automatic_monitoring_disabled'),
])
def test_user_disables_while_ai_generates(change, reason):
    repo, card, synced = setup()
    repo.get_conversation.return_value.update(change)
    send = Mock()
    result = dispatch(repo, card, synced, send=send)
    assert result['reason'] == reason
    send.assert_not_called()
    repo.claim_send_attempt.assert_not_called()


@pytest.mark.parametrize('change', [{'platform': 'zhilian'}, {'job_id': 'j2'}, {'user_id': 'other'}])
def test_changed_identity_never_sends(change):
    repo, card, synced = setup()
    repo.get_conversation.return_value.update(change)
    send = Mock()
    assert dispatch(repo, card, synced, send=send)['status'] == 'ambiguous'
    send.assert_not_called()


def test_new_manual_message_invalidates_ai_draft():
    repo, card, synced = setup()
    repo.list_messages.return_value = [*synced['messages'], {'id': 2, 'sender_type': 'user', 'content': '已回复'}]
    send = Mock()
    assert dispatch(repo, card, synced, send=send)['reason'] == 'conversation_changed_during_generation'
    send.assert_not_called()


def test_cancel_and_risk_do_not_touch_platform():
    for locked in (False, True):
        repo, card, synced = setup()
        stop = Event()
        if not locked:
            stop.set()
        send = Mock()
        result = dispatch(repo, card, synced, stop=stop, send=send, locked=locked)
        assert result['status'] in {'skipped', 'blocked'}
        send.assert_not_called()


def test_verified_reply_has_stable_key_and_only_then_persists():
    repo, card, synced = setup()
    send = Mock(return_value={'success': True, 'verified': True, 'action_started': True})
    assert dispatch(repo, card, synced, send=send)['status'] == 'sent'
    key = repo.claim_send_attempt.call_args.kwargs['idempotency_key']
    assert key.startswith('auto-reply:')
    assert repo.append_messages.call_args.args[1][0].platform_message_id == key
    assert repo.update_send_attempt.call_args.kwargs['status'] == 'sent'
    repo.claim_send_attempt.side_effect = lambda **kwargs: ({**kwargs, 'status': 'sent'}, False)
    assert dispatch(repo, card, synced, send=send)['reason'] == 'already_replied'
    assert send.call_count == 1


def test_uncertain_reply_blocks_retries_and_never_creates_fake_message():
    repo, card, synced = setup()
    send = Mock(return_value={'verified': False, 'action_started': True})
    assert dispatch(repo, card, synced, send=send)['status'] == 'send_unknown'
    assert repo.update_send_attempt.call_args.kwargs['status'] == 'unknown'
    repo.append_messages.assert_not_called()
    repo.claim_send_attempt.side_effect = lambda **kwargs: ({**kwargs, 'status': 'unknown'}, False)
    assert dispatch(repo, card, synced, send=send)['status'] == 'send_unknown'
    assert send.call_count == 1


def test_wait_is_configured_bounded_and_interruptible():
    repo, card, synced = setup()
    stop = Mock()
    stop.wait.return_value = True
    send = Mock()
    with patch('bosshunter.automation.reply_dispatch.random.uniform', return_value=123) as random:
        result = dispatch_automatic_reply(repo, card, '您好', synced, config={}, stop_event=stop, send=send, risk_locked=lambda: False)
    random.assert_called_once_with(60.0, 180.0)
    stop.wait.assert_called_once_with(123)
    assert result['reason'] == 'user_stopped'
    send.assert_not_called()


def test_platform_changed_draft_is_retryable_not_sent_and_not_an_unsafe_send():
    repo, card, synced = setup()
    send = Mock(return_value={'verified': False, 'action_started': False,
                              'error': 'platform_changed_during_generation'})
    result = dispatch(repo, card, synced, send=send)
    assert result['status'] == 'skipped'
    assert result['reason'] == 'platform_changed_during_generation'
    assert repo.update_send_attempt.call_args.kwargs['status'] == 'not_sent'
    repo.append_messages.assert_not_called()


def test_regenerated_unsent_draft_can_send_but_verified_reply_cannot_send_twice():
    conn = sqlite3.connect(":memory:")
    try:
        repo = ConversationRepository(conn)
        card = repo.upsert_conversation({"id": "c1", "platform": "boss", "job_id": "j1"})
        repo.append_messages("c1", [IncomingMessage("hr", "请介绍经验", platform_message_id="m1")])
        synced = {"conversation_id": "c1", "messages": repo.list_messages("c1")}
        send = Mock(side_effect=[
            {"verified": False, "action_started": False, "error": "platform_changed_during_generation"},
            {"verified": True, "action_started": True},
        ])

        def run(text):
            with patch("bosshunter.automation.reply_dispatch.random.uniform", return_value=0):
                return dispatch_automatic_reply(repo, card, text, synced,
                    config={}, stop_event=Event(), send=send, risk_locked=lambda: False)

        assert run("初稿")['status'] == 'skipped'
        assert run("重新结合资料生成的回复")['status'] == 'sent'
        synced['messages'] = repo.list_messages('c1')
        assert run("不能重复发送的另一个草稿")['reason'] == 'already_replied'
        assert send.call_count == 2
        assert len(repo.list_send_attempts(str(card.get('user_id') or ''), 'c1')) == 1
    finally:
        conn.close()


@pytest.mark.parametrize('status', ['pending', 'unknown', 'sent'])
def test_unsent_hash_replacement_never_reopens_unsafe_or_delivered_attempt(status):
    conn = sqlite3.connect(':memory:')
    try:
        repo = ConversationRepository(conn)
        repo.upsert_conversation({'id': 'c1', 'platform': 'boss'})
        args = {'user_id': '', 'conversation_id': 'c1', 'idempotency_key': 'one-hr-trigger', 'platform': 'boss'}
        repo.claim_send_attempt(**args, message_hash='first')
        repo.update_send_attempt(user_id='', conversation_id='c1', idempotency_key='one-hr-trigger', status=status, response={})
        attempt, claimed = repo.claim_send_attempt(**args, message_hash='regenerated', replace_unsent_hash=True)
        assert not claimed
        assert attempt['status'] == status
        assert attempt['message_hash'] == 'first'
    finally:
        conn.close()


def test_manual_hash_conflict_behavior_is_unchanged_for_unsent_drafts():
    conn = sqlite3.connect(':memory:')
    try:
        repo = ConversationRepository(conn)
        repo.upsert_conversation({'id': 'c1', 'platform': 'boss'})
        args = {'user_id': '', 'conversation_id': 'c1', 'idempotency_key': 'manual', 'platform': 'boss'}
        repo.claim_send_attempt(**args, message_hash='first')
        repo.update_send_attempt(user_id='', conversation_id='c1', idempotency_key='manual', status='not_sent', response={})
        attempt, claimed = repo.claim_send_attempt(**args, message_hash='edited')
        assert not claimed
        assert attempt['message_hash'] == 'first'
    finally:
        conn.close()
