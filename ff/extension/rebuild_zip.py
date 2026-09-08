import json
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
src = BASE
out = os.path.join(BASE, 'dist', 'webflow-bridge-firefox-1.0.0.zip')
os.makedirs(os.path.dirname(out), exist_ok=True)
if os.path.exists(out):
    os.remove(out)

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and d != 'dist']
        for f in sorted(files):
            if f.startswith('.') or f == '__pycache__':
                continue
            p = os.path.join(root, f)
            arc = os.path.relpath(p, src).replace(os.sep, '/')
            z.write(p, arc)
print('built:', out)

issues = []
with zipfile.ZipFile(out) as z:
    mf = json.loads(z.read('manifest.json').decode('utf-8'))
    bss = mf.get('browser_specific_settings') or mf.get('applications') or {}
    gid = (bss.get('gecko') or {}).get('id', '')
    if '.local' in gid:
        issues.append('WARNING: gecko id contains .local: %r' % gid)
    elif not gid:
        issues.append('WARNING: no gecko id found in manifest.json')

    hits = []
    for n in z.namelist():
        if n.endswith(('.json', '.js', '.html', '.css')):
            txt = z.read(n).decode('utf-8', 'ignore').lower()
            if 'kimi' in txt:
                hits.append(n)
    if hits:
        issues.append('kimi hits: %s' % hits)
    else:
        print('kimi hits: NONE - clean')

print('gecko id:', gid)
if issues:
    for i in issues:
        print(i)
    sys.exit(1)
print('manifest check: OK')
