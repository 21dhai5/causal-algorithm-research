"""仅回环 HTTP 服务；固定路由、来源核对及小体积 JSON，不接受模型端点或文件路径。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket

from .core import FacePromptError, VariationExhausted, generate_prompt
from .history import HistoryLedger


MAX_BODY_BYTES = 32768  # 限制 JSON 整体字节数，独立于提示词的 4000 字符限制。


# 拒绝重复 JSON 字段，避免客户端与服务端对同一提示词采用不同值。
def _unique_fields(pairs: list) -> dict:
    fields = {}  # 一次对象解析期间的字段集合，不保存到日志或磁盘。
    for name, value in pairs:  # 同名键不能覆盖前一值。
        if name in fields:
            raise FacePromptError("JSON 字段不能重复。")
        fields[name] = value
    return fields


# 将非标准 NaN、Infinity 等 JSON 常量统一视为输入错误。
def _invalid_constant(value: str):
    raise FacePromptError("请求必须使用标准 JSON 值。")


class FaceHTTPServer(ThreadingHTTPServer):
    """线程处理请求，账本由服务创建者拥有并在服务结束后关闭。"""

    daemon_threads = True  # 退出时不等待被客户端阻塞的请求线程。

    # 只监听 IPv4 回环地址；端口 0 供内存验证申请空闲端口使用。
    def __init__(self, port: int, history: HistoryLedger):
        self.history = history  # 所有请求共享线程安全账本，不接收客户端传入的历史位置。
        super().__init__(("127.0.0.1", port), FaceRequestHandler)


class FaceRequestHandler(BaseHTTPRequestHandler):
    """每个连接一条请求；所有错误只返回中文 JSON，不回显内部路径或异常。"""

    server_version = "CausalFace"  # 不向浏览器公开本机 Python 运行时版本。
    sys_version = ""  # 省略父类默认追加的运行时信息。

    # 为头部和请求体读取设置有限等待时间，避免无限占用线程。
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    # 禁用默认访问日志，防止路径、查询参数或用户文本落入终端日志。
    def log_message(self, format: str, *args) -> None:
        pass

    # 框架解析失败同样使用固定 JSON 错误，忽略可能包含原始请求的默认详情。
    def send_error(self, code: int, message=None, explain=None) -> None:
        self._json(code, {"error": "HTTP 请求无效或请求方法不受支持。"})

    # 固定安全响应头，不开放跨域权限；始终关闭连接防止未消费请求体被复用。
    def _respond(self, status: int, content: bytes, content_type: str) -> None:
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass

    # JSON 始终以 UTF-8 编码，禁止序列化非标准浮点值。
    def _json(self, status: int, payload: dict) -> None:
        self._respond(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

    # Host 必须精确指向当前回环端口；浏览器 Origin 只能与本请求 Host 完全一致。
    def _local_request(self) -> bool:
        hosts = self.headers.get_all("Host", [])  # 拒绝重复 Host，不能只取第一项。
        origins = self.headers.get_all("Origin", [])  # 命令行客户端可不提供 Origin，提供后必须精确核验。
        port = self.server.server_port  # 实际绑定端口，兼容验证中的临时端口。
        if len(hosts) != 1 or hosts[0] not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._json(403, {"error": "仅接受指向本机当前端口的请求。"})
            return False
        if len(origins) > 1 or origins and origins[0] != f"http://{hosts[0]}":
            self._json(403, {"error": "请求来源与本机页面不一致。"})
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            self._json(403, {"error": "不接受跨站请求。"})
            return False
        return True

    # 仅提供固定首页及健康状态；不把 URL 转为本地文件路径。
    def do_GET(self) -> None:
        if not self._local_request():
            return
        if self.path == "/api/health":
            self._json(200, {"status": "ok", "mode": "rule_based_design"})
        elif self.path == "/favicon.ico":
            self._respond(204, b"", "image/x-icon")
        elif self.path == "/":
            try:
                content = Path(__file__).with_name("web.html").read_bytes()  # 唯一可读取的网页资源由项目随包提供。
            except OSError:
                self._json(503, {"error": "本地页面暂不可用。"})
                return
            self._respond(200, content, "text/html; charset=utf-8")
        else:
            self._json(404, {"error": "未找到此本地接口。"})

    # 验证来源、内容类型和长度后才读取 JSON，生成失败不返回历史中的重复结果。
    def do_POST(self) -> None:
        if not self._local_request():
            return
        if self.path != "/api/generate":
            self._json(404, {"error": "未找到此本地接口。"})
            return
        if self.headers.get_all("Transfer-Encoding"):
            self._json(400, {"error": "不支持分块或其他传输编码。"})
            return
        if (len(self.headers.get_all("Content-Type", [])) != 1 or self.headers.get_content_type() != "application/json"
                or self.headers.get_content_charset("utf-8") != "utf-8"):
            self._json(415, {"error": "请使用 UTF-8 的 application/json 请求。"})
            return
        lengths = self.headers.get_all("Content-Length", [])  # 明确且唯一的长度阻止不定长读取及重复长度歧义。
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10:
            self._json(411, {"error": "请求需要唯一有效的 Content-Length。"})
            return
        length = int(lengths[0])  # 长度已限制为十位以内，不接受符号、空格或负数。
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "请求体不能超过 32 KiB。"})
            return
        try:
            raw = self.rfile.read(length)  # 只读取已验证长度，客户端过早断开时拒绝不完整 JSON。
            if len(raw) != length:
                raise FacePromptError("请求体不完整。")
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields, parse_constant=_invalid_constant)  # 不自动接受其他 Unicode 编码。
            if not isinstance(body, dict) or "prompt" not in body or set(body) - {"prompt", "expression", "intensity", "cause"}:
                raise FacePromptError("请求必须包含 prompt，且仅可附加 expression、intensity、cause 字段。")
            # 缺省值与 Python/CLI 一致；生成器在接触共享账本前统一验证类型和组合。
            self._json(200, generate_prompt(body["prompt"], self.server.history, expression=body.get("expression"),
                                            intensity=body.get("intensity", "medium"), cause=body.get("cause", "")))
        except VariationExhausted as error:
            self._json(409, {"error": str(error)})
        except FacePromptError as error:
            self._json(400, {"error": str(error)})
        except (ValueError, RecursionError):
            self._json(400, {"error": "请求不是有效的 UTF-8 JSON。"})
        except (OSError, socket.timeout):
            self._json(408, {"error": "请求读取超时或连接已断开。"})
