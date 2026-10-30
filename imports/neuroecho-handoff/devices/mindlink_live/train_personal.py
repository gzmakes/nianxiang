"""Train from independently self-labelled recordings; never use eSense as labels.
Usage: python train_personal.py --recordings recordings --test-session FILE_STEM --output personal.joblib
At least three distinct server sessions required. Test session is held out in full.
"""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
import argparse,json,hashlib,datetime
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score,confusion_matrix
from model_adapter import quality_check,preprocess,extract_features
from src.config import CONFIG

def windows(path):
    data=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
    meta=next(x for x in data if x.get('type')=='metadata')
    rows=[r for e in data if e.get('type')=='samples' for r in e['rows']]
    marks=sorted([e for e in data if e.get('type')=='marker'],key=lambda e:e['t'])
    if not rows:return meta,[]
    rows.sort(key=lambda x:x[0]);out=[]
    for i in range(0,len(rows)-2048+1,1024):
        w=rows[i:i+2048];start,end=w[0][0],w[-1][0]
        before=[e for e in marks if e['t']<=start]
        label=before[-1]['label'] if before else None
        if label not in ('focus','mind_wandering'):continue
        if start-before[-1]['t']<4:continue # transition guard; discard clicking period
        if any(start<e['t']<=end for e in marks):continue
        if len({r[4] for r in w})!=1 or any(r[3] for r in w):continue
        if any(len(r)<6 for r in w) or any(b[5]-a[5]!=1 for a,b in zip(w,w[1:])):continue
        if any(b[0]<=a[0] or b[0]-a[0]>.25 for a,b in zip(w,w[1:])):continue
        x=np.asarray([r[1] for r in w],dtype=float);q=max(r[2] for r in w)
        good,_=quality_check(x,q,CONFIG)
        if not good:continue
        out.append({'label':label,**extract_features(preprocess(x,CONFIG),512)})
    return meta,out

def train(paths,test_session,output):
    records=[];features=None;source=[];servers=set();test_server=None
    for path in paths:
        meta,rows=windows(path);server=meta['server_session_id'];servers.add(server)
        if path.stem==test_session:test_server=server
        for row in rows:row.update(recording=path.stem,server=server)
        records+=rows;source.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'usable_windows':len(rows)})
    if len(servers)<3:raise ValueError('Need >=3 independent server sessions; restarting recording within one server run is not independent')
    if test_server is None:raise ValueError('test-session file stem not found')
    df=pd.DataFrame(records)
    if df.empty:raise ValueError('No eligible independently labelled windows')
    # All recordings belonging to the held-out server run are excluded from fitting.
    tr=df[df.server!=test_server];te=df[df.server==test_server]
    labels=['focus','mind_wandering']
    for name,part in [('train',tr),('test',te)]:
        if any((part.label==label).sum()<10 for label in labels):raise ValueError(name+' needs >=10 valid windows per class')
    features=[k for k in extract_features(np.ones(2048))]
    model=make_pipeline(StandardScaler(),LogisticRegression(C=1,class_weight='balanced',max_iter=2000,random_state=42))
    model.fit(tr[features],tr.label);pred=model.predict(te[features]);ba=float(balanced_accuracy_score(te.label,pred))
    evaluation={'balanced_accuracy':ba,'baseline_balanced_accuracy':.5,'confusion_matrix':confusion_matrix(te.label,pred,labels=labels).tolist(),
                'labels':labels,'test_server_session':test_server,'train_windows':len(tr),'test_windows':len(te),
                'split':'entire independent server session held out; no test refit or tuning',
                'warning':'one held-out session; overlapping windows are not independent trials; scores uncalibrated; not validated on new people'}
    bundle={'kind':'personal_attention_v1','model_id':hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()[:16],
            'target':'self-reported focus versus mind wandering','trained_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'config':CONFIG,'features':features,'model':model,'evaluation':evaluation,'sources':source}
    output.parent.mkdir(parents=True,exist_ok=True);joblib.dump(bundle,output)
    report={k:v for k,v in bundle.items() if k!='model'}
    output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evaluation,ensure_ascii=False,indent=2));return bundle
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--recordings',type=Path,required=True);p.add_argument('--test-session',required=True);p.add_argument('--output',type=Path,default=Path('personal.joblib'));a=p.parse_args()
    train(sorted(a.recordings.glob('*.jsonl')),a.test_session,a.output)
