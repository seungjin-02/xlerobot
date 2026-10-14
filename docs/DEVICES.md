# 기기별 구성과 교체

첫 기기: LeKiwi 베이스, Wi-Fi 이름 lekiwi01, 설치 당시 유선 10.42.0.24. 두 번째: 동일 모델·바퀴 구성이라고 사용자 확인, 팔과 USB 카메라 두 개, 기기 이름 LeKiwi-b82479, 설치 당시 유선 10.42.0.141. 유선 주소는 DHCP로 바뀔 수 있습니다.

실제 설정은 로봇의 `~/.config/lekiwi-phone/config.json`, `robot-profile.yaml`에 있습니다. 전자는 Wi-Fi 암호·PIN을 포함하므로 저장소에 복사하지 않습니다. 현재 두 번째 기기는 speed_tick_limit=3000, 바퀴 순서 [7,8,9], 방향 [1,1,1], radius .05, base_radius .125를 사용했습니다. 동형 모델이라도 설치 전 바퀴 번호와 방향은 확인합니다. 예시의 1500 출력 상한을 3000으로 바꾸려면 확인된 프로필을 사용합니다.

`has_arm`은 설치 설정이며 카메라 수로 추측하지 않습니다. `cameras`에는 front, 필요하면 wrist와 source/rotation이 저장됩니다. front는 카메라 서버의 index 0이며 기록의 `/snapshot` 소스입니다. wrist는 index 1로 화면에서만 선택합니다. 실제 프레임 수신 상태로 연결 여부를 표시합니다.

```bash
bash install.sh --profile /path/to/verified.yaml   --camera /dev/v4l/by-path/ACTUAL-FRONT-video-index0   --has-arm --wrist-camera /dev/v4l/by-path/ACTUAL-WRIST-video-index0
```

팔 없는 기기는 `--has-arm`과 `--wrist-camera`를 생략합니다. 이전 설정의 팔/집게 카메라를 없애는 자동 옵션은 아직 없습니다. 재구성할 때 서비스 중지 후 config.json의 has_arm=false, cameras에서 wrist 제거, 카메라 서비스를 단일 front로 바꾸거나 이전 설정을 비공개 백업하고 새 설정으로 재설치합니다.

두 번째 기기의 USB 포트 경로: 본체는 `platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.2:1.0-video-index0`, 집게는 `...usb-0:1.1:1.0-video-index0`. 사용자 관찰상 /dev/video0가 집게였고 /dev/video2를 본체로 지정했습니다. 카메라가 같은 시리얼 번호를 보고해 by-id가 충돌하므로 by-path를 사용했습니다. USB 포트를 바꾸면 역할을 다시 확인해야 합니다.

프레임에는 실제 노출 시각 대신 cap.read 직후 monotonic 시각을 기록합니다. 본체/집게 역할은 이미지 내용만으로 자동 추론하지 않습니다. 실제 화면을 보고 역할을 확인합니다.
