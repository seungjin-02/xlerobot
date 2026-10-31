import {Mission} from './mission.js';
// Native Explorer supplies obstacle-aware map building. Mobile adds bounded return workflow.
export class ExplorationMission extends Mission {
 get busy(){return super.busy||['exploring','saving_map','starting_navigation','localizing'].includes(this.state);}
 async start(options,status){
  if(options.mode!=='explore')return super.start(options,status);
  if(this.busy)throw Error('현재 운행을 먼저 종료하세요');
  if(!this.validPose(status?.pose?.map))throw Error('출발점 지도 위치가 필요합니다');
  if(!['running','external'].includes(status?.processes?.mapping?.state))throw Error('지도 탭에서 지도 생성을 먼저 시작하세요');
  if(!Number.isFinite(options.seconds)||options.seconds<60||options.seconds>3600||!Number.isFinite(options.radius)||options.radius<1||options.radius>10)throw Error('운행 범위와 시간을 확인하세요');
  this.epoch++;const epoch=this.epoch;this.origin={...status.pose.map};this.home={...this.origin};this.deadline=this.clock()+options.seconds;this.radius=options.radius;this.state='exploring';this.reason='새 공간 탐색 중';
  const r=await this.post('/api/explore/start',{});if(epoch!==this.epoch)return;
  if(!r?.ok){this.state='failed';this.reason=r?.message??'탐색 시작 실패';}
 }
 async returnHome(){
  if(this.state==='exploring')return this.saveAndReturn();
  return super.returnHome();
 }
 async saveAndReturn(){
  this.state='saving_map';this.reason='탐색 정지 후 복귀 지도 저장 중';this.stageAt=this.clock();this.saveSeen=false;
  const epoch=this.epoch,r=await this.post('/api/explore/stop',{});if(epoch!==this.epoch)return;
  if(!r?.ok){this.state='failed';this.reason='탐색 정지 확인 실패';return;}
  const save=await this.post('/api/map/save',{});if(epoch!==this.epoch)return;
  if(!save?.ok){this.state='failed';this.reason=save?.message??'복귀 지도 저장 실패';}
 }
 async observe(status){
  if(this.state==='exploring'){
   const p=status?.pose?.map;
   if(!this.validPose(p)){await this.cancel('failed','지도 위치를 잃어 탐색을 종료했습니다');return;}
   const run=status.exploration;
   if(this.clock()>=this.deadline||Math.hypot(p.x-this.origin.x,p.y-this.origin.y)>=this.radius||['done','stopped'].includes(run?.state)){
    this.returnPose={...p};await this.saveAndReturn();
   }
   return;
  }
  if(this.state==='saving_map'){
   const save=status?.processes?.save_map;
   if(save?.state==='running')this.saveSeen=true;
   if(save?.state==='failed'){this.state='failed';this.reason='지도를 저장하지 못해 복귀를 중단했습니다';return;}
   if(this.saveSeen&&save?.state==='succeeded'&&typeof save.map==='string'){
    const epoch=this.epoch;this.state='starting_navigation';this.stageAt=this.clock();this.reason='생성한 지도에서 복귀 준비 중';this.returnPose={...status.pose.map};
    const stop=await this.post('/api/process/stop',{name:'mapping'});if(epoch!==this.epoch)return;
    if(!stop?.ok){this.state='failed';this.reason='지도 작성 종료 실패';return;}
    const start=await this.post('/api/process/start',{name:'navigation',options:{map:save.map.split('/').pop()}});if(epoch!==this.epoch)return;
    if(!start?.ok){this.state='failed';this.reason=start?.message??'복귀 준비 실패';}
   }else if(this.clock()-this.stageAt>45){this.state='failed';this.reason='지도 저장 확인 시간 초과';}
   return;
  }
  if(this.state==='starting_navigation'){
   if(['running','external'].includes(status?.processes?.navigation?.state)&&status?.navigation?.state!=='unavailable'){
    const epoch=this.epoch;this.state='localizing';this.stageAt=this.clock();
    const r=await this.post('/api/nav/initial_pose',this.returnPose);if(epoch!==this.epoch)return;
    if(!r?.ok){this.state='failed';this.reason='복귀 위치 초기화 실패';}
   }else if(this.clock()-this.stageAt>60){this.state='failed';this.reason='복귀 준비 시간 초과';}
   return;
  }
  if(this.state==='localizing'){
   if(status?.navigation?.is_localized&&this.validPose(status?.pose?.map)){
    this.queue=[{...this.origin,isHome:true}];this.reason='출발점 복귀 중';await this.next();
   }else if(this.clock()-this.stageAt>30){this.state='failed';this.reason='복귀 위치 확인 시간 초과';}
   return;
  }
  return super.observe(status);
 }
 async cancel(state='stopped',reason='운행 종료'){
  if(['exploring','saving_map'].includes(this.state)){
   const epoch=++this.epoch;this.state='canceling';const r=await this.post('/api/explore/stop',{});if(epoch!==this.epoch)return;
   this.state=r?.ok?state:'failed';this.reason=r?.ok?reason:'탐색 정지 확인 실패';return;
  }
  return super.cancel(state,reason);
 }
}
