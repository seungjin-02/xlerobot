# 기록·백업·학습용 변환

실제 원본은 로봇 `~/lekiwi-recordings/<episode-id>/`입니다. 다운로드는 선택사항이고 폴더를 PC/외장SSD로 복사해도 됩니다. 기록 종료 후 복사하여 작성 중인 파일을 피합니다.

Ubuntu/PowerShell에서 아래처럼 복사합니다(경로와 계정은 실제 값으로 교체).

```bash
scp -r <user>@<robot-ip>:/home/<user>/lekiwi-recordings ./private/
python tools/dataset_manifest.py ./private/lekiwi-recordings --output ./private/data-manifest.json
```

두 번째 기기는 현재 실제 기록이 없고 첫 기기의 과거 기록은 이 저장소에 포함되지 않았습니다. `data/synthetic-example/`은77프레임 합성 검증 데이터로, 학습 성능을 의미하지 않습니다. 로봇 Wi-Fi암호/PIN/SSH키는 데이터와 함께 Git에 넣지 않습니다. `episode.json`의 device_profile에는 바퀴/카메라/팔 구성만 보존합니다.

원본: episode.json(작업·결과·기기·완료), samples.jsonl(20Hz 목표의 시각·상태·요청/발행행동), commands.jsonl(폰명령), frames/*.jpg(본체).

camera_capture_ns는 cap.read 직후 monotonic 시각으로 실제 노출시각과 같지 않습니다. training_valid는 카메라<=150ms, 상태<=250ms, 명령 연결<=600ms 등 품질 조건을 반영합니다. 상태6차원=[x,y,yaw,vx,vy,yaw_rate], 행동3차원=[vx,vy,yaw_rate]. applied_action은 실제 ROS 발행 Twist로 물리 실측 속도는 아닙니다. odom은 엔코더 기반 상대추정이며 지도 위치가 아닙니다.

집게 영상을 선택해도 새 기록은 본체만 저장합니다. 카메라 역할 변경 전 과거 기록은 metadata와 실제 프레임을 확인한 뒤 분리합니다. 팔 장착유무·자세가 주행과 시야에 영향을 주므로 동일 작업/구성별로 관리합니다.

## 새 Ubuntu PC / WSL2 환경

Python3.12 가상환경에서(현재 검증은 Ubuntu PC):

```bash
python3 -m venv .venv-export
source .venv-export/bin/activate
python -m pip install -r requirements-export.txt
python export_lerobot.py ./private/lekiwi-recordings --output ./private/new-dataset
```

실제로 검증한 LeRobot0.6.0을 고정했습니다. 학습용 GPU PyTorch/CUDA 구성은 PC에 맞게 별도 준비합니다. 새 환경 설치의 모든 전이 의존성을 lock한 파일은 아니므로 아래 environment-versions.json과 비교하세요.

합성 예제 변환은 명시적으로 `--allow-demo`를 사용:

```bash
python export_lerobot.py data/synthetic-example --output ./private/synthetic-dataset --allow-demo
```

기본값은 완결된 성공 시범과 유효 연속구간만 사용; 최소10프레임,20fps. 실패 포함은 --include-failures, 완결된 미분류 결과 포함은 --include-unfinished. 파일 자체가 불완전한 episode는 항상 제외. 출력 폴더는 새 경로여야 함. 결과는 observation.images.front(HWC), observation.state(6), action(3), requested_action(3), task이며 cloud 업로드하지 않습니다.

모델 학습은 아직 구현하지 않았습니다. 기존 팔 포함9차원 모델에 그대로 넣을 수 없고 base-only 정책에 맞춰야 합니다. 기록만으로 모델이 학습되지는 않습니다.

대량 실물 영상은 외장SSD/별도 데이터 저장소에 보관하고 manifest(경로,크기,SHA256,작업/결과)를 Git에 추가하면 됩니다. GitHub 저장소에는 작은 합성예제만 보존합니다. 새 데이터는 private/에 가져온 뒤 별도로 백업합니다.
