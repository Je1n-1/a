const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const qa=JSON.parse(fs.readFileSync('docs/ocr-environment.json','utf8'));
const base='http://127.0.0.1:5055';
const directory=process.env.PLANO_REAL_GRADE_FOLDER||'C:/Users/jeanm/OneDrive/Desktop/dowloads';
const common=['Formação Inicial em Educação a Distância','Matemática Elementar','Metodologia Científica','Relações Étnico-raciais: Africana, Afro-brasileira e Indígena'];
const cases=[
 {file:fs.readdirSync(directory).find(x=>x.startsWith('23_03_2026')),name:'Eletrotécnica',count:26,hours:1220},
 {file:'eng eletrica.pdf',name:'Engenharia Elétrica',count:19,hours:735,names:[...common,'Engenharia Elétrica e Profissão','Formação Cidadã Contemporânea','Pré-Cálculo','Cálculo Diferencial e Integral a Uma Variável','Geometria Analítica','Química Geral','Desenho Técnico Elétrico','Lógica de Programação e Algoritmos','Produção de Texto','Ética e Legislação do Curso','Linguagem de Programação','Probabilidade e Estatística','Cálculo Diferencial e Integral a Várias Variáveis','Física: Eletricidade','Gestão de Projetos']},
 {file:'eng computacao.pdf',name:'Engenharia da Computação',count:19,hours:735,names:[...common,'Formação Cidadã Contemporânea','O Engenheiro de Computação e a Profissão','Pré-Cálculo','Desenho Técnico Elétrico','Produção Textual','Raciocínio Lógico','Lógica de Programação e Algoritmos','Matemática Computacional','Química Geral','Cálculo Diferencial e Integral a Uma Variável','Física: Mecânica','Geometria Analítica e Álgebra Linear','Cálculo Diferencial e Integral a Várias Variáveis','Ferramentas Matemáticas Aplicadas','Materiais Elétricos']}
];
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(60000);
 const errors=[],results=[];page.on('pageerror',e=>errors.push(e.message));
 const get=async url=>(await page.request.get(base+'/api'+url)).json();
 const modal=page.locator('#common-dialog'),importer=page.locator('#import-dialog');
 try{
  assert.equal((await get('/diagnostics')).path,qa.browser_database);assert.equal((await get('/courses')).length,0);
  for(const item of cases){
   await page.goto(base+'/subjects');await page.locator('#new-course').click();await modal.locator('[name=name]').fill(item.name);await modal.locator('button[type=submit]').click();await modal.waitFor({state:'hidden'});
   const course=(await get('/courses')).find(c=>c.name===item.name);let preview;
   for(let attempt=0;attempt<2;attempt++){
    const before=(await get('/subjects')).length;
    await page.locator('[data-import]').first().click();await importer.waitFor({state:'visible'});await importer.locator('[name=file]').setInputFiles(path.join(directory,item.file));
    const response=page.waitForResponse(r=>r.url().endsWith('/import/preview'));await importer.locator('button[type=submit]').click();const r=await response;assert.equal(r.status(),200,await r.text());preview=await r.json();
    await page.locator('#selection-count').waitFor();assert.equal(preview.summary.recognized,item.count);assert.equal(preview.summary.total_hours,item.hours);assert.equal((await get('/subjects')).length,before);
    if(item.names){
     assert.deepEqual(preview.items.map(r=>r.name),item.names);
     assert.deepEqual(preview.items.map(r=>r.workload_minutes),[...Array(4).fill(900),...Array(15).fill(2700)]);
     assert.ok(preview.items.every(r=>r.period.startsWith('UCFC ')));
     assert.equal(preview.ocr.repeated_rows,57);assert.match(await importer.textContent(),/mesmo trecho repetido/);
    }else assert.ok(preview.items.some(r=>r.name==='Saúde e Segurança no Trabalho'&&r.workload_minutes===720));
    if(!attempt)await page.screenshot({path:`docs/ocr-preview-${course.id}.png`});
    const confirmed=page.waitForResponse(r=>r.url().endsWith('/import/confirm'));
    await page.locator('#confirm-import').click();const saved=await(await confirmed).json();await importer.waitFor({state:'hidden'});
    assert.equal(saved.inserted,attempt?0:item.count);assert.equal(saved.ignored,attempt?item.count:0);
    assert.equal((await get('/subjects')).filter(s=>s.course_id===course.id).length,item.count);
   }
   await page.locator('[data-study]').first().click();await page.waitForURL(base+'/');await page.locator('[data-action=pause]').waitFor();await page.waitForTimeout(1100);
   await page.locator('[data-action=finish]').click();await modal.locator('button[type=submit]').click();await modal.waitFor({state:'hidden'});
   assert.equal((await get('/sessions/recent'))[0].course_name,item.name);
   results.push({file:item.file,course_id:course.id,recognized:item.count,hours:item.hours,ocr:preview.ocr||null,confirmed:true,reimport_no_duplicates:true,study_finished:true});
  }
  const all=await get('/subjects');assert.equal(all.length,64);assert.equal(all.filter(s=>s.name===common[0]).length,2);
  await page.goto(base+'/subjects?course=3');await page.locator('[data-import]').first().click();await importer.waitFor({state:'visible'});await page.setViewportSize({width:390,height:844});await importer.locator('[name=file]').setInputFiles(path.join(directory,'eng computacao.pdf'));await importer.locator('button[type=submit]').click();await page.locator('#selection-count').waitFor();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'docs/ocr-preview-mobile.png'});
  assert.deepEqual(errors,[]);const evidence={errors,results,total_subjects:64,sessions:3};fs.writeFileSync('docs/ocr-ui.json',JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2));
 }catch(error){await page.screenshot({path:'docs/ocr-failure.png'});throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
