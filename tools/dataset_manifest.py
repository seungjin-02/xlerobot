#!/usr/bin/env python3
"""Read-only dataset inventory; keeps images in separate storage."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
root=a.root.resolve()
if not root.is_dir():p.error('dataset root must be a directory')
files=[]
for f in sorted(root.rglob('*')):
 if not f.is_file() or f.is_symlink() or f.resolve()==a.output.resolve():continue
 h=hashlib.sha256()
 with f.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 files.append({'path':str(f.relative_to(root)),'bytes':f.stat().st_size,'sha256':h.hexdigest()})
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'format':'lekiwi-data-manifest-v1','files':files,'bytes':sum(x['bytes'] for x in files)},indent=2)+'\n')
print(f"Inventoried {len(files)} files; source data unchanged")
