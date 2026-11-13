"""标准库命令行：默认只规划分镜，图像请求必须由用户明确启用。"""

import argparse
import json
from pathlib import Path
import sys

from .images import GENERATION_KIND, HttpImageProvider, ImageGenerationError, generate_images, reserve_output_directory


# 解析输入、先完成规划和配置检查，再独占创建目录并保存结果；部分图像失败返回 3。
def main(argv: list[str] | None = None) -> int:
    # 标准输出固定为 UTF-8，使 Windows 管道中的中文 JSON 也能跨平台读取。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="生成因果分镜 JSON；可选择调用已配置的图像服务生成静帧。")  # 公开且不含密钥参数的接口。
    parser.add_argument("--text", required=True, help="要规划的短文本")
    parser.add_argument("--duration", type=float, default=6, help="总时长（秒），默认 6")
    parser.add_argument("--shots", type=int, default=3, help="镜头数量，默认 3")
    parser.add_argument("--style", help="可选风格描述，默认使用核心规划器风格")
    parser.add_argument("--output", type=Path, help="在已存在父目录中创建的新输出目录；已有目标会被拒绝")
    parser.add_argument("--generate-images", action="store_true", help="显式启用可能计费的图像请求；必须提供 --output 和三个图像环境变量")
    try:
        options = parser.parse_args(argv)  # argparse 的退出转换为可测试的整数返回值。
    except SystemExit as error:
        return int(error.code)
    if options.generate_images and options.output is None:
        print("错误：--generate-images 必须同时提供 --output。", file=sys.stderr)
        return 2
    try:
        from .core import build_storyboard  # 延迟导入，避免规划核心与可选图像适配器相互耦合。

        kwargs = {"duration": options.duration, "shots": options.shots}  # 核心参数保持单一来源。
        if options.style is not None:
            kwargs["style"] = options.style
        board = build_storyboard(options.text, **kwargs)  # 输入失败时尚未创建任何输出目录。
        board["generation_kind"] = GENERATION_KIND
        provider = HttpImageProvider.from_env() if options.generate_images else None  # 环境配置本身不会触发请求。
        if options.output is not None:
            directory = reserve_output_directory(options.output)  # 原子拒绝已有目标。
            if provider is not None:
                generate_images(board, provider, directory)
            with (directory / "storyboard.json").open("x", encoding="utf-8") as output:  # 即使部分镜头失败也保存状态。
                json.dump(board, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
        else:
            print(json.dumps(board, ensure_ascii=False, indent=2, allow_nan=False))
        return 3 if any(shot["image"]["status"] == "failed" for shot in board["shots"]) else 0
    except ImageGenerationError:
        print("错误：图像配置无效；请检查 STORYBOARD_IMAGE_URL、STORYBOARD_IMAGE_MODEL、STORYBOARD_IMAGE_KEY 和 HTTPS 端点。", file=sys.stderr)
        return 2
    except ValueError:
        print("错误：文本无法解析、分镜参数不合法，或输出路径经过符号链接。", file=sys.stderr)
        return 2
    except OSError:
        print("错误：无法独占创建输出目录或写入结果；请使用已有父目录中的新目录。", file=sys.stderr)
        return 2
