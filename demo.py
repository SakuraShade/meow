# -*- coding: utf-8 -*-
"""
Demo: Alt+B 开关 → 拦截 Enter → 处理输入框内容 → 覆写 → 重新发送
兼容: UIA 可读控件(记事本/浏览器) + 自绘控件(微信 4.x 等走剪贴板兜底)
依赖: pip install uiautomation keyboard pyperclip
建议: 以管理员权限运行
"""
import threading
import time

import keyboard
import pyperclip
import uiautomation as auto
import catify

auto.SetGlobalSearchTimeout(0.5)

# ---------------- 状态 ----------------
enabled   = False
_injected = False
_lock     = threading.Lock()


# ---------------- UIA 读写 ----------------
def get_focused():
    try:
        return auto.GetFocusedControl()
    except Exception:
        return None


def get_text_uia(ctl):
    try:
        if ctl.IsValuePatternAvailable():
            return ctl.GetValuePattern().Value
    except Exception:
        pass
    try:
        if ctl.IsTextPatternAvailable():
            return ctl.GetTextPattern().DocumentRange.GetText(-1)
    except Exception:
        pass
    return None


def set_text_uia(ctl, text):
    try:
        if ctl.IsValuePatternAvailable():
            vp = ctl.GetValuePattern()
            if not vp.IsReadOnly:
                vp.SetValue(text)
                return True
    except Exception:
        pass
    return False


# ---------------- 剪贴板兜底 ----------------
def get_text_clipboard():
    """Ctrl+A → Ctrl+C 读焦点输入框内容；读不到返回 None"""
    try:
        backup = pyperclip.paste()
    except Exception:
        backup = ""
    text = None
    try:
        pyperclip.copy("")           # 清空，用来区分“复制成功”和“没复制到”
        time.sleep(0.02)
        keyboard.send('ctrl+a')
        time.sleep(0.03)
        keyboard.send('ctrl+c')
        time.sleep(0.06)
        text = pyperclip.paste()
    except Exception as e:
        print("[剪贴板] 读取异常:", e)
    finally:
        # 恢复用户原有剪贴板
        try:
            pyperclip.copy(backup)
        except Exception:
            pass
    return text


def set_text_clipboard(text):
    """Ctrl+A → Ctrl+V 覆写焦点输入框"""
    try:
        backup = pyperclip.paste()
    except Exception:
        backup = ""
    try:
        pyperclip.copy(text)
        time.sleep(0.02)
        keyboard.send('ctrl+a')
        time.sleep(0.03)
        keyboard.send('ctrl+v')
        time.sleep(0.10)             # 让应用先拿到新内容，再恢复剪贴板
        return True
    except Exception as e:
        print("[剪贴板] 写入异常:", e)
        return False
    finally:
        try:
            pyperclip.copy(backup)
        except Exception:
            pass


# ---------------- 你的处理函数 ----------------
def process_message(text: str) -> str:
    if text is None:
        return ""
    return catify.catify(text.strip(), kaomoji_interval=2)


# ---------------- Alt+B ----------------
def toggle():
    global enabled
    enabled = not enabled
    print(f"\n[Alt+B] 开关 -> {'✅ 开' if enabled else '❌ 关'}")


# ---------------- 核心流程 ----------------
def _handle(ctl):
    """返回 True 表示已处理并已补发 Enter；False 表示需要原样放行"""
    global _injected

    # ① 先试 UIA
    old = None
    via = None
    if ctl is not None:
        old = get_text_uia(ctl)
        if old is not None:
            via = "UIA"

    # ② UIA 读不到，剪贴板兜底
    if old is None:
        old = get_text_clipboard()
        via = "剪贴板" if old is not None else None

    if via is None:
        print("[Enter] 读取失败，原样放行")
        return False

    new = process_message(old)
    print(f"[Enter/方式={via}] 原: {old!r}")
    print(f"[Enter/方式={via}] 新: {new!r}")

    # ③ 写回
    ok = False
    if via == "UIA":
        ok = set_text_uia(ctl, new)
        if not ok:
            print("[Enter] UIA 写入失败，改用剪贴板覆写")
            ok = set_text_clipboard(new)
    else:
        ok = set_text_clipboard(new)

    if not ok:
        print("[Enter] 写入失败，原样放行")
        return False

    # ④ 补发 Enter（此时内容已被替换）
    time.sleep(0.05)
    _injected = True
    keyboard.send('enter')
    time.sleep(0.05)
    _injected = False
    return True


def on_enter(event):
    if getattr(event, "event_type", "down") != "down":
        return True
    if _injected:
        return True
    if not enabled:
        return True
    if not _lock.acquire(blocking=False):
        return False  # 上一次还没处理完，吞掉这次

    def worker():
        try:
            with auto.UIAutomationInitializerInThread(debug=False):
                ctl = get_focused()
                done = _handle(ctl)
                if not done:
                    # 原样放行：补发一次干净的 Enter
                    global _injected
                    _injected = True
                    keyboard.send('enter')
                    _injected = False
        except Exception as e:
            print("[Enter] 线程异常:", e)
        finally:
            _lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return False


# ---------------- 入口 ----------------
if __name__ == "__main__":
    print("=" * 56)
    print("Alt+B  切换开关")
    print("开关开时：按 Enter 会先改写输入框内容，再自动发送")
    print("Ctrl+C 退出")
    print("=" * 56)

    keyboard.add_hotkey('alt+b', toggle)
    keyboard.hook_key('enter', on_enter, suppress=True)

    try:
        keyboard.wait()
    except KeyboardInterrupt:
        print("\n退出")