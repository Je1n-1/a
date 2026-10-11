const fs=require('node:fs');
const {chromium}=require('C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 page.on('response',r=>{if(r.url().includes('/api/'))requests.push({url:r.url(),status:r.status()})});
 await page.goto('http://127.0.0.1:5053/formations');
 await page.waitForSelector('#app[aria-busy="false"]');
 console.log((await page.locator('body').innerText()).slice(0,3500));
 console.log(JSON.stringify({errors,requests}));
 await page.screenshot({path:'docs/v3/ui-empty-formations.png',fullPage:true});
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
