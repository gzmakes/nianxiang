from server import core


def test_warm_start_allows_first_two_light_turns_but_respects_serious_and_opt_out():
    assert core._sticker_allowed_for_warm_start("你好，今天终于忙完了")
    assert core._sticker_allowed_for_warm_start("给我讲讲 React 和 Expo 的关系")
    assert not core._sticker_allowed_for_warm_start("我不想看到表情包")
    assert not core._sticker_allowed_for_warm_start("我现在有自伤的念头")
    assert not core._sticker_allowed_for_warm_start("家里有人去世了")


def test_warm_start_sticker_prefers_comfort_for_distressed_turns():
    catalog = [
        {"id": "builtin/happy.svg"},
        {"id": "builtin/comfort.svg"},
    ]
    assert core._warm_start_sticker_id("今天好难受", catalog) == "builtin/comfort.svg"
    assert core._warm_start_sticker_id("今天终于忙完了", catalog) == "builtin/happy.svg"


def test_first_two_assistant_replies_receive_allowlisted_sticker_when_model_omits_one(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "warm-start.db"))
    core.init_db()

    class FakeModel:
        model = "synthetic"

        def complete(self, system, prompt):
            return "我先听你说。"

    monkeypatch.setattr(core.model, "from_env", lambda: FakeModel())
    sid = core.create_session("empty")['session']['id']

    replies = []
    for text in ("今天终于忙完了", "感觉轻松多了", "继续聊聊吧"):
        result = core.generate_reply(sid, text)
        replies.append(result["reply"])

    assert "[表情: builtin/happy.svg]" in replies[0]
    assert "[表情: builtin/happy.svg]" in replies[1]
    assert "[表情:" not in replies[2]
