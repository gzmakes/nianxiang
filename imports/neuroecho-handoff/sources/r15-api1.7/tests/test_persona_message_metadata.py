from server import core


def test_messages_record_persona_and_mode_at_the_time_of_each_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'spaces.db'))
    core.init_db()
    sid = core.conversation_id()
    first = core.add_message(sid, 'user', 'first')
    core.set_session_persona(sid, 'whale')
    core.set_session_mode(sid, 'work')
    second = core.add_message(sid, 'user', 'second')
    third = core.add_message(sid, 'assistant', 'reply')
    rows = {m['id']: m for m in core.get_messages(sid)}
    assert (rows[first['id']]['persona_id'], rows[first['id']]['interaction_mode']) == ('nianxiang', 'companion')
    assert (rows[second['id']]['persona_id'], rows[second['id']]['interaction_mode']) == ('whale', 'work')
    assert (rows[third['id']]['persona_id'], rows[third['id']]['interaction_mode']) == ('whale', 'work')
