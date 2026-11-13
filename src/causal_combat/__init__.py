"""以规则、状态和固定步长帧驱动的仙侠交互特效设计。"""

from .core import DEFAULT_TEXT, build_combat

__all__ = ["DEFAULT_TEXT", "build_combat"]  # 公开接口只负责生成数据，不启动服务或访问文件。
