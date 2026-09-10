"""Runtime 执行生命周期扩展点。"""

from .protocols import ToolResultObserver, ToolResultObserverOutput

__all__ = ["ToolResultObserver", "ToolResultObserverOutput"]
