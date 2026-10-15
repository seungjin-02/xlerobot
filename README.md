# LeKiwi Control Center

**LeKiwi 모바일 베이스**의 로컬 조종·주행 기록·읽기 전용 시스템 관리 도구입니다. 저장소 이름은 xlerobot입니다. Python/ROS 2와 순수 HTML/CSS/JavaScript를 유지하며 팔 제어·자동 주행·모델 학습·웹 자동 업데이트는 포함하지 않습니다.

Phase 1에서 세 화면 UI, Git 태그/커밋 표시, SSH/Git 최초 설치 도우미, 정적 설치 포털과 수동 업데이트 절차를 추가했습니다. [분석·구조·공개 배포 검토](docs/CONTROL_CENTER.md), [검증 범위](docs/VERIFICATION.md)를 확인하세요. 현재 원본은 Private이며 검증된 릴리스 태그·공개 사이트는 아직 없습니다. 공개 상태·원격 설정·릴리스는 이번 개발에서 변경하지 않았습니다.

폰 브라우저 ↔ 르키위 Wi-Fi AP ↔ 라즈베리파이 웹 서버 ↔ ROS 2 바퀴 드라이버로 동작합니다. 설치 후 노트북·랜선·인터넷 없이 조종합니다. 안드로이드에서 실제 작동 확인, 아이폰 실기기 검증은 미완료입니다.

## 여기부터 시작

1. 최초 설치: [Git 설치·PC 도우미](docs/GIT_INSTALL.md) → [설치기 상세](docs/INSTALL.md) → [기기별 설정](docs/DEVICES.md). 인터넷은 Pi에도 필요합니다.
2. 이미 준비된 로봇: Wi-Fi 연결 → `http://192.168.4.1:8090` → 설치 때 정한 코드 → 조종 시작.
3. 기록·변환: [데이터 안내](docs/DATA.md). 기록 버튼을 누르기 전에는 수집하지 않습니다.
4. 작업 이어가기: [인수인계](docs/HANDOFF.md)와 [전체 활동 기록](docs/HISTORY.md).
5. 문제 발생: [문제 해결·복구](docs/TROUBLESHOOTING.md).
6. 검증·버전: [검증 범위](docs/VERIFICATION.md), [구조](docs/ARCHITECTURE.md), `evidence/`.
7. 기존 설치 업데이트: [태그 검증·백업·설치 재실행·복구](docs/UPDATE.md).
8. 공개 포털 소스: `site/`와 수동 GitHub Pages workflow. 승인·배포 전용 설정이 필요하며 아직 게시하지 않았습니다.

## 빠른 설치 — 로봇에서 실행

지원: Raspberry Pi Ubuntu 24.04 + ROS 2 Jazzy + NetworkManager + STS3215 바퀴 ID 7·8·9. 다른 OS나 모터는 추가 개발 대상입니다.

인증된 Git으로 clone한 뒤 관리자가 검증한 **실제 릴리스 태그와 전체 커밋**을 대조해 선택합니다. 상세 명령은 [Git 설치 안내](docs/GIT_INSTALL.md)를 따르세요. 아직 태그가 없으므로 임의의 최신 main을 운영 릴리스로 사용하지 마세요. 아래는 검증된 버전으로 전환한 뒤의 설치기 호출입니다. 프로필은 해당 기기의 순서·방향·치수를 확인한 파일이어야 합니다.

```bash
cd ~/xlerobot
bash install.sh --profile /path/to/verified-robot-profile.yaml
```

새 AP 이름은 무선 MAC에서 생성하고, 암호·QR은 로봇에서 생성됩니다. 기존 AP를 재사용할 수도 있습니다. 최초 설치 후 재부팅하고 1배에서 방향·정지를 확인합니다. 예시 PIN `1119`는 실제 배포 시 `--pin`으로 변경할 수 있습니다. 인증 정보나 실제 QR 카드는 저장소에 넣지 않습니다.

## 소스·패키지·데이터

`app/`: 웹 앱·ROS 연동·카메라·기록, `drivers/`: 포함한 ROS 드라이버와 원본 라이선스, `profiles/`: 설정 예시, `tests/`: 설치·기록·변환 검사, `export_lerobot.py`: 학습 형식 변환.

`dist/lekiwi-setup-and-recording.zip`은 이전 인수인계 시점의 보관 아티팩트이며 이번 변경을 포함하지 않습니다. 새 설치·업데이트 배포 경로는 Git입니다. `data/synthetic-example/`은 합성 검증 데이터이며 실제 주행 시범이 아닙니다. 실물 데이터는 로봇/별도 백업에 남기고 [데이터 안내](docs/DATA.md)에 따라 옮깁니다.

## 개발 확인

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m unittest discover -s app -p test_control.py -v
python -m unittest discover -s tests -v
```

모터 없이 UI 확인: `python app/server.py --demo --host 127.0.0.1 --port 8092 --recordings ./private/demo-recordings` 실행 후 예시 코드 `12345678`로 인증합니다. 합성 환경은 실물 동작을 검증하지 않습니다. 브라우저 회귀 테스트·스크린샷 재생성은 [검증 안내](docs/VERIFICATION.md)를 참고하세요.
