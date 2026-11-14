"""仅监听回环的固定资源与JSON接口；无模型、图像、存储或跨域接口。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket

from .core import CharacterPromptError, MODE, generate_multiview_prompt, get_defaults, strict_json_loads


MAX_BODY_BYTES = 256 * 1024  # JSON请求的字节上限，独立于各字段字符上限。
MAX_PAGE_BYTES = 2 * 1024 * 1024  # 固定相邻页面的最大读取字节数。
REQUEST_FIELDS = {"description", "style", "views", "features"}  # HTTP请求唯一允许的字段，全部可省略。


class CharacterHTTPServer(ThreadingHTTPServer):
    """每个连接独立处理文本；绑定地址固定为127.0.0.1，不允许公开监听。"""

    daemon_threads = True  # 服务退出时不等待未完成的客户端请求线程。

    # 端口0供调用方申请临时测试端口；命令行只接受1至65535。
    def __init__(self, port: int = 8767):
        if type(port) is not int or not 0 <= port <= 65535:
            raise CharacterPromptError("port必须是0至65535的整数。")
        super().__init__(("127.0.0.1", port), CharacterRequestHandler)

    # 断开的客户端等线程异常不打印带私有路径的默认回溯。
    def handle_error(self, request, client_address) -> None:
        pass


class CharacterRequestHandler(BaseHTTPRequestHandler):
    """固定路由与严格同源校验；错误不回显请求内容、磁盘路径或运行时信息。"""

    server_version = "CausalCharacter"  # 响应中只公开服务名。
    sys_version = ""  # 避免父类追加Python运行时版本。

    # 有限读写超时，限制未完整发送的客户端长期占用线程。
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    # 请求文本、地址与作者简报不写入终端访问日志。
    def log_message(self, format: str, *args) -> None:
        pass

    # 未支持方法和框架解析错误也使用固定中文JSON，不回显HTTP原文。
    def send_error(self, code: int, message=None, explain=None) -> None:
        self._json(code, {"error": "HTTP请求无效或方法不受支持。"})

    # 所有响应关闭连接并设置页面安全策略，不开放外部脚本、网络或跨域权限。
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
            if self.command != "HEAD":
                self.wfile.write(content)
        except OSError:
            pass

    # 结果严格输出UTF-8标准JSON；无缓存、无CORS响应头。
    def _json(self, status: int, payload: dict) -> None:
        self._respond(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

    # 精确校验唯一Host、Origin和Fetch-Site，阻断DNS重绑定与跨站请求。
    def _local_request(self) -> bool:
        hosts = self.headers.get_all("Host", [])  # Host必须唯一并包含当前实际端口。
        origins = self.headers.get_all("Origin", [])  # 非浏览器客户端可省略Origin，存在时必须同源。
        sites = self.headers.get_all("Sec-Fetch-Site", [])  # 浏览器来源元数据同样不接受重复值。
        port = self.server.server_port  # 实际回环监听端口，包含测试时分配的临时值。
        if len(hosts) != 1 or hosts[0] not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._json(403, {"error": "仅接受指向本机当前端口的请求。"})
            return False
        if len(origins) > 1 or origins and origins[0] != f"http://{hosts[0]}":
            self._json(403, {"error": "请求来源与本机页面不一致。"})
            return False
        if len(sites) > 1 or sites and sites[0] not in ("same-origin", "none"):
            self._json(403, {"error": "不接受跨站请求。"})
            return False
        return True

    # 仅公开固定相邻web.html、健康检查与共享默认值，不将URL映射到磁盘路径。
    def do_GET(self) -> None:
        if not self._local_request():
            return
        if self.path == "/api/health":
            self._json(200, {"status": "ok", "mode": MODE})
        elif self.path == "/api/defaults":
            self._json(200, get_defaults())
        elif self.path in ("/", "/web.html"):
            try:
                with Path(__file__).with_name("web.html").open("rb") as page:  # 只读取随包的固定页面。
                    content = page.read(MAX_PAGE_BYTES + 1)  # 额外一字节用于检测超限。
                if len(content) > MAX_PAGE_BYTES:
                    raise OSError("固定页面超限。")
            except OSError:
                self._json(503, {"error": "本地页面暂不可用。"})
                return
            self._respond(200, content, "text/html; charset=utf-8")
        elif self.path == "/favicon.ico":
            self._respond(204, b"", "image/x-icon")
        else:
            self._json(404, {"error": "未找到此本地接口。"})

    # 先校验来源、媒体类型与唯一长度，再有界读取；省略字段取默认，显式null不取默认。
    def do_POST(self) -> None:
        if not self._local_request():
            return
        if self.path != "/api/generate":
            self._json(404, {"error": "未找到此本地接口。"})
            return
        if self.headers.get_all("Transfer-Encoding"):
            self._json(400, {"error": "不支持分块或其他传输编码。"})
            return
        types = self.headers.get_all("Content-Type", [])  # 只支持可选UTF-8 charset的唯一JSON媒体类型。
        if len(types) != 1 or re.fullmatch(r'application/json(?:\s*;\s*charset\s*=\s*(?:"utf-8"|utf-8))?\s*', types[0], re.IGNORECASE) is None:
            self._json(415, {"error": "请使用UTF-8的application/json请求。"})
            return
        if self.headers.get_all("Content-Encoding"):
            self._json(415, {"error": "不接受压缩或其他内容编码。"})
            return
        lengths = self.headers.get_all("Content-Length", [])  # 拒绝重复值、负值、符号和长度歧义。
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10:
            self._json(411, {"error": "请求需要唯一有效的Content-Length。"})
            return
        length = int(lengths[0])  # 已知非负且最多十位的请求字节长度。
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "请求体不能超过256 KiB。"})
            return
        try:
            raw = self.rfile.read(length)  # 不读取超过客户端声明和服务上限的字节。
            if len(raw) != length:
                raise CharacterPromptError("请求体不完整。")
            body = strict_json_loads(raw)  # 标准JSON解码，拒绝重复字段与非有限常量。
            if not isinstance(body, dict) or set(body).difference(REQUEST_FIELDS):
                raise CharacterPromptError("请求必须是JSON对象，只支持description、style、views、features。")
            for field in ("views", "features"):  # Python接口的None默认约定不适用于显式HTTP null。
                if field in body and not isinstance(body[field], list):
                    raise CharacterPromptError(f"{field}必须是数组，不能为null。")
            self._json(200, generate_multiview_prompt(**body))
        except CharacterPromptError as error:
            self._json(400, {"error": str(error)})
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._json(400, {"error": "请求字段或JSON结构无效，请检查类型与长度上限。"})
        except (OSError, socket.timeout):
            self._json(408, {"error": "请求读取超时或连接已断开。"})
