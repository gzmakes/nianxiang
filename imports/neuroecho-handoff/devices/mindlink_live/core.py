"""Real acquisition with separate rolling display and contiguous analysis buffers."""
import collections,threading,time,uuid
import numpy as np
from scipy import signal
from transport import open_serial,serial
from recording import Recorder
FS=512
BANDS=[('δ 1–4*',1,4),('θ 4–8',4,8),('α 8–13',8,13),('β 13–30',13,30),('γ 30–45',30,45)]
SOS=signal.butter(4,[1,45],btype='bandpass',fs=FS,output='sos')
ZI=signal.sosfilt_zi(SOS)
def powers(x):
    f,p=signal.welch(x,fs=FS,window='hann',nperseg=1024,noverlap=512,scaling='density')
    return [float(10*np.log10(max(np.sum(p[(f>=lo)&(f<hi)])*(f[1]-f[0]),1e-12))) for _,lo,hi in BANDS]

class Parser:
    """None marks a bad/malformed packet at its actual place in the byte stream."""
    def __init__(self):self.buf=bytearray();self.bad=0
    def feed(self,data):
        self.buf.extend(data);out=[]
        while len(self.buf)>=4:
            k=self.buf.find(b'\xaa\xaa')
            if k<0:self.buf=self.buf[-1:];break
            del self.buf[:k]
            if len(self.buf)<4:break
            n=self.buf[2]
            if n>169:self.bad+=1;out.append(None);del self.buf[0];continue
            if len(self.buf)<n+4:break
            p=bytes(self.buf[3:3+n]);check=self.buf[n+3]
            if ((~sum(p))&255)!=check:
                self.bad+=1;out.append(None);del self.buf[0];continue
            del self.buf[:n+4];rows=[];i=0;valid=True
            while i<len(p):
                ext=0
                while i<len(p) and p[i]==0x55:ext+=1;i+=1
                if i>=len(p):valid=False;break
                code=p[i];i+=1;length=1
                if code>=128:
                    if i>=len(p):valid=False;break
                    length=p[i];i+=1
                if i+length>len(p):valid=False;break
                if ext==0:rows.append((code,p[i:i+length]))
                i+=length
            if valid:out.append(rows)
            else:self.bad+=1;out.append(None)
        return out

class Monitor:
    def __init__(self,port,record_dir='recordings'):
        self.port=port;self.lock=threading.RLock();self.session_id=uuid.uuid4().hex
        self.started=time.monotonic();self.started_wall=time.time();self.connected=False;self.message='等待设备'
        self.raw=collections.deque(maxlen=FS*16);self.raw_q=collections.deque(maxlen=FS*16)
        self.raw_mask=collections.deque(maxlen=FS*16)
        # (session_seconds, raw_original, masked, envelope) -- never cleared on gaps.
        self.display=collections.deque(maxlen=FS*30)
        self.vendor={'attention':None,'meditation':None};self.vendor_times={k:0 for k in self.vendor}
        self.vendor_history=collections.deque(maxlen=180);self.model_history=collections.deque(maxlen=75)
        self.model_result=None;self.model_error=None;self.personal_result=None;self.personal_meta=None
        self.heat=collections.deque(maxlen=120);self.gaps=collections.deque(maxlen=50)
        self.q=None;self.qt=0;self.last=0;self.last_packet=0;self.total=0;self.packets=0;self.bad=0
        self.masked_total=0;self.generation=0;self.segment=0;self.rate=0;self.rate_start=self.started;self.rate_count=0
        self.sample_clock=None;self.previous=None;self.artifact_until=0;self.last_artifact=0
        self.filter_state=ZI.copy()*0;self.filter_count=0;self.squares=collections.deque(maxlen=128)
        self.gap_pending=True;self.recorder=Recorder(record_dir)
    def _filter_reset(self):
        self.filter_state=ZI.copy()*0;self.filter_count=0;self.squares.clear()
    def reset_segment(self,reason='stream_gap',now=None,display_time=None):
        now=time.monotonic() if now is None else now
        self.generation+=1;self.raw.clear();self.raw_q.clear();self.raw_mask.clear();self.segment=0
        self.model_result=None;self.personal_result=None;self._filter_reset();self.previous=None
        self.vendor={k:None for k in self.vendor};self.vendor_times={k:0 for k in self.vendor}
        self.q=None;self.qt=0;self.gap_pending=True
        t=now-self.started if display_time is None else display_time
        # Preserve all older displayed points; insert a break without fabricated samples.
        if self.sample_clock is not None:
            t=max(float(np.nextafter(self.sample_clock,np.inf)),t)
            if not self.display or self.display[-1][1] is not None:self.display.append((t,None,True,None))
        self.gaps.append({'t':t,'reason':reason})
        self.recorder.write({'type':'gap','t':t,'reason':reason,'segment_id':self.generation})
    def _samples(self,values,now,packet_end):
        if not values:return []
        rows=[]
        for value,t in values:
            self.sample_clock=t;self.gap_pending=False
            q=self.q if self.q is not None and now-self.qt<2 else 255
            spike=abs(value)>1500 or (self.previous is not None and abs(value-self.previous)>600)
            self.previous=value
            if spike:self.artifact_until=t+.25;self.last_artifact=now
            masked=spike or t<self.artifact_until or q!=0
            self.raw.append(value);self.raw_q.append(q);self.raw_mask.append(masked)
            self.total+=1;self.segment+=1;self.rate_count+=1;self.last=now
            env=None
            if masked:
                self.masked_total+=1;self.model_result=None;self.personal_result=None;self._filter_reset()
            else:
                if not self.filter_count:self.filter_state=ZI*value
                yy,self.filter_state=signal.sosfilt(SOS,[value],zi=self.filter_state)
                self.squares.append(float(yy[0]**2));self.filter_count+=1
                if self.filter_count>=FS//2 and len(self.squares)==128:env=float(np.sqrt(np.mean(self.squares)))
            self.display.append((t,value,masked,env));rows.append([t,value,q,masked,self.generation,self.total])
        return rows
    def ingest(self,events,now=None):
        now=time.monotonic() if now is None else now;records=[]
        with self.lock:
            if self.last and now-self.last>1 and not self.gap_pending:
                self.reset_segment('raw_timeout',now,display_time=self.sample_clock+1e-7 if self.sample_clock is not None else None)
            count=sum(1 for rows in events if rows is not None for c,v in rows if c==128 and len(v)==2)
            elapsed=now-self.started
            if count:
                # All times are host-arrival estimates, bounded by chunk arrival.
                # Normally use nominal spacing; fit a burst into its observed time interval when necessary.
                prev=self.sample_clock
                expected_end=(prev or 0)+count/FS
                if prev is not None and not self.gap_pending and expected_end<=elapsed and elapsed-expected_end<.25:
                    times=prev+np.arange(1,count+1)/FS
                else:
                    start=elapsed-(count-1)/FS
                    if prev is not None:start=max(start,prev+1e-7)
                    if self.display:start=max(start,self.display[-1][0]+1e-7)
                    start=min(start,elapsed)
                    if prev is not None and not self.gap_pending and start-prev>.25:
                        self.reset_segment('timing_gap',now,display_time=prev+1e-7)
                    times=np.linspace(start,elapsed,count) if count>1 else np.array([elapsed])
                stamp_index=0
            vals=[]
            for rows in events:
                if rows is None:
                    records+=self._samples(vals,now,False);vals=[];self.bad+=1
                    gap_t=self.sample_clock+1e-7 if self.sample_clock is not None else elapsed
                    if self.sample_clock is not None and count and stamp_index<count:
                        gap_t=(self.sample_clock+float(times[stamp_index]))/2
                    self.reset_segment('bad_packet',now,display_time=gap_t);continue
                self.packets+=1;self.last_packet=now
                # Flush before contact status changes so it cannot relabel prior samples.
                for code,v in rows:
                    if code==2 and len(v)==1:
                        records+=self._samples(vals,now,False);vals=[];self.q=v[0];self.qt=now
                    elif code==128 and len(v)==2:
                        vals.append((int.from_bytes(v,'big',signed=True),float(times[stamp_index])));stamp_index+=1
                    elif code in (4,5) and len(v)==1:
                        name='attention' if code==4 else 'meditation';self.vendor[name]=int(v[0]);self.vendor_times[name]=now
                if any(c in (4,5) for c,v in rows):
                    records+=self._samples(vals,now,False);vals=[]
                    self.vendor_history.append({'t':now-self.started,**self.vendor_values(now)})
                    self.recorder.write({'type':'scores','t':now-self.started,'quality':self.q,'values':dict(self.vendor)})
            records+=self._samples(vals,now,True)
            if now-self.rate_start>=2:
                self.rate=self.rate_count/(now-self.rate_start);self.rate_count=0;self.rate_start=now
            self.message='正在接收真实 RAW'
        if records:self.recorder.write({'type':'samples','rows':records})
    def run(self):
        while True:
            try:
                with open_serial(self.port) as s:
                    parser=Parser()
                    with self.lock:self.connected=True;self.reset_segment('serial_open');self.message='等待数据'
                    while True:
                        chunk=s.read(max(1,min(s.in_waiting,8192)));now=time.monotonic()
                        if chunk:self.ingest(parser.feed(chunk),now)
                        else:
                            with self.lock:
                                if self.last and now-self.last>1 and not self.gap_pending:
                                    self.reset_segment('timeout',now);self.message='数据暂时中断，自动等待恢复'
            except (serial.SerialException,OSError) as e:
                with self.lock:
                    self.connected=False;self.message='串口不可用：'+str(e)
                    if not self.gap_pending:self.reset_segment('serial_disconnect')
                time.sleep(1)
    def vendor_values(self,now):
        return {k:(v if v is not None and 1<=v<=100 and self.q==0 and now-self.qt<2 and now-self.vendor_times[k]<2 and now-self.last<1 and now-self.last_artifact>.5 else None) for k,v in self.vendor.items()}
    def model_snapshot(self,now):
        r=dict(self.model_result) if self.model_result else {'scores':None,'reasons':['warming_up']}
        if self.model_error:r={'scores':None,'reasons':[self.model_error]}
        if now-self.last>=1 or self.q!=0 or now-self.qt>=2 or now-self.last_artifact<.5:r.update(scores=None,reasons=['poor_contact_or_stale_or_artifact'])
        elif r.get('monotonic') and now-r['monotonic']>4:r.update(scores=None,reasons=['stale_prediction'])
        r.pop('monotonic',None)
        r.update(labels=['闭眼休息','中等心算','困难心算'],name='Gradient Boosting',test_balanced_accuracy=.5948258897195067,meaning='实验任务状态估计；未经本设备个人校准',calibrated=False)
        return r
    def personal_snapshot(self,now):
        r=dict(self.personal_result) if self.personal_result else {'value':None,'valid':False,'reason':'model_not_loaded' if not self.personal_meta else 'warming_up'}
        if now-self.last>=1 or self.q!=0 or now-self.qt>=2 or now-self.last_artifact<.5 or now-r.get('monotonic',0)>4:
            r.update(value=None,valid=False,reason=r.get('reason') if not self.personal_result else 'quality_or_stale')
        r.pop('monotonic',None);r['model']=self.personal_meta;return r
    def snapshot(self,now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            elapsed=now-self.started
            # Let old data scroll out even during outages; time never restarts.
            display_end=max(elapsed,self.sample_clock or elapsed)
            points=[p for p in self.display if display_end-10<=p[0]<=display_end]
            status=dict(api_version='1.0',session_id=self.session_id,port=self.port,connected=self.connected,
                live=self.connected and bool(self.last) and now-self.last<1,quality=self.q if now-self.qt<2 else None,
                age=now-self.last if self.last else None,total=self.total,packets=self.packets,bad=self.bad,masked_total=self.masked_total,
                rate=round(self.rate,1),message=self.message,vendor=self.vendor_values(now),vendor_history=list(self.vendor_history),
                model=self.model_snapshot(now),personal=self.personal_snapshot(now),model_history=list(self.model_history),
                elapsed=elapsed,display_end=display_end,heat=list(self.heat),bands=[b[0] for b in BANDS],gaps=list(self.gaps),
                raw=[None if p[2] else p[1] for p in points],raw_original=[p[1] for p in points],
                raw_mask=[p[2] for p in points],times=[p[0] for p in points],envelope=[p[3] for p in points],dt=1/FS,
                recording=self.recorder.status())
            return status
