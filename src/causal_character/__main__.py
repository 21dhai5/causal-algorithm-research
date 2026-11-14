"""支持python -m causal_character运行本地命令行。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
