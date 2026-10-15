# 교수님께 보여드리는 LeKiwi · 5분 시연

2026-10-15 확인한 main `e9c020f`와 SLAM 확장 `0926137`을 비교하는 발표 자료입니다. 배포하지 않은 로컬 정적 자료이며 실제 로봇을 제어하지 않습니다.

## 실행

가장 간단한 전달 파일은 `private/presentation-delivery/LeKiwi-presentation.html`입니다. 이미지까지 포함한 단일 HTML이며 다운로드해서 브라우저로 열면 됩니다. `python3 presentation/build_delivery.py`로 다시 생성할 수 있습니다. ZIP은 이 소스 폴더 전체를 담습니다.

이 폴더 전체를 복사해 `index.html`을 Chrome/Edge/Firefox에서 여세요. HTML·CSS·JS·이미지 외의 의존성과 인터넷 연결이 필요하지 않습니다. 로컬 파일 접근이 제한된 관리형 브라우저에서는 다음으로 실행하고 브라우저 주소창에 `http://127.0.0.1:8088`을 입력하세요.

```bash
cd /path/to/xlerobot/presentation
python3 -m http.server 8088 --bind 127.0.0.1
```

상단에서 버전을 선택하고 하단에서 장을 이동합니다. `←` `→`: 장 이동, `1` `2`: 버전 전환, `Space`: 개념 시연 재생/정지, `F`: 전체 화면. 실제 앱 이미지 클릭 시 전체 캡처가 열립니다. 시연 진행 막대는 가상의 수집 흐름만 바꿉니다.

## 권장 5분 순서

[발표 대본](TALK_TRACK.md)을 보면서 **main 1 → 2 → 3 → 4 → latest 1 → 2 → 3 → 6 → 7** 순서로 보여주세요. 모든 장을 설명할 필요는 없습니다. 각 버전의 나머지 장은 질문에 답할 때 사용합니다. “개념 시연·실물 연결 없음” 표시는 발표 중 유지합니다.

짧은 무음 미리보기 MP4와 전달용 ZIP은 `private/presentation-delivery/`에 별도 생성합니다. 영상은 발표 자료를 녹화한 것으로 실제 앱 원격 조종 영상이나 실제 로봇 주행 영상이 아닙니다.

## 출처와 주장의 범위

- main 앱 캡처: `git archive origin/main app`으로 `e9c020f` 소스를 별도 임시 폴더에 추출하고 `--demo`로 실행해 촬영했습니다.
- SLAM 캡처: `0926137` 앱의 실제 데모 화면. 데모는 SLAM을 활성화하지 않으며 실제 센서 값을 주입하지 않았습니다.
- 3D 그림: Canvas에 투영한 등각 개념 형상. 실제 LeKiwi CAD·물리 시뮬레이터가 아닙니다. LiDAR 광선·경로·단계는 설명용 애니메이션이며 mapping/Nav2를 실행하지 않습니다.
- 합성 지도: `evidence/slam/synthetic-map.png`. 실제 ROS SLAM Toolbox에 6×6m 합성 방 센서 입력을 넣어 생성한 시험 결과입니다. 실제 현장 지도가 아닙니다.
- 검사 수: `evidence/slam/verification.json`. **0926137 코드**의 Python154개, Chromium20개이며 main 단독 실행 수로 주장하지 않습니다.
- 기능·한계: `docs/CONTROL_CENTER.md`, `docs/PHASE2.md`, `docs/SLAM_IMPLEMENTATION_REPORT.md`, `docs/SLAM.md`, `docs/VERIFICATION.md`.
- 비교 대상은 일반적인 분리된 터미널/카메라/로그 운용 절차입니다. 모든 기존 제품보다 우수하다는 주장이나 성능/시간 향상 수치를 만들지 않았습니다.
- 웹 지도 뷰어·웹 목표 지정·멀티모달 학습·학습된 자율주행 정책은 구현된 기능이 아닙니다. SLAM 지도·Nav2는 현재 별도 터미널 도구입니다.

자료 자체의 확인 결과는 `VALIDATION.json`에 기록합니다. 앱 코드는 변경하지 않았습니다.
