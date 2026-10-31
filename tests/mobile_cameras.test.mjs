import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const script=readFileSync(new URL('../app/mobile/mobile.js',import.meta.url),'utf8').split("const cameraRoles=['top','left_wrist','right_wrist'];")[1];
function fixture(){let time=0,count=0;const callbacks={},intervals=[],subscriptions=[],revoked=[];const roles=['top','left_wrist','right_wrist'];const images={camera:{hidden:true},cameraLeft:{hidden:true},cameraRight:{hidden:true}},tiles={};for(const role of roles){const nodes={'.camera-placeholder':{hidden:false,textContent:''},'.camera-status':{textContent:''}};tiles[role]={querySelector:q=>nodes[q]};}
 const ui={cameraToggle:{},cameraBox:{}};
 const context=vm.createContext({cameraEnabled:true,Map,Date:{now:()=>time},URL:{createObjectURL:()=>`blob:fixture-${++count}`,revokeObjectURL:u=>revoked.push(u)},document:{getElementById:id=>images[id],querySelector:q=>tiles[q.match(/data-camera="([^"]+)"/)[1]]},$:id=>ui[id],conn:{on:(name,f)=>callbacks[name]=f,subscribe:c=>subscriptions.push(c)},setInterval:f=>intervals.push(f)});
 vm.runInContext("const cameraRoles=['top','left_wrist','right_wrist'];"+script,context);
 return {callbacks,intervals,subscriptions,revoked,images,tiles,ui,setTime:t=>time=t};
}
test('requests all three native camera channels together',()=>{const f=fixture();f.callbacks.link('open');assert.deepEqual(Array.from(f.subscriptions.at(-1)).filter(c=>c.startsWith('camera/')),['camera/top','camera/left_wrist','camera/right_wrist']);});
test('independent frames do not overwrite the other cameras',()=>{const f=fixture();for(const role of ['top','left_wrist','right_wrist'])f.callbacks.camera({camera:role,blob:{}});assert.equal(new Set(Object.values(f.images).map(i=>i.src)).size,3);assert.ok(Object.values(f.images).every(i=>!i.hidden));const top=f.images.camera.src;f.callbacks.camera({camera:'right_wrist',blob:{}});assert.equal(f.images.camera.src,top);assert.equal(f.revoked.length,1);});
test('turning video off unsubscribes all and releases previews',()=>{const f=fixture();for(const role of ['top','left_wrist','right_wrist'])f.callbacks.camera({camera:role,blob:{}});f.ui.cameraToggle.onclick();assert.equal(f.ui.cameraBox.hidden,true);assert.equal(f.subscriptions.at(-1).filter(c=>c.startsWith('camera/')).length,0);assert.equal(f.revoked.length,3);assert.ok(Object.values(f.images).every(i=>i.hidden));});
test('stale camera frames are hidden and marked delayed',()=>{const f=fixture();f.setTime(1);f.callbacks.camera({camera:'top',blob:{}});f.setTime(6001);f.intervals[0]();assert.equal(f.images.camera.hidden,true);assert.equal(f.tiles.top.querySelector('.camera-status').textContent,'수신 지연');});
