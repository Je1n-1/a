from flask import Blueprint, request
from routes.api import run, body
from services import core, curriculum_workspace as workspace, curriculum_equivalences as equivalences, manual_catalog

curriculum_workspace = Blueprint('curriculum_workspace', __name__, url_prefix='/api/curriculum-workspace')


@curriculum_workspace.get('/catalog')
def catalog():
    return run(lambda conn:{'items':manual_catalog.catalog(conn,request.args)})


def execute(ident, action, fn):
    values = body()
    if not isinstance(values, dict):
        return {'error':'Informe um objeto válido.'},400
    def operation(conn):
        conn.execute('BEGIN IMMEDIATE')
        return workspace.repeatable(conn, f'{ident}:{action}', values, lambda: fn(conn,values))
    return run(operation)


@curriculum_workspace.route('/<int:ident>',methods=['GET','PATCH'])
def detail(ident):
    if request.method == 'GET':
        return run(lambda conn:workspace.detail(conn,ident))
    return execute(ident,'save',lambda conn,values:workspace.save(conn,ident,values))


@curriculum_workspace.route('/<int:ident>/completion',methods=['GET','POST'])
def completion(ident):
    if request.method=='GET':
        return run(lambda conn:workspace.completion_preview(conn,ident))
    return execute(ident,'complete',lambda conn,values:workspace.save(conn,ident,{**values,'academic_status':'completed'}))


@curriculum_workspace.post('/<int:ident>/contents')
def content_create(ident):
    return execute(ident,'create-content',lambda conn,values:workspace.save_topic(conn,ident,values))


@curriculum_workspace.post('/<int:ident>/contents/order')
def content_order(ident):
    return execute(ident,'order-content',lambda conn,values:workspace.reorder(conn,ident,values))


@curriculum_workspace.patch('/<int:ident>/contents/<int:topic_id>')
def content_edit(ident,topic_id):
    return execute(ident,f'edit-content:{topic_id}',lambda conn,values:workspace.save_topic(conn,ident,values,topic_id))


@curriculum_workspace.route('/<int:ident>/contents/<int:topic_id>/removal',methods=['GET','POST'])
def content_remove(ident,topic_id):
    if request.method=='GET':
        return run(lambda conn:workspace.topic_removal_preview(conn,ident,topic_id))
    return execute(ident,f'remove-content:{topic_id}',lambda conn,values:workspace.remove_topic(conn,ident,topic_id,values))


@curriculum_workspace.post('/<int:ident>/contents/<int:topic_id>/restore')
def content_restore(ident,topic_id):
    return execute(ident,f'restore-content:{topic_id}',lambda conn,values:workspace.restore_topic(conn,ident,topic_id))


@curriculum_workspace.get('/<int:ident>/equivalences')
def candidates(ident):
    return run(lambda conn:equivalences.candidates(conn,ident))


@curriculum_workspace.get('/formations/<int:formation_id>/equivalences')
def formation_equivalences(formation_id):
    return run(lambda conn:equivalences.formation_overview(conn,formation_id))


@curriculum_workspace.post('/formations/<int:formation_id>/equivalences/preview')
def formation_equivalence_preview(formation_id):
    values = body()
    if not isinstance(values, dict):
        return {'error':'Informe um objeto válido.'},400
    return run(lambda conn:equivalences.formation_preview(conn,formation_id,values))


@curriculum_workspace.post('/formations/<int:formation_id>/equivalences/confirm')
def formation_equivalence_confirm(formation_id):
    return execute(f'formation:{formation_id}','equivalences',
                   lambda conn,values:equivalences.formation_apply(conn,formation_id,values))


@curriculum_workspace.route('/<int:ident>/equivalences/<int:other>',methods=['GET','POST'])
def link(ident,other):
    if request.method=='GET':
        return run(lambda conn:equivalences.compare(conn,ident,other))
    return execute(ident,f'link:{other}',lambda conn,values:equivalences.link(conn,ident,other,values))


@curriculum_workspace.post('/<int:ident>/equivalences/<int:other>/decision')
def separate(ident,other):
    return execute(ident,f'decision:{other}',lambda conn,values:equivalences.decide_separate(conn,ident,other,values))


@curriculum_workspace.route('/<int:ident>/unlink',methods=['GET','POST'])
def unlink(ident):
    if request.method=='GET':
        return run(lambda conn:equivalences.unlink_preview(conn,ident))
    return execute(ident,'unlink',lambda conn,values:equivalences.unlink(conn,ident,values))
