import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SlopmuxIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / ".bashrc").touch()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.tmux_log = self.root / "tmux-log"
        tmux = self.bin / "tmux"
        tmux.write_text(
            "#!/bin/sh\n"
            "printf '%s\\0' \"$@\" >>\"$SLOPMUX_TEST_TMUX_LOG\"\n"
            "exit \"${SLOPMUX_TEST_TMUX_STATUS:-0}\"\n"
        )
        tmux.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(
            HOME=str(self.home),
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_CONFIG_SYSTEM="/dev/null",
            PATH=f"{self.bin}:/usr/bin:/bin",
            SLOPMUX_TEST_TMUX_LOG=str(self.tmux_log),
        )
        self.checkout_root = self.root / "checkouts"
        self.parent = self.make_repository(self.root / "parent")

    def execute(self, *args, cwd=None, env=None, check=False):
        result = subprocess.run(
            [str(arg) for arg in args],
            cwd=cwd or self.parent,
            env=env or self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and result.returncode:
            self.fail(
                f"command failed ({result.returncode}): {' '.join(map(str, args))}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def git(self, *args, cwd=None, check=True, env=None):
        return self.execute("git", *args, cwd=cwd, check=check, env=env)

    def make_repository(self, path):
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main", cwd=path)
        (path / "README").write_text("initial\n")
        self.git("add", "README", cwd=path)
        self.git(
            "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-q", "-m", "initial", cwd=path,
        )
        self.git("config", "slopmux.baseBranch", "main", cwd=path)
        self.git(
            "config", "slopmux.checkoutRoot", str(self.checkout_root), cwd=path
        )
        return path

    def slopmux(self, command, *args, cwd=None, env=None, check=False):
        return self.execute(ROOT / f"slopmux-{command}", *args, cwd=cwd,
                            env=env, check=check)

    def new(self, name, *args, parent=None, check=True):
        parent = parent or self.parent
        result = self.slopmux("new", name, *args, cwd=parent)
        if check and result.returncode:
            self.fail(result.stderr)
        return result

    def checkout(self, name, parent_name="parent", root=None):
        return (root or self.checkout_root) / parent_name / name

    def startup_contents(self):
        arguments = self.tmux_log.read_bytes().split(b"\0")[:-1]
        shell_command = arguments[-1].decode()
        words = shlex.split(shell_command)
        startup_file = Path(words[words.index("--rcfile") + 1])
        contents = startup_file.read_text()
        startup_file.unlink()
        return contents

    def commit_file(self, repository, filename, contents):
        (repository / filename).write_text(contents)
        self.git("add", filename, cwd=repository)
        self.git(
            "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-q", "-m", filename, cwd=repository,
        )
        return self.git("rev-parse", "HEAD", cwd=repository).stdout.strip()

    def test_create_list_sync_remove_lifecycle_and_independence(self):
        self.new("foo", "--tool", "codex")
        self.new("bar")
        foo = self.checkout("foo")
        bar = self.checkout("bar")
        registry = self.parent / ".git" / "slopmux" / "agents"

        self.assertTrue((foo / ".git").is_dir())
        self.assertTrue((bar / ".git").is_dir())
        self.assertEqual(self.git("remote", cwd=foo).stdout, "")
        self.assertEqual(list((foo / ".git" / "objects" / "info").glob("alternates")), [])
        object_files = [path for path in (foo / ".git" / "objects").rglob("*")
                        if path.is_file()]
        self.assertTrue(object_files)
        self.assertTrue(all(path.stat().st_nlink == 1 for path in object_files))
        self.assertEqual((registry / "foo" / "checkout").read_text().strip(), str(foo))
        self.assertEqual((registry / "foo" / "branch").read_text().strip(), "foo")

        listing = self.slopmux("ls", check=True).stdout
        self.assertIn("foo", listing)
        self.assertIn("codex", listing)
        self.assertEqual(listing.count(" ok "), 2)

        foo_oid = self.commit_file(foo, "foo.txt", "foo\n")
        listing = self.slopmux("ls", check=True).stdout
        self.assertIn("different", listing)
        self.slopmux("sync", "foo", check=True)
        self.assertEqual(
            self.git("rev-parse", "refs/heads/foo").stdout.strip(), foo_oid
        )

        self.git("worktree", "prune", cwd=foo)
        self.git("gc", cwd=foo)
        self.git("config", "agent.only", "yes", cwd=foo)
        self.git("update-ref", "refs/heads/local-only", "HEAD", cwd=foo)
        self.assertNotEqual(
            self.git("config", "--get", "agent.only", check=False).returncode, 0
        )
        self.assertNotEqual(
            self.git("show-ref", "--verify", "refs/heads/local-only", check=False).returncode,
            0,
        )
        self.assertNotEqual(
            self.git("show-ref", "--verify", "refs/heads/local-only", cwd=bar,
                     check=False).returncode,
            0,
        )
        self.git("update-ref", "-d", "refs/heads/local-only", cwd=foo)

        (foo / ".git" / "info" / "exclude").write_text("ignored-output\n")
        (foo / "ignored-output").write_text("disposable\n")

        self.slopmux("rm", "foo", check=True)
        self.assertFalse(foo.exists())
        self.assertFalse((registry / "foo").exists())
        self.assertEqual(
            self.git("rev-parse", "refs/heads/foo").stdout.strip(), foo_oid
        )
        self.slopmux("rm", "--delete-branch", "bar", check=True)
        self.assertNotEqual(
            self.git("show-ref", "--verify", "refs/heads/bar", check=False).returncode,
            0,
        )

    def test_statuses_are_observational(self):
        self.new("foo")
        foo = self.checkout("foo")
        self.commit_file(foo, "ahead", "ahead\n")
        self.assertIn("different", self.slopmux("ls", check=True).stdout)
        parent_before = self.git("rev-parse", "refs/heads/foo").stdout
        self.slopmux("ls", check=True)
        self.assertEqual(self.git("rev-parse", "refs/heads/foo").stdout, parent_before)
        self.git("update-ref", "-d", "refs/heads/foo")
        self.assertIn("unpublished", self.slopmux("ls", check=True).stdout)
        shutil.rmtree(foo)
        self.assertIn("missing", self.slopmux("ls", check=True).stdout)
        self.assertTrue((self.parent / ".git/slopmux/agents/foo").exists())

    def test_fast_forward_only_and_checked_out_parent_branch(self):
        self.new("foo")
        foo = self.checkout("foo")
        self.commit_file(foo, "one", "one\n")
        self.slopmux("sync", "foo", check=True)
        self.git("checkout", "-q", "foo")
        self.commit_file(foo, "two", "two\n")
        refused = self.slopmux("sync", "foo")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("could not fast-forward", refused.stderr)
        self.git("checkout", "-q", "main")

        parent_tip = self.commit_file(self.parent, "parent-only", "parent\n")
        self.git("update-ref", "refs/heads/foo", parent_tip)
        refused = self.slopmux("sync", "foo")
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(
            self.git("rev-parse", "refs/heads/foo").stdout.strip(), parent_tip
        )

    def test_basename_clash_move_and_checkout_root_change(self):
        self.new("old")
        old_checkout = self.checkout("old")
        other_parent = self.make_repository(self.root / "other" / "parent")
        clash = self.new("clash", parent=other_parent, check=False)
        self.assertNotEqual(clash.returncode, 0)
        self.assertIn("belongs to", clash.stderr)

        moved_parent = self.root / "moved" / "parent"
        moved_parent.parent.mkdir()
        self.parent.rename(moved_parent)
        self.parent = moved_parent
        self.new("after-move")
        ownership = self.checkout_root / "parent" / ".slopmux-parent"
        self.assertEqual(ownership.read_text().strip(), str(moved_parent))
        self.assertTrue(old_checkout.exists())
        moved_oid = self.commit_file(old_checkout, "moved.txt", "moved\n")
        self.slopmux("sync", "old", check=True)
        self.assertEqual(
            self.git("rev-parse", "refs/heads/old").stdout.strip(), moved_oid
        )

        new_root = self.root / "new-checkouts"
        self.git("config", "slopmux.checkoutRoot", str(new_root))
        self.new("new-root")
        self.assertTrue(self.checkout("new-root", root=new_root).exists())
        listing = self.slopmux("ls", check=True).stdout
        self.assertIn(str(old_checkout), listing)
        self.assertIn(str(self.checkout("new-root", root=new_root)), listing)

    def test_name_branch_and_base_validation(self):
        for name in ("-bad", "bad/name", "bad name", ".bad"):
            with self.subTest(name=name):
                result = self.new(name, check=False)
                self.assertNotEqual(result.returncode, 0)
        missing = self.new("missing-base", "no-such-branch", check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("base branch does not exist", missing.stderr)
        tag_oid = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("tag", "tag-only", tag_oid)
        tag_base = self.new("tag-base", "tag-only", check=False)
        self.assertNotEqual(tag_base.returncode, 0)
        self.git("branch", "taken")
        collision = self.new("taken", check=False)
        self.assertNotEqual(collision.returncode, 0)
        self.assertIn("parent branch already exists", collision.stderr)

        self.git("config", "slopmux.branchPrefix", "bad prefix/")
        invalid_branch = self.new("branch", check=False)
        self.assertNotEqual(invalid_branch.returncode, 0)
        self.assertIn("invalid assigned branch", invalid_branch.stderr)

        self.git("config", "--unset", "slopmux.branchPrefix")
        dangling = self.checkout("unregistered")
        dangling.parent.mkdir(parents=True, exist_ok=True)
        dangling.symlink_to(self.root / "does-not-exist")
        collision = self.new("unregistered", check=False)
        self.assertNotEqual(collision.returncode, 0)
        self.assertIn("unregistered checkout already exists", collision.stderr)
        self.assertTrue(dangling.is_symlink())

    def test_removal_refusals_preserve_checkout_and_registry(self):
        cases = ("dirty", "detached", "extra", "wrong-head", "missing")
        for name in cases:
            self.new(name)
        checkouts = {name: self.checkout(name) for name in cases}
        (checkouts["dirty"] / "untracked").write_text("dirty\n")
        self.git("checkout", "--detach", "-q", cwd=checkouts["detached"])
        self.git("branch", "extra-ref", cwd=checkouts["extra"])
        self.git("checkout", "-q", "-b", "other", cwd=checkouts["wrong-head"])
        shutil.rmtree(checkouts["missing"])

        result = self.slopmux("rm", *cases)
        self.assertNotEqual(result.returncode, 0)
        for name in cases:
            self.assertTrue((self.parent / f".git/slopmux/agents/{name}").exists())
        for name in cases[:-1]:
            self.assertTrue(checkouts[name].exists())

    def test_removal_refuses_current_directory(self):
        self.new("foo")
        foo = self.checkout("foo")
        environment = self.env.copy()
        environment["GIT_DIR"] = str(self.parent / ".git")
        environment["GIT_WORK_TREE"] = str(self.parent)
        result = self.slopmux("rm", "foo", cwd=foo, env=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("current directory", result.stderr)
        self.assertTrue(foo.exists())

    def test_tmux_failure_keeps_registered_checkout(self):
        environment = self.env.copy()
        environment["SLOPMUX_TEST_TMUX_STATUS"] = "9"
        result = self.slopmux("new", "foo", env=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.checkout("foo").is_dir())
        self.assertTrue((self.parent / ".git/slopmux/agents/foo").is_dir())
        self.assertTrue(self.git("show-ref", "--verify", "refs/heads/foo").returncode == 0)

    def test_agent_uses_native_protections_without_sandbox_command(self):
        result = self.slopmux("new", "--tool", "aider", "foo")

        self.assertEqual(result.returncode, 0, result.stderr)
        startup = self.startup_contents()
        self.assertIn("exec aider\n", startup)
        self.assertNotIn("sandbox", startup)
        self.assertNotIn("dangerously", startup)

        self.git("branch", "claude")
        result = self.slopmux("new", "from-claude", "claude")

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_arguments = self.tmux_log.read_bytes().split(b"\0")[:-1]
        self.assertIn(b"[slop]from-claude", tmux_arguments)
        startup = self.startup_contents()
        self.assertNotIn("exec claude\n", startup)

    def test_configured_sandbox_receives_unmodified_agent_command(self):
        sandbox_policy = self.home / "sandbox policy"
        sandbox_policy.write_text("#!/bin/sh\nexit 0\n")
        sandbox_policy.chmod(0o755)
        self.git("config", "slopmux.sandboxCommand", "~/sandbox policy")

        result = self.slopmux("new", "bar", "-t", "claude")

        self.assertEqual(result.returncode, 0, result.stderr)
        launch_line = self.startup_contents().splitlines()[-1]
        self.assertEqual(
            shlex.split(launch_line),
            ["exec", str(sandbox_policy), "claude"],
        )
        self.assertNotIn("dangerously", launch_line)

    def test_invalid_sandbox_commands_fail_before_tmux(self):
        missing = self.root / "missing"
        sandbox_policy = self.root / "sandbox-policy"
        sandbox_policy.touch()
        relative = self.parent / "relative-policy"
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
                self.git("config", "slopmux.sandboxCommand", str(command))
                result = self.slopmux("new", "-t", "codex", "invalid")

                self.assertEqual(result.returncode, 1)
                self.assertIn(expected_error, result.stderr)
                self.assertFalse(self.tmux_log.exists())

    def test_delete_branch_uses_expected_old_value(self):
        self.new("foo")
        foo = self.checkout("foo")
        self.commit_file(foo, "agent", "agent\n")
        race_environment = self.env.copy()
        race_environment.update(
            GIT_AUTHOR_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="Test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
        )
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        old_parent_tip = self.git("rev-parse", "refs/heads/foo").stdout.strip()
        race_oid = self.git(
            "commit-tree", tree, "-p", old_parent_tip, "-m", "external race",
            env=race_environment,
        ).stdout.strip()
        git_wrapper = self.bin / "git"
        git_wrapper.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = -C ] && [ \"$2\" = \"$SLOPMUX_RACE_PARENT\" ] "
            "&& [ \"$3\" = update-ref ] && [ \"$4\" = -d ]; then\n"
            "  /usr/bin/git -C \"$SLOPMUX_RACE_PARENT\" update-ref \"$5\" "
            "\"$SLOPMUX_RACE_OID\" || exit\n"
            "fi\n"
            "exec /usr/bin/git \"$@\"\n"
        )
        git_wrapper.chmod(0o755)
        race_environment.update(
            SLOPMUX_RACE_PARENT=str(self.parent),
            SLOPMUX_RACE_OID=race_oid,
        )

        result = self.slopmux(
            "rm", "--delete-branch", "foo", env=race_environment
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("parent branch changed", result.stderr)
        self.assertTrue(foo.exists())
        self.assertTrue((self.parent / ".git/slopmux/agents/foo").exists())
        self.assertEqual(
            self.git("rev-parse", "refs/heads/foo", env=race_environment).stdout.strip(),
            race_oid,
        )

    def test_concurrent_creation_and_sync(self):
        commands = [
            [str(ROOT / "slopmux-new"), name] for name in ("one", "two")
        ]
        processes = [
            subprocess.Popen(command, cwd=self.parent, env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for command in commands
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual([result[2] for result in results], [0, 0], results)
        for name in ("one", "two"):
            self.commit_file(self.checkout(name), f"{name}.txt", f"{name}\n")
        processes = [
            subprocess.Popen([str(ROOT / "slopmux-sync"), name], cwd=self.parent,
                             env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
            for name in ("one", "two")
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual([result[2] for result in results], [0, 0], results)


if __name__ == "__main__":
    unittest.main()
