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
const out = fs.mkdtempSync(path.join(os.tmpdir(), 'plano-security-'));
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

  let browser, attacker;
  try {
    let ready=false;
    for(let i=0;i<100;i++){try{const d=await fetch(base+'/api/diagnostics').then(r=>r.json());assert.equal(path.resolve(d.path).toLowerCase(),database.toLowerCase());ready=true;break;}catch{await sleep(100);}}
    assert.ok(ready);
    const http=require('node:http');
    attacker=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Isolated hostile origin</title>');});
    await new Promise(r=>attacker.listen(0,'127.0.0.1',r));
    browser=await chromium.launch({channel:'msedge',headless:true});
    const page=await browser.newPage();page.setDefaultTimeout(10000);
    await page.goto('http://127.0.0.1:'+attacker.address().port);
    for(const [method,route] of [['GET','/api/diagnostics'],['POST','/api/backups']]) {
      await page.evaluate(async({url,method})=>{await fetch(url,{method,mode:'no-cors',...(method==='POST'?{headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'confirmed=true'}:{})}).catch(()=>null);},{url:base+route,method});
      await sleep(100);
      assert.ok(fs.readFileSync(path.join(out,'server.log'),'utf8').includes(method+' '+route+' HTTP/1.1" 403'), 'Server must reject the hostile request');
    }
    const before=await fetch(base+'/api/courses').then(r=>r.json());
    const denied=await page.evaluate(async url=>{try{await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Must not be created'})});return false;}catch{return true;}},base+'/api/courses');
    assert.equal(denied,true);
    assert.deepEqual(await fetch(base+'/api/courses').then(r=>r.json()),before);
    const errors=[],violations=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{window.cspViolations=[];document.addEventListener('securitypolicyviolation',e=>window.cspViolations.push(e.violatedDirective));});
    for(const route of ['/','/subjects','/projects','/analytics']){
      await page.goto(base+route);await page.waitForLoadState('networkidle');violations.push(...await page.evaluate(()=>window.cspViolations));
    }
    // Legitimate backup and multipart recovery through the UI, with CSP enforced.
    await page.locator('[data-storage]').click();await page.locator('#create-backup').click();
    const downloadPromise=page.waitForEvent('download');await page.locator('#common-dialog button[type=submit]').click();
    const download=await downloadPromise;const file=path.join(out,'backup.db');await download.saveAs(file);
    await page.locator('#common-dialog').waitFor({state:'hidden'});
    await page.locator('[data-storage]').click();await page.locator('#recover-backup').click();
    await page.locator('#common-dialog [name=file]').setInputFiles(file);
    await page.locator('#common-dialog [name=confirmed]').check();
    await page.locator('#common-dialog button[type=submit]').click();
    await page.locator('#common-dialog h2').filter({hasText:'Cópia recuperada'}).waitFor();
    await page.screenshot({path:path.join(out,'recovery.png'),fullPage:true});
    violations.push(...await page.evaluate(()=>window.cspViolations));assert.deepEqual(violations,[]);assert.deepEqual(errors,[]);
    const result={passed:true,hostileOriginBlocked:true,legitimateBackupRecovery:true,errors,violations,artifacts:out};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
  }finally{
    if(browser)await browser.close();if(attacker)await new Promise(r=>attacker.close(r));
    if(server.exitCode===null)spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});fs.closeSync(log);
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
