#!/usr/bin/env python3
import hashlib,json,zipfile
from pathlib import Path
r=Path(__file__).resolve().parents[1]
files=sorted(p for p in r.rglob('*') if p.is_file() and not any(x in p.relative_to(r).parts for x in ('.git','__pycache__','dist','private','.venv')) and p.name!='SHA256.json')
(r/'dist').mkdir(exist_ok=True)
with zipfile.ZipFile(r/'dist/lekiwi-setup-and-recording.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in files:z.write(p,'xlerobot/'+str(p.relative_to(r)))
(r/'dist/SHA256.json').write_text(json.dumps({'lekiwi-setup-and-recording.zip':hashlib.sha256((r/'dist/lekiwi-setup-and-recording.zip').read_bytes()).hexdigest()},indent=2)+'\n')
print('Created portable snapshot ZIP')
