# LeKiwi Control Center — 개발 지시서 기준 상태

2026-10-15 제공된 16절 개발 지시서를 작업 기준으로 삼습니다. 기존 Phase 1 구현을 재사용하고 새로 구현한 부분과 검증·게시·실물 적용을 구분합니다. Phase 2는 설계만 제공합니다.

## 1. 분석과 구현 계획

기준 main은 PR #1 병합 커밋 `8d5bfbb10b6df841a426b0dfbd3cb0803026eb49`입니다. README, server/core/frontend, recorder/ROS backend, install/setup, export, INSTALL/ARCHITECTURE/DATA/VERIFICATION/TROUBLESHOOTING/HANDOFF와 전체 tests를 대조했습니다.

Python ThreadingHTTPServer와 순수 HTML/CSS/JS, PIN 쿠키 세션, 단일 lease·증가 seq, 기존 ROS 2 경로와 EpisodeRecorder를 유지합니다. 포털 → PC Python/OpenSSH → Pi Git clone·검증 태그·install.sh → 로컬 세 화면 구조는 이미 구현되어 있습니다. 상세 계약과 Phase 2는 [CONTROL_CENTER.md](CONTROL_CENTER.md)에 있습니다.

이번 보완 계획은 사용자 지정 ROS workspace 재설치 보존, 필드 누락 상태 응답의 대기 오판 방지, Public 전환에 맞는 안내 갱신, 요구사항/검증 추적과 공개 포털 게시입니다. 모터 제어 정책·기록 스키마·런타임 프레임워크·의존성을 바꾸지 않습니다.

## 2. 요구사항별 추적

| 지시서 | 구현 및 근거 | 남은 범위 |
| --- | --- | --- |
| 1–3 프로젝트·분석·아키텍처 | 본 문서, CONTROL_CENTER.md, 기존 Python/ROS/정적 웹 재사용 | 팔 제어·학습·자율주행은 제외 |
| 3A 공개 설치 포털 | `site/index.html`, `site/style.css`, 수동 Pages workflow | 게시 결과와 실제 URL은 PUBLICATION.md에서 확인 |
| 3B·6 PC 도우미 | `tools/install_assistant.py`, `tools/robot_install.py`, 단계/오류·SSH·환경/프로필·기존 설치 검사 | 실제 깨끗한 Pi 전체 설치 및 Windows/macOS 미검증 |
| 3C·8 세 화면 | `app/index.html`, `app/app.js`, `app/style.css`, `app/system_info.py` | 폰 OS별 비활성화 실기기 시험 |
| 4 Git 최초 설치 | `docs/GIT_INSTALL.md`, clone→태그/SHA 대조→기존 install.sh | 검증된 운영 태그 미등록. 임의 버전을 만들지 않음 |
| 4 공개 출처 | 사용자가 원본 Public 전환, 인증 없는 Git 읽기 확인 | 기존 프로젝트 라이선스 고지 유지. Public이 새 사용·재배포 라이선스를 부여하지 않음 |
| 5 Pi 인터넷 | GIT_INSTALL.md, COMPUTERS.md, 포털 A/B/C 연결 안내와 게이트웨이/DNS/Git/Ubuntu·ROS 검사 | 각 OS 인터넷 공유와 모든 apt endpoint의 실물 검증 |
| 7 완료 화면·QR | PC의 0600 완료 HTML과 URL QR, Pi의 선택적 비공개 Wi-Fi QR, 실패 시 수동 주소 | AP 연결과 PIN 인증은 별도. QR에 PIN/토큰 없음 |
| 8.1 조종 | 기존 명령 검증·속도/가속 제한, 카메라·연결/권한/준비·정지 표시 | 주행·물리 정지는 실물 검증 필요 |
| 8.2 기록 | EpisodeRecorder, 작업/결과/시간/샘플/목록/ZIP/공간, episode-v1 유지 | 새 실물 주행 기록/다운로드/변환 미실시 |
| 8.3 시스템 | 인증된 읽기 전용 `/api/system`, Git·OS/ROS·서비스·앱 소유 제어 프로세스·모터 피드백·공간·오류 | 모터 미수신은 확인 불가. 실행 중 프로세스와 물리 상태를 동일시하지 않음 |
| 9 Git 버전 | feature→테스트→PR→main→현장 검증→운영 태그 정책 | 이번 main 적용은 검증된 운영 릴리스가 아님 |
| 10 Phase 1 업데이트 | UPDATE.md: 출처/버전/대기→백업→의존성 검토→전환/설치/검증→수동 복구 | 실제 롤백·OS 환경 전체 복원 시험 |
| 10·14 Phase 2 | CONTROL_CENTER.md의 권한 분리·서명·별도 실행기·잠금·원자적 전환·복구 설계 | 웹 자동 업데이트는 구현하지 않음 |
| 11 안전 | 기존 core.py·ROS 경로 유지, PIN/session/lease/seq/속도/정지·재연결 테스트 | 마지막 출력 최대 10초 유지. 물리적 안전 보장 주장 없음 |
| 12 호환성 | 기존 API와 기록 형식·데모·변환기·서비스·설치 재사용 | 초기화된 Pi와 새 OS에서의 전체 호환성 |
| 13 테스트 | 기존 전체 Python/Chromium + 새 workspace/대기 필드 검증 테스트 | 합성·모의·실물 결과를 구분 |
| 15 개발 규칙 | feature 브랜치, 기존 의존성 유지, 기기 설정/비밀/기록을 Git에서 제외 | 미검증 기능을 완료로 표현하지 않음 |
| 16 결과 보고 | 본 문서, IMPLEMENTATION_REPORT.md, VERIFICATION.md, PUBLICATION.md | 공개/실물 검증이 필요한 항목은 계속 표시 |

## 3. 충돌과 해결

**운영 태그와 main 현장 적용:** 지시서의 기본 운영 설치는 검증된 태그입니다. 사용자의 별도 main 실물 적용 요청은 현장 검증용으로 수행했으며 운영 릴리스 태그나 전체 검증 완료 기록을 생성하지 않았습니다. 최초 설치 도우미는 여전히 main 설치를 거부합니다.

**Private 제한과 Public 허용:** 최초 지시서는 명시적 승인 없는 공개 전환을 금지합니다. 이후 사용자가 Public 전환을 허용하고 직접 변경했습니다. 기존 원본을 공개 출처로 사용하며 다른 원격으로 임의 변경하지 않습니다. 과거 문서의 Private 표기는 당시 상태이고 현재 상태는 PUBLICATION.md가 기준입니다.

**공개 열람과 라이선스:** Public Git 읽기와 오픈소스 사용·재배포 허가는 별개입니다. 드라이버 Apache-2.0 고지와 프로젝트 LICENSE-NOTICE.md를 유지합니다. 새 MIT/Apache 라이선스를 임의로 부여하지 않습니다.

**설정 보존과 workspace:** 기존 install.sh는 setup_robot.py에 기본 workspace를 명시해 사용자 지정 설정을 덮을 수 있었습니다. 이제 `--workspace` → 선택한 `--config-dir`의 기존 workspace → 최초 설치 기본 경로 순으로 선택합니다. 불완전한 기존 설정은 기본값으로 리셋하지 않고 실패합니다. 명시적 `--workspace`는 이미 빌드한 workspace 재사용이며, 생략 시 선택한 실제 경로에 포함 드라이버를 빌드합니다.

**확인 불가와 대기:** 상태 필드가 빠진 응답은 업데이트 대기 확인을 통과하지 않습니다. `available=false`, `motor_ready=null`인 정상 형식의 소프트웨어 대기는 물리 정지 확인과 별개로 안내합니다.

## 4. 최종 검증 기준

Python 전체와 Chromium 시나리오, 문법·pip·Git diff 검사를 실행합니다. 카메라와 인증·서비스를 실제 장비에서 확인한 결과는 VERIFICATION.md의 현장 항목에 별도 기록합니다. 재부팅/AP 클라이언트·모터 활성화·방향/정지·통신 단절·실물 데이터 변환·깨끗한 OS 설치·백업 복원은 별도 현장 검증 대상입니다. 이 항목을 모두 충족하기 전 운영 릴리스를 검증 완료로 표시하지 않습니다.
