# -*- coding: utf-8 -*-
"""输入后端与网关测试（用假后端，不需要真实窗口）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meow.input import ClipboardBackend, ClipboardTiming, NullBackend, TextGateway  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeBackend,
    FakeClipboard,
    FakeKeyboard,
    SessionBackend,
)


class TestTextGatewayRead(unittest.TestCase):
    def test_returns_first_successful_backend(self):
        first = FakeBackend("first", text="hello")
        second = FakeBackend("second", text="world")
        gateway = TextGateway([first, second])

        field = gateway.read()
        self.assertIsNotNone(field)
        self.assertEqual(field.text, "hello")
        self.assertEqual(field.backend_name, "first")
        self.assertEqual(second.read_calls, 0)

    def test_falls_back_when_first_returns_none(self):
        first = FakeBackend("first", text=None)
        second = FakeBackend("second", text="world")
        gateway = TextGateway([first, second])

        field = gateway.read()
        self.assertEqual(field.backend_name, "second")
        self.assertEqual(first.read_calls, 1)

    def test_returns_none_when_all_fail(self):
        gateway = TextGateway([FakeBackend("a"), FakeBackend("b")])
        self.assertIsNone(gateway.read())

    def test_exception_does_not_stop_fallback(self):
        broken = FakeBackend("broken", read_error=RuntimeError("boom"))
        working = FakeBackend("working", text="ok")
        gateway = TextGateway([broken, working])
        self.assertEqual(gateway.read().backend_name, "working")

    def test_empty_text_is_returned_as_field(self):
        gateway = TextGateway([FakeBackend("a", text="   "), FakeBackend("b", text="x")])
        field = gateway.read()
        self.assertEqual(field.text, "   ")
        self.assertEqual(field.backend_name, "a")

    def test_requires_at_least_one_backend(self):
        with self.assertRaises(ValueError):
            TextGateway([])


class TestTextGatewayWrite(unittest.TestCase):
    def test_prefers_backend_that_read(self):
        first = FakeBackend("first", text="old")
        second = FakeBackend("second", text="old")
        gateway = TextGateway([first, second])
        field = gateway.read()

        ok, used = gateway.write(field, "new")
        self.assertTrue(ok)
        self.assertEqual(used, "first")
        self.assertEqual(first.written, ["new"])
        self.assertEqual(second.written, [])

    def test_falls_back_when_write_fails(self):
        first = FakeBackend("first", text="old", can_write=False)
        second = FakeBackend("second", text=None)
        gateway = TextGateway([first, second])
        field = gateway.read()

        ok, used = gateway.write(field, "new")
        self.assertTrue(ok)
        self.assertEqual(used, "second")
        self.assertEqual(second.written, ["new"])

    def test_reports_failure_when_nothing_works(self):
        backend = FakeBackend("only", text="old", can_write=False)
        gateway = TextGateway([backend])
        field = gateway.read()
        ok, used = gateway.write(field, "new")
        self.assertFalse(ok)
        self.assertEqual(used, "only")

    def test_write_exception_is_contained(self):
        broken = FakeBackend("broken", text="old", write_error=RuntimeError("boom"))
        backup = FakeBackend("backup", text=None)
        gateway = TextGateway([broken, backup])
        field = gateway.read()

        ok, used = gateway.write(field, "new")
        self.assertTrue(ok)
        self.assertEqual(used, "backup")


class TestSessionComposition(unittest.TestCase):
    def test_nested_sessions_are_entered_and_exited(self):
        first = SessionBackend("first", text="a")
        plain = FakeBackend("plain", text=None)
        gateway = TextGateway([first, plain])

        with gateway.session():
            self.assertEqual(first.entered, 1)

        self.assertEqual(first.exited, 1)

    def test_broken_session_does_not_break_others(self):
        class BrokenSession(FakeBackend):
            def session(self):
                raise RuntimeError("no com for you")

        good = SessionBackend("good", text="a")
        gateway = TextGateway([BrokenSession("broken"), good])
        with gateway.session():
            self.assertEqual(good.entered, 1)


class TestNullBackend(unittest.TestCase):
    def test_always_fails(self):
        backend = NullBackend()
        self.assertIsNone(backend.read())
        self.assertFalse(backend.write("x"))


class TestClipboardBackend(unittest.TestCase):
    def make(self, source_text: str, echoed: bool = True):
        clipboard = FakeClipboard("原有的剪贴板内容")
        keyboard = FakeKeyboard(clipboard, copied=source_text, echo=echoed)
        backend = ClipboardBackend(
            clipboard=clipboard,
            keyboard=keyboard,
            timing=ClipboardTiming(0, 0, 0, 0),
        )
        return backend, clipboard, keyboard

    def test_read_returns_copied_text(self):
        backend, clipboard, keyboard = self.make("输入框里的内容")
        self.assertEqual(backend.read(), "输入框里的内容")
        self.assertEqual(keyboard.sent, ["ctrl+a", "ctrl+c"])

    def test_read_restores_previous_clipboard(self):
        backend, clipboard, _ = self.make("abc")
        backend.read()
        self.assertEqual(clipboard.content, "原有的剪贴板内容")

    def test_read_returns_none_when_app_cannot_copy(self):
        # 应用不支持 Ctrl+C —— 旧实现会误判成「读到空字符串」，
        # 然后清空输入框并回车；现在必须返回 None 触发原样放行
        backend, clipboard, _ = self.make("", echoed=False)
        self.assertIsNone(backend.read())
        self.assertEqual(clipboard.content, "原有的剪贴板内容")

    def test_read_returns_none_on_exception(self):
        class Exploding:
            def send(self, keys):
                raise RuntimeError("boom")

            def copy(self, text):
                pass

            def paste(self):
                return ""

        backend = ClipboardBackend(
            clipboard=Exploding(),
            keyboard=Exploding(),
            timing=ClipboardTiming(0, 0, 0, 0),
        )
        self.assertIsNone(backend.read())

    def test_write_sends_select_all_and_paste(self):
        backend, clipboard, keyboard = self.make("旧内容")
        self.assertTrue(backend.write("新内容"))
        self.assertEqual(keyboard.sent, ["ctrl+a", "ctrl+v"])
        self.assertEqual(clipboard.content, "原有的剪贴板内容")

    def test_write_returns_false_when_keyboard_fails(self):
        class Exploding:
            def send(self, keys):
                raise RuntimeError("boom")

            def copy(self, text):
                pass

            def paste(self):
                return ""

        backend = ClipboardBackend(
            clipboard=Exploding(),
            keyboard=Exploding(),
            timing=ClipboardTiming(0, 0, 0, 0),
        )
        self.assertFalse(backend.write("x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
