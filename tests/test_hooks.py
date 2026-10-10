# -*- coding: utf-8 -*-
"""键盘钩子测试：拦截、放行、补发 Enter 的时机。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meow.hooks import EnterHook, EnterOutcome  # noqa: E402
from tests.fakes import FakeListener, SynchronousThread  # noqa: E402


def make_hook(handler, gate=None, listener=None):
    listener = listener or FakeListener()
    hook = EnterHook(
        handler,
        gate=gate or (lambda: True),
        listener=listener,
        thread_factory=SynchronousThread,
    )
    return hook, listener


class TestInstallAndUninstall(unittest.TestCase):
    def test_start_registers_enter_and_hotkey(self):
        hook, listener = make_hook(lambda send: EnterOutcome.PASSTHROUGH)
        hook.start(hotkey="alt+b", on_hotkey=lambda: None)

        self.assertIn("enter", listener.hooks)
        self.assertTrue(listener.hooks["enter"]["suppress"])
        self.assertIn("alt+b", listener.hotkeys)
        self.assertTrue(hook.running)

    def test_stop_unhooks_everything(self):
        hook, listener = make_hook(lambda send: EnterOutcome.PASSTHROUGH)
        hook.start(hotkey="alt+b", on_hotkey=lambda: None)
        hook.stop()

        self.assertEqual(len(listener.unhooked), 1)
        self.assertEqual(len(listener.removed_hotkeys), 1)
        self.assertFalse(hook.running)

    def test_stop_is_safe_without_start(self):
        hook, _ = make_hook(lambda send: EnterOutcome.PASSTHROUGH)
        hook.stop()
        self.assertFalse(hook.running)

    def test_start_twice_unhooks_first(self):
        hook, listener = make_hook(lambda send: EnterOutcome.PASSTHROUGH)
        hook.start()
        hook.start()
        self.assertEqual(len(listener.unhooked), 1)


class TestGate(unittest.TestCase):
    def test_gate_closed_passes_key_through_untouched(self):
        calls: list[int] = []
        hook, listener = make_hook(lambda send: calls.append(1) or EnterOutcome.SENT, gate=lambda: False)
        hook.start()

        allowed = listener.fire_enter()
        self.assertTrue(allowed, "功能关闭时必须原样放行，不能吞键")
        self.assertEqual(calls, [])

    def test_gate_open_suppresses_key(self):
        hook, listener = make_hook(lambda send: EnterOutcome.PASSTHROUGH)
        hook.start()
        self.assertFalse(listener.fire_enter())


class TestOutcomes(unittest.TestCase):
    def test_sent_outcome_does_not_resend(self):
        def handler(send_enter):
            send_enter()
            return EnterOutcome.SENT

        hook, listener = make_hook(handler)
        hook.start()
        listener.fire_enter()
        self.assertEqual(listener.sent, ["enter"])

    def test_passthrough_resends_clean_enter(self):
        hook, listener = make_hook(lambda send: EnterOutcome.PASSTHROUGH)
        hook.start()
        listener.fire_enter()
        self.assertEqual(listener.sent, ["enter"])

    def test_swallow_sends_nothing(self):
        hook, listener = make_hook(lambda send: EnterOutcome.SWALLOW)
        hook.start()
        listener.fire_enter()
        self.assertEqual(listener.sent, [])

    def test_handler_exception_still_passes_through(self):
        def boom(send_enter):
            raise RuntimeError("炸了")

        hook, listener = make_hook(boom)
        hook.start()
        listener.fire_enter()
        self.assertEqual(listener.sent, ["enter"], "异常时也应该把回车还给用户")


class TestReentrancy(unittest.TestCase):
    def test_injected_enter_is_ignored(self):
        calls: list[str] = []

        def handler(send_enter):
            calls.append("handled")
            send_enter()  # 补发的那次应该被钩子忽略
            return EnterOutcome.SENT

        listener = FakeListener()
        hook, _ = make_hook(handler, listener=listener)
        hook.start()

        # send_enter 内部会调用 listener.send，这里模拟那次 send 触发钩子
        original_send = listener.send

        def send_and_replay(keys):
            original_send(keys)
            listener.fire_enter()

        listener.send = send_and_replay
        listener.fire_enter()

        self.assertEqual(calls, ["handled"], "补发的 Enter 不能被再次处理")

    def test_key_up_events_pass_through(self):
        hook, listener = make_hook(lambda send: EnterOutcome.SENT)
        hook.start()
        self.assertTrue(listener.fire_enter(event_type="up"))

    def test_busy_lock_swallows_concurrent_enter(self):
        # 用不会自动结束的假线程模拟「上一次还没处理完」
        class BlockingThread(SynchronousThread):
            def start(self):
                self.started = True  # 故意不执行 target

        listener = FakeListener()
        hook = EnterHook(
            lambda send: EnterOutcome.SENT,
            gate=lambda: True,
            listener=listener,
            thread_factory=BlockingThread,
        )
        hook.start()

        self.assertFalse(listener.fire_enter(), "第一次回车被吞掉进入处理")
        self.assertFalse(listener.fire_enter(), "处理中再次回车也应该被吞掉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
