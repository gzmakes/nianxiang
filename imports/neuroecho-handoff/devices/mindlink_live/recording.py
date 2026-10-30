"""Opt-in local JSONL recording. Original counts and bad-sample flags are retained."""
import json,threading,time,uuid
from pathlib import Path
class Recorder:
    def __init__(self,root):
        self.root=Path(root);self.lock=threading.RLock();self.file=None;self.path=None;self.error=None;self.flush_at=0
    def status(self):
        with self.lock:return {'active':self.file is not None,'file':str(self.path) if self.path else None,'error':self.error}
    def start(self,session_id):
        with self.lock:
            if self.file:return self.status()
            self.root.mkdir(parents=True,exist_ok=True)
            self.path=self.root/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.jsonl')
            self.file=self.path.open('x',encoding='utf-8');self.error=None
            self.write({'type':'metadata','recording_id':self.path.stem,'server_session_id':session_id,'fs':512,'unit':'ADC counts','rows_format':['session_seconds','raw_original','poor_signal','display_masked','segment_id','sample_index'],'label_semantics':'self_report; not device-score labels'})
            return self.status()
    def write(self,event):
        with self.lock:
            if self.file:
                try:
                    self.file.write(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n')
                    if time.monotonic()-self.flush_at>1:self.file.flush();self.flush_at=time.monotonic()
                except OSError as e:
                    self.error=str(e);self.file.close();self.file=None
    def stop(self):
        with self.lock:
            if self.file:self.file.close();self.file=None
            return self.status()
