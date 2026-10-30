// Regression: two tabs must not overwrite catalog edits or stale import previews.
// Starts an isolated database/server; never sends writes to the personal site.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require('C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const out = fs.mkdtempSync(path.join(os.tmpdir(), 'plano-catalog-concurrency-'));
const database = path.join(out, 'test.db');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const probe = net.createServer();
  await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
  const port = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  const base = `http://127.0.0.1:${port}`;
  const seed = `
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app import create_app
from tracker import db
db.initialize(sys.argv[1])
app = create_app(sys.argv[1])
client = app.test_client()
course = client.post('/api/courses', json={'name':'Timer regression'}).json
subject = client.post('/api/subjects', json={'course_id':course['id'], 'name':'Instalações', 'academic_status':'in_progress'}).json
topic = client.post('/api/topics', json={'subject_id':subject['id'], 'name':'Projeto luminotécnico'}).json
stamp = (datetime.now(timezone.utc) - timedelta(hours=9)).replace(microsecond=0).isoformat()
with patch('tracker.timer.now', return_value=stamp):
    result = client.post('/api/timer', json={'operation_key':'long-topic', 'subject_id':subject['id'], 'topic_id':topic['id'], 'session_kind':'study'})
    assert result.status_code == 200, result.json
app.run(host='127.0.0.1', port=int(sys.argv[2]), debug=False, use_reloader=False)
`;
  const log = fs.openSync(path.join(out, 'server.log'), 'w');
  const server = spawn(process.env.PLANO_TEST_PYTHON || path.join(root, '.venv/Scripts/python.exe'),
    ['-u', '-c', seed, database, String(port)],
    {cwd:root, windowsHide:true, stdio:['ignore', log, log], env:{...process.env, PYTHONUTF8:'1'}});

  let browser;
  try {
    let ready=false;
    for(let i=0;i<100;i++) {
      try { const d=await fetch(base+'/api/diagnostics').then(r=>r.json());assert.equal(path.resolve(d.path).toLowerCase(),database.toLowerCase());ready=true;break; }
      catch {await sleep(100);}
    }
    assert.ok(ready,'Isolated server failed to start');
    browser=await chromium.launch({channel:'msedge',headless:true});
    const ctx=await browser.newContext();
    const a=await ctx.newPage(),b=await ctx.newPage(),errors=[];
    for(const page of [a,b]) {page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));}
    const modal=p=>p.locator('#common-dialog');
    const save=async p=>{await modal(p).locator('button[type=submit]').click();await modal(p).waitFor({state:'hidden'});};
    const close=async p=>modal(p).getByRole('button',{name:'Cancelar',exact:true}).click();
    await Promise.all([a.goto(base+'/subjects'),b.goto(base+'/subjects')]);
    await Promise.all([a.locator('[data-edit-course]').click(),b.locator('[data-edit-course]').click()]);
    await modal(a).locator('[name=name]').fill('Curso atualizado');await save(a);
    await modal(b).locator('[name=name]').fill('Edição antiga');
    await modal(b).locator('button[type=submit]').click();
    await modal(b).locator('.form-error').filter({hasText:'outra aba'}).waitFor();
    assert.equal(await modal(b).locator('[name=name]').inputValue(),'Edição antiga');
    await close(b);await b.locator('[data-edit-course]').click();
    assert.equal(await modal(b).locator('[name=name]').inputValue(),'Curso atualizado');
    await close(b);
    await Promise.all([a.locator('[data-edit-subject]').click(),b.locator('[data-edit-subject]').click()]);
    await modal(a).locator('[name=notes]').fill('Atualização preservada');await save(a);
    await modal(b).locator('[name=notes]').fill('Não deve sobrescrever');
    await modal(b).locator('button[type=submit]').click();
    await modal(b).locator('.form-error').filter({hasText:'outra aba'}).waitFor();
    await pageShot(b,'conflict.png');await close(b);
    await b.locator('[data-edit-subject]').click();
    assert.equal(await modal(b).locator('[name=notes]').inputValue(),'Atualização preservada');await close(b);
    // Stale archive confirmation must not hide a more recently edited row.
    await b.locator('[data-archive-subject]').click();
    await a.locator('[data-status-id]').selectOption('completed');
    await a.locator('#notifications').filter({hasText:'Situação salva'}).waitFor();
    await modal(b).locator('button[type=submit]').click();
    await modal(b).locator('.form-error').filter({hasText:'outra aba'}).waitFor();await close(b);
    const read=async route=>(await ctx.request.get(base+'/api'+route)).json();
    let subject=(await read('/subjects'))[0];assert.equal(subject.academic_status,'completed');assert.equal(subject.archived_at,null);
    // Import update carries the preview's version and cannot overwrite a later edit.
    async function preview(page) {
      await page.locator('[data-import]').click();
      const d=page.locator('#import-dialog');
      await d.locator('[data-tab=text]').click();await d.locator('[name=text]').fill('Disciplina\tCarga horária\nInstalações\t90');
      await d.locator('button[type=submit]').click();await d.locator('#confirm-import').waitFor();
      await d.locator('.import-detail').evaluate(el=>el.open=true);
      await d.locator('[data-field=duplicate_action]').selectOption('update');return d;
    }
    const d=await preview(b);
    await a.locator('[data-edit-subject]').click();await modal(a).locator('[name=notes]').fill('Conservar até revisar importação');await save(a);
    await d.locator('#confirm-import').click();await d.locator('.form-error').filter({hasText:'outra aba'}).waitFor();
    assert.equal((await read('/subjects'))[0].notes,'Conservar até revisar importação');
    await d.locator('[data-close]').click();
    const fresh=await preview(b);await fresh.locator('#confirm-import').click();await fresh.waitFor({state:'hidden'});
    assert.equal((await read('/subjects'))[0].workload_minutes,5400);
    assert.deepEqual(errors,[]);
    const result={passed:true,errors,checks:['two course editors','two subject editors','stale archive','quick status','stale import','fresh import'],artifacts:out};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
    async function pageShot(page,name){await page.screenshot({path:path.join(out,name),fullPage:true});}
  } finally {
    if(browser)await browser.close();
    if(server.exitCode===null)spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
    fs.closeSync(log);
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
