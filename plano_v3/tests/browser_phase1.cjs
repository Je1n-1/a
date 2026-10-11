const fs=require('node:fs');
const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base='http://127.0.0.1:5055';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const evidence={errors:[],httpErrors:[],steps:[]};
 page.on('pageerror',e=>evidence.errors.push(e.message));
 page.on('response',r=>{if(r.status()>=400)evidence.httpErrors.push({url:r.url(),status:r.status()})});
 const get=async path=>(await page.request.get(base+'/api'+path)).json();
 async function createCourse(name){await page.locator('#new-course').click();await page.locator('#common-dialog [name=name]').fill(name);await page.locator('#common-dialog [name=institution]').fill('Curso de teste • Fase 1');await page.locator('#common-dialog button[type=submit]').click();await page.locator('#common-dialog').waitFor({state:'hidden'});}
 async function filePreview(){await page.locator('[data-import]').first().click();await page.locator('#import-dialog [name=file]').setInputFiles('static/downloads/modelo_grade_curricular.xlsx');await page.locator('#import-dialog button[type=submit]').click();await page.locator('#selection-count').waitFor();}
 try{
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#timer-status').textContent==='Pronto para começar');
  await page.screenshot({path:'docs/phase1-today-empty.png',fullPage:true});
  await page.goto(base+'/subjects');await page.locator('[data-new-course]').waitFor();
  await createCourse('Engenharia Elétrica');
  await filePreview();
  assert.equal(await page.locator('[data-field=include]:checked').count(),0);
  assert.equal(await page.locator('#confirm-import').isDisabled(),true);
  assert.equal((await get('/subjects')).length,0);
  await page.screenshot({path:'docs/phase1-import-preview.png',fullPage:true});
  await page.locator('#select-all').check();
  await page.locator('[data-field=code][data-index="0"]').fill('001');
  await page.locator('[data-field=hours][data-index="0"]').fill('47.5');
  await page.locator('#confirm-import').click();await page.locator('#import-dialog').waitFor({state:'hidden'});
  let rows=await get('/subjects');assert.equal(rows.length,3);assert.equal(rows.find(x=>x.code==='001').workload_minutes,2850);
  evidence.steps.push('Modelo: 3 identificadas, 0 selecionadas; seleção em lote, edição e gravação de 3.');
  await filePreview();await page.locator('#select-all').check();await page.locator('#confirm-import').click();await page.locator('#import-dialog').waitFor({state:'hidden'});
  assert.equal((await get('/subjects')).length,3);
  evidence.steps.push('Reimportação sem duplicatas.');
  await createCourse('Engenharia da Computação');
  await page.locator('[data-import]').first().click();await page.locator('[data-tab=text]').click();
  await page.locator('#import-dialog [name=text]').fill('Disciplina\tCódigo\tPeríodo\tCarga (h)\nCircuitos Elétricos I\t001\t1º semestre\t45\nÁlgebra Linear\t002\t1º semestre\t60');
  await page.locator('#import-dialog button[type=submit]').click();await page.locator('#selection-count').waitFor();
  await page.locator('#confirm-import').click();await page.locator('#import-dialog').waitFor({state:'hidden'});
  rows=await get('/subjects');assert.equal(rows.length,5);assert.equal(rows.filter(x=>x.name==='Circuitos Elétricos I').length,2);
  evidence.steps.push('Dois cursos com disciplina homônima e códigos 001 preservados.');
  await page.reload();await page.locator('[data-study]').first().waitFor();
  await page.screenshot({path:'docs/phase1-subjects.png',fullPage:true});
  await page.locator('[data-study]').first().click();await page.waitForURL(base+'/');await page.waitForFunction(()=>document.querySelector('#timer-status').textContent==='Em estudo');
  const active=await get('/timer');assert.ok(active.subject_id);evidence.activeId=active.id;
  await page.reload();await page.waitForFunction(()=>document.querySelector('#timer-status').textContent==='Em estudo');
  assert.equal((await get('/timer')).id,active.id);
  const second=await browser.newPage();await second.goto(base);await second.waitForFunction(()=>document.querySelector('#timer-status').textContent==='Em estudo');await second.close();
  await page.waitForTimeout(1200);
  await page.locator('[data-action=pause]').click();await page.waitForFunction(()=>document.querySelector('#timer-status').textContent==='Em pausa');
  await page.screenshot({path:'docs/phase1-timer.png',fullPage:true});
  await page.locator('[data-action=resume]').click();await page.waitForFunction(()=>document.querySelector('#timer-status').textContent==='Em estudo');
  await page.locator('[data-action=finish]').click();await page.locator('#common-dialog [name=note]').fill('Sessão de verificação: revisão de conceitos.');await page.locator('#common-dialog button[type=submit]').click();await page.locator('#common-dialog').waitFor({state:'hidden'});
  assert.equal(await get('/timer'),null);assert.equal((await get('/sessions/recent')).length,1);
  evidence.steps.push('Estudar em um clique; recarga e segunda aba recuperam o timer; pausa, retomada e finalização criam uma sessão.');
  await page.setViewportSize({width:390,height:844});await page.reload();await page.waitForFunction(()=>document.querySelector('#timer-status').textContent==='Pronto para começar');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'docs/phase1-mobile-today.png',fullPage:true});
  await page.goto(base+'/subjects');await page.locator('[data-import]').first().waitFor();await filePreview();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'docs/phase1-mobile-import.png',fullPage:true});
  await page.locator('#import-dialog [data-close]').click();
  await page.goto(base+'/analytics');assert.match(await page.locator('main').innerText(),/Próxima etapa/);
  evidence.steps.push('390px: Hoje e prévia sem overflow da página; Análises identificada como próxima etapa.');
  evidence.diagnostics=await get('/diagnostics');
  assert.deepEqual(evidence.errors,[]);assert.deepEqual(evidence.httpErrors,[]);
 }catch(error){evidence.failure=error.stack;await page.screenshot({path:'docs/phase1-failure.png',fullPage:true});process.exitCode=1;}
 finally{fs.writeFileSync('docs/phase1-ui.json',JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
