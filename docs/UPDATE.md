# 검증된 Git 태그로 수동 업데이트 — Phase 1

현재 출처·공개 사이트와 지시서별 구현 상태는 [PUBLICATION.md](PUBLICATION.md), [REQUIREMENTS.md](REQUIREMENTS.md)를 확인하세요. 기존 사용자 지정 workspace는 재설치에서도 보존하며, 상태 API의 필수 조종/기록 필드가 누락되면 대기 검사에 실패합니다.

웹 자동 업데이트는 구현하지 않았습니다. 일반 PIN API에서 셸이나 업데이트를 실행하지 않습니다. 아래는 로봇 관리자가 SSH 터미널에서 한 단계씩 확인하는 절차입니다. 실행 가능한 실존 릴리스 태그는 아직 없으며 `VERIFIED_*` 값은 별도로 승인된 태그/커밋으로 바꿔야 합니다. 초기 설치 도우미는 기존 설치를 업데이트하지 않습니다.

## 1. 출처·버전·정지 상태 확인

`~/xlerobot`은 예시 경로이므로 실제 설치 루트를 사용하세요. 원격 주소에는 토큰을 넣지 않습니다. origin은 `https://github.com/seungjin-02/xlerobot.git`의 승인된 배포 출처와 같아야 하며 임의로 바꾸지 않습니다. 공개 배포 저장소가 별도로 승인되면 해당 출처를 검토하여 문서·도우미를 함께 갱신합니다.

```bash
cd ~/xlerobot
git rev-parse HEAD
git describe --tags --exact-match HEAD   # 태그 없으면 운영 버전으로 검증됐다고 간주하지 않음
git status --short --untracked-files=all
```

추적 파일 수정과 비추적 소스 파일이 있으면 중단하고 별도로 보존/검토합니다. `git reset --hard`, `git clean`, `stash` 자동 적용은 사용하지 않습니다. 운영 설치의 코드는 직접 편집하지 않고 feature→테스트→PR→main→검증→릴리스 태그 흐름으로 변경합니다. 기기 설정·인증 정보는 `~/.config/lekiwi-phone`, 기록은 설정의 `recordings` 경로에 유지하며 Git에 넣지 않습니다.

웹에서 기록 종료·조종 종료를 실행하고, 이 버전의 검사 도구가 있는 경우 Pi에서 다음을 실행합니다.

```bash
python3 tools/verify_robot.py --idle
```

PIN은 터미널에서 비표시 입력합니다. 기록/저장/조종/모터 준비/다른 명령 발행자가 있으면 실패합니다. 구버전에 도구가 없으면 기존 UI/인증된 `/api/status`에서 같은 항목을 확인하고 현재 기능이 확인되지 않으면 진행하지 않습니다. 통신 미확인 상태를 물리적 정지로 판단하지 않습니다. 현장에서 모터가 정지·비활성인지 확인하고 필요하면 모터 전원을 분리합니다. 다른 모터 소유 프로세스를 임의 종료하지 않습니다. 업데이트 중 다른 사용자가 조종하지 않도록 접근을 통제합니다. 이번 버전은 분산 업데이트 잠금/관리자 권한 분리를 제공하지 않습니다.

## 2. 비공개 백업과 복구 준비

조종/기록 종료를 확인한 후 새 SSH Bash 세션에서 아래 변수들을 유지하며 진행합니다. 다음은 일반 기본 배치의 예시입니다. config의 실제 recordings/workspace와 외부 서비스·카메라 구성이 다르면 해당 경로까지 별도 백업해야 합니다. 백업에는 암호가 포함되므로 공개 위치·저장소에 두지 않습니다.

```bash
umask 077
backup_dir="$HOME/lekiwi-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$backup_dir"
git rev-parse HEAD > "$backup_dir/old-commit"
git tag --points-at HEAD > "$backup_dir/old-tags"
cp -a "$HOME/.config/lekiwi-phone" "$backup_dir/config"
cp -a "$HOME/.config/systemd/user" "$backup_dir/user-units"
systemctl --user stop lekiwi-phone.service lekiwi-camera.service
```

`systemctl ... is-active`로 비활성을 확인합니다. 위 정지 단계에 실패하거나 다른 제어 프로세스가 남아 있으면 계속하지 않습니다.

설정 파일에서 `workspace`와 `recordings` 경로를 값만 필요한 로컬 관리자에게 확인합니다. 설정 전체를 터미널에 출력하거나 로그로 남기지 마세요. 해당 ROS workspace를 백업하고 실제 기록은 다른 디스크로 복사·해시 검증합니다. 기본 경로를 사용하는 경우의 예:

```bash
cp -a "$HOME/.local/share/lekiwi-phone/ros_ws" "$backup_dir/ros_ws"
# 데이터가 크면 다른 디스크 사용. 설정의 실제 기록 경로로 교체하세요.
cp -a "$HOME/lekiwi-recordings" "$backup_dir/recordings"
python3 tools/dataset_manifest.py "$backup_dir/recordings" --output "$backup_dir/recordings-manifest.json"
```

기록 폴더가 아직 없으면 그 사실을 기록하고 복사 단계만 생략합니다. 외부 경로/심볼릭 링크는 실제 대상도 보존해야 합니다. 남은 공간·복사 종료·해시/파일 수를 확인합니다. ROS workspace는 의존 빌드 아티팩트 복구용입니다. 기존 `.previous` 파일은 재설치 때 덮어써질 수 있어 이번 백업을 대신하지 않습니다. OS/apt 패키지 전체 복원은 파일 복사로 되지 않습니다. 의존성 변경이 크면 SD 카드 이미지/디스크 스냅샷이나 구버전 재설치 환경을 먼저 준비하세요.

## 3. 릴리스 검증과 변경 영향

GitHub Releases와 관리자의 검증 기록에서 실제 태그·전체 SHA·지원 OS·마이그레이션을 확인합니다. 태그를 선택했다고 검증 릴리스가 되는 것은 아닙니다. 서명된 태그를 배포한다면 신뢰된 공개키로 `git tag -v`를 확인하고, 예상 SHA도 별도 신뢰 경로로 확인합니다. 이번 도우미는 관리자 제공 SHA 대조까지 구현하며 서명자 키 배포/자동 검증은 Phase 2입니다.

```bash
release_tag=VERIFIED_TAG
expected_commit=VERIFIED_40_CHARACTER_COMMIT
git fetch origin tag "$release_tag"
new_commit="$(git rev-parse --verify "refs/tags/$release_tag^{commit}")"
test "$new_commit" = "$expected_commit" || exit 1
old_commit="$(cat "$backup_dir/old-commit")"
git diff --name-only "$old_commit" "$new_commit" -- \
  requirements-test.txt requirements-export.txt prepare-system.sh install.sh setup_robot.py \
  start.sh drivers app/recorder.py
```

의존성 변경과 설정·데이터 형식·서비스 호환성을 검토한 뒤 진행합니다. `git fetch`는 태그를 강제로 덮어쓰지 않습니다. 태그가 이동했거나 기존 태그와 충돌하면 중단합니다. `expected_commit`이나 태그를 셸 명령으로 평가하지 않습니다.

## 4. 버전 전환·의존성·서비스

```bash
git checkout --detach "$new_commit"
# --skip-network로 기존 AP 재설정 생략. 실제 확인한 프로필을 사용합니다.
bash install.sh --profile "$HOME/.config/lekiwi-phone/robot-profile.yaml" \
  --skip-network --noninteractive --confirm-wheel-map
python3 tools/verify_robot.py --idle
git describe --tags --exact-match HEAD
git rev-parse HEAD
```

`install.sh`는 의존성 준비, 포함한 드라이버 재빌드, 사용자 서비스 재생성·재시작을 수행합니다. Git 전환만으로 업데이트 완료로 판단하지 않습니다. 기존 PIN/AP 암호, 이름, 카메라 소스·회전, 팔 유무, 기록 경로와 motor ticks 상한을 유지합니다. 의도한 변경은 명시적 옵션으로 지정합니다. `--skip-network`는 기존 설정에 실제 AP 암호가 있어야 하며 누락되면 추측값을 넣지 않고 중단합니다. 의존성/서비스/실물 검증이 실패하면 완료 기록을 갱신하지 않습니다.

위 단계 성공 후 실제 태그/커밋과 검증일을 비공개 운영 기록에 남깁니다. 초기 도우미의 `installed-version.json`은 최초 성공의 감사 기록이며 자동 갱신하지 않습니다. 시스템 화면의 현재 버전은 이 파일 대신 실제 Git HEAD에서 읽습니다. 서비스 응답·본체 JPEG·상태를 확인하고, 필요한 재부팅 후 AP/URL/인증·카메라 역할·저속 방향과 정지·기록과 다운로드를 현장에서 재검증합니다.

## 5. 실패 시 수동 복구

재시작을 반복해 성공으로 처리하지 말고, 서비스 정지와 모터 안전 확보 후 실패 로그를 확인합니다. 업데이트 후 설정과 데이터도 별도 비공개 장소에 보존한 뒤 복원합니다.

1. `git checkout --detach "$old_commit"`으로 이전 코드를 복원합니다. Git은 설정/기록/apt/ROS 빌드를 복원하지 않습니다.
2. 백업에서 `config`와 변경 대상 사용자 유닛만 원래 위치에 복원합니다. 다른 앱의 유닛을 통째로 삭제·덮어쓰지 않습니다. 0700/0600 권한과 경로를 확인합니다.
3. 이전 ROS workspace를 원래 위치로 복원하거나 이전 소스·의존성으로 재빌드합니다. colcon 설치는 절대 경로를 포함할 수 있어 다른 경로로 옮겨 그대로 사용하지 않습니다.
4. 변경한 OS/apt/Python 의존성은 해당 환경 백업/구버전 절차로 복원합니다. Git만 롤백한 상태를 완전한 복구로 표현하지 않습니다.
5. `systemctl --user daemon-reload` 후 기존 phone/camera 서비스를 시작합니다. 구버전의 health/카메라/인증/대기를 검증하고 이전 프로필과 PIN인지 확인합니다.
6. 기록 데이터의 자동 스키마 변환은 수행하지 않습니다. 업데이트 후 신규 데이터도 보존하며 원본/백업 manifest와 비교합니다. 설정 호환성과 실제 방향/정지를 확인할 때까지 운영에 복귀하지 않습니다.

Phase 2의 잠금·별도 권한 실행 서비스·서명 검증·원자적 전환·자동 복구안은 [설계 문서](CONTROL_CENTER.md)를 참조하세요.
