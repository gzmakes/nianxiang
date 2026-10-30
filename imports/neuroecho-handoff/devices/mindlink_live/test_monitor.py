import unittest,time
import numpy as np
from app import Parser,powers,Monitor,FS

def packet(p):return b'\xaa\xaa'+bytes([len(p)])+p+bytes([(~sum(p))&255])
def feed_wave(m,x,start=None):
 start=m.started+1 if start is None else start
 for i in range(0,len(x),512):
  vals=x[i:i+512];events=[[(2,b'\x00')]]+ [[(128,int(v).to_bytes(2,'big',signed=True))] for v in vals]
  m.ingest(events,now=start+(i+len(vals))/512)
 m.connected=True
 return start+len(x)/512
class Checks(unittest.TestCase):
 def test_fragment_signed_checksum(self):
  p=Parser();frame=packet(b'\x80\x02\xff\x9c');self.assertEqual(p.feed(frame[:3]),[])
  rows=p.feed(frame[3:]);self.assertEqual(int.from_bytes(rows[0][0][1],'big',signed=True),-100)
  bad=frame[:-1]+bytes([frame[-1]^1]);self.assertEqual(p.feed(bad+frame),[None]+rows);self.assertEqual(p.bad,1)
 def test_alpha_power(self):
  x=100*np.sin(2*np.pi*10*np.arange(FS*4)/FS);v=powers(x)
  self.assertEqual(int(np.argmax(v)),2);self.assertAlmostEqual(v[2],10*np.log10(5000),places=1)
 def test_gap_preserves_history_and_recovers(self):
  m=Monitor('unused');x=100*np.sin(np.arange(FS*2)*2*np.pi*10/FS)
  now=feed_wave(m,x);old=list(m.display);m.reset_segment('bad_packet',now+.01)
  self.assertEqual(list(m.display)[:len(old)],old);self.assertEqual(len(m.raw),0)
  now=feed_wave(m,x,now+.1);s=m.snapshot(now)
  self.assertGreater(len(s['raw']),2048);self.assertIn(None,s['raw']);self.assertTrue(all(b>a for a,b in zip(s['times'],s['times'][1:])))
 def test_noise_masks_only_local_span(self):
  m=Monitor('unused');x=np.round(100*np.sin(np.arange(FS*6)*2*np.pi*10/FS)).astype(int);x[1500]=3000
  now=feed_wave(m,x);s=m.snapshot(now)
  self.assertEqual(s['raw_original'][1500],3000);self.assertIsNone(s['raw'][1500])
  self.assertEqual(len(m.raw),len(x));self.assertIsNotNone(s['raw'][-1]);self.assertIsNotNone(s['envelope'][-1])
 def test_rms_settles(self):
  m=Monitor('unused');x=np.round(100*np.sin(2*np.pi*10*np.arange(FS*6)/FS)).astype(int)
  now=feed_wave(m,x);s=m.snapshot(now)
  self.assertTrue(all(v is None for v in s['envelope'][:255]));self.assertAlmostEqual(np.mean(s['envelope'][-512:]),100/np.sqrt(2),delta=2)
 def test_outage_scrolls_out_old_wave(self):
  m=Monitor('unused');now=feed_wave(m,[10]*1024);m.reset_segment('timeout',now+1)
  self.assertGreater(len(m.snapshot(now+2)['raw']),0);self.assertEqual(m.snapshot(now+12)['raw'],[])
 def test_corrupt_mid_chunk_never_future(self):
  m=Monitor('unused');now=m.started+2
  raw=[[(128,b'\x00\x0a')]]
  m.ingest([[(2,b'\x00')]]+raw*100+[None,None,None]+raw*412,now)
  s=m.snapshot(now)
  self.assertLessEqual(max(s['times']),2)
  self.assertTrue(all(b>a for a,b in zip(s['times'],s['times'][1:])))
 def test_nonraw_packets_do_not_hide_raw_gap(self):
  m=Monitor('unused');now=feed_wave(m,[10]*512);old=m.generation
  m.ingest([[(2,b'\x00'),(4,b'\x46')]],now+1.1)
  self.assertGreater(m.generation,old);self.assertEqual(len(m.raw),0)
  m.ingest([[(2,b'\x00')]]+[[(128,b'\x00\x0a')]]*512,now+1.2)
  s=m.snapshot(now+1.2)
  self.assertTrue(all(b>a for a,b in zip(s['times'],s['times'][1:])))
  self.assertLessEqual(max(s['times']),s['elapsed'])
 def test_artifact_invalidates_predictions_until_new_inference(self):
  m=Monitor('unused');now=feed_wave(m,[10]*512)
  m.model_result={'scores':[.1,.2,.7],'monotonic':now}
  m.personal_result={'value':90,'valid':True,'monotonic':now}
  m.ingest([[(128,(3000).to_bytes(2,'big',signed=True))]],now+.01)
  self.assertIsNone(m.model_result);self.assertIsNone(m.personal_result)
 def test_burst_and_corruption_timestamps(self):
  import random
  r=random.Random(42);m=Monitor('test');now=m.started
  for step in range(200):
   now+=r.choice([.001,.02,.05,.1,.2,1.2]);n=r.randrange(0,150)
   events=[[(128,b'\x00\x0a')]]*n
   for _ in range(r.randrange(4)):events.insert(r.randrange(len(events)+1),None)
   if r.random()<.3:events.insert(0,[(2,b'\x00')])
   m.ingest(events,now);d=list(m.display)
   self.assertTrue(all(b[0]>a[0] for a,b in zip(d,d[1:])),step)
   self.assertLessEqual(d[-1][0],now-m.started+1e-6)
if __name__=='__main__':unittest.main()
