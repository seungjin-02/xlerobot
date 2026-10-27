"""Exact cell-center Euclidean distances; stdlib, linear time in grid size."""
import math


def squared_line(values):
    """Lower envelope of parabolas (squared distance transform)."""
    n=len(values);sites=[0]*n;edges=[0.]*(n+1);k=0
    edges[0]=-math.inf;edges[1]=math.inf
    for q in range(1,n):
        old=sites[k]
        cross=((values[q]+q*q)-(values[old]+old*old))/(2*(q-old))
        while cross<=edges[k]:
            k-=1;old=sites[k]
            cross=((values[q]+q*q)-(values[old]+old*old))/(2*(q-old))
        k+=1;sites[k]=q;edges[k]=cross;edges[k+1]=math.inf
    result=[0.]*n;k=0
    for q in range(n):
        while edges[k+1]<q:k+=1
        result[q]=(q-sites[k])**2+values[sites[k]]
    return result


def euclidean_distances(width,height,seeds):
    if width<1 or height<1 or len(seeds)!=width*height:raise ValueError('Invalid clearance grid')
    far=(width+height)**2+1
    data=[0. if seed else float(far) for seed in seeds]
    for y in range(height):
        start=y*width;data[start:start+width]=squared_line(data[start:start+width])
    for x in range(width):
        column=squared_line([data[y*width+x] for y in range(height)])
        for y,value in enumerate(column):data[y*width+x]=math.sqrt(value)
    return data
