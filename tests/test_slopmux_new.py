import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def git_environment():
    environment = os.environ.copy()
    environment["GIT_CONFIG_GLOBAL"] = "/dev/null"
    environment["GIT_CONFIG_SYSTEM"] = "/dev/null"
    return environment


class SlopmuxNewTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / ".bashrc").touch()
        self.binary_directory = self.root / "bin"
        self.binary_directory.mkdir()
        self.capture = self.root / "tmux-arguments"
        tmux = self.binary_directory / "tmux"
        tmux.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\0' \"$@\" >\"$SLOPMUX_TEST_CAPTURE\"\n"
        )
        tmux.chmod(0o755)
        self.environment = git_environment()
        self.environment["HOME"] = str(self.home)
        self.environment["SLOPMUX_TEST_CAPTURE"] = str(self.capture)
        self.environment["PATH"] = f"{self.binary_directory}:/usr/bin:/bin"
        self.git("init", "-q", "-b", "master")
        (self.repository / "README").touch()
        self.git("add", "README")
        self.git(
            "-c",
            "user.name=Slopmux Test",
            "-c",
            "user.email=slopmux@example.invalid",
            "commit",
            "-q",
            "-m",
            "initial",
        )
        self.git(
            "config",
            "slopmux.worktreeRoot",
            str(self.root / "worktrees"),
        )

    def git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.repository,
            env=self.environment,
            check=True,
        )

    def startup_contents(self):
        arguments = self.capture.read_bytes().split(b"\0")[:-1]
        shell_command = arguments[-1].decode()
        words = shlex.split(shell_command)
        startup_file = Path(words[words.index("--rcfile") + 1])
        contents = startup_file.read_text()
        startup_file.unlink()
        return contents

    def run_slopmux_new(self, *arguments):
        return subprocess.run(
            [ROOT / "slopmux-new", *arguments],
            cwd=self.repository,
            env=self.environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def configure_sandbox(self, value):
        self.git("config", "slopmux.sandboxCommand", str(value))

    def test_agent_uses_native_protections_without_sandbox_command(self):
        result = self.run_slopmux_new("--tool", "aider", "foo")

        self.assertEqual(result.returncode, 0, result.stderr)
        startup = self.startup_contents()
        self.assertIn("exec aider\n", startup)
        self.assertNotIn("sandbox", startup)
        self.assertNotIn("dangerously", startup)

        self.git("branch", "claude")
        result = self.run_slopmux_new("from-claude", "claude")

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_arguments = self.capture.read_bytes().split(b"\0")[:-1]
        self.assertIn(b"[slop]from-claude", tmux_arguments)
        startup = self.startup_contents()
        self.assertNotIn("exec claude\n", startup)

    def test_configured_sandbox_receives_unmodified_agent_command(self):
        sandbox_policy = self.home / "sandbox policy"
        sandbox_policy.write_text("#!/bin/sh\nexit 0\n")
        sandbox_policy.chmod(0o755)
        self.configure_sandbox("~/sandbox policy")

        result = self.run_slopmux_new("bar", "-t", "claude")

        self.assertEqual(result.returncode, 0, result.stderr)
        startup = self.startup_contents()
        launch_line = startup.splitlines()[-1]
        self.assertEqual(
            shlex.split(launch_line),
            ["exec", str(sandbox_policy), "claude"],
        )
        self.assertNotIn("dangerously", startup)

    def test_invalid_sandbox_commands_fail_before_tmux(self):
        missing = self.root / "missing"
        sandbox_policy = self.root / "sandbox-policy"
        sandbox_policy.touch()
        relative = self.repository / "relative-policy"
        relative.write_text("#!/bin/sh\nexit 0\n")
        relative.chmod(0o755)
        cases = (
            (missing, f"sandbox command does not exist: {missing}"),
            (
                sandbox_policy,
                f"sandbox command is not executable: {sandbox_policy}",
            ),
            (
                "relative-policy",
                "slopmux.sandboxCommand must be an absolute path",
            ),
        )

        for command, expected_error in cases:
            with self.subTest(command=command):
                self.configure_sandbox(command)
                result = self.run_slopmux_new("-t", "codex", "invalid")

                self.assertEqual(result.returncode, 1)
                self.assertIn(expected_error, result.stderr)
                self.assertFalse(self.capture.exists())


if __name__ == "__main__":
    unittest.main()
