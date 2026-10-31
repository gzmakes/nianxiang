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
project (`/opt/nianxiang/GPT-SoVITS` plus the CUDA-enabled Python at
`/root/miniforge3/bin/python`). The separate `/opt/nianxiang/venv` is for the
gateway only and must not be used to start GPT-SoVITS because it has no Torch.
If you use a different layout, edit `WorkingDirectory`, `PATH`, and
`ExecStart` before enabling it. Set GPT/SoVITS weights through GPT-SoVITS's own
API after the process is healthy; private filenames are intentionally not
committed.

Some HAI images do not boot with systemd. For those images, use
`deploy/run_hai.sh` from the gateway directory. It starts both loopback-only
processes with `nohup`, pidfiles, and the same paths as the service templates:

```bash
chmod +x /opt/nianxiang/voice-gateway/deploy/run_hai.sh
/opt/nianxiang/voice-gateway/deploy/run_hai.sh start
/opt/nianxiang/voice-gateway/deploy/run_hai.sh status
```

The script does not open a public port and does not contain tokens or model
filenames. Re-run it after an instance restart.

Keep ports 9880 and 9881 loopback-only. Use `nginx.conf.example` with a real
certificate, or a private overlay network, for remote R15 backends. The
Tencent Cloud console must be used by an authorized operator to confirm the
instance ID, public/private addresses and security-group rules; this repo
does not contain cloud credentials and cannot perform that login.
