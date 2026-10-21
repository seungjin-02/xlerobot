# Ubuntu 로컬 Codex 인수인계 — SLAM 기록·지도·Nav2

## 2026-10-21 main 통합 안내

사용자가 main 병합을 요청하여 원격 PR과 통합을 진행합니다. 아래 로컬 bundle 이관 절차와 “병합·푸시 없음” 문구는 최초 보관 시점의 기록이며, 더 이상 병합 금지 지시가 아닙니다. 통합 완료 여부는 GitHub PR과 원격 main으로 확인합니다. 통합 후 Ubuntu에서는 기존 작업을 보존하고 `git fetch origin main`으로 가져와 검토합니다. 기기 적용·의존성 설치·실물 센서 점검은 여전히 별도 단계입니다.

## 최초 구현 시점의 완료/미완료

- 기준 main: `e9c020f` (관리자 6자리 비밀번호 지원까지 반영).
- 작업 브랜치: `feature/slam-recording`. 사용자 요청에 따라 **로컬 커밋만**, 원격 푸시·PR·main 병합·장비 배포·릴리스 게시 없음.
- 코드와 합성 소프트웨어 검증 완료 범위는 [보고서](SLAM_IMPLEMENTATION_REPORT.md), 실제 사용 절차는 [SLAM.md](SLAM.md).
- 실제 르키위와 연결하지 않았으며 LiDAR 모델·실제 토픽·실측 TF·로봇 외접 반경은 확인하지 못했습니다. 합성 지도는 6m×6m 가상 방의 시험 데이터일 뿐 실제 장소 지도가 아닙니다.
- 로컬 커밋을 다른 PC로 가져오기 위해 `private/xlerobot-slam-handoff.bundle`을 제공합니다. 이것은 애플리케이션 ZIP 설치 배포가 아니라 검토 중인 Git 커밋의 오프라인 이관 파일입니다. 원격 반영은 나중에 명시적으로 진행합니다.

## Ubuntu 노트북에서 변경 가져오기와 검토

기존 저장소/로컬 작업을 먼저 보존합니다. bundle은 기준 main 커밋을 전제하므로 원격 main을 fetch해 해당 객체가 있어야 합니다.

```bash
cd /path/to/xlerobot
git status --short
git fetch origin main
git bundle verify /path/to/xlerobot-slam-handoff.bundle
git fetch /path/to/xlerobot-slam-handoff.bundle \
  feature/slam-recording:feature/slam-recording
git switch feature/slam-recording
```

동일한 이름의 로컬 브랜치에 기존 작업이 있으면 강제로 덮어쓰지 말고 새 이름으로 가져옵니다. 로컬 Codex에게 다음을 전달하세요.

```text
docs/SLAM.md, docs/SLAM_IMPLEMENTATION_REPORT.md, docs/SLAM_HANDOFF.md를 읽고
feature/slam-recording 변경을 검토해줘. 기존 사용자 작업을 보존하고 테스트한 뒤,
원격 상태/충돌을 확인해 별도 승인을 받은 main 병합과 르키위 적용을 진행해줘.

새 기능의 기존 검증은 합성 센서·가상 모터이며 실물 적용 검증은 아직 없다.
실제 LiDAR 모델·드라이버·scan 토픽 타입·frame_id·ROS_DOMAIN_ID를 확인하고
실측 odom→base→laser TF와 모터/카메라 설정을 보존해줘.
기존 PIN/AP·기록·ROS workspace·서비스·관리형 업데이트 상태를 먼저 백업해줘.

기존 관리자 app-only 업데이트로 설치/의존성 변경을 우회하지 말고 수동 갱신해줘.
Python/ROS/SLAM 지도 검증 후에만 현장 통제 하에 Nav2를 시험해줘.
실측 로봇 반경과 초기 위치를 사용하고, 모터 활성화 전에 현장 준비를 확인해줘.
학습 데이터는 원본 rosbag+episode를 함께 보존하고 기존 LeRobot 형식과 구분해줘.
```

## main 병합·배포 시 주의

현재 main에 자동 병합하지 않았습니다. 나중에 사용자가 승인하면 최신 main과 충돌을 검토하고 feature/PR의 테스트를 통과시킨 뒤 병합합니다. 여기에 포함된 `prepare-system.sh`와 `tools/` 변경은 기존 Phase 2 updater의 앱 전용 허용 범위 밖입니다. 서명 검증/경로 제한을 낮추거나 앱 릴리스로 가장하지 않습니다. [UPDATE.md](UPDATE.md)에 따라 의존성까지 포함한 수동 업데이트를 합니다.

장비 계정/주소를 이전 기록만으로 확정하지 마세요. 이전 장치 주소 후보는 `10.42.0.141`이었으며 로그인 계정은 미확인이므로 실제 SSH 호스트 키·장비 이름·계정과 연결을 다시 확인합니다. 비밀번호·키를 Git이나 보고서에 넣지 않습니다.

추천 현장 순서:

1. 기존 서비스/설정/데이터/workspace와 복구 방법 확인 및 비공개 백업.
2. 모터 비활성 상태에서 LiDAR/odom/TF read-only 확인. 누락된 모델별 드라이버/실측 extrinsic 구성.
3. rosbag2 의존성 설치와 일반/SLAM 기록 API·UI 확인. 카메라 유무·필수 TF·누락/재연결 실패 표시 확인.
4. 현장 통제·낮은 속도로 짧은 수동 주행 기록. bag counts·시각·TF·이미지·ZIP 보존 확인.
5. Ubuntu PC에서 실제 장소 기록으로 새 지도를 생성하고 벽/원점/거리/loop closure 품질 평가.
6. 실제 지도에서 AMCL 초기 위치 확인. 실측 footprint로 Nav2 계획을 검토하고 물리적 정지 수단 확보 후 명시적 `--enable-motion`으로 감독 하 시험.
7. 정지·명령/센서 단절·다른 제어 충돌·모터 통신 장애·수동 모드 복귀를 검증한 뒤에만 운영 판단.
8. 정책 학습은 성공/실패·장소별 데이터 분리, 센서 시간 정렬, 시뮬레이션/오프라인 평가를 별도로 설계.
