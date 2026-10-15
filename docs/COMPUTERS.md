# Ubuntu / Windows에서 시작

조종 서버·카메라·ROS는 로봇에 설치합니다. PC의 OS와 무관하게 폰에서 로봇 AP로 조종합니다. 노트북은 설치·관리·데이터 복사와 학습용입니다.

## Windows

PowerShell의 `ssh`, `scp`를 확인합니다. 없는 경우 Windows 선택적 기능의 OpenSSH Client를 설치합니다. 최신 설치 경로는 [Git 설치 안내](GIT_INSTALL.md)입니다. 비공개 저장소는 PC와 Pi에서 각각 Git 인증을 준비합니다. PC 도우미의 Windows/macOS 실행은 아직 미검증입니다.

```powershell
ssh <user>@<robot-ip>
scp -r .\xlerobot <user>@<robot-ip>:/home/<user>/
```

로봇에 SSH 접속한 뒤 Git clone·검증된 태그/커밋 선택을 수행하고 `cd ~/xlerobot; bash install.sh ...`를 실행합니다. Windows에서 로봇용 Bash 설치 스크립트를 직접 실행하지 않습니다.

랜선 직결은 DHCP 서버가 없으면 주소가 자동 배정되지 않을 수 있습니다. 이 노트북의 Ubuntu는 인터넷 공유로 10.42.0.1/24를 사용했지만 Windows에는 같은 주소가 보장되지 않습니다. Windows 인터넷 공유의 실제 어댑터 주소를 확인하거나 공유기에 PC와 로봇을 연결하여 DHCP 주소를 찾으세요. 준비된 로봇은 PC를 AP에 연결해 192.168.4.1로 SSH할 수도 있습니다. PC의 인터넷 연결은 끊길 수 있습니다.

데이터 변환·학습은 WSL2 Ubuntu를 사용할 수 있으나 이 프로젝트에서 Windows/WSL2 실기기 검증은 하지 않았습니다. GPU 학습은 별도 CUDA/드라이버 검증이 필요합니다. 폰 조종에는 PC GPU나 ROS가 필요하지 않습니다.

## Ubuntu

```bash
ssh <user>@<robot-ip>
scp -r ./xlerobot <user>@<robot-ip>:/home/<user>/
```

직결 설치 시 NetworkManager 유선 설정에서 IPv4를 '다른 컴퓨터와 공유'로 설정할 수 있습니다. `ip -br addr`, `ip neigh`, `nmcli device status`로 확인합니다. 케이블 연결과 로봇 전원이 켜져 있어야 합니다. 특정 IP를 다음 기기에 고정으로 가정하지 않습니다.

비공개 Git clone/push에는 본인의 GitHub 인증이 필요합니다. SSH 키나 토큰은 저장소 문서/파일에 붙여넣지 않습니다.
