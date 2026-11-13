"""标准库命令行入口；默认输出可复制文本，文件仅按用户显式路径独占创建。"""

import argparse
import json
from pathlib import Path
import sys

from .core import CharacterPromptError, DEFAULT_DESCRIPTION, DEFAULT_STYLE, generate_multiview_prompt, strict_json_loads
from .server import CharacterHTTPServer, MAX_BODY_BYTES


# 有界读取显式地标文件；严格JSON解析，不自动寻找配置或历史文件。
def _read_features(path: Path) -> list:
    try:
        with path.open("rb") as source:  # 文件只读，作用域结束立即关闭。
            raw = source.read(MAX_BODY_BYTES + 1)  # 多读一字节用于检测超限。
    except OSError:
        raise CharacterPromptError("无法读取地标JSON文件，请检查路径与权限。") from None
    if len(raw) > MAX_BODY_BYTES:
        raise CharacterPromptError("地标JSON文件不能超过256 KiB。")
    features = strict_json_loads(raw)  # JSON数组结构由生成器继续校验。
    if not isinstance(features, list):
        raise CharacterPromptError("地标JSON文件必须包含数组。")
    return features


# 解析本地生成与服务参数；所有业务错误返回2，不自动打开浏览器或覆盖已有文件。
def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="生成同一人物的多视图中文提示词；显式因果规则设计，不生成图像。")  # 无模型、密钥及外部服务依赖。
    parser.add_argument("--serve", action="store_true", help="启动仅监听127.0.0.1的本地网页服务")
    parser.add_argument("--port", type=int, default=8767, help="本地服务端口，默认8767")
    parser.add_argument("--text", help="人物身份原文，最多6000字符；省略时使用示例")
    parser.add_argument("--style", help="表达风格，最多1000字符；省略时使用示例")
    parser.add_argument("--views", help="英文逗号分隔的固定视图ID；省略时使用front,right,back,left")
    parser.add_argument("--features", type=Path, help="包含地标数组的UTF-8 JSON文件，最多40项")
    parser.add_argument("--json", action="store_true", help="输出完整结构化JSON结果")
    parser.add_argument("--output", type=Path, help="仅创建尚不存在的UTF-8输出文件，不覆盖已有内容")
    try:
        options = parser.parse_args(argv)  # 参数解析结果只用于本次本地执行。
    except SystemExit as error:
        return int(error.code)
    if not 1 <= options.port <= 65535:
        print("错误：端口必须是1至65535的整数。", file=sys.stderr)
        return 2
    if options.serve and (options.text is not None or options.style is not None or options.views is not None or options.features is not None or options.json or options.output is not None):
        print("错误：--serve不能同时使用生成或输出参数。", file=sys.stderr)
        return 2
    try:
        if options.serve:
            with CharacterHTTPServer(options.port) as server:  # 固定绑定回环，启动失败不退回其他地址。
                print(f"本地工具已启动：http://127.0.0.1:{server.server_port}/ ，按Ctrl+C停止。", file=sys.stderr)
                server.serve_forever()
            return 0
        result = generate_multiview_prompt(  # 显式空字符串不会被默认值替换。
            DEFAULT_DESCRIPTION if options.text is None else options.text,
            style=DEFAULT_STYLE if options.style is None else options.style,
            views=None if options.views is None else [view.strip() for view in options.views.split(",")],
            features=None if options.features is None else _read_features(options.features),
        )
        output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) if options.json else result["full_prompt"]  # 默认仅输出完整可复制文本。
        if options.output is None:
            print(output)
        else:
            with options.output.open("x", encoding="utf-8", newline="\n") as target:  # 原子独占创建，不覆盖目标文件或已有符号链接。
                target.write(output + "\n")
        return 0
    except CharacterPromptError as error:
        print("错误：" + str(error), file=sys.stderr)
        return 2
    except FileExistsError:
        print("错误：输出路径已存在，不能覆盖。", file=sys.stderr)
        return 2
    except OSError:
        print("错误：无法启动本地服务或写入输出，请检查端口、路径及本机权限。", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
