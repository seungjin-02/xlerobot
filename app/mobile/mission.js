// Supervised mission sequencing. No ROS/driver ownership; native Nav2 remains authoritative.
export class Mission {
 constructor(post,clock=()=>performance.now()/1000){this.post=post;this.clock=clock;this.state='idle';this.epoch=0;this.reason='대기';}
 get busy(){return ['sending','running','returning','canceling','await_return'].includes(this.state);}
 validPose(p){return p&&['x','y','yaw'].every(k=>Number.isFinite(p[k]));}
 async start({mode,points,cycles=1,seconds=300},status){
  if(this.busy)throw Error('현재 운행을 먼저 종료하세요');
  if(!['goal','roundtrip','route'].includes(mode))throw Error('지원하지 않는 운행 방식');
  if(!this.validPose(status?.pose?.map))throw Error('출발점의 지도 위치를 확인할 수 없습니다');
  if(!Number.isInteger(cycles)||cycles<1||cycles>20||!Number.isFinite(seconds)||seconds<60||seconds>3600)throw Error('운행 조건이 올바르지 않습니다');
  if(!Array.isArray(points)||!points.length||points.length>100||!points.every(p=>this.validPose(p)))throw Error('목표를 선택하세요');
  if(!['running','external'].includes(status?.processes?.navigation?.state))throw Error('선택한 지도에서 주행 준비를 먼저 완료하세요');
  this.home={...status.pose.map};this.mode=mode;this.queue=[];this.epoch++;this.pending=null;this.activeSeen=false;
  for(let i=0;i<(mode==='route'?cycles:1);i++)this.queue.push(...points.map(p=>({...p})));
  if(mode!=='goal')this.queue.push({...this.home,isHome:true});
  this.deadline=this.clock()+seconds;this.reason='운행 중';await this.next();
 }
 async next(){
  if(!this.queue.length){this.state='complete';this.reason='운행 완료';return;}
  const epoch=this.epoch;this.pending=this.queue.shift();this.activeSeen=false;this.sentAt=this.clock();this.state='sending';
  const {x,y,yaw}=this.pending;const result=await this.post('/api/nav/goal',{x,y,yaw});
  if(epoch!==this.epoch)return;
  if(!result?.ok){this.state='failed';this.reason=result?.message??'목표 전송 실패';return;}
  this.state=this.pending.isHome?'returning':'running';
 }
 async update(status){
  if(!['running','returning'].includes(this.state))return;
  const nav=status?.navigation,pose=status?.pose?.map;
  if(!this.validPose(pose)){await this.cancel('failed','위치 추정이 끊겨 정지했습니다');return;}
  if(this.clock()>this.sentAt+120){await this.cancel('failed','목표 도달 시간 초과');return;}
  if(this.clock()>this.deadline&&!this.pending.isHome){await this.returnHome();return;}
  if(nav?.state==='active'){this.activeSeen=true;return;}
  if(!this.activeSeen)return; // never consume a previous goal's terminal status
  if(nav?.state==='succeeded'){
   if(Math.hypot(pose.x-this.pending.x,pose.y-this.pending.y)>.25){await this.cancel('failed','도착 위치 불일치');return;}
   await this.next();
  }else if(['failed','canceled','aborted','rejected'].includes(nav?.state)){
   this.state='failed';this.reason=nav.message??'목표 이동 중단';
  }
 }
 async cancel(state='stopped',reason='운행 종료'){
  const epoch=++this.epoch;this.state='canceling';this.queue=[];
  const result=await this.post('/api/nav/cancel',{});
  if(epoch!==this.epoch)return;
  this.state=result?.ok?state:'failed';this.reason=result?.ok?reason:'정지 요청을 확인하지 못했습니다';
 }
 async returnHome(){
  if(!this.home||!this.busy)throw Error('복귀할 출발점이 없습니다');
  const epoch=++this.epoch;this.state='canceling';this.queue=[];
  const result=await this.post('/api/nav/cancel',{});
  if(epoch!==this.epoch)return;
  if(!result?.ok){this.state='failed';this.reason='복귀 전 취소 요청 실패';return;}
  // Wait for a terminal cancellation status before issuing the return goal.
  this.state='await_return';this.reason='현재 목표 취소 확인 중';this.cancelAt=this.clock();
 }
 async observe(status){
  if(this.state==='await_return'){
   if(['canceled','succeeded','idle','failed','aborted'].includes(status?.navigation?.state)){
    this.queue=[{...this.home,isHome:true}];await this.next();
   }else if(this.clock()-this.cancelAt>5){this.state='failed';this.reason='취소 확인 시간 초과';}
   return;
  }
  await this.update(status);
 }
 disconnected(){this.epoch++;this.queue=[];this.state='stopped';this.reason='연결 끊김: 자동 재개하지 않습니다';}
}
