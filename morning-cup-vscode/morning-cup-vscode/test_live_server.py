import unittest
from app import app

class LiveServerTests(unittest.TestCase):
    def setUp(self):
        self.old=app.config['LIVE_SERVER']; app.config['LIVE_SERVER']=True
        self.client=app.test_client()
    def tearDown(self):
        app.config['LIVE_SERVER']=self.old
    def test_preflight_allowed_only_for_local_editor(self):
        for origin in ['http://127.0.0.1:5500','http://localhost:5500']:
            r=self.client.options('/api/forecast',headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'Content-Type'})
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.headers['Access-Control-Allow-Origin'],origin)
        r=self.client.options('/api/forecast',headers={'Origin':'https://elsewhere.example'})
        self.assertNotIn('Access-Control-Allow-Origin',r.headers)
        r=self.client.post('/api/forecast',json={},headers={'Origin':'https://elsewhere.example'})
        self.assertEqual(r.status_code,403)
    def test_disabled_by_default_and_files_resolve(self):
        app.config['LIVE_SERVER']=False
        r=self.client.post('/api/forecast',json={},headers={'Origin':'http://127.0.0.1:5500'})
        self.assertEqual(r.status_code,403)
        self.assertEqual(self.client.get('/').status_code,302)
        with self.client.get('/static/index.html') as response:
            self.assertIn(b'./style.css',response.data)
        for path in ['style.css','app.js','area.js','setup.js','shop-editor.js']:
            with self.client.get('/static/'+path) as response:
                self.assertEqual(response.status_code,200)

if __name__=='__main__':unittest.main()
