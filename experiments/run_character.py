"""从源码直接运行人物多视图提示词工具；只导入标准库与独立人物包。"""

from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[1] / "src"  # 当前项目的源码位置，不访问旧项目。
sys.path.insert(0, str(SOURCE))

from causal_character.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
