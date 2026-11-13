"""仙侠模拟命令行：无参数输出示例JSON，--serve仅启动本机交互页面。"""

import argparse
import json
from pathlib import Path
import sys

from .core import DEFAULT_TEXT, build_combat
from .server import CombatHTTPServer


# 解析独立命令行；参数验证仍交给生成器，防止API与CLI采用不同范围。
def main(argv: list[str] | None = None) -> int:
    # Windows重定向和本机服务提示统一使用UTF-8，避免中文因系统代码页损坏。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="生成可复现的仙侠战斗素材与30Hz规则交互数据；无参数输出示例JSON。")  # 一个入口同时支持数据与本地页面。
    parser.add_argument("--serve", action="store_true", help="启动仅回环HTTP页面，使用Ctrl+C结束")  # 服务不自动打开浏览器。
    parser.add_argument("--port", type=int, default=8766, help="本地页面端口，默认8766")  # 仅在serve模式生效。
    parser.add_argument("--text", default=DEFAULT_TEXT, help="1至4000字符的自由创作简报；数值参数为权威设计输入")  # 不声称通用文本抽取。
    parser.add_argument("--charge", type=float, default=0.8, help="蓄力比例[0,1]")  # 控制释放门槛与能量。
    parser.add_argument("--distance-m", type=float, default=8, help="双方距离[2,24]米")  # 与API的distance_m对应。
    parser.add_argument("--shield", type=float, default=50, help="初始盾强[0,120]虚构单位")  # 零盾直接检测身体。
    parser.add_argument("--aim-offset-m", type=float, default=0, help="目标平面横向偏移[-5,5]米")  # 与API的aim_offset_m对应。
    parser.add_argument("--seed", type=int, default=7, help="素材随机种子[0,2**32)")  # 只改变外观，不掷骰判定命中。
    parser.add_argument("--json", action="store_true", help="显式选择JSON输出；也是默认行为")  # 允许脚本清晰声明格式。
    parser.add_argument("--output", type=Path, help="将完整JSON写入新文件；文件已存在时拒绝覆盖")  # 调用方显式控制路径。
    args = parser.parse_args(argv)  # 不保存命令行创作文本到额外日志。
    if args.serve:
        if not 1 <= args.port <= 65535:
            parser.error("--port必须在1至65535之间。")
        if args.output:
            parser.error("--serve不能与--output同时使用。")
        try:
            with CombatHTTPServer(args.port) as server:  # 服务句柄只由当前线程管理。
                print(f"仙侠规则设计模拟：http://127.0.0.1:{server.server_port}/ （Ctrl+C结束）", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
            return 0
        except OSError:
            print("无法启动本机服务，请检查端口是否被占用。", file=sys.stderr)
            return 1
    try:
        result = build_combat(args.text, charge=args.charge, distance_m=args.distance_m, shield=args.shield, aim_offset_m=args.aim_offset_m, seed=args.seed)  # 保持公开生成器的一致校验。
        content = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"  # JSON可直接供其他脚本使用。
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as output:  # 独占创建防止无意覆盖用户文件。
                output.write(content)
        elif hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(content.encode("utf-8"))  # JSON管道固定为UTF-8，不受Windows本地代码页影响。
        else:
            print(content, end="")
        return 0
    except (ValueError, OSError) as error:
        print(f"生成失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
