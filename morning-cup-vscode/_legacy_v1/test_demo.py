import tempfile
import unittest
from pathlib import Path
from demo_server import configure_demo
from app import app

class DemoTests(unittest.TestCase):
    def test_sessions_are_isolated_and_real_upload_blocked(self):
        old=dict(app.config)
        try:
            with tempfile.TemporaryDirectory() as d:
                configure_demo(d)
                one, two=app.test_client(),app.test_client()
                first=one.get('/api/state',base_url='https://demo.example').json
                self.assertTrue(first['public_demo'])
                c=first['config']; c['name']='Visitor one'
                self.assertEqual(one.post('/api/config',json=c,base_url='https://demo.example',headers={'Origin':'https://demo.example'}).status_code,200)
                self.assertEqual(one.get('/api/state',base_url='https://demo.example').json['config']['name'],'Visitor one')
                self.assertNotEqual(two.get('/api/state',base_url='https://demo.example').json['config']['name'],'Visitor one')
                self.assertEqual(len(list(Path(d).glob('*.db'))),2)
                self.assertEqual(one.post('/api/upload',json={},base_url='https://demo.example').status_code,403)
                self.assertEqual(one.post('/api/start-real',json={},base_url='https://demo.example').status_code,403)
                self.assertEqual(one.post('/api/config',json=c,base_url='https://demo.example',headers={'Origin':'https://evil.example'}).status_code,403)
        finally:
            app.config.clear();app.config.update(old)

if __name__=='__main__':unittest.main()
