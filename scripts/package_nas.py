#!/usr/bin/env python3
"""Create a private NAS upload archive from explicit source paths and master data."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master-data', type=Path, required=True)
    parser.add_argument('--nas-ip', default='192.168.31.230')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--offline', action='store_true', help='Include downloaded Linux wheels and prebuilt Web')
    args = parser.parse_args()
    payload = json.loads(args.master_data.read_text())
    from nas_master_data import validate_payload
    validate_payload(payload)
    output = ROOT / '.local/nas-deploy' / datetime.now().strftime('%Y%m%d-%H%M%S')
    folder = output / 'sjlerp-nas'
    folder.mkdir(parents=True, mode=0o700)
    os.chmod(output, 0o700)
    ignore = shutil.ignore_patterns('node_modules', 'dist', '__pycache__', '.pytest_cache', '*.pyc', '.env', '.DS_Store')
    for rel in ('apps/api', 'apps/web', 'infra/nas'):
        shutil.copytree(ROOT / rel, folder / rel, ignore=ignore)
    (folder / 'scripts').mkdir()
    shutil.copy2(ROOT / 'scripts/nas_master_data.py', folder / 'scripts/nas_master_data.py')
    shutil.copy2(ROOT / '.dockerignore', folder / '.dockerignore')
    shutil.copy2(ROOT / 'docs/nas-deployment.md', folder / 'DEPLOYMENT.md')
    (folder / 'migration').mkdir(mode=0o700)
    shutil.copy2(args.master_data, folder / 'migration/master-data.json')
    env = dict(SJL_NAS_IP=args.nas_ip, SJL_HTTP_PORT=str(args.port),
               SJL_ALLOWED_ORIGINS=f'http://{args.nas_ip}:{args.port}',
               SJL_ENVIRONMENT='local', SJL_COOKIE_SECURE='false',
               SJL_DB_PASSWORD=secrets.token_hex(32), SJL_REDIS_PASSWORD=secrets.token_hex(32))
    compose = (ROOT / 'infra/nas/compose.yml').read_text()
    def substitute(match):
        name = re.split(r':[-?]', match.group(1))[0]
        return env[name]
    compose = re.sub(r'(?<!\$)\$\{([^}]+)\}', substitute, compose)
    doc = yaml.safe_load(compose)
    for config in [doc['x-app'], *doc['services'].values()]:
        if 'build' in config:
            config['build']['context'] = '.'
        if 'volumes' in config:
            config['volumes'] = [v.replace('../../migration:', './migration:') for v in config['volumes']]
    if args.offline:
        shutil.copytree(ROOT / '.local/nas-deploy/offline/wheels', folder / 'offline/wheels')
        shutil.copytree(ROOT / 'apps/web/dist', folder / 'offline/web-dist')
        doc['x-app']['build']['dockerfile'] = 'infra/nas/api-offline.Dockerfile'
        doc['services']['web']['build']['dockerfile'] = 'infra/nas/web-offline.Dockerfile'
        for name in ('postgres', 'redis'):
            doc['services'][name]['pull_policy'] = 'never'
    # GUI import needs no separate environment-variable setup.
    (folder / 'docker-compose.yaml').write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    os.chmod(folder / 'docker-compose.yaml', 0o600)
    (folder / 'MIGRATION-SUMMARY.json').write_text(json.dumps({
        'kept': {k: len(v) for k, v in payload['tables'].items()},
        'excluded_source_counts': payload['excluded_counts'],
        'url': env['SJL_ALLOWED_ORIGINS'],
    }, ensure_ascii=False, indent=2))
    archive = output / 'sjlerp-nas.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                z.write(path, path.relative_to(output))
    os.chmod(archive, 0o600)
    print(archive)
    print(f'{archive.stat().st_size:,} bytes; master data only, no original .env or operational files')


if __name__ == '__main__':
    main()
