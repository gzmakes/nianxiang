"""本机 DSH 插件桥：BYO 图库读取与路径安全。"""
import pytest
from server import plugin_bridge


def test_meme_pack_and_safe_file(tmp_path, monkeypatch):
    root = tmp_path / "profiles" / "desktop" / "node_modules" / "dsh-meme"
    (root / "memes" / "demo" / "memes" / "happy").mkdir(parents=True)
    (root / "package.json").write_text('{"version":"1.2.3"}', encoding="utf-8")
    (root / "memes" / "demo" / "manifest.json").write_text('{"name":"演示","license":"personal"}', encoding="utf-8")
    (root / "memes" / "demo" / "memes" / "happy" / "a.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(plugin_bridge, "PROFILES", tmp_path / "profiles")

    d = plugin_bridge.memes()
    assert d["installed"] is True and d["version"] == "1.2.3"
    items = {item["id"]: item for item in d["items"]}
    assert items["demo/happy/a.jpg"]["url"] == "/plugin-memes/demo/happy/a.jpg"
    assert items["builtin/happy.svg"]["url"] == "/static/stickers/happy.svg"
    assert plugin_bridge.meme_file("demo", "happy", "a.jpg") is not None
    assert plugin_bridge.meme_file("demo", "happy", "../secret") is None


def test_automatic_catalog_is_precise_persona_scoped_and_single_use():
    nianxiang = plugin_bridge.meme_prompt_catalog("nianxiang")
    whale = plugin_bridge.meme_prompt_catalog("whale")
    assert {item["id"] for item in nianxiang} == {
        "builtin/happy.svg", "builtin/comfort.svg", "builtin/curious.svg", "builtin/cheer.svg",
    }
    assert all(item["meaning"] and item["url"].startswith("/static/") for item in nianxiang)
    assert any(item["id"].startswith("dafeiyu-001/") for item in whale)
    assert not any(item["id"].startswith("dafeiyu-001/") for item in nianxiang)
    exact = "[表情: dafeiyu-001/happy/deyi.jpg] [表情: dafeiyu-001/happy/ok.jpg]"
    assert plugin_bridge.sanitize_meme_markers(exact, "whale") == "[表情: dafeiyu-001/happy/deyi.jpg] "
    assert plugin_bridge.sanitize_meme_markers(exact, "nianxiang") == " "
