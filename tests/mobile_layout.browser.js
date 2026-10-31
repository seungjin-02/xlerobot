async page => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));const report={};
 for(const width of [390,1280]){
  await page.setViewportSize({width,height:1000});await page.getByRole('navigation').getByRole('button',{name:'조종',exact:true}).click();
  const drive=await page.evaluate(()=>{const r=e=>{const b=e.getBoundingClientRect();return{x:b.x,y:b.y,width:b.width,height:b.height,bottom:b.bottom}};return{camera:r(document.querySelector('#screen-drive>.camera')),controls:r(document.querySelector('#screen-drive>.controls')),speed:r(document.querySelector('#screen-drive>.speed-card')),frames:[...document.querySelectorAll('.camera-frame')].map(r),scroll:document.documentElement.scrollWidth};});
  if(drive.frames.length!==3||drive.scroll>width)throw Error('Camera layout failure');
  if(width>=760&&(Math.abs(drive.camera.bottom-drive.speed.bottom)>1||Math.abs(drive.camera.y-drive.controls.y)>1))throw Error('Column height mismatch');
  await page.screenshot({path:`private/control-center-evidence/camera-layout-${width}.png`,fullPage:true});
  await page.getByRole('navigation').getByRole('button',{name:'자율주행',exact:true}).click();
  const auto=await page.evaluate(()=>{const buttons=[...document.querySelectorAll('#navigationView .map-bar button')].map(e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom}});return{buttons,fieldGap:document.getElementById('navSpeed').closest('label').getBoundingClientRect().top-document.getElementById('navStart').getBoundingClientRect().bottom,scroll:document.documentElement.scrollWidth};});
  if(auto.fieldGap<16||auto.scroll>width)throw Error('Navigation field overlap '+JSON.stringify(auto));
  for(let i=0;i<auto.buttons.length;i++)for(let j=i+1;j<auto.buttons.length;j++){const a=auto.buttons[i],b=auto.buttons[j];if(Math.max(b.x-a.right,a.x-b.right,b.y-a.bottom,a.y-b.bottom)<7)throw Error('Toolbar cramped');}
  await page.getByRole('navigation').getByRole('button',{name:'지도 관리',exact:true}).click();
  const map=await page.evaluate(()=>{const b=document.getElementById('reloadMaps');return{gap:b.getBoundingClientRect().top-b.previousElementSibling.getBoundingClientRect().bottom,scroll:document.documentElement.scrollWidth};});
  if(map.gap<12||map.scroll>width)throw Error('Map list spacing');report[width]={drive,auto,map};
 }
 if(errors.length)throw Error(JSON.stringify(errors));return {report,errors};
}
