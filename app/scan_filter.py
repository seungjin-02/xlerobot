"""Remove configured three-wheel near returns; preserve raw and farther obstacles."""
import math

def wheel_self_returns(ranges, angle_min, angle_increment, cutoff=.17, centers=(-120,0,120), self_radius=0.):
    if not math.isfinite(cutoff) or not .03<cutoff<=.18:raise ValueError('Invalid wheel self-return distance')
    if not isinstance(centers,(list,tuple)) or len(centers)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>180 for v in centers):
        raise ValueError('Invalid wheel filter angles')
    if isinstance(self_radius,bool) or not isinstance(self_radius,(int,float)) or not math.isfinite(self_radius) or not 0<=self_radius<=.19:
        raise ValueError('Invalid self reflection radius')
    result=list(ranges)
    for i,value in enumerate(ranges):
        angle=math.degrees(angle_min+i*angle_increment)
        near_wheel=any(abs((angle-center+180)%360-180)<=18 for center in centers)
        if math.isfinite(value) and 0<value and (value<self_radius or near_wheel and value<cutoff):result[i]=math.nan
    return result
