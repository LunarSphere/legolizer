"""Package exact official LDraw geometry for the browser."""
import json
import shutil
from pathlib import Path

def web_name(name):
    # Match LDrawLoader's normalization of subpart and high-resolution paths.
    if name.startswith('s/'):
        return 'parts/' + name
    if name.startswith('48/'):
        return 'p/' + name
    return name

def web_text(text):
    lines = []
    for line in text.splitlines():
        fields = line.split(maxsplit=14)
        if len(fields) == 15 and fields[0] == '1':
            fields[14] = web_name(fields[14].replace('\\', '/').lower())
            line = ' '.join(fields)
        lines.append(line)
    return '\n'.join(lines)

def package_build(source: Path, out: Path, library: Path, build_id: str,
                  title: str, description: str, asset_prefix: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    model = (source / 'model.mpd').read_text(encoding='utf-8')
    packed = []
    seen = set()
    def collect(text):
        for line in text.splitlines():
            fields = line.split(maxsplit=14)
            if len(fields) != 15 or fields[0] != '1':
                continue
            name = fields[14].replace('\\', '/').lower()
            if name in seen:
                continue
            seen.add(name)
            candidates = [library / folder / name for folder in ('parts', 'p', 'models', '')]
            source = next((p for p in candidates if p.is_file()), None)
            if source is None:
                raise FileNotFoundError(f'Official library dependency missing: {name}')
            content = source.read_text(encoding='utf-8-sig')
            packed.append(f'0 FILE {web_name(name)}\n{web_text(content)}\n0 NOFILE\n')
            collect(content)
    collect(model)
    (out / 'packed.mpd').write_text(web_text(model) + '\n' + '\n'.join(packed), encoding='utf-8')
    for name in ('model.mpd', 'parts.json', 'build-guide.pdf', 'render.png'):
        if (source / name).resolve() != (out / name).resolve():
            shutil.copyfile(source / name, out / name)
    config = next(p for p in library.iterdir() if p.name.lower() == 'ldconfig.ldr')
    shutil.copyfile(config, out / 'LDConfig.ldr')
    for license_name in ('readme.txt', 'careadme.txt', 'calicense.txt', 'calicense4.txt'):
        if (library / license_name).exists():
            shutil.copyfile(library / license_name, out / license_name)
    parts = json.loads((out / 'parts.json').read_text(encoding='utf-8'))['parts']
    metadata = {
        'id': build_id, 'name': title, 'description': description,
        'status': 'ready', 'partCount': sum(p['quantity'] for p in parts),
        'colorCount': len({p['color_id'] for p in parts}),
        'stepCount': sum(line == '0 STEP' for line in model.splitlines()),
        'assets': { 'model': f'{asset_prefix}/packed.mpd', 'ldraw': f'{asset_prefix}/model.mpd',
            'colors': f'{asset_prefix}/LDConfig.ldr', 'instructions': f'{asset_prefix}/build-guide.pdf',
            'parts': f'{asset_prefix}/parts.json', 'preview': f'{asset_prefix}/render.png' },
    }
    return metadata
