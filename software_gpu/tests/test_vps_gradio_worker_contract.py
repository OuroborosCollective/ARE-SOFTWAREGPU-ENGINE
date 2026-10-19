"""Safety regressions for the optional 3-vCPU ARE worker deployment.

No mutation of real Docker hosts; fail closed on unsafe project-wide cleanup.
"""
import os
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "ops" / "softwaregpu-worker"


class TestWorkerDeploymentContract(unittest.TestCase):
    def test_exact_worker_compose_is_scoped_and_bounded(self):
        config = (WORKER / "compose.yaml").read_text("utf-8")
        self.assertIn('cpus: "3.0"', config)
        self.assertIn('127.0.0.1:17860:7860', config)
        self.assertIn("mem_limit: 3g", config)
        self.assertIn("pids_limit: 96", config)
        self.assertIn("read_only: true", config)
        self.assertIn("cap_drop:", config)
        self.assertIn("no-new-privileges:true", config)
        self.assertIn("tmpfs:", config)
        self.assertIn("ARE_GRADIO_CONTAINER_BIND: \"1\"", config)
        self.assertNotIn("volumes:", config)
        self.assertNotIn("0.0.0.0:7860", config)
        self.assertNotIn("privileged: true", config)

    def test_cleanup_is_owned_and_never_prunes_the_host(self):
        script = (WORKER / "deploy.sh").read_text("utf-8")
        self.assertIn("com.docker.compose.project=are-softwaregpu", script)
        self.assertIn("org.ouroboros.service=are-softwaregpu-worker", script)
        self.assertIn("--remove-orphans", script)
        self.assertIn("docker volume rm", script)
        self.assertNotIn("docker system prune", script)
        self.assertNotIn("docker volume prune", script)
        self.assertNotIn("docker container prune", script)
        self.assertNotIn("docker image prune", script)
        self.assertNotIn("docker rm -f", script)
        self.assertNotIn("docker image rm -f", script)
        self.assertIn("ARE_WORKER_FIRST_INSTALL_ROLLBACK", script)
        self.assertIn("PREEXISTING_CONTAINER", script)
        self.assertIn("BOOT_HEALTHY", script)
        self.assertIn('docker compose -p "${PROJECT}" -f "${CONFIG}" down --remove-orphans', script)

    def test_bind_default_loopback_and_unsafe_external_bind_denied(self):
        from plugins.gradio_arena.app import gradio_server_bind
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gradio_server_bind(), "127.0.0.1")
        with mock.patch.dict(os.environ, {"ARE_GRADIO_SERVER_BIND": "0.0.0.0"}, clear=True):
            with self.assertRaisesRegex(SystemExit, "CONTAINER_BIND_REQUIRED"):
                gradio_server_bind()
        with mock.patch.dict(os.environ, {"ARE_GRADIO_SERVER_BIND": "0.0.0.0",
                                           "ARE_GRADIO_CONTAINER_BIND": "1"}, clear=True):
            self.assertEqual(gradio_server_bind(), "0.0.0.0")
        with mock.patch.dict(os.environ, {"ARE_GRADIO_SERVER_BIND": "example.invalid",
                                           "ARE_GRADIO_CONTAINER_BIND": "1"}, clear=True):
            with self.assertRaisesRegex(SystemExit, "BIND_INVALID"):
                gradio_server_bind()

    def test_no_untagged_or_foreign_project_cleanup_paths(self):
        script = (WORKER / "deploy.sh").read_text("utf-8")
        # A project-specific ephemeral volume or an unused dangling
        # worker-labelled image is the only eligible garbage.
        self.assertIn('label=org.ouroboros.lifecycle=disposable', script)
        self.assertIn('label=org.ouroboros.service=are-softwaregpu-worker', script)
        self.assertIn('label=com.docker.compose.project=are-softwaregpu', script)
        self.assertIn('dangling=true', script)
        self.assertIn('docker ps -aq --filter "ancestor=', script)
        self.assertIn('docker ps -aq --filter "volume=', script)
        self.assertNotIn('docker volume rm -f', script)
        self.assertNotIn('docker compose down -v', script)

    def test_image_source_identity_is_required(self):
        dockerfile = (WORKER / "Dockerfile").read_text("utf-8")
        config = (WORKER / "compose.yaml").read_text("utf-8")
        script = (WORKER / "deploy.sh").read_text("utf-8")
        self.assertIn("org.opencontainers.image.revision", dockerfile)
        self.assertIn("ARE_EXPECTED_SOURCE_SHA", config)
        self.assertIn("ARE_WORKER_SHA_MISMATCH", script)
        self.assertIn("ARE_WORKER_DIRTY_CHECKOUT", script)

    def test_image_contains_no_host_credentials_or_persistent_storage(self):
        dockerfile = (WORKER / "Dockerfile").read_text("utf-8")
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("plugins.gradio_arena.app", dockerfile)
        self.assertNotIn("ARE_GRADIO_PASSWORD=", dockerfile)
        self.assertNotIn("VOLUME ", dockerfile)
        self.assertNotIn("curl | sh", dockerfile)


if __name__ == "__main__":
    unittest.main()
