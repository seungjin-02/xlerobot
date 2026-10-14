# 확인과 복구

폰에서 페이지가 안 뜨면 실제 로봇 AP에 연결했는지, '인터넷 없이 연결 유지'를 선택했는지 확인합니다. 핫스팟/모바일 데이터를 잠시 끄고 `http://192.168.4.1:8090`로 접속합니다. 인터넷 없음 표시는 정상입니다.

랜선은 `ip -br addr`, `ip neigh`, `nmcli device status`로 링크/DHCP를 확인합니다. carrier0이면 전원/케이블부터 확인. 이전 로봇 IP나 SSH host key를 새 기기에 그대로 신뢰하지 않습니다. 새 기기의 SSH fingerprint를 현장/관리자와 확인합니다.

```bash
systemctl --user status lekiwi-phone.service lekiwi-camera.service
journalctl --user -u lekiwi-phone.service -n 100 --no-pager
journalctl --user -u lekiwi-camera.service -n 100 --no-pager
curl http://127.0.0.1:8080/status
ls -l /dev/serial/by-id /dev/v4l/by-path
free -h
df -h ~
du -sh ~/lekiwi-recordings
```

설치 전/업데이트 전 주행과 기록을 종료합니다. 서버 재시작은 활성 조종을 끊으므로 조종 중 업데이트하지 않습니다.

```bash
systemctl --user stop lekiwi-phone.service lekiwi-camera.service
```

프로필 이전본 `robot-profile.previous.yaml`, 유닛 `.service.previous`, `previous-controllers.json`에 이전 자동시작 상태가 남습니다. 복구할 때 현재본을 별도 비공개 폴더에 백업하고 이전본을 복원, daemon-reload 후 서비스 시작합니다. 기존 lekiwi-host/lekiwi-nav를 다시 사용할 경우 폰 서비스가 멈춰 있음을 확인하고 이전 enable 상태에 맞춰 복원합니다. 모터 USB를 두 프로세스에서 동시에 제어하지 않습니다.

저장 공간은 기록으로 증가합니다. 자동 삭제는 없습니다. 백업을 검증한 뒤 사용자가 원본 제거 여부를 결정합니다. 남은256MB/128MB 임계값은 마지막 보호장치이며 수GB 여유를 남겨 운영합니다.
