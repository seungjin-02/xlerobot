'use strict';
const $=id=>document.getElementById(id);
let releases=[],busy=false,checking=false,timer=null,completedCommit=null;
async function request(path,body){
 const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),150000);
 try{
  const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
  const data=await r.json();
  if(r.status===401){$('panel').hidden=true;$('login').hidden=false;releases=[];}
  if(!r.ok)throw Error(data.error||'확인 실패');
  return data;
 }finally{clearTimeout(deadline);}
}
function render(){
 const selected=releases.find(r=>r.commit===$('release').value);
 $('apply').disabled=busy||checking||!selected||!$('isolated').checked;
 $('recover').disabled=busy||checking||!$('isolated').checked;
 $('check').disabled=busy||checking;
 $('release').disabled=busy||checking;
 $('apply').textContent=selected?selected.tag+' 버전으로 업데이트':'업데이트할 검증 버전 없음';
 $('notes').textContent=selected?`${selected.tag}\n${selected.commit}\n\n${selected.notes}\n\n변경 파일\n${selected.changes.join('\n')}`:'';
}
async function checkReleases(){
 if(checking||busy)return;
 checking=true;render();$('availability').textContent='검증된 새 버전 확인 중…';
 try{
  const d=await request('releases',{});releases=d.releases;
  // Automatically recommend a stable version; prereleases require explicit selection.
  const stable=releases.filter(r=>/^v\d+\.\d+\.\d+$/.test(r.tag)).sort((a,b)=>{
   const x=a.tag.slice(1).split('.').map(BigInt),y=b.tag.slice(1).split('.').map(BigInt);
   for(let i=0;i<3;i++)if(x[i]!==y[i])return x[i]>y[i]?-1:1;
   return 0;
  });
  const seen=new Set();
  releases=[...stable,...releases].filter(r=>{if(seen.has(r.commit))return false;seen.add(r.commit);return true;});
  $('release').replaceChildren(new Option('릴리스를 선택하세요',''),...releases.map(r=>new Option(`${r.tag} · ${r.commit.slice(0,8)}`,r.commit)));
  $('release').value=stable[0]?.commit||'';
  $('availability').textContent=stable.length?'검증된 새 버전 '+stable[0].tag+'을 적용할 수 있습니다.':releases.length?'시험 릴리스만 있습니다. 내용을 확인하고 직접 선택하세요.':'적용 가능한 검증된 새 버전이 없습니다. 미검증 main은 자동 설치하지 않습니다.';
  $('error').textContent='';
 }catch(e){
  releases=[];$('release').replaceChildren();$('availability').textContent='새 버전을 확인하지 못했습니다. 연결 후 다시 확인하세요.';$('error').textContent=e.message;
 }finally{checking=false;render();}
}
async function poll(){
 try{
  const d=await request('status');busy=d.busy;
  $('status').textContent=`상태: ${d.phase}${busy?' · 진행 중':''}`;$('error').textContent=d.job_error||d.error||'';
  $('panel').hidden=false;$('login').hidden=true;render();
  if(d.phase==='succeeded'&&!busy&&!checking&&d.commit!==completedCommit){completedCommit=d.commit;await checkReleases();}
 }catch(e){$('error').textContent=e.message;}
}
$('login').addEventListener('submit',async e=>{
 e.preventDefault();const password=$('password').value;$('password').value='';
 try{await request('login',{password});await poll();await checkReleases();if(!timer)timer=setInterval(poll,2000);}catch(e){$('error').textContent=e.message;}
});
$('logout').onclick=async()=>{
 try{await request('logout',{});}finally{$('panel').hidden=true;$('login').hidden=false;releases=[];clearInterval(timer);timer=null;}
};
$('check').onclick=checkReleases;
$('release').onchange=render;$('isolated').onchange=render;
$('apply').onclick=async()=>{
 const r=releases.find(r=>r.commit===$('release').value);if(!r||!$('isolated').checked||busy||checking)return;
 busy=true;render();
 try{await request('apply',{tag:r.tag,commit:r.commit,motor_power_isolated:true});$('isolated').checked=false;await poll();}
 catch(e){busy=false;$('error').textContent=e.message;render();}
};
$('recover').onclick=async()=>{
 if(!confirm('이전 버전으로 복원된 서비스 상태를 확인한 뒤 조종 잠금을 해제합니다. 모터 전원이 분리돼 있나요?'))return;
 try{await request('confirm-recovery',{motor_power_isolated:$('isolated').checked});await poll();}catch(e){$('error').textContent=e.message;}
};
poll().then(async()=>{if(!$('panel').hidden){await checkReleases();timer=setInterval(poll,2000);}});
