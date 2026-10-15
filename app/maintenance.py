"""Read-only side of the updater lock. Stop/finish/read APIs remain available."""
import contextlib
import fcntl
import json
import os
from pathlib import Path

from core import ControlError

class Maintenance:
    def __init__(self, root=None, required=None):
        self.root = Path(root or os.environ.get('LEKIWI_UPDATE_ROOT', '/var/lib/lekiwi-updater'))
        self.required = os.environ.get('LEKIWI_MANAGED_UPDATES') == '1' if required is None else required

    @contextlib.contextmanager
    def allow(self):
        path = self.root/'operation.lock'
        if not path.exists():
            if self.required: raise ControlError('업데이트 서비스 상태 확인 필요: 조종이 차단됐습니다')
            yield
            return
        try:
            with path.open('rb') as lock:
                try: fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError: raise ControlError('업데이트 중에는 조종·기록을 시작할 수 없습니다') from None
                if (self.root/'maintenance.json').exists():
                    raise ControlError('업데이트/복구 검증 전까지 조종·기록이 차단됩니다')
                yield
        except OSError:
            raise ControlError('업데이트 잠금을 확인할 수 없어 조종을 차단했습니다') from None

    def status(self):
        admin_url = os.environ.get('LEKIWI_ADMIN_URL')
        extra = {'admin_url': admin_url} if admin_url else {}
        try:
            value = json.loads((self.root/'status.json').read_text())
            return {**extra, 'enabled':True, 'blocked':(self.root/'maintenance.json').exists(),
                **{k:value.get(k) for k in ('phase','tag','commit','updated_at','error')}}
        except (OSError, ValueError):
            return {**extra, 'enabled':self.required, 'blocked':self.required, 'phase':'unknown' if self.required else 'not_configured'}
