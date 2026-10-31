'use strict';
let autonomyBusy=false, autonomyMapBusy=false, autonomyMapAt=0;
let autonomySpeed=1,autonomySpeedBusy=false;
function renderAutonomy(){
  const a=status?.autonomy;
  if(!$('autonomyStart'))return;
  const busy=!!a?.busy, mine=!!a?.mine;
  if(busy && !autonomySpeedBusy)autonomySpeed=a.speed_multiplier||1;
  if(busy && a.limits){
    $('autonomyMode').value=a.limits.mode||'patrol';
    if(a.limits.target_distance_m!=null)$('roundTripDistance').value=a.limits.target_distance_m;
    $('autonomyRadius').value=a.limits.max_radius_m;
    $('autonomyMinutes').value=a.limits.max_duration_s/60;
    $('autonomyCycles').value=a.limits.cycles;
  }
  $('autonomySpeed').value=autonomySpeed;
  $('autonomySpeedValue').textContent=autonomySpeed+'배';
  $('autonomySpeedDetail').textContent=`이동 요청 상한 ${(autonomySpeed*.03).toFixed(2)} m/s · 회전 요청 상한 ${($('autonomyMode').value==='straight_round_trip'?0:autonomySpeed*.15).toFixed(2)} rad/s`;
  const speedDisabled=autonomySpeedBusy || (busy && (!mine || a.phase!=='running'));
  $('autonomySpeed').disabled=speedDisabled;
  document.querySelectorAll('[data-autonomy-speed]').forEach(b=>{b.disabled=speedDisabled;b.classList.toggle('selected',Number(b.dataset.autonomySpeed)===autonomySpeed);});
  $('autonomyStart').disabled=!a?.configured || busy || !!status?.armed || !!status?.recording?.active || autonomyBusy || disconnected || !!status?.updates?.blocked;
  $('autonomyPause').disabled=!mine || !!a?.paused || autonomyBusy;
  $('autonomyResume').disabled=!mine || !a?.paused || autonomyBusy;
  $('autonomyStop').disabled=!busy || autonomyBusy;
  $('autonomyReturn').disabled=!mine || a?.phase!=='running' || autonomyBusy;
  for(const id of ['autonomyTask','autonomyRadius','autonomyMinutes','autonomyCycles','autonomyMode','roundTripDistance','initialScanRotation'])$(id).disabled=busy;
  const straight=$('autonomyMode').value==='straight_round_trip';
  const roundTrip=$('autonomyMode').value!=='patrol';
  if(straight)$('initialScanRotation').checked=false;
  $('initialScanRotation').disabled=busy||straight;
  $('roundTripSettings').hidden=!roundTrip;
  $('autonomyCycles').disabled=busy||roundTrip;
  const names={idle:'대기',starting:'센서·SLAM 준비 중',surveying:'제자리 회전·초기 지도 확보 중',running:'자동 운행',stopping:'정지·기록 저장 중',fault:'오류'};
  $('autonomyState').textContent=a?.error || a?.blocked_reason || (a?.paused?'일시정지':names[a?.phase]||'상태 확인 중');
  const m=a?.mission;
  const states={outbound:'전방 목표로 이동',waiting:'준비',exploring:'미탐색 영역 탐색',patrolling:'순회',returning:'출발점 복귀',paused:'일시정지',complete:'완료',blocked:'경로 확보 불가',fault:'오류로 정지',stopped:'종료'};
  const reasons={straight_heading_limit:'방향 이탈로 정지',return_corridor_not_clear:'직선 복귀 경로 막힘·정지',reachable_targets_exhausted:'갈 수 있는 목표 소진',reachable_area_exhausted:'도달 가능한 영역 탐색 종료',cycles_complete:'설정 순회 완료',duration_limit:'운행 시간 도달',navigation_failures_limit:'이동 실패 누적으로 복귀',home_unreachable:'복귀 경로 없음·정지',return_timeout:'복귀 시간 초과·정지',no_clear_known_start_cell:'출발 지점의 관측·외곽 여유 부족',safe_waypoint_reached:'안전 구간 도착·다음 경로 확인',outbound_goal_reached:'전방 목표 도착·복귀 준비',outbound_goal_failed:'전방 목표 이동 실패',outbound_corridor_not_clear:'전방 목표까지 안전한 경로 확보 불가',round_trip_path_blocked:'경로가 막혀 왕복 종료',round_trip_goal_timeout:'목표 이동 시간 초과',round_trip_lateral_limit:'통로 이탈로 정지',round_trip_overshoot:'목표 거리 초과로 정지',returned_home:'출발점 복귀 완료',operator_stop:'사용자 종료',return_failed:'복귀 경로 이동 실패',return_distance_reserve:'복귀 거리 확보',cancel_ack_timeout:'목표 취소 응답 시간 초과'};
  $('autonomyProgress').textContent=m?`상태 ${states[m.state]||m.state} · 이동 ${Number(m.distance_m).toFixed(2)}m · 목표 ${m.goals_sent}개 · 완료 순회 ${m.cycles_finished}회${m.reason?' · '+(reasons[m.reason]||m.reason):''}`:'지도·좌표·센서가 준비되면 시작할 수 있습니다.';
  if(['round_trip','straight_round_trip'].includes(m?.task_mode))$('autonomyProgress').textContent=`${states[m.state]||m.state} · 전방 목표 ${m.target_distance_m}m · 누적 이동 ${Number(m.distance_m).toFixed(2)}m · ${m.round_trip_completed?'왕복 완료':m.outbound_reached?'전방 목표 도착 확인':'전방 목표 도착 전'}${m.reason?' · '+(reasons[m.reason]||m.reason):''}`;
  if(m?.return_reason)$('autonomyProgress').textContent+=' · 복귀 이유: '+(reasons[m.return_reason]||m.return_reason);
  if(busy){$('badge').textContent=a.paused?'자동 순회 일시정지':'자동 탐색·순회';$('controlSummary').textContent+=' · 자동 운행';}
  if(currentScreen==='autonomy' && !autonomyMapBusy && Date.now()-autonomyMapAt>1500)refreshAutonomyMap();
}
async function refreshAutonomyMap(){
  autonomyMapBusy=true;autonomyMapAt=Date.now();
  try{
    const m=await api('autonomy/map',undefined,2500),canvas=$('autonomyMap');
    canvas.hidden=!m.available;
    if(!m.available){$('autonomyMapState').textContent='아직 생성된 실시간 지도가 없습니다.';return;}
    const w=m.width,h=m.height;if(!Number.isInteger(w)||!Number.isInteger(h)||w<1||h<1||m.data.length!==w*h)return;
    const image=document.createElement('canvas');image.width=w;image.height=h;const pix=image.getContext('2d').createImageData(w,h);
    for(let i=0;i<m.data.length;i++){const v=m.data[i],j=((h-1-Math.floor(i/w))*w+i%w)*4,c=v<0?105:v>20?24:224;pix.data[j]=c;pix.data[j+1]=c;pix.data[j+2]=c;pix.data[j+3]=255;}
    image.getContext('2d').putImageData(pix,0,0);canvas.width=640;canvas.height=Math.max(180,Math.round(640*h/w));
    const ctx=canvas.getContext('2d');ctx.imageSmoothingEnabled=false;ctx.drawImage(image,0,0,canvas.width,canvas.height);
    const point=p=>{const dx=p[0]-m.origin[0],dy=p[1]-m.origin[1],c=Math.cos(m.origin[2]),s=Math.sin(m.origin[2]);return [(c*dx+s*dy)/m.resolution/w*canvas.width,(h-(-s*dx+c*dy)/m.resolution)/h*canvas.height];};
    ctx.strokeStyle='#175d9c';ctx.lineWidth=2;ctx.beginPath();(m.trail||[]).forEach((p,i)=>{const q=point(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.stroke();
    if(m.goal){const [x,y]=point(m.goal);ctx.strokeStyle='#9c3517';ctx.beginPath();ctx.moveTo(x-7,y);ctx.lineTo(x+7,y);ctx.moveTo(x,y-7);ctx.lineTo(x,y+7);ctx.stroke();}
    if(m.pose){const [x,y]=point(m.pose);ctx.fillStyle='#175d9c';ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();}
    $('autonomyMapState').textContent=`실시간 SLAM 지도 · 수신 ${Number(m.map_age_s).toFixed(1)}초 전${m.display_downsampled?' · 화면용 축소 표시':''}`;
  }catch(e){$('autonomyMapState').textContent='지도 조회 실패: '+e.message;}finally{autonomyMapBusy=false;}
}
async function autonomyAction(action){
  if(autonomyBusy)return;autonomyBusy=true;render();
  try{
    const body=action==='start'?{task:$('autonomyTask').value,max_radius:Number($('autonomyRadius').value),max_duration:Number($('autonomyMinutes').value)*60,cycles:Number($('autonomyCycles').value),max_distance:50,speed_multiplier:autonomySpeed,mode:$('autonomyMode').value,target_distance:Number($('roundTripDistance').value),initial_scan_rotation:$('initialScanRotation').checked,rotation_clearance_confirmed:$('initialScanRotation').checked}:{};
    await api('autonomy/'+action,body,10000);await refresh();
  }catch(e){message(e.message);}finally{autonomyBusy=false;render();}
}
document.addEventListener('DOMContentLoaded',()=>{for(const action of ['start','pause','resume','return','stop'])$('autonomy'+action[0].toUpperCase()+action.slice(1)).addEventListener('click',()=>autonomyAction(action));});
const $ = id => document.getElementById(id);
let lease = null, seq = 0, direction = 'idle', hold = null;
let speed = 10 / 30, status = null, offset = 0, pairing = false, stopping = false;
let recordBusy=false;
let preparing = false, arming = false, refreshing = false, disconnected = false;
let generation = 0, pendingCommands = 0, bestRtt = Infinity;
let currentScreen = 'drive', navigating = false, systemLoading = false;
const controls = [...document.querySelectorAll('.drive')];
function message(text = '') { $('message').textContent = text; }
async function api(path, body, timeout = 1500, keepalive = false) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch('/api/' + path, { method: body ? 'POST' : 'GET', credentials: 'same-origin', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined, signal: controller.signal, cache: 'no-store', keepalive });
    const data = await res.json();
    if (!res.ok) { const err = new Error(data.error || '연결 오류'); err.status = res.status; throw err; }
    return data;
  } finally { clearTimeout(timer); }
}
function render() {
  const switchLink=$('controllerSwitch');if(switchLink){switchLink.hidden=!status?.controller_switch_enabled;const u=new URL(location.href);u.port='8091';u.pathname='/';u.search='';u.hash='';switchLink.href=u.href;}
  const mine = !!lease, maintenance = !!status?.updates?.blocked;
  if(status?.device_name)document.querySelector('.brand strong').textContent=status.device_name==='XLeRobot Trolley'?'XLeRobot':status.device_name;
  controls.forEach(b => {
    b.disabled = maintenance || !mine || arming || stopping || navigating;
    const selected = mine && b.dataset.dir === direction;
    b.classList.toggle('pressed', selected);
    b.setAttribute('aria-pressed', String(selected));
  });
  $('arm').disabled = maintenance || mine || !!status?.armed || stopping || preparing || arming || disconnected || document.hidden;
  if(status?.autonomy?.busy)$('arm').disabled=true;
  $('arm').textContent = arming ? '준비 중…' : mine ? '조종 중' : '조종 시작';
  $('badge').textContent = disconnected ? '재연결 중' : status?.demo ? '시뮬레이션' : mine ? '조종 중' : status ? '연결됨' : '접속 대기';
  $('badge').classList.toggle('on', mine && !disconnected);
  $('controlSummary').textContent = `${status?.demo ? '합성 데모 · 실물 연결 없음' : '로컬 로봇'} · ${status && !disconnected ? 'PIN 인증됨' : '연결 확인 필요'} · ${disconnected ? '재연결 중' : mine ? '내 제어권' : status?.armed ? '다른 기기 조종 중' : '조종 중지'} · ${status?.recording?.active ? '기록 중' : '기록 대기'}`;
  if(maintenance)$('controlSummary').textContent+=' · 업데이트/복구 검증 중 · 조종·기록 차단';
  $('motorState').textContent = `${status?.demo ? '시뮬레이션 · ' : ''}모터 준비 피드백: ${!status?.available ? '확인 불가' : status.motor_ready === true ? '준비됨' : status.motor_ready === false ? '비활성' : '확인 불가'} · 제어 연결: ${status?.available ? '응답 있음' : '확인 불가'}`;
  document.querySelectorAll('[data-screen]').forEach(button => {
    button.disabled = navigating || arming || preparing || stopping || recordBusy;
    if (button.closest('nav')) {
      if (button.dataset.screen === currentScreen) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
  });
  const names = {forward:'전진',back:'후진',left:'왼쪽 이동',right:'오른쪽 이동',turn_left:'좌회전',turn_right:'우회전'};
  $('state').textContent = disconnected ? '재연결 중 · 마지막 이동은 최대 10초 유지됩니다' : mine && direction !== 'idle' ? `${names[direction]} 켜짐 · 같은 버튼을 다시 누르면 정지` : status?.armed && !status.mine ? '다른 폰에서 조종 중입니다' : status?.fault || (status?.other_publishers ? 'PC의 다른 조종 프로그램을 종료하세요' : status?.reason || '로봇 상태 확인 중');
  $('speedValue').textContent = Math.round(speed * 30) + '배';
  const max = status?.max_linear ?? .9;
  $('speedDetail').textContent = `이동 요청 ${(.03 * Math.round(speed * 30)).toFixed(2)} m/s · 회전 요청 ${(.15 * Math.round(speed * 30)).toFixed(3)} rad/s (${(.15 * Math.round(speed * 30) * 180 / Math.PI).toFixed(1)}°/s)`;
  $('limitNote').textContent = max < .89 ? `현재 제어 제한 ${max.toFixed(3)} m/s. 실제 드라이버 상한이 적용됩니다.` : '하한 0.03 · 기본 0.30 · 상한 0.90 m/s. 바퀴 출력 제한이 별도로 적용되며 실제 속도는 미측정입니다.';
  document.querySelectorAll('[data-speed]').forEach(b => b.classList.toggle('selected', Number(b.dataset.speed) === Math.round(speed * 30)));
  renderCameras();
  const rec=status?.recording;
  $('recordStart').disabled=maintenance || (!lease && !(status?.autonomy?.mine && status?.autonomy?.phase==='running')) || recordBusy || !!rec?.active || !!rec?.finishing;
  $('task').disabled=!!rec?.active || !!rec?.finishing;
  $('recordBadge').textContent=rec?.finishing?'저장 중':rec?.active?'기록 중':'대기';
  $('recordFinish').hidden=!rec?.active || !rec?.mine;
  $('recordFinish').querySelectorAll('button').forEach(b=>b.disabled=recordBusy);
  $('recordState').textContent=rec?.error || rec?.camera_error || (rec?.active ? `${rec.samples}프레임 저장 · 학습에 쓸 수 있는 프레임 ${rec.valid_samples}개` : '수동 조종 또는 내 자율주행을 시작한 뒤 학습 데이터를 수집할 수 있습니다. 자동 운행과 기록은 별도로 종료합니다.');
  $('recordDuration').textContent=rec?.active || rec?.finishing ? `기록 시간 ${Math.floor(rec.elapsed_s || 0)}초 · ${rec.fps} Hz 목표` : '요청 명령·출력 제한 후 발행 명령·센서 상태를 구분해 저장합니다.';
  $('recordStorage').textContent=`남은 공간 ${bytes(status?.storage?.free_bytes)} · 시작 시 최소 256 MiB 필요`;
  const slam=rec?.slam;
  $('recordSlam').disabled=!slam?.available || !!rec?.active || !!rec?.finishing || recordBusy;
  $('slamState').textContent=!slam?.available ? 'SLAM 기록은 실제 ROS 2·rosbag2 환경에서 사용할 수 있습니다. 데모에서는 센서를 만들지 않습니다.' :
    slam?.enabled ? (slam.error || `SLAM ${slam.bag_closed ? '저장 종료' : slam.ready ? '센서 수신 중' : '입력 확인 필요'} · LiDAR ${slam.counts?.[slam.config.scan_topic] || 0}개 · odometry ${slam.counts?.[slam.config.odom_topic] || 0}개 · ${(slam.missing || []).join(', ')}`) :
    'SLAM을 선택하면 원본 LiDAR·odometry·TF와 제공되는 IMU·관절·진단을 함께 저장합니다. 카메라 없이도 지도용 기록이 가능합니다.';
  const episodes=status?.episodes || [];
  const signature=JSON.stringify(episodes);
  if($('episodes').dataset.signature!==signature){
    $('episodes').dataset.signature=signature;$('episodes').replaceChildren();
    const names={success:'성공',failure:'실패',unfinished:'미분류',interrupted:'중단'};
    for(const ep of episodes.slice(0,5)){
      if(!ep.complete)continue;
      const row=document.createElement('div');row.className='episode-row';
      const label=document.createElement('span');label.textContent=`${ep.control_mode==='autonomous'?'자동 순회 · ':''}${ep.task} · ${names[ep.outcome]||'미분류'} · ${ep.samples}프레임 · 학습 유효 ${ep.valid_samples||0}개`;
      const link=document.createElement('a');link.textContent='다운로드';link.href='/api/record/'+encodeURIComponent(ep.episode_id)+'/download';
      row.append(label,link);$('episodes').append(row);
      if(ep.slam?.enabled){const quality=document.createElement('small');quality.textContent=ep.slam.valid_for_mapping?'SLAM 입력 검사 통과 · 오프라인 지도 생성 가능':'SLAM 불완전 · 센서/TF 확인 필요';row.append(quality);}
    }
  }

  renderAutonomy();
}
function clearDirection() { direction = 'idle'; hold = null; render(); }
function lostLease(reason) {
  generation++; lease = null; clearDirection();
  if (status) status = {...status, armed:false, mine:false};
  message(reason || '조종이 종료됐습니다. 다시 시작하세요.'); render();
}
async function stop(reason = '') {
  generation++; lease = null; clearDirection(); stopping = true; message(); render();
  let acknowledged = false;
  try { await api('stop', {}, 3500, true); acknowledged = true; }
  catch { message('정지 명령이 전달되지 않았습니다. 연결 끊김 시 마지막 이동이 최대 10초 유지될 수 있습니다. 즉시 멈춰야 하면 전원을 차단하세요.'); }
  finally { stopping = false; if (reason && acknowledged) message(reason); await refresh(); render(); }
}
async function sendCommand(urgent = false) {
  if (!lease || document.hidden || (!urgent && pendingCommands > 0) || pendingCommands >= 4) return;
  pendingCommands++;
  const currentLease = lease, sentSeq = ++seq, currentGeneration = generation;
  try {
    await api('command', {lease:currentLease, seq:sentSeq, direction, speed, hold, sent_at:Date.now() + offset}, 700);
    if (lease === currentLease && generation === currentGeneration) { disconnected = false; render(); return true; }
  } catch (e) {
    if (lease !== currentLease || generation !== currentGeneration || sentSeq < seq) return;
    if (e.status === 401) { lostLease('접속 코드를 다시 입력하세요.'); $('login').hidden=false; $('panel').hidden=true; }
    else if (e.status === 409 && e.message.includes('조종 권한')) { lostLease('10초 이상 연결이 끊겨 정지했습니다. 다시 조종 시작을 누르세요.'); }
    else { disconnected = true; render(); }
  } finally { pendingCommands--; }
}
async function refresh() {
  if (refreshing || arming || preparing || document.hidden) return;
  refreshing = true;
  const start = Date.now(), currentGeneration = generation;
  try {
    const next = await api('status', undefined, 1800);
    if (currentGeneration !== generation) return;
    const end=Date.now(), rtt=end-start;
    if(rtt <= bestRtt + 20){offset=next.server_time-(start+end)/2;bestRtt=Math.min(bestRtt,rtt);}
    status = next; disconnected = false;
    $('login').hidden=true; $('panel').hidden=false;
    if (lease && !status.mine) lostLease(status.reason);
    render();
  } catch (e) {
    if (currentGeneration !== generation) return;
    if (e.status === 401) {
      lostLease('접속 코드를 입력하세요.'); $('login').hidden=false; $('panel').hidden=true;
    } else { disconnected = true; render(); }
  } finally { refreshing = false; }
}
$('pairForm').addEventListener('submit', async e => {
  e.preventDefault(); if (pairing) return; pairing=true; message();
  try { await api('pair',{pin:$('pin').value}); $('pin').value=''; await refresh(); }
  catch(e) { message(e.message); } finally { pairing=false; }
});
$('arm').addEventListener('click', async () => {
  if (arming || lease || document.hidden) return;
  arming=true; generation++; message(); render();
  const armGeneration = generation;
  try {
    const data=await api('arm',{},12000);
    if (document.hidden || generation !== armGeneration) {
      await stop('화면을 벗어나 조종 시작을 취소했습니다');
      return;
    }
    lease=data.lease; seq=0; clearDirection();
    status={...status, armed:true, mine:true}; disconnected=false;
    await sendCommand();
  } catch(e) { await stop(e.message || '조종 시작 실패'); }
  finally { arming=false; await refresh(); render(); }
});
controls.forEach(button => {
  button.addEventListener('click', () => {
    if (!lease || stopping || arming || navigating) return;
    if (direction === button.dataset.dir) clearDirection();
    else {
      direction=button.dataset.dir;
      hold=`${Date.now()}-${Math.random().toString(36).slice(2)}`;
      render();
    }
    sendCommand(true);
  });
  button.addEventListener('contextmenu',e=>e.preventDefault());
});
$('speed').addEventListener('input',e=>{speed=Number(e.target.value)/30;render();sendCommand(true);});
document.querySelectorAll('[data-speed]').forEach(b=>b.addEventListener('click',()=>{speed=Number(b.dataset.speed)/30;$('speed').value=b.dataset.speed;render();sendCommand(true);}));
$('stop').addEventListener('click',()=>stop());
$('recordStart').addEventListener('click',async()=>{
  recordBusy=true;message();render();
  try{await api('record/start',{task:$('task').value,slam:$('recordSlam').checked && !!status?.recording?.slam?.available},15000);}
  catch(e){message(e.message);}
  finally{recordBusy=false;await refresh();render();}
});
document.querySelectorAll('[data-outcome]').forEach(b=>b.addEventListener('click',async()=>{
  recordBusy=true;message();render();
  try{const result=await api('record/finish',{outcome:b.dataset.outcome},15000);if(!result.autonomy_continues){generation++;lease=null;clearDirection();}message(result.autonomy_continues?'학습 데이터를 저장했습니다. 자율주행은 계속됩니다.':'기록을 저장하고 조종을 종료했습니다.');}
  catch(e){message(e.message);}
  finally{recordBusy=false;await refresh();render();}
}));
function hideStop(){
  if(!lease && !arming)return;
  generation++;lease=null;clearDirection();
  if(status)status={...status,armed:false,mine:false};
  navigator.sendBeacon('/api/stop',new Blob([JSON.stringify({})],{type:'application/json'}));render();
}
document.addEventListener('visibilitychange',()=>{if(document.hidden)hideStop();else refresh();});
window.addEventListener('pagehide',hideStop);
window.addEventListener('blur',()=>{if(lease || arming)stop('화면 전환으로 조종을 종료했습니다');});
window.addEventListener('offline',()=>{disconnected=true;render();});
window.addEventListener('online',()=>{refresh();sendCommand(true);});
let cameraOn=false;
let cameraListSignature='';
function renderCameras(){
 const cameras=status?.cameras||[];
 const signature=JSON.stringify(cameras);
 if(signature===cameraListSignature)return;
 cameraListSignature=signature;
 const selected=$('cameraSelect').value;
 $('cameraSelect').replaceChildren();
 cameras.forEach(c=>{const option=document.createElement('option');option.value=c.index;option.textContent=({front:'상단',wrist:'집게',left_wrist:'왼팔 손목',right_wrist:'오른팔 손목'}[c.role]||c.role)+(c.connected?'':' · 연결 안 됨');option.disabled=!c.connected;$('cameraSelect').append(option);});
 if(cameras.some(c=>String(c.index)===selected&&c.connected))$('cameraSelect').value=selected;
 $('cameraSelect').hidden=cameras.length<2;
 $('deviceConfig').textContent=status?.has_arm?'팔 장착 · 카메라':'본체 카메라';
 if(cameraOn && currentScreen === 'drive')loadCamera();
}
function loadCamera(){ $('cameraError').hidden=true;$('camera').src=status?.demo ? '/api/camera/demo.jpg' : `http://${location.hostname}:8080/stream?cam=${$('cameraSelect').value||0}`; }
$('cameraSelect').addEventListener('change',()=>{if(cameraOn)loadCamera();});

$('cameraToggle').addEventListener('click',()=>{
  cameraOn=!cameraOn;$('cameraBox').hidden=!cameraOn;$('cameraToggle').textContent=cameraOn?'영상 끄기':'영상 켜기';
  if(cameraOn && currentScreen === 'drive')loadCamera();
  else $('camera').removeAttribute('src');
});
$('camera').addEventListener('error',()=>$('cameraError').hidden=false);
function bytes(value) {
  return Number.isFinite(value) ? `${(value / 1024**3).toFixed(2)} GiB` : '확인 불가';
}
async function showScreen(name) {
  if (!['drive', 'record', 'autonomy', 'system'].includes(name) || navigating || arming || preparing || stopping || recordBusy || name === currentScreen) return;
  navigating = true; render();
  try {
    if (lease) {
      clearDirection();
      const acknowledged = await sendCommand(true);
      if (!acknowledged) {
        await stop();
        return; // Stay on the current screen when movement cancellation was not acknowledged.
      }
    }
    currentScreen = name;
    for (const screen of ['drive', 'record', 'autonomy', 'system']) $('screen-' + screen).hidden = screen !== name;
    render();
    if (cameraOn && name !== 'drive') $('camera').removeAttribute('src');
    else if (cameraOn) loadCamera();
    if (name === 'system') await refreshSystem();
    await refresh();
  } finally { navigating = false; render(); }
}
const known = value => value === null || value === undefined || value === '' ? '확인 불가' : String(value);
const yesNo = value => value === true ? '예' : value === false ? '아니오' : '확인 불가';
async function refreshSystem() {
  if (systemLoading) return;
  systemLoading = true; $('systemRefresh').disabled = true;
  $('systemState').textContent = '정보 확인 중…';
  try {
    const data = await api('system', undefined, 12000);
    const stateName = service => ({active:'활성', inactive:'비활성', failed:'실패', unknown:'확인 불가', not_applicable_demo:'데모 · 해당 없음'}[service?.state] || known(service?.state));
    const rows = [
      ['장치', data.device_name], ['실행 모드', data.demo ? '합성 데모' : 'ROS 로봇'],
      ['Git 태그', data.git?.tag || '태그 없음 / 확인 불가'], ['Git 커밋', data.git?.commit],
      ['추적 파일 변경', yesNo(data.git?.modified)], ['OS', data.os], ['아키텍처', data.architecture],
      ['ROS 배포판 (환경)', data.ros?.sourced_distro], ['Jazzy 설치 파일', yesNo(data.ros?.jazzy_installed)],
      ['웹 응답', data.web_server === 'responding' ? '정상 응답' : '확인 불가'],
      ['웹 서비스', stateName(data.services?.['lekiwi-phone.service'])],
      ['카메라 서비스', stateName(data.services?.['lekiwi-camera.service'])],
      ['ROS 제어 프로세스', {simulated:'데모', running_owned_process:'앱 소유 프로세스 실행 중', not_owned_or_not_running:'앱 소유 프로세스 없음 · 외부 상태 별도 확인'}[data.base_process]],
      ['모터 준비 피드백', (data.motor?.simulated ? '시뮬레이션 · ' : '') + yesNo(data.motor?.feedback_ready)],
      ['ROS 상태 최신', yesNo(data.motor?.feedback_fresh)],
      ['제어권', data.control?.mine ? '내 제어권' : data.control?.armed ? '다른 기기' : '조종 중지'],
      ['다른 명령 발행자', data.control?.other_publishers], ['남은 공간', bytes(data.storage?.free_bytes)],
      ['기록 경로', data.storage?.path], ['오류', data.fault || data.control?.cleanup_error || '보고된 오류 없음'],
    ];
    $('systemInfo').replaceChildren();
    for (const [label, value] of rows) {
      const term = document.createElement('dt'), description = document.createElement('dd');
      term.textContent = label; description.textContent = known(value); $('systemInfo').append(term, description);
    }
    const update=data.updates;
    $('updateState').textContent=update?.enabled ? `${update.blocked ? '조종·기록 차단 · ' : ''}${known(update.phase)}${update.error ? ' · '+update.error : ''}` : '관리자 업데이트 서비스가 아직 설치되지 않았습니다.';
    const adminLink = $('updateOpen');
    adminLink.hidden = true; adminLink.removeAttribute('href');
    if (update?.enabled && /^https:\/\/(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+):8093$/.test(update.admin_url || '')) {
      adminLink.href = update.admin_url; adminLink.hidden = false;
      $('updateHelp').textContent = '휴대폰에서 관리자 로그인 후 검증된 최신 버전을 적용합니다. 백업·적용·복구는 로봇이 수행합니다.';
    } else {
      $('updateHelp').textContent = update?.enabled ? '모바일 업데이트가 설정되지 않았습니다. 기존 SSH 터널 관리자 화면을 사용하세요.' : '기존 기기는 먼저 관리자 업데이트 서비스를 한 번 설정해야 합니다.';
    }
    $('systemState').textContent = '마지막 조회 ' + new Date().toLocaleTimeString() + ' · 설치 정보 최대 5초 캐시';
  } catch (error) {
    $('systemInfo').replaceChildren();
    $('updateOpen').hidden = true; $('updateOpen').removeAttribute('href');
    $('systemState').textContent = '확인 실패: ' + error.message;
    if (error.status === 401) await refresh();
  } finally { systemLoading = false; $('systemRefresh').disabled = false; }
}
document.querySelectorAll('[data-screen]').forEach(button => button.addEventListener('click', () => showScreen(button.dataset.screen)));
$('systemRefresh').addEventListener('click', refreshSystem);
setInterval(() => { if (currentScreen === 'system' && !$('panel').hidden && !document.hidden) refreshSystem(); }, 10000);
setInterval(sendCommand,100);
setInterval(()=>{if(!$('panel').hidden&&!document.hidden)refresh();},1000);
render();refresh();

async function changeAutonomySpeed(value){
  if(autonomySpeedBusy)return;
  const selected=Number(value);
  if(!Number.isInteger(selected)||selected<1||selected>3)return;
  autonomySpeed=selected;
  if(!status?.autonomy?.busy){renderAutonomy();return;}
  autonomySpeedBusy=true;renderAutonomy();
  try{await api('autonomy/speed',{speed_multiplier:selected},3000);}
  catch(e){message(e.message);}
  finally{autonomySpeedBusy=false;await refresh();renderAutonomy();}
}
document.addEventListener('DOMContentLoaded',()=>{
  $('autonomySpeed').addEventListener('input',()=>changeAutonomySpeed($('autonomySpeed').value));
  document.querySelectorAll('[data-autonomy-speed]').forEach(b=>b.addEventListener('click',()=>changeAutonomySpeed(b.dataset.autonomySpeed)));
});

document.addEventListener('DOMContentLoaded',()=>{$('autonomyMode').addEventListener('change',renderAutonomy);});
