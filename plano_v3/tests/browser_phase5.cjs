const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const qa=JSON.parse(fs.readFileSync('docs/phase5-environment.json','utf8'));
const base='http://127.0.0.1:5055';
const documents=process.env.PLANO_REAL_GRADE_FOLDER||'C:/Users/jeanm/OneDrive/Desktop/dowloads';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});
 const evidence={errors:[],steps:[]};
 const modal=page.locator('#common-dialog'),importer=page.locator('#import-dialog');
 const get=async route=>(await page.request.get(base+'/api'+route)).json();
 page.on('pageerror',e=>evidence.errors.push(e.message));
 const close=()=>modal.locator('[data-close]').first().click();
 const storage=async()=>{await page.locator('[data-storage]').click();await modal.locator('#create-backup').waitFor();};
 try{
  assert.equal((await get('/diagnostics')).path,qa.browser_database);
  assert.equal((await get('/courses')).length,0,'Comece com uma base de homologação sem cursos.');
  await page.goto(base+'/subjects');await page.locator('[data-new-course]').waitFor();
  await page.locator('#new-course').click();await modal.locator('[name=name]').fill('Eletrotécnica — homologação');
  await modal.locator('button[type=submit]').click();await modal.waitFor({state:'hidden'});
  const course=(await get('/courses'))[0];
  const file=fs.readdirSync(documents).find(name=>name.startsWith('23_03_2026')&&name.endsWith('.pdf'));
  assert.ok(file,'Cronograma real não encontrado.');
  for(let attempt=0;attempt<2;attempt++){
   await page.locator('[data-import]').first().click();await importer.waitFor({state:'visible'});await importer.locator('[name=file]').setInputFiles(path.join(documents,file));
   const response=page.waitForResponse(r=>r.url().endsWith('/import/preview'));
   await importer.locator('button[type=submit]').click();const preview=await (await response).json();await page.locator('#selection-count').waitFor();
   assert.equal(preview.summary.recognized,26);assert.equal(preview.summary.total_hours,1220);
   assert.ok(preview.items.some(row=>row.name==='Saúde e Segurança no Trabalho'&&row.workload_minutes===720));
   assert.equal((await get('/subjects')).length,attempt*26);
   if(attempt===0){evidence.grade={recognized:26,total_hours:1220,warnings:preview.warnings};await page.screenshot({path:'docs/phase5-real-grade.png'});}
   await page.locator('#confirm-import').click();await importer.waitFor({state:'hidden'});
   assert.equal((await get('/subjects')).length,26);
  }
  evidence.steps.push('Cronograma real: 26 linhas, disciplina de 12 h preservada, prévia sem escrita e reimportação sem duplicar.');
  for(const filename of ['eng eletrica.pdf','eng computacao.pdf']){
   await page.locator('[data-import]').first().click();await importer.waitFor({state:'visible'});await importer.locator('[name=file]').setInputFiles(path.join(documents,filename));
   await importer.locator('button[type=submit]').click();await page.locator('#selection-count').waitFor();
   assert.equal(await importer.locator('[data-field=name]').count(),19);
   await importer.locator('[data-close]').click();
  }
  assert.equal((await get('/subjects')).length,26);
  evidence.steps.push('PDFs das engenharias produzem prévia OCR com 19 disciplinas; cancelar conserva o banco.');
  await page.locator('[data-study]').first().click();await page.waitForURL(base+'/');await page.locator('[data-action=pause]').waitFor();
  await page.waitForTimeout(1100);await page.locator('[data-action=pause]').click();await page.locator('[data-action=resume]').waitFor();
  await page.locator('[data-action=resume]').click();await page.locator('[data-action=pause]').waitFor();
  await page.locator('[data-action=finish]').click();await modal.locator('[name=note]').fill('Homologação com grade real.');
  await modal.locator('button[type=submit]').click();await modal.waitFor({state:'hidden'});
  const recent=await get('/sessions/recent');assert.equal(recent[0].course_name,course.name);
  evidence.steps.push('Disciplina importada inicia estudo diretamente; pausa, retomada e conclusão gravam histórico.');
  await storage();await modal.locator('#create-backup').click();
  assert.equal((await get('/diagnostics')).last_backup,null,'Abrir confirmação não deve criar backup.');
  const downloadEvent=page.waitForEvent('download');await modal.locator('button[type=submit]').click();const download=await downloadEvent;
  const saved=path.join(qa.qa,'browser-backup.db');await download.saveAs(saved);await modal.waitFor({state:'hidden'});
  const diagnostic=await get('/diagnostics');assert.ok(diagnostic.last_backup.created_at);assert.ok(diagnostic.last_backup.available);
  evidence.backup_path=diagnostic.last_backup.path;
  await page.setViewportSize({width:390,height:844});await storage();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'docs/phase5-backup-mobile.png'});
  await modal.locator('#recover-backup').click();
  await modal.locator('[name=file]').setInputFiles(saved);await modal.locator('[name=confirmed]').check();
  const recoveryResponse=page.waitForResponse(r=>r.url().endsWith('/api/backups/recover'));
  await modal.locator('button[type=submit]').click();const recovery=await (await recoveryResponse).json();
  await modal.locator('h2').filter({hasText:'Cópia recuperada'}).waitFor();
  assert.equal(recovery.subjects,26);assert.equal(recovery.active_database_changed,false);
  assert.equal((await get('/diagnostics')).path,qa.browser_database);
  evidence.recovered_path=recovery.path;
  await page.screenshot({path:'docs/phase5-recovery-mobile.png'});await close();
  evidence.steps.push('Backup baixado, data registrada e cópia recuperada pela UI móvel; banco ativo preservado.');
  await storage();await modal.locator('#recover-backup').click();
  await modal.locator('[name=file]').setInputFiles({name:'invalid.db',mimeType:'application/octet-stream',buffer:Buffer.from('not sqlite')});
  await modal.locator('[name=confirmed]').check();await modal.locator('button[type=submit]').click();
  await modal.locator('.form-error').filter({hasText:'incompatível'}).waitFor();await page.keyboard.press('Escape');await modal.waitFor({state:'hidden'});
  await page.goto(base+'/analytics');await page.waitForFunction(()=>document.querySelector('#analytics-results').getAttribute('aria-busy')==='false');
  assert.equal(await page.locator('.chart-card').count(),2);
  const exportEvent=page.waitForEvent('download');await page.locator('#export-csv').click();await (await exportEvent).saveAs(path.join(qa.qa,'history.csv'));
  evidence.steps.push('Backup inválido rejeitado; Escape fecha o formulário; histórico com dois gráficos e CSV baixado.');
  assert.deepEqual(evidence.errors,[]);
  fs.writeFileSync('docs/phase5-ui.json',JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2));
 }catch(error){await page.screenshot({path:'docs/phase5-failure.png'});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
