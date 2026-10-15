# Git 기반 최초 설치와 PC 도우미

이 절차는 최초 설치용입니다. 기존 설치에는 [수동 업데이트](UPDATE.md)를 사용하세요. 현재 원본은 Public이며 인증 없이 Git으로 읽을 수 있습니다. 검증된 릴리스 태그는 없으므로, 아래 자리표시자는 관리자가 승인·검증한 실제 태그와 전체 커밋으로 대체해야 합니다. 이 변경의 깨끗한 Pi 전체 설치는 아직 미검증입니다.

## 연결과 사전 준비

대상: Raspberry Pi Ubuntu 24.04 ARM64, 일반 사용자·sudo, NetworkManager, ROS 2 Jazzy, 기기에서 확인한 STS3215 ID7·8·9 바퀴 프로필. ROS와 나머지 의존성은 기존 설치기가 준비합니다. PC 도우미 코드는 Linux/Python3.12에서 검사했습니다. Windows/macOS의 OpenSSH/TTY와 실물 설치는 미검증이며 보장하지 않습니다. WSL 사용도 별도 확인이 필요합니다.

1. 공유기 Ethernet(권장), 노트북 Wi-Fi→Ethernet 인터넷 공유, 또는 Pi의 기존 Wi-Fi로 인터넷을 제공합니다. 랜선 연결은 인터넷 공유 활성화를 뜻하지 않습니다. Ubuntu NetworkManager는 유선 IPv4 “다른 컴퓨터와 공유”, Windows는 어댑터 인터넷 연결 공유, macOS는 시스템 설정의 인터넷 공유를 확인하세요. 실제 메뉴·게이트웨이·DHCP 주소를 확인하며 10.42.0.x를 고정 가정하지 않습니다.
2. Pi의 실제 주소와 SSH 호스트 키를 확인합니다. `ssh USER@PI_ADDRESS`로 접속하며 root는 사용하지 않습니다. 자동으로 호스트 키 검사를 끄거나 known_hosts를 지우지 않습니다.
3. Pi에서 `sudo apt-get update && sudo apt-get install git python3-yaml`을 실행합니다. Ubuntu 기본 Python3.12, iproute2, sudo, systemd, Bash가 필요합니다. PC에서 `.venv-assistant`를 만들고 `python -m pip install PyYAML==6.0.3`을 실행합니다. PyYAML은 기존 저장소의 프로필 검증 의존성입니다. QR은 Pi의 기존 python3-qrcode 설치를 재사용하므로 PC의 추가 QR 라이브러리는 필요 없습니다.
4. 현재 공개 원본은 PC와 Pi 모두 인증 없이 읽습니다. 조직 정책으로 Private 배포 출처를 사용하는 경우에는 **Pi 자체**의 Git 읽기 인증도 준비합니다. OS의 Git 자격 증명 관리자를 사용하고 토큰을 URL/명령 인자/설정 문서/로그에 넣지 않습니다. PC의 키나 클라우드 Git 프록시 인증을 Pi로 복사하지 않습니다. PC와 Pi에서 각각 `git ls-remote https://github.com/seungjin-02/xlerobot.git HEAD`를 확인합니다.
5. Pi에서 `ip -br address`, `ip route show default`, `getent hosts github.com`을 확인합니다. GitHub HTTPS/Git, Ubuntu ports와 ROS 설치용 GitHub API·release assets·packages.ros.org 접근이 필요합니다. apt의 실제 저장소 설정에 따른 목적지도 허용해야 합니다. 도우미 사전 검사는 게이트웨이·DNS·Git 태그 읽기·Ubuntu/ROS bootstrap HTTPS를 검사하며 모든 apt 패키지의 가용성을 보증하지 않습니다.

AP나 PC 공유 설정은 도우미가 자동 변경하지 않습니다. 특히 Pi의 같은 Wi-Fi 장치를 클라이언트에서 AP로 바꾸면 SSH가 끊길 수 있어 Ethernet으로 진행하는 것이 좋습니다. 설치기는 기존 NetworkManager AP 구성을 재사용하거나 새 구성을 등록하지만 도우미는 `--activate-ap`를 전달하지 않습니다. 현재 연결이 절대 유지된다고 보장하지 않습니다.

## PC에서 실행

PC에서도 인증된 Git clone으로 이 저장소를 준비합니다. 릴리스로 제공된 도우미 자체의 출처·커밋도 확인하세요. 도우미는 PC의 `robot_install.py`를 SSH로 실행하므로 선택한 대상 태그뿐 아니라 PC 도우미 코드도 신뢰해야 합니다.

```bash
git clone https://github.com/seungjin-02/xlerobot.git
cd xlerobot
python3 -m venv .venv-assistant
.venv-assistant/bin/python -m pip install PyYAML==6.0.3
.venv-assistant/bin/python tools/install_assistant.py \
  --host USER@PI_ADDRESS --tag VERIFIED_TAG --commit VERIFIED_40_CHARACTER_COMMIT
```

관리자가 별도 경로로 제공한 태그의 커밋을 확인하세요. 태그 이름만으로 “검증된 릴리스”가 되지 않습니다. 도우미는 원격 태그의 peeled commit과 예상 SHA를 대조하고 clone 후 다시 확인합니다. 커밋 대조는 전송 후 변경 탐지를 돕지만 관리자의 검증·서명 신뢰를 대신하지 않습니다. 현재 도우미는 vX.Y.Z 및 사전릴리스 형식을 지원하며 다른 형식은 명시적으로 거부합니다. `--install` 없이는 clone·설정 쓰기 없이 사전 검사만 합니다.

```bash
.venv-assistant/bin/python tools/install_assistant.py \
  --host USER@PI_ADDRESS --tag VERIFIED_TAG --commit VERIFIED_40_CHARACTER_COMMIT \
  --install --profile /path/to/verified-profile.yaml \
  --serial-port /dev/serial/by-id/VERIFIED_MOTOR_USB \
  --camera /dev/v4l/by-path/VERIFIED_FRONT_CAMERA \
  --confirm-wheel-map --output lekiwi-installed.html
```

`--directory`는 Pi 홈 아래 새 상대 경로이며 기본 xlerobot입니다. 기존 경로·설정이 있으면 거부합니다. 도우미는 파일을 삭제/초기화하거나 기존 설치에 덮어쓰지 않습니다. Pi의 sudo 인증과 새 웹앱 PIN은 SSH 터미널에서 입력합니다. PIN은 0600 임시 파일로 설치기에 전달하고 제거하며 명령 인자나 QR·완료 파일에 넣지 않습니다. 도우미는 터미널 출력을 별도 로그로 저장하지 않습니다. 사용자의 터미널 기록/화면 공유는 별도로 관리하세요.

프로필은 PC에서 기존 validate_profile로 검사한 뒤 Pi에서도 검사합니다. `--confirm-wheel-map`은 물리적 검증을 대신하지 않습니다. 본체/집게 경로는 현장에서 확인하고 집게가 있으면 `--wrist-camera`를 명시합니다. 도우미는 바퀴나 팔을 활성화하지 않습니다.

도우미의 원격 작업은 Git clone → exact tag/commit → 기존 install.sh → 서비스 active → 비데모 /health → 본체 snapshot JPEG → `~/.config/lekiwi-phone/installed-version.json` 기록 순서입니다. 이후 별도 읽기 전용 SSH 요청으로 재검증하고 PC에 0600 완료 HTML을 생성합니다. 실패한 명령은 완료로 표시하지 않으며 부분 체크아웃·설정은 조사할 수 있게 보존합니다. 원격 설치기/apt의 비밀값이 섞인 상세 출력을 별도 수집하지 않습니다. 단계와 실패 종류를 표시하고 Pi의 systemctl/journalctl로 상세 진단합니다.

## 설치 완료

완료 HTML은 장치·AP 이름·Git 태그/커밋·서비스 응답과 **웹앱 URL QR**을 표시합니다. AP 암호·PIN·세션 토큰·Wi-Fi QR은 PC로 가져오지 않습니다. QR 생성 실패 시 수동 주소를 제공합니다. 기존 파일을 덮어쓰지 않으므로 새 `--output` 경로를 선택하세요.

최초 재부팅 후 폰의 Wi-Fi 설정에서 AP에 연결하고 URL QR을 스캔합니다. 주소는 `http://192.168.4.1:8090`이며 PIN 인증이 별도로 필요합니다. QR 스캔이 Wi-Fi 연결을 보장하지 않습니다. 선택적 Wi-Fi QR은 로봇의 비공개 연결 카드에서 확인하며 암호/QR은 기본 접힌 상태입니다. 그 카드는 암호를 포함하므로 외부에 게시하지 않습니다.

새 그룹 권한·AP는 재부팅 후 확인합니다. 서비스 검증에 실패한 경우 설치 성공으로 처리하지 않으며, 그룹 권한/카메라/프로필/ROS 빌드/재부팅을 조사한 뒤 수동 절차로 복구하세요. 최초 1배 방향·정지·카메라 역할과 통신 장애 시험은 현장 작업입니다.

## 직접 Git 설치

도우미를 사용할 수 없는 PC에서는 Pi에 SSH 접속해 동일한 출처·태그·예상 커밋을 확인하고 Git으로 설치합니다. 검증 절차를 생략하거나 최신 main을 운영 설치하지 마세요.

```bash
git clone https://github.com/seungjin-02/xlerobot.git
cd xlerobot
git fetch origin --tags
# 다음 두 값을 관리자가 제공한 실제 값으로 설정
release_tag=VERIFIED_TAG
expected_commit=VERIFIED_40_CHARACTER_COMMIT
test "$(git rev-parse --verify "refs/tags/$release_tag^{commit}")" = "$expected_commit" || exit 1
git checkout --detach "$expected_commit"
bash install.sh --profile /path/to/verified-profile.yaml
```

설치 버전은 `git describe --tags --exact-match HEAD`, `git rev-parse HEAD`와 로컬 시스템 화면에서 확인합니다. 직접 설치는 installed-version.json을 자동으로 만들지 않지만 Git 정보는 직접 읽어 표시합니다. `python3 tools/verify_robot.py --idle`로 서비스·카메라·소프트웨어 대기를 확인하고 최초 재부팅/현장 검증을 완료하세요.
