# xlerobot — LeKiwi 폰 조종과 주행 데이터 기록

2026-10-14 기준 재현·인수인계 프로젝트입니다. 저장소 이름은 xlerobot이지만 현재 구현은 **LeKiwi 모바일 베이스**용입니다. 팔 제어·팔 학습·자동 주행은 구현하지 않았습니다.

폰 브라우저 ↔ 르키위 Wi-Fi AP ↔ 라즈베리파이 웹 서버 ↔ ROS 2 바퀴 드라이버로 동작합니다. 설치 후 노트북·랜선·인터넷 없이 조종합니다. 안드로이드에서 실제 작동 확인, 아이폰 실기기 검증은 미완료입니다.

## 여기부터 시작

1. 처음 재현: [설치 안내](docs/INSTALL.md) → [Ubuntu/Windows PC 준비](docs/COMPUTERS.md) → [기기별 설정](docs/DEVICES.md).
2. 이미 준비된 로봇: Wi-Fi 연결 → `http://192.168.4.1:8090` → 설치 때 정한 코드 → 조종 시작.
3. 기록·변환: [데이터 안내](docs/DATA.md). 기록 버튼을 누르기 전에는 수집하지 않습니다.
4. 작업 이어가기: [인수인계](docs/HANDOFF.md)와 [전체 활동 기록](docs/HISTORY.md).
5. 문제 발생: [문제 해결·복구](docs/TROUBLESHOOTING.md).
6. 검증·버전: [검증 범위](docs/VERIFICATION.md), [구조](docs/ARCHITECTURE.md), `evidence/`.

## 빠른 설치 — 로봇에서 실행

지원: Raspberry Pi Ubuntu 24.04 + ROS 2 Jazzy + NetworkManager + STS3215 바퀴 ID 7·8·9. 다른 OS나 모터는 추가 개발 대상입니다.

GitHub에서 Download ZIP으로 받은 소스를 로봇 사용자 홈의 `~/xlerobot`에 풀거나, 인증된 Git으로 clone합니다. 아래 프로필은 반드시 해당 기기의 순서·방향·치수를 확인한 파일이어야 합니다.

```bash
cd ~/xlerobot
bash install.sh --profile /path/to/verified-robot-profile.yaml
```

새 AP 이름은 무선 MAC에서 생성하고, 암호·QR은 로봇에서 생성됩니다. 기존 AP를 재사용할 수도 있습니다. 최초 설치 후 재부팅하고 1배에서 방향·정지를 확인합니다. 예시 PIN `1119`는 실제 배포 시 `--pin`으로 변경할 수 있습니다. 인증 정보나 실제 QR 카드는 저장소에 넣지 않습니다.

## 소스·패키지·데이터

`app/`: 웹 앱·ROS 연동·카메라·기록, `drivers/`: 포함한 ROS 드라이버와 원본 라이선스, `profiles/`: 설정 예시, `tests/`: 설치·기록·변환 검사, `export_lerobot.py`: 학습 형식 변환.

`dist/lekiwi-setup-and-recording.zip`은 독립 설치 패키지입니다. `data/synthetic-example/`은 합성 검증 데이터이며 실제 주행 시범이 아닙니다. 실물 데이터는 로봇/별도 백업에 남기고 [데이터 안내](docs/DATA.md)에 따라 옮깁니다. 현재 접근 가능한 두 번째 기기에는 기록 폴더가 아직 없었습니다. 첫 번째 기기의 과거 기록은 이번 GitHub 업로드에 포함되지 않았습니다.

## 개발 확인

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m unittest discover -s app -p test_control.py -v
python -m unittest discover -s tests -v
```

모터 없이 UI 확인: `python app/server.py --demo --host 127.0.0.1 --port 8092 --recordings ./private/demo-recordings` 실행 후 `http://127.0.0.1:8092`에 예시 코드 `12345678`로 접속합니다. 합성 환경은 실물 동작을 검증하지 않습니다.
