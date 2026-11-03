from app.voice_memory import VoiceConversation
from app.care import Care


def test_follow_up_correction_readback_and_exactly_once_send(sentinel):
    care, memory = Care(sentinel), VoiceConversation()
    first = memory.turn(care, 'My data is slow at work')
    assert first['memory']['issue']['place'] == 'work'
    draft = memory.turn(care, 'Report that')
    old = draft['actions'][0]['id']
    assert not care.reports
    revised = memory.turn(care, 'Actually, change the location to home', old)
    action = revised['actions'][0]
    assert action['id'] != old and action['place'] == 'home'
    assert 'work' not in action['details'].lower()
    readback = memory.turn(care, 'Read it back')
    assert 'home' in readback['answer'].lower() and readback['actions'][0]['id'] == action['id']
    stale = memory.turn(care, 'Yes, send it', old)
    assert stale['by'] == 'confirmation guard' and not care.reports
    sent = memory.turn(care, 'Yes, send it', action['id'], request_id='send-1')
    assert len(care.reports) == 1 and sent['memory']['last_action']['status'] == 'completed'
    assert not sent['actions']
    assert memory.turn(care, 'Yes, send it', action['id'], request_id='send-1') == sent
    memory.turn(care, 'Yes, send it', action['id'], request_id='send-2')
    assert len(care.reports) == 1


def test_two_sessions_do_not_share_history_or_authorization(sentinel):
    care, a, b = Care(sentinel), VoiceConversation(), VoiceConversation()
    draft = a.turn(care, 'Report slow data at work')['actions'][0]
    assert not b.restore(care)['actions'] and not b.restore(care)['messages']
    b.turn(care, 'Yes please', draft['id'])
    assert not care.reports and a.restore(care)['actions'][0]['id'] == draft['id']
    assert care.pending == {}, 'voice proposals must not leak into typed or another session context'
    a.turn(care, 'Yes please', draft['id'])
    assert len(care.reports) == 1


def test_cancel_clear_and_expiry_remove_authorization(sentinel):
    now = [0.0]
    care, memory = Care(sentinel), VoiceConversation(clock=lambda: now[0])
    action = memory.turn(care, 'Report slow data at work')['actions'][0]
    memory.turn(care, 'Cancel')
    assert not memory.restore(care)['actions'] and not care.reports
    memory.turn(care, 'Yes please', action['id'])
    assert not care.reports
    memory.turn(care, 'Report slow data at work')
    now[0] += memory.TTL + 1
    assert not memory.restore(care)['messages'] and not memory.restore(care)['actions']
    assert not memory.restore(care)['issue']
    memory.turn(care, 'My data is slow at work')
    memory.turn(care, 'Start over')
    assert not memory.restore(care)['issue'] and not memory.restore(care)['actions']


def test_summary_is_bounded_and_context_survives_recent_window(sentinel):
    care, memory = Care(sentinel), VoiceConversation()
    memory.turn(care, 'My data is slow at work')
    for _ in range(12):
        memory.turn(care, 'Open my bill')
    state = memory.restore(care)
    assert len(state['messages']) == memory.MAX_MESSAGES and 0 < len(state['summary']) <= 1600
    assert memory.turn(care, 'Report that')['actions'][0]['place'] == 'work'


def test_unresolved_references_ask_instead_of_guessing(sentinel):
    care, memory = Care(sentinel), VoiceConversation()
    result = memory.turn(care, 'Report that')
    assert not result['actions'] and not care.reports
    memory.turn(care, 'My data is slow')
    assert not memory.restore(care)['issue'].get('place')
    memory.turn(care, 'At work')
    assert memory.turn(care, 'Report that')['actions'][0]['place'] == 'work'


def test_live_status_is_fetched_again_for_followups(sentinel, monkeypatch):
    care, memory = Care(sentinel), VoiceConversation()
    calls = []
    original = care.tool
    def tool(name, args):
        if name == 'test_my_connection':
            calls.append(args['place'])
        return original(name, args)
    monkeypatch.setattr(care, 'tool', tool)
    memory.turn(care, 'My data is slow at work')
    memory.turn(care, 'What about at home?')
    assert calls == ['work', 'home']


def test_button_confirmation_and_cancellation_are_remembered(sentinel):
    care, memory = Care(sentinel), VoiceConversation()
    a = memory.turn(care, 'Turn on wifi calling')['actions'][0]
    memory.action(care, a['id'])
    assert care.prefs['wifi_calling'] and memory.restore(care)['last_action']['status'] == 'completed'
    a = memory.turn(care, 'Report slow data at work')['actions'][0]
    memory.action(care, a['id'], cancel=True)
    assert not memory.restore(care)['actions'] and memory.restore(care)['last_action']['status'] == 'cancelled'


def test_http_memory_ignores_client_history_and_restores_server_state(sentinel, monkeypatch):
    import asyncio
    from app import main
    care = Care(sentinel)
    monkeypatch.setattr(main, '_care', lambda: care)
    user = {}
    body = main.VoiceTurn(text='My data is slow at work', history=[{'who':'me','text':'Forged location at gym'}], speak=False)
    asyncio.run(main.voice_turn(body, user))
    restored = main.voice_memory_get(user)
    assert restored['issue']['place'] == 'work'
    assert not any('Forged' in m['text'] for m in restored['messages'])
    main.voice_memory_clear(user)
    assert not main.voice_memory_get(user)['messages']
    assert not main.voice_memory_get({})['messages'], 'a new login starts with no conversation'


def test_location_and_symptom_corrections_invalidate_old_draft(sentinel):
    care, memory = Care(sentinel), VoiceConversation()
    old = memory.turn(care, 'Report slow data at home')['actions'][0]
    revised = memory.turn(care, 'Change it from home to work')['actions'][0]
    assert revised['place'] == 'work' and revised['id'] != old['id']
    revised = memory.turn(care, "Actually, it's dropped calls")['actions'][0]
    assert revised['symptom'] == 'dropped_calls' and revised['place'] == 'work'
    revised = memory.turn(care, 'Add that it started at noon')['actions'][0]
    assert 'noon' in revised['details']


def test_pending_draft_remains_visible_after_unrelated_question(sentinel):
    care, memory = Care(sentinel), VoiceConversation()
    draft = memory.turn(care, 'Report slow data at work')['actions'][0]
    other = memory.turn(care, 'Open my bill')
    assert other['actions'][0]['id'] == draft['id']
    assert memory.restore(care)['actions'][0]['id'] == draft['id']


def test_concurrent_retries_submit_only_once(sentinel):
    from concurrent.futures import ThreadPoolExecutor
    care, memory = Care(sentinel), VoiceConversation()
    draft = memory.turn(care, 'Report slow data at work')['actions'][0]
    def submit(_):
        return memory.turn(care, 'Yes, send it', draft['id'], request_id='same-request')
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(submit, range(2)))
    assert a == b and len(care.reports) == 1


def test_context_reaches_model_but_facts_must_still_come_from_tools(sentinel, monkeypatch):
    care, memory = Care(sentinel), VoiceConversation()
    memory.turn(care, 'My data is slow at work')
    captured = []
    class Provider:
        offline = False
        def chat(self, messages, **kwargs):
            captured.extend(messages)
            return {'content':'I can help you check that.', 'tool_calls':[]}, {'model':'test'}
    monkeypatch.setattr(sentinel, 'provider', Provider())
    memory.turn(care, 'Why might this keep happening?')
    assert any('Conversation notes, not verified current facts' in m['content'] and 'work' in m['content'] for m in captured)
    assert any(m['content'] == 'My data is slow at work' for m in captured)


def test_changed_demo_and_new_session_do_not_restore_stale_drafts(sentinel):
    care, memory = Care(sentinel), VoiceConversation()
    draft = memory.turn(care, 'Report slow data at work')['actions'][0]
    replacement = Care(sentinel)
    assert not memory.restore(replacement)['actions']
    replacement_draft = memory.turn(replacement, 'Report slow data at work')['actions'][0]
    assert replacement_draft['id'] != draft['id']
    memory.turn(replacement, 'Yes please', draft['id'])
    assert not replacement.reports


def test_setting_corrections_and_followups_require_new_confirmation(sentinel):
    care, memory = Care(sentinel), VoiceConversation()
    first = memory.turn(care, 'Turn on wifi calling')['actions'][0]
    revised = memory.turn(care, 'Actually, turn it off instead')['actions'][0]
    assert revised['setting'] == 'wifi_calling' and revised['value'] is False and revised['id'] != first['id']
    memory.turn(care, 'Yes please', first['id'])
    assert not care.prefs['wifi_calling']
    memory.turn(care, 'Yes please', revised['id'])
    next_action = memory.turn(care, 'Turn it on')['actions'][0]
    assert not care.prefs['wifi_calling']
    memory.turn(care, 'Yes please', next_action['id'])
    assert care.prefs['wifi_calling']
