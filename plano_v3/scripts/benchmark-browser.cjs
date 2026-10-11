const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const median=v=>v.sort((a,b)=>a-b)[Math.floor(v.length/2)];
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const report={};
 try{for(const route of ['/','/analytics?start=2026-09-11&end=2026-10-10']){
  const trials=[];
  for(let i=0;i<5;i++){
   const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
   const calls=[];const errors=[];
   page.on('request',r=>{if(r.url().includes('/api/'))calls.push(new URL(r.url()).pathname)});
   page.on('pageerror',e=>errors.push(e.message));
   await page.goto(`http://127.0.0.1:${process.argv[2]}${route}`);
   await page.waitForFunction(route=>route==='/'?document.querySelector('#today-total').textContent!=='—':document.querySelector('#analytics-results').getAttribute('aria-busy')==='false',route);
   const timing=await page.evaluate(()=>({ready_ms:performance.now(),resources:performance.getEntriesByType('resource').map(x=>({name:new URL(x.name).pathname,bytes:x.decodedBodySize}))}));
   if(errors.length)throw Error(errors.join('\n'));
   trials.push({...timing,calls});await context.close();
  }
  report[route]={median_ready_ms:Math.round(median(trials.map(x=>x.ready_ms))),api_calls:trials[2].calls,
      javascript_bytes:trials[2].resources.filter(r=>r.name.endsWith('.js')).reduce((sum,r)=>sum+r.bytes,0),
      javascript_modules:trials[2].resources.filter(r=>r.name.endsWith('.js')).map(r=>r.name),trials:trials.map(x=>Math.round(x.ready_ms))};
 }}finally{await browser.close();}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
