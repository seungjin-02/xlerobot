"""Bounded exploration and repeated patrol over observed occupancy grids.

No ROS imports, motor access, network calls or inferred physical calibration.
Goals use known free space only. Unknown/unreachable space is never declared covered.
"""
from collections import deque
from dataclasses import dataclass
import math
from clearance import euclidean_distances


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    resolution: float
    data: tuple
    origin_x: float = 0.
    origin_y: float = 0.
    origin_yaw: float = 0.
    received_at: float = 0.

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in (self.width, self.height)):
            raise ValueError('Invalid map dimensions')
        if self.width*self.height > 250000 or len(self.data) != self.width*self.height:
            raise ValueError('Map size mismatch or map exceeds 250000 cells')
        if not finite(self.resolution) or not .02 <= self.resolution <= .5:
            raise ValueError('Map resolution must be 0.02..0.5 m')
        if not all(finite(v) for v in (self.origin_x, self.origin_y, self.origin_yaw, self.received_at)):
            raise ValueError('Invalid map origin/time')
        if any(type(v) is not int or not -1 <= v <= 100 for v in self.data):
            raise ValueError('Invalid occupancy value')
        object.__setattr__(self, 'data', tuple(self.data))

    def cell(self, x, y):
        dx, dy = x-self.origin_x, y-self.origin_y
        c, s = math.cos(self.origin_yaw), math.sin(self.origin_yaw)
        col = math.floor((c*dx+s*dy)/self.resolution)
        row = math.floor((-s*dx+c*dy)/self.resolution)
        return row*self.width+col if 0 <= col < self.width and 0 <= row < self.height else None

    def world(self, index):
        x = (index % self.width+.5)*self.resolution
        y = (index // self.width+.5)*self.resolution
        c, s = math.cos(self.origin_yaw), math.sin(self.origin_yaw)
        return self.origin_x+c*x-s*y, self.origin_y+s*x+c*y

    def neighbors(self, index, diagonal=False):
        col, row = index % self.width, index // self.width
        offsets = ((1,0),(-1,0),(0,1),(0,-1))
        if diagonal: offsets += ((1,1),(1,-1),(-1,1),(-1,-1))
        for dx, dy in offsets:
            if 0 <= col+dx < self.width and 0 <= row+dy < self.height:
                yield (row+dy)*self.width+col+dx


@dataclass(frozen=True)
class Limits:
    robot_radius: float
    margin: float = .05
    max_radius: float = 3.
    max_duration: float = 600.
    max_distance: float = 50.
    cycles: int = 2
    goal_timeout: float = 45.
    map_timeout: float = 5.
    pose_timeout: float = .75
    coverage_radius: float = .25
    min_goal_distance: float = .3
    max_failures: int = 8
    known_body_radius: float = 0.

    def __post_init__(self):
        positives = ('robot_radius','max_radius','max_duration','max_distance','goal_timeout',
                     'map_timeout','pose_timeout','coverage_radius','min_goal_distance')
        if any(not finite(getattr(self,k)) or getattr(self,k) <= 0 for k in positives):
            raise ValueError('Limits must be finite and positive')
        if not .05 <= self.robot_radius <= 2 or not finite(self.margin) or self.margin < 0:
            raise ValueError('Invalid radius or margin')
        if not finite(self.known_body_radius) or not 0<=self.known_body_radius<=min(.10,self.robot_radius):
            raise ValueError('Invalid known body radius')
        if self.max_radius <= self.robot_radius+self.margin:
            raise ValueError('Operating radius too small')
        if type(self.cycles) is not int or not 1 <= self.cycles <= 100:
            raise ValueError('cycles must be 1..100')
        if type(self.max_failures) is not int or not 1 <= self.max_failures <= 100:
            raise ValueError('Invalid failure budget')


@dataclass(frozen=True)
class Goal:
    x: float
    y: float
    yaw: float
    kind: str
    path: tuple
    path_length: float


class Planner:
    def __init__(self, grid, pose, home, limits):
        # Only the confirmed solid central body already occupies this area.
        # Handle its sensor-origin blind cells without clearing ANY obstacle or
        # cells outside that body. The conservative outer radius is unchanged.
        if limits.known_body_radius:
            data=tuple(0 if v==-1 and math.dist(grid.world(i),pose[:2])+grid.resolution*math.sqrt(.5)<=limits.known_body_radius else v
                       for i,v in enumerate(grid.data))
            grid=Grid(grid.width,grid.height,grid.resolution,data,grid.origin_x,grid.origin_y,grid.origin_yaw,grid.received_at)
        self.grid, self.pose, self.home, self.limits = grid, pose, home, limits
        # Exact center distances. Account for both full occupied cells and a
        # candidate pose anywhere inside its cell, not only the cell centers.
        self.obstacles = self.distances(lambda v: v > 20, border=True)
        self.unknown = self.distances(lambda v: v == -1, border=True)
        threshold = (limits.robot_radius+limits.margin)/grid.resolution+math.sqrt(2.)
        self.safe = {i for i,v in enumerate(grid.data) if 0 <= v <= 20
                     and self.obstacles[i] > threshold and self.unknown[i] > threshold
                     and math.dist(grid.world(i),home)+limits.robot_radius+limits.margin <= limits.max_radius}
        start = grid.cell(*pose[:2])
        self.parents, self.distance = {}, {}
        if start in self.safe:
            self.parents = {start:None}; self.distance = {start:0}; queue = deque([start])
            while queue:
                current = queue.popleft()
                for neighbor in grid.neighbors(current):
                    if neighbor in self.safe and neighbor not in self.parents:
                        self.parents[neighbor] = current
                        self.distance[neighbor] = self.distance[current]+1; queue.append(neighbor)

    def distances(self, predicate, border=False):
        g=self.grid
        seeds=[predicate(v) or (border and (i%g.width in (0,g.width-1) or i//g.width in (0,g.height-1)))
               for i,v in enumerate(g.data)]
        return euclidean_distances(g.width,g.height,seeds)

    def goal(self, index, kind):
        if index not in self.parents: return None
        cells = []; current = index
        while current is not None:
            cells.append(current); current = self.parents[current]
        path = tuple(self.grid.world(i) for i in reversed(cells))
        x,y = self.grid.world(index)
        return Goal(x,y,math.atan2(y-self.pose[1],x-self.pose[0]),kind,path,(len(path)-1)*self.grid.resolution)

    def select(self, visited, failed, explore=True):
        g, limits = self.grid, self.limits
        candidates = [i for i in self.parents
                      if math.dist(g.world(i),self.pose[:2]) >= limits.min_goal_distance
                      and not any(math.dist(g.world(i),p) < max(.3,2*g.resolution) for p in failed)]
        if explore:
            band = (limits.robot_radius+limits.margin)/g.resolution+math.sqrt(.5)+2
            frontiers = [i for i in candidates if self.unknown[i] <= band
                         and self.visible_unknown(i,math.ceil(band))]
            if frontiers:
                # Prefer a nearby reachable observation point; no goal is in unknown space.
                i = min(frontiers,key=lambda n:(self.distance[n],n))
                return self.goal(i,'explore')
        covered = set(); radius = math.ceil(limits.coverage_radius/g.resolution)
        for point in visited:
            center = g.cell(*point)
            if center is not None:
                covered.update(i for i in self.near(center,radius)
                               if math.dist(g.world(i),point) <= limits.coverage_radius)
        uncovered = [i for i in candidates if i not in covered]
        return self.goal(min(uncovered,key=lambda n:(self.distance[n],n)),'patrol') if uncovered else None

    def near(self, index, radius):
        g = self.grid; x,y = index%g.width,index//g.width
        for row in range(max(0,y-radius),min(g.height,y+radius+1)):
            for col in range(max(0,x-radius),min(g.width,x+radius+1)):
                yield row*g.width+col

    def visible_unknown(self, index, radius):
        g = self.grid; x,y = index%g.width,index//g.width
        for n in self.near(index,radius):
            if g.data[n] != -1: continue
            dx,dy = n%g.width-x,n//g.width-y; steps = max(abs(dx),abs(dy))
            for step in range(1,steps+1):
                value = g.data[(y+round(dy*step/steps))*g.width+x+round(dx*step/steps)]
                if value > 20: break
                if value == -1: return True
        return False


class Mission:
    def __init__(self, limits, round_trip_distance=None,straight=False):
        if type(straight) is not bool or (straight and round_trip_distance is None):raise ValueError("Straight mode requires a round-trip target")
        self.straight=straight
        if round_trip_distance is not None and (isinstance(round_trip_distance,bool) or not finite(round_trip_distance) or not .1<=round_trip_distance<=1.):
            raise ValueError('왕복 목표 거리는 0.1~1m여야 합니다')
        self.limits = limits; self.state = 'waiting'; self.reason = None
        self.home = None; self.started = self.previous_time = self.last_pose = None
        self.trail = []; self.cycle_trail = []; self.failed = []
        self.distance = 0.; self.cycles = 0; self.sequence = 0
        self.map_distance=0.;self.travel_reference=None;self.last_travel_distance=None
        self.active = None; self.active_since = None; self.cancelling = False
        self.cancel_since = None; self.after_cancel = None; self.failures = 0
        self.return_started = None; self.events = []
        self.return_reason=None
        self.known_cells = 0; self.known_at_send = 0
        self.cached_planner = None; self.cached_map = None
        self.round_trip_distance=round_trip_distance;self.outbound_reached=False
        self.start_heading=None;self.outbound_target=None

    def command(self, action, goal=None):
        result = {'action':action,'state':self.state,'reason':self.reason,'token':self.sequence,'goal':goal}
        if action != 'wait': self.events.append({k:v for k,v in result.items() if k != 'goal'})
        return result

    def halt(self, state, reason, now):
        self.state, self.reason = state, reason
        if state=='returning':self.return_reason=reason
        if self.active and not self.cancelling:
            self.cancelling = True; self.cancel_since = now; self.after_cancel = state
            return self.command('cancel')
        return self.command('stop' if state in ('fault','stopped','blocked','complete') else 'wait')

    def pause(self, now): return self.halt('paused','operator_pause',now)
    def stop(self, now): return self.halt('stopped','operator_stop',now)

    def resume(self):
        if self.state != 'paused' or self.cancelling: return False
        self.state = 'exploring'; self.reason = None; return True

    def result(self, token, outcome):
        if outcome not in ('succeeded','failed','canceled'): raise ValueError('Unknown action outcome')
        if token != self.sequence or self.active is None: return False
        self.events.append({'event':'navigation_result','token':token,'kind':self.active.kind,
                            'outcome':outcome,'cancel_pending':self.cancelling})
        if self.cancelling:
            self.active = None; self.cancelling = False; self.state = self.after_cancel
            return True
        if self.state in ('fault','stopped','blocked','complete','paused'): return False
        goal = self.active; self.active = None
        if goal.kind in ('outbound','outbound_stage'):
            if outcome=='succeeded' and self.last_pose and math.dist(self.last_pose[:2],(goal.x,goal.y))<=.10:
                if goal.kind=='outbound':
                    self.outbound_reached=True;self.state='returning';self.reason=self.return_reason='outbound_goal_reached'
                else:self.state='outbound';self.reason='safe_waypoint_reached'
            else:
                self.failures+=1;self.state='blocked';self.reason='outbound_goal_failed'
            return True
        tolerance=.10 if self.round_trip_distance is not None else .25
        if outcome == 'succeeded' and self.last_pose and math.dist(self.last_pose[:2],(goal.x,goal.y)) <= tolerance:
            if goal.kind == 'return': self.state = 'complete'; self.reason = 'returned_home'
            elif goal.kind == 'explore' and self.known_cells <= self.known_at_send:
                self.failed.append((goal.x,goal.y)); self.failures += 1
        else:
            self.failed.append((goal.x,goal.y)); self.failures += 1
            if goal.kind == 'return': self.state = 'blocked'; self.reason = 'return_failed'
        return True

    def step(self, grid, pose, now, pose_received_at=None, sensors_ready=True,travel_distance=None):
        if not finite(now) or len(pose) != 3 or not all(finite(v) for v in pose):
            raise ValueError('Invalid time or pose')
        if self.previous_time is not None and now < self.previous_time:
            return self.halt('fault','clock_regression',now)
        self.previous_time = now
        if self.cancelling:
            if now-self.cancel_since > 3:
                self.state = 'fault'; self.reason = 'cancel_ack_timeout'
                return self.command('stop')
            return self.command('wait')
        if self.state in ('paused','stopped','fault','blocked','complete'):
            return self.command('wait')
        pose_received_at = now if pose_received_at is None else pose_received_at
        if (not sensors_ready or now-pose_received_at > self.limits.pose_timeout
                or grid is None or now-grid.received_at > self.limits.map_timeout
                or grid.received_at > now+.1 or pose_received_at > now+.1):
            return self.halt('fault','stale_sensor_map_or_pose',now)
        if self.home is None:
            self.home = tuple(pose[:2]); self.started = now; self.state = 'exploring'
            self.start_heading=pose[2]
            if self.round_trip_distance is not None:
                self.outbound_target=(pose[0]+self.round_trip_distance*math.cos(pose[2]),pose[1]+self.round_trip_distance*math.sin(pose[2]))
        if self.last_pose is not None:
            delta = math.dist(pose[:2],self.last_pose[:2])
            if delta > 1.: return self.halt('fault','localization_jump',now)
            self.map_distance+=delta
            if travel_distance is None:self.distance += delta
        if travel_distance is not None:
            if not finite(travel_distance) or travel_distance<0:return self.halt('fault','invalid_travel_distance',now)
            if self.last_travel_distance is not None and travel_distance<self.last_travel_distance:
                return self.halt('fault','odometry_distance_regression',now)
            if self.travel_reference is None:self.travel_reference=travel_distance
            self.last_travel_distance=travel_distance;self.distance=travel_distance-self.travel_reference
        self.last_pose = tuple(pose)
        if self.round_trip_distance is not None:
            dx,dy=pose[0]-self.home[0],pose[1]-self.home[1]
            lateral=-dx*math.sin(self.start_heading)+dy*math.cos(self.start_heading)
            forward=dx*math.cos(self.start_heading)+dy*math.sin(self.start_heading)
            if abs(lateral)>(.03 if self.straight else .10):return self.halt('fault','round_trip_lateral_limit',now)
            if self.straight and abs((pose[2]-self.start_heading+math.pi)%(2*math.pi)-math.pi)>.05:return self.halt('fault','straight_heading_limit',now)
            if forward>self.round_trip_distance+.10:return self.halt('fault','round_trip_overshoot',now)
        self.known_cells = sum(v != -1 for v in grid.data)
        if not self.trail or math.dist(pose[:2],self.trail[-1]) >= grid.resolution*.4:
            self.trail.append(tuple(pose[:2])); self.cycle_trail.append(tuple(pose[:2]))
        if self.distance >= self.limits.max_distance:
            return self.halt('stopped','distance_limit',now)
        if math.dist(pose[:2],self.home)+self.limits.robot_radius+self.limits.margin > self.limits.max_radius:
            return self.halt('fault','outside_operating_radius',now)
        if self.return_started is not None and now-self.return_started > self.limits.goal_timeout:
            return self.halt('blocked','return_timeout',now)
        map_key = (grid.width,grid.height,grid.resolution,grid.origin_x,grid.origin_y,grid.origin_yaw,grid.data)
        if self.active and self.cached_planner is not None and map_key == self.cached_map:
            planner = self.cached_planner
        else:
            planner = Planner(grid,pose,self.home,self.limits)
            self.cached_planner, self.cached_map = planner,map_key
        if not planner.parents: return self.halt('blocked','no_clear_known_start_cell',now)
        if grid.cell(*pose[:2]) not in planner.parents:
            return self.halt('blocked','pose_outside_reachable_component',now)
        if self.active:
            if (grid.cell(self.active.x,self.active.y) not in planner.parents
                    or any(grid.cell(*p) not in planner.safe for p in self.active.path)):
                if grid.cell(self.active.x,self.active.y) not in planner.parents:
                    self.failed.append((self.active.x,self.active.y));self.failures += 1
                if self.round_trip_distance is not None:return self.halt('blocked','round_trip_path_blocked',now)
                return self.halt('exploring','active_path_changed',now)
            if now-self.active_since > self.limits.goal_timeout:
                self.failed.append((self.active.x,self.active.y));self.failures += 1
                if self.round_trip_distance is not None:return self.halt('blocked','round_trip_goal_timeout',now)
                return self.halt('exploring','goal_timeout',now)
            if now-self.started >= self.limits.max_duration and self.active.kind != 'return':
                return self.halt('returning','duration_limit',now)
            return self.command('wait')
        returning = (self.state == 'returning' or now-self.started >= self.limits.max_duration
                     or self.failures >= self.limits.max_failures or self.cycles >= self.limits.cycles)
        if returning and self.return_reason is None:
            self.return_reason=('duration_limit' if now-self.started>=self.limits.max_duration
                                else 'navigation_failures_limit' if self.failures>=self.limits.max_failures else 'cycles_complete')
        goal = None
        if not returning and self.round_trip_distance is not None:
            returning=self.outbound_reached
            if not returning:
                remaining=math.dist(pose[:2],self.outbound_target)
                count=max(1,math.ceil(remaining/(grid.resolution*.5)))
                path=tuple((pose[0]+(self.outbound_target[0]-pose[0])*i/count,
                            pose[1]+(self.outbound_target[1]-pose[1])*i/count) for i in range(count+1))
                safe_prefix=[]
                for point in path:
                    if grid.cell(*point) not in planner.safe:break
                    safe_prefix.append(point)
                if len(safe_prefix)==len(path):
                    goal=Goal(*self.outbound_target,self.start_heading,'outbound',path,remaining)
                else:
                    # Explore only a verified footprint-clear prefix of the same
                    # straight corridor; never send Nav2 into unseen goal space.
                    candidates=[(i,p) for i,p in enumerate(safe_prefix) if .15<=math.dist(pose[:2],p)<=.30]
                    if not candidates:return self.halt('blocked','outbound_corridor_not_clear',now)
                    index,point=candidates[-1]
                    goal=Goal(*point,self.start_heading,'outbound_stage',tuple(safe_prefix[:index+1]),math.dist(pose[:2],point))
        elif not returning:
            goal=planner.select(self.cycle_trail,self.failed)
        if goal is None and not returning:
            if self.failed:
                returning=True;self.return_reason='reachable_targets_exhausted'
            else:
                self.cycles += 1
                if self.cycles < self.limits.cycles:
                    self.cycle_trail = [tuple(pose[:2])]
                    goal = planner.select(self.cycle_trail,[],explore=False)
                returning = goal is None
                if returning:self.return_reason='cycles_complete' if self.cycles>=self.limits.cycles else 'reachable_area_exhausted'
        home = planner.goal(grid.cell(*self.home),'return')
        if goal and (home is None or 2*goal.path_length+home.path_length > self.limits.max_distance-self.distance):
            returning = True; goal = None; self.reason = self.return_reason = 'return_distance_reserve'
        if returning:
            self.state = 'returning'
            if self.return_started is None: self.return_started = now
            if math.dist(pose[:2],self.home) <= (.05 if self.round_trip_distance is not None else .15):
                return self.halt('complete','finished_at_home',now)
            if home is None: return self.halt('blocked','home_unreachable',now)
            if self.round_trip_distance is not None:
                if self.straight:
                    distance=math.dist(pose[:2],self.home);count=max(1,math.ceil(distance/(grid.resolution*.5)))
                    path=tuple((pose[0]+(self.home[0]-pose[0])*i/count,pose[1]+(self.home[1]-pose[1])*i/count) for i in range(count+1))
                    if any(grid.cell(*point) not in planner.safe for point in path):return self.halt('blocked','return_corridor_not_clear',now)
                    home=Goal(*self.home,self.start_heading,'return',path,distance)
                else:
                    home=Goal(self.home[0],self.home[1],self.start_heading,home.kind,
                              home.path+(self.home,),home.path_length+math.dist(home.path[-1],self.home))
            goal = home
        self.active = goal; self.active_since = now; self.sequence += 1; self.known_at_send = self.known_cells
        self.state = 'returning' if goal.kind == 'return' else ('outbound' if goal.kind in ('outbound','outbound_stage') else ('exploring' if goal.kind == 'explore' else 'patrolling'))
        return self.command('send_goal',goal)

    def report(self):
        return {'state':self.state,'reason':self.reason,'distance_m':self.distance,'cycles_finished':self.cycles,
                'distance_source':'wheel_odometry' if self.travel_reference is not None else 'map_pose','map_distance_m':self.map_distance,
                'return_reason':self.return_reason,
                'goals_sent':self.sequence,'goal_failures':self.failures,'home':self.home,
                'active_goal_kind':self.active.kind if self.active else None,'cancel_pending':self.cancelling,
                'physical_motion_verified':False,'task_mode':'straight_round_trip' if self.straight else 'round_trip' if self.round_trip_distance is not None else 'patrol',
                'target_distance_m':self.round_trip_distance,'outbound_target':self.outbound_target,
                'outbound_reached':self.outbound_reached,
                'navigation_results':[e for e in self.events if e.get('event')=='navigation_result'][-20:],
                'round_trip_completed':self.round_trip_distance is not None and self.outbound_reached and self.state=='complete' and self.reason in ('returned_home','finished_at_home')}
