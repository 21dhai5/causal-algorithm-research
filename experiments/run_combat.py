"""从源码仓库直接运行仙侠交互示例，无需安装依赖包。"""

from pathlib import Path
import sys


SOURCE = Path(__file__).resolve().parents[1] / "src"  # 只定位本仓库源码，不读取用户指定文件。
sys.path.insert(0, str(SOURCE))

from causal_combat.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
