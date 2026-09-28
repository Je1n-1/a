"""Servidor manual de validação: sempre cria banco isolado, nunca usa o pessoal."""
import os
import sys
import tempfile
import argparse
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
parser=argparse.ArgumentParser()
parser.add_argument('--database',type=Path)
args=parser.parse_args()
if args.database:
    db=args.database.resolve()
    if not db.is_file() or not db.parent.name.startswith('plano-etapa2-browser-') or db.parent.parent!=Path(tempfile.gettempdir()).resolve():
        raise SystemExit('Aceita somente o banco temporário criado por este teste.')
    folder=db.parent
else:
    folder=Path(tempfile.mkdtemp(prefix='plano-etapa2-browser-'))
os.environ['PLANO_DATABASE_PATH']=str(folder/'test.db')
from app import app
from database.connection import connect
from services import core
from database.repositories import core as repo

with connect() as conn:
    seed = not args.database
    for index,name in enumerate(('Engenharia Elétrica · teste','Engenharia da Computação · teste','Técnico em Eletrônica · teste') if seed else ()):
        course=core.create_formation(conn,{'name':name,'institution':'Ambiente de validação'})
        subject=core.create_curriculum(conn,course['id'],{'name':'Circuitos Elétricos','period':'1º período','workload_minutes':2700,'academic_status':'not_available'})
        core.create_curriculum(conn,course['id'],{'name':'Cálculo I','period':'1º período','workload_minutes':3600})
        if index==1:
            topic=core.create_content(conn,subject['id'],{'name':'Leis de Kirchhoff'})
            study=repo.insert(conn,'materias_estudo',{'origin':'curriculum','curriculum_subject_id':subject['id'],'status':'paused','mastery_is_provisional':1,'difficulty_is_provisional':1})
            repo.insert(conn,'sessoes_estudo',{'study_subject_id':study,'topic_id':topic['id'],'date':'2026-09-28','duration_seconds':1500,'entry_method':'manual'})
            repo.insert(conn,'anotacoes_estudo',{'study_subject_id':study,'topic_id':topic['id'],'title':'Anotações de teste','content_markdown':'Preservar origem ao vincular e desvincular.'})
print(f'BANCO TEMPORARIO: {folder}',flush=True)
@app.get('/__test__/viewport')
def viewport_fixture():
    from flask import send_file
    return send_file(Path(__file__).with_name('viewport_harness.html'))

app.run(host='127.0.0.1',port=5053,debug=False,use_reloader=False)
