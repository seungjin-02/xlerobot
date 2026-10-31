'use strict';
// Exercise the production UI through the read-only preview, without robot access.
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const net = require('node:net');
const vm = require('node:vm');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.env.TEST_PYTHON || 'python3', ['tools/preview_ui.py', '--port', String(port)], {cwd: root, stdio: 'ignore'});
  let launchError, browser;
  child.on('error', error => {launchError = error;});
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      if (launchError) throw launchError;
      try {if ((await fetch(base)).ok) {ready = true; break;}} catch {}
      await delay(100);
    }
    if (!ready) throw Error('Preview did not start');
    await fs.mkdir(path.join(root, 'private/control-center-evidence'), {recursive: true});
    browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
    const page = await browser.newPage();
    const external = [];
    await page.route('**/*', route => {
      const url = route.request().url();
      if (!url.startsWith(base + '/')) {external.push(url); return route.abort();}
      return route.continue();
    });
    await page.goto(base);
    await page.locator('#panel').waitFor({state: 'visible'});
    const check = vm.runInNewContext('(' + await fs.readFile(path.join(__dirname, 'mobile_layout.browser.js'), 'utf8') + ')');
    await check(page);
    if (external.length) throw Error('Preview attempted external requests');
    console.log('Mobile preview: three cameras, toolbar spacing, column alignment and mobile overflow passed');
  } finally {
    if (browser) await browser.close();
    if (child.pid && child.exitCode === null) {
      const stopped = new Promise(resolve => child.once('exit', resolve));
      const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
      child.kill();
      await stopped;
      clearTimeout(timer);
    }
  }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
