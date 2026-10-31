# Nianxiang Voice Gateway

This service is intended to run beside GPT-SoVITS on the HAI instance. It
listens on `127.0.0.1:9881` by default, authenticates every `/v1/*` request,
and forwards only validated whale text to GPT-SoVITS at loopback `9880`.

Set `VOICE_GATEWAY_TOKEN_HASHES` to comma-separated SHA-256 token hashes. For a
temporary local setup, `VOICE_GATEWAY_TOKENS` accepts raw tokens and hashes them
in memory at startup; raw values are never returned or logged. Keep `.env` out
of Git and put TLS/remote access in a reverse proxy or private network. Never
expose GPT-SoVITS port 9880.

```bash
cp .env.example .env
# edit .env, then export its variables using your secret manager
./start.sh
curl http://127.0.0.1:9881/healthz
```

`GET /healthz` is unauthenticated. `GET /v1/status` and `POST /v1/tts` require
`Authorization: Bearer <token>`. Generated audio is returned in memory and is
not persisted by this service.

## R15 client configuration

R15 keeps the browser unaware of the gateway token. Configure the backend
environment (or its private `voice-settings.json`) before starting the R15
service:

```text
XINJI_TTS_ENABLED=true
XINJI_TTS_PROVIDER=remote
XINJI_TTS_GATEWAY_URL=https://your-private-gateway.example/v1
XINJI_TTS_GATEWAY_TOKEN=<individual-token>
XINJI_TTS_PERSONA_ID=whale
```

The gateway URL may include `/v1`; the backend appends `/tts`. Keep the token
out of browser storage, logs, Git, and public deployment variables. Set
`XINJI_TTS_PROVIDER=local` to retain the existing Windows GPT-SoVITS mode.

On Windows, start GPT-SoVITS with `PYTHONUTF8=1` and
`PYTHONIOENCODING=utf-8`. This prevents its GBK console handler from failing on
private-use characters before the gateway can receive a WAV response.

## HAI deployment

Keep GPT-SoVITS on `127.0.0.1:9880` and this gateway on `127.0.0.1:9881`.
Copy `deploy/voice-gateway.service` to `/etc/systemd/system/` and create an
untracked `/etc/nianxiang/voice-gateway.env` from `.env.example` (mode `0600`).
Enable it with `systemctl enable --now voice-gateway`. If the service is
accessed outside the host, put Nginx/Caddy or a private network in front of
9881; never open 9880 or send a long-lived token over plain HTTP.

### Token rotation

Run `python token_admin.py --generate` on an administrator machine. Deliver
the printed token privately to one teammate and put only its `sha256` value in
`VOICE_GATEWAY_TOKEN_HASHES`. To revoke or rotate a teammate, remove its hash,
write the updated environment file, and restart `voice-gateway`; there is no
public token-management endpoint. Do not use `VOICE_GATEWAY_TOKENS` in a
long-lived deployment. Keep the environment file out of Git and restrict it
to the service administrator (`chmod 600`).

The gateway has no model upload or arbitrary-path API. It accepts only the
`whale` persona and sends the configured reference audio to the loopback
GPT-SoVITS service.
