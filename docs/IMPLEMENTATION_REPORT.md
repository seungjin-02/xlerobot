# LeKiwi Control Center Phase 1 개발 결과

**추가 보완:** 2026-10-15 제공된 개발 지시서 전체에 따른 구현·충돌·미완료 상태는 [REQUIREMENTS.md](REQUIREMENTS.md)에 재구성했습니다. 원본 Public 전환과 공개 포털은 [PUBLICATION.md](PUBLICATION.md)를 확인하세요. 아래 본문은 PR #1 개발 시점의 결과입니다.

## 1. 기준과 구조

원격 main `a67415b3a60b5b3127fdd8b2d1bb58726dbdf67c`을 확인하고 `feature/lekiwi-control-center`에서 개발했습니다. 기존 PIN/쿠키·단일 조종자·lease/seq·속도/가속 제한·ROS `/cmd_vel`·카메라8080·EpisodeRecorder·LeRobot 변환 구조를 분석한 뒤 재사용했습니다. [분석과 최종 아키텍처](CONTROL_CENTER.md)에 계약과 변경 이유를 정리했습니다.

구성은 **정적 설치 포털 → PC Python/OpenSSH 도우미 → Pi의 Git 태그 설치 → 로컬 Control Center**입니다. 앱의 런타임 프레임워크는 바꾸지 않았습니다.

## 2. 구현 내용

| 요청 | 결과 |
| --- | --- |
| 조종·기록·시스템 화면 | 모바일 우선 세 화면, 공통 상태/정지, PC 2열 조종 배치 |
| 화면 전환 안전성 | 내부 이동은 idle 확인 후 제어권·기록 유지, 실패 시 종료 요청과 현재 화면 유지. blur/hidden/pagehide 정지 요청, 지연 arm 응답 무효화 |
| 기록 | 기존 EpisodeRecorder/파일 형식 유지. 작업·결과·시간·샘플·에피소드/다운로드·저장 공간 표시 |
| 시스템 관리 | 인증된 읽기 전용 `/api/system`: Git 태그/커밋/변경, OS/ROS, 서비스, 제어 프로세스, 피드백 최신 여부, 공간/경로/오류. 확인 불가는 명시 |
| 공개 설치 포털 | `site/`에 준비물·네트워크·Git 설치·폰 연결·FAQ·릴리스/업데이트 안내. API 없음. 수동 Pages workflow 추가, 배포는 미실행 |
| PC 도우미 | 주소/포트, SSH 신뢰/인증, OS/ARM64, 게이트웨이/DNS/Git·의존성 bootstrap 접근, 기존 설치, 프로필, 태그/SHA 검사. 명시적 `--install`에서만 설치 |
| Git 최초 설치 | Pi에서 clone→태그 커밋 재대조→기존 install.sh. 최신 main 자동 선택 없음. 잘못된/미등록 태그·기존 경로는 거부 |
| 인터넷 | 공유기 Ethernet·PC 인터넷 공유·Pi Wi-Fi 안내. Pi 자체 인터넷/Git 인증 필요, 자동 PC 공유/즉시 AP 전환 없음 |
| 완료 QR | 서비스/HTTP/본체JPEG 검증 뒤 PC 0600 완료 HTML. 웹앱 URL QR·수동 주소, AP명/버전 표시. PIN/AP암호/토큰 제외 |
| 버전·업데이트 | 현재 Git exact tag/HEAD 표시. [수동 업데이트](UPDATE.md)에 출처/태그/SHA 검증·의존 변경 검토·백업·재설치·검증·복구 제공 |
| 설정 보존 | 재설치에서 기존 PIN/AP암호·카메라 소스/회전·팔 구성·사용자 지정 기록 경로·motor ticks 상한 보존. PIN 파일 입력 추가 |
| 자동 업데이트 | Phase 2 설계만 작성. 웹 셸/업데이트 실행 API 없음 |

## 3. 변경 파일

- 앱: `app/index.html`, `app/app.js`, `app/style.css`, `app/server.py`, `app/recorder.py`, 새 `app/system_info.py`.
- 설치/검사: `setup_robot.py`, 새 `tools/install_assistant.py`, `tools/robot_install.py`, `tools/verify_robot.py`.
- 포털/CI: 새 `site/index.html`, `site/style.css`, `.github/workflows/pages.yml`; `.github/workflows/check.yml`에 Chromium 회귀 작업 추가.
- 테스트: 새 `tests/test_http.py`, `tests/test_install_assistant.py`, `tests/test_setup_preservation.py`, `tests/test_system_info.py`, `tests/browser_smoke.cjs`; `requirements-test.txt`에 기존 Pi QR 라이브러리인 qrcode8.2를 테스트용 추가.
- 문서: `README.md`, `docs/ARCHITECTURE.md`, `docs/COMPUTERS.md`, `docs/HANDOFF.md`, `docs/INSTALL.md`, `docs/TROUBLESHOOTING.md`, `docs/VERIFICATION.md`; 새 `docs/CONTROL_CENTER.md`, `docs/GIT_INSTALL.md`, `docs/UPDATE.md`, 본 보고서.
- 합성 증거: `evidence/control-center/`의 검증 결과와 선택한 화면 이미지. 전체 이미지/브라우저 결과는 무시 경로 `private/control-center-evidence/`에서 재생성합니다.

`app/core.py`, `app/ros_backend.py`, `drivers/`, `export_lerobot.py`, 기록 파일 스키마는 변경하지 않았습니다. 기존 API 필드를 제거하지 않고 새 진단·공간·시간 필드를 추가했습니다. 기존 dist ZIP은 과거 아티팩트로 유지하고 새로 만들지 않았습니다.

## 4. 검증과 증거

Python **87개** (기존47 + 신규40), Chromium **10개 시나리오** 통과. JavaScript/셸 문법·Python 컴파일·pip check·diff 검사도 통과했습니다. [검증 안내](VERIFICATION.md)에 재현 명령과 실제/모의 검증 구분을 정리했습니다. 새 HTTP 기록에서 episode-v1·state6/action3·요청/발행 분리·변환 입력 구간·JPEG를 검사했습니다. 실제 LeRobotDataset 생성/readback은 이번 환경에서 미실행입니다.

선택한 합성 화면:

- [모바일 조종](../evidence/control-center/drive-mobile.png)
- [PC 시스템 관리](../evidence/control-center/system-desktop.png)
- [설치 포털](../evidence/control-center/portal-desktop.png)

SSH 실패/네트워크/TLS/없는 Git·릴리스 태그/프로필 오류/설치 실패/서비스 실패는 모의 시험입니다. 태그 clone·SHA 대조·의존성 차이·Git 버전 전환과 복귀는 실제 임시 로컬 Git 저장소에서 검사했습니다. Pi/ROS/systemd 모의 성공을 실제 하드웨어 설치 성공으로 보고하지 않습니다.

## 5. 제약과 후속 조치

원본 저장소는 현재 Private이고 검증된 운영 릴리스 태그는 없습니다. 저장소 공개·별도 공개 복제·원격 설정 변경·릴리스 태그 게시·Pages 배포는 실행하지 않았습니다. 공개 전 전체 이력/민감 정보와 팀의 코드 공개 권한을 감사하고 앱/문서의 공개 라이선스를 결정해야 합니다. 현재 LICENSE-NOTICE는 앱/문서의 추가 공개 라이선스를 부여하지 않습니다. 원본 이력 노출을 줄이는 별도 공개 배포 Git 저장소를 권장하며, 승인 후 출처 상수·포털 링크·릴리스 동기화 절차를 함께 정해야 합니다.

깨끗한 Pi의 전체 Git 설치, 실제 SSH/sudo·apt/colcon, 서비스·재부팅/AP/QR·카메라 역할·1배 방향/정지·통신 단절/복구·실물 기록/변환, 실제 업데이트/복구는 현장 검증이 필요합니다. Windows/macOS PC·아이폰/안드로이드 OS별 백그라운드 동작과 GitHub Actions 실행·Pages 배포도 미검증입니다. Linux 도우미 검증은 클라우드 CLI/모의 SSH 수준입니다.

기존 10초 연결 단절 유예를 유지했습니다. 웹 서버가 마지막 출력을 계속 발행하면 300ms 드라이버 timeout만으로 10초 유예가 사라지지 않습니다. stop 요청/피드백과 물리적 정지를 구분해야 합니다. 기존 8080 카메라 서버도 신뢰하는 AP에서만 사용하며 이번 단계에 별도 인증을 추가하지 않았습니다.

Phase 2는 관리자 권한 분리·업데이트 잠금·고정 권한 별도 실행 서비스·신뢰된 서명/출처·새 환경 사전 빌드·설정/데이터/의존성 백업·원자적 전환·검증 실패 복구·전원 단절 실물 시험을 설계했습니다. 실제 자동 업데이트 실행 기능은 구현하지 않았습니다.

클라우드의 재사용 `start_skill`도 새 의존성/테스트/시스템 API 검증과 브라우저 검사 안내에 맞춰 초안 저장했습니다. 기존 install_script는 변경한 requirements-test.txt를 읽습니다. 이 초안 저장은 환경 게시를 실행하지 않으며 새 작업 복원을 검증한 것은 아닙니다.
