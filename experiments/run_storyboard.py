"""从源码直接运行分镜入口；离线规则模式不需要安装第三方依赖。"""

from pathlib import Path
import sys

# SOURCE 固定为当前独立项目的包目录，不读取旧项目或用户资料。
SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from causal_storyboard.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
