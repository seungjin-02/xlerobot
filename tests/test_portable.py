import copy
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'));sys.path.insert(0,str(ROOT))
from recorder import EpisodeRecorder,DemoCameraFeed
from setup_robot import validate_profile,read_profile,wifi_qr_payload
from export_lerobot import uniform_segments,validated_image
from PIL import Image
import io

class Clock:
    def __init__(self):self.now=500_000_000_000
    def __call__(self):return self.now
    def advance(self,ns):self.now+=ns
class Feed:
    error=None
    def __init__(self,clock):
        self.clock=clock;self.age=0
        buffer=io.BytesIO();Image.new('RGB',(32,24),'green').save(buffer,format='JPEG');self.jpeg=buffer.getvalue()
    def start(self):pass
    def close(self):pass
    @property
    def frame(self):
        now=self.clock();return {'jpeg':self.jpeg,'capture_ns':now-self.age,'received_ns':now,'sequence':now//50000000,'width':32,'height':24,'timestamp_source':'capture'}

class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.clock=Clock();self.feed=Feed(self.clock)
        self.rec=EpisodeRecorder(self.root,{'demo':True},self.feed,clock=self.clock)
        self.rec.start('phone','테스트 주차')
    def tearDown(self):self.rec.close();self.temp.cleanup()
    def sample(self,connected=True):
        state={'received_ns':self.clock(),'ros_stamp_ns':1,'values':[0.,0.,0.,.2,0.,0.]}
        self.rec.sample((.9,0,0),(.2,0,0),state,True,0,connected)
    def read(self):return [json.loads(line) for line in (self.rec.path/'samples.jsonl').read_text().splitlines()]
    def test_requested_and_applied_actions_are_distinct(self):
        self.sample();self.rec.finish('phone','success');row=self.read()[0]
        self.assertEqual(row['requested_action'],[.9,0,0]);self.assertEqual(row['applied_action'],[.2,0,0]);self.assertTrue(row['training_valid'])
    def test_frame_timing_is_saved(self):
        self.sample();self.rec.finish('phone');r=self.read()[0]
        self.assertEqual(r['robot_monotonic_ns'],r['camera_capture_ns']);self.assertEqual(r['camera_timestamp_source'],'capture')
    def test_disconnected_period_excluded_from_training(self):
        self.sample(False);self.rec.finish('phone');self.assertFalse(self.read()[0]['training_valid'])
    def test_stale_camera_excluded(self):
        self.feed.age=200_000_000;self.sample();self.rec.finish('phone');self.assertFalse(self.read()[0]['training_valid'])
    def test_twenty_hz_sampling_with_fifty_hz_control(self):
        for _ in range(50):self.sample();self.clock.advance(20_000_000)
        self.rec.finish('phone');self.assertEqual(len(self.read()),20)
    def test_final_metadata_has_result_and_count(self):
        self.sample();r=self.rec.finish('phone','success');m=json.loads((self.rec.path/'episode.json').read_text())
        self.assertTrue(m['complete']);self.assertEqual(m['outcome'],'success');self.assertEqual(m['samples'],1);self.assertEqual(r['valid_samples'],1)
    def test_other_phone_cannot_finish(self):
        with self.assertRaises(ValueError):self.rec.finish('other','success')
        self.assertTrue(self.rec.active)
    def test_in_progress_metadata_is_not_complete(self):
        m=json.loads((self.rec.path/'episode.json').read_text());self.assertFalse(m['complete'])
    def test_finish_interrupted_on_shutdown(self):
        self.sample();self.rec.close();m=json.loads((self.rec.path/'episode.json').read_text());self.assertEqual(m['outcome'],'interrupted')
    def test_live_clock_camera_sample_not_rejected_by_timestamp_order(self):
        import time
        other=EpisodeRecorder(self.root/'live',{'demo':True},DemoCameraFeed())
        other.start('p','live clock test')
        state={'received_ns':time.monotonic_ns(),'ros_stamp_ns':1,'values':[0.]*6}
        other.sample((0.,0.,0.),(0.,0.,0.),state,False,0,True)
        result=other.finish('p','success');self.assertEqual(result['valid_samples'],1)
        other.close()
    def test_second_recording_cannot_overlap(self):
        with self.assertRaises(ValueError):self.rec.start('phone','another')

class SetupTests(unittest.TestCase):
    def setUp(self):self.profile=read_profile(ROOT/'profiles/standard-sts3215.yaml')
    def test_current_robot_usb_identifier_not_bundled(self):self.assertEqual(self.profile['lekiwi_node']['ros__parameters']['serial_port'],'AUTO')
    def test_accepts_wheel_permutations_and_preserves_output_limit(self):
        p=self.profile['lekiwi_node']['ros__parameters'];p['wheel_ids']=[8,9,7];p['serial_port']='/dev/serial/by-id/new-device'
        result=validate_profile(self.profile)['lekiwi_node']['ros__parameters']
        self.assertEqual(result['wheel_ids'],[8,9,7]);self.assertEqual(result['speed_tick_limit'],1500);self.assertFalse(result['torque_enable'])
    def test_arm_ids_rejected(self):
        self.profile['lekiwi_node']['ros__parameters']['wheel_ids']=[1,2,3]
        with self.assertRaises(ValueError):validate_profile(self.profile)
    def test_invalid_geometry_rejected(self):
        for value in [0,float('nan'),-1]:
            p=copy.deepcopy(self.profile);p['lekiwi_node']['ros__parameters']['wheel_radius']=value
            with self.assertRaises(ValueError):validate_profile(p)
    def test_wifi_qr_escapes_reserved_characters(self):
        self.assertEqual(wifi_qr_payload('a;b:c','p\\"w'), 'WIFI:T:WPA;S:a\\;b\\:c;P:p\\\\\\"w;;')
    def test_oversized_motor_output_rejected(self):
        self.profile['lekiwi_node']['ros__parameters']['speed_tick_limit']=4000
        with self.assertRaises(ValueError):validate_profile(self.profile)

class ExportTests(unittest.TestCase):
    def rows(self):return [{'training_valid':True,'elapsed_s':i/20,'image':'frames/a.jpg','state':[0]*6,'applied_action':[.1,0,0]} for i in range(30)]
    def test_invalid_interval_splits_episodes(self):
        rows=self.rows();rows[15]['training_valid']=False
        result=uniform_segments(rows);self.assertEqual(len(result),2);self.assertTrue(all(len(s)>=10 for s in result))
    def test_short_segment_skipped(self):self.assertEqual(uniform_segments(self.rows()[:3]),[])
    def test_finite_actions_required(self):
        rows=self.rows();rows[15]['applied_action'][0]=float('nan');self.assertEqual(len(uniform_segments(rows)),2)
    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);episode=root/'episode';episode.mkdir();(root/'secret').write_text('no')
            with self.assertRaises(ValueError):validated_image(episode,{'image':'../secret'})

if __name__=='__main__':unittest.main(verbosity=2)
