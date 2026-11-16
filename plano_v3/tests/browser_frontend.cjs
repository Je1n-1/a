// All writes are confined to this runner's temporary database and random loopback port.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn,spawnSync}=require('node:child_process');
const {chromium}=require('C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const phase=process.argv.find(a=>a.startsWith('--phase='))?.split('=')[1]||'final';
const root=path.resolve(__dirname,'..'),out=fs.mkdtempSync(path.join(os.tmpdir(),'plano-frontend-'+phase+'-'));
const wait=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port;
 const log=fs.openSync(path.join(out,'server.log'),'w');
 const code='from tracker import db\nfrom app import create_app\nimport sys\ndb.initialize(sys.argv[1])\ncreate_app(sys.argv[1]).run(host="127.0.0.1",port=int(sys.argv[2]),debug=False,use_reloader=False)';
 const server=spawn(process.env.PLANO_TEST_PYTHON||'python',['-u','-c',code,path.join(out,'test.db'),String(port)],{cwd:root,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,PYTHONUTF8:'1'}});
 let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/diagnostics')).ok)break;}catch{}await wait(100);}
  browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  const post=async(route,data)=>{const r=await context.request.post(base+'/api'+route,{data});assert(r.ok(),await r.text());return r.json();};
  const courses=[await post('/courses',{name:'Engenharia Elétrica',institution:'Curso de demonstração'}),await post('/courses',{name:'Engenharia da Computação',institution:'Curso de demonstração'})];
  const subjects=[];
  for(const [i,name] of ['Circuitos Elétricos','Cálculo I','Física I','Programação em C','Sistemas Digitais','Eletrônica Aplicada'].entries()){
   subjects.push(await post('/subjects',{name,course_id:courses[i<3?0:1].id,academic_status:i===0?'completed':i%2?'in_progress':'available',period:i<3?'Fundamentos de engenharia':'Tecnologia e aplicação',workload_minutes:3600}));
  }
  const topic=await post('/topics',{subject_id:subjects[0].id,name:'Análise de circuitos resistivos'});
  const projects=[];
  for(const name of ['Bancada de automação','Monitor de energia','Portfólio técnico','Simulador de circuitos']){
   const p=await post('/projects',{name,objective:'Desenvolver uma solução, validar o funcionamento e documentar os resultados.',status:'in_progress',course_id:courses[0].id});
   await post('/projects/'+p.id+'/steps',{name:'Definir requisitos e componentes'});await post('/projects/'+p.id+'/steps',{name:'Construir e testar a aplicação'});projects.push(p);
  }
  const dates=[];
  for(let i=0;i<24;i++){
   const d=new Date(Date.now()-Math.floor(i/2)*86400000).toISOString().slice(0,10);dates.push(d);
   await post('/sessions/manual',{mode:'duration',date:d,duration_seconds:900+(i%5)*900,operation_key:'session-'+i,...(i%4===0?{project_id:projects[i%projects.length].id}:{subject_id:subjects[i%subjects.length].id}),note:'Registro fictício para conferir a interface.'});
  }
  let goal;
  for(const [i,title] of ['Construir uma automação funcional','Reforçar a base de matemática','Aplicar eletrônica em um projeto'].entries()){
   const document={schema_version:1,objective:{title,description:'Organizar os conhecimentos, aplicar na prática e conferir o resultado.',stages:[{key:'base',title:'Consolidar os conceitos necessários',description:'Relacionar o conteúdo estudado ao problema.',tasks:[{key:'circuitos',title:'Revisar os fundamentos de circuitos',description:'Tensão, corrente, resistência e potência.',planned_minutes:120,source:{kind:'subject',id:subjects[0].id}},{key:'requisitos',title:'Descrever o resultado esperado',description:'Definir o comportamento e os critérios de aceitação.',planned_minutes:60,requires:['circuitos']}]},{key:'aplicar',title:'Construir e validar a solução',description:'Experimentar, registrar e ajustar.',tasks:[{key:'projeto',title:'Desenvolver a aplicação',description:'Construir a primeira versão e testar seus componentes.',planned_minutes:240,source:{kind:'project',id:projects[0].id},requires:['requisitos']},{key:'validar',title:'Conferir e documentar os testes',description:'Registrar evidências do funcionamento.',planned_minutes:90,requires:['projeto']}]}]}};
   goal=await post('/objectives',{document,operation_key:'goal-'+i});
  }
  const page=await context.newPage(),errors=[],external=[],violations=[];page.setDefaultTimeout(12000);
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(base+'/'))external.push(r.url());});
  await page.exposeFunction('reportCsp',e=>violations.push(e));
  await page.addInitScript(()=>document.addEventListener('securitypolicyviolation',e=>window.reportCsp(e.violatedDirective)));
  const routes=[['today','/','#start-button'],['subjects','/subjects?course='+courses[0].id,'.subjects-table'],['objectives','/objectives?objective='+goal.id,'[data-action="detail"]'],['projects','/projects','.project-card'],['analytics','/analytics','#history-body tr']];
  const selected=['baseline','global','theme','final'].includes(phase)?routes:routes.filter(([name])=>name===phase);
  const frames=[],contrast=[];
  const get=async route=>(await context.request.get(base+'/api'+route)).json();
  for(const [name,url,ready] of selected){
   await page.goto(base+url);await page.locator(ready).first().waitFor();
   if(name==='today')await page.waitForFunction(()=>!document.querySelector('#start-button').disabled);
   if(name==='analytics')await page.waitForFunction(()=>document.querySelector('#analytics-results').getAttribute('aria-busy')==='false');
   if(phase!=='baseline'){
    assert.equal(await page.locator('.sidebar').count(),0);
    assert.deepEqual(await page.locator('nav a').allTextContents(),['Hoje','Objetivos','Disciplinas','Projetos','Análises']);
   }
   const themes=['baseline','global'].includes(phase)?['dark']:['dark','light'];
   for(const theme of themes){
    if(phase!=='baseline'&&phase!=='global'){
     if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme-toggle').click();
     assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
    }
    if(phase==='final'){
     const pairs=await page.evaluate(()=>{
      const style=getComputedStyle(document.documentElement),v=k=>style.getPropertyValue('--'+k).trim();
      const lum=h=>{h=h.slice(1);if(h.length===3)h=[...h].map(c=>c+c).join('');const c=[0,2,4].map(i=>parseInt(h.slice(i,i+2),16)/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722;};
      return [['text','panel'],['muted','panel2'],['placeholder','field'],['accent-text','accent-bg'],['on-accent','action'],['success','success-bg'],['warning','warning-bg'],['danger','danger-bg']].map(([a,b])=>{const x=lum(v(a)),y=lum(v(b));return {pair:a+'/'+b,ratio:(Math.max(x,y)+.05)/(Math.min(x,y)+.05)};});
     });for(const p of pairs)assert(p.ratio>=4.5,theme+' contrast '+JSON.stringify(p));contrast.push({name,theme,pairs});
    }
    const widths=phase==='final'?[360,390,768,1024,1440,1920]:[390,1440];
    for(const width of widths){
     await page.setViewportSize({width,height:1000});
     const metrics=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
     if(phase!=='baseline')assert(metrics.scroll<=metrics.width+1,name+' '+theme+' '+JSON.stringify(metrics));
     if(width===390||width===1440){const filename=name+'-'+theme+'-'+width+'.png';await page.screenshot({path:path.join(out,filename),fullPage:true});frames.push(filename);if(phase==='final'&&width===1440)await page.screenshot({path:path.join(out,name+'-'+theme+'-viewport.png')});}
    }
   }
  }
  if(phase==='projects'||phase==='final'){
   await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/projects');
   await page.locator('#new-project').click();
   await page.locator('#common-dialog [name=name]').fill('Projeto criado pela interface');
   await page.locator('#common-dialog [name=objective]').fill('Conferir criação, edição, etapas e registro de tempo.');
   await page.locator('#common-dialog button[type=submit]').click();
   await page.locator('[data-add-step]').waitFor();
   await page.locator('[data-add-step]').click();await page.locator('#common-dialog [name=name]').fill('Validar protótipo');
   await page.locator('#common-dialog button[type=submit]').click();await page.locator('[data-complete-step]').check();
   await page.waitForFunction(()=>document.querySelector('#project-detail .project-progress').textContent.includes('1 de 1'));
   await page.locator('[data-edit-project]').click();await page.locator('#common-dialog [name=status]').selectOption('completed');
   await page.locator('#common-dialog button[type=submit]').click();await page.locator('#common-dialog').waitFor({state:'hidden'});
   await page.locator('[data-manual]').click();await page.locator('#common-dialog [name=minutes]').fill('30');
   await page.locator('#common-dialog [name=note]').fill('Protótipo verificado.');
   await page.locator('#common-dialog button[type=submit]').click();await page.locator('.project-record').first().waitFor();
   assert.match(await page.locator('.project-record').first().innerText(),/Protótipo verificado/);
   await page.locator('.project-overview a.button.primary').click();await page.waitForFunction(()=>!document.querySelector('#start-button').disabled);
   assert.equal(await page.locator('#activity-kind').inputValue(),'project');
   await page.goto(base+'/projects');await page.locator('.project-card').first().waitFor();
   await page.locator('#project-status').selectOption('completed');await page.locator('#project-search').fill('criado pela interface');
   assert.equal(await page.locator('.project-card').count(),1);
  }
  if(phase==='analytics'||phase==='final'){
   await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/analytics');
   const ready=()=>page.waitForFunction(()=>document.querySelector('#analytics-results').getAttribute('aria-busy')==='false'&&!document.querySelector('#export-csv').disabled);
   await ready();
   const snapshot=await (await context.request.get(base+'/api/analytics'+new URL(page.url()).search)).json();
   const clock=s=>[Math.floor(s/3600),Math.floor(s%3600/60),s%60].map(n=>String(n).padStart(2,'0')).join(':');
   assert.equal(await page.locator('#metric-period').innerText(),clock(snapshot.summary.period.effective_seconds));
   assert.equal(await page.locator('#history-body tr').count(),20);
   await page.locator('#next-page').click();await page.waitForFunction(()=>document.querySelector('#page-info').textContent.startsWith('Página 2'));
   const downloadEvent=page.waitForEvent('download');await page.locator('#export-csv').click();const csv=await downloadEvent;
   const file=path.join(out,'historico.csv');await csv.saveAs(file);
   assert.equal(fs.readFileSync(file,'utf8').trim().split(/\r?\n/).length,snapshot.history.total+1,'CSV includes every page');
   await page.locator('#previous-page').click();await page.waitForFunction(()=>document.querySelector('#page-info').textContent.startsWith('Página 1'));
   const id=await page.locator('#history-body tr').first().getAttribute('data-session-id');
   await page.locator('.history-actions summary').first().click();
   await page.locator('[data-edit="'+id+'"]').click();
   await page.locator('#common-dialog [name=note]').fill('Nota corrigida na interface.');
   await page.locator('#common-dialog [name=reason]').fill('Conferência da nova interface.');
   await page.locator('#common-dialog button[type=submit]').click();await page.locator('#common-dialog').waitFor({state:'hidden'});await ready();
   assert.equal(await page.locator('#metric-period').innerText(),clock(snapshot.summary.period.effective_seconds));
   await page.locator('.history-actions summary').first().click();
   await page.locator('[data-audit="'+id+'"]').click();await page.locator('.audit-entry').waitFor();
   assert.match(await page.locator('.audit-entry').innerText(),/Conferência da nova interface/);await page.keyboard.press('Escape');
   await page.locator('#analytics-filters [name=activity]').selectOption('project');await ready();
   await page.locator('#analytics-filters [name=project_id]').selectOption(String(projects[0].id));
   await page.locator('#analytics-filters button[type=submit]').click();await ready();
   assert.match(page.url(),new RegExp('project_id='+projects[0].id));
   assert((await page.locator('#history-body').innerText()).includes('Bancada de automação'));
   const filterBefore=page.url();await page.locator('#theme-toggle').click();assert.equal(page.url(),filterBefore);
   await page.locator('#theme-toggle').click();await page.reload();await ready();
   assert.equal(await page.locator('#analytics-filters [name=project_id]').inputValue(),String(projects[0].id));
   await page.locator('#breakdown').selectOption('step');assert.match(await page.locator('#subject-chart').innerText(),/Sem etapa/);
  }
  if(phase==='theme'||phase==='final'){
   await page.goto(base+'/');await page.waitForFunction(()=>!document.querySelector('#start-button').disabled);
   assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
   await page.locator('#today-subject').selectOption('free');await page.locator('#free-title').fill('Rascunho preservado');
   const before=await (await context.request.get(base+'/api/timer')).json();
   await page.locator('#theme-toggle').click();assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
   assert.deepEqual(await (await context.request.get(base+'/api/timer')).json(),before);
   assert.equal(await page.locator('#free-title').inputValue(),'Rascunho preservado');
   await page.locator('#manual-session').click();await page.locator('#common-dialog').waitFor({state:'visible'});
   await page.locator('#common-dialog input').first().focus();await page.keyboard.press('Escape');await page.locator('#common-dialog').waitFor({state:'hidden'});
   await page.locator('#diagnostics').click();await page.locator('#common-dialog').waitFor({state:'visible'});await page.keyboard.press('Escape');
   await page.reload();assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  }
  if(phase==='final'){
   await page.goto(base+'/?subject='+subjects[1].id);await page.waitForFunction(()=>!document.querySelector('#start-button').disabled);
   await page.locator('#start-button').click();await page.locator('#timer-actions [data-action=pause]').waitFor();
   const active=await get('/timer');
   await page.locator('#theme-toggle').focus();await page.keyboard.press('Enter');
   const after=await get('/timer');assert.equal(after.id,active.id);assert.equal(after.version,active.version);assert.equal(after.status,'running');
   await page.goto(base+'/subjects');await page.locator('.active-session').waitFor();
   assert.equal((await get('/timer')).id,active.id);await page.locator('#theme-toggle').click();
   assert.equal((await get('/timer')).version,active.version);
   await page.goto(base+'/');await page.locator('#timer-actions [data-action=cancel]').click();
   await page.locator('#common-dialog button[type=submit]').click();await page.locator('#common-dialog').waitFor({state:'hidden'});assert.equal(await get('/timer'),null);
   // Accessible focus and dialogs at mobile width, in both themes.
   await page.setViewportSize({width:360,height:800});
   for(const theme of ['light','dark']){
    if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme-toggle').click();
    await page.locator('#manual-session').click();await page.locator('#common-dialog').waitFor({state:'visible'});
    await page.locator('#common-dialog [name=minutes]').fill('12');
    assert(await page.locator('#common-dialog button[type=submit]').isVisible());
    assert(await page.locator('#common-dialog').evaluate(e=>e.getBoundingClientRect().right<=innerWidth));
    await page.screenshot({path:path.join(out,'manual-'+theme+'-360.png')});await page.keyboard.press('Escape');
   }
   await page.goto(base+'/');await page.keyboard.press('Tab');assert.equal(await page.locator(':focus').innerText(),'Pular para o conteúdo');
   await page.keyboard.press('Enter');assert.equal(await page.locator(':focus').getAttribute('id'),'main');
   await page.evaluate(()=>localStorage.setItem('plano.theme','invalid'));await page.reload();assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
   const isolated=await browser.newContext();await isolated.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new Error('Storage unavailable');}}));
   const offlineStorage=await isolated.newPage();offlineStorage.on('pageerror',e=>errors.push(e.message));await offlineStorage.goto(base+'/');
   await offlineStorage.locator('#theme-toggle').click();assert.equal(await offlineStorage.locator('html').getAttribute('data-theme'),'light');await isolated.close();
   // Real empty states after narrowing existing filters, then a recoverable server error.
   await page.goto(base+'/subjects');await page.locator('.subjects-table').waitFor();await page.locator('#subject-search').fill('nao-existe-123');assert.match(await page.locator('#subject-results').innerText(),/Nenhuma disciplina/);
   await page.goto(base+'/projects');await page.locator('.project-card').first().waitFor();await page.locator('#project-search').fill('nao-existe-123');assert.match(await page.locator('#project-cards').innerText(),/Nenhum projeto/);
   await page.goto(base+'/analytics?start=2020-01-01&end=2020-01-02');await page.locator('#analysis-empty').waitFor({state:'visible'});
   await page.route('**/api/analytics?*',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Indisponível para teste'})}));
   await page.locator('#reset-filters').click();await page.locator('#analytics-error').filter({hasText:'Indisponível para teste'}).waitFor();
   assert(await page.locator('#analytics-filters').isVisible());await page.unroute('**/api/analytics?*');await page.locator('#reset-filters').click();await page.locator('#history-body tr').first().waitFor();
  }
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(violations,[]);
  const result={passed:true,phase,out,frames,contrast,errors,external,violations};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{if(browser)await browser.close();if(server.exitCode===null)spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});fs.closeSync(log);}
})().catch(e=>{console.error(e);process.exitCode=1;});

