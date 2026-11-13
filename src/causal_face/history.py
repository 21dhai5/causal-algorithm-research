"""事务性去重账本只持久化 SHA-256，不保存输入、提示词、时间或请求日志。"""

from hashlib import sha256
from pathlib import Path
import sqlite3
from threading import Lock

from .core import FacePromptError, MAX_VARIANTS, VariationExhausted


# 所有线程共享同一连接锁；独立进程之间由 SQLite 唯一键与写事务协调。
class HistoryLedger:
    # 打开用户指定账本；仅 :memory: 特例不创建目录，连接不跨进程共享。
    def __init__(self, path: str | Path):
        self._lock = Lock()  # 保护当前连接的事务和关闭操作，不以 Python 锁替代 SQLite 进程锁。
        self._connection = None  # 连接由实例拥有，close 后保持 None。
        try:
            if str(path) != ":memory:":
                path = Path(path).expanduser()  # 文件路径仅来自可信 CLI 参数，HTTP 不接受路径。
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._connection = sqlite3.connect(str(path), timeout=15, check_same_thread=False)
            self._connection.execute("CREATE TABLE IF NOT EXISTS output_hashes (output_hash TEXT PRIMARY KEY)")
            self._connection.commit()
        except (OSError, sqlite3.Error) as error:
            self.close()
            raise FacePromptError("无法打开去重历史，请检查历史路径和文件权限。") from error

    # 在单次有上限的事务中选择首个未登记结果；耗尽时不返回重复提示词。
    def reserve(self, candidates: list[dict]) -> dict:
        if not candidates or len(candidates) > MAX_VARIANTS:
            raise FacePromptError("有限设计空间无效。")
        with self._lock:
            if self._connection is None:
                raise FacePromptError("去重历史已经关闭。")
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                for candidate in candidates:  # 最多 648 次散列比较，绝不无限随机重试。
                    digest = sha256(candidate["prompt"].encode("utf-8")).hexdigest()  # 散列标识最终完整文本，不含原文索引。
                    cursor = self._connection.execute("INSERT OR IGNORE INTO output_hashes VALUES (?)", (digest,))  # 唯一键处理跨实例和跨进程竞争。
                    if cursor.rowcount == 1:
                        self._connection.commit()
                        return {**candidate, "variation_id": digest}
                self._connection.rollback()
            except sqlite3.Error as error:
                self._connection.rollback()
                raise FacePromptError("去重历史暂时不可用，请稍后重试。") from error
        raise VariationExhausted(f"当前输入的 {len(candidates)} 种保守设计组合已在此历史中用尽，无法继续保证不同。请调整原文中的可变要求。")

    # 关闭连接时与生成互斥；可重复调用以支持异常清理。
    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    # 将账本生命周期交给 with 语句，避免验证或命令结束后遗留连接。
    def __enter__(self):
        return self

    # 即使调用方发生错误也释放连接，不吞掉调用方异常。
    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
