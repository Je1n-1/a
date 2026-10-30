// Regression: a topic on the active timer must not prevent rendering its controls.
// Starts an isolated database/server; never sends writes to the personal site.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require('C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const out = fs.mkdtempSync(path.join(os.tmpdir(), 'plano-timer-controls-'));
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
    let ready = false;
    for (let i=0; i<100; i++) {
      try {
        const report = await fetch(base+'/api/diagnostics').then(r=>r.json());
        assert.equal(path.resolve(report.path).toLowerCase(), database.toLowerCase());
        ready = true;break;
      } catch { await sleep(100); }
    }
    assert.ok(ready, 'Isolated server failed to start; inspect '+out);
    browser = await chromium.launch({channel:'msedge', headless:true});
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', e=>errors.push(e.message));
    const get = async p=>(await page.request.get(base+'/api'+p)).json();
    const modal = page.locator('#common-dialog');
    const controls = page.locator('#timer-actions');
    const checkHealthy = async () => {
      assert.equal(await page.locator('#connection-error').innerText(), '');
      assert.equal(await page.locator('#timer-error').innerText(), '');
      assert.deepEqual(errors, []);
    };
    await page.goto(base);
    await controls.locator('[data-action=cancel]').waitFor();
    await checkHealthy();
    await page.goto(base+'/analytics');
    await page.locator('#analytics-filters').waitFor();
    for (const width of [320,375,390,600,700,768,1024,1100,1440]) {
      await page.setViewportSize({width,height:1000});
      const layout = await page.locator('.analysis-filters').evaluate(el=>({columns:getComputedStyle(el).gridTemplateColumns.split(' ').length,overflow:document.documentElement.scrollWidth>innerWidth+1}));
      assert.equal(layout.columns,width<=375?1:width<=1100?2:3);
      if(layout.overflow) console.log(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,cl:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))));
      assert.equal(layout.overflow,false,`Overflow at ${width}`);
    }
    await page.goto(base);
    await controls.locator('[data-action=cancel]').waitFor();
    assert.match(await page.locator('#active-title').innerText(), /Projeto luminotécnico · Estudo/);
    assert.equal((await get('/timer')).recovery_required, true);
    assert.ok(await controls.locator('[data-action=pause]').isEnabled());
    assert.ok(await controls.locator('[data-action=cancel]').isEnabled());
    await page.reload();
    await controls.locator('[data-action=recover]').waitFor();
    await checkHealthy();
    // Opening/cancelling the discard dialog must leave the session untouched.
    const before = await get('/timer');
    await controls.locator('[data-action=cancel]').click();
    await modal.getByRole('button', {name:'Cancelar',exact:true}).click();
    assert.equal((await get('/timer')).version, before.version);
    await controls.locator('[data-action=recover]').click();
    await modal.locator('[name=choice]').selectOption('cutoff');
    await modal.locator('[name=cutoff_at]').fill(
      await modal.locator('[name=cutoff_at]').getAttribute('min'));
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({state:'hidden'});
    assert.equal((await get('/timer')).status, 'paused');
    assert.equal((await get('/timer')).effective_seconds, 0);
    await controls.locator('[data-action=resume]').click();
    await controls.locator('[data-action=pause]').waitFor();
    await sleep(1200);
    await controls.locator('[data-action=pause]').click();
    await controls.locator('[data-action=resume]').waitFor();
    await controls.locator('[data-action=break-plan]').click();
    await modal.locator('[name=minutes]').fill('1');
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({state:'hidden'});
    assert.equal((await get('/timer')).rest_active, true);
    await controls.locator('[data-action=resume]').click();
    await controls.locator('[data-action=finish]').click();
    await modal.locator('[name=note]').fill('Regression: topic controls remain usable');
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({state:'hidden'});
    assert.equal(await get('/timer'), null);
    const saved = await get('/sessions/recent');
    assert.equal(saved.length, 1);
    assert.equal(saved[0].topic_id, before.topic_id);
    // Start a review through the actual form, then discard it through the dialog.
    await page.goto(base+`/?subject=${before.subject_id}&topic=${before.topic_id}&kind=review`);
    await page.waitForFunction(()=>!document.querySelector('#start-button').disabled);
    await page.locator('#start-button').click();
    await controls.locator('[data-action=cancel]').waitFor();
    assert.match(await page.locator('#active-title').innerText(), /Projeto luminotécnico · Revisão/);
    await page.setViewportSize({width:390,height:844});
    await page.reload();
    await controls.locator('[data-action=cancel]').waitFor();
    await checkHealthy();
    await page.screenshot({path:path.join(out,'topic-controls-mobile.png'),fullPage:true});
    await controls.locator('[data-action=cancel]').click();
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({state:'hidden'});
    assert.equal(await get('/timer'), null);
    assert.deepEqual(await get('/sessions/recent'), saved);
    await checkHealthy();
    const result = {passed:true, errors, checks:['topic study and review', 'reload', 'overdue recovery with cutoff', 'pause/resume', 'scheduled break', 'finish', 'discard preserves history', 'mobile'], artifacts:out};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result,null,2));
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null) spawnSync('taskkill', ['/PID',String(server.pid),'/T','/F'], {windowsHide:true,stdio:'ignore'});
    fs.closeSync(log);
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
