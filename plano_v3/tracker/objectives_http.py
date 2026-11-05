from flask import Blueprint, request
from .http import endpoint, body
from . import objectives

api = Blueprint('objectives', __name__, url_prefix='/api/objectives')


@api.get('')
@endpoint()
def listing(conn):
    return objectives.listing(conn, request.args.get('archived') == '1')


@api.get('/context')
@endpoint()
def context(conn):
    return {'sources': objectives.catalog(conn)}


@api.post('/preview')
@endpoint()
def preview(conn):
    return objectives.validate(conn, body().get('document'))


@api.post('')
@endpoint(True)
def create(conn):
    return objectives.create(conn, body())


@api.get('/<int:ident>')
@endpoint()
def detail(conn, ident):
    return objectives.detail(conn, ident)


@api.get('/<int:ident>/document')
@endpoint()
def document(conn, ident):
    return objectives.document(conn, ident)


@api.patch('/<int:ident>')
@endpoint(True)
def edit(conn, ident):
    return objectives.edit(conn, ident, body())


@api.put('/<int:ident>/path')
@endpoint(True)
def revise(conn, ident):
    return objectives.revise(conn, ident, body())


@api.patch('/<int:ident>/tasks/<int:task_id>')
@endpoint(True)
def task(conn, ident, task_id):
    return objectives.edit_task(conn, ident, task_id, body())
