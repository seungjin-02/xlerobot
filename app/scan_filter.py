"""Remove only the measured three-wheel near-return sectors; preserve farther obstacles."""
import math

def wheel_self_returns(ranges, angle_min, angle_increment, cutoff=.17):
    if not math.isfinite(cutoff) or not .03<cutoff<=.18:raise ValueError('Invalid wheel self-return distance')
    result=list(ranges)
    for i,value in enumerate(ranges):
        angle=math.degrees(angle_min+i*angle_increment)
        near_wheel=any(abs((angle-center+180)%360-180)<=18 for center in (-120,0,120))
        if near_wheel and math.isfinite(value) and 0<value<cutoff:result[i]=math.nan
    return result
