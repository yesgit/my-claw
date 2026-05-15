from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows-only 依赖，条件导入
# ---------------------------------------------------------------------------
_IS_WINDOWS = platform.system() == "Windows"

_uia: Any = None

if _IS_WINDOWS:
    try:
        import uiautomation as _uia_mod  # type: ignore[import-untyped]

        _uia = _uia_mod
    except ImportError:
        logger.warning("uiautomation 未安装，computer 工具的控件读取功能不可用。请运行 pip install uiautomation")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ControlInfo:
    """UIA 控件信息。"""
    control_type: str
    name: str
    automation_id: str
    class_name: str
    rect: tuple[int, int, int, int]
    depth: int
    text: str  # 控件的 Value / 文本内容

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_type": self.control_type,
            "name": self.name,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "rect": {
                "left": self.rect[0],
                "top": self.rect[1],
                "right": self.rect[2],
                "bottom": self.rect[3],
            },
            "width": self.rect[2] - self.rect[0],
            "height": self.rect[3] - self.rect[1],
            "depth": self.depth,
            "text": self.text,
        }


# ---------------------------------------------------------------------------
# 控件读取器
# ---------------------------------------------------------------------------

class ControlReader:
    """基于 Windows UIA 的控件树读取。"""

    # 支持的控件类型过滤
    COMMON_CONTROL_TYPES = {
        "ButtonControl", "EditControl", "TextControl", "ListControl",
        "ListItemControl", "TreeControl", "TreeItemControl", "TabControl",
        "TabItemControl", "MenuControl", "MenuItemControl", "ComboBoxControl",
        "CheckBoxControl", "RadioButtonControl", "PaneControl", "GroupControl",
        "ToolBarControl", "StatusBarControl", "DataItemControl",
        "DocumentControl", "HyperlinkControl", "ImageControl",
        "ScrollBarControl", "SliderControl", "SpinnerControl",
        "SplitButtonControl", "ThumbControl", "TitleBarControl",
        "ToolTipControl", "WindowControl",
    }

    @staticmethod
    def is_available() -> bool:
        """检查 UIA 功能是否可用。"""
        return _IS_WINDOWS and _uia is not None

    def list_controls(
        self,
        hwnd: int,
        control_type: str | None = None,
        name: str | None = None,
        depth: int = 4,
        max_count: int = 50,
    ) -> list[ControlInfo]:
        """列出窗口的控件树。

        Args:
            hwnd: 窗口句柄。
            control_type: 按控件类型过滤（如 "ListControl"）。
            name: 按控件名称过滤（子串匹配）。
            depth: 遍历深度，默认 4。
            max_count: 最大返回数量，默认 50。

        Returns:
            控件信息列表。
        """
        self._ensure_uia()

        root = _uia.ControlFromHandle(hwnd)
        if root is None:
            raise ValueError(f"无法获取句柄 {hwnd} 对应的控件")

        results: list[ControlInfo] = []
        self._walk_controls(root, depth=depth, current_depth=0,
                            control_type=control_type, name=name,
                            max_count=max_count, results=results)
        return results

    def read_text(
        self,
        hwnd: int,
        control_type: str | None = None,
        name: str | None = None,
        count: int = 10,
        depth: int = 6,
    ) -> list[dict[str, str]]:
        """读取窗口中匹配控件的文本内容。

        常用于读取消息列表等场景。

        Args:
            hwnd: 窗口句柄。
            control_type: 控件类型过滤。
            name: 控件名称过滤。
            count: 最多读取数量。
            depth: 搜索深度。

        Returns:
            文本内容列表，每项包含 {"name": "...", "text": "..."}。
        """
        self._ensure_uia()

        root = _uia.ControlFromHandle(hwnd)
        if root is None:
            raise ValueError(f"无法获取句柄 {hwnd} 对应的控件")

        # 找到匹配的控件
        matched = []
        self._walk_controls(root, depth=depth, current_depth=0,
                            control_type=control_type, name=name,
                            max_count=50, results=matched)

        # 提取文本
        texts: list[dict[str, str]] = []
        for ctrl_info in matched[:count]:
            texts.append({
                "name": ctrl_info.name,
                "text": ctrl_info.text,
                "control_type": ctrl_info.control_type,
            })

        return texts

    def read_list_items(
        self,
        hwnd: int,
        list_name: str | None = None,
        count: int = 20,
    ) -> list[dict[str, str]]:
        """读取窗口中 ListControl 的子项文本。

        这是一个便捷方法，专门用于读取列表类控件（如聊天消息列表）。

        Args:
            hwnd: 窗口句柄。
            list_name: ListControl 的 Name 属性（模糊匹配）。
            count: 最多读取的子项数量。

        Returns:
            子项文本列表。
        """
        self._ensure_uia()

        root = _uia.ControlFromHandle(hwnd)
        if root is None:
            raise ValueError(f"无法获取句柄 {hwnd} 对应的控件")

        # 查找 ListControl
        search_kwargs: dict[str, Any] = {"ControlType": _uia.UIA.UIA_ListControlTypeId}
        if list_name:
            search_kwargs["Name"] = list_name

        list_ctrl = root.ListControl(**search_kwargs)
        if list_ctrl is None or not list_ctrl.Exists(maxSearchSeconds=2):
            # 尝试不限定 Name
            list_ctrl = root.ListControl(ControlType=_uia.UIA.UIA_ListControlTypeId)
            if list_ctrl is None or not list_ctrl.Exists(maxSearchSeconds=2):
                return []

        # 读取子项
        items: list[dict[str, str]] = []
        children = list_ctrl.GetChildren()
        # 取最后 count 项
        for child in children[-count:]:
            text = self._extract_control_text(child)
            items.append({
                "name": child.Name or "",
                "text": text,
                "control_type": child.ControlTypeName,
            })

        return items

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _walk_controls(
        self,
        ctrl: Any,
        depth: int,
        current_depth: int,
        control_type: str | None,
        name: str | None,
        max_count: int,
        results: list[ControlInfo],
    ) -> None:
        """递归遍历控件树。"""
        if len(results) >= max_count:
            return
        if current_depth > depth:
            return

        # 跳过根控件本身
        if current_depth > 0:
            ctrl_type = ctrl.ControlTypeName
            ctrl_name = ctrl.Name or ""
            ctrl_auto_id = ctrl.AutomationId or ""
            ctrl_class = ctrl.ClassName or ""

            # 过滤
            if control_type and ctrl_type != control_type:
                pass  # 仍然遍历子控件
            elif name and name not in ctrl_name:
                pass  # 仍然遍历子控件
            else:
                rect = ctrl.BoundingRectangle
                text = self._extract_control_text(ctrl)
                results.append(ControlInfo(
                    control_type=ctrl_type,
                    name=ctrl_name,
                    automation_id=ctrl_auto_id,
                    class_name=ctrl_class,
                    rect=(rect.left, rect.top, rect.right, rect.bottom),
                    depth=current_depth,
                    text=text,
                ))

        # 递归子控件
        try:
            for child in ctrl.GetChildren():
                if len(results) >= max_count:
                    return
                self._walk_controls(child, depth, current_depth + 1,
                                    control_type, name, max_count, results)
        except Exception:  # noqa: BLE001
            pass  # 某些控件可能无法遍历子节点

    @staticmethod
    def _extract_control_text(ctrl: Any) -> str:
        """从控件中提取文本内容。

        尝试多种方式：Value pattern → Name → 子 TextControl 拼接。
        """
        parts: list[str] = []

        # 方式1：Value Pattern
        try:
            value = ctrl.GetValuePattern().Value
            if value and isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:  # noqa: BLE001
            pass

        # 方式2：Name 属性
        if ctrl.Name and ctrl.Name.strip():
            parts.append(ctrl.Name.strip())

        # 方式3：子 TextControl 文本拼接
        try:
            for child in ctrl.GetChildren():
                if child.ControlTypeName == "TextControl" and child.Name:
                    parts.append(child.Name.strip())
        except Exception:  # noqa: BLE001
            pass

        return "\n".join(parts) if parts else ""

    @staticmethod
    def _ensure_uia() -> None:
        """确保 UIA 可用。"""
        if not _IS_WINDOWS:
            raise RuntimeError("computer 工具的控件读取仅支持 Windows")
        if _uia is None:
            raise RuntimeError("uiautomation 未安装，请运行 pip install uiautomation")