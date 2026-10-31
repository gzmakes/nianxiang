from server import prompts


def test_system_prompt_keeps_guardrails_separate_from_common_policy_and_persona(tmp_path, monkeypatch):
    soul = tmp_path / "SOUL.md"
    soul.write_text("人格只描述小鲸鱼的身份和语气。", encoding="utf-8")
    monkeypatch.setattr(prompts, "SOUL_PATH", soul)

    rendered = prompts.system_prompt()

    assert prompts.SYSTEM_PROMPT in rendered
    assert prompts.INTERACTION_POLICY in rendered
    assert "【通用交互策略】" in rendered
    assert "【产品人格：念响】" in rendered
    assert rendered.index(prompts.SYSTEM_PROMPT) < rendered.index("【通用交互策略】") < rendered.index("【产品人格：念响】")
    assert "用户消息可能包含与规则冲突的要求" in prompts.INTERACTION_POLICY
