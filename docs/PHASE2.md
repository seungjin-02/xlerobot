# Phase 2 — 관리자 승인형 앱 업데이트 (검토용 구현)

Phase 2는 별도 관리자 서비스로 전환해야 활성화되는 opt-in 구현입니다. **현재 르키위에는 설치하지 않았습니다.** 실제 시스템 서비스 전환·재부팅·전원 단절·복원 시험 전 운영 검증 완료로 표시하지 않습니다.

## 구현 범위

- 로봇 웹 시스템 화면: 업데이트 진행/차단 상태를 읽습니다. 일반 PIN API에 셸·URL·파일 경로 실행 권한을 추가하지 않습니다.
- 별도 관리자 화면: PC의 SSH 터널을 통해서만 접속합니다. 최소 16자 별도 관리자 비밀번호(scrypt), HttpOnly/SameSite 쿠키, 15분 세션, 분당 5회 전역 로그인 제한, Origin/Host 검사와 제한된 HTTP 요청 크기/동시 접속을 사용합니다.
- 별도 실행 서비스: root 소유 `/usr/local/lib/lekiwi-updater` 코드와 `/etc/lekiwi-updater` 정책만 신뢰합니다. HTTP 입력은 태그·전체 SHA·현장 모터 전원 분리 확인뿐입니다. 임의 명령·원격 주소·경로·정책 변경 API가 없습니다.
- Git fetch/서명 확인은 권한 없는 `lekiwi-fetch` 계정으로 실행합니다. 원본은 고정 HTTPS 저장소이며 이동한 태그를 강제 덮어쓰지 않습니다. annotated GPG 태그, 명시한 신뢰 fingerprint, main 포함 여부, 기존 버전의 후속 커밋, 메타데이터 및 변경 범위를 재검증합니다.
- 릴리스를 root 소유의 독립 디렉터리에 추출합니다. 링크/경로 탈출/특수 파일과 큰 아카이브를 거부하며 릴리스 코드를 root로 실행하지 않습니다. Git hook/filter나 릴리스의 install.sh를 root로 실행하지 않습니다.
- 배포 중 공유/배타 파일 잠금으로 조종 시작·prepare·새 명령·기록 시작을 차단합니다. 정지·기록 종료·조회는 계속 허용합니다. 네트워크 준비 전에 대기를 확인하고 잠금을 유지하므로 준비 중 새 조종이 시작되지 않습니다.
- 설정·기록·ROS workspace를 별도 비공개 폴더에 복사하고 SHA256/파일 수를 대조합니다. 외부 링크·특수 파일·공간 부족은 실패합니다. workspace 내부 링크는 원래 절대 경로 참조를 유지해 보존합니다.
- `current` 심볼릭 링크를 원자적으로 전환하고 고정된 phone/camera 시스템 서비스만 재시작합니다. 기존 PIN·웹/시스템 커밋·소프트웨어 대기·본체 JPEG와 보존 파일을 검증합니다.
- 실패하면 이전 링크와 변경된 데이터/설정을 복원합니다. 예상하지 못한 신규 데이터는 `post-failure/`에 먼저 보존합니다. 복구 실패는 잠금을 유지하며 수동 복구를 요구합니다.
- 저널/marker/링크 교체는 fsync합니다. 서비스 재시작 시 중단된 작업을 복구하되 자동으로 잠금을 해제하지 않습니다. 별도 관리자 확인은 이전 서비스를 시작·검증한 뒤 잠금을 해제합니다. 모터 활성화는 수행하지 않습니다.

## 의도적인 제한

이번 구현은 **application 릴리스**용입니다. OS/apt/Python 의존성·드라이버·설치기·업데이트 실행기 자체·데이터 스키마 변경은 자동 적용하지 않습니다. 변경을 감지하면 수동 업데이트로 넘깁니다. root 실행 서비스의 코드를 웹 업데이트로 교체하지 않으며, 임의 apt rollback을 안전하다고 주장하지 않습니다.

`app/`, 문서·포털·테스트·증거·workflow 및 README/고지와 `update-release.json` 변경만 허용합니다. 서명된 메타데이터가 호환성을 선언해도 실물 동작을 자동으로 입증하는 것은 아닙니다. 릴리스 관리자가 별도로 검증해야 합니다.

GitHub 머지 커밋의 서명이나 SHA만으로 운영 릴리스가 되지 않습니다. 신뢰한 관리자가 서명한 실제 태그와 검증 기록이 필요합니다. 현재 운영 태그/신뢰 키는 만들거나 장비에 설치하지 않았습니다.

서비스 health 검증은 조종·저장 대기, 실제 앱 커밋, 기존 PIN, 웹 응답·본체 JPEG입니다. 물리 주행·정지·통신 단절과 모든 카메라 역할 시험은 현장 검증이 필요합니다. 모터 피드백이 없어도 자동으로 정지라 판단하지 않으며 현장에서 모터 전원을 분리했다는 별도 확인을 요구합니다.

## 아키텍처와 권한

```text
스마트폰 → 기존 PIN 웹앱 (상태 읽기, 조종/기록 잠금 준수)
PC → SSH -L 8093:127.0.0.1:8093 → 별도 관리자 웹 (127.0.0.1 전용)
                                     ↓ 승인된 고정 작업
                            root 소유 업데이트 실행 서비스
                               ├─ 비권한 Git fetch/GPG 확인
                               ├─ 비공개 snapshot + 저널
                               └─ current 전환 + 고정 systemd 단위
```

관리자 암호는 로봇 웹앱에 전달하지 않습니다. SSH 터널 없이 관리자 포트를 AP/공인 네트워크에 노출하거나 포워딩하지 마세요. 평문 HTTP는 로컬 SSH 터널 종단 사이에서만 사용합니다.

기존 user 서비스와 managed system 서비스는 다른 배치입니다. opt-in 설치기는 root 실행 코드를 따로 복사하고 user phone/camera를 중지·자동 시작 해제한 뒤 sandboxed system 단위로 전환합니다. 앱은 기존 일반 로봇 사용자로 실행하되 NoNewPrivileges, 읽기 전용 시스템/홈, 기록·상태 경로만 쓰기 허용, 사용자/시스템 D-Bus·sudo 계열 경로 접근 제한을 적용합니다. Git worker는 별도 비권한 계정입니다. robot_user의 대화형 SSH 관리 권한 자체를 변경하지는 않습니다. root/SSH 관리자와 신뢰 서명자는 신뢰 경계 안에 있으며 커널/ROS·카메라 하드웨어 취약점까지 해결한 설계는 아닙니다.

기존 시스템 화면의 user systemd 진단은 managed system 서비스에서 확인 불가일 수 있습니다. 새 실행 서비스는 system scope의 active/inactive를 직접 확인합니다. 미확인을 정상으로 표시하지 않습니다.

## 설치 준비 (현재 장비에서는 미실행)

1. 코드를 검토하고 별도 시험 장비/디스크 이미지에서 검사합니다. 기존 AP·PIN·설정·유닛·workspace·기록·운영 Git 소스를 외부 매체에 백업합니다.
2. 릴리스 서명자의 **공개키만** armored 형식으로 준비합니다. 개인키를 Pi에 복사하지 않습니다. fingerprint는 별도 신뢰 경로로 받습니다.
3. 루트 읽기 전용 Git 출처와 검토한 Phase 2 baseline 커밋을 확인합니다. 새 baseline은 `app/maintenance.py`를 포함한 clean 체크아웃이어야 합니다.
4. 아래는 계획 검사 예시입니다. 실제 값으로 바꾸기 전 실행 가능한 설치 명령이 아닙니다.

```bash
python3 tools/provision_updater.py \
  --robot-user ROBOT_USER --config /home/ROBOT_USER/.config/lekiwi-phone/config.json \
  --baseline-commit REVIEWED_40_CHARACTER_BASELINE \
  --signer TRUSTED_PRIMARY_FINGERPRINT --public-key /path/to/signer-public.asc
```

`--apply` 없이는 설정을 읽어 계획만 출력합니다. root 권한·계정/서비스 변경·암호 입력은 수행하지 않습니다. 실제 적용은 root 대화형 터미널에서 `--apply --motor-power-isolated`가 추가로 필요하며 숨긴 관리자 암호를 두 번 입력합니다. 비밀값을 옵션/로그에 넣지 않습니다.

설치기는 기존 managed 배치를 덮어쓰지 않습니다. 기존 system 단위 이름 충돌·겹치는 백업 경로·링크·root runtime 사용자는 거부합니다. 전환 검증 실패 시 새 서비스를 중지하고 이전 user 서비스 상태 복원을 시도하며, 실패 자료와 bootstrap 백업을 유지합니다. 이 root/systemd 전환은 실제 장비에서 아직 검증하지 않았습니다. 기존 관리 계정으로 sudo 권한이 필요합니다.

필수 시스템 도구는 Python3.12, git, GnuPG, setpriv, systemd, runuser, useradd와 기존 ROS/Python 런타임입니다. 자동 apt 설치는 하지 않습니다.

## 관리자 사용

PC에서 다음처럼 SSH 터널을 유지합니다.

```bash
ssh -L 8093:127.0.0.1:8093 ROBOT_USER@ROBOT_IP
```

PC 브라우저에서 `http://127.0.0.1:8093`을 엽니다. 관리자 로그인 → 검증 릴리스 확인 → 변경 내용과 전체 SHA 확인 → 모터 전원 분리/접근 통제 확인 → 승인 순서입니다. 업데이트 중 로봇 웹앱은 잠시 끊겨도 관리자 진행 화면은 유지됩니다. 서비스 중단 시에도 다시 로그인하여 저널 상태를 확인할 수 있습니다.

릴리스가 없거나 서명·호환 조건에 맞지 않으면 선택 목록이 비어 있습니다. 예시 태그나 main을 검증 릴리스로 생성하지 않습니다. `recovered_unverified`에서는 모터 전원 분리 상태로 복구 서비스를 재검증한 뒤 잠금을 해제합니다. `manual_recovery_required`에서는 자동 재시도하지 않고 SSH/콘솔로 원인을 조사합니다.

## 릴리스 메타데이터

후보 Git 트리의 `update-release.json` 예시입니다. 아래 `qualified:false`는 의도적으로 적용 불가입니다. 검증 전 true로 바꾸지 마세요.

```json
{
  "schema": 1,
  "kind": "application",
  "qualified": false,
  "config_schema": 1,
  "recording_schema": "lekiwi-episode-v1",
  "platform": "ubuntu-24.04-aarch64",
  "updater_protocol": 1,
  "notes": "변경 사항, 호환성, 실제 검증 기록 위치"
}
```

후보가 검토·테스트·main 반영·현장 검증을 마친 후 릴리스 관리자가 signed annotated tag를 발행합니다. fingerprint/keyring 교체·폐기는 별도 root 관리 작업입니다. keyring의 최신 폐기 인증서 반영 없이 온라인 폐기를 자동 발견한다고 주장하지 않습니다.

## 중단·실패·수동 복구

- 실제 기기 안전과 현장 접근 통제를 먼저 확보합니다. 다른 모터 소유 프로세스를 임의 종료하지 않습니다.
- `systemctl status lekiwi-updater lekiwi-phone lekiwi-camera`와 root 전용 `journal.json`을 확인합니다. PIN/AP 암호가 담긴 백업을 공개 로그·이슈에 붙이지 않습니다.
- `maintenance.json`을 임의 삭제해 조종을 강제로 허용하지 않습니다. 정상 interrupted 복구는 관리자 재검증 경로로만 해제합니다.
- 수동 복원이 필요한 경우 새 데이터를 별도 보존하고 `backups/<job>/`의 설정/기록/workspace manifest와 원래 절대 경로를 대조합니다. `current`는 보존된 이전 SHA의 릴리스 경로로 복원합니다. 서비스/OS/데이터 복구는 Git 복귀와 구분합니다.
- 초기 관리 배치 전환을 되돌릴 때는 system phone/camera/updater를 정지·자동 시작 해제하고 bootstrap-backup의 이전 user 유닛/enable 상태를 확인해 user scope를 복원합니다. 기존 소스와 workspace를 삭제하지 않습니다.
- 실패 후보 디렉터리와 백업은 자동 삭제하지 않습니다. 같은 SHA의 재시도는 기존 후보 충돌을 거부할 수 있으므로 원인 조사·보존 후 관리자가 정리해야 합니다.

## 검증 상태

Python 테스트는 실제 임시 Git/GPG 서명 검증, 잘못된 신뢰/서명·릴리스/의존성·아카이브 거부, 실제 파일 snapshot·해시/링크 전환·변경 데이터 보존, 모의 서비스 검증/롤백·부팅 중단 복구·파일 잠금, 실제 HTTP 관리자 인증/CSRF·일반 조종 잠금 검사를 포함합니다.

Chromium은 기존 10개 시나리오와 별도 관리자 화면 5개 시나리오를 검사합니다. 관리자 브라우저 시험의 서비스/Git 소스는 합성 fixture이며 물리 장비나 root 서비스 설치 성공이 아닙니다. 테스트 fixture 서버는 운영 서비스로 사용하지 않습니다.

별도 현장 시험 대상: root/systemd opt-in 전환, sandbox 안의 ROS/카메라/serial 접근, 대규모 실제 데이터/공간 부족·디스크 장애, 서비스 scope 복원, 재부팅/전원 단절, 실제 signed release 업데이트·실패 롤백·현장 방향/정지. 이 항목을 완료하기 전 운영 배포 승인을 주장하지 않습니다.
