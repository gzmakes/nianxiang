from fastapi.testclient import TestClient

from server import main, pet_assets


def test_manifest_and_video_read_with_ranges(tmp_path, monkeypatch):
    monkeypatch.setattr(pet_assets, "ROOT", tmp_path)
    (tmp_path / "待机.webm").write_bytes(b"0123456789")
    (tmp_path / "ignore.txt").write_bytes(b"secret")
    (tmp_path / "escape.webm").symlink_to(tmp_path / "ignore.txt")
    client = TestClient(main.app, base_url="http://127.0.0.1:8787", client=("127.0.0.1", 1234))
    manifest = client.get("/api/pet-assets").json()
    assert manifest == {"available": True, "animations": [{"name": "待机", "url": "/api/pet-assets/%E5%BE%85%E6%9C%BA.webm"}]}
    url = manifest["animations"][0]["url"]
    response = client.get(url)
    assert response.status_code == 200 and response.content == b"0123456789"
    assert response.headers["content-type"] == "video/webm"
    assert response.headers["accept-ranges"] == "bytes"
    ranged = client.get(url, headers={"Range": "bytes=2-5"})
    assert ranged.status_code == 206 and ranged.content == b"2345"
    assert ranged.headers["content-range"] == "bytes 2-5/10"
    assert client.get(url, headers={"Range": "bytes=-3"}).content == b"789"
    invalid = client.get(url, headers={"Range": "bytes=99-"})
    assert invalid.status_code == 416 and invalid.headers["content-range"] == "bytes */10"
    assert client.get("/api/pet-assets/escape.webm").status_code == 404
    assert client.get("/api/pet-assets/ignore.txt").status_code == 404


def test_missing_assets_and_hosted_or_cross_origin_are_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(pet_assets, "ROOT", tmp_path / "missing")
    client = TestClient(main.app, base_url="http://127.0.0.1:8787", client=("127.0.0.1", 1234))
    assert client.get("/api/pet-assets").json() == {"available": False, "animations": []}
    assert client.get("/api/pet-assets", headers={"Origin": "https://elsewhere.example"}).status_code == 403
    assert client.get("/api/pet-assets", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/pet-assets", headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    remote = TestClient(main.app, base_url="http://127.0.0.1:8787", client=("192.0.2.2", 1234))
    assert remote.get("/api/pet-assets").status_code == 403
    monkeypatch.setattr(main, "PUBLIC_ORIGIN", "https://example.test")
    assert client.get("/api/pet-assets").status_code == 403


def test_name_validation_cannot_read_outside_asset_directory(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    root.mkdir()
    (tmp_path / "secret.webm").write_bytes(b"secret")
    monkeypatch.setattr(pet_assets, "ROOT", root)
    for name in ("../secret.webm", "..\\secret.webm", "secret.txt", ".webm", "bad\x00.webm"):
        assert pet_assets.open_video(name) is None


def test_memes_are_local_same_origin_and_whitelisted_without_following_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(pet_assets, "MEMES_ROOT", tmp_path)
    (tmp_path / "可爱.png").write_bytes(b"test image bytes")
    (tmp_path / "Ciallo.png").symlink_to(tmp_path / "可爱.png")
    (tmp_path / "not-allowed.png").write_bytes(b"private")
    client = TestClient(main.app, base_url="http://127.0.0.1:8787", client=("127.0.0.1", 1234))
    manifest = client.get("/api/pet-memes").json()
    assert manifest == {"available": True, "memes": [{"name": "可爱", "url": "/api/pet-memes/%E5%8F%AF%E7%88%B1.png"}]}
    response = client.get(manifest["memes"][0]["url"])
    assert response.status_code == 200 and response.content == b"test image bytes"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert client.get("/api/pet-memes/Ciallo.png").status_code == 404
    assert client.get("/api/pet-memes/not-allowed.png").status_code == 404
    assert client.get("/api/pet-memes", headers={"Origin": "https://elsewhere.example"}).status_code == 403
    assert client.get(manifest["memes"][0]["url"], headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    remote = TestClient(main.app, base_url="http://127.0.0.1:8787", client=("192.0.2.2", 1234))
    assert remote.get("/api/pet-memes").status_code == 403
    monkeypatch.setattr(main, "PUBLIC_ORIGIN", "https://example.test")
    assert client.get(manifest["memes"][0]["url"]).status_code == 403
    assert pet_assets.open_meme("../可爱.png") is None
    assert pet_assets.open_meme("可爱.png/secret") is None


def test_resource_contract_matches_served_media_types():
    paths = main.app.openapi()["paths"]
    video = paths["/api/pet-assets/{name}"]["get"]["responses"]
    image = paths["/api/pet-memes/{name}"]["get"]["responses"]
    for status in ("200", "206"):
        assert video[status]["content"]["video/webm"]["schema"] == {"type": "string", "format": "binary"}
    assert "416" in video
    assert image["200"]["content"]["image/png"]["schema"] == {"type": "string", "format": "binary"}
