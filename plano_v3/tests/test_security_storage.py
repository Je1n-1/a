import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from app import create_app
from tracker import db, storage
from upgrade import contents, verify_preserved, fingerprint


class SecurityStorage(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'test.db';db.initialize(self.path)
        self.client=create_app(self.path).test_client()

    def test_rejects_external_same_site_and_opaque_origins(self):
        for origin in ('https://example.org','null','https://localhost','http://localhost:5054','http://localhost@evil.test','http://localhost/path','http://localhost#fragment'):
            response=self.client.post('/api/courses',json={'name':'Injected'},headers={'Origin':origin})
            self.assertEqual(response.status_code,403,origin)
        for site in ('cross-site','same-site','none','unknown'):
            self.assertEqual(self.client.post('/api/courses',json={'name':'Injected'},headers={'Sec-Fetch-Site':site}).status_code,403)
        self.assertEqual(self.client.get('/api/courses').json,[])

    def test_local_origin_and_headerless_json_tools_remain_usable(self):
        for headers in ({},{'Origin':'http://localhost','Sec-Fetch-Site':'same-origin'}):
            self.assertEqual(self.client.post('/api/courses',json={'name':'Local'},headers=headers).status_code,200)

    def test_read_requests_and_host_are_also_protected(self):
        for headers in ({'Host':'evil.test'},{'Origin':'http://evil.test'}, {'Sec-Fetch-Site':'same-site'}, {'Referer':'http://localhost:9999/page'}):
            self.assertEqual(self.client.get('/api/diagnostics',headers=headers).status_code,403)
        self.assertEqual(self.client.get('/api/diagnostics',environ_overrides={'REMOTE_ADDR':'192.168.1.50'}).status_code,403)
        self.assertEqual(self.client.get('/',headers={'Sec-Fetch-Site':'none'}).status_code,200)

    def test_simple_forms_cannot_mutate_or_restore(self):
        for route,data in (('/api/courses',{'name':'Injected'}),('/api/backups/recover',{'confirmed':'true','file':(io.BytesIO(b'bad'),'bad.db')})):
            self.assertEqual(self.client.post(route,data=data).status_code,403)
        self.assertEqual(self.client.post('/api/backups/recover',headers={'X-Plano-Request':'1'},data={}).status_code,400)

    def test_security_headers_cache_and_no_cors(self):
        for route in ('/','/api/subjects','/missing'):
            response=self.client.get(route)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
            self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
            self.assertEqual(response.headers['X-Frame-Options'],'DENY')
            self.assertIn("script-src 'self'",response.headers['Content-Security-Policy'])
            self.assertNotIn('Access-Control-Allow-Origin',response.headers)
        self.assertEqual(self.client.options('/api/backups',headers={'Origin':'https://evil.test'}).status_code,403)

    def test_streamed_fingerprint_detects_values_and_preserves_new_columns(self):
        with db.transaction(self.path) as conn:
            conn.executemany('INSERT INTO courses(name,created_at) VALUES (?,?)',(('Curso '+str(i),'2026-10-30') for i in range(1000)))
        before=contents(self.path)
        self.assertNotIn('rows',before['courses'])
        self.assertEqual(before['courses']['count'],1000)
        with db.transaction(self.path) as conn:conn.execute('ALTER TABLE courses ADD COLUMN extra TEXT')
        verify_preserved(self.path,before)
        with db.transaction(self.path) as conn:conn.execute("UPDATE courses SET name='Modified' WHERE id=999")
        with self.assertRaisesRegex(RuntimeError,'courses'):verify_preserved(self.path,before)

    def test_hash_distinguishes_types_boundaries_and_row_order(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.execute('CREATE TABLE data(a,b)')
            hashes=[]
            for values in ((None,''),('',None),(1,'1'),('1',1),('ab','c'),('a','bc'),(b'a','b'),('a','b')):
                conn.execute('DELETE FROM data');conn.execute('INSERT INTO data VALUES (?,?)',values)
                hashes.append(fingerprint(conn,'data',['a','b'])['sha256'])
            self.assertEqual(len(set(hashes)),len(hashes))

    def test_recovery_still_preserves_every_value(self):
        with db.transaction(self.path) as conn:conn.execute("INSERT INTO courses(name,created_at) VALUES ('Preservar','2026-10-30')")
        before=contents(self.path);backup=Path(self.temp.name)/'copy.db';storage.copy_database(self.path,backup)
        with backup.open('rb') as upload:restored=storage.recover_copy(self.path,upload)
        self.assertEqual(contents(Path(restored['path'])),before)
        self.assertEqual(contents(self.path),before)
