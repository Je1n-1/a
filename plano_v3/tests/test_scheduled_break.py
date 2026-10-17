from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app import create_app
from tracker import db


class ScheduledBreak(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.db'
        db.initialize(self.path)
        self.client = create_app(self.path).test_client()

    def at(self, time, route, values, status=200):
        with patch('tracker.timer.now', return_value='2026-10-14T' + time + '+00:00'):
            response = self.client.post('/api' + route, json=values)
        self.assertEqual(response.status_code, status, response.json)
        return response.json

    def start(self):
        return self.at('17:00:00', '/timer', {'operation_key':'test', 'title':'Estudo'})

    def test_deadline_never_resumes_or_truncates_actual_pause(self):
        t = self.start()
        t = self.at('18:00:00', f'/timer/{t["id"]}/break-plan', {'version':t['version'], 'minutes':60})
        self.assertEqual(t['status'], 'paused')
        self.assertEqual(t['break_until'], '2026-10-14T19:00:00+00:00')
        with patch('tracker.timer.now', return_value='2026-10-14T19:30:00+00:00'):
            loaded = create_app(self.path).test_client().get('/api/timer').json
        self.assertEqual((loaded['status'], loaded['effective_seconds'], loaded['break_seconds'], loaded['rest_seconds']), ('paused',3600,0,5400))
        self.assertEqual(loaded['break_until'], t['break_until'])
        t = self.at('19:30:00', f'/timer/{t["id"]}/resume', {'version':t['version']})
        self.assertIsNone(t['break_until'])
        t = self.at('20:15:00', f'/timer/{t["id"]}/finish', {'version':t['version']})
        self.assertEqual((t['effective_seconds'],t['break_seconds'],t['rest_seconds']), (6300,0,5400))
        db.diagnostics(self.path)

    def test_change_or_clear_deadline_keeps_same_pause(self):
        t = self.start()
        t = self.at('17:01:00', f'/timer/{t["id"]}/pause', {'version':t['version']})
        original = t['open_interval']['id']
        t = self.at('17:02:00', f'/timer/{t["id"]}/break-plan', {'version':t['version'], 'return_at':'2026-10-14T16:00'})
        self.assertEqual(t['break_until'], '2026-10-14T19:00:00+00:00')
        self.at('17:03:00', f'/timer/{t["id"]}/break-clear', {'version':1},409)
        t = self.at('17:04:00', f'/timer/{t["id"]}/break-clear', {'version':t['version']})
        self.assertIsNone(t['break_until'])
        self.assertNotEqual(t['open_interval']['id'], original)
        self.assertTrue(t['rest_active'])
        self.assertEqual((t['status'],t['break_seconds'],t['rest_seconds']), ('paused',60,120))

    def test_switches_preserve_short_pauses_and_rest_without_overlap(self):
        t = self.start()
        for stamp, action, extra in [
            ('17:01:00', 'pause', {}),
            ('17:02:00', 'break-plan', {'minutes': 1}),
            ('17:04:00', 'break-plan', {'minutes': 60}),
            ('17:05:00', 'pause', {}),
            ('17:06:00', 'resume', {}),
            ('17:07:00', 'finish', {}),
        ]:
            t = self.at(stamp, f'/timer/{t["id"]}/{action}', {'version': t['version'], **extra})
        self.assertEqual((t['effective_seconds'], t['break_seconds'], t['rest_seconds'], t['total_seconds']), (120,120,180,420))
        s = self.client.get(f'/api/sessions/{t["session_id"]}').json
        self.assertEqual(s['rest_seconds'], 180)
        self.assertEqual(sum(d['rest_seconds'] for d in s['daily_allocation']), 180)
        report = self.client.get('/api/analytics?start=2026-10-14&end=2026-10-14').json
        self.assertEqual(report['summary']['period']['rest_seconds'], 180)
        self.assertEqual(report['history']['rows'][0]['rest_seconds'], 180)
        self.assertFalse(t['rest_active'])
        self.assertIsNone(t['break_until'])

    def test_rest_crossing_midnight_csv_and_corrections(self):
        import csv
        import io
        t = self.at('02:57:00', '/timer', {'operation_key': 'midnight'})
        for stamp, action, extra in [('02:58:00','pause',{}), ('02:59:00','break-plan',{'minutes':1}), ('03:01:00','resume',{}), ('03:02:00','finish',{})]:
            t = self.at(stamp, f'/timer/{t["id"]}/{action}', {'version': t['version'], **extra})
        ident = t['session_id']
        s = self.client.get(f'/api/sessions/{ident}').json
        self.assertEqual(s['daily_allocation'], [
            {'date':'2026-10-13','effective_seconds':60,'break_seconds':60,'rest_seconds':60},
            {'date':'2026-10-14','effective_seconds':60,'break_seconds':0,'rest_seconds':60},
        ])
        f = '?start=2026-10-14&end=2026-10-14'
        r = self.client.get('/api/analytics'+f).json['history']['rows'][0]
        self.assertEqual((r['effective_seconds'],r['break_seconds'],r['rest_seconds'],r['total_rest_seconds']), (60,0,60,120))
        rows = list(csv.reader(io.StringIO(self.client.get('/api/analytics/export.csv'+f).text.lstrip('\ufeff')), delimiter=';'))
        self.assertEqual((rows[1][9],rows[1][10],rows[1][19]), ('120','0','60'))
        keep = self.client.patch(f'/api/sessions/{ident}', json={'version':1,'operation_key':'keep','reason':'Nota','note':'Conferido'} )
        self.assertEqual(keep.status_code, 200, keep.json)
        self.assertEqual(keep.json['rest_seconds'], 120)
        replace = self.client.patch(f'/api/sessions/{ident}', json={'version':2,'operation_key':'replace','reason':'Corrigir duração','mode':'duration','date':'2026-10-13','duration_seconds':300})
        self.assertEqual(replace.status_code, 200, replace.json)
        self.assertEqual((replace.json['break_seconds'],replace.json['rest_seconds']), (0,0))
        audit = self.client.get(f'/api/sessions/{ident}/corrections').json
        self.assertEqual(audit[0]['old_values']['rest_seconds'], 120)
        db.diagnostics(self.path)

    def test_invalid_schedule_does_not_pause(self):
        t = self.start()
        for data in [{'minutes':0},{'minutes':True},{'minutes':1441},{'minutes':1.5},{'return_at':'2026-10-14T12:00'},{'return_at':'bad'},{'minutes':1,'return_at':'2026-10-14T16:00'}]:
            self.at('17:01:00', f'/timer/{t["id"]}/break-plan', {'version':t['version'],**data},400)
        loaded = self.client.get('/api/timer').json
        self.assertEqual((loaded['status'],loaded['version']), ('running',1))

    def test_migration_recognizes_open_scheduled_rest_preserving_old_columns(self):
        from upgrade import upgrade
        path = Path(self.tmp.name) / 'previous.db'
        with patch('tracker.db.versions', return_value=db.versions()[:5]):
            db.initialize(path)
        with db.transaction(path) as conn:
            conn.execute("INSERT INTO timers(title,status,started_at,operation_key,break_until) VALUES ('Aberto','paused','2026-10-14T17:00:00+00:00','old','2026-10-14T18:01:00+00:00')")
            conn.execute("INSERT INTO timer_intervals(timer_id,kind,started_at,ended_at) VALUES (1,'focus','2026-10-14T17:00:00+00:00','2026-10-14T17:01:00+00:00')")
            conn.execute("INSERT INTO timer_intervals(timer_id,kind,started_at) VALUES (1,'break','2026-10-14T17:01:00+00:00')")
        result = upgrade(path, Path(self.tmp.name) / 'backups')
        self.assertTrue(result['existing_rows_preserved'])
        self.assertEqual(result['applied'], ['0006_rest_time', '0007_projects'])
        with patch('tracker.timer.now', return_value='2026-10-14T17:10:00+00:00'):
            t = create_app(path).test_client().get('/api/timer').json
        self.assertEqual((t['effective_seconds'],t['break_seconds'],t['rest_seconds']), (60,0,540))
        self.assertTrue(t['rest_active'])

    def test_finish_cancel_and_recovery_constraints(self):
        t = self.start()
        self.at('01:01:00', f'/timer/{t["id"]}/break-plan', {'version':1,'minutes':10},409)
        t = self.at('17:01:00', f'/timer/{t["id"]}/break-plan', {'version':1,'minutes':10})
        t = self.at('17:02:00', f'/timer/{t["id"]}/cancel', {'version':t['version']})
        self.assertIsNone(t['break_until'])
        self.at('17:03:00', f'/timer/{t["id"]}/break-plan', {'version':t['version'],'minutes':10},409)
