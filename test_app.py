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
