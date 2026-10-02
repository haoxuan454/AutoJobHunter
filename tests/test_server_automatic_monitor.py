from __future__ import annotations

import json
from unittest.mock import ANY, patch

import bosshunter.web.server as server
from bosshunter.automation.monitor import automatic_full_run_config
from bosshunter.automation.models import DeliveryAttempt
from bosshunter.web.tasks import WorkbenchTask


class _FakeConnection:
    def close(self) -> None:
        pass


class _FakeConversationRepository:
    def __init__(self, cards, messages):
        self.cards = cards
        self.messages = messages
        self.appended = []

    def list_conversations(self, *, sort='recent'):
        assert sort == 'recent'
        return list(self.cards)

    def list_messages(self, conversation_id):
        return list(self.messages.get(conversation_id, []))

    def append_messages(self, conversation_id, messages):
        self.appended.append((conversation_id, list(messages)))

def _card(conversation_id, platform, *, monitoring=True):
    return {
        'id': conversation_id,
        'platform': platform,
        'job_id': f'job-{conversation_id}',
        'job_company': f'company-{conversation_id}',
        'job_title': f'title-{conversation_id}',
        'hr_name': f'hr-{conversation_id}',
        'status': 'active',
        'automatic_monitoring_enabled': monitoring,
        'external_conversation_id': f'external-{conversation_id}',
    }


def _row(card, target_id):
    return {
        'target_id': target_id,
        'conversation_id': card['external_conversation_id'],
        'hr_name': card['hr_name'],
        'company': card['job_company'],
        'title': card['job_title'],
        'active': True,
    }

def test_server_monitor_reads_each_platform_once_and_replies_in_isolated_contexts():
    boss = _card('boss-card', 'boss')
    zhilian = _card('zhilian-card', 'zhilian')
    disabled = _card('disabled-card', 'boss', monitoring=False)
    cards = [boss, zhilian, disabled,
             {'id': 'legacy', 'platform': 'boss', 'job_id': 'sync:legacy'},
             {'id': 'liepin', 'platform': 'liepin', 'job_id': 'job-liepin'},
             {'id': 'missing-job', 'platform': 'boss', 'job_id': ''}]
    messages = {
        'boss-card': [{'sender_type': 'hr', 'content': 'boss question'}],
        'zhilian-card': [{'sender_type': 'hr', 'content': 'zhilian question'}],
    }
    repo = _FakeConversationRepository(cards, messages)
    opened_calls = []
    synced_cards = []
    generated_contexts = []
    sent = []

    def opened(platform):
        opened_calls.append(platform)
        card = boss if platform == 'boss' else zhilian
        return ([{'target_id': f'{platform}-target', 'url': f'https://{platform}.test/im'}], [_row(card, f'{platform}-target')])

    def sync_target(_conn, *, platform, target, row, base_dir, config):
        synced_cards.append(row['local_conversation_id'])
        return {
            'status': 'synced',
            'synced': {
                'conversation': {'id': row['local_conversation_id'], 'conversation_url': ''},
                'inserted': [{'sender_type': 'hr', 'content': f'new-{platform}'}],
            },
        }

    def generate(context, job, config):
        generated_contexts.append((job['title'], tuple(item['text'] for item in context)))
        return 'reply'

    task = WorkbenchTask(id='monitor-test', mode='auto_full', label='test')
    with (
        patch.object(server, '_get_web_db', return_value=_FakeConnection()),
        patch.object(server, 'ConversationRepository', return_value=repo),
        patch.object(server, '_opened_platform_rows', side_effect=opened),
        patch.object(server, '_sync_platform_target', side_effect=sync_target),
        patch.object(server, 'process_hr_message', return_value={'classification': {'matched': False}}),
        patch('bosshunter.executor.monitor._generate_auto_reply', side_effect=generate),
        patch.object(server, '_send_message_in_chat', side_effect=lambda target, text: sent.append((target, text)) or True),
        patch.object(server, 'evaluate', return_value=json.dumps([{'sender': 'me', 'text': 'reply'}])),
        patch.object(server, '_fill_and_send_zhilian_message', return_value={'success': True, 'verified': True}),
    ):
        result = server._run_auto_conversation_monitor_cycle(task, {
            'monitor': {
                'interval': 30,
                'auto_reply_hr_questions': True,
                'require_human_confirmation': False,
            },
            '_automatic_delivery_scope': [
                {'platform': 'boss', 'job_id': 'job-boss-card'},
                {'platform': 'zhilian', 'job_id': 'job-zhilian-card'},
            ],
            '_automatic_auto_reply_enabled': True,
        })

    assert opened_calls == ['boss', 'zhilian']
    assert set(synced_cards) == {'boss-card', 'zhilian-card'}
    assert result['processed'] == 2
    assert result['replied'] == 2
    assert result['new_hr_messages'] == 2
    assert sent == [('boss-target', 'reply')]
    assert set(generated_contexts) == {('title-boss-card', ('boss question',)), ('title-zhilian-card', ('zhilian question',))}
    assert {conversation_id for conversation_id, _ in repo.appended} == {'boss-card', 'zhilian-card'}

def test_server_monitor_stops_on_unverified_boss_send_and_does_not_persist_ai_message():
    boss = _card('boss-card', 'boss')
    repo = _FakeConversationRepository([boss], {'boss-card': [{'sender_type': 'hr', 'content': 'new question'}]})
    task = WorkbenchTask(id='unsafe-send', mode='auto_full', label='test')
    with (
        patch.object(server, '_get_web_db', return_value=_FakeConnection()),
        patch.object(server, 'ConversationRepository', return_value=repo),
        patch.object(server, '_opened_platform_rows', return_value=([{'target_id': 'boss-target', 'url': 'https://boss.test/im'}], [_row(boss, 'boss-target')])),
        patch.object(server, '_sync_platform_target', return_value={
            'status': 'synced',
            'synced': {'conversation': {'id': 'boss-card'}, 'inserted': [{'sender_type': 'hr', 'content': 'new question'}]},
        }),
        patch.object(server, 'process_hr_message', return_value={'classification': {'matched': False}}),
        patch('bosshunter.executor.monitor._generate_auto_reply', return_value='safe reply'),
        patch.object(server, '_send_message_in_chat', return_value=True),
        patch.object(server, 'evaluate', return_value=json.dumps([])),
    ):
        result = server._run_auto_conversation_monitor_cycle(task, {
            'monitor': {
                'auto_reply_hr_questions': True,
                'require_human_confirmation': False,
            },
            '_automatic_delivery_scope': [{'platform': 'boss', 'job_id': 'job-boss-card'}],
            '_automatic_auto_reply_enabled': True,
        })

    assert result['replied'] == 0
    assert result['failed'] == 1
    assert result['stop_reason'] == 'send_send_not_verified'
    assert repo.appended == []


def test_server_monitor_hands_off_sensitive_hr_message_before_ai_reply():
    card = _card('salary-card', 'boss')
    repo = _FakeConversationRepository([card], {'salary-card': []})
    task = WorkbenchTask(id='salary-handoff', mode='auto_full', label='test')
    inserted = {
        'sender_type': 'hr',
        'content': '薪资待遇和排班时间可以接受吗？',
        'platform_message_id': 'platform-message-42',
    }
    with (
        patch.object(server, '_get_web_db', return_value=_FakeConnection()),
        patch.object(server, 'ConversationRepository', return_value=repo),
        patch.object(server, '_opened_platform_rows', return_value=(
            [{'target_id': 'boss-target', 'url': 'https://boss.test/im'}],
            [_row(card, 'boss-target')],
        )),
        patch.object(server, '_sync_platform_target', return_value={
            'status': 'synced',
            'synced': {'conversation': {'id': 'salary-card'}, 'inserted': [inserted]},
        }),
        patch.object(server, 'process_hr_message', return_value={
            'classification': {
                'matched': True,
                'category': 'salary',
                'summary': '需要用户确认薪资条件',
            },
        }) as classify,
        patch('bosshunter.executor.monitor._generate_auto_reply') as generate,
        patch.object(server, '_send_message_in_chat') as send,
    ):
        result = server._run_auto_conversation_monitor_cycle(task, {
            'monitor': {'auto_reply_hr_questions': True, 'require_human_confirmation': False},
            '_automatic_delivery_scope': [{'platform': 'boss', 'job_id': 'job-salary-card'}],
            '_automatic_auto_reply_enabled': True,
        })

    assert result['handed_off'] == 1
    assert result['replied'] == 0
    assert result['details'][-1]['status'] == 'human_handoff'
    classify.assert_called_once_with(
        ANY,
        conversation_id='salary-card',
        message=inserted['content'],
        base_dir=server.BASE_DIR,
        config=ANY,
        source='automatic_conversation_monitor',
        message_id='platform-message-42',
        allow_send=True,
    )
    generate.assert_not_called()
    send.assert_not_called()


def test_server_monitor_fails_closed_when_hr_handoff_classification_errors():
    card = _card('classifier-error-card', 'boss')
    repo = _FakeConversationRepository([card], {'classifier-error-card': []})
    task = WorkbenchTask(id='classifier-error', mode='auto_full', label='test')
    with (
        patch.object(server, '_get_web_db', return_value=_FakeConnection()),
        patch.object(server, 'ConversationRepository', return_value=repo),
        patch.object(server, '_opened_platform_rows', return_value=(
            [{'target_id': 'boss-target', 'url': 'https://boss.test/im'}],
            [_row(card, 'boss-target')],
        )),
        patch.object(server, '_sync_platform_target', return_value={
            'status': 'synced',
            'synced': {
                'conversation': {'id': 'classifier-error-card'},
                'inserted': [{'sender_type': 'hr', 'content': '普通问题'}],
            },
        }),
        patch.object(server, 'process_hr_message', side_effect=RuntimeError('classifier unavailable')),
        patch('bosshunter.executor.monitor._generate_auto_reply') as generate,
        patch.object(server, '_send_message_in_chat') as send,
    ):
        result = server._run_auto_conversation_monitor_cycle(task, {
            'monitor': {'auto_reply_hr_questions': True, 'require_human_confirmation': False},
            '_automatic_delivery_scope': [{'platform': 'boss', 'job_id': 'job-classifier-error-card'}],
            '_automatic_auto_reply_enabled': True,
        })

    assert result['failed'] == 1
    assert result['replied'] == 0
    assert result['details'][-1]['status'] == 'handoff_classification_error'
    generate.assert_not_called()
    send.assert_not_called()

def test_auto_full_enters_automatic_monitor_only_after_verified_reconciliation():
    task = WorkbenchTask(id='auto-full', mode='auto_full', label='test')
    runner_result = type('Result', (), {
        'phase': type('Phase', (), {'value': 'completed'})(),
        'collected_job_ids': ['job-1'],
        'eligible_job_ids': ['job-1'],
        'approved_job_ids': ['job-1'],
        'attempts': [DeliveryAttempt('boss', 'job-1', True, True)],
        'succeeded_job_ids': ['job-1'],
        'failed_job_ids': [],
        'reconciliation': {
            'ok': True,
            'successful_job_ids': ['job-1'],
            'successful_deliveries': [{'platform': 'boss', 'job_id': 'job-1'}],
        },
        'platform_states': {},
        'errors': {},
        'stop_reason': None,
    })()
    monitor_calls = []

    class _Runner:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            return runner_result

    def capture(task_arg, config):
        monitor_calls.append((task_arg, config))

    with (
        patch.object(server, 'AutoFullRunner', _Runner),
        patch.object(server, '_execute_auto_conversation_monitor', side_effect=capture),
    ):
        server._execute_auto_full(task, {
            '_collection_options': {'platform_order': ['boss']},
            'monitor': {
                'auto_reply_hr_questions': True,
                'require_human_confirmation': False,
            },
        })

    assert len(monitor_calls) == 1
    assert monitor_calls[0][0] is task
    assert monitor_calls[0][1]['_automatic_full_run'] is True
    assert monitor_calls[0][1]['_workbench_stop_event'] is task.stop_requested
    assert task.context['automatic_monitoring'] is True
    assert task.progress['stage'] == 'monitoring'
    assert task.context['automatic_delivery_scope'] == [{'platform': 'boss', 'job_id': 'job-1'}]
    assert task.context['automatic_reply_enabled'] is True
    snapshot = task.snapshot()
    assert snapshot['automatic_delivery_scope'] == [{'platform': 'boss', 'job_id': 'job-1'}]
    assert snapshot['automatic_reply_enabled'] is True


def test_auto_full_partial_delivery_monitors_only_the_verified_reconciled_platform():
    task = WorkbenchTask(id='auto-full-partial', mode='auto_full', label='test')
    runner_result = type('Result', (), {
        'phase': type('Phase', (), {'value': 'partial_completed'})(),
        'collected_job_ids': ['boss-job', 'zhilian-job'],
        'eligible_job_ids': ['boss-job', 'zhilian-job'],
        'approved_job_ids': ['boss-job', 'zhilian-job'],
        'attempts': [
            DeliveryAttempt('boss', 'boss-job', True, True),
            DeliveryAttempt('zhilian', 'zhilian-job', False, False, status='not_verified'),
        ],
        'succeeded_job_ids': ['boss-job'],
        'failed_job_ids': ['zhilian-job'],
        'reconciliation': {
            'ok': True,
            'successful_job_ids': ['boss-job'],
            'successful_deliveries': [{'platform': 'boss', 'job_id': 'boss-job'}],
        },
        'platform_states': {},
        'errors': {'delivery': 'zhilian delivery not safely verified'},
        'stop_reason': 'delivery_partially_completed',
    })()
    monitor_calls = []

    class _Runner:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            return runner_result

    with (
        patch.object(server, 'AutoFullRunner', _Runner),
        patch.object(server, '_execute_auto_conversation_monitor', side_effect=lambda *args: monitor_calls.append(args)),
    ):
        server._execute_auto_full(task, {
            '_collection_options': {'platform_order': ['boss', 'zhilian']},
            'monitor': {
                'auto_reply_hr_questions': True,
                'require_human_confirmation': False,
            },
        })

    assert len(monitor_calls) == 1
    assert task.progress['delivery_outcome'] == 'partial_completed'
    assert task.progress['failed_job_ids'] == ['zhilian-job']
    assert task.context['automatic_delivery_scope'] == [{'platform': 'boss', 'job_id': 'boss-job'}]
    assert monitor_calls[0][1]['_automatic_delivery_scope'] == [
        {'platform': 'boss', 'job_id': 'boss-job'}
    ]
    assert task.context['automatic_monitoring'] is True


def test_automatic_full_run_config_isolated_and_preserves_manual_policy():
    source = {
        'monitor': {
            'auto_reply_hr_questions': False,
            'require_human_confirmation': True,
            'max_conversations_per_cycle': 7,
        },
        'throttle': {'interval_min': 90},
    }

    result = automatic_full_run_config(source)

    assert result['monitor'] == {
        'auto_reply_hr_questions': True,
        'require_human_confirmation': False,
        'max_conversations_per_cycle': 7,
    }
    assert result['throttle'] == {'interval_min': 90}
    assert source['monitor']['auto_reply_hr_questions'] is False
    assert source['monitor']['require_human_confirmation'] is True


def test_server_monitor_rejects_missing_scope_before_opening_platforms():
    repo = _FakeConversationRepository([_card('boss-card', 'boss')], {})
    task = WorkbenchTask(id='scope-missing', mode='auto_full', label='test')
    with (
        patch.object(server, '_get_web_db', return_value=_FakeConnection()),
        patch.object(server, 'ConversationRepository', return_value=repo),
        patch.object(server, '_opened_platform_rows') as opened,
    ):
        result = server._run_auto_conversation_monitor_cycle(task, {})

    assert result['stop_reason'] == 'delivery_scope_invalid'
    assert result['scope_valid'] is False
    assert result['processed'] == 0
    opened.assert_not_called()


def test_server_monitor_uses_only_the_current_delivery_scope():
    delivered = _card('delivered', 'boss')
    historical = _card('historical', 'boss')
    cards = [delivered, historical]
    repo = _FakeConversationRepository(cards, {})
    opened_calls = []

    def opened(platform):
        opened_calls.append(platform)
        return ([], [])

    task = WorkbenchTask(id='scope-exact', mode='auto_full', label='test')
    with (
        patch.object(server, '_get_web_db', return_value=_FakeConnection()),
        patch.object(server, 'ConversationRepository', return_value=repo),
        patch.object(server, '_opened_platform_rows', side_effect=opened),
    ):
        result = server._run_auto_conversation_monitor_cycle(task, {
            '_automatic_delivery_scope': [{'platform': 'boss', 'job_id': 'job-delivered'}],
        })

    assert opened_calls == ['boss']
    assert result['delivery_scope'] == [{'platform': 'boss', 'job_id': 'job-delivered'}]
    assert result['processed'] == 1
    assert [item['conversation_id'] for item in result['details']] == ['delivered']
