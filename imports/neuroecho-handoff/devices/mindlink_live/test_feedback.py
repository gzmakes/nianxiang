import unittest,time
import numpy as np
from app import Monitor
from model_adapter import PublicModel
class FeedbackChecks(unittest.TestCase):
 def test_vendor_invalid_zero_stale(self):
  m=Monitor('unused');now=time.monotonic();m.last=m.qt=now;m.q=0
  m.vendor={'attention':75,'meditation':0};m.vendor_times={'attention':now,'meditation':now}
  self.assertEqual(m.vendor_values(now),{'attention':75,'meditation':None})
  m.q=25;self.assertIsNone(m.vendor_values(now)['attention'])
  m.q=0;self.assertIsNone(m.vendor_values(now+3)['attention'])
 def test_model_stale_and_contact(self):
  m=Monitor('unused');now=time.monotonic();m.last=m.qt=now;m.q=0
  m.model_result={'scores':[.2,.3,.5],'monotonic':now-5,'reasons':[]}
  self.assertIsNone(m.model_snapshot(now)['scores'])
  m.model_result['monotonic']=now;m.q=200
  self.assertIsNone(m.model_snapshot(now)['scores'])
 def test_frozen_model_qc(self):
  model=PublicModel();x=100*np.sin(np.arange(2048)*2*np.pi*10/512)
  s=model.predict(x,0);self.assertAlmostEqual(sum(s['scores']),1)
  self.assertIsNone(model.predict(x,200)['scores'])
  self.assertIsNone(model.predict(x*100,0)['scores'])
  self.assertEqual(model.bundle['labels'],['Eyes-closed rest','Medium arithmetic','Hard arithmetic'])
if __name__=='__main__':unittest.main()
