"""Frozen public task model + optional personal, independently labelled attention model."""
import sys,time
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from core import powers
ROOT=Path(__file__).parent/'public_model';sys.path.insert(0,str(ROOT))
from src.preprocessing import quality_check,preprocess
from src.features import extract_features
class PublicModel:
    def __init__(self):self.bundle=joblib.load(ROOT/'best.joblib')
    def predict(self,x,quality):
        good,reasons=quality_check(x,quality,self.bundle['config'])
        if not good:return {'scores':None,'reasons':reasons}
        f=extract_features(preprocess(x,self.bundle['config']),512)
        scores=self.bundle['model'].predict_proba(pd.DataFrame([f])[self.bundle['features']])[0]
        full=np.zeros(3);full[np.asarray(self.bundle['model'].classes_,dtype=int)]=scores
        return {'scores':full.tolist(),'reasons':[]}
class PersonalModel:
    def __init__(self,path):
        self.bundle=joblib.load(path)
        if self.bundle.get('kind')!='personal_attention_v1':raise ValueError('Not a personal_attention_v1 bundle')
        if self.bundle['config']['fs']!=512:raise ValueError('Model sample rate differs')
        self.meta={k:self.bundle.get(k) for k in ['kind','model_id','target','evaluation','trained_at']}
    def predict(self,x,quality):
        good,reasons=quality_check(x,quality,self.bundle['config'])
        if not good:return {'value':None,'valid':False,'reason':','.join(reasons)}
        f=extract_features(preprocess(x,self.bundle['config']),512)
        s=self.bundle['model'].predict_proba(pd.DataFrame([f])[self.bundle['features']])[0]
        index=list(self.bundle['model'].classes_).index('focus')
        return {'value':float(s[index]*100),'valid':True,'reason':None,'meaning':'personal self-reported focus model score; uncalibrated'}
class ModelWorker:
    def __init__(self,monitor,personal_path=None):self.m=monitor;self.personal_path=personal_path
    def run(self):
        m=self.m;model=None;personal=None
        try:model=PublicModel()
        except Exception as e:
            with m.lock:m.model_error=str(e)
        if self.personal_path:
            try:
                personal=PersonalModel(self.personal_path)
                with m.lock:m.personal_meta=personal.meta
            except Exception as e:
                with m.lock:m.personal_meta={'error':str(e)}
        seen=(-1,-1);model_seen=(-1,-1)
        while True:
            time.sleep(.1)
            with m.lock:
                key=(m.generation,m.segment//512)
                if len(m.raw)<2048 or key==seen or time.monotonic()-m.last>=1:continue
                seen=key;gen=m.generation;sample_total=m.total;model_key=(gen,m.segment//1024)
                x=np.asarray(list(m.raw)[-2048:],dtype=float);q=max(list(m.raw_q)[-2048:])
                masked=any(list(m.raw_mask)[-2048:]);mask_count=m.masked_total;end=m.last
            # Masked samples are never concatenated across gaps or imputed for analysis.
            clean=not masked and q==0
            heat={'t':end-m.started,'db':powers(x) if clean else None}
            result=None;custom=None;error=None
            if model_key!=model_seen:
                model_seen=model_key
                if model:
                    try:result=model.predict(x,q) if clean else {'scores':None,'reasons':['artifact_or_contact']}
                    except Exception as e:result={'scores':None,'reasons':['inference_error']};error=str(e)
                if personal:
                    try:custom=personal.predict(x,q) if clean else {'value':None,'valid':False,'reason':'artifact_or_contact'}
                    except Exception as e:custom={'value':None,'valid':False,'reason':str(e)}
            with m.lock:
                if gen!=m.generation or mask_count!=m.masked_total:continue
                m.heat.append(heat)
                if result is not None:
                    m.model_error=error;result.update(t=end-m.started,monotonic=end,sample_total=sample_total)
                    m.model_result=result;m.model_history.append({k:v for k,v in result.items() if k!='monotonic'})
                if custom is not None:custom.update(monotonic=end);m.personal_result=custom
