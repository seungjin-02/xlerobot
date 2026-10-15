"""Local episodes: timestamped camera frames, requested/applied actions and odometry.
Disk I/O stays off the motor-control thread. No cloud uploads.
"""
import http.client
import io
import json
import math
import queue
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

class CameraFeed:
    def __init__(self, host='127.0.0.1', port=8080):
        self.host, self.port = host, port
        self.frame = None
        self.error = None
        self.stop_event = threading.Event()
        self.thread = None
    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear(); self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
    def run(self):
        conn = None
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                if conn is None: conn = http.client.HTTPConnection(self.host, self.port, timeout=1)
                conn.request('GET', '/snapshot'); response = conn.getresponse()
                jpeg = response.read(2_000_001)
                if response.status != 200 or len(jpeg) > 2_000_000: raise RuntimeError('camera snapshot unavailable')
                if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'): raise RuntimeError('invalid camera JPEG')
                received = time.monotonic_ns()
                captured = int(response.getheader('X-Capture-Monotonic-Ns') or received)
                seq = int(response.getheader('X-Frame-Sequence') or received)
                from PIL import Image
                with Image.open(io.BytesIO(jpeg)) as image: dimensions = image.size
                self.frame = {'jpeg': jpeg, 'sequence': seq, 'capture_ns': captured, 'received_ns': received,
                              'width': dimensions[0], 'height': dimensions[1],
                              'timestamp_source': 'capture' if response.getheader('X-Capture-Monotonic-Ns') else 'receive'}
                self.error = None
            except Exception as error:
                self.error = str(error)
                if conn: conn.close()
                conn = None
            self.stop_event.wait(max(.001, .05 - (time.monotonic() - started)))
        if conn: conn.close()
    def close(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=2)

class EpisodeRecorder:
    def __init__(self, root, device_profile=None, feed=None, fps=20, clock=time.monotonic_ns,
                 slam_config=None, slam_supported=False, slam_factory=None):
        self.root = Path(root); self.profile = device_profile or {}
        self.feed = feed or CameraFeed(); self.clock = clock; self.fps = fps
        self.lock = threading.RLock(); self.active = False; self.finishing = False
        self.owner = None; self.error = None; self.episode_id = None
        self.samples = self.valid_samples = 0; self.last_sample_ns = 0
        self.next_sample_ns = 0
        self.last_episode = None; self.queue = None; self.thread = None
        from slam import SlamSession, configuration
        self.slam_config = slam_config or configuration()
        self.slam_supported = slam_supported
        self.slam_factory = slam_factory or SlamSession
        self.slam = None
    def start(self, owner, task, slam=False):
        if type(slam) is not bool: raise ValueError('SLAM 기록 선택은 true/false여야 합니다')
        if slam and not self.slam_supported: raise ValueError('SLAM 기록에는 실제 ROS 2와 rosbag2_py가 필요합니다. 데모는 지원하지 않습니다')
        task = str(task).strip()
        if not 1 <= len(task) <= 240: raise ValueError('수행할 작업을 1~240자로 입력하세요')
        # Starting a sensor recorder may take seconds. This lock never belongs to
        # Controller, and active stays false until the independent process is ready.
        with self.lock:
            if self.active or self.finishing: raise ValueError('기존 기록을 먼저 종료하세요')
            self.root.mkdir(parents=True, exist_ok=True); self.root.chmod(0o700)
            if shutil.disk_usage(self.root).free < 256 * 1024**2: raise ValueError('저장 공간이 256MB 미만입니다')
            self.feed.start()
            if not slam:
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    f = self.feed.frame
                    if f and self.clock() - f['received_ns'] < 200_000_000: break
                    time.sleep(.02)
                else: raise ValueError('카메라 연결을 확인하세요. 일반 기록에는 전방 영상이 필요합니다')
            self.episode_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
            self.path = self.root / self.episode_id; self.path.mkdir(mode=0o700); (self.path / 'frames').mkdir(mode=0o700)
            self.started_ns = self.clock(); self.wall_started_ns = time.time_ns()
            self.meta = {'format': 'lekiwi-episode-v1', 'episode_id': self.episode_id, 'task': task, 'fps': self.fps,
                         'started_monotonic_ns': self.started_ns, 'started_wall_ns': self.wall_started_ns,
                         'device_profile': self.profile, 'outcome': 'unfinished', 'complete': False,
                         'action_level':'published_ros_twist_after_limits',
                         'state_names': ['x_m','y_m','yaw_rad','vx_m_s','vy_m_s','yaw_rate_rad_s'],
                         'action_names': ['vx_m_s','vy_m_s','yaw_rate_rad_s']}
            self._write_meta(); self.queue = queue.Queue(maxsize=256); self.stop_event = threading.Event()
            self.slam = self.slam_factory(self.slam_config) if slam else None
            if self.slam:
                try:
                    self.slam.start(self.path)
                    self.meta['slam'] = {'enabled':True,'config':self.slam_config,'bag':'slam/bag'}
                except Exception as error:
                    self.slam.stop()
                    self.meta.update(error=str(error),outcome='interrupted',slam={'enabled':True,'complete':False})
                    self._write_meta(); self.feed.close(); self.slam = None
                    raise
            self.active = True; self.finishing = False; self.owner = owner; self.error = None
            self.samples = self.valid_samples = 0; self.last_sample_ns = 0; self.next_sample_ns = 0
            self.thread = threading.Thread(target=self._writer, daemon=True); self.thread.start()
            return self.episode_id
    def _write_meta(self):
        tmp = self.path / 'episode.json.tmp'; tmp.write_text(json.dumps(self.meta,ensure_ascii=False,indent=2)); tmp.replace(self.path/'episode.json')
    def event(self, data):
        if not self.active: return
        self._enqueue(('event', {**data, 'robot_monotonic_ns': self.clock()}))
    def _enqueue(self, item):
        try: self.queue.put_nowait(item)
        except queue.Full:
            self.error = '기록 저장이 지연되어 종료했습니다'; self.active = False; self.finishing = True
            self.meta['outcome'] = 'interrupted'; self.stop_event.set()
    def sample(self, requested, applied, state, motor_ready, connection_age_ms, operator_connected):
        if not self.active: return
        f = self.feed.frame
        now = self.clock()
        if now < self.next_sample_ns: return
        interval = round(1_000_000_000 / self.fps)
        self.next_sample_ns = self.next_sample_ns + interval if self.next_sample_ns and now - self.next_sample_ns < interval else now + interval
        self.last_sample_ns = now
        camera_age = (now - f['capture_ns']) / 1e6 if f else None
        state_age = (now - state['received_ns']) / 1e6 if state else None
        values = list(state['values']) if state else None
        valid = bool(f and state and 0 <= camera_age <= 150 and 0 <= state_age <= 250 and operator_connected
                     and all(math.isfinite(float(v)) for v in [*requested,*applied,*values]))
        doc = {'robot_monotonic_ns': now, 'elapsed_s': (now-self.started_ns)/1e9,
               'requested_action': list(requested), 'applied_action': list(applied), 'state': values,
               'state_ros_stamp_ns': state.get('ros_stamp_ns') if state else None,
               'motor_ready': motor_ready, 'connection_age_ms': connection_age_ms,
               'camera_capture_ns': f['capture_ns'] if f else None, 'camera_received_ns': f['received_ns'] if f else None,
               'camera_sequence': f['sequence'] if f else None, 'camera_timestamp_source': f['timestamp_source'] if f else None,
               'camera_age_ms': camera_age, 'state_age_ms': state_age, 'training_valid': valid}
        self._enqueue(('sample',doc, f['jpeg'] if f else None))
    def finish(self, owner, outcome='unfinished', force=False):
        if outcome not in ('success','failure','unfinished','interrupted'): raise ValueError('잘못된 결과 표시')
        with self.lock:
            if not self.active and not self.finishing: return self.last_episode
            if not force and owner != self.owner: raise ValueError('기록을 시작한 폰에서 종료하세요')
            self.active = False; self.finishing = True; self.meta['outcome'] = outcome; self.stop_event.set()
            thread = self.thread
        thread.join(timeout=5)
        if thread.is_alive(): raise ValueError('저장 마무리 중입니다. 잠시 후 다시 확인하세요')
        return self.last_episode
    def _writer(self):
        index = 0
        try:
            with (self.path/'samples.jsonl').open('w') as samples, (self.path/'commands.jsonl').open('w') as events:
                while not self.stop_event.is_set() or not self.queue.empty():
                    try: item = self.queue.get(timeout=.1)
                    except queue.Empty: continue
                    if item[0] == 'event': events.write(json.dumps(item[1],ensure_ascii=False,allow_nan=False)+'\n'); continue
                    _, doc, jpeg = item
                    if index % 100 == 0 and shutil.disk_usage(self.root).free < 128 * 1024**2:
                        raise OSError('저장 공간이 부족합니다')
                    if self.slam and index % 20 == 0:
                        status = self.slam.status()
                        if status.get('error') or not status.get('ready'):
                            raise OSError('SLAM 센서 기록 오류: '+str(status.get('error') or status.get('missing')))
                    if jpeg:
                        name = f'frames/{index:07d}.jpg'; (self.path/name).write_bytes(jpeg); doc['image'] = name
                    else: doc['image'] = None
                    samples.write(json.dumps(doc,ensure_ascii=False,allow_nan=False)+'\n')
                    self.samples += 1; self.valid_samples += int(doc['training_valid']); index += 1
        except Exception as error:
            self.error = str(error); self.meta['outcome'] = 'interrupted'
        finally:
            if self.slam:
                try:
                    summary = self.slam.stop()
                    self.meta['slam'].update(summary)
                    if not summary.get('complete') or not summary.get('ready'):
                        self.error = self.error or 'SLAM 센서 기록 불완전: manifest와 capture.log 확인'
                    self.meta['slam']['valid_for_mapping'] = bool(summary.get('complete') and summary.get('ready'))
                    from slam import atomic_json
                    atomic_json(self.path/'slam/manifest.json',self.meta['slam'])
                except Exception as error:
                    self.error = str(error)
                if self.error: self.meta['outcome'] = 'interrupted'
            self.meta.update(ended_monotonic_ns=self.clock(), samples=self.samples, valid_samples=self.valid_samples,
                             complete=self.error is None, error=self.error)
            try: self._write_meta()
            except OSError as error: self.error = str(error)
            self.feed.close()
            self.last_episode = {'id':self.episode_id,'outcome':self.meta['outcome'],'samples':self.samples,'valid_samples':self.valid_samples,'error':self.error}
            self.active = self.finishing = False; self.owner = None
    def status(self, owner=None):
        return {'active':self.active,'finishing':self.finishing,'mine':bool(self.owner) and self.owner==owner,
                'episode_id':self.episode_id,'samples':self.samples,'valid_samples':self.valid_samples,
                'error':self.error,'camera_error':self.feed.error,'last_episode':self.last_episode,'fps':self.fps,
                'elapsed_s':max(0, (self.clock()-self.started_ns)/1e9) if self.active or self.finishing else 0,
                'slam':{'available':self.slam_supported,'enabled':self.slam is not None,
                        'config':self.slam_config, **(self.slam.status() if self.slam else {})}}
    def close(self):
        if self.active or self.finishing: self.finish(None,'interrupted',force=True)
        self.feed.close()

class DemoCameraFeed:
    def __init__(self):
        from PIL import Image, ImageDraw
        image=Image.new('RGB',(640,480),'#20342c'); ImageDraw.Draw(image).text((24,24),'SIMULATION - NO ROBOT CAMERA',fill='white')
        buffer=io.BytesIO(); image.save(buffer,format='JPEG'); self.jpeg=buffer.getvalue(); self.error=None
    def start(self): pass
    @property
    def frame(self):
        now=time.monotonic_ns()
        return {'jpeg':self.jpeg,'sequence':now//50000000,'capture_ns':now,'received_ns':now,'width':640,'height':480,'timestamp_source':'simulation'}
    def close(self): pass
