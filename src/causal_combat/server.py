"""只监听回环的仙侠交互服务；固定资源和受限JSON输入，不接受远端或文件参数。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket

from .core import DEFAULT_TEXT, MODE, build_combat


MAX_BODY_BYTES = 32768  # JSON整体字节数限制，独立于简报的4000字符限制。
DEFAULTS = {"text": DEFAULT_TEXT, "charge": 0.8, "distance_m": 8, "shield": 50, "aim_offset_m": 0, "seed": 7}  # 页面和空JSON请求共用的设计参数。


# 拒绝重复字段，防止浏览器、代理和服务端对同一字段取值产生歧义。
def _unique_fields(pairs: list) -> dict:
    fields = {}  # 只在一次JSON对象解析期间持有用户数据。
    for name, value in pairs:  # 名称和值来自严格JSON解码器。
        if name in fields:
            raise ValueError("JSON字段不能重复。")
        fields[name] = value
    return fields


# 标准JSON不允许NaN或Infinity，不能交给后续数值计算。
def _invalid_constant(value: str):
    raise ValueError("请求必须使用标准JSON值。")


class CombatHTTPServer(ThreadingHTTPServer):
    """每条请求独立生成无共享可变状态的剧本，监听地址不能由客户端修改。"""

    daemon_threads = True  # 关闭服务不等待阻塞的客户端线程。

    # 正常端口范围1至65535；0仅供调用方申请临时回环端口验证。
    def __init__(self, port: int = 8766):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port必须是0至65535的整数。")
        super().__init__(("127.0.0.1", port), CombatRequestHandler)


class CombatRequestHandler(BaseHTTPRequestHandler):
    """只处理固定API；请求文本不写磁盘和访问日志，错误不暴露路径或运行时。"""

    server_version = "CausalCombat"  # 隐去默认Python版本信息。
    sys_version = ""  # 禁止父类追加运行时版本。

    # 有限超时防止客户端不发送完整请求而长期占用连接。
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    # 不记录URL、创作简报或原始请求到终端。
    def log_message(self, format: str, *args) -> None:
        pass

    # 框架级错误同样返回固定JSON，不反射原始HTTP内容。
    def send_error(self, code: int, message=None, explain=None) -> None:
        self._json(code, {"error": "HTTP请求无效或方法不受支持。"})

    # 安全响应头与显式关闭连接避免跨站嵌入、内容嗅探及请求体复用。
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

    # UTF-8且禁止非标准浮点结果；服务不开放任何跨域权限。
    def _json(self, status: int, payload: dict) -> None:
        self._respond(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

    # Host必须是当前回环端口，Origin若存在必须与Host精确同源。
    def _local_request(self) -> bool:
        hosts = self.headers.get_all("Host", [])  # 拒绝重复Host，不能只采用第一项。
        origins = self.headers.get_all("Origin", [])  # 非浏览器客户端允许省略Origin。
        sites = self.headers.get_all("Sec-Fetch-Site", [])  # 拒绝重复头及跨站浏览器请求。
        port = self.server.server_port  # 实际绑定端口，支持临时端口验证。
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

    # 固定首页、默认参数、健康状态；绝不将URL转换为文件路径。
    def do_GET(self) -> None:
        if not self._local_request():
            return
        if self.path == "/api/health":
            self._json(200, {"status": "ok", "mode": MODE})
        elif self.path == "/api/defaults":
            self._json(200, DEFAULTS)
        elif self.path in ("/", "/web.html"):
            try:
                content = Path(__file__).with_name("web.html").read_bytes()  # 唯一静态资源固定随包提供，不接收路径参数。
            except OSError:
                self._json(503, {"error": "本地页面暂不可用。"})
                return
            self._respond(200, content, "text/html; charset=utf-8")
        elif self.path == "/favicon.ico":
            self._respond(204, b"", "image/x-icon")
        else:
            self._json(404, {"error": "未找到此本地接口。"})

    # 核验来源、类型和唯一长度后才读取请求体；未知字段和错误类型一律拒绝。
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
            self._json(415, {"error": "请使用UTF-8的application/json请求。"})
            return
        if self.headers.get_all("Content-Encoding"):
            self._json(415, {"error": "不接受压缩或其他内容编码。"})
            return
        lengths = self.headers.get_all("Content-Length", [])  # 唯一的已知长度防止请求体边界歧义。
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10:
            self._json(411, {"error": "请求需要唯一有效的Content-Length。"})
            return
        length = int(lengths[0])  # 已拒绝负数、符号、空白和超长整数。
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "请求体不能超过32 KiB。"})
            return
        try:
            raw = self.rfile.read(length)  # 只读取声明的有限字节数。
            if len(raw) != length:
                raise ValueError("请求体不完整。")
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields, parse_constant=_invalid_constant)  # 拒绝重复键和非标准常量。
            if not isinstance(body, dict) or set(body).difference(DEFAULTS):
                raise ValueError("请求只支持text、charge、distance_m、shield、aim_offset_m、seed字段。")
            self._json(200, build_combat(**body))
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._json(400, {"error": "请求必须是有效UTF-8 JSON对象；仅接受支持的字段、非空简报及范围内的有限数值。"})
        except (OSError, socket.timeout):
            self._json(408, {"error": "请求读取超时或连接已断开。"})
