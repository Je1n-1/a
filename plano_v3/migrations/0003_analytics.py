"""Backfill congelado da migration 0003; checksum inclui este arquivo."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def migrate(conn):
    zone=ZoneInfo('America/Sao_Paulo')
    for raw in conn.execute('SELECT * FROM study_sessions').fetchall():
        session=dict(raw)
        days={}
        def add(day,kind,seconds):
            days.setdefault(day,{'focus':0,'break':0})[kind]+=seconds
        if session['source']=='timer':
            intervals=conn.execute('SELECT kind,started_at,ended_at FROM timer_intervals WHERE timer_id=?',(session['timer_id'],)).fetchall()
        elif session['started_at']:
            intervals=[('focus',session['started_at'],session['ended_at'])]
        else:
            intervals=[]
            add(session['local_date'],'focus',session['effective_seconds'])
        for kind,start,end in intervals:
            cursor=datetime.fromisoformat(start).astimezone(timezone.utc)
            stop=datetime.fromisoformat(end).astimezone(timezone.utc) if end else None
            if stop is None or stop<cursor:
                raise RuntimeError('Sessão histórica com intervalo inválido; backfill interrompido.')
            while cursor<stop:
                day=cursor.astimezone(zone).date()
                midnight=datetime.combine(day+timedelta(days=1),time(),zone).astimezone(timezone.utc)
                boundary=min(stop,midnight)
                add(day.isoformat(),kind,int((boundary-cursor).total_seconds()))
                cursor=boundary
        if sum(d['focus'] for d in days.values())!=session['effective_seconds'] or sum(d['break'] for d in days.values())!=session['break_seconds']:
            raise RuntimeError('Rateio não confere com a sessão; migration revertida.')
        conn.executemany('INSERT INTO session_days VALUES (?,?,?,?)',[(session['id'],day,v['focus'],v['break']) for day,v in days.items()])
