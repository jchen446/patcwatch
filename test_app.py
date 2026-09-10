import unittest
from app import Detector

class DetectorTests(unittest.TestCase):
    def capture(self, *messages):
        return {'status':'OK','messages':[{'id':i,'text':t} for i,t in messages]}
    def test_baseline_change_duplicate_and_failure(self):
        d=Detector()
        self.assertEqual(d.read(self.capture(('a','one'),('b','two')))['decision'],'BASELINE')
        self.assertEqual(d.read(self.capture(('a','changed')))['decision'],'CHANGED')
        prior=dict(d.seen)
        self.assertEqual(d.read({'status':'UNAVAILABLE'})['decision'],'UNAVAILABLE')
        self.assertEqual(d.seen,prior)
        self.assertEqual(d.read(self.capture(('a','changed')))['decision'],'UNCHANGED')
        self.assertEqual(d.read(self.capture())['decision'],'UNCHANGED')
    def test_malformed_capture_is_atomic(self):
        d=Detector();d.read(self.capture(('a','one')));prior=dict(d.seen)
        with self.assertRaises(ValueError):d.read(self.capture(('a','changed'),('a','duplicate')))
        self.assertEqual(d.seen,prior)
    def test_untrusted_text_is_literal(self):
        d=Detector();d.read(self.capture(('a','one')))
        text='<script>fetch("https://example.com")</script>'
        self.assertIn(text,d.read(self.capture(('a',text)))['drafts'][0]['text'])

if __name__=='__main__':unittest.main()

class MonitorTests(unittest.TestCase):
    def test_restart_dedup_and_failure_preserves_success(self):
        import tempfile, json
        from pathlib import Path
        from patcwatch.server import Monitor
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'input.json'
            def write(text):source.write_text(json.dumps({'status':'OK','messages':[{'id':'x','text':text}]}))
            write('first');m=Monitor(source,root/'state');self.assertEqual(m.check()['status'],'BASELINE')
            write('second');self.assertEqual(len(m.check()['drafts']),1)
            m=Monitor(source,root/'state');self.assertEqual(m.check()['status'],'UNCHANGED');self.assertEqual(len(m.snapshot()['drafts']),1)
            success=m.snapshot()['last_success'];source.write_text('{broken')
            self.assertEqual(m.check()['status'],'UNAVAILABLE');self.assertEqual(m.snapshot()['last_success'],success)
            self.assertEqual(len(m.snapshot()['drafts']),1)
    def test_source_identity_cannot_reuse_state(self):
        import tempfile,json
        from pathlib import Path
        from patcwatch.server import Monitor
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a.json';a.write_text('{"status":"OK","messages":[]}')
            Monitor(a,root/'state').check()
            with self.assertRaises(ValueError):Monitor(root/'b.json',root/'state')
