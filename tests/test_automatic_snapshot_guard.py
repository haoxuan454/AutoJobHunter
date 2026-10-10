from unittest.mock import Mock

import pytest

from bosshunter.automation.snapshot_guard import guarded_chat_opener
from bosshunter.platform_delivery.reply.boss import send_conversation_reply as send_boss_reply
from bosshunter.platform_delivery.reply.zhilian import send_conversation_reply as send_zhilian_reply


@pytest.mark.parametrize('adapter', [send_boss_reply, send_zhilian_reply])
@pytest.mark.parametrize('change', ['manual_reply', 'hr_reply', 'same_text_new_id', 'unreadable'])
def test_changed_platform_after_generation_never_sends(adapter, change):
    baseline = [{'sender': 'hr', 'text': '请介绍经验', 'message_id': 'm1'}]
    current = list(baseline)
    if change == 'manual_reply':
        current.append({'sender': 'me', 'text': '已回复'})
    elif change == 'hr_reply':
        current.append({'sender': 'hr', 'text': '不用了，谢谢'})
    elif change == 'same_text_new_id':
        current = [{**baseline[0], 'message_id': 'm2'}]
    else:
        current = None
    opened = Mock(return_value={'status': 'matched_chat_loaded', 'success': True})
    guarded = guarded_chat_opener(baseline, open_chat=opened, read_messages=Mock(return_value=current))
    send, count = Mock(), Mock()
    result = adapter('target', {}, '草稿', open_chat=guarded, read_snapshot=count, send=send)
    assert not result['verified'] and not result['action_started']
    assert result['error'] in {'platform_changed_during_generation', 'automatic_snapshot_unreadable'}
    send.assert_not_called()
    count.assert_not_called()


def test_unchanged_thread_passes_and_system_receipts_are_ignored():
    baseline = [{'sender': 'hr', 'text': '你好', 'id': 'm1'}]
    opened = {'status': 'matched_chat_loaded', 'success': True}
    guard = guarded_chat_opener(baseline, open_chat=Mock(return_value=opened),
        read_messages=Mock(return_value=[*baseline, {'sender': 'system', 'text': '已读'}]))
    assert guard('tab', {}) == opened


@pytest.mark.parametrize('baseline', [None, [], {}, [{'sender':'hr','text':''}], ['bad']])
def test_missing_baseline_does_not_even_open_platform(baseline):
    opened = Mock()
    guard = guarded_chat_opener(baseline, open_chat=opened, read_messages=Mock())
    assert guard('tab', {})['status'] == 'automatic_snapshot_unreadable'
    opened.assert_not_called()
