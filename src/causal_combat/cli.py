"""VFX提示词命令行：默认输出正文，--json输出完整报告，服务仅监听本机。"""

import argparse
import json
from pathlib import Path
import stat
import sys

from .core import DEFAULT_TEXT, generate_prompt
from .server import MAX_BODY_BYTES, CombatHTTPServer, _invalid_constant, _unique_fields


# 只读取用户明确提供的本地JSON文件；有界读取且不接受重复键或非标准数值。
def _inventory(path: Path) -> dict:
    # 在任何文件系统访问前拒绝UNC与设备路径，避免把清单选项用作网络读取。
    if str(path).replace("\\", "/").startswith("//"):
        raise ValueError("清单必须是本地普通文件，不支持网络或设备路径。")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("清单必须是本地普通文件。")
    with path.open("rb") as source:  # 文件句柄仅在本次CLI读取期间持有。
        raw = source.read(MAX_BODY_BYTES + 1)  # 多读一字节识别超限，不静默截断。
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("清单文件不能超过256 KiB。")
    body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields, parse_constant=_invalid_constant)  # 与HTTP保持一致的严格JSON规则。
    if not isinstance(body, dict) or set(body).difference({"elements", "interactions"}) or "elements" not in body:
        raise ValueError("清单文件必须包含elements数组，只允许elements和interactions字段。")
    for field, value in body.items():  # 显式null不能冒充未提供清单。
        if not isinstance(value, list):
            raise ValueError(f"清单文件的{field}必须是数组。")
    return body


# 解析独立命令行；参数验证仍交给生成器，防止API与CLI采用不同范围。
def main(argv: list[str] | None = None) -> int:
    # Windows重定向和本机服务提示统一使用UTF-8，避免中文因系统代码页损坏。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="根据任意具体元素和属性生成VFX提示词；默认输出完整提示词正文，不执行模拟或渲染。")  # 一个入口同时支持提示词与本地页面。
    parser.add_argument("--serve", action="store_true", help="启动仅回环HTTP页面，使用Ctrl+C结束")  # 服务不自动打开浏览器。
    parser.add_argument("--port", type=int, default=8766, help="本地页面端口，默认8766")  # 仅在serve模式生效。
    parser.add_argument("--text", help="最多20000字符；支持逐行名称｜属性=值或名称：完整细节，普通叙述保留待拆分")  # 未提供时普通模式用示例，清单模式用空上下文。
    parser.add_argument("--inventory", type=Path, help="读取本地JSON清单：{elements:[...],interactions:[...]}；元素清单为权威输入")  # 只有此显式选项可以读取用户文件。
    parser.add_argument("--json", action="store_true", help="输出含逐元素提示词、交互、证据及警告的完整JSON")  # 默认则输出可复制正文。
    parser.add_argument("--output", type=Path, help="将正文或--json报告写入新文件，文件已存在时拒绝覆盖")  # 调用方显式控制路径。
    args = parser.parse_args(argv)  # 不保存命令行创作文本到额外日志。
    if args.serve:
        if not 1 <= args.port <= 65535:
            parser.error("--port必须在1至65535之间。")
        if args.output or args.inventory or args.json or args.text is not None:
            parser.error("--serve不能与--text、--inventory、--json或--output同时使用。")
        try:
            with CombatHTTPServer(args.port) as server:  # 服务句柄只由当前线程管理。
                print(f"VFX提示词编排：http://127.0.0.1:{server.server_port}/ （Ctrl+C结束）", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
            return 0
        except OSError:
            print("无法启动本机服务，请检查端口是否被占用。", file=sys.stderr)
            return 1
    try:
        inventory = _inventory(args.inventory) if args.inventory else {}  # 无清单时只解析用户文本，不注入示例元素。
        text = args.text if args.text is not None else "" if args.inventory else DEFAULT_TEXT  # 自定义清单不混入默认示例场景。
        result = generate_prompt(text, **inventory)  # 保持公开生成器的一致校验。
        content = (json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) if args.json else result["full_prompt"]) + "\n"  # 格式同时适用于终端和文件。
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as output:  # 独占创建防止无意覆盖用户文件。
                output.write(content)
        elif hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(content.encode("utf-8"))  # 正文与JSON管道固定为UTF-8，不受Windows本地代码页影响。
        else:
            print(content, end="")
        return 0
    except (ValueError, TypeError, OverflowError, RecursionError, OSError) as error:
        print(f"生成失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
