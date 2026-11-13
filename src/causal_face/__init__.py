"""独立标准库人脸提示词入口；导入时不读文件、不调用网络或研究模型。"""

from .core import FacePromptError, VariationExhausted, generate_prompt
from .history import HistoryLedger

__all__ = ["FacePromptError", "VariationExhausted", "generate_prompt", "HistoryLedger"]  # 面向脚本和本地 HTTP 服务的稳定入口。
