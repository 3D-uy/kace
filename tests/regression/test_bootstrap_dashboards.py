"""Execute dashboard provisioning against a sandbox, never the host services."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.regression.test_bootstrap_minimal_mutation import _find_bash


BOOTSTRAP = Path(__file__).resolve().parents[2] / "scripts/bootstrap.sh"


@unittest.skipUnless(_find_bash(), "bash is required")
class TestBootstrapDashboards(unittest.TestCase):
    def run_provisioning(self, dashboard, prebaked, *, nginx_failure=False, download_failure=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Bash resolves the sandbox path itself, including on Windows.
            script = BOOTSTRAP.read_text(encoding="utf-8")
            packages = script.split('# ── 2. System Packages', 1)[1].split('# ── 3. Klipper', 1)[0]
            ui = script.split('# ── 6. Dashboard UI', 1)[1].split('# ── 9. Patch Systemd', 1)[0]
            # Drop the remainder of the heading, retaining the actual executable sections.
            sections = packages.split('\n', 1)[1] + ui.split('\n', 1)[1]
            sections = sections.replace('/etc/nginx', '${TEST_ROOT}/nginx').replace('/var/www', '${TEST_ROOT}/www')
            harness = r'''
set -e
TEST_ROOT=$(cd "$1" && pwd)
PREBAKED="$2" DASHBOARD="$3"
PRINTER_HOME="$TEST_ROOT/home" PRINTER_USER=test PRINTER_GROUP=test SUDO=""
MAINSAIL_URL=mainsail MAINSAIL_SHA256=mainsail-hash
FLUIDD_URL=fluidd FLUIDD_SHA256=fluidd-hash
MAINSAIL_CONFIG_URL=mainsail-config MAINSAIL_CONFIG_SHA256=mainsail-config-hash
FLUIDD_CONFIG_URL=fluidd-config FLUIDD_CONFIG_SHA256=fluidd-config-hash
log_stage() { echo "stage:$1"; }
log_ok() { :; }
log_err() { echo "$*"; }
wait_for_apt_locks() { :; }
apt-get() { echo "apt:$*"; }
chown() { :; }
systemctl() { echo "service:$*"; return 1; }
install_verified_dashboard() {
    echo "install:$1:$2:$3"
    if [ "${FAIL_DOWNLOAD:-0}" = 1 ]; then return 7; fi
    mkdir -p "$5"
    echo dashboard > "$5/index.html"
}
download_verified_file() { echo config > "$3"; }
nginx() {
    echo "nginx:$*"
    test ! -e "$TEST_ROOT/nginx/sites-enabled/mainsail"
    test "${FAIL_NGINX:-0}" != 1
}
mkdir -p "$PRINTER_HOME/printer_data/config" "$PRINTER_HOME/mainsail" \
    "$TEST_ROOT/nginx/sites-available" "$TEST_ROOT/nginx/sites-enabled"
echo vendor > "$TEST_ROOT/nginx/sites-available/mainsail"
if [ "$PREBAKED" = true ]; then
    ln -s "$TEST_ROOT/nginx/sites-available/mainsail" "$TEST_ROOT/nginx/sites-enabled/mainsail"
    if [ ! -L "$TEST_ROOT/nginx/sites-enabled/mainsail" ]; then exit 77; fi
fi
# The conflict probe above must fail; the configured service restart must succeed.
systemctl() { echo "service:$*"; test "$1" = restart; }
'''
            runner = root / 'runner.sh'
            runner.write_text(harness + sections, encoding='utf-8', newline='\n')
            environment = dict(os.environ, MSYS='winsymlinks:sys', FAIL_NGINX=str(int(nginx_failure)), FAIL_DOWNLOAD=str(int(download_failure)))
            result = subprocess.run(
                [_find_bash(), runner.as_posix(), root.as_posix(), str(prebaked).lower(), dashboard],
                capture_output=True, text=True, env=environment, timeout=20,
            )
            if result.returncode == 77:
                self.skipTest('Bash symlinks are unavailable on this host')
            config = root / 'nginx/sites-available/kace-printer'
            return result, config.read_text() if config.exists() else '', (root / 'nginx/sites-enabled/mainsail').exists(), (root / 'nginx/sites-available/mainsail').read_text()

    def test_fluidd_installs_on_prebaked_base_and_owns_port_80(self):
        result, config, vendor_enabled, vendor = self.run_provisioning('fluidd', True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('install -y git unzip file', result.stdout)
        self.assertIn('install:Fluidd:fluidd:fluidd-hash', result.stdout)
        self.assertNotIn('install:Mainsail', result.stdout)
        self.assertIn('listen 80 default_server;', config)
        self.assertIn('/www/fluidd;', config)
        self.assertIn('proxy_pass http://kace_apiserver;', config)
        self.assertNotIn('listen 81', config)
        self.assertFalse(vendor_enabled)
        self.assertEqual(vendor, 'vendor\n')
        self.assertIn('nginx:-t', result.stdout)
        self.assertIn('service:restart nginx', result.stdout)

    def test_both_preserves_preinstalled_mainsail_location(self):
        result, config, _, _ = self.run_provisioning('both', True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('/home/mainsail;', config)
        self.assertIn('/www/fluidd;', config)
        self.assertIn('listen 81 default_server;', config)

    def test_mainsail_prebaked_preserves_vendor_site(self):
        result, config, vendor_enabled, _ = self.run_provisioning('mainsail', True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('install:', result.stdout)
        self.assertEqual(config, '')
        self.assertTrue(vendor_enabled)

    def test_vanilla_still_installs_requested_dashboards(self):
        for dashboard in ('mainsail', 'fluidd', 'both'):
            with self.subTest(dashboard=dashboard):
                result, config, _, _ = self.run_provisioning(dashboard, False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for name in ('mainsail', 'fluidd'):
                    self.assertEqual(f'install:{name.title()}' in result.stdout, dashboard in (name, 'both'))
                self.assertIn('listen 80 default_server;', config)

    def test_nginx_failure_restores_vendor_site_and_never_restarts(self):
        result, _, vendor_enabled, _ = self.run_provisioning('fluidd', True, nginx_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(vendor_enabled)
        self.assertNotIn('service:restart nginx', result.stdout)

    def test_download_failure_stops_before_nginx(self):
        result, config, vendor_enabled, _ = self.run_provisioning('fluidd', True, download_failure=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(config, '')
        self.assertTrue(vendor_enabled)

    def test_fluidd_cannot_complete_after_nginx_startup_failure(self):
        script = BOOTSTRAP.read_text(encoding='utf-8')
        services = script.split('# ── 10. Start Services', 1)[1].split(
            'if [ "$POWER_RELAY" = "true" ]; then', 1,
        )[0].split('\n', 1)[1]
        harness = r'''
set -e
PREBAKED=true DASHBOARD=fluidd SUDO="" MOONRAKER_CONFIG=unused
log_stage() { :; }
log_ok() { :; }
log_err() { echo "$*"; }
verify_requested_power_relay() { :; }
systemctl() {
    if [ "${!#}" = nginx ] && [ "$1" = "$FAIL_OPERATION" ]; then return 1; fi
}
'''
        for operation in ('restart', 'is-active'):
            with self.subTest(operation=operation):
                result = subprocess.run(
                    [_find_bash(), '-c', harness + services + '\necho completed'],
                    capture_output=True, text=True, timeout=10,
                    env=dict(os.environ, FAIL_OPERATION=operation),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('completed', result.stdout)


if __name__ == '__main__':
    unittest.main()
