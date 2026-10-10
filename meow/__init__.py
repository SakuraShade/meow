"""meow —— 按 Enter 自动把输入框文本「猫娘化」的 Windows 桌面小工具。

包结构（自下而上，每层只依赖它下面的层）::

    meow.engine    纯文本改写引擎：无 IO、无全局状态，可单独测试
    meow.config    配置模型与 JSON 持久化
    meow.input     输入框读写后端（UIAutomation / 剪贴板兜底）
    meow.hooks     键盘钩子（Enter 拦截、全局快捷键）
    meow.tray      Windows 通知区域（托盘）图标
    meow.ui        Tkinter 图形界面
    meow.service   业务编排：把上面几层粘起来
    meow.bootstrap 组装依赖（依赖注入的集中点）

设计原则：
1. **引擎与平台解耦** —— ``meow.engine`` 不 import 任何 Windows 相关模块，方便测试与复用。
2. **依赖注入** —— 剪贴板、键盘、UIAutomation 都以参数传入，测试里可以替换成假的实现。
3. **日志代替 print** —— 全部走 ``logging``，UI 通过 handler 订阅，不直接读 stdout。
"""

from __future__ import annotations

__version__ = "2.0.0"
__all__ = ["__version__"]
