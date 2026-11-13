"""从源码直接运行人脸提示词工具；只导入标准库及独立人脸包。"""

from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[1] / "src"  # 当前独立项目的源码位置，不访问旧项目。
sys.path.insert(0, str(SOURCE))

from causal_face.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
