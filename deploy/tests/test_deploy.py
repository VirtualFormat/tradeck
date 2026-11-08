"""tradeck 既有部署入口定点回归，所有 Docker 与 SSH 使用本地替身。"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


DEPLOY = Path(__file__).resolve().parents[1]


class DeployTests(unittest.TestCase):
    def run_ship(self, root, *, state="running healthy 0 30 sha256:test", failure="", selected=("web",)):
        docker = root / "docker"
        docker.write_text('''#!/bin/bash
if [[ "$1 $2" == "image inspect" ]]; then echo sha256:test; fi
exit 0
''')
        docker.chmod(0o755)
        ssh = root / "ssh"
        ssh.write_text('''#!/bin/bash
command="${!#}"
echo "$command" >>"$DEPLOY_PATH/ssh.log"
case "$command" in
  *"config --format json"*)
    printf '%s\n' 'api ghcr.zqg.cc.cd/virtualformat/tradeck-api:latest' 'quant ghcr.zqg.cc.cd/virtualformat/tradeck-quant:latest' 'mcp ghcr.zqg.cc.cd/virtualformat/tradeck-mcp:latest' 'web ghcr.zqg.cc.cd/virtualformat/tradeck-web:latest'
    ;;
  *"image inspect"*) echo sha256:test ;;
  *"State.Status"*)
    [[ "$command" == *"{{.Image}}"* ]] || exit 8
    echo "$HEALTH_STATE"
    ;;
  *" up "*) [[ "$FAILURE" != up ]] || exit 7 ;;
  *"compose ps"*) echo sha256:old ;;
esac
exit 0
''')
        ssh.chmod(0o755)
        sleep = root / "sleep"
        sleep.write_text("#!/bin/bash\nexit 0\n")
        sleep.chmod(0o755)
        env = os.environ | {"DEPLOY_PATH": str(root), "HEALTH_STATE": state, "FAILURE": failure, "PATH": f"{root}:{os.environ['PATH']}"}
        return subprocess.run(["bash", str(DEPLOY / "ship-images.sh"), *selected], env=env, capture_output=True, text=True, timeout=10)

    def test_ship_up_failure_prevents_old_healthy_container_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_ship(root, failure="up")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("compose up 失败", result.stderr)
            self.assertNotIn("State.Status", (root / "ssh.log").read_text())

    def test_ship_exact_image_health_and_existing_default_services(self):
        for state, success in (
            ("running healthy 0 30 sha256:test", True),
            ("running none 0 20 sha256:test", True),
            ("running healthy 0 30 sha256:old", False),
            ("exited healthy 0 30 sha256:test", False),
            ("running healthy 1 30 sha256:test", False),
        ):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result = self.run_ship(root, state=state, selected=())
                self.assertEqual(result.returncode == 0, success, result.stderr)
                rebuilds = [line for line in (root / "ssh.log").read_text().splitlines() if " up " in line]
                self.assertEqual(len(rebuilds), 1)
                self.assertTrue(rebuilds[0].endswith("--force-recreate api quant mcp web"))

    def test_missing_postgres_image_pulls_auth_db(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "deploy"
            scripts.mkdir()
            shutil.copyfile(DEPLOY / "deploy-cn.sh", scripts / "deploy-cn.sh")
            (root / "docker-compose.yml").write_text("services: {auth-db: {image: postgres:16-alpine}}\n")
            (root / ".env").write_text("")
            docker = root / "docker"
            docker.write_text('''#!/bin/bash
echo "$*" >>"$CASE_ROOT/docker.log"
if [[ "$1 $2" == "image inspect" ]]; then exit 1; fi
if [[ "$1" == inspect ]]; then echo healthy; fi
if [[ " $* " == *" ps -q "* ]]; then echo test-api; fi
exit 0
''')
            docker.chmod(0o755)
            curl = root / "curl"
            curl.write_text("#!/bin/bash\nexit 0\n")
            curl.chmod(0o755)
            env = os.environ | {"CASE_ROOT": str(root), "PATH": f"{root}:{os.environ['PATH']}"}
            result = subprocess.run(["bash", str(scripts / "deploy-cn.sh")], env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = (root / "docker.log").read_text()
            self.assertIn(" pull auth-db", log)
            self.assertNotIn(" pull postgres", log)


if __name__ == "__main__":
    unittest.main()
