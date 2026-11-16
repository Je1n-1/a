// End-to-end checks use an isolated database and a private port only.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn,spawnSync}=require('node:child_process');
const {chromium}=require('C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),out=fs.mkdtempSync(path.join(os.tmpdir(),'plano-objectives-'));
const database=path.join(out,'test.db'),pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base=`http://127.0.0.1:${port}`;
 const seed=`from tracker import db\nfrom app import create_app\nimport sys\ndb.initialize(sys.argv[1])\ncreate_app(sys.argv[1]).run(host='127.0.0.1',port=int(sys.argv[2]),debug=False,use_reloader=False)`;
 const log=fs.openSync(path.join(out,'server.log'),'w');const server=spawn(process.env.PLANO_TEST_PYTHON||'python',['-u','-c',seed,database,String(port)],{cwd:root,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,PYTHONUTF8:'1'}});let browser;
 try{
  let ready=false;for(let i=0;i<100;i++){try{const r=await fetch(base+'/api/diagnostics');if(r.ok){ready=true;break;}}catch{}await pause(100);}assert(ready,'Server did not start');
  browser=await chromium.launch({channel:'msedge',headless:true});const ctx=await browser.newContext({viewport:{width:1440,height:1100}});const page=await ctx.newPage(),errors=[];page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  const post=async(route,data)=>{const r=await ctx.request.post(base+'/api'+route,{data});assert(r.ok(),await r.text());return r.json();};
  const course=await post('/courses',{name:'Eletrotécnica'}),subject=await post('/subjects',{name:'Circuitos elétricos',course_id:course.id,academic_status:'completed'}),topic=await post('/topics',{subject_id:subject.id,name:'Sensores'});
  await post('/sessions/manual',{mode:'duration',date:'2026-11-04',duration_seconds:1500,subject_id:subject.id,topic_id:topic.id,operation_key:'seed-session'});
  const doc={schema_version:1,objective:{title:'Desenvolver uma automação funcional',description:'Construir, testar e documentar uma solução para um problema real.',stages:[{key:'definicao',title:'Definir o problema e o resultado esperado',description:'Entender a necessidade e definir o resultado.',tasks:[{key:'base',title:'Reaproveitar fundamentos elétricos',description:'Conhecimentos já concluídos no curso.',planned_minutes:120,source:{kind:'subject',id:subject.id},requires:[]},{key:'necessidade',title:'Descrever a necessidade',description:'Escolher o cenário de aplicação.',planned_minutes:60,source:null,requires:[]}]},{key:'construir',title:'Escolher componentes e desenhar o funcionamento',description:'Organizar os conhecimentos e desenvolver a solução.',tasks:[{key:'sensores',title:'Revisar opções de sensores',description:'Comparar alternativas.',planned_minutes:90,source:{kind:'topic',id:topic.id},requires:['base']},{key:'prototipo',title:'Construir o protótipo',description:'Aplicar os conhecimentos e registrar o funcionamento.',planned_minutes:240,source:null,requires:['sensores']}]},{key:'validar',title:'Testar e documentar',tasks:[{key:'testes',title:'Conferir os cenários previstos',description:'Registrar os resultados e os ajustes.',planned_minutes:120,source:null,requires:['prototipo']}]}]}};
  await page.goto(base+'/objectives');
  await page.getByRole('heading',{name:'O que você quer ser capaz de fazer?'}).waitFor();
  assert.equal(await page.locator('nav a').count(),5);
  await page.locator('.page-heading [data-action="new"]').click();
  await page.locator('#objective-intention').fill('Quero desenvolver uma automação funcional.');
  await page.locator('.objective-extra').first().locator('summary').click();
  await page.locator('#objective-experience').fill('Conheço a lei de Ohm.');
  await page.locator('#objective-constraints').fill('Três horas por semana.');
  await page.locator('[data-action="prompt"]').click();
  await page.locator('#objective-prompt-panel').waitFor({state:'visible'});
  assert.match(await page.locator('#objective-prompt').inputValue(),/Circuitos elétricos/);
  assert.match(await page.locator('#objective-prompt').inputValue(),/Três horas/);
  await page.locator('#objective-file').setInputFiles({name:'objetivo.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc))});
  await page.locator('#objective-review-panel').waitFor({state:'visible'});
  assert.equal(await page.locator('.objective-draft-task').count(),5);
  assert.equal(await page.locator('#objective-draft-stages input').count(),0);
  assert.equal(await page.locator('.objective-draft-stage[open]').count(),0);
  for(const width of [768,375,320]){
    await page.setViewportSize({width,height:1000});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Import preview overflows at '+width);
  }
  await page.setViewportSize({width:1440,height:1100});
  await page.screenshot({path:path.join(out,'import.png'),fullPage:true});
  // Reload restores the unsaved AI conversation and preview without creating a goal.
  await page.reload();await page.locator('#objective-review-panel').waitFor({state:'visible'});
  assert.equal(await page.locator('#objective-constraints').inputValue(),'Três horas por semana.');
  assert.equal((await (await ctx.request.get(base+'/api/objectives')).json()).length,0);
  await page.locator('.objective-draft-stage summary').first().click();
  await page.locator('[data-action="draft-task"][data-key="necessidade"]').click();
  await page.locator('#common-dialog textarea[name="description"]').fill('Identificar uma situação real para automatizar.');
  await page.locator('#common-dialog button[type=submit]').click();
  await page.locator('#common-dialog').waitFor({state:'hidden'});
  await page.locator('[data-action="confirm"]').click();
  await page.locator('#objective-detail').waitFor({state:'visible'});
  await page.locator('#notifications').filter({hasText:'Objetivo salvo'}).waitFor();
  assert.equal(await page.locator('.objective-task').count(),5);
  assert.equal(await page.locator('.objective-task select').count(),0);
  const goalId=new URL(page.url()).searchParams.get('objective');
  await page.locator('[data-action="expand"]').click();
  const firstTask=page.locator('.objective-task').filter({hasText:'Descrever a necessidade'});
  await firstTask.locator('[data-complete]').check();
  await page.locator('#objective-detail .objective-summary').filter({hasText:'40%'}).waitFor();
  const linked=page.locator('.objective-task').filter({hasText:'Revisar opções de sensores'}).first();
  await linked.locator('[data-action="task"]').click();
  assert.equal(await page.locator('#common-dialog select[name="status"]').count(),0);
  await page.locator('#common-dialog input[name="needs_review"]').check();
  await page.locator('#common-dialog button[type=submit]').click();
  await page.locator('#common-dialog').waitFor({state:'hidden'});
  const topicRows=await (await ctx.request.get(base+'/api/topics')).json();
  assert.equal(topicRows[0].needs_review,1);
  await page.locator('#objective-state-filter').selectOption('review');
  assert.equal(await page.locator('.objective-task').count(),1);
  assert.equal(await page.locator('.objective-stage[open]').count(),1);
  await page.locator('#objective-state-filter').selectOption('');
  await page.locator('[data-action="expand"]').click();
  await page.screenshot({path:path.join(out,'detail.png'),fullPage:true});
  // Clicking a dependency reveals it even if its stage was collapsed.
  await page.locator('.objective-task').filter({hasText:'Construir o protótipo'}).first().locator('.objective-requirement').click();
  assert(await page.locator('.objective-highlight').isVisible());
  // Follow the exact linked topic and change it at the source.
  const sourceUrl=await linked.locator('.objective-source a').getAttribute('href');
  const sourcePage=await ctx.newPage();await sourcePage.goto(base+sourceUrl);
  await sourcePage.locator('#common-dialog [data-topic-id="'+topic.id+'"]').first().waitFor();
  await Promise.all([
    sourcePage.waitForResponse(r=>r.url().includes('/api/topics?')),
    sourcePage.locator('#common-dialog [data-topic-id="'+topic.id+'"][data-field="completed"]').check()
  ]);
  await sourcePage.close();
  await page.reload();
  await page.locator('#objective-detail .objective-summary').filter({hasText:'60%'}).waitFor();
  assert(await page.locator('.objective-task').filter({hasText:'Revisar opções de sensores'}).first().locator('.objective-review-flag').isVisible());
  // Add separate fixture goals only in this isolated test database.
  for(const [i,title] of ['Reaprender matemática para engenharia','Dominar eletrônica básica','Preparar-me para ensinar Física'].entries()){
    const other=structuredClone(doc);other.objective.title=title;
    await post('/objectives',{document:other,operation_key:'extra-'+i});
  }
  await page.locator('[data-action="home"]:visible').click();
  await page.locator('#objectives-overview').waitFor({state:'visible'});
  assert.equal(await page.locator('.objective-card').count(),4);
  for(const width of [768,375,320]){
    await page.setViewportSize({width,height:1000});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Overview overflows at '+width);
  }
  await page.setViewportSize({width:1440,height:1100});
  await page.screenshot({path:path.join(out,'overview.png'),fullPage:true});
  await page.locator('[data-action="detail"]').click();
  await page.locator('[data-action="revise"]').click();
  await page.locator('#objective-review-panel').waitFor({state:'visible'});
  await page.locator('[data-action="draft-metadata"]').click();
  await page.locator('#common-dialog input[name="title"]').fill('Automação · caminho revisado');
  await page.locator('#common-dialog button[type=submit]').click();
  await page.locator('#common-dialog').waitFor({state:'hidden'});
  await page.locator('[data-action="confirm"]').click();
  await page.locator('#objective-detail h1').filter({hasText:'caminho revisado'}).waitFor();
  assert(await page.locator('.objective-task').filter({hasText:'Descrever a necessidade'}).locator('[data-complete]').isChecked());
  for(const width of [1440,768,375,320]){
    await page.setViewportSize({width,height:1000});
    const d=await page.evaluate(()=>({w:innerWidth,s:document.documentElement.scrollWidth}));
    assert(d.s<=d.w+1,JSON.stringify(d));
  }
  await page.locator('[data-action="expand"]').click();
  await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
  await page.locator('.objective-task').last().scrollIntoViewIfNeeded();
  assert(await page.locator('.objective-task').last().isVisible());
  await page.setViewportSize({width:1440,height:1100});
  await page.locator('[data-action="options"]').click();
  await page.locator('#common-dialog button[type=submit]').click();
  await page.locator('#objectives-overview').waitFor({state:'visible'});
  // Archived direct links survive reload instead of selecting an unrelated goal.
  await page.goto(base+'/objectives?objective='+goalId+'&view=detail');
  await page.locator('#objective-detail').waitFor({state:'visible'});
  assert.match(await page.locator('#objective-detail .eyebrow').innerText(),/ARQUIVADO/);
  assert.match(await page.locator('#objective-detail h1').innerText(),/caminho revisado/);
  await page.locator('[data-action="options"]').click();
  await page.locator('#common-dialog button[type=submit]').click();
  await page.locator('#objectives-overview').waitFor({state:'visible'});
  // Back/forward returns to the objective screen rather than leaving the app.
  await page.locator('[data-action="detail"]').click();
  await page.locator('#objective-detail').waitFor({state:'visible'});
  await page.waitForURL(/view=detail/);await page.goBack();
  await page.locator('#objectives-overview').waitFor({state:'visible'});
  for(const url of ['/','/subjects','/projects','/analytics']){
    await page.goto(base+url);await page.locator('nav').waitFor();
    assert(await page.locator('nav a[href="/objectives"]').isVisible());
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,out,errors}));

 }finally{if(browser)await browser.close();if(server.exitCode===null)spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});fs.closeSync(log);}
})().catch(e=>{console.error(e);process.exitCode=1;});
