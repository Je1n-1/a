"""Auditoria V3: fonte SQLite somente leitura; reproduções em diretório isolado."""
from pathlib import Path
import sys, os, io, json, sqlite3, hashlib, time, ast, tempfile
from datetime import datetime
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from config import DATABASE_PATH, LOCAL_TIMEZONE
from database import connection, migrations
from flask import Flask
from routes.api import api
from routes.pages import pages


def inspect(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {'path': str(path), 'bytes': path.stat().st_size,
                'integrity': c.execute('PRAGMA integrity_check').fetchall(),
                'foreign_keys': c.execute('PRAGMA foreign_key_check').fetchall(),
                'counts': {t: c.execute('SELECT COUNT(*) FROM "' + t + '"').fetchone()[0] for t in tables},
                'migrations': c.execute('SELECT version,name,checksum FROM schema_migrations ORDER BY version').fetchall()}


def make_app():
    app = Flask('phase0', template_folder=str(ROOT/'templates'), static_folder=str(ROOT/'static'))
    app.register_blueprint(api)
    app.register_blueprint(pages)
    return app


def main():
    stamp = datetime.now(LOCAL_TIMEZONE).strftime('%Y%m%d-%H%M%S')
    work = Path(os.environ['LOCALAPPDATA'])/'Plano'/'v3-audit'/stamp
    work.mkdir(parents=True, exist_ok=False)
    source = Path(DATABASE_PATH).resolve()
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    result = {'workdir': str(work), 'source': inspect(source), 'source_sha256_before': before_hash}
    backup_dir = Path(os.environ['LOCALAPPDATA'])/'Plano'/'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir/f'plano-v2-before-v3-{stamp}.db'
    with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    result['backup'] = inspect(backup)
    assert result['backup']['counts'] == result['source']['counts']
    assert result['backup']['migrations'] == result['source']['migrations']
    assert result['backup']['integrity'] == [('ok',)] and not result['backup']['foreign_keys']
    db = work/'http-tests.db'
    connection.DATABASE_PATH = db
    begin = time.perf_counter()
    result['first_migrations'] = migrations.migrate(db)
    result['migration_ms'] = round((time.perf_counter()-begin)*1000, 2)
    result['second_migrations'] = migrations.migrate(db)
    assert result['second_migrations'] == []
    app = make_app()
    client = app.test_client()
    result['cases'] = []
    def record(name, response):
        payload = response.get_json(silent=True)
        result['cases'].append({'name': name, 'status': response.status_code,
            'summary': payload.get('summary') if isinstance(payload, dict) else None,
            'error': payload.get('error') if isinstance(payload, dict) else None,
            'format': payload.get('format') if isinstance(payload, dict) else None})
        return payload
    def course(name):
        r = client.post('/api/formations', json={'name':name})
        assert r.status_code == 200, r.data
        return r.json['id']
    def preview(ident, content, name):
        return client.post(f'/api/formations/{ident}/curriculum/preview', data={'file':(io.BytesIO(content),name)}, content_type='multipart/form-data')
    fid = course('Auditoria modelo')
    route = f'/api/formations/{fid}/curriculum'
    template = (ROOT/'static/downloads/modelo_grade_curricular.xlsx').read_bytes()
    payload = record('XLSX model preview', preview(fid, template, 'modelo.xlsx'))
    assert payload['summary']['recognized'] == 3 and payload['summary']['selected'] == 0
    assert client.get(route).json == []
    record('all unchecked confirmation', client.post(route+'/import', json={'confirmed':True,'items':payload['items']}))
    assert client.get(route).json == []
    for row in payload['items']: row['include'] = True
    imported = record('all selected confirmation', client.post(route+'/import', json={'confirmed':True,'items':payload['items']}))
    assert imported['summary']['inserted'] == 3
    repeated = record('duplicate import', client.post(route+'/import', json={'confirmed':True,'items':payload['items']}))
    assert repeated['summary']['inserted'] == 0 and repeated['summary']['skipped'] == 3
    reopened = make_app().test_client()
    assert len(reopened.get(route).json) == 3
    result['persisted_after_app_recreation'] = 3
    result['diagnostics_path'] = reopened.get('/api/diagnostics').json['database']['path']
    csv = 'Disciplina;Código;Período;Carga (h);Importar?\nÁlgebra Linear;001;1;45;Sim\n'.encode('utf-8-sig')
    fid2 = course('Auditoria CSV')
    data = record('CSV accents leading zero', preview(fid2,csv,'grade.csv'))
    assert data['items'][0]['code'] == '001'
    result['short_workload_header_minutes'] = data['items'][0]['workload_minutes']
    data = record('CSV canonical workload header', preview(fid2,csv.replace(b'Carga (h)', 'Carga horária (h)'.encode()),'grade.csv'))
    assert data['items'][0]['workload_minutes'] == 2700
    assert data['items'][0]['name'] == 'Álgebra Linear'
    record('CSV confirmation', client.post(f'/api/formations/{fid2}/curriculum/import',json={'confirmed':True,'items':data['items']}))
    from docx import Document
    doc = Document()
    table = doc.add_table(rows=2, cols=3)
    for cell,value in zip(table.rows[0].cells,['Disciplina','Código','Carga (h)']): cell.text=value
    for cell,value in zip(table.rows[1].cells,['Eletrônica','001','30']): cell.text=value
    buf = io.BytesIO(); doc.save(buf)
    docx = record('DOCX table', preview(fid2,buf.getvalue(),'grade.docx'))
    assert docx['summary']['recognized'] == 1
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter(); page=writer.add_blank_page(width=595,height=842)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 50 780 Td (UCFC 1) Tj 0 -20 Td (Circuitos 60) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    buf=io.BytesIO(); writer.write(buf)
    pdf = record('textual PDF synthetic', preview(fid2,buf.getvalue(),'grade.pdf'))
    assert pdf['summary']['recognized'] == 1
    writer=PdfWriter(); writer.add_blank_page(width=595,height=842); buf=io.BytesIO(); writer.write(buf)
    record('PDF without text', preview(fid2,buf.getvalue(),'sem-texto.pdf'))
    for name,content in [('empty.csv',b''),('invalid.xlsx',b'not a zip'),('invalid.pdf',b'invalid'),('invalid.docx',b'invalid'),('large.csv',b'x'*(5*1024*1024+1)),('grade.tsv',b'Disciplina\tCarga (h)\nCircuitos\t30')]:
        record(name, preview(fid2,content,name))
    result['temporary_database'] = inspect(db)
    result['source_sha256_after'] = hashlib.sha256(source.read_bytes()).hexdigest()
    assert result['source_sha256_after'] == before_hash
    paths = [p for p in ROOT.rglob('*') if p.is_file() and not any(x in p.parts for x in ('.venv','__pycache__','docs'))]
    result['inventory']={'python_files':sum(p.suffix=='.py' for p in paths),'js_files':sum(p.suffix=='.js' for p in paths),'route_rules':len(list(app.url_map.iter_rules())),
        'files':{str(p.relative_to(ROOT)):{'lines':len(p.read_text(encoding='utf-8').splitlines()),'bytes':p.stat().st_size} for p in paths if str(p.relative_to(ROOT)).replace('\\','/') in ['services/core.py','static/js/app.js','static/js/focus.js','services/grade_import.py','routes/api.py']}}
    result['api_decorators']=sum(isinstance(n,ast.FunctionDef) and sum(isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name) and d.func.value.id=='api' for d in n.decorator_list) for n in ast.walk(ast.parse((ROOT/'routes/api.py').read_text(encoding='utf-8'))))
    (ROOT/'docs/v3/evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__ == '__main__': main()
