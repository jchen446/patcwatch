"""Install the Microsoft monitor as a per-user macOS LaunchAgent."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = 'com.patcwatch.monitor'


def definition(data, port, interval, executable=None):
    return {'Label': LABEL,
            'ProgramArguments': [executable or sys.executable, '-m', 'patcwatch', '--microsoft',
                                 '--data-dir', str(data), '--port', str(port), '--interval', str(interval)],
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 30,
            'WorkingDirectory': str(data), 'Umask': 0o077,
            'StandardOutPath': str(data / 'service.stdout.log'),
            'StandardErrorPath': str(data / 'service.stderr.log')}


def manage(action, data, port, interval):
    if sys.platform != 'darwin':
        raise ValueError('Automatic background installation currently supports macOS. See README for other operating systems.')
    path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    domain = 'gui/' + str(os.getuid())
    target = domain + '/' + LABEL
    if action == 'status':
        result = subprocess.run(['launchctl', 'print', target], capture_output=True, text=True)
        print(result.stdout if result.returncode == 0 else 'Patcwatch background service is not loaded.')
        return
    if action == 'uninstall':
        if path.exists():
            subprocess.run(['launchctl', 'bootout', target], capture_output=True)
            path.unlink()
        print('Background service removed. Private state and Microsoft credentials retained.')
        return
    if path.exists():
        raise ValueError('Background service already installed; use --background uninstall before reinstalling.')
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        plistlib.dump(definition(data, port, interval), stream)
    path.chmod(0o600)
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True, text=True)
    if result.returncode:
        path.unlink()
        raise ValueError('Could not load LaunchAgent. Run from your signed-in macOS user session.')
    print('Installed Patcwatch background service at http://127.0.0.1:' + str(port))
    print('Runs while signed in and awake. Check --background status; uninstall with --background uninstall.')
