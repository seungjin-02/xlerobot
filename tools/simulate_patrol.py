#!/usr/bin/env python3
"""Deterministic grid/ray-visibility simulation, NOT SLAM or a physics engine."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from patrol import Grid,Limits,Mission


class World:
    width=70; height=50; resolution=.1
    def __init__(self):
        self.truth=[100 if x in (0,69) or y in (0,49) or (30<=x<=35 and 19<=y<=29)
                    or (x==45 and not 13<=y<=25) else 0 for y in range(50) for x in range(70)]
        self.observed=[-1]*len(self.truth)

    def reveal(self,pose):
        cx,cy=pose[0]/.1,pose[1]/.1
        for ray in range(180):
            angle=2*math.pi*ray/180
            for step in range(1,46):
                x=int(cx+math.cos(angle)*step*.33);y=int(cy+math.sin(angle)*step*.33)
                if not 0<=x<70 or not 0<=y<50:break
                i=y*70+x;self.observed[i]=self.truth[i]
                if self.truth[i]>20:break

    def collision(self,pose,radius):
        for y in range(max(0,int((pose[1]-radius)/.1)),min(50,int((pose[1]+radius)/.1)+1)):
            for x in range(max(0,int((pose[0]-radius)/.1)),min(70,int((pose[0]+radius)/.1)+1)):
                dx=max(x*.1-pose[0],0,pose[0]-(x+1)*.1)
                dy=max(y*.1-pose[1],0,pose[1]-(y+1)*.1)
                if self.truth[y*70+x]>20 and math.hypot(dx,dy)<=radius:return True
        return False


def run(scenario='explore-patrol',cycles=1,steps=2200):
    world=World();pose=(1.25,2.55,0.)
    limits=Limits(.12,margin=.03,max_radius=6.5,max_duration=1800,max_distance=180,
                  cycles=cycles,goal_timeout=120,coverage_radius=.30,min_goal_distance=.3)
    mission=Mission(limits);route=[];token=None;frames=[];collisions=0;changed=False;paused=False
    previous=[-1]*len(world.truth);now=0.; goal_kinds={};pause_until=None
    for iteration in range(steps):
        world.reveal(pose)
        if scenario=='dynamic-obstacle' and not changed and mission.distance>2 and len(route)>5:
            x,y=route[4];i=int(y/.1)*70+int(x/.1);world.truth[i]=100;changed=True;world.reveal(pose)
        grid=Grid(70,50,.1,tuple(world.observed),received_at=now)
        if scenario=='stale-map' and iteration==15:
            grid=Grid(70,50,.1,tuple(world.observed),received_at=now-10)
        if scenario=='pause-resume' and not paused and iteration==15:
            command=mission.pause(now);paused=True;pause_until=now+3
        else:
            if pause_until is not None and now>=pause_until:mission.resume();pause_until=None
            command=mission.step(grid,pose,now)
        if command['action']=='cancel':
            route=[];mission.result(command['token'],'canceled')
        elif command['action']=='send_goal':
            goal=command['goal'];route=list(goal.path);token=command['token']
            goal_kinds[goal.kind]=goal_kinds.get(goal.kind,0)+1
        changed_cells=[[i,v] for i,v in enumerate(world.observed) if v!=previous[i]]
        previous=list(world.observed)
        if changed_cells or iteration%2==0 or command['action']!='wait':
            frames.append({'time':now,'pose':pose,'state':mission.state,'action':command['action'],
                           'goal':[mission.active.x,mission.active.y] if mission.active else None,'cells':changed_cells})
        if mission.state in ('fault','blocked','complete','stopped') and not mission.cancelling:break
        if mission.state not in ('paused','fault','blocked','complete','stopped') and route:
            point=route.pop(0);pose=(*point,pose[2])
            if world.collision(pose,limits.robot_radius):collisions+=1;break
            if not route:
                # Give the mission the final measured pose before the action result.
                mission.step(Grid(70,50,.1,tuple(world.observed),received_at=now+.01),pose,now+.01)
                mission.result(token,'succeeded')
        now+=1
    report={**mission.report(),'scenario':scenario,'iterations':iteration+1,'simulated_time_s':now,
            'grid_circle_collisions':collisions,'dynamic_obstacle_inserted':changed,'goal_kinds':goal_kinds,
            'observed_cells':sum(v!=-1 for v in world.observed),'total_grid_cells':len(world.truth),
            'synthetic':True,'perfect_pose_assumed':True,'physics_engine':False,'slam_algorithm_tested':False,
            'physical_hardware_tested':False,'operator_region_drawn':False,'limits':asdict(limits)}
    return {'report':report,'width':70,'height':50,'resolution':.1,'frames':frames,'truth':world.truth}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--scenario',choices=['explore-patrol','dynamic-obstacle','pause-resume','stale-map'],default='explore-patrol')
    p.add_argument('--cycles',type=int,default=1);args=p.parse_args()
    result=run(args.scenario,args.cycles)
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'simulation.json').write_text(json.dumps(result,separators=(',',':')))
    (args.output/'report.json').write_text(json.dumps(result['report'],indent=2))
    print(json.dumps(result['report'],indent=2))
    if result['report']['grid_circle_collisions']:return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
