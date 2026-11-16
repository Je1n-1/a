// End-to-end study-route import and timer regression. The spawned site uses a disposable database.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require('C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'), out=fs.mkdtempSync(path.join(os.tmpdir(),'plano-study-routes-'));
const database=path.join(out,'isolated.db'), sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  const probe=net.createServer(); await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve)); const port=probe.address().port; await new Promise(resolve=>probe.close(resolve));
  const base=`http://127.0.0.1:${port}`;
  const seed=`
import sys
from app import create_app
from tracker import db
db.initialize(sys.argv[1]); app=create_app(sys.argv[1]); client=app.test_client()
course=client.post('/api/courses',json={'name':'Engenharia Elétrica','institution':'SENAI'}).json
subject=client.post('/api/subjects',json={'course_id':course['id'],'name':'Circuitos Elétricos','academic_status':'in_progress','code':'EE-1','period':'1º'}).json
other=client.post('/api/subjects',json={'course_id':course['id'],'name':'Eletrônica'}).json
topic=client.post('/api/topics',json={'subject_id':subject['id'],'name':'Grandezas elétricas'}).json
print(f'{course["id"]},{subject["id"]},{other["id"]},{topic["id"]}',flush=True)
app.run(host='127.0.0.1',port=int(sys.argv[2]),debug=False,use_reloader=False)
`;
  const python=process.env.PLANO_TEST_PYTHON||'C:/Users/jeanm/AppData/Local/Programs/Python/Python313/python.exe';
  const log=fs.openSync(path.join(out,'server.log'),'w');
  const server=spawn(python,['-u','-c',seed,database,String(port)],{cwd:root,windowsHide:true,stdio:['ignore','pipe',log],env:{...process.env,PYTHONUTF8:'1'}});
  let lines='', ids, browser;
  server.stdout.on('data',chunk=>lines+=chunk.toString());
  try {
    let ready=false;
    for(let i=0;i<120;i++){
      const found=lines.match(/(\d+),(\d+),(\d+),(\d+)/);
      if(found){ids=found.slice(1).map(Number);try{const r=await fetch(base+'/api/diagnostics');if(r.ok){ready=true;break;}}catch{}}
      await sleep(100);
    }
    assert.ok(ready,'isolated server did not start; see '+out);
    browser=await chromium.launch({channel:'msedge',headless:true});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(10000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+`/subjects?course=${ids[0]}`);
    await page.locator('[data-study-route]').first().waitFor({state:'attached'});
    await page.locator('.row-action-menu summary').first().click();
    await page.locator(`[data-study-route="${ids[1]}"]`).click();
    const modal=page.locator('#common-dialog');
    await modal.waitFor({state:'visible'});
    await modal.getByRole('button',{name:'Copiar prompt'}).click();
    const prompt=await modal.locator('[data-route-prompt]').inputValue();
    assert.match(prompt,/SENAI/);assert.match(prompt,/Grandezas elétricas/);assert.match(prompt,/completed/);assert.match(prompt,/existing_topic_id/);
    await modal.getByRole('button',{name:'Colar resposta JSON'}).click();
    const routeDoc={schema_version:1,kind:'subject_study_route',route:{title:'Circuitos — roteiro',description:'Conteúdos do plano',modules:[{key:'base',title:'Fundamentos',description:'Conceitos iniciais',topics:[{key:'grandezas',title:'Grandezas elétricas',description:'Usar unidades adequadas.',estimated_minutes:45,source_reference:'Unidade 1',existing_topic_id:null},{key:'lei_ohm',title:'Lei de Ohm',description:'Relacionar tensão, corrente e resistência.',estimated_minutes:60,source_reference:'Unidade 2',existing_topic_id:null}]}]}};
    await modal.locator('[data-route-json]').fill(JSON.stringify(routeDoc,null,2));
    await modal.getByRole('button',{name:'Gerar prévia'}).click();
    await modal.getByText('Vinculado a tópico existente').waitFor();
    await modal.getByRole('button',{name:'Confirmar importação'}).click();
    await modal.getByText('Roteiro principal').waitFor();
    const route=await page.request.get(base+`/api/subjects/${ids[1]}/study-route`).then(r=>r.json());
    assert.equal(route.route.topic_count,2);assert.equal(route.route.modules[0].topics[0].id,ids[3]);
    await page.screenshot({path:path.join(out,'discipline-route-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.goto(base+`/subjects?course=${ids[0]}&subject=${ids[1]}`);
    await page.locator('[data-study-route]').click();
    await modal.waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    assert((await modal.boundingBox()).width<=390);
    await page.screenshot({path:path.join(out,'discipline-route-mobile.png')});
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(base+`/?subject=${ids[1]}`);
    await page.locator('#today-route-wrap:not([hidden])').waitFor();
    assert.match(await page.locator('#today-route').inputValue(),/main/);
    const topicSelect=page.locator('[data-topic]');
    await page.waitForFunction(()=>[...document.querySelector('[data-topic]').options].some(o=>o.textContent.includes('Lei de Ohm')));
    assert.equal(await topicSelect.locator('optgroup').first().getAttribute('label'),'Fundamentos');
    await topicSelect.selectOption(String(route.route.modules[0].topics[1].id));
    await page.screenshot({path:path.join(out,'today-desktop.png'),fullPage:true});
    await page.locator('#start-button').click();
    const actions=page.locator('#timer-actions');await actions.locator('[data-action=pause]').waitFor();
    await actions.locator('[data-action=pause]').click();await actions.locator('[data-action=resume]').waitFor();
    await actions.locator('[data-action=resume]').click();await actions.locator('[data-action=finish]').waitFor();await sleep(1200);
    await actions.locator('[data-action=finish]').click();
    await modal.locator('button[type=submit]').click();
    await page.waitForFunction(()=>{const d=document.querySelector('#common-dialog');return !d.open||!!d.querySelector('[role=alert]')?.textContent;});
    if(await modal.isVisible()) throw new Error('Finish dialog stayed open: '+await modal.innerText());
    const recent=await page.request.get(base+'/api/sessions/recent').then(r=>r.json());
    assert.equal(recent[0].topic_id,route.route.modules[0].topics[1].id);
    await page.setViewportSize({width:390,height:844});
    await page.goto(base+`/?subject=${ids[1]}`);
    await page.locator('#today-route-wrap:not([hidden])').waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.screenshot({path:path.join(out,'today-mobile.png'),fullPage:true});
    await page.goto(base+`/subjects?course=${ids[0]}&subject=${ids[1]}`);
    await page.locator('[data-study-route]').first().waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.screenshot({path:path.join(out,'discipline-detail-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    const result={passed:true,errors,checks:['contextual prompt','external JSON preview and import','canonical existing-topic link','module grouping in Today','timer pause/resume/finish and topic history','mobile overflow'],artifacts:out};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
  }finally{
    if(browser)await browser.close();
    if(server.exitCode===null)spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
    fs.closeSync(log);
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
