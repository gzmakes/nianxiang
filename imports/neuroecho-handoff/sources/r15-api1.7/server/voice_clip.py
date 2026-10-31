from __future__ import annotations
import io, json, os, re, subprocess, sys, tempfile, threading, urllib.error, urllib.request, wave
from pathlib import Path
from . import voice_settings
MAX_CHARS=800; MAX_BYTES=20_000_000; _slot=threading.BoundedSemaphore(1)
class VoiceUnavailable(Exception): pass
def spoken_text(value:str)->str:
    value=re.sub(r'\[表情[:：]\s*[^\]\r\n]+\]','',value)
    value=re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',value)
    return re.sub(r'[*_`#]','',value).strip()
def _validate_wav(data:bytes,max_bytes:int)->bytes:
    if not data or len(data)>max_bytes: raise VoiceUnavailable('语音服务返回的音频无效或过大，可使用朗读功能。')
    try:
        with wave.open(io.BytesIO(data),'rb') as audio:
            if audio.getnframes()<max(1,audio.getframerate()//10): raise VoiceUnavailable('语音服务返回空音频，可使用朗读功能。')
    except (wave.Error,EOFError) as exc: raise VoiceUnavailable('语音服务返回的不是有效 WAV，可使用朗读功能。') from exc
    return data
def _synthesize_windows(text,persona_id,settings):
    cfg=settings.get('tts',{})
    if persona_id!='whale': raise VoiceUnavailable('只有小鲸鱼人格可以生成小鲸鱼语音。')
    ref=Path(str(cfg.get('ref_audio_path','')))
    if not ref.is_file(): raise VoiceUnavailable('小鲸鱼参考音不存在，可使用朗读功能。')
    body={'text':text,'text_lang':cfg.get('text_lang','zh'),'ref_audio_path':str(ref),'prompt_text':cfg.get('prompt_text',''),'prompt_lang':cfg.get('prompt_lang','zh'),'text_split_method':'cut5','batch_size':1,'media_type':'wav','streaming_mode':False}
    req=urllib.request.Request(str(cfg.get('base_url','http://127.0.0.1:9880')).rstrip('/')+'/tts',data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json; charset=utf-8'},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=float(cfg.get('timeout_seconds',180))) as response:
            try: data=response.read(int(cfg.get('max_audio_bytes',MAX_BYTES))+1)
            except TypeError: data=response.read()
        if data.lstrip().startswith(b'{'): raise VoiceUnavailable('GPT-SoVITS 返回了错误信息，可使用朗读功能。')
        return _validate_wav(data,int(cfg.get('max_audio_bytes',MAX_BYTES)))
    except VoiceUnavailable: raise
    except (OSError,urllib.error.URLError,TimeoutError) as exc: raise VoiceUnavailable('GPT-SoVITS 服务不可用，可使用朗读功能。') from exc
def _synthesize_macos(text):
    if not os.path.exists('/usr/bin/say') or not os.path.exists('/usr/bin/afconvert'): raise VoiceUnavailable('本机语音生成不可用，可使用浏览器朗读。')
    with tempfile.TemporaryDirectory(prefix='xinji-voice-') as folder:
        aiff,wav=Path(folder)/'voice.aiff',Path(folder)/'voice.wav'
        try:
            subprocess.run(['/usr/bin/say','-v','Tingting','-o',str(aiff)],input=text.encode(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=45)
            subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16',str(aiff),str(wav)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=15)
            return _validate_wav(wav.read_bytes() if wav.is_file() else b'',MAX_BYTES)
        except (OSError,subprocess.SubprocessError,wave.Error,EOFError) as exc: raise VoiceUnavailable('本机语音生成失败，可使用浏览器朗读。') from exc
def synthesize(text:str,persona_id:str='whale')->bytes:
    text=spoken_text(text)
    if not text: raise ValueError('这条回复没有可生成语音的文字。')
    settings=voice_settings.load_settings(); cfg=settings.get('tts',{})
    if len(text)>int(cfg.get('max_chars',MAX_CHARS)): raise ValueError(f"这条回复超过 {int(cfg.get('max_chars',MAX_CHARS))} 字，请使用朗读功能。")
    if sys.platform=='win32' and not cfg.get('enabled'): raise VoiceUnavailable('本机语音生成未配置，可使用浏览器朗读。')
    if not _slot.acquire(blocking=False): raise VoiceUnavailable('正在生成另一条语音，请稍后再试。')
    try:
        if sys.platform=='win32': return _synthesize_windows(text,persona_id,settings)
        if sys.platform=='darwin': return _synthesize_macos(text)
        raise VoiceUnavailable('本机语音生成不可用，可使用浏览器朗读。')
    finally: _slot.release()
def _port_open(base_url):
    try:
        with urllib.request.urlopen(urllib.request.Request(base_url.rstrip('/')+'/docs'),timeout=.3): return True
    except urllib.error.HTTPError:
        # A running GPT-SoVITS build may not expose /docs; any HTTP response
        # still proves that the loopback service is reachable.
        return True
    except Exception: return False
def status(settings=None):
    cfg=(settings or voice_settings.load_settings()).get('tts',{}); ref=Path(str(cfg.get('ref_audio_path','')))
    if sys.platform not in ('win32', 'darwin'): state='platform_unsupported'
    elif not cfg.get('enabled'): state='voice_not_configured'
    elif sys.platform=='win32' and not ref.is_file(): state='reference_audio_missing'
    else: state='ready' if _port_open(str(cfg.get('base_url','http://127.0.0.1:9880'))) else 'service_not_running'
    return {'enabled':bool(cfg.get('enabled')),'state':state,'base_url':str(cfg.get('base_url','')),'reference_audio':ref.is_file()}
