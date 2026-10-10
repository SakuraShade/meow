# -*- coding: utf-8 -*-
"""服务层测试：一次回车到底发生了什么。

全部使用假后端，不碰真实窗口、剪贴板和键盘。
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meow.config import AppSettings, ConfigStore  # noqa: E402
from meow.engine import CatifyEngine, CatifyParams  # noqa: E402
from meow.events import TOPIC_SETTINGS, TOPIC_STATE, TOPIC_STATS, EventBus  # noqa: E402
from meow.hooks import EnterOutcome  # noqa: E402
from meow.input import TextGateway  # noqa: E402
from meow.service import MeowService, abbreviate  # noqa: E402
from tests.fakes import FakeBackend, workspace_temp_dir  # noqa: E402


class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = workspace_temp_dir()
        tmp_path = self._tmp.__enter__()
        self.store = ConfigStore(tmp_path / "settings.json")
        self.settings = AppSettings(enabled=True)
        self.settings.catify = CatifyParams(strength=1, add_tilde=False, seed=1)
        self.bus = EventBus()
        self.events: list[tuple[str, object]] = []
        for topic in (TOPIC_STATE, TOPIC_SETTINGS, TOPIC_STATS):
            self.bus.subscribe(topic, lambda payload, t=topic: self.events.append((t, payload)))
        self.engine = CatifyEngine()
        self.logger = logging.getLogger("meow.test")
        self.logger.addHandler(logging.NullHandler())

    def tearDown(self):
        self._tmp.__exit__(None, None, None)

    def make_service(self, *backends) -> MeowService:
        gateway = TextGateway(list(backends))
        return MeowService(
            self.settings,
            self.engine,
            gateway,
            bus=self.bus,
            store=self.store,
            logger=self.logger,
        )

    @staticmethod
    def send_recorder():
        calls: list[int] = []

        def send_enter() -> None:
            calls.append(1)

        return calls, send_enter


class TestHandleEnter(ServiceFixture):
    def test_disabled_passes_through_without_touching_field(self):
        self.settings.enabled = False
        backend = FakeBackend("uia", text="你好")
        service = self.make_service(backend)
        outcome = service.handle_enter(lambda: None)
        self.assertIs(outcome, EnterOutcome.PASSTHROUGH)
        self.assertEqual(backend.read_calls, 0)
        self.assertEqual(backend.written, [])

    def test_rewrites_writes_and_sends(self):
        backend = FakeBackend("uia", text="你好")
        service = self.make_service(backend)
        calls, send = self.send_recorder()

        outcome = service.handle_enter(send)
        self.assertIs(outcome, EnterOutcome.SENT)
        self.assertEqual(calls, [1])
        self.assertEqual(len(backend.written), 1)
        self.assertIn("喵", backend.written[0])
        self.assertEqual(service.stats.rewrites, 1)

    def test_passthrough_when_no_backend_reads(self):
        service = self.make_service(FakeBackend("uia"))
        calls, send = self.send_recorder()
        outcome = service.handle_enter(send)
        self.assertIs(outcome, EnterOutcome.PASSTHROUGH)
        self.assertEqual(calls, [])
        self.assertEqual(service.stats.passthrough, 1)

    def test_passthrough_on_blank_field(self):
        backend = FakeBackend("uia", text="   ")
        service = self.make_service(backend)
        outcome = service.handle_enter(lambda: None)
        self.assertIs(outcome, EnterOutcome.PASSTHROUGH)
        self.assertEqual(backend.written, [])

    def test_passthrough_when_write_fails(self):
        backend = FakeBackend("uia", text="你好", can_write=False)
        service = self.make_service(backend)
        calls, send = self.send_recorder()
        outcome = service.handle_enter(send)
        self.assertIs(outcome, EnterOutcome.PASSTHROUGH)
        self.assertEqual(calls, [])
        self.assertEqual(service.stats.failures, 1)

    def test_falls_back_to_second_backend_for_write(self):
        primary = FakeBackend("uia", text="你好", can_write=False)
        fallback = FakeBackend("clipboard", text=None)
        service = self.make_service(primary, fallback)
        outcome = service.handle_enter(lambda: None)
        self.assertIs(outcome, EnterOutcome.SENT)
        self.assertEqual(len(fallback.written), 1)
        self.assertEqual(service.stats.last_backend, "clipboard")

    def test_auto_send_off_swallows_enter(self):
        self.settings.auto_send = False
        backend = FakeBackend("uia", text="你好")
        service = self.make_service(backend)
        calls, send = self.send_recorder()

        outcome = service.handle_enter(send)
        self.assertIs(outcome, EnterOutcome.SWALLOW)
        self.assertEqual(calls, [])
        self.assertEqual(len(backend.written), 1)

    def test_auto_send_off_second_enter_just_sends(self):
        self.settings.auto_send = False
        backend = FakeBackend("uia", text="你好")
        service = self.make_service(backend)

        service.handle_enter(lambda: None)
        rewritten = backend.written[0]

        outcome = service.handle_enter(lambda: None)
        self.assertIs(outcome, EnterOutcome.PASSTHROUGH)
        self.assertEqual(len(backend.written), 1, "第二次回车不应该再次改写")
        self.assertEqual(service.stats.rewrites, 1)
        self.assertIn("喵", rewritten)

    def test_stats_published(self):
        backend = FakeBackend("uia", text="你好")
        service = self.make_service(backend)
        service.handle_enter(lambda: None)
        stats_events = [payload for topic, payload in self.events if topic == TOPIC_STATS]
        self.assertTrue(stats_events)
        self.assertEqual(stats_events[-1]["rewrites"], 1)


class TestStateChanges(ServiceFixture):
    def test_toggle_publishes_state(self):
        self.settings.enabled = False
        service = self.make_service(FakeBackend("uia"))
        self.assertTrue(service.toggle())
        self.assertTrue(service.enabled)
        self.assertIn((TOPIC_STATE, True), self.events)
        self.assertFalse(service.toggle())
        self.assertIn((TOPIC_STATE, False), self.events)

    def test_set_enabled_reports_change(self):
        service = self.make_service(FakeBackend("uia"))
        self.assertTrue(service.enabled, "夹具默认是开启状态")
        self.assertFalse(service.set_enabled(True), "状态没变时应当返回 False")
        self.assertTrue(service.set_enabled(False))
        self.assertFalse(service.set_enabled(False))

    def test_update_catify_clamps_and_publishes(self):
        service = self.make_service(FakeBackend("uia"))
        params = service.update_catify(strength=99, kaomoji_prob=-1)
        self.assertEqual(params.strength, 2)
        self.assertEqual(params.kaomoji_prob, 0.0)
        self.assertTrue(any(topic == TOPIC_SETTINGS for topic, _ in self.events))

    def test_update_app_keeps_catify(self):
        service = self.make_service(FakeBackend("uia"))
        service.update_catify(strength=1)
        settings = service.update_app(auto_send=False)
        self.assertFalse(settings.auto_send)
        self.assertEqual(settings.catify.strength, 1)

    def test_settings_are_persisted(self):
        service = self.make_service(FakeBackend("uia"))
        service.set_enabled(False)
        self.assertTrue(self.store.path.exists())
        self.assertFalse(self.store.load().enabled)

    def test_reset_catify(self):
        service = self.make_service(FakeBackend("uia"))
        service.update_catify(strength=0, add_tilde=False)
        params = service.reset_catify()
        self.assertEqual(params.strength, 2)
        self.assertTrue(params.add_tilde)

    def test_preview_does_not_touch_backends(self):
        backend = FakeBackend("uia", text="你好")
        service = self.make_service(backend)
        result = service.preview("你好")
        self.assertIn("喵", result)
        self.assertEqual(backend.read_calls, 0)
        self.assertEqual(backend.written, [])


class TestHelpers(unittest.TestCase):
    def test_abbreviate_short_text(self):
        self.assertEqual(abbreviate("你好"), "你好")

    def test_abbreviate_flattens_newlines(self):
        self.assertEqual(abbreviate("a\nb"), "a⏎b")

    def test_abbreviate_truncates(self):
        result = abbreviate("x" * 500)
        self.assertEqual(len(result), 120)
        self.assertTrue(result.endswith("…"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
