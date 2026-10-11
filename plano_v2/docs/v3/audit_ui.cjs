const fs=require('node:fs');
const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const result={errors:[],responses:[],steps:[]};
 page.on('pageerror',e=>result.errors.push(e.message));
 page.on('response',r=>{if(r.url().includes('/api/')||r.status()>=400)result.responses.push({url:r.url(),status:r.status()})});
 try {
  await page.goto('http://127.0.0.1:5053/formations');
  await page.waitForSelector('#app[aria-busy="false"]');
  result.diagnostics=await (await page.request.get('http://127.0.0.1:5053/api/diagnostics')).json();
  await page.locator('[data-new-formation]').first().click();
  await page.locator('#modal-root [name="name"]').fill('Curso de auditoria UI');
  await page.locator('#modal-root .button.primary').click();
  await page.waitForSelector('#modal-root .modal',{state:'detached'});
  await page.locator('[data-formation-tab="curriculum"]').click();
  await page.locator('[data-import]').click();
  await page.locator('[name="curriculum_file"]').setInputFiles('static/downloads/modelo_grade_curricular.xlsx');
  await page.locator('#modal-root .button.primary').click();
  await page.waitForSelector('[data-import-include]');
  result.steps.push({step:'preview',rows:await page.locator('[data-import-include]').count(),selected:await page.locator('[data-import-include]:checked').count()});
  await page.screenshot({path:'docs/v3/ui-preview-unselected.png',fullPage:true});
  await page.locator('#modal-root .button.primary').click();
  result.steps.push({step:'confirm_zero',error:await page.locator('[data-form-error]').innerText()});
  assert.match(result.steps.at(-1).error,/Selecione ao menos/);
  await page.locator('[data-import-include="0"]').check();
  await page.locator('#modal-root .button.primary').click();
  await page.waitForSelector('#modal-root .modal',{state:'detached'});
  await page.reload();
  await page.waitForSelector('#app[aria-busy="false"]');
  const formations=await (await page.request.get('http://127.0.0.1:5053/api/formations')).json();
  const fid=formations.find(x=>x.name==='Curso de auditoria UI').id;
  const rows=await (await page.request.get(`http://127.0.0.1:5053/api/formations/${fid}/curriculum`)).json();
  assert.equal(rows.length,1);
  result.steps.push({step:'persisted_after_reload',count:rows.length});
  await page.screenshot({path:'docs/v3/ui-import-persisted.png',fullPage:true});
  for(const path of ['/','/focus','/history','/analytics']) {
   const start=Date.now();
   await page.goto('http://127.0.0.1:5053'+path);
   if(path!='/focus')await page.waitForSelector('#app[aria-busy="false"]');
   else await page.waitForFunction(()=>!document.querySelector('#focus-app')?.textContent.includes('Carregando'));
   result.steps.push({step:'page',path,load_ms:Date.now()-start,text:(await page.locator('main').innerText()).slice(0,650)});
  }
  await page.setViewportSize({width:390,height:844});
  await page.goto('http://127.0.0.1:5053/');
  await page.waitForSelector('#app[aria-busy="false"]');
  await page.screenshot({path:'docs/v3/ui-today-mobile.png',fullPage:true});
 } catch(e){result.failure=e.stack;await page.screenshot({path:'docs/v3/ui-failure.png',fullPage:true});process.exitCode=1;}
 finally {fs.writeFileSync('docs/v3/ui_evidence.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
