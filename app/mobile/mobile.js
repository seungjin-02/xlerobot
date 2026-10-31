import {ExplorationMission} from './exploration_mission.js';
import {Connection} from './native/connection.js';
import {createMapView} from './native/widgets/map_view.js';
const aliases={main:'panel',pair:'pairForm',link:'badge',notice:'message',cameraRole:'cameraSelect',driveCamera:'camera',cameraState:'cameraError',readiness:'state',speedLabel:'speedValue',speedSource:'limitNote',zero:'stop'};
const $=id=>document.getElementById(aliases[id]??id),tell=m=>{$('notice').textContent=m??'';};
let arming=false,startGeneration=0,directionKey=null,cameraEnabled=true;
const DIR={forward:[1,0,0],back:[-1,0,0],left:[0,1,0],right:[0,-1,0],turn_left:[0,0,1],turn_right:[0,0,-1]};

function nativeLevel(){const levels=status?.teleop?.pads?.drive?.levels??[];const requested=.03*Number($('speed').value);let level=0;levels.forEach((p,i)=>{if(p[0]<=requested+1e-6)level=i;});return level;}
function pressed(){document.querySelectorAll('[data-dir]').forEach(b=>{const on=b.dataset.dir===directionKey;b.classList.toggle('pressed',on);b.setAttribute('aria-pressed',String(on));});}
const conn=new Connection(tell);
const mission=new ExplorationMission((path,body)=>conn.post(path,body));let updatingMission=false;let route=[];let diagnostics=null;let status=null,tab='drive',direction=null,target=null;
const mapping=createMapView($('mappingView'));
const navigation=createMapView($('navigationView'),(tool,pose)=>{if(tool==='initial')conn.post('/api/nav/initial_pose',pose);else{target=pose;navigation.setGoal(pose);tell('목표를 선택했습니다.');}});
function stop(){direction=null;directionKey=null;pressed();conn.send({type:'teleop',pad:'drive',level:0,x:0,y:0,yaw:0});}
function post(path,data={}){stop();return conn.post(path,data);}
function open(){$('login').hidden=true;$('main').hidden=false;conn.subscribe(['map','scan','plan','odom','motors']);conn.connect();}
$('pair').onsubmit=async e=>{e.preventDefault();$('loginError').hidden=true;$('loginError').textContent='';$('pin').removeAttribute('aria-invalid');try{if(!/^\d{4,8}$/.test($('pin').value))throw Error('접속 코드는 숫자 4~8자리로 입력하세요.');const r=await fetch('/api/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:$('pin').value})});$('pin').value='';const d=await r.json();if(!r.ok)throw Error(d.error);open();}catch(err){$('loginError').textContent=err.message==='Failed to fetch'?'로봇에 연결할 수 없습니다. Wi-Fi 연결을 확인하세요.':err.message;$('loginError').hidden=false;$('pin').setAttribute('aria-invalid','true');$('pin').focus();}};
fetch('/api/status').then(r=>{if(r.ok)open();}).catch(()=>{});
function render(){
 for(const id of ['bringup','powerOn','powerOff','mappingStart','mappingStop','mapSave','navStart','missionStart','navSpeed'])if($(id))$(id).disabled=!conn.isOpen;
 document.querySelectorAll('[data-api]').forEach(b=>b.disabled=!conn.isOpen);
 const missing=Object.entries(diagnostics?.devices??{}).filter(([name,ok])=>['lekiwi_motor','ydlidar'].includes(name)&&!ok).map(([name])=>name);
 if(missing.length)for(const id of ['bringup','powerOn','mappingStart','navStart','missionStart'])if($(id))$(id).disabled=true;
 const levels=status?.teleop?.pads?.drive?.levels??[];
 $('speed').disabled=!levels.length;
 const level=levels[nativeLevel()];$('speedLabel').textContent=$('speed').value+'배';$('speedDetail').textContent=level?`적용 가능한 이동 ${level[0].toFixed(2)} m/s · 회전 ${level[1].toFixed(2)} rad/s`:'속도 정책 응답 대기';document.querySelectorAll('[data-speed]').forEach(b=>b.classList.toggle('selected',b.dataset.speed===$('speed').value));
 $('speedSource').textContent=levels.length?`최대 ${levels.at(-1)[0].toFixed(2)} m/s · ${status?.teleop?.limits?.source==='default'?'베이스 피드백 대기 중인 엔진 기본 상한':'로보시지 베이스에서 읽은 상한'}`:'속도 정책 응답 대기';
 $('readiness').textContent=missing.length?'USB 장치 미인식 · 전원을 끄고 허브·전원·케이블 점검이 필요합니다.':status?.teleop?.blocked_reason??'로봇 상태를 확인하세요';
 document.querySelectorAll('[data-dir]').forEach(b=>b.disabled=arming||mission.busy||!status?.teleop?.is_allowed);
 $('arm').disabled=arming||!conn.isOpen||!!missing.length||mission.busy||status?.motor?.ready===true;
 $('arm').textContent=arming?'준비 중…':status?.motor?.ready?'조종 중':'조종 시작';
 $('motorState').textContent=`모터 준비 피드백: ${status?.motor?.ready===true?'준비됨':status?.motor?.ready===false?'비활성':'확인 불가'}`;
 $('controlSummary').textContent=`${conn.isOpen?'로봇 연결됨':'연결 확인 필요'} · ${status?.control?.holder?'제어권 사용 중':'조종 대기'}`;pressed();
 const stateLabel={stopped:'대기',running:'실행 중',external:'외부에서 실행 중',starting:'준비 중',stopping:'종료 중',idle:'대기',succeeded:'저장 완료',failed:'오류'};const mapState=status?.processes?.mapping?.state,saveState=status?.processes?.save_map?.state;$('mappingState').textContent=`지도 생성: ${stateLabel[mapState]??'미확인'} · 저장: ${stateLabel[saveState]??'미확인'}`;
 mapping.setRobot(status?.pose?.map);navigation.setRobot(status?.pose?.map);navigation.setToolsEnabled(conn.isOpen);
 const sys=status?.system??{},gib=n=>Number.isFinite(n)?(n/1073741824).toFixed(2)+' GB':'미확인';
 const facts={'연결':conn.isOpen?'정상':'끊김','CPU 사용률':sys.cpu_percent==null?'미확인':sys.cpu_percent+'%','CPU 온도':sys.cpu_temp==null?'미확인':sys.cpu_temp+' °C','메모리':gib(sys.memory_used)+' / '+gib(sys.memory_total),'저장장치 사용률':sys.disk_percent==null?'미확인':sys.disk_percent+'%','가동 시간':sys.uptime==null?'미확인':Math.floor(sys.uptime/60)+'분','ROS 도메인':status?.ros?.domain_id??'미확인','USB 모터':diagnostics?.devices?.lekiwi_motor?'인식됨':'미인식','USB LiDAR':diagnostics?.devices?.ydlidar?'인식됨':'미인식','바퀴 준비':status?.motor?.ready===true?'준비됨':status?.motor?.ready===false?'비활성':'피드백 없음','제어권':status?.control?.holder?'사용 중':'대기','트롤리 외곽':'45 × 35 × 77 cm','충돌 계산 반경':'30 cm','저전압':sys.throttled?.is_undervoltage_now?'감지됨':'현재 감지 없음','지도 생성':status?.processes?.mapping?.state??'미확인','내비게이션':status?.processes?.navigation?.state??'미확인'};
 $('systemFacts').replaceChildren();for(const[key,value]of Object.entries(facts)){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=String(value);$('systemFacts').append(dt,dd);}
 $('warnings').textContent=JSON.stringify(status?.warnings??[],null,2);
}
conn.on('status',m=>{status=m.status??m;render();if(!updatingMission){updatingMission=true;mission.observe(status).catch(e=>tell(e.message)).finally(()=>{updatingMission=false;$('missionState').textContent=mission.reason;});}});
conn.on('link',state=>{$('link').textContent=state==='open'?'연결됨':'연결 끊김';if(state==='open')reloadMaps();else{mission.disconnected();direction=null;status=null;mapping.setMap(null);navigation.setMap(null);render();}});
conn.on('map',m=>{mapping.setMap(m);navigation.setMap(m);});conn.on('scan',m=>{mapping.setScan(m);navigation.setScan(m);});conn.on('plan',m=>navigation.setPlan(m));conn.on('event',m=>tell(m.message));
$('speed').oninput=render;
document.querySelectorAll('nav [data-screen]').forEach(b=>b.onclick=()=>{stop();const screen=b.dataset.screen;tab=screen==='record'?'maps':screen==='autonomy'?'auto':screen;document.querySelectorAll('.screen').forEach(p=>p.hidden=p.id!=='screen-'+screen);document.querySelectorAll('nav [data-screen]').forEach(x=>x.setAttribute('aria-current',x===b?'page':'false'));render();window.dispatchEvent(new Event('resize'));});
document.querySelectorAll('[data-api]').forEach(b=>b.onclick=()=>post(b.dataset.api));
const commands={bringup:['/api/process/start',{name:'bringup',options:{use_camera:true}}],powerOn:['/api/motor/power',{enabled:true}],powerOff:['/api/motor/power',{enabled:false}],mappingStart:['/api/process/start',{name:'mapping',options:{}}],mappingStop:['/api/process/stop',{name:'mapping'}],mapSave:['/api/map/save',{}]};
for(const[id,[path,body]]of Object.entries(commands))if($(id))$(id).onclick=()=>post(path,body);
$('zero').onclick=async()=>{startGeneration++;stop();if(mission.busy)await mission.cancel();if(status?.control?.holder?.client_id===conn.clientId){if(status?.motor?.ready)await conn.post('/api/motor/power',{enabled:false});await conn.post('/api/control/release');}};
$('arm').onclick=async()=>{if(arming||document.hidden)return;const token=++startGeneration;arming=true;render();try{
 let result=await conn.post('/api/control/acquire');if(!result?.ok)return;
 if(!['running','external'].includes(status?.processes?.bringup?.state)){
 result=await conn.post('/api/process/start',{name:'bringup',options:{use_camera:true}});if(!result?.ok)return;
 const deadline=Date.now()+30000;while(!['running','external'].includes(status?.processes?.bringup?.state)){if(Date.now()>deadline)throw Error('로봇 연결 준비 시간 초과');if(token!==startGeneration||document.hidden)throw Error('조종 시작 취소');await new Promise(r=>setTimeout(r,200));}
 }
 if(token!==startGeneration||document.hidden)throw Error('조종 시작 취소');await conn.post('/api/motor/power',{enabled:true});
 }catch(e){tell(e.message);}finally{arming=false;render();}};

document.querySelectorAll('[data-dir]').forEach(b=>{b.onclick=()=>{if(b.disabled||arming||mission.busy)return;if(directionKey===b.dataset.dir)stop();else{directionKey=b.dataset.dir;direction=DIR[directionKey];pressed();}};b.oncontextmenu=e=>e.preventDefault();});
document.querySelectorAll('[data-speed]').forEach(b=>b.onclick=()=>{$('speed').value=b.dataset.speed;render();});
window.addEventListener('blur',stop);document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();if(mission.busy)mission.cancel('stopped','화면이 숨겨져 운행을 종료했습니다');}});
setInterval(()=>{if(!direction||!conn.isOpen||document.hidden)return;const[x,y,yaw]=direction;conn.send({type:'teleop',pad:'drive',level:nativeLevel(),x,y,yaw});},50);
async function reloadMaps(){const data=await conn.get('/api/maps');if(!data)return;$('mapList').replaceChildren();$('navigationMap').replaceChildren();for(const m of data.maps??[]){const b=document.createElement('button');b.textContent=`${m.name} · ${(m.width*m.resolution).toFixed(1)} × ${(m.height*m.resolution).toFixed(1)} m`;b.onclick=()=>{$('navigationMap').value=m.name;$('preview').src='/api/maps/preview?name='+encodeURIComponent(m.name);$('preview').hidden=false;};$('mapList').append(b);const o=document.createElement('option');o.value=m.name;o.textContent=m.name;$('navigationMap').append(o);}}
$('reloadMaps').onclick=reloadMaps;$('navStart').onclick=()=>post('/api/process/start',{name:'navigation',options:{map:$('navigationMap').value}});
$('navSpeed').oninput=()=>{$('navSpeedLabel').textContent=$('navSpeed').value+'%';};$('navSpeed').onchange=()=>post('/api/nav/speed',{percent:Number($('navSpeed').value)});
$('missionStart').onclick=async()=>{try{await mission.start({mode:$('mission').value,radius:Number($('radius').value),points:$('mission').value==='route'?route:[target],cycles:Number($('cycles').value),seconds:Number($('duration').value)*60},status);$('missionState').textContent=mission.reason;}catch(e){tell(e.message);}};
$('missionPause').onclick=()=>mission.cancel('paused','일시정지: 새 운행 시작으로 재개하세요');
$('missionStop').onclick=()=>mission.cancel();
$('missionHome').onclick=()=>mission.returnHome().catch(e=>tell(e.message));
function showRoute(){$('points').replaceChildren();route.forEach((p,i)=>{const li=document.createElement('li');li.textContent=`${i+1}. ${p.x.toFixed(2)}, ${p.y.toFixed(2)} m`;$('points').append(li);});}
$('addPoint').onclick=()=>{if(!target)return tell('지도에서 목표를 선택하세요');route.push({...target});showRoute();};
$('clearPoints').onclick=()=>{route=[];showRoute();};
$('loadLogs').onclick=async()=>{$('logs').textContent=JSON.stringify(await conn.get('/api/logs?process='+encodeURIComponent($('logProcess').value)+'&lines=100'),null,2);};

let library={maps:{}};
async function loadLibrary(){const data=await conn.get('/api/library');if(data)library=data;}
function currentMeta(){return library.maps?.[$('navigationMap').value]??{label:'',route:[]};}
function restoreRoute(){route=currentMeta().route.map(p=>({...p}));$('mapLabel').value=currentMeta().label;showRoute();tell('선택 지도에 저장된 경로를 불러왔습니다.');}
$('navigationMap').onchange=restoreRoute;
$('loadRoute').onclick=async()=>{await loadLibrary();restoreRoute();};
async function saveLibrary(includeRoute){const name=$('navigationMap').value;if(!name)return tell('지도를 먼저 선택하세요');const result=await conn.post('/api/library/route',{name,label:$('mapLabel').value,route:includeRoute?route:currentMeta().route});if(result?.ok){await loadLibrary();tell('지도 관리 정보를 저장했습니다.');}}
$('saveRoute').onclick=()=>saveLibrary(true);$('saveMapLabel').onclick=()=>saveLibrary(false);
$('exportMap').onclick=()=>{const name=$('navigationMap').value;if(!name)return tell('지도를 선택하세요');const a=document.createElement('a');a.href='/api/maps/export?name='+encodeURIComponent(name);a.download='map-export.zip';a.click();};
conn.on('link',state=>{if(state==='open')loadLibrary();});

async function loadDiagnostics(){if(!conn.isOpen)return;const data=await conn.get('/api/mobile/diagnostics');if(data){diagnostics=data;render();}}
conn.on('link',state=>{if(state==='open')loadDiagnostics();});setInterval(loadDiagnostics,5000);
function missionHelp(){const mode=$('mission').value;const help={goal:'저장 지도를 준비한 뒤 지도에서 목표를 선택합니다.',roundtrip:'선택한 목표에 도착하면 출발점으로 돌아옵니다.',route:'지도에서 지점을 차례로 추가하고 반복 횟수를 지정합니다. 마지막에 출발점으로 돌아옵니다.',explore:'지도 탭에서 지도 생성을 시작하고 바퀴 조작을 켠 뒤 실행합니다. 새 공간을 탐색하고 반경·시간 조건이나 탐색 완료 시 지도를 저장하여 복귀합니다.'};$('missionHelp').textContent=help[mode];$('addPoint').hidden=mode!=='route';$('clearPoints').hidden=mode!=='route';$('cycles').closest('label').hidden=mode!=='route';$('radius').closest('label').hidden=mode!=='explore';}
$('mission').onchange=missionHelp;missionHelp();

const cameraRoles=['top','left_wrist','right_wrist'];
const cameraImages={top:'camera',left_wrist:'cameraLeft',right_wrist:'cameraRight'};
const cameraURLs=new Map(),cameraTimes=new Map();
function cameraTile(role){return document.querySelector(`[data-camera="${role}"]`);}
function clearCameras(message){
 for(const role of cameraRoles){const tile=cameraTile(role);document.getElementById(cameraImages[role]).hidden=true;tile.querySelector('.camera-placeholder').hidden=false;tile.querySelector('.camera-placeholder').textContent=message;tile.querySelector('.camera-status').textContent=message;const url=cameraURLs.get(role);if(url)URL.revokeObjectURL(url);}
 cameraURLs.clear();cameraTimes.clear();
}
function subscribeCamera(){conn.subscribe(['map','scan','plan','odom','motors',...(cameraEnabled?cameraRoles.map(role=>`camera/${role}`):[])]);}
$('cameraToggle').onclick=()=>{cameraEnabled=!cameraEnabled;$('cameraBox').hidden=!cameraEnabled;$('cameraToggle').textContent=cameraEnabled?'영상 끄기':'영상 켜기';if(!cameraEnabled)clearCameras('영상 꺼짐');subscribeCamera();};
conn.on('link',state=>{if(state==='open')subscribeCamera();else clearCameras('로봇 미연결');});
conn.on('camera',({camera,blob})=>{
 if(!cameraEnabled||!cameraRoles.includes(camera))return;
 const tile=cameraTile(camera),img=document.getElementById(cameraImages[camera]);const previous=cameraURLs.get(camera),url=URL.createObjectURL(blob);
 cameraURLs.set(camera,url);cameraTimes.set(camera,Date.now());img.src=url;img.hidden=false;tile.querySelector('.camera-placeholder').hidden=true;tile.querySelector('.camera-status').textContent='수신 중';if(previous)URL.revokeObjectURL(previous);
});
setInterval(()=>{for(const role of cameraRoles){const at=cameraTimes.get(role);if(at&&Date.now()-at>5000){const tile=cameraTile(role);document.getElementById(cameraImages[role]).hidden=true;tile.querySelector('.camera-placeholder').hidden=false;tile.querySelector('.camera-placeholder').textContent='영상 수신 지연';tile.querySelector('.camera-status').textContent='수신 지연';}}},1000);
