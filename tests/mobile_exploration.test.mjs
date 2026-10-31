import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
const base=readFileSync(new URL('../app/mobile/mission.js',import.meta.url),'utf8');
const url='data:text/javascript;base64,'+Buffer.from(base).toString('base64');
const source=readFileSync(new URL('../app/mobile/exploration_mission.js',import.meta.url),'utf8').replace('./mission.js',url);
const {ExplorationMission}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
function setup(){let time=0;const calls=[];const m=new ExplorationMission(async(path,body)=>{calls.push({path,body});return{ok:true};},()=>time);const s={pose:{map:{x:0,y:0,yaw:0}},navigation:{state:'idle'},processes:{mapping:{state:'running'},save_map:{state:'idle'}}};return{m,s,calls,setTime:t=>time=t};}
const opts={mode:'explore',seconds:60,radius:3};
test('time-bound exploration saves, localizes and returns through native APIs',async()=>{const{m,s,calls,setTime}=setup();await m.start(opts,s);s.pose.map.x=1;setTime(61);await m.observe(s);assert.equal(m.state,'saving_map');assert.equal(calls.at(-1).path,'/api/map/save');s.processes.save_map={state:'running'};await m.observe(s);s.processes.save_map={state:'succeeded',map:'room.yaml'};await m.observe(s);assert.equal(m.state,'starting_navigation');assert.equal(calls.at(-1).body.options.map,'room.yaml');s.processes.navigation={state:'running'};await m.observe(s);assert.equal(calls.at(-1).path,'/api/nav/initial_pose');s.navigation.is_localized=true;await m.observe(s);assert.equal(calls.at(-1).path,'/api/nav/goal');assert.equal(calls.at(-1).body.x,0);s.navigation.state='active';await m.observe(s);s.pose.map.x=0;s.navigation.state='succeeded';await m.observe(s);assert.equal(m.state,'complete');});
test('stale saved map status is not used to return',async()=>{const{m,s,calls,setTime}=setup();await m.start(opts,s);setTime(61);await m.observe(s);s.processes.save_map={state:'succeeded',map:'old.yaml'};await m.observe(s);assert.equal(m.state,'saving_map');assert.equal(calls.filter(c=>c.path==='/api/process/start').length,0);});
test('lost localization stops exploration without starting navigation',async()=>{const{m,s,calls}=setup();await m.start(opts,s);s.pose.map=null;await m.observe(s);assert.equal(m.state,'failed');assert.equal(calls.at(-1).path,'/api/explore/stop');});
test('radius limit requests stop before save or navigation',async()=>{const{m,s,calls}=setup();await m.start(opts,s);s.pose.map.x=3.1;await m.observe(s);assert.equal(calls[1].path,'/api/explore/stop');assert.equal(m.state,'saving_map');});
