# 웹앱 자동 탐색·순회

웹앱의 **자율 순회**에서 새로운 공간의 온라인 SLAM과 Nav2 목표 이동을 실행한다. 알려진 빈 공간을 따라 미탐색 경계에 접근하고, 이후 접근 가능한 영역을 순회한 뒤 출발점으로 복귀한다. 출발점 기준 반경·운행 시간·누적 거리·순회 횟수를 제한한다. 방 전체 청소율 또는 최적 경로는 보장하지 않는다.

## 실물 시작 조건

`~/.config/lekiwi-phone/config.json`의 `patrol.calibration`이 필요하다. `measured: true`는 실제 측정 후에만 입력한다.

- `robot_radius`: 본체 중심에서 바퀴·케이블 등 가장 먼 돌출부까지의 거리(m).
- `base_frame`: 보통 `base_footprint`이며 기존 odometry와 일치해야 한다.
- `lidar_frame`: 실제 `/scan` 메시지 프레임(현재 새 로봇은 `lidar_link`).
- `lidar_transform`: 본체 프레임 기준 `x,y,z`(m), `roll,pitch,yaw`(rad). x 앞, y 왼쪽, z 위. 센서의 실제 스캔 평면과 방향을 측정한다.
- `external_lidar_tf`: 이미 올바른 외부 TF가 있으면 true, 이 프로그램이 실측 TF를 발행하면 false.

센서 지름만으로 위치·방향·전체 외곽을 추정하지 않는다. 설정 수정 후 웹 서비스를 재시작한다. 실제 첫 주행은 바닥이 평평하고 계단·낙차가 없는 제한된 공간에서 감독하며 검증한다. 2D LiDAR 스캔 평면 밖의 장애물·낙차 감지는 별도 센서 없이는 보장되지 않는다.

## 제어와 기록

수동 조종과 자동 주행은 한 제어권을 공유한다. Nav2 명령은 NavigationGuard를 거치며 선속도 요청을 0.1m/s, 각속도를 0.5rad/s로 제한한다. 센서·TF·지도·계획 응답 이상, 기록 오류, 목표 취소 응답 시간 초과 시 종료한다. 일시정지와 종료는 0 명령 및 모터 비활성화를 요청한다. 실제 제동 성능은 하드웨어에서 별도 확인한다.

영상·상태·실제 발행 명령·ROS bag·목표 및 결과 이벤트를 기존 웹 기록에 저장한다. `device_profile.control_mode=autonomous`이며 결과 기본값은 `unfinished`다. 학습 데이터 변환은 자동 기록을 기본 제외하며 `export_lerobot.py --include-autonomous`로 명시적으로 선택한다. 자동 실행만으로 학습 모델이 훈련되지는 않는다. 외부 업로드는 없다.

## 검증

`python3 -m unittest discover -s app -p test_control.py`, `python3 -m unittest discover -s tests`.
`tools/simulate_patrol.py`는 완벽한 위치와 합성 센서를 사용한 로직 시험이다.
`tests/ros_patrol_integration.py --output <새 폴더>`는 합성 센서·가상 바퀴에 실제 slam_toolbox/Nav2/rosbag를 연결한다. 물리 주행·카메라 품질·실제 청소율 검증과 구분한다.
