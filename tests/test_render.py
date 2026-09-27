"""Renderer command construction and failure handling with subprocess mocked."""

import contextlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from legolizer import render


class RenderModelTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "model.mpd"
        self.source.write_text("0 FILE model.mpd\n", encoding="utf-8")
        self.output = self.root / "out" / "render.png"
        for patch in (
            mock.patch.object(render.shutil, "which", lambda name: None),
            mock.patch.object(render, "_app_binary", lambda name: None),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def _run(self, env, side_effect=None, timeout=None):
        def write_output(command, **kwargs):
            self.output.write_bytes(b"png")

        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                render.subprocess, "run", side_effect=side_effect or write_output
            ) as run,
        ):
            render.render_model(self.source, self.output, timeout=timeout)
        return run.call_args

    def test_ldview_command_uses_library_and_absolute_paths(self):
        (self.root / "lib" / "ldraw").mkdir(parents=True)
        call = self._run(
            {"LDVIEW_BIN": "ldview", "LDRAW_LIBRARY_PATH": str(self.root / "lib")}, timeout=120
        )
        command = call.args[0]
        self.assertEqual(command[0], "ldview")
        self.assertEqual(command[1], f"-LDrawDir={self.root / 'lib' / 'ldraw'}")
        self.assertIn(f"-SaveSnapshot={self.output.resolve()}", command)
        self.assertIn("-SaveAlpha=0", command)
        self.assertEqual(command[-1], str(self.source.resolve()))
        self.assertEqual(call.kwargs["timeout"], 120)
        self.assertTrue(call.kwargs["check"])

    def test_transparent_ldview_render_saves_alpha(self):
        env = {"LDVIEW_BIN": "ldview", "LDRAW_LIBRARY_PATH": str(self.root)}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                render.subprocess,
                "run",
                side_effect=lambda *a, **k: self.output.write_bytes(b"png"),
            ) as run,
        ):
            render.render_model(self.source, self.output, transparent=True)
        command = run.call_args.args[0]
        self.assertIn("-SaveAlpha=1", command)
        self.assertNotIn("-SaveAlpha=0", command)

    def test_custom_lpub3d_arguments_are_formatted(self):
        env = {"LPUB3D_BIN": "lpub3d", "LPUB3D_RENDER_ARGS": "--render {input} -o {output}"}
        command = self._run(env).args[0]
        self.assertEqual(command, ["lpub3d", "--render", str(self.source), "-o", str(self.output)])

    def test_missing_or_unconfigured_renderers_fail_before_running(self):
        with mock.patch.object(render.subprocess, "run") as run:
            with mock.patch.dict(os.environ, {"LPUB3D_BIN": "lpub3d"}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "LPUB3D_RENDER_ARGS"):
                    render.render_model(self.source, self.output)
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "Install LDView or LPub3D"):
                    render.render_model(self.source, self.output)
        run.assert_not_called()

    def test_subprocess_failures_become_runtime_errors(self):
        env = {"LDVIEW_BIN": "ldview", "LDRAW_LIBRARY_PATH": str(self.root)}
        cases = [
            (FileNotFoundError(), "executable not found: ldview"),
            (subprocess.TimeoutExpired("ldview", 5), "exceeded 5 seconds"),
            (subprocess.CalledProcessError(1, "ldview", "", " boom \n"), "Renderer failed: boom"),
            (lambda *a, **k: None, "did not create"),
        ]
        for error, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                self._run(env, side_effect=error, timeout=5)


class RenderLocationTests(unittest.TestCase):
    def test_ldraw_dir_prefers_nested_ldraw_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.dict(os.environ, {"LDRAW_LIBRARY_PATH": directory}, clear=True):
                self.assertEqual(render._ldraw_dir(), str(root))
                (root / "ldraw").mkdir()
                self.assertEqual(render._ldraw_dir(), str(root / "ldraw"))

    def test_ldraw_dir_without_config_is_none(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("ldraw.config.Config.load", side_effect=OSError),
        ):
            self.assertIsNone(render._ldraw_dir())

    def test_app_binary_finds_standard_install_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if os.name == "nt":
                binary = root / "LDView" / "LDView64.exe"
                patch = mock.patch.dict(os.environ, {"ProgramFiles": directory}, clear=True)
            else:
                binary = root / "Applications" / "LDView.app" / "Contents" / "MacOS" / "LDView"
                is_file = render.Path.is_file
                patch = contextlib.ExitStack()
                patch.enter_context(mock.patch.object(render.Path, "home", lambda: root))
                # Hide a real /Applications install on the host.
                patch.enter_context(
                    mock.patch.object(
                        render.Path,
                        "is_file",
                        lambda path: path.is_relative_to(root) and is_file(path),
                    )
                )
            with patch:
                self.assertIsNone(render._app_binary("LDView"))
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b"")
                self.assertEqual(render._app_binary("LDView"), str(binary))


if __name__ == "__main__":
    unittest.main()
