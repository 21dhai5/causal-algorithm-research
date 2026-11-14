"""标准库命令行与回环服务入口；默认仅向标准输出返回可复制的中文提示词。"""

import argparse
import json
from pathlib import Path
import sys

from .core import EXPRESSION_LABELS, INTENSITY_LABELS, FacePromptError, generate_prompt, validate_expression, validate_prompt
from .history import HistoryLedger
from .server import FaceHTTPServer


# 解析互斥运行方式，先验证原文再打开账本；全部文件由调用方指定的历史目录承担。
def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="根据一段原文生成具有条件一致性的人脸绘画提示词；规则设计不属于因果效应推断。")  # 单输入交互无需额外模型或密钥。
    parser.add_argument("--text", help="完整原文，最高优先级保留")
    parser.add_argument("--expression", choices=EXPRESSION_LABELS, help="显式表情设计；省略时沿用原有补全")
    parser.add_argument("--intensity", choices=INTENSITY_LABELS, help="表情强度，默认 medium；需先选择表情")
    parser.add_argument("--cause", help="可选触发情境，最多 500 字符；只作设计设定，不推断真实情绪")
    parser.add_argument("--json", action="store_true", help="输出提示词、设计假设、变体标识及模式的 JSON")
    parser.add_argument("--serve", action="store_true", help="启动仅监听 127.0.0.1 的本地网页")
    parser.add_argument("--port", type=int, default=8765, help="本地端口，默认 8765")
    parser.add_argument("--history", type=Path, default=Path.home() / ".causal-face" / "history.sqlite3", help="仅保存输出散列的去重历史路径")
    try:
        options = parser.parse_args(argv)  # 参数只控制本地执行，不从环境读取凭据或服务地址。
    except SystemExit as error:
        return int(error.code)
    if options.serve and (options.text is not None or options.json or options.expression is not None
                          or options.intensity is not None or options.cause is not None):
        print("错误：--serve 不能同时使用 --text、--json、--expression、--intensity 或 --cause。", file=sys.stderr)
        return 2
    if not options.serve and options.text is None:
        print("错误：请提供 --text，或使用 --serve 打开本地工具。", file=sys.stderr)
        return 2
    if not 1 <= options.port <= 65535:
        print("错误：端口必须是 1 至 65535 的整数。", file=sys.stderr)
        return 2
    try:
        intensity = "medium" if options.intensity is None else options.intensity  # 解析后补入缺省强度，服务参数仍能检测显式传入。
        cause = "" if options.cause is None else options.cause  # 空情境为合法缺省，不自动编造故事。
        if not options.serve:
            validate_prompt(options.text)  # 无效输入不会创建默认历史目录。
            validate_expression(options.expression, intensity, cause)  # 表情参数同样必须在任何历史路径创建前验证。
        with HistoryLedger(options.history) as history:  # 同一账本的进程和线程共享 SQLite 唯一约束。
            if options.serve:
                with FaceHTTPServer(options.port, history) as server:  # 仅固定回环绑定，启动失败不退回公开地址。
                    print(f"本地工具已启动：http://127.0.0.1:{server.server_port}/ ，按 Ctrl+C 停止。", file=sys.stderr)
                    server.serve_forever()
            else:
                result = generate_prompt(options.text, history, expression=options.expression, intensity=intensity, cause=cause)  # 默认输出不混入变体 ID 或调试信息。
                print(json.dumps(result, ensure_ascii=False, indent=2) if options.json else result["prompt"])
        return 0
    except FacePromptError as error:
        print("错误：" + str(error), file=sys.stderr)
        return 2
    except OSError:
        print("错误：无法启动本地服务，请检查端口占用及本机权限。", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
