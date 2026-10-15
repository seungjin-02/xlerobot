#!/usr/bin/env python3
"""Build an offline single HTML and ZIP; no network, app or robot access."""
import base64
from pathlib import Path
import json
import zipfile

root = Path(__file__).resolve().parent
out = root.parent / 'private' / 'presentation-delivery'
out.mkdir(parents=True, exist_ok=True)
assets = {p.name: 'data:image/png;base64,' + base64.b64encode(p.read_bytes()).decode('ascii')
          for p in (root / 'assets').glob('*.png')}
script = (root / 'app.js').read_text().replace("const asset=name=>'assets/'+name;",
    'const embeddedAssets=' + json.dumps(assets) + ';const asset=name=>embeddedAssets[name];')
html = (root / 'index.html').read_text().replace('<link rel="stylesheet" href="style.css">',
    '<style>' + (root / 'style.css').read_text() + '</style>').replace(
    '<script src="app.js"></script>', '<script>' + script.replace('</script>', '<\\/script>') + '</script>')
(out / 'LeKiwi-presentation.html').write_text(html)
with zipfile.ZipFile(out / 'LeKiwi-presentation.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
    for p in sorted(root.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            bundle.write(p, Path('LeKiwi-presentation') / p.relative_to(root))
print(out)
