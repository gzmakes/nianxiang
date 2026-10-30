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
