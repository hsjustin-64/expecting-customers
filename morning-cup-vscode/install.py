"""Install a separate environment on each Windows x64 computer."""
from pathlib import Path
import hashlib, json, os, platform, subprocess, sys, venv

def main():
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64') or sys.maxsize <= 2**32:
        raise RuntimeError('This installer requires Windows x64 and 64-bit Python.')
    if not (3, 10) <= sys.version_info[:2] <= (3, 12):
        raise RuntimeError('Install Python 3.10, 3.11 or 3.12 (64-bit), then run install.bat again.')
    root = Path(__file__).resolve().parent
    # Prophet bundles long Stan paths; keep the venv out of deep project folders.
    env_root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MCup'
    target = env_root / hashlib.sha256(str(root).encode()).hexdigest()[:12]
    venv.EnvBuilder(with_pip=True).create(target)
    python = target / 'Scripts' / 'python.exe'
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL', 'PIP_NO_INDEX', 'PIP_FIND_LINKS'):
        env.pop(key, None)
    env['PIP_CONFIG_FILE'] = os.devnull
    subprocess.run([str(python), '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple',
                    '--only-binary=:all:', '-r', str(root / 'requirements-demo.txt')], env=env, check=True)
    subprocess.run([str(python), str(root / 'check_environment.py')], cwd=root, env=env, check=True)
    (root / '.python-path').write_text(str(python), encoding='utf-8')
    settings_path = root / '.vscode' / 'settings.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
    settings['python.defaultInterpreterPath'] = str(python)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    launch_path = root / '.vscode' / 'launch.json'
    launch = json.loads(launch_path.read_text(encoding='utf-8-sig'))
    for entry in launch['configurations']:
        entry['python'] = str(python)
    launch_path.write_text(json.dumps(launch, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Environment:', target)
    print('Installation and actual Prophet prediction passed. Use F5 or start-backend.bat.')

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Installation failed: {exc}', file=sys.stderr)
        sys.exit(1)
