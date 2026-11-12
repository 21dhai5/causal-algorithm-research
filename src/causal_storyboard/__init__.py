"""可替换解析器的纯 Python 事件分镜入口；导入不执行模型请求或文件操作。"""

from .core import DEFAULT_STYLE, RuleSceneParser, SceneParser, build_storyboard, validate_scene

__all__ = ["DEFAULT_STYLE", "RuleSceneParser", "SceneParser", "build_storyboard", "validate_scene"]  # 对外稳定入口。
