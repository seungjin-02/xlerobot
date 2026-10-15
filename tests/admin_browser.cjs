'use strict';
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const fs=require('node:fs/promises');
const path=require('node:path');
const net=require('node:net');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function main(){
 const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const python=process.env.TEST_PYTHON||path.join(root,'.venv/bin/python');
 const child=spawn(python,['tests/admin_fixture.py','--port',String(port)],{cwd:root,stdio:['ignore','ignore','pipe']});let log='';child.stderr.on('data',d=>log+=d);child.on('error',e=>log+=e.message);
 let browser;const passed=[];
 try{
  const base=`http://127.0.0.1:${port}`;
  let ready=false;for(let i=0;i<100;i++){try{if((await fetch(base)).ok){ready=true;break;}}catch{}await delay(100);}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,args:['--no-sandbox']});const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.locator('#password').fill('wrong-admin-fixture');await page.locator('#login button').click();await page.waitForFunction(()=>document.getElementById('error').textContent.includes('login_failed'));assert.equal(await page.locator('#panel').isVisible(),false);passed.push('separate administrator login rejects normal credentials');
  await page.locator('#password').fill('separate-admin-fixture');await page.locator('#login button').click();await page.locator('#panel').waitFor({state:'visible'});assert.equal(await page.locator('#password').inputValue(),'');passed.push('administrator login and cleared password');
  await page.locator('#check').click();await page.locator('#release option[value="'+ 'b'.repeat(40)+'"]').waitFor({state:'attached'});await page.locator('#release').selectOption('b'.repeat(40));assert.equal(await page.locator('#apply').isDisabled(),true);assert.ok((await page.locator('#notes').innerText()).includes('<script>'));assert.equal(await page.evaluate(()=>window.pwned),undefined);passed.push('release notes are text and physical confirmation required');
  const dir=path.join(root,'private/control-center-evidence');await fs.mkdir(dir,{recursive:true});await page.screenshot({path:path.join(dir,'admin-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:path.join(dir,'admin-mobile.png'),fullPage:true});
  await page.locator('#isolated').check();await page.locator('#apply').click();await page.waitForFunction(()=>document.getElementById('status').textContent.includes('succeeded'),null,{timeout:20000});passed.push('approved synthetic update completes and status survives application transition');
  await page.locator('#logout').click();await page.locator('#login').waitFor({state:'visible'});const result=await page.request.get(base+'/api/status');assert.equal(result.status(),401);assert.deepEqual(errors,[]);passed.push('logout revokes administrator session');
  await fs.writeFile(path.join(dir,'admin-browser-results.json'),JSON.stringify({synthetic:true,physical_hardware_tested:false,passed,js_errors:errors},null,2));console.log('PASS: '+passed.length+' administrator Chromium scenarios\n'+passed.join('\n'));
 }finally{if(browser)await browser.close();if(child.exitCode===null){child.kill('SIGTERM');await new Promise(r=>child.once('exit',r));}}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
