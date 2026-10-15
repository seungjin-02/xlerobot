# SLAM 기록과 Nav2 흐름 구현 보고

## 먼저: 실제 기기 지도는 만들지 않았습니다

이번 작업은 클라우드에서 수행했으며 르키위·노트북 랜선·실제 LiDAR에 접속하지 않았습니다. 검증용 **6m×6m 가상 방**에서 벽까지의 거리, 가상 로봇 pose/odometry, base→laser 고정 TF와 동적 TF를 생성했습니다. 이 합성 메시지를 실제 ROS Jazzy rosbag2/SLAM Toolbox/Nav2에 입력했습니다. 지도와 목표 도착 결과는 **소프트웨어 경로 검증**이며 실제 장소 지도, 물리 시뮬레이터 또는 실물 주행 검증이 아닙니다.

## 구현

1. 최신 원격 main `e9c020f`를 가져오고 별도 feature 브랜치에서 작업했습니다.
2. 기존 기록 UI/API에 선택적 SLAM 모드를 추가했습니다. 실물 ROS/rosbag2 환경에서 기본 선택되며 데모에서는 사용할 수 없습니다. 기존 API에서 옵션 생략은 기존 카메라 기록 방식입니다.
3. 원본 LaserScan/Odometry/TF와 제공되는 IMU·PointCloud·JointState·명령·모터 준비·진단·카메라 보정·배터리·지도/위치/경로/목표 토픽을 bag에 저장합니다. 존재하지 않는 센서는 만들어 넣지 않습니다.
4. 구독 전용 별도 프로세스로 CDR/SQLite를 기록하고 센서 신선도·프레임 연결·scan/odom 시각 차이·역행·메시지 형태·중복 발행자·디스크 여유·프로세스 종료를 감시합니다. 종료 시 bag/manifest를 닫고 기존 ZIP에 포함합니다.
5. SLAM 모드에서는 카메라가 없어도 기록합니다. 카메라 없는 샘플의 training_valid는 false이며 가짜 JPEG/유효 학습 프레임을 만들지 않습니다. 기존 이미지+상태6+행동3 export는 변경하지 않았습니다.
6. 오프라인 입력 검사·mapping bag 준비·SLAM Toolbox lifecycle 활성화·시뮬레이션 clock 재생·PGM/YAML 지도 저장·pose graph 직렬화를 추가했습니다. motor/goal 명령을 재생하지 않으며 기존 map→odom을 제거합니다. 실제 로봇 domain42와 분리합니다.
7. 저장 지도에서 AMCL omni 위치 추정 → Nav2 NavFn 계획/DWB holonomic 추종 → `/nav2_cmd_vel` → guard → 기존 RosBackend 출력 한도 → `/cmd_vel`의 실행 경로를 구현했습니다.
8. Nav2는 기본 설정 준비만 하며 `--enable-motion`이 있어야 실제 모터 활성화를 허용합니다. 폰 서비스·다른 발행자 충돌을 거부하고 준비/센서/명령 timeout 및 수치 이상에서 정지/비활성화를 요청합니다. 실제 footprint 반경은 사용자 실측 필수 입력입니다.

## 파일과 기존 호환성

- `app/slam.py`, `app/slam_capture.py`: 설정·센서 품질·별도 worker 수명 관리와 bag 기록.
- `app/recorder.py`, `app/server.py`, `app/index.html`, `app/app.js`, `app/style.css`: SLAM 선택·상태·카메라 선택적 기록·다운로드 포함.
- `app/navigation_guard.py`, `tools/navigation_launch.py`, `tools/start_navigation.py`: Nav2 전용 출력, 저속/신선도/충돌 감시, 명시적 실행.
- `tools/check_slam_sensors.py`, `tools/slam_map.py`, `tools/prepare_slam.sh`: 입력 검사·오프라인 지도·Ubuntu 의존성.
- `prepare-system.sh`: rosbag2 Python/SQLite 의존성 추가. 기존 updater의 앱 전용 업데이트 범위 밖이므로 수동 설치 필요.
- `app/ros_backend.py`: 노드 이름을 선택하는 선택적 인자만 추가. 수동 제어는 기본 이름을 유지하며 자율주행 guard는 다른 이름을 써 서로를 다른 발행자로 감지합니다.
- `tests/test_slam.py`, `tests/test_http.py`, `tests/browser_smoke.cjs`, `tests/ros_slam_integration.py`, `tests/ros_navigation_integration.py`: 단위/API/브라우저/실제 ROS 합성 통합 검증.
- `updater/network.py`: 기존 테스트에서 발견한 OpenSSL3.0/3.5의 IP mismatch 종료 코드 차이를 처리합니다. 성공 종료와 명시적 IP 일치 문구를 모두 요구하며 검증을 우회하지 않습니다.
- `README.md`, `docs/DATA.md`, `docs/HANDOFF.md`, `docs/INSTALL.md`, 새 SLAM 문서: 기록·지도·자율주행·미검증 범위와 로컬 이관 절차.

`app/core.py`의 수동 연결 단절 10초 정책, 기존 속도/가속 제어, 드라이버 소스, 카메라 서버, `export_lerobot.py`, 기존 에피소드 기본 형식은 유지합니다. SLAM sidecar와 선택적 API 필드를 추가했으며 새 trainer/3D SLAM/웹 자율주행 목표 UI는 구현하지 않았습니다.

## 검증의 의미

Python 회귀/추가 테스트, 일반·관리자 Chromium 시험과 실제 Jazzy 통합 결과는 `evidence/slam/verification.json`에 기록합니다. 실제 ROS 시험은 공식 `ros:jazzy-ros-base` 컨테이너(Ubuntu24.04 amd64)와 apt의 Jazzy SLAM Toolbox/Nav2를 사용했습니다. ARM64 실물 시험은 아닙니다.

- 원본 bag에는 실제 ROS 타입/직렬화로 합성 scan·odom·TF·IMU·관절·0 속도 명령을 저장했습니다.
- 지도는 120×120 cells, 0.05m/cell의 합성 방입니다. 실제 `/map`과 pose graph 파일 출력을 확인했습니다.
- 생성한 지도를 Nav2 map_server/AMCL/planner/controller/behavior/smoother/BT 노드 7개에 로드했습니다. 합성 목표 `(0.6,0)`이 NavigateToPose 상태4(SUCCEEDED)로 완료됐습니다. 실제 하드웨어를 연결하는 RosBackend 대신 가상 모터에 guard 출력을 적분해 synthetic pose를 갱신했습니다. 목표 허용 오차 내 도착이며 정확히 0.6m를 물리적으로 주행했다는 뜻이 아닙니다.
- guard 이동 요청 상한0.1m/s, 종료 후 출력0·모터 비활성, Nav2의 `/cmd_vel` 직접 발행 없음과 센서/명령/충돌/실패 시 정지 분기를 검사했습니다.

## 실제 사용 전에 남은 것

LiDAR 모델/드라이버/토픽, 본체와 센서 좌표/실측 extrinsic, 실제 시간 동기화, ROS domain, GPIO/USB·모터 방향·동역학·엔코더 오차, 카메라/IMU 보정, 로봇 외접 반경, 현장 지도 품질을 확인해야 합니다. 메시지 수신과 TF 연결은 물리적 보정 정확성을 검증하지 않습니다. 장애물 회피와 정지/제동은 실제 장비에서 현장 통제 하에 검증해야 합니다.

기존 학습 export에 LiDAR/IMU가 자동 추가되지 않습니다. 정책 학습에는 별도 시간 정렬·결측 처리·feature 스키마·trainer·평가가 필요합니다. SLAM 지도/Nav2는 이 학습과 별개로 사용합니다.

사용자 지시에 따라 **feature 브랜치 로컬 커밋만** 남깁니다. 원격 푸시·PR·main 병합·릴리스·장비 적용은 하지 않습니다. 이후 Ubuntu 로컬 작업은 [인수인계](SLAM_HANDOFF.md)와 [사용 절차](SLAM.md)를 따릅니다.
