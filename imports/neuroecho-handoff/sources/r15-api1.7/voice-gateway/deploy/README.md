# HAI deployment checklist

The repository contains the gateway and deployment templates, but cloud
deployment still requires an authenticated HAI SSH/Jupyter session. Run
`check_hai.sh` first and save its output privately. Confirm the GPU, disk and
Python/Torch versions before installing anything.

On HAI, place GPT-SoVITS and the private whale assets under `/opt/nianxiang`,
then run the GPT-SoVITS API bound to `127.0.0.1:9880`. Copy the gateway to
`/opt/nianxiang/voice-gateway`, create a dedicated virtual environment, install
`requirements.txt`, and create `/etc/nianxiang/voice-gateway.env` with mode
`0600`. Set `VOICE_GATEWAY_REFERENCE_AUDIO` to the private reference file and
configure only token hashes. Install `voice-gateway.service` and verify:

```bash
curl -fsS http://127.0.0.1:9881/healthz
curl -fsS -H "Authorization: Bearer $VOICE_TOKEN" http://127.0.0.1:9881/v1/status
```

`gpt-sovits.service.example` matches the documented HAI layout used by this
project (`/opt/nianxiang/GPT-SoVITS` plus `/opt/nianxiang/venv`). If you use a
different layout, edit `WorkingDirectory`, `PATH`, and `ExecStart` before
enabling it. Set GPT/SoVITS weights through GPT-SoVITS's own API after the
process is healthy; private filenames are intentionally not committed.

Keep ports 9880 and 9881 loopback-only. Use `nginx.conf.example` with a real
certificate, or a private overlay network, for remote R15 backends. The
Tencent Cloud console must be used by an authorized operator to confirm the
instance ID, public/private addresses and security-group rules; this repo
does not contain cloud credentials and cannot perform that login.
