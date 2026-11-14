"""Repeatable local QA, no installation, broker login or running-service changes.

Use the repository virtualenv. Explicit tool paths override PATH; selected Node
is prepended to child PATH so pytest and Vite use the same executable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def resolve_tool(name: str, explicit: str | None, env: dict[str, str]) -> str:
    candidate = str(Path(explicit).expanduser().resolve()) if explicit else shutil.which(name, path=env.get('PATH', ''))
    if not candidate or not Path(candidate).is_file():
        raise FileNotFoundError(f'{name} unavailable; supply --{name} with an existing executable')
    return str(Path(candidate).resolve())


def child_environment(parent: dict[str, str], node: Path) -> dict[str, str]:
    env = {k: v for k, v in parent.items() if not k.upper().startswith(('NO7_', 'MT5_'))}
    old = next((k for k in env if k.upper() == 'PATH'), 'PATH')
    path = env.pop(old, '')
    env['PATH'] = str(node.parent) + os.pathsep + path
    return env


def junit_report(path: Path) -> dict:
    tree = ET.parse(path).getroot()
    cases = list(tree.iter('testcase'))
    if not cases:
        raise ValueError('JUnit contains no test cases')
    reasons = Counter()
    for case in cases:
        for skipped in case.findall('skipped'):
            reason = skipped.get('message') or (skipped.text or 'unspecified').strip()
            if any(x in reason.lower() for x in ('no redis-server', 'needs bash', 'node is not installed', 'no .venv')):
                category = 'dependency'
            elif any(x in reason.lower() for x in ('sourced,', 'runs no python', 'creates the venv')):
                category = 'policy'
            else:
                category = 'unclassified'
            reasons[(category, reason)] += 1
    return {'tests': len(cases), 'failures': sum(c.find('failure') is not None for c in cases),
            'errors': sum(c.find('error') is not None for c in cases),
            'skipped': sum(c.find('skipped') is not None for c in cases),
            'skip_reasons': [{'category': k[0], 'reason': k[1], 'count': v} for k, v in sorted(reasons.items())]}


def run_job(name: str, command: list[str], cwd: Path, env: dict[str, str], output: Path, timeout: int) -> dict:
    marker = output / f'{name}.exit'
    marker.write_text('RUNNING', encoding='utf-8')
    code = None
    with (output / f'{name}.log').open('w', encoding='utf-8') as out, (output / f'{name}.err').open('w', encoding='utf-8') as err:
        try:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=out, stderr=err, timeout=timeout)
            code = result.returncode
            status = 'passed' if code == 0 else 'failed'
            terminal = str(code)
        except subprocess.TimeoutExpired:
            status, terminal = 'timeout', 'TIMEOUT'
            err.write('Verification child exceeded the configured timeout.\n')
        except OSError as exc:
            status, terminal = 'error', 'ERROR'
            err.write(f'Cannot execute verification child: {type(exc).__name__}\n')
    marker.write_text(terminal, encoding='utf-8')
    return {'name': name, 'status': status, 'exit_code': code}


def overall_status(jobs: list[dict], junit: dict) -> str:
    if not jobs or any(j['status'] != 'passed' for j in jobs) or junit.get('failures', 0) or junit.get('errors', 0):
        return 'failed'
    return 'passed_with_skips' if junit['skipped'] else 'passed'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', help='Explicit Node executable; otherwise use PATH (no download)')
    parser.add_argument('--git', help='Explicit Git executable; otherwise use PATH')
    parser.add_argument('--output', type=Path, help='New artifact directory; existing directories are refused')
    parser.add_argument('--timeout', type=int, default=900, help='Maximum seconds per child')
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    output = (args.output or ROOT / 'storage/local-dev/qa' / datetime.now(timezone.utc).strftime('verify-%Y%m%dT%H%M%S-%fZ')).resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print('Refusing to overwrite an existing artifact directory.', file=sys.stderr)
        return 2
    summary = {'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running',
               'scope': 'local tests/build only; no Redis/MT5/VM acceptance', 'jobs': [],
               'tools': {'python': sys.executable}, 'junit': None}
    summary_path = output / 'summary.json'

    def save():
        temporary = output / 'summary.tmp'
        temporary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
        temporary.replace(summary_path)

    save()
    try:
        node = resolve_tool('node', args.node, dict(os.environ))
        git = resolve_tool('git', args.git, dict(os.environ))
        env = child_environment(dict(os.environ), Path(node))
        summary['tools'].update(node=node, git=git, bash=shutil.which('bash', path=env['PATH']),
                                redis_server=shutil.which('redis-server', path=env['PATH']))
        if sys.version_info < (3, 11):
            raise ValueError('Python 3.11+ required')
        vite = ROOT / 'apps/web-dashboard/node_modules/vite/bin/vite.js'
        if not vite.is_file():
            raise FileNotFoundError('Dashboard dependencies missing; no automatic installation')
        jobs = [('node-version', [node, '--version'], ROOT),
                ('git-version', [git, '--version'], ROOT),
                ('dependencies', [sys.executable, '-m', 'pip', 'check'], ROOT),
                ('lint', [sys.executable, '-m', 'ruff', 'check', '--select', 'F,E9', '.'], ROOT),
                # Build first: PWA tests inspect the bundle that this run produced.
                ('build', [node, str(vite), 'build'], ROOT / 'apps/web-dashboard'),
                ('tests', [sys.executable, '-m', 'pytest', 'tests', '-q', '-rs', '--tb=short',
                           '-o', 'faulthandler_timeout=180', f'--junitxml={output / "tests.xml"}'], ROOT),
                ('diff', [git, 'diff', '--check'], ROOT)]
        for name, command, cwd in jobs:
            result = run_job(name, command, cwd, env, output, args.timeout)
            summary['jobs'].append(result)
            save()
            if result['status'] != 'passed':
                break
        if any(j['name'] == 'tests' for j in summary['jobs']):
            summary['junit'] = junit_report(output / 'tests.xml')
        summary['status'] = overall_status(summary['jobs'], summary['junit'] or {'skipped': 0})
        if len(summary['jobs']) != len(jobs):
            summary['status'] = 'failed'
    except (OSError, ValueError, ET.ParseError) as exc:
        summary['status'] = 'blocked' if not summary['jobs'] else 'failed'
        summary['error'] = str(exc)
    finally:
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
    print(f"{summary['status']}: {summary_path}")
    return 0 if summary['status'] in ('passed', 'passed_with_skips') else 1


if __name__ == '__main__':
    raise SystemExit(main())