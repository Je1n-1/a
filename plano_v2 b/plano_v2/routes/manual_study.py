from flask import Blueprint, request
from routes.api import run, body
from services import core, manual_study as study, manual_catalog, curriculum_workspace as workspace, focus_tracking

manual_study = Blueprint('manual_study',__name__,url_prefix='/api/manual-study')


def execute(scope, operation):
    values=body()
    if not isinstance(values,dict):
        return {'error':'Informe um objeto válido.'},400
    def perform(conn):
        conn.execute('BEGIN IMMEDIATE')
        if not values.get('operation_key'):
            raise core.DomainError('Identificador da operação ausente. Reabra o formulário.')
        try:
            return workspace.repeatable(conn,'manual:'+scope,values,lambda:operation(conn,values))
        except focus_tracking.FocusTrackingError as error:
            raise core.DomainError(str(error),error.status,error.code) from error
    return run(perform)


@manual_study.get('/today')
def today(): return run(study.today)


@manual_study.get('/catalog')
def catalog(): return run(lambda conn:{'items':manual_catalog.catalog(conn)})


@manual_study.get('/choices')
def choices(): return run(lambda conn:study.choices(conn,request.args))


@manual_study.get('/focus/active')
def active(): return run(study.active)


@manual_study.post('/focus')
def start(): return execute('start',study.start)


@manual_study.get('/focus/<int:ident>')
def focus(ident): return run(lambda conn:study.snapshot(conn,ident))


@manual_study.post('/focus/<int:ident>/<action>')
def action(ident,action):
    if action not in ('pause','resume','finish'):
        return {'error':'Ação não encontrada.'},404
    return execute(f'{ident}:{action}',lambda conn,values:study.finish(conn,ident,values) if action=='finish' else study.change_state(conn,ident,values,action))


@manual_study.put('/focus/<int:ident>/note')
def note(ident): return execute(f'{ident}:note',lambda conn,values:study.save_note(conn,ident,values))


@manual_study.post('/sessions')
def record(): return execute('record',study.manual_entry)


@manual_study.get('/sessions/<int:ident>')
def session(ident): return run(lambda conn:study.session_detail(conn,ident))


@manual_study.post('/sessions/<int:ident>/feedback')
def feedback(ident): return execute(f'{ident}:feedback',lambda conn,values:study.feedback(conn,ident,values))
