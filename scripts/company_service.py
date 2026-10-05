"""Start, inspect, restart or stop a company using its own deployment settings."""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.company_runtime_backup import Deployment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', type=Path, required=True)
    parser.add_argument('action', choices=['start', 'status', 'restart', 'stop'])
    args = parser.parse_args()
    commands = {'start': ('up', '-d'), 'status': ('ps', '--all'),
                'restart': ('restart',), 'stop': ('stop',)}
    print('Running company service command...', flush=True)
    try:
        deployment = Deployment(args.deployment)
        result = deployment.compose(*commands[args.action])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        if args.action == 'stop':
            parser.exit(1, 'Stop failed; shutdown is not confirmed. Check Docker Desktop and the deployment '
                           'directory, then retry stop and inspect status. Retain existing data.\n')
        parser.exit(1, 'Service command failed. Check Docker Desktop, the deployment directory and its .env; '
                       'retain existing data and run check_company_deployment.py for diagnostics.\n')
    if args.action == 'status':
        print(result.stdout.decode('utf-8', errors='replace'))
    elif args.action == 'stop':
        print('Company containers stopped. Data and volumes retained. '
              'Shared Ollama and Docker Desktop remain running; see the SOP for host cleanup.')
    else:
        print('Command completed. Run check_company_deployment.py before login or acceptance.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
