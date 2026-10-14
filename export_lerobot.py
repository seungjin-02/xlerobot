#!/usr/bin/env python3
"""Convert completed local demonstrations to a base-only LeRobot dataset.
Default: successful, complete episodes and fresh, connected observations only.
No uploads. LeRobot 0.6.x is required in the exporting Python environment.
"""
import argparse
import bisect
import json
import math
from pathlib import Path

def collect_episodes(root):
    if (root/'episode.json').is_file(): return [root]
    return sorted(p.parent for p in root.glob('*/episode.json'))

def validated_image(episode, row):
    image=(episode/row['image']).resolve()
    if not image.is_relative_to(episode.resolve()) or not image.is_file(): raise ValueError('Invalid image path')
    return image

def uniform_segments(rows, fps=20, min_frames=10):
    # Split gaps before resampling; never bridge a disconnected/missing-data interval.
    valid=[];groups=[];previous=None
    for row in rows:
        ok=row.get('training_valid') and row.get('image') and len(row.get('state') or [])==6 and len(row.get('applied_action') or [])==3
        if ok:
            t=float(row['elapsed_s'])
            ok=math.isfinite(t) and all(math.isfinite(float(v)) for v in [*row['state'],*row['applied_action']])
        if not ok:
            if valid:groups.append(valid);valid=[]
            previous=None;continue
        if previous is not None and (t<=previous or t-previous>1.6/fps):
            if valid:groups.append(valid)
            valid=[]
        valid.append(row);previous=t
    if valid:groups.append(valid)
    segments=[]
    for group in groups:
        times=[float(r['elapsed_s']) for r in group]
        resampled=[]
        t=times[0]
        while t<=times[-1]+1e-8:
            index=bisect.bisect_left(times,t)
            choices=[i for i in (index-1,index) if 0<=i<len(group)]
            nearest=min(choices,key=lambda i:abs(times[i]-t))
            if abs(times[nearest]-t)>0.75/fps: break
            resampled.append(group[nearest]);t+=1/fps
        if len(resampled)>=min_frames:segments.append(resampled)
    return segments

def export(root, destination, repo_id, include_failures=False, include_unfinished=False, allow_demo=False):
    import numpy as np
    from PIL import Image
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    candidates=[];skipped=[];dimensions=None
    for episode in collect_episodes(root):
        meta=json.loads((episode/'episode.json').read_text())
        if not meta.get('complete'):skipped.append({'episode':episode.name,'reason':'incomplete'});continue
        outcome=meta.get('outcome')
        if outcome!='success' and not (include_failures and outcome=='failure') and not (include_unfinished and outcome in ('unfinished','interrupted')):
            skipped.append({'episode':episode.name,'reason':'outcome not selected'});continue
        if meta.get('device_profile',{}).get('demo') and not allow_demo:
            skipped.append({'episode':episode.name,'reason':'simulation'});continue
        rows=[json.loads(line) for line in (episode/'samples.jsonl').read_text().splitlines() if line]
        segments=uniform_segments(rows)
        if not segments: skipped.append({'episode':episode.name,'reason':'no continuous valid segment'})
        for segment in segments:
            image=validated_image(episode,segment[0])
            with Image.open(image) as frame:shape=(frame.height,frame.width,3)
            if dimensions is None:dimensions=shape
            if shape!=dimensions:raise ValueError('카메라 해상도가 다른 기록은 별도 데이터셋으로 변환하세요')
            candidates.append((episode,meta,segment))
    if not candidates:raise ValueError('변환할 성공 기록/유효 연속 구간이 없습니다. 최소 10프레임이 필요합니다')
    if destination.exists():raise ValueError('대상 폴더가 이미 있습니다. 새 폴더를 지정하세요')
    state_names=['x_m','y_m','yaw_rad','vx_m_s','vy_m_s','yaw_rate_rad_s']
    action_names=['vx_m_s','vy_m_s','yaw_rate_rad_s']
    features={'observation.images.front':{'dtype':'image','shape':dimensions,'names':['height','width','channel']},
              'observation.state':{'dtype':'float32','shape':(6,),'names':state_names},
              'action':{'dtype':'float32','shape':(3,),'names':action_names},
              'requested_action':{'dtype':'float32','shape':(3,),'names':action_names}}
    dataset=LeRobotDataset.create(repo_id=repo_id,root=destination,fps=20,robot_type='lekiwi_mobile_base',features=features,use_videos=False,image_writer_threads=2)
    origins=[]
    try:
        for episode,meta,segment in candidates:
            for row in segment:
                with Image.open(validated_image(episode,row)) as frame:
                    image=np.asarray(frame.convert('RGB'))
                if image.shape!=dimensions:raise ValueError('기록 중 카메라 해상도가 변경됐습니다')
                dataset.add_frame({'observation.images.front':image,'observation.state':np.array(row['state'],dtype=np.float32),
                                   'action':np.array(row['applied_action'],dtype=np.float32),'requested_action':np.array(row['requested_action'],dtype=np.float32),
                                   'task':meta['task']})
            dataset.save_episode()
            origins.append({'source_episode':episode.name,'source_outcome':meta['outcome'],'source_device_profile':meta['device_profile'],
                            'source_start_elapsed_s':segment[0]['elapsed_s'],'source_end_elapsed_s':segment[-1]['elapsed_s'],'frames':len(segment)})
    finally:dataset.finalize()
    report={'format':'LeRobotDataset','fps':20,'episodes':len(origins),'frames':sum(e['frames'] for e in origins),'action_kind':'applied_base_velocity',
            'action_units':['m/s','m/s','rad/s'],'source_segments':origins,'skipped':skipped,'uploaded':False}
    (destination/'source-recordings.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('records',type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--repo-id',default='local/lekiwi-base-demos')
    p.add_argument('--include-failures',action='store_true');p.add_argument('--include-unfinished',action='store_true');p.add_argument('--allow-demo',action='store_true')
    a=p.parse_args();r=export(a.records,a.output,a.repo_id,a.include_failures,a.include_unfinished,a.allow_demo)
    print(json.dumps({k:v for k,v in r.items() if k not in ('source_segments','skipped')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
