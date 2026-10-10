# -*- coding: utf-8 -*-
"""配置与参数模型测试。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meow.config import AppSettings, ConfigStore  # noqa: E402
from meow.engine.params import CatifyParams  # noqa: E402
from meow.paths import AppPaths  # noqa: E402
from tests.fakes import workspace_temp_dir  # noqa: E402


class TestCatifyParams(unittest.TestCase):
    def test_defaults(self):
        params = CatifyParams()
        self.assertEqual(params.strength, 2)
        self.assertTrue(params.add_tilde)

    def test_clamp_out_of_range(self):
        params = CatifyParams(strength=99, kaomoji_prob=5.0, kaomoji_std=-3.0).clamp()
        self.assertEqual(params.strength, 2)
        self.assertEqual(params.kaomoji_prob, 1.0)
        self.assertEqual(params.kaomoji_std, 0.0)

    def test_clamp_handles_garbage(self):
        params = CatifyParams.from_dict(
            {"strength": "abc", "kaomoji_prob": None, "only_subject_object": "yes"}
        )
        self.assertEqual(params.strength, 2)
        self.assertEqual(params.kaomoji_prob, 0.7)
        self.assertTrue(params.only_subject_object)

    def test_from_dict_ignores_unknown_keys(self):
        params = CatifyParams.from_dict({"nope": 1, "strength": 1})
        self.assertEqual(params.strength, 1)

    def test_roundtrip(self):
        params = CatifyParams(strength=1, kaomoji_interval=4.5, seed=7)
        self.assertEqual(CatifyParams.from_dict(params.to_dict()), params)


class TestAppSettings(unittest.TestCase):
    def test_from_dict_defaults_on_garbage(self):
        settings = AppSettings.from_dict("not a dict")
        self.assertEqual(settings.hotkey, "alt+b")
        self.assertFalse(settings.enabled)

    def test_hotkey_normalised(self):
        self.assertEqual(AppSettings.from_dict({"hotkey": "  ALT+B "}).hotkey, "alt+b")

    def test_empty_hotkey_falls_back(self):
        self.assertEqual(AppSettings.from_dict({"hotkey": "   "}).hotkey, "alt+b")

    def test_nested_catify(self):
        settings = AppSettings.from_dict({"catify": {"strength": 0}})
        self.assertEqual(settings.catify.strength, 0)


class TestConfigStore(unittest.TestCase):
    def setUp(self):
        self._tmp = workspace_temp_dir()
        self.tmp_path = self._tmp.__enter__()
        self.store = ConfigStore(self.tmp_path / "settings.json")

    def tearDown(self):
        self._tmp.__exit__(None, None, None)

    def test_load_missing_returns_defaults(self):
        settings = self.store.load()
        self.assertEqual(settings.hotkey, "alt+b")

    def test_save_then_load(self):
        settings = AppSettings(enabled=True, hotkey="ctrl+shift+m")
        settings.catify.strength = 1
        self.assertTrue(self.store.save(settings))

        loaded = self.store.load()
        self.assertTrue(loaded.enabled)
        self.assertEqual(loaded.hotkey, "ctrl+shift+m")
        self.assertEqual(loaded.catify.strength, 1)

    def test_corrupt_file_falls_back(self):
        self.store.path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(self.store.load().hotkey, "alt+b")

    def test_save_is_atomic_and_leaves_no_temp(self):
        self.store.save(AppSettings())
        leftovers = list(self.store.path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_saved_file_is_readable_json(self):
        self.store.save(AppSettings(enabled=True))
        data = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertTrue(data["enabled"])
        self.assertIn("catify", data)


class TestAppPaths(unittest.TestCase):
    def test_explicit_data_dir_wins(self):
        with workspace_temp_dir() as tmp:
            paths = AppPaths.resolve(tmp)
            self.assertEqual(paths.data_dir, tmp.resolve())

    def test_ensure_creates_directories(self):
        with workspace_temp_dir() as tmp:
            paths = AppPaths(tmp / "nested" / "data").ensure()
            self.assertTrue(paths.log_dir.is_dir())
            self.assertTrue(paths.icon_dir.is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
