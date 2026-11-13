"""独立的人物多视图提示词模块；标准库实现，不读取历史、不调用网络模型。"""

from .core import CharacterPromptError, generate_multiview_prompt

__all__ = ["CharacterPromptError", "generate_multiview_prompt"]  # 最小公共接口及可捕获的输入错误。
