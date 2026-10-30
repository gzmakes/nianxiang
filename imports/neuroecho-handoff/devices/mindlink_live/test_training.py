"""Synthetic engineering fixture only; not a real-person performance estimate."""
import unittest,tempfile,json,contextlib,io
from pathlib import Path
import numpy as np
from train_personal import train,windows
from model_adapter import PersonalModel
class Training(unittest.TestCase):
 def test_session_holdout_roundtrip_and_label_scope(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);paths=[]
   for i,server in enumerate(['day1','day2','day3','day3']):
    path=root/f'run{i}.jsonl';paths.append(path)
    t=np.arange(512*80)/512
    x=np.round(70*np.sin(2*np.pi*np.where(t<40,10,20)*t)).astype(int)
    events=[{'type':'metadata','server_session_id':server},
      {'type':'marker','label':'focus','t':0},{'type':'marker','label':'mind_wandering','t':40},
      {'type':'samples','rows':[[float(tt),int(xx),0,False,0,k] for k,(tt,xx) in enumerate(zip(t,x))]}]
    path.write_text('\n'.join(json.dumps(e) for e in events))
   with contextlib.redirect_stdout(io.StringIO()):b=train(paths,'run2',root/'model.joblib')
   self.assertEqual(b['evaluation']['test_server_session'],'day3')
   self.assertEqual(b['evaluation']['train_windows'],b['evaluation']['test_windows'])
   p=PersonalModel(root/'model.joblib');self.assertTrue(p.predict(x[:2048],0)['valid'])
   # Looking at a fixation target is not silently treated as a focus label.
   text=paths[0].read_text().replace('"focus"','"fixation"').replace('"mind_wandering"','"thinking"')
   paths[0].write_text(text);self.assertEqual(windows(paths[0])[1],[])
 def test_insufficient_sessions_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'one.jsonl';p.write_text(json.dumps({'type':'metadata','server_session_id':'one'}))
   with self.assertRaisesRegex(ValueError,'independent'):train([p],'one',Path(d)/'model.joblib')
if __name__=='__main__':unittest.main()
