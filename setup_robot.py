#!/usr/bin/env python3
"""One-time provisioning; never starts motors or calibrates wheels."""
import argparse
import getpass
import html
import json
import math
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parent


def read_profile(path):
    data=yaml.safe_load(Path(path).read_text())
    if not isinstance(data,dict) or not isinstance(data.get('lekiwi_node',{}).get('ros__parameters'),dict):
        raise ValueError('lekiwi_node.ros__parameters 형식의 프로필이 필요합니다')
    return data

def validate_profile(data):
    p=data['lekiwi_node']['ros__parameters']
    ids=p.get('wheel_ids',[]); directions=p.get('wheel_directions',[])
    if len(ids)!=3 or any(type(i) is not int for i in ids) or set(ids)!={7,8,9}:
        raise ValueError('바퀴 ID 7·8·9만 지원합니다. 팔 ID를 지정하지 마세요')
    if len(directions)!=3 or any(type(d) not in (int,float) or d not in (-1,1) for d in directions):
        raise ValueError('wheel_directions는 바퀴 순서에 맞는 ±1 세 개여야 합니다')
    for name in ('wheel_radius','base_radius','speed_tick_scale'):
        value=p.get(name)
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0: raise ValueError(name+' 값이 필요합니다')
    ticks=p.get('speed_tick_limit',1500)
    if type(ticks) is not int or not 1<=ticks<=3000: raise ValueError('바퀴 출력 제한은 1~3000 ticks/s로 지정하세요')
    # Preserve each robot's output ceiling while sharing the same UI request range.
    p.update(speed_tick_limit=ticks, max_linear_x=.9,max_linear_y=.9,max_linear_speed=.9,max_angular_z=4.5,
             max_wheel_speed=(.9+p['base_radius']*4.5)/p['wheel_radius'],
             motor_backend='feetech',enable_motor_write=True,torque_enable=False,cmd_vel_timeout=.3,
             odom_source='encoder',encoder_feedback_source='position',encoder_position_tick_deadband=0)
    if p['max_wheel_speed']*p['speed_tick_scale']>32767: raise ValueError('기하/속도 환산이 모터 명령 범위를 초과합니다')
    if not p.get('serial_port'): raise ValueError('serial_port가 필요합니다')
    return data

def discover_serials(dev=Path('/dev/serial/by-id')):
    return sorted(str(p) for p in dev.glob('*') if p.exists())

def select_serial(p, explicit, noninteractive):
    if explicit: p['serial_port']=str(Path(explicit).resolve()) if '/by-id/' not in explicit else explicit
    if p.get('serial_port') and Path(p['serial_port']).exists(): return
    ports=discover_serials()
    preferred=[p for p in ports if '1a86' in p or 'CH340' in p or 'CH341' in p]
    if len(preferred)==1: p['serial_port']=preferred[0];return
    if len(ports)==1: p['serial_port']=ports[0];return
    if noninteractive: raise ValueError('모터 USB가 여러 개거나 없습니다. --serial-port로 지정하세요')
    print('모터 버스의 USB 포트를 선택하세요. 라이다 포트와 구분해야 합니다.')
    for index,port in enumerate(ports): print(f'  {index+1}. {port}')
    choice=input('포트 번호 또는 /dev/serial/by-id/... 경로: ').strip()
    port=ports[int(choice)-1] if choice.isdigit() and 1<=int(choice)<=len(ports) else choice
    if not Path(port).exists(): raise ValueError('선택한 USB 장치가 없습니다')
    p['serial_port']=port

def wifi_qr_payload(ssid,password):
    def esc(value):
        return ''.join('\\'+c if c in '\\;,:"' else c for c in value)
    return 'WIFI:T:WPA;S:'+esc(ssid)+';P:'+esc(password)+';;'

def write_card(folder, name, ssid, password, pin, url):
    import qrcode
    import qrcode.image.svg
    folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
    for payload,filename in [(wifi_qr_payload(ssid,password),'wifi.svg'),(url,'control.svg')]:
        qr=qrcode.make(payload,image_factory=qrcode.image.svg.SvgPathImage)
        qr.save(str(folder/filename))
    esc=html.escape
    body=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>{esc(name)} 연결 카드</title>
<style>body{{font:16px system-ui;max-width:760px;margin:32px auto;padding:16px;color:#173127}}h1{{font-size:28px}}.codes{{display:flex;gap:24px;flex-wrap:wrap}}section{{flex:1;min-width:250px;border:1px solid #ccd8cd;border-radius:16px;padding:20px}}img{{width:220px;max-width:100%}}code{{word-break:break-all}}@media print{{body{{margin:0}}}}</style>
<h1>{esc(name)} · 폰 조종</h1><div class="codes"><section><h2>1. Wi-Fi 연결</h2><img src="wifi.svg" alt="Wi-Fi QR"><p>Wi-Fi: <strong>{esc(ssid)}</strong></p><p>암호: <code>{esc(password)}</code></p></section><section><h2>2. 조종 화면 열기</h2><img src="control.svg" alt="조종 URL QR"><p><a href="{esc(url)}">{esc(url)}</a></p><p>접속 코드: <strong>{esc(pin)}</strong></p></section></div>
<p>인터넷 없이 연결 유지 선택. 접속이 안 되면 폰 핫스팟과 모바일 데이터를 잠시 끄세요.</p><p>노트북 없이 사용 가능합니다. 설치 후 최초 1회 재부팅하고, 바퀴 방향과 정지를 낮은 설정에서 확인하세요.</p></html>'''
    (folder/'index.html').write_text(body)
    for file in folder.iterdir(): file.chmod(0o600)

def configure_ap(name,ssid,password,skip=False,profile=None,activate=False):
    if skip: return profile or 'lekiwi-ap'
    connection=profile or 'lekiwi-phone-ap'
    if profile:
        subprocess.run(['sudo','nmcli','con','modify',profile,'connection.autoconnect','yes','connection.autoconnect-priority','999','802-11-wireless.ssid',ssid,'ipv4.method','shared','ipv4.addresses','192.168.4.1/24'],check=True)
    else:
        import uuid
        def safe(value):
            if '\n' in value or '\r' in value: raise ValueError('Wi-Fi 이름/암호에 줄바꿈은 허용하지 않습니다')
            return value.replace('\\','\\\\')
        content=f'[connection]\nid={connection}\nuuid={uuid.uuid4()}\ntype=wifi\ninterface-name=wlan0\nautoconnect=true\nautoconnect-priority=999\n\n[wifi]\nmode=ap\nssid={safe(ssid)}\nband=bg\nchannel=6\n\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={safe(password)}\n\n[ipv4]\nmethod=shared\naddress1=192.168.4.1/24\n\n[ipv6]\nmethod=disabled\n'
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory)/'ap.nmconnection';temp.write_text(content);temp.chmod(0o600)
            target='/etc/NetworkManager/system-connections/lekiwi-phone-ap.nmconnection'
            subprocess.run(['sudo','install','-m','600',str(temp),target],check=True)
            subprocess.run(['sudo','nmcli','con','load',target],check=True)
    return connection

def main():
    parser=argparse.ArgumentParser(description='LeKiwi 최초 설치 · 모터 활성화 없음')
    parser.add_argument('--profile');parser.add_argument('--serial-port');parser.add_argument('--workspace')
    parser.add_argument('--name');parser.add_argument('--ssid');parser.add_argument('--wifi-credentials',type=Path)
    parser.add_argument('--pin',default=None);parser.add_argument('--camera',default='0');parser.add_argument('--camera-rotation',type=int,choices=(0,90,180,270),default=0)
    parser.add_argument('--has-arm',action='store_true');parser.add_argument('--wrist-camera');parser.add_argument('--wrist-rotation',type=int,choices=(0,90,180,270),default=0)
    parser.add_argument('--ap-profile');parser.add_argument('--skip-network',action='store_true');parser.add_argument('--activate-ap',action='store_true')
    parser.add_argument('--noninteractive',action='store_true');parser.add_argument('--confirm-wheel-map',action='store_true');parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--config-dir',type=Path,default=Path.home()/'.config/lekiwi-phone')
    args=parser.parse_args()
    if os.geteuid()==0: raise ValueError('sudo로 전체 설치를 실행하지 마세요. 로봇 사용자 계정에서 실행하세요')
    config_dir=args.config_dir;config_path=config_dir/'config.json'
    old=json.loads(config_path.read_text()) if config_path.exists() else {}
    candidate=args.profile or (old.get('profile') if old.get('profile') and Path(old['profile']).exists() else None)
    if not candidate:
        conventional=Path.home()/'lekiwi_autonomy_ws/base-profile-initial.yaml'
        candidate=str(conventional) if conventional.exists() else str(ROOT/'profiles/standard-sts3215.yaml')
    data=read_profile(candidate);p=data['lekiwi_node']['ros__parameters']
    select_serial(p,args.serial_port,args.noninteractive)
    original_device=old.get('device_mac')
    mac_path=Path('/sys/class/net/wlan0/address')
    current_device=mac_path.read_text().strip() if mac_path.exists() else None
    device_changed=bool(original_device and original_device!=current_device)
    if not args.confirm_wheel_map and (not old or device_changed):
        if args.noninteractive: raise ValueError('모터 순서/방향을 확인한 뒤 --confirm-wheel-map을 지정하세요')
        print('현재 선택된 바퀴 순서:',p['wheel_ids'],'방향:',p['wheel_directions'])
        print('템플릿은 현재 기기의 실제 순서/방향을 보장하지 않습니다. 필요하면 프로필 파일을 수정하세요.')
        if input('이 기기에서 바퀴 번호·방향·치수를 확인했나요? [yes/no]: ').strip().lower()!='yes':
            raise ValueError('기기별 프로필 확인 후 다시 설치하세요')
    validate_profile(data)
    unique=current_device.replace(':','')[-6:] if current_device else (Path('/etc/machine-id').read_text().strip()[-6:] if Path('/etc/machine-id').exists() else secrets.token_hex(3))
    name=args.name or (old.get('name') if not device_changed else None) or 'LeKiwi-'+unique
    ssid=args.ssid or (old.get('ssid') if not device_changed else None) or name
    if not args.ap_profile and not args.skip_network:
        try:
            active=subprocess.check_output(['nmcli','--escape','no','-t','-f','NAME,DEVICE','con','show','--active'],text=True)
            for line in active.splitlines():
                profile,device=line.rsplit(':',1)
                if device=='wlan0' and subprocess.check_output(['nmcli','-g','802-11-wireless.mode','con','show',profile],text=True).strip()=='ap':
                    args.ap_profile=profile
                    break
        except (OSError,ValueError,subprocess.CalledProcessError): pass
    credentials=json.loads(args.wifi_credentials.read_text()) if args.wifi_credentials else {}
    password=credentials.get('password') or old.get('wifi_password')
    if args.ap_profile and not args.skip_network:
        actual_password=subprocess.check_output(['sudo','nmcli','--show-secrets','-g','802-11-wireless-security.psk','con','show',args.ap_profile],text=True).strip()
        if not actual_password: raise ValueError('기존 AP 암호를 읽지 못했습니다. WPA AP 설정을 확인하세요')
        if credentials.get('password') and credentials['password']!=actual_password: raise ValueError('입력한 Wi-Fi 암호가 기존 AP 암호와 다릅니다')
        password=actual_password
    if args.skip_network and not password: raise ValueError('--skip-network 사용 시 실제 AP 암호가 담긴 --wifi-credentials 파일이 필요합니다')
    password=password or secrets.token_urlsafe(12)
    if not 8<=len(password)<=63 or '\n' in password or '\r' in password: raise ValueError('Wi-Fi 암호는 8~63자여야 합니다')
    if not 1<=len(ssid.encode())<=32 or '\n' in ssid or '\r' in ssid: raise ValueError('Wi-Fi 이름은 1~32바이트여야 합니다')
    pin=args.pin or old.get('pin') or '1119'
    if not isinstance(pin,str) or not pin.isdigit() or not 4<=len(pin)<=8: raise ValueError('접속 코드는 4~8자리 숫자여야 합니다')
    workspace=Path(args.workspace or old.get('workspace') or Path.home()/'.local/share/lekiwi-phone/ros_ws').expanduser().resolve()
    camera=args.camera
    if not (camera.isdigit() or camera.startswith('/dev/')) or any(c in camera for c in '\n\r'): raise ValueError('카메라는 번호 또는 /dev/... 경로로 지정하세요')
    summary={'robot_name':name,'ssid':ssid,'serial_port':p['serial_port'],'wheel_ids':p['wheel_ids'],'wheel_directions':p['wheel_directions'],'workspace':str(workspace),'camera':camera,'url':'http://192.168.4.1:8090','motor_activation':False,'dry_run':args.dry_run}
    if args.dry_run: print(json.dumps(summary,ensure_ascii=False,indent=2));return
    if not (workspace/'install/setup.bash').exists(): raise ValueError('바퀴 제어 workspace가 없습니다. 먼저 install.sh로 의존성과 드라이버를 준비하세요')
    config_dir.mkdir(parents=True,exist_ok=True);config_dir.chmod(0o700)
    profile_path=config_dir/'robot-profile.yaml'
    if profile_path.exists(): shutil.copy2(profile_path,config_dir/'robot-profile.previous.yaml')
    profile_temp=profile_path.with_suffix('.yaml.tmp');profile_temp.write_text(yaml.safe_dump(data,sort_keys=False));profile_temp.chmod(0o600);profile_temp.replace(profile_path)
    config={**old,'pin':pin,'profile':str(profile_path),'workspace':str(workspace),'ros_setup':'/opt/ros/jazzy/setup.bash','workspace_setup':str(workspace/'install/setup.bash'),
            'name':name,'device_mac':current_device,'ssid':ssid,'wifi_password':password,'recordings':str(Path.home()/'lekiwi-recordings'),'camera':camera,'camera_rotation':args.camera_rotation}
    cameras=[{'role':'front','source':camera,'rotation':args.camera_rotation}]
    wrist=args.wrist_camera or next((c['source'] for c in old.get('cameras',[]) if c['role']=='wrist'),None)
    if wrist:
        if not (wrist.isdigit() or wrist.startswith('/dev/')) or any(c in wrist for c in '\n\r'):raise ValueError('집게 카메라 경로가 잘못됐습니다')
        cameras.append({'role':'wrist','source':wrist,'rotation':args.wrist_rotation})
    config.update(has_arm=args.has_arm or old.get('has_arm',False),cameras=cameras)
    config_temp=config_path.with_suffix('.json.tmp');config_temp.write_text(json.dumps(config,ensure_ascii=False,indent=2));config_temp.chmod(0o600);config_temp.replace(config_path)
    card=config_dir/'connection-card';write_card(card,name,ssid,password,pin,summary['url'])
    unit_dir=Path.home()/'.config/systemd/user';unit_dir.mkdir(parents=True,exist_ok=True)
    def unit_escape(value): return str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')
    app=ROOT/'app'
    phone=f'[Unit]\nDescription=LeKiwi phone control and recording\nAfter=network.target\nWants=lekiwi-camera.service\n\n[Service]\nWorkingDirectory={unit_escape(app)}\nExecStart="{unit_escape(ROOT/"start.sh")}" "{unit_escape(config_path)}"\nRestart=on-failure\nRestartSec=3\nTimeoutStopSec=12\nKillMode=control-group\n\n[Install]\nWantedBy=default.target\n'
    camera_specs=' '.join(chr(34)+unit_escape(c['source'])+':'+c['role']+':'+str(c['rotation'])+chr(34) for c in cameras)
    cam=f'[Unit]\nDescription=LeKiwi timestamped camera\nAfter=network.target\n\n[Service]\nExecStart=/usr/bin/python3 "{unit_escape(app/"camera.py")}" --cams {camera_specs} --port 8080\nRestart=on-failure\nRestartSec=3\n\n[Install]\nWantedBy=default.target\n'
    for filename,content in [('lekiwi-phone.service',phone),('lekiwi-camera.service',cam)]:
        existing=unit_dir/filename
        if existing.exists():shutil.copy2(existing,existing.with_suffix('.service.previous'))
        existing.write_text(content)
    previous_controllers={}
    for service in ('lekiwi-host.service','lekiwi-nav.service'):
        previous_controllers[service]=subprocess.run(['systemctl','--user','is-enabled',service],capture_output=True,text=True).stdout.strip()
    if not (config_dir/'previous-controllers.json').exists():
        (config_dir/'previous-controllers.json').write_text(json.dumps(previous_controllers,indent=2))
    subprocess.run(['systemctl','--user','disable','--now','lekiwi-host.service','lekiwi-nav.service'],capture_output=True,check=False)
    subprocess.run(['systemctl','--user','stop','lekiwi-phone.service','lekiwi-camera.service'],check=False)
    connection=configure_ap(name,ssid,password,args.skip_network,args.ap_profile,args.activate_ap)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','lekiwi-phone.service','lekiwi-camera.service'],check=True)
    subprocess.run(['systemctl','--user','start','lekiwi-camera.service','lekiwi-phone.service'],check=True)
    print(json.dumps(summary,ensure_ascii=False,indent=2));print('연결 카드:',card/'index.html')
    print('모터는 켜지지 않았습니다. 최초 설치 후 재부팅하고 낮은 설정에서 방향·정지를 확인하세요.')
    if args.activate_ap:
        print('AP 전환으로 현재 무선 SSH 연결이 끊길 수 있습니다.',flush=True)
        subprocess.run(['sudo','nmcli','--wait','20','con','up',connection],check=True)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as error: raise SystemExit(str(error))
