# 검증 범위

## Phase 2 검토 브랜치

신규 구현·시험별 실제/모의 구분과 실물 미검증 범위는 [PHASE2.md](PHASE2.md)에 기록합니다. Phase 2는 실물 장비 미적용이며 운영 릴리스 검증 완료 기록을 만들지 않습니다.

## 개발 지시서 전체 대조·보완 — 2026-10-15 Ubuntu 노트북

요구사항별 구현/충돌/미완료 범위는 [REQUIREMENTS.md](REQUIREMENTS.md), 현재 공개 출처·포털·운영 태그 기준은 [PUBLICATION.md](PUBLICATION.md)를 따릅니다.

- Python 3.12.3: 기존 제어 26개 + tests 69개 = **95개 통과**, 실패/건너뜀 0. 기존 87개를 모두 유지하고 workspace 보존·대기 상태 필드 누락/형식·활성 상태 거부 8개를 추가했습니다.
- Node 20.20.2, Playwright 1.62.1, 실제 Chromium 151: 기존 **10개 시나리오 통과**, JS 예외 0. 수정한 공개 포털의 PC/모바일 배치도 포함합니다.
- JS/셸 문법, Python 컴파일, pip check, git diff --check 통과. 테스트 venv에 외부 ROS PYTHONPATH가 유입되지 않도록 PYTHONPATH를 비운 격리 환경을 사용했습니다.
- 실제 임시 디렉터리에서 공백이 있는 사용자 지정 workspace 선택·설정 무변경, 명시적 경로 우선, 최초 설치 기본 경로, 손상/빈 설정 실패를 검사했습니다. 불완전한 상태 응답은 대기 통과하지 않습니다. 모터 피드백이 없는 정상 형식의 소프트웨어 대기는 물리 정지 검증과 구분합니다.
- GitHub 원본 Public 전환 후 인증 없는 Git fetch로 전체 4커밋 이력과 태그 부재를 확인했습니다. 110개 도달 가능 blob·기존 ZIP 내부 148개 파일에 대한 고신뢰 개인키/토큰/인증 URL 패턴 검사에서 일치 항목은 없었습니다. 자동 검사는 비밀 부재 보장이나 포괄적 라이선스 감사를 대신하지 않습니다.

### 앞선 main 현장 적용에서 확인한 범위

PR #1 병합 main `8d5bfbb10b6df841a426b0dfbd3cb0803026eb49`을 기존 Ubuntu 24.04.4 ARM64 설치에 수동 적용했습니다. 최초 설치 도우미는 사용하지 않았습니다. 설정/PIN/AP·유닛·ROS workspace·기존 소스를 비공개 백업했고 노트북 사본까지 SHA256을 대조했습니다. 기록 폴더는 적용 전부터 없었습니다.

colcon 1패키지 빌드 성공, 서비스 active/enabled·Git clean/HEAD·기존 PIN·세 화면 HTML/시스템 API·front/wrist 640×480 JPEG 스트림과 본체 snapshot sequence 증가를 확인했습니다. 설정 JSON 전체/프로필 의미·네트워크 시스템 파일을 보존했습니다. 모터 통신은 available=false로 표시됐으며 활성화/주행하지 않았습니다. 재부팅/AP 클라이언트·실물 기록/변환·복원·깨끗한 OS 전체 설치는 미실시입니다. 이 현장 결과를 새 보완 코드 전체의 실물 검증 또는 운영 릴리스 검증 완료로 간주하지 않습니다.

## Control Center Phase 1 — 2026-10-15 클라우드 검증

- Python 3.12.14, Debian 13 x86_64, Node.js 24.19.0. 기존 테스트 47개를 포함해 **87개 통과** (app 제어26 + tests61), 실패/건너뜀 0.
- PyYAML6.0.3, Pillow12.3.0, qrcode8.2 설치 및 pip check 통과. QR 테스트는 기존 Pi 의존성 qrcode를 개발 환경에도 설치해 실제 SVG 생성·비밀값 제외·0600 완료 파일을 확인합니다. 앱의 새 런타임 의존성은 없습니다.
- node --check app/app.js, node --check tests/browser_smoke.cjs, bash -n install.sh prepare-system.sh start.sh, git diff --check 통과.
- 실제 Chromium + Playwright1.62.1에서 **10개 시나리오 통과**, JavaScript 예외 0. 모바일390×844/PC1280×900, PIN·합성 JPEG·세 화면·읽기 전용 진단·기록 중 메뉴 이동·종료 정지·인증 ZIP 다운로드·blur/hidden·연결 복구·지연 arm·정지 전달 실패 경고·정적 포털 레이아웃을 검사했습니다. hidden은 실제 핸들러에 visibilitychange를 발생시킨 합성 시험이며 폰 OS의 프로세스 정지/강제 종료 보장은 아닙니다.
- HTTP 세션 만료/잘못된 PIN/외부 Origin/다른 소유자/오래된 seq/읽기 전용 API/모터 상태 미확인 표시를 확인했습니다. episode-v1과 state6/action3, requested/applied 구분, uniform_segments 및 이미지 경로 검증을 새 HTTP 기록에서 확인했습니다. 실제 LeRobotDataset export/readback은 이번 환경에서 실행하지 않았습니다.
- 설치 사전 검사의 OS·아키텍처·Git 미설치·게이트웨이·DNS·TLS 실패·기존 경로·태그 불일치와 SSH 실패·프로필 오류·설치 실패·서비스 실패·TTY 필수 조건을 모의 시험했습니다. 실제 로컬 임시 Git에서 annotated/lightweight 태그·clone·SHA 대조·의존성 차이·버전 전환/복귀를 검증했습니다. SSH/sudo/Pi 설치를 실제로 수행한 결과는 아닙니다.
- 기존 설치기 재실행을 격리된 홈/프로필과 모의 systemd로 실행해 PIN/AP 암호·카메라 소스/회전·팔 유무·사용자 지정 기록 경로·motor ticks 제한과 기록 파일 보존을 확인했습니다. 전체 apt/colcon/systemd/AP 실물 동작은 별도입니다.
- 플랫폼 기존 인증으로 Private 원격 main/태그 조회 성공. 검증된 운영 릴리스 태그는 아직 없으며 게시하지 않았습니다. Pages workflow와 CI 변경은 로컬 검사만 했고 GitHub Actions에서 실행하지 않았습니다.

재현:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s app -p test_control.py -v
.venv/bin/python -m unittest discover -s tests -v
node --check app/app.js
bash -n install.sh prepare-system.sh start.sh
# 개발/CI 전용 브라우저 도구. 앱 런타임에는 필요하지 않음.
npm install --prefix .local/browser playwright@1.62.1
node .local/browser/node_modules/playwright/cli.js install chromium
NODE_PATH="$PWD/.local/browser/node_modules" node tests/browser_smoke.cjs
```

시스템 Chromium이 없으면 Playwright가 설치한 Chromium을 사용합니다. Linux에서 필요한 OS 라이브러리가 없으면 CI처럼 Playwright의 공식 `install --with-deps chromium`을 사용하세요. npm/브라우저 다운로드가 필요하므로 기본 Python 개발 환경과 구분합니다. 테스트가 시작한 합성 서버만 종료합니다. 결과 JSON과 스크린샷은 무시 경로 `private/control-center-evidence/`에 생성되며 실제 로봇 증거가 아닙니다.

### 남은 실물·외부 검증

깨끗한 Ubuntu24.04 ARM64 Pi에서 Git 인증→실제 검증 릴리스 clone→sudo/의존성/colcon→설정·서비스→재부팅/AP/QR→PIN→본체/집게 카메라→1배 방향/정지→연결 손실/복구→주행 기록→LeRobot 변환을 검증해야 합니다. 기존 설치의 실제 업데이트·의존성 복구와 설정/데이터 백업 복원도 필요합니다. 아이폰/안드로이드의 백그라운드·강제 종료, Windows/macOS PC 도우미, Pages 공개 배포·권한·전체 Git 이력 감사도 미완료입니다.

## 이전 인수인계 시점의 증거 (이번 변경의 실물 검증 아님)

최신 소스 Python26 제어 +21 설치/기록/변환 테스트 통과. node --check app/app.js 통과. 포함한 ROS 소스의 과거 colcon 결과190 tests, failures/errors0. 이는 최신 카메라UI를190개로 검사했다는 의미가 아닙니다.

합성 시범77프레임: 실제 LeRobot0.6.0 데이터셋 변환/readback (image3x480x640,state6,action3). 인증 HTTP 시작/종료/ZIP 다운로드와 terminal stop 검증. UI 모바일 크기 기록 화면 확인은 합성 환경.

첫 로봇: 카메라 timestamp/JPEG, 인증UI, 자동시작 설정 확인. 두 번째: Ubuntu24.04/Jazzy, 소스 새 빌드, AP와자동시작, 두 카메라640x480 프레임수신, has_arm=true/front+wrist/armed=false 응답 확인. 사용자가 두 번째 실물 주행 정상이라고 확인했으나 자동 실물 주행/속도 측정을 실행하지 않았음.

미검증 항목은 HANDOFF.md에 정리했습니다. evidence JSON은 그 시점 결과이며 지속적인 건강 상태를 보장하지 않습니다. evidence screenshot은 합성/과거 화면이며 최신 카메라 선택 화면의 증거가 아닙니다.
