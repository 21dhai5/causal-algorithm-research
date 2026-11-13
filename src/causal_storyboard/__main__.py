"""支持 python -m causal_storyboard，不在导入包时执行生成。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
