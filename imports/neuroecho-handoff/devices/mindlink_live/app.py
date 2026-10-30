"""MindLink local service. Versioned HTTP/SSE interface is platform independent."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse,json,threading,time
from pathlib import Path
from flask import Flask,jsonify,send_file,request,Response
from core import Monitor,Parser,powers,FS
from transport import list_ports
ROOT=Path(__file__).resolve().parent
app=Flask(__name__);monitor=None;ATTENTION_SOURCE='esense';ALLOWED_ORIGINS=set()

def metrics(source=None):
    source=source or ATTENTION_SOURCE
    if source not in ('esense','personal'):raise ValueError('source must be esense or personal')
    now=time.monotonic()
    with monitor.lock:
        m=monitor;values=m.vendor_values(now);personal=m.personal_snapshot(now)
        def value(key):
            personal_selected=key=='attention' and source=='personal'
            val=personal.get('value') if personal_selected else values[key]
            ts=(m.personal_result or {}).get('monotonic',0) if personal_selected else m.vendor_times[key]
            valid=val is not None and m.connected
            return {'value':val if valid else None,'valid':valid,'source':'personal_model' if personal_selected else 'neurosky_esense',
                    'updated_at_unix':m.started_wall+ts-m.started if ts else None,'age_ms':round((now-ts)*1000) if ts else None,
                    'reason':None if valid else personal.get('reason','unavailable') if personal_selected else 'quality_artifact_stale_or_zero',
                    'unit':'score_0_100','model':m.personal_meta if personal_selected else None}
        return {'api_version':'1.0','session_id':m.session_id,'sequence':m.packets,'timestamp_unix':time.time(),
                'connected':m.connected,'live':m.connected and bool(m.last) and now-m.last<1,
                'signal_quality':m.q if now-m.qt<2 else None,'attention':value('attention'),'relaxation':value('meditation'),
                'public_task':m.model_snapshot(now),'recording':m.recorder.status(),
                'capabilities':{'personal_model_loaded':bool(m.personal_meta and 'error' not in m.personal_meta),'emotion_model_loaded':False}}
@app.before_request
def local_policy():
    # Prevent browser-based cross-site recording changes; desktop native clients need no CORS.
    origin=request.headers.get('Origin')
    same={request.host_url.rstrip('/'),'http://localhost:'+request.host.split(':')[-1]}
    if origin and origin not in same|ALLOWED_ORIGINS:return jsonify(error='origin_not_allowed'),403
@app.after_request
def headers(response):
    response.headers['Cache-Control']='no-store'
    origin=request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin']=origin;response.headers['Vary']='Origin'
        response.headers['Access-Control-Allow-Headers']='Content-Type';response.headers['Access-Control-Allow-Methods']='GET,POST,OPTIONS'
    return response
@app.get('/')
def home():return send_file(ROOT/'index.html')
@app.get('/favicon.ico')
def favicon():return '',204
@app.get('/feedback.js')
def feedback_script():return send_file(ROOT/'feedback.js')
@app.get('/demo')
def content_demo():return send_file(ROOT/'sdk/content_demo.html')
@app.get('/api/state')
def state():return jsonify(monitor.snapshot())
@app.get('/api/v1/state')
def versioned():
    try:return jsonify(metrics(request.args.get('source')))
    except ValueError as e:return jsonify(error=str(e)),400
@app.get('/api/v1/health')
def health():return jsonify(api_version='1.0',status='running',port=monitor.port,recording=monitor.recorder.status())
@app.get('/api/v1/events')
def events():
    source=request.args.get('source',ATTENTION_SOURCE)
    if source not in ('esense','personal'):return jsonify(error='unknown_source'),400
    def generate():
        while True:
            yield 'event: metrics\ndata: '+json.dumps(metrics(source),ensure_ascii=False,allow_nan=False)+'\n\n'
            time.sleep(.5)
    return Response(generate(),mimetype='text/event-stream',headers={'X-Accel-Buffering':'no'})
@app.route('/api/v1/recording/start',methods=['POST'])
def start_recording():return jsonify(monitor.recorder.start(monitor.session_id))
@app.route('/api/v1/recording/stop',methods=['POST'])
def stop_recording():return jsonify(monitor.recorder.stop())
@app.route('/api/v1/markers',methods=['POST'])
def markers():
    data=request.get_json(silent=True) or {};label=data.get('label')
    if label not in ['focus','mind_wandering','relaxed','fixation','thinking','unlabelled','emotion_rating']:return jsonify(error='invalid_label'),400
    if not monitor.recorder.status()['active']:return jsonify(error='start_recording_first'),409
    ratings={}
    if label=='emotion_rating':
        for key in ['valence','arousal']:
            val=data.get(key)
            if isinstance(val,bool) or not isinstance(val,(int,float)) or not 1<=val<=9:return jsonify(error=key+' must be 1..9'),400
            ratings[key]=val
    event={'type':'marker','t':time.monotonic()-monitor.started,'label':label,'basis':'self_report',**ratings}
    monitor.recorder.write(event);return jsonify(event)
@app.get('/api/v1/schema')
def schema():return send_file(ROOT/'api_schema.json')

def main():
    global monitor,ATTENTION_SOURCE,ALLOWED_ORIGINS
    p=argparse.ArgumentParser();p.add_argument('--port',default='auto');p.add_argument('--http-port',type=int,default=8876)
    p.add_argument('--list-ports',action='store_true');p.add_argument('--attention-model',type=Path)
    p.add_argument('--attention-source',choices=['esense','personal'],default='esense')
    p.add_argument('--allow-origin',action='append',default=[]);p.add_argument('--record-dir',type=Path,default=ROOT/'recordings');args=p.parse_args()
    if args.list_ports:print(json.dumps(list_ports(),ensure_ascii=False,indent=2));return
    if args.port=='auto':
        ports=list_ports();matching=[x for x in ports if x['vid']==0x10c4 and x['pid']==0xea60]
        if len(matching)!=1:p.error('Cannot uniquely select CP2102; use --list-ports then --port COMx or /dev/ttyUSBx')
        args.port=matching[0]['port']
    if args.attention_source=='personal' and not args.attention_model:p.error('--attention-source personal requires --attention-model')
    ATTENTION_SOURCE=args.attention_source;ALLOWED_ORIGINS=set(args.allow_origin)
    monitor=Monitor(args.port,args.record_dir)
    from model_adapter import ModelWorker
    threading.Thread(target=ModelWorker(monitor,args.attention_model).run,daemon=True).start()
    threading.Thread(target=monitor.run,daemon=True).start()
    try:app.run(host='127.0.0.1',port=args.http_port,threaded=True,use_reloader=False)
    finally:monitor.recorder.stop()
if __name__=='__main__':main()
