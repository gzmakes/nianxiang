import unittest,time,tempfile,json
from pathlib import Path
from unittest.mock import patch
import app,transport
from core import Monitor
class API(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.monitor=Monitor('test',self.tmp.name);self.client=app.app.test_client()
 def tearDown(self):app.monitor.recorder.stop();self.tmp.cleanup()
 def test_valid_and_expiry(self):
  m=app.monitor;now=time.monotonic();m.connected=True;m.last=m.qt=now;m.q=0;m.vendor['attention']=65;m.vendor_times['attention']=now
  s=self.client.get('/api/v1/state').json;self.assertTrue(s['attention']['valid']);self.assertEqual(s['attention']['source'],'neurosky_esense')
  m.vendor_times['attention']=now-3;s=self.client.get('/api/v1/state').json;self.assertIsNone(s['attention']['value']);self.assertFalse(s['attention']['valid'])
 def test_personal_no_silent_fallback(self):
  s=self.client.get('/api/v1/state?source=personal').json
  self.assertEqual(s['attention']['source'],'personal_model');self.assertFalse(s['attention']['valid'])
  self.assertEqual(self.client.get('/api/v1/state?source=bogus').status_code,400)
 def test_record_marker_original(self):
  self.assertEqual(self.client.post('/api/v1/markers',json={'label':'focus'}).status_code,409)
  self.client.post('/api/v1/recording/start');self.client.post('/api/v1/markers',json={'label':'fixation'})
  m=app.monitor;m.ingest([[(2,b'\x00'),(128,(3000).to_bytes(2,'big',signed=True))]])
  p=m.recorder.path;self.client.post('/api/v1/recording/stop');events=[json.loads(x) for x in p.read_text().splitlines()]
  self.assertEqual([e['label'] for e in events if e['type']=='marker'],['fixation'])
  row=[e for e in events if e['type']=='samples'][0]['rows'][0];self.assertEqual(row[1],3000);self.assertTrue(row[3])
 def test_foreign_origin_blocked(self):
  self.assertEqual(self.client.post('/api/v1/recording/start',headers={'Origin':'https://unrelated.example'}).status_code,403)
 def test_sse_contract(self):
  r=self.client.get('/api/v1/events',buffered=False);chunk=next(r.response).decode();r.close()
  self.assertIn('event: metrics',chunk);self.assertIn('"api_version": "1.0"',chunk)
 def test_windows_serial_arguments(self):
  class Fake:
   def Serial(self,**kw):return kw
  with patch.object(transport,'serial',Fake()),patch.object(transport.os,'name','nt'):
   args=transport.open_serial('COM4')
  self.assertEqual(args['port'],'COM4');self.assertNotIn('exclusive',args)
if __name__=='__main__':unittest.main()
