"""本地合成研究命令；独占创建 JSON，只有显式 --overwrite 才允许覆盖已有普通文件。"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src")) # 允许未安装的 src 布局直接运行。

from causal_research import run_experiment


# 解析有界实验配置，输出完整 JSON 到显式路径或标准输出，不执行外部命令。
def main() -> int:
    parser = argparse.ArgumentParser(description="SYNTHETIC ONLY chronological causal research; no real efficacy claim") # CLI 帮助。
    parser.add_argument("--seed", type=int, default=42, help="First independent trajectory seed") # 首个种子。
    parser.add_argument("--samples", type=int, default=1200, help="Origins per serial trajectory, 200..10000") # 每条轨迹规模。
    parser.add_argument("--replications", type=int, default=30, help="Independent seeds, 1..200") # 独立重复数。
    parser.add_argument("--bootstrap-draws", type=int, default=400, help="Moving-block draws, 100..2000") # 条件自助次数。
    parser.add_argument("--block-length", type=int, default=None, help="Block length; default round(test_n**(1/3))") # 块长度。
    parser.add_argument("--label-delay", type=int, default=0, help="Extra steps after outcome event before feedback arrives") # 标签到达延迟。
    parser.add_argument("--output", type=Path, help="New .json report path; omitted means stdout") # 输出位置。
    parser.add_argument("--overwrite", action="store_true", help="Explicitly permit replacing the named existing regular report") # 显式覆盖许可。
    arguments = parser.parse_args() # 命令行用户输入。
    if arguments.overwrite and arguments.output is None:
        parser.error("--overwrite requires --output")
    if arguments.output is not None:
        if arguments.output.suffix.lower() != ".json":
            parser.error("--output must end in .json")
        if arguments.output.is_symlink():
            parser.error("refusing symlink output")
        if arguments.output.exists() and (not arguments.overwrite or not arguments.output.is_file()):
            parser.error("output already exists; choose a new path or use --overwrite for a regular file")
    try:
        report = run_experiment(seed=arguments.seed, samples=arguments.samples,
                                replications=arguments.replications, bootstrap_draws=arguments.bootstrap_draws,
                                block_length=arguments.block_length, label_delay=arguments.label_delay) # 纯本地实验。
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n" # 稳定键顺序，拒绝 NaN。
        if arguments.output is None:
            sys.stdout.write(serialized)
        else:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            if arguments.output.is_symlink():
                raise ValueError("refusing symlink output")
            with arguments.output.open("w" if arguments.overwrite else "x", encoding="utf-8", newline="\n") as stream: # 默认独占创建。
                stream.write(serialized)
            print(f"SYNTHETIC ONLY report written: {arguments.output}")
    except (ValueError, OSError) as error:
        parser.exit(2, f"experiment refused: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
