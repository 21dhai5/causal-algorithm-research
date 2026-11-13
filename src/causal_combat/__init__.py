"""依据开放元素清单生成VFX提示词，不执行模拟或渲染。"""

from .core import DEFAULT_ELEMENTS, DEFAULT_INTERACTIONS, DEFAULT_TEXT, generate_prompt

__all__ = ["DEFAULT_TEXT", "DEFAULT_ELEMENTS", "DEFAULT_INTERACTIONS", "generate_prompt"]  # 公开接口只编排提示词，不启动服务或访问文件。
