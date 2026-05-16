"""macOS 控件读取器。

使用 macOS Accessibility API（通过 pyobjc 的 ApplicationServices）实现
控件树遍历和文本读取。

注意：需要授予辅助功能权限（System Preferences → Privacy → Accessibility）。
"""
from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# macOS-only 依赖，条件导入
# ---------------------------------------------------------------------------
_IS_MACOS = platform.system() == "Darwin"

_AX: Any = None  # ApplicationServices Accessibility


def _init_ax() -> bool:
    """初始化 ApplicationServices 框架，返回是否成功。"""
    global _AX

    try:
        import ApplicationServices as _AX_mod  # type: ignore[import-untyped]
        _AX = _AX_mod
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("pyobjc-framework-ApplicationServices 导入失败: %s", exc)
        return False


if _IS_MACOS:
    _init_ax()


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MacControlInfo:
    """macOS Accessibility 控件信息。"""

    role: str  # AXRole，如 AXButton, AXTextField, AXStaticText
    title: str  # AXTitle
    description: str  # AXDescription
    value: str  # AXValue
    position: tuple[float, float, float, float]  # (x, y, width, height)
    depth: int
    text: str  # 提取的文本内容

    def to_dict(self) -> dict[str, Any]:
        x, y, w, h = self.position
        return {
            "control_type": self.role,
            "name": self.title or self.description or "",
            "automation_id": "",
            "class_name": self.role,
            "rect": {
                "left": int(x),
                "top": int(y),
                "right": int(x + w),
                "bottom": int(y + h),
            },
            "width": int(w),
            "height": int(h),
            "depth": self.depth,
            "text": self.text,
        }


# ---------------------------------------------------------------------------
# macOS 控件读取器
# ---------------------------------------------------------------------------


class MacControlReader:
    """基于 macOS Accessibility API 的控件树读取。"""

    # 常见的控件角色
    COMMON_ROLES = {
        "AXButton",
        "AXTextField",
        "AXStaticText",
        "AXTextArea",
        "AXList",
        "AXOutline",
        "AXTable",
        "AXRow",
        "AXCell",
        "AXGroup",
        "AXRadioGroup",
        "AXCheckBox",
        "AXComboBox",
        "AXMenuButton",
        "AXMenuBarItem",
        "AXMenuItem",
        "AXScrollArea",
        "AXScrollBar",
        "AXSlider",
        "AXSplitGroup",
        "AXTabGroup",
        "AXToolbar",
        "AXWebArea",
        "AXWindow",
        "AXSheet",
        "AXDialog",
        "AXGrowArea",
        "AXImage",
        "AXProgressIndicator",
        "AXRelevanceIndicator",
        "AXDisclosureTriangle",
        "AXPopUpButton",
        "AXPopover",
    }

    @staticmethod
    def is_available() -> bool:
        """检查 Accessibility API 是否可用。"""
        return _IS_MACOS and _AX is not None

    def list_controls(
        self,
        hwnd: int,
        control_type: str | None = None,
        name: str | None = None,
        depth: int = 4,
        max_count: int = 50,
    ) -> list[MacControlInfo]:
        """列出窗口的控件树。

        Args:
            hwnd: macOS 上对应 window_id（CGWindowID）。
            control_type: 按控件角色过滤（如 "AXButton"）。
            name: 按控件标题过滤（子串匹配）。
            depth: 遍历深度，默认 4。
            max_count: 最大返回数量，默认 50。

        Returns:
            控件信息列表。
        """
        self._ensure_available()

        # 通过 PID 获取应用的 AX 元素
        info = self._get_window_info(hwnd)
        if info is None:
            raise ValueError(f"无法获取窗口 {hwnd} 的信息")

        pid = info["pid"]

        # 获取应用的 AX 应用对象
        app_ref = self._get_ax_app(pid)
        if app_ref is None:
            raise ValueError(f"无法获取 PID {pid} 的 Accessibility 对象")

        results: list[MacControlInfo] = []
        self._walk_controls(
            app_ref,
            depth=depth,
            current_depth=0,
            control_type=control_type,
            name=name,
            max_count=max_count,
            results=results,
        )
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

        Args:
            hwnd: 窗口 ID。
            control_type: 控件角色过滤。
            name: 控件标题过滤。
            count: 最多读取数量。
            depth: 搜索深度。

        Returns:
            文本内容列表。
        """
        self._ensure_available()

        info = self._get_window_info(hwnd)
        if info is None:
            raise ValueError(f"无法获取窗口 {hwnd} 的信息")

        pid = info["pid"]
        app_ref = self._get_ax_app(pid)
        if app_ref is None:
            raise ValueError(f"无法获取 PID {pid} 的 Accessibility 对象")

        matched: list[MacControlInfo] = []
        self._walk_controls(
            app_ref,
            depth=depth,
            current_depth=0,
            control_type=control_type,
            name=name,
            max_count=50,
            results=matched,
        )

        texts: list[dict[str, str]] = []
        for ctrl_info in matched[:count]:
            texts.append(
                {
                    "name": ctrl_info.title or ctrl_info.description or "",
                    "text": ctrl_info.text,
                    "control_type": ctrl_info.role,
                }
            )

        return texts

    def read_list_items(
        self,
        hwnd: int,
        list_name: str | None = None,
        count: int = 20,
    ) -> list[dict[str, str]]:
        """读取窗口中列表控件的子项文本。

        Args:
            hwnd: 窗口 ID。
            list_name: 列表控件的标题（模糊匹配）。
            count: 最多读取的子项数量。

        Returns:
            子项文本列表。
        """
        self._ensure_available()

        info = self._get_window_info(hwnd)
        if info is None:
            raise ValueError(f"无法获取窗口 {hwnd} 的信息")

        pid = info["pid"]
        app_ref = self._get_ax_app(pid)
        if app_ref is None:
            raise ValueError(f"无法获取 PID {pid} 的 Accessibility 对象")

        # 查找 AXList 或 AXOutline
        lists: list[MacControlInfo] = []
        self._walk_controls(
            app_ref,
            depth=6,
            current_depth=0,
            control_type="AXList",
            name=list_name,
            max_count=5,
            results=lists,
        )

        if not lists:
            # 尝试 AXOutline
            self._walk_controls(
                app_ref,
                depth=6,
                current_depth=0,
                control_type="AXOutline",
                name=list_name,
                max_count=5,
                results=lists,
            )

        if not lists:
            return []

        # 读取列表子项
        items: list[dict[str, str]] = []
        for lst in lists:
            # 获取 AX 元素
            ax_element = self._find_ax_element_by_info(app_ref, lst)
            if ax_element is None:
                continue

            children = self._get_ax_children(ax_element)
            for child in children[-count:]:
                text = self._extract_ax_text(child)
                title = self._get_ax_attribute(child, "AXTitle") or ""
                role = self._get_ax_attribute(child, "AXRole") or ""
                items.append(
                    {
                        "name": title,
                        "text": text,
                        "control_type": role,
                    }
                )

        return items

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_window_info(window_id: int) -> dict[str, Any] | None:
        """通过 CGWindowID 获取窗口信息（PID 等）。"""
        if not _IS_MACOS:
            return None

        try:
            import Quartz  # type: ignore[import-untyped]

            window_list = Quartz.CGWindowListCreate(
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID,
            )
            if window_list is None:
                return None

            count = window_list.getCount()
            for i in range(count):
                try:
                    win_dict = window_list.objectAtIndex(i)
                except Exception:  # noqa: BLE001
                    continue

                wid = win_dict.get("kCGWindowNumber", 0)
                if wid == window_id:
                    return {
                        "pid": win_dict.get("kCGWindowOwnerPID", 0),
                        "owner": win_dict.get("kCGWindowOwnerName", "") or "",
                        "title": win_dict.get("kCGWindowName", "") or "",
                    }
        except ImportError:
            pass

        return None

    @staticmethod
    def _get_ax_app(pid: int) -> Any:
        """获取指定 PID 的 AX 应用对象。"""
        try:
            app_ref = _AX.AXUIElementCreateApplication(pid)
            if app_ref is None:
                return None
            return app_ref
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _get_ax_attribute(element: Any, attribute: str) -> Any:
        """安全获取 AX 属性值。"""
        try:
            result = _AX.AXUIElementCopyAttributeValue(element, attribute, None)
            if result and result[0] == 0:  # kAXErrorSuccess
                return result[1]
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _get_ax_children(element: Any) -> list[Any]:
        """获取 AX 元素的子元素列表。"""
        children = _AX.AXUIElementCopyAttributeValue(element, "AXChildren", None)
        if children and children[0] == 0 and children[1]:
            return list(children[1])
        return []

    @staticmethod
    def _get_ax_position(element: Any) -> tuple[float, float, float, float]:
        """获取 AX 元素的位置和大小。"""
        try:
            pos = _AX.AXUIElementCopyAttributeValue(element, "AXPosition", None)
            size = _AX.AXUIElementCopyAttributeValue(element, "AXSize", None)
            x = y = w = h = 0.0
            if pos and pos[0] == 0 and pos[1]:
                x, y = pos[1]
            if size and size[0] == 0 and size[1]:
                w, h = size[1]
            return (x, y, w, h)
        except Exception:  # noqa: BLE001
            return (0, 0, 0, 0)

    def _extract_ax_text(self, element: Any) -> str:
        """从 AX 元素提取文本内容。"""
        parts: list[str] = []

        # AXValue
        value = self._get_ax_attribute(element, "AXValue")
        if value and isinstance(value, str) and value.strip():
            parts.append(value.strip())

        # AXTitle
        title = self._get_ax_attribute(element, "AXTitle")
        if title and isinstance(title, str) and title.strip():
            parts.append(title.strip())

        # AXDescription
        desc = self._get_ax_attribute(element, "AXDescription")
        if desc and isinstance(desc, str) and desc.strip():
            parts.append(desc.strip())

        # AXSelectedText (for text fields)
        sel_text = self._get_ax_attribute(element, "AXSelectedText")
        if sel_text and isinstance(sel_text, str) and sel_text.strip():
            parts.append(sel_text.strip())

        # 子 AXStaticText
        for child in self._get_ax_children(element):
            role = self._get_ax_attribute(child, "AXRole")
            if role == "AXStaticText":
                child_text = self._extract_ax_text(child)
                if child_text:
                    parts.append(child_text)

        return "\n".join(parts) if parts else ""

    def _walk_controls(
        self,
        element: Any,
        depth: int,
        current_depth: int,
        control_type: str | None,
        name: str | None,
        max_count: int,
        results: list[MacControlInfo],
    ) -> None:
        """递归遍历 AX 控件树。"""
        if len(results) >= max_count:
            return
        if current_depth > depth:
            return

        if current_depth > 0:
            role = self._get_ax_attribute(element, "AXRole") or ""
            title = self._get_ax_attribute(element, "AXTitle") or ""
            desc = self._get_ax_attribute(element, "AXDescription") or ""
            value = self._get_ax_attribute(element, "AXValue") or ""
            if not isinstance(value, str):
                value = str(value) if value is not None else ""

            # 过滤
            matched = True
            if control_type and role != control_type:
                matched = False
            if name and name not in title and name not in desc:
                matched = False

            if matched:
                pos = self._get_ax_position(element)
                text = self._extract_ax_text(element)
                results.append(
                    MacControlInfo(
                        role=role,
                        title=title,
                        description=desc,
                        value=value,
                        position=pos,
                        depth=current_depth,
                        text=text,
                    )
                )

        # 递归子控件
        try:
            for child in self._get_ax_children(element):
                if len(results) >= max_count:
                    return
                self._walk_controls(
                    child,
                    depth,
                    current_depth + 1,
                    control_type,
                    name,
                    max_count,
                    results,
                )
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _find_ax_element_by_info(
        root: Any, target: MacControlInfo
    ) -> Any | None:
        """根据 MacControlInfo 查找对应的 AX 元素。"""
        # 简单实现：遍历查找匹配 role + title 的元素
        def _search(element: Any, target_role: str, target_title: str, max_depth: int = 8) -> Any | None:
            if max_depth <= 0:
                return None
            try:
                role = _AX.AXUIElementCopyAttributeValue(element, "AXRole", None)
                title = _AX.AXUIElementCopyAttributeValue(element, "AXTitle", None)
                if role and role[0] == 0 and role[1] == target_role:
                    if title and title[0] == 0 and title[1] == target_title:
                        return element
                for child in _AX.AXUIElementCopyAttributeValue(element, "AXChildren", None)[1] or []:
                    result = _search(child, target_role, target_title, max_depth - 1)
                    if result:
                        return result
            except Exception:  # noqa: BLE001
                pass
            return None

        return _search(root, target.role, target.title)

    @staticmethod
    def _ensure_available() -> None:
        """确保 Accessibility API 可用。"""
        if not _IS_MACOS:
            raise RuntimeError("computer 工具的控件读取仅支持 macOS")
        if _AX is None:
            raise RuntimeError(
                "pyobjc-framework-ApplicationServices 未安装，"
                "请运行: pip install pyobjc-framework-ApplicationServices"
            )
