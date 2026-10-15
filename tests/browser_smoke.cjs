/* Real Chromium integration tests against an isolated synthetic server, no motors. */
'use strict';
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const {existsSync} = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(check, description) {
  for(let count=0;count<100;count++) { if(await check()) return; await delay(100); }
  throw new Error('Timed out: '+description);
}
async function freePort() {
  const server = net.createServer();
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const port=server.address().port; await new Promise(resolve=>server.close(resolve)); return port;
}
async function stopChild(child) {
  if(!child.pid || child.exitCode!==null || child.signalCode!==null)return;
  const exited=new Promise(resolve=>child.once('exit',resolve));
  const deadline=setTimeout(()=>child.kill('SIGKILL'),5000);
  try {child.kill('SIGTERM');await exited;}finally{clearTimeout(deadline);}
}
async function main() {
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'lekiwi-browser-'));
  const port=await freePort(), base=`http://127.0.0.1:${port}`;
  const python=process.env.TEST_PYTHON || path.join(root,'.venv/bin/python');
  const child=spawn(python,['app/server.py','--demo','--host','127.0.0.1','--port',String(port),'--recordings',directory],{cwd:root,stdio:['ignore','pipe','pipe']});
  let serverLog=''; child.stderr.on('data',data=>serverLog+=data.toString());
  child.on('error',error=>{serverLog+=error.message;});
  let browser;
  const passed=[];
  const artifacts=path.join(root,'private/control-center-evidence'); await fs.mkdir(artifacts,{recursive:true});
  try {
    await waitFor(async()=>{try{return (await fetch(base+'/health')).ok;}catch{return false;}},'server health');
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || (existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined),args:['--no-sandbox']});
    const context=await browser.newContext({viewport:{width:390,height:844},acceptDownloads:true});
    const page=await context.newPage();
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base);await page.locator('#pin').fill('12345678');await page.locator('#pairForm button').click();
    await page.locator('#panel').waitFor({state:'visible'});
    const status=async()=> (await context.request.get(base+'/api/status')).json();
    await page.locator('#cameraToggle').click();
    await page.waitForFunction(()=>document.getElementById('camera').naturalWidth===640);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(artifacts,'drive-mobile.png'),fullPage:true});
    passed.push('PIN, demo camera, mobile layout');

    await page.locator('#arm').click();await waitFor(async()=>(await status()).armed,'arm');
    await page.locator('[data-dir="forward"]').click();
    await waitFor(async()=>(await status()).output_motion[0]>0,'synthetic forward motion');
    await page.locator('nav [data-screen="record"]').click();
    await page.locator('#screen-record').waitFor({state:'visible'});
    let current=await status();assert.equal(current.mine,true);assert.deepEqual(current.output_motion,[0,0,0]);
    await page.locator('#task').fill('브라우저 합성 시범');await page.locator('#recordStart').click();
    await waitFor(async()=>(await status()).recording.active,'record start');
    await page.locator('nav [data-screen="drive"]').click();await page.locator('[data-dir="forward"]').click();
    await delay(800);await page.locator('nav [data-screen="record"]').click();
    await waitFor(async()=>(await status()).recording.samples>=10,'valid samples');
    current=await status();assert.equal(current.recording.active,true);assert.equal(current.mine,true);
    assert.deepEqual(current.output_motion,[0,0,0]);
    await page.screenshot({path:path.join(artifacts,'record-mobile.png'),fullPage:true});
    passed.push('moving screen transition sends idle and keeps lease/recording');
    await page.locator('[data-outcome="success"]').click();
    await waitFor(async()=>!(await status()).recording.active && !(await status()).armed,'record finish and stop');
    const downloadEvent=page.waitForEvent('download'); await page.locator('#episodes a').first().click();
    const download=await downloadEvent;assert.equal(await download.failure(),null);
    assert.match(download.suggestedFilename(),/\.zip$/);
    passed.push('record finish, stop and authenticated ZIP download');

    await page.locator('nav [data-screen="system"]').click();
    await page.locator('#systemInfo dt').first().waitFor();
    assert.match(await page.locator('#systemInfo').innerText(),/Git 커밋/);
    await page.screenshot({path:path.join(artifacts,'system-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1280,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(artifacts,'system-desktop.png'),fullPage:true});
    await page.locator('nav [data-screen="drive"]').click();
    await waitFor(async()=>await page.locator('nav [data-screen="drive"]').getAttribute('aria-current')==='page' && !(await page.locator('nav [data-screen="drive"]').isDisabled()),'drive navigation complete');
    await page.screenshot({path:path.join(artifacts,'drive-desktop.png'),fullPage:true});
    passed.push('read-only system information and desktop layout');

    await page.locator('#arm').click();await waitFor(async()=>(await status()).armed,'rearm');
    await page.locator('[data-dir="forward"]').click();
    await waitFor(async()=>(await status()).output_motion[0]>0,'movement before blur');
    await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
    await waitFor(async()=>!(await status()).armed,'blur stop');
    passed.push('browser blur stops synthetic control');

    await page.locator('#arm').click();await waitFor(async()=>(await status()).armed,'arm before reconnect');
    await page.locator('[data-dir="forward"]').click();
    await waitFor(async()=>(await status()).output_motion[0]>.01,'motion before reconnect');
    await page.route('**/api/command',route=>route.abort());
    await page.route('**/api/status',route=>route.abort());
    await delay(1000);
    assert.equal((await status()).mine,true);
    await page.unroute('**/api/command');await page.unroute('**/api/status');
    await waitFor(async()=>!(await status()).reconnecting,'reconnect within grace');
    assert.equal((await status()).mine,true);
    await page.locator('#stop').click();await waitFor(async()=>!(await status()).armed,'stop after reconnect');
    passed.push('transient command/status loss reconnects within existing grace without losing lease');

    // Hidden event follows the same production handler, while the real page is kept inspectable.
    await page.locator('#arm').click();await waitFor(async()=>(await status()).armed,'rearm before hidden');
    await page.evaluate(()=>{
      Object.defineProperty(document,'hidden',{configurable:true,value:true});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(async()=>!(await status()).armed,'hidden beacon stop');
    await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
    passed.push('hidden visibility handler stops synthetic control');

    // Delay an arm response after the server already armed, then blur before it reaches the UI.
    await page.route('**/api/arm',async route=>{const response=await route.fetch();await delay(500);await route.fulfill({response});});
    await page.locator('#arm').click();await waitFor(async()=>(await status()).armed,'delayed arm');
    await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
    await delay(900);assert.equal((await status()).armed,false);
    assert.equal(await page.locator('#arm').textContent(),'조종 시작');
    await page.unroute('**/api/arm');
    passed.push('late arm response cannot restore control after blur');

    // A failed navigation-idle and failed stop must preserve the stop warning and screen.
    await page.locator('#arm').click();await waitFor(async()=>(await status()).armed,'rearm before network loss');
    await page.route('**/api/command',route=>route.abort());
    await page.route('**/api/stop',route=>route.abort());
    await page.locator('nav [data-screen="system"]').click();
    await waitFor(async()=> (await page.locator('#message').innerText()).includes('정지 명령이 전달되지 않았습니다'),'stop warning');
    assert.equal(await page.locator('#screen-drive').isVisible(),true);
    await page.unroute('**/api/command');await page.unroute('**/api/stop');
    await context.request.post(base+'/api/stop',{data:{},headers:{Origin:base}});
    passed.push('navigation failure stays on drive and retains stop delivery warning');
    assert.deepEqual(errors,[]);
    await context.close();
    const portalPort=await freePort();
    const portal=spawn(python,['-m','http.server',String(portalPort),'--bind','127.0.0.1','--directory','site'],{cwd:root,stdio:'ignore'});
    try {
      const portalBase=`http://127.0.0.1:${portalPort}`;
      await waitFor(async()=>{try{return (await fetch(portalBase)).ok;}catch{return false;}},'static portal');
      const portalPage=await browser.newPage({viewport:{width:1280,height:900}});
      await portalPage.goto(portalBase);
      assert.equal((await portalPage.locator('h1').innerText()).includes('기록하세요'),true);
      await portalPage.screenshot({path:path.join(artifacts,'portal-desktop.png'),fullPage:true});
      await portalPage.setViewportSize({width:390,height:844});
      assert.equal(await portalPage.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      await portalPage.screenshot({path:path.join(artifacts,'portal-mobile.png'),fullPage:true});
      await portalPage.close();passed.push('static installation portal desktop and mobile layout');
    } finally { await stopChild(portal); }
    await fs.writeFile(path.join(artifacts,'browser-results.json'),JSON.stringify({demo:true,physical_hardware_tested:false,passed,js_errors:errors},null,2));
    console.log('PASS: '+passed.length+' Chromium scenarios\n'+passed.join('\n'));
  } catch(error) {
    console.error(serverLog);throw error;
  } finally {
    if(browser)await browser.close();
    await stopChild(child);
    await fs.rm(directory,{recursive:true,force:true});
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
