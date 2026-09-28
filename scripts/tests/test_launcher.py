"""Launcher contract tests. No real Docker, sudo, npm, Python venv or curl in PATH."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

DOCKER = r'''#!/bin/bash
printf 'priv=%s docker %s\n' "${FAKE_PRIV:-0}" "$*" >> "$FAKE_LOG"
case "$1" in
  info)
    [[ ${SCENARIO:-ok} != denied && ${SCENARIO:-ok} != stopped || ${FAKE_PRIV:-0} == 1 ]] || exit 1
    [[ ${SCENARIO:-ok} != stopped || -f "$FAKE_STATE" ]] || exit 1
    exit 0 ;;
  context) echo "${FAKE_CONTEXT:-default}"; exit 0 ;;
  inspect) echo "${FAKE_HEALTH:-healthy}"; exit 0 ;;
  compose)
    shift
    if [[ "$1" == version ]]; then
      [[ ${COMPOSE_KIND:-modern} == modern || ${FAKE_LEGACY:-0} == 1 ]]; exit $?
    fi
    if [[ "$1" == build && ${FAIL_BUILD:-0} == 1 ]]; then exit 23; fi
    if [[ "$1" == up && ${FAIL_UP:-0} == 1 ]]; then exit 24; fi
    if [[ "$1" == run && ${FAIL_TESTS:-0} == 1 ]]; then exit 25; fi
    if [[ "$1" == ps && ${2:-} == -q ]]; then echo "fake-$3"; fi
    exit 0 ;;
esac
exit 1
'''


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.repo = self.root / 'fresh checkout'
        (self.repo / 'scripts').mkdir(parents=True)
        for name in ('astra.sh', 'run.sh', 'build.sh', 'scripts/docker-compose.sh'):
            shutil.copy2(ROOT / name, self.repo / name)
        self.log = self.root / 'calls'
        self.env = {**os.environ, 'PATH': str(self.bin), 'ASTRA_OPEN_BROWSER': '0',
                    'FAKE_LOG': str(self.log), 'FAKE_STATE': str(self.root / 'daemon'),
                    'ASTRA_WAIT_TIMEOUT': '2'}
        for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'COMPOSE_KIND', 'SCENARIO'):
            self.env.pop(key, None)
        self.bin.joinpath('dirname').symlink_to(shutil.which('dirname'))
        self.bin.joinpath('bash').symlink_to('/bin/bash')
        self.script('docker', DOCKER)
        self.script('sleep', '#!/bin/bash\n/bin/sleep 0.05\n')
        self.script('sudo', '''#!/bin/bash
printf 'sudo %s\\n' "$*" >> "$FAKE_LOG"
[[ ${DENY_SUDO:-0} != 1 ]] || exit 1
[[ "$1" != -v ]] || exit 0
[[ "$1" != --preserve-env=* ]] || shift
export FAKE_PRIV=1
exec "$@"
''')
        self.script('systemctl', '#!/bin/bash\nprintf "systemctl %s\\n" "$*" >> "$FAKE_LOG"\n: > "$FAKE_STATE"\n')

    def script(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_script(self, name='astra.sh', args=(), **env):
        return subprocess.run(['/bin/bash', str(self.repo / name), *args],
                              env={**self.env, **env}, cwd=self.root,
                              text=True, capture_output=True, timeout=10)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ''

    def test_default_fresh_checkout_has_no_host_runtime_requirements(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('compose up -d --build', self.calls())
        self.assertNotIn('pytest', self.calls())
        self.assertNotIn('sudo', self.calls())
        self.assertIn('ASTRA готова:', result.stdout)

    def test_quick_lets_compose_build_missing_images(self):
        result = self.run_script('run.sh', ['quick'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('compose up -d\n', self.calls())
        self.assertNotIn('--no-build', self.calls())

    @unittest.skipIf(os.geteuid() == 0, 'sudo fallback applies to unprivileged users')
    def test_socket_permission_fallback_keeps_commands_under_sudo(self):
        result = self.run_script(SCENARIO='denied')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('sudo -v', self.calls())
        self.assertIn('priv=1 docker compose up -d --build', self.calls())
        self.assertNotIn('systemctl', self.calls())

    @unittest.skipIf(os.geteuid() == 0, 'sudo fallback applies to unprivileged users')
    def test_stopped_daemon_is_started_before_compose(self):
        result = self.run_script(SCENARIO='stopped')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('sudo systemctl start docker', self.calls())

    def test_unavailable_custom_context_does_not_switch_daemon(self):
        result = self.run_script(SCENARIO='denied', FAKE_CONTEXT='rootless')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('sudo', self.calls())
        self.assertNotIn('compose up', self.calls())

    @unittest.skipIf(os.geteuid() == 0, 'sudo fallback applies to unprivileged users')
    def test_denied_sudo_stops_without_claiming_success(self):
        result = self.run_script(SCENARIO='denied', DENY_SUDO='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('compose up', self.calls())
        self.assertNotIn('ASTRA готова:', result.stdout)

    def test_legacy_compose(self):
        self.script('docker-compose', '#!/bin/bash\nexport FAKE_LEGACY=1\nexec docker compose "$@"\n')
        result = self.run_script(COMPOSE_KIND='legacy')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_build_checks_run_inside_containers(self):
        result = self.run_script('build.sh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('backend python -m pytest tests -q', self.calls())
        self.assertIn('frontend sh -ec npm run build && npm run lint && npm test', self.calls())
        self.assertNotIn('--seed', self.calls())

    def test_failures_propagate_and_never_report_ready(self):
        for args, setting in (([], 'FAIL_UP'), (['check'], 'FAIL_BUILD'), (['check'], 'FAIL_TESTS')):
            with self.subTest(setting=setting):
                result = self.run_script(args=args, **{setting: '1'})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('ASTRA готова:', result.stdout)
                self.assertNotIn('Проверки ASTRA завершены успешно.', result.stdout)

    def test_health_wait_has_deadline_and_diagnostics(self):
        result = self.run_script(FAKE_HEALTH='starting', ASTRA_WAIT_TIMEOUT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('compose logs --tail=30', self.calls())


if __name__ == '__main__':
    unittest.main()
