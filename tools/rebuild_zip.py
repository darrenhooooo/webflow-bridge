import zipfile, os
src = 'extension'
out = 'dist/webflow-bridge-0.2.0.zip'
os.makedirs('dist', exist_ok=True)
if os.path.exists(out):
    os.remove(out)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in sorted(files):
            if f.startswith('.'):
                continue
            p = os.path.join(root, f)
            arc = os.path.relpath(p, src).replace(os.sep, '/')
            z.write(p, arc)
print('built:', out)
hits = []
with zipfile.ZipFile(out) as z:
    for n in z.namelist():
        if n.endswith(('.json', '.js', '.html', '.css')):
            txt = z.read(n).decode('utf-8', 'ignore').lower()
            if 'kimi' in txt:
                hits.append(n)
print('kimi hits:', hits if hits else 'NONE - clean')
with zipfile.ZipFile(out) as z:
    mf = z.read('manifest.json').decode('utf-8')
    for line in mf.splitlines():
        if '"version"' in line or '"description"' in line or '"name"' in line:
            print(line.strip())
