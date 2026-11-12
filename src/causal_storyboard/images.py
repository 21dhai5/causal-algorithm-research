"""可选图像适配器：只接受验证过的 PNG，绝不下载响应中的 URL。"""

import base64
import binascii
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import struct
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zlib

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 单张 PNG 的压缩文件上限。
MAX_RESPONSE_BYTES = 30 * 1024 * 1024  # HTTP 响应的读取上限。
GENERATION_KIND = "STORYBOARD_STILL_IMAGES_NOT_CONTINUOUS_VIDEO"  # 明确产物为分镜静帧。
_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}  # PNG 合法色深。


class ImageGenerationError(ValueError):
    """保存可公开的固定错误信息，不携带服务凭据或响应正文。"""


class ImageProvider(Protocol):
    # 返回 PNG 字节；调用方仍会独立验证内容后才保存。
    def generate(self, prompt: str) -> bytes: ...


class _NoRedirect(HTTPRedirectHandler):
    # 禁止任何重定向，避免授权头与付费请求被转发。
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ImageGenerationError("图像服务重定向已拒绝。")


# 计算普通或 Adam7 PNG 的各扫描段，用于有界解压与逐行过滤器验证。
def _scanlines(width: int, height: int, depth: int, color: int, interlace: int) -> list[tuple[int, int]]:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]  # 每像素通道数。
    passes = ((0, 0, 1, 1),) if not interlace else (  # Adam7 各遍的起点与步长。
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
    )
    rows = []  # 每段的行字节数与行数，不含行首过滤器字节。
    for x, y, dx, dy in passes:  # 当前遍的采样位置。
        columns = max(0, (width - x + dx - 1) // dx)  # 当前遍宽度。
        count = max(0, (height - y + dy - 1) // dy)  # 当前遍高度。
        if columns and count:
            rows.append(((columns * channels * depth + 7) // 8, count))
    return rows


# 校验像素数据并移除非像素辅助元数据，避免损坏元数据导致有效像素文件无法读取。
def _validate_png(data: bytes) -> bytes:
    if not isinstance(data, bytes) or len(data) > MAX_IMAGE_BYTES or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ImageGenerationError("图像不是大小受限的有效 PNG。")
    offset = 8  # 下一个 PNG 块的文件偏移。
    header = None  # 已验证的 IHDR 字段。
    palette = False  # 索引色必须在 IDAT 前提供调色板。
    idat_state = 0  # 0 未开始、1 连续读取中、2 数据块已经结束。
    compressed = bytearray()  # 所有连续 IDAT 组成的单一 zlib 流。
    chunks = 0  # 限制恶意碎片块数量。
    ended = False  # 只有末尾合法 IEND 才能完成验证。
    raster = bytearray(data[:8])  # 仅保留构成静态像素所需的块，不保留文本、色彩配置或动画元数据。
    palette_entries = 0  # 索引透明度长度不能超过调色板条目数。
    transparency = False  # 透明度块不能重复，且必须位于数据块之前。
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]  # 当前块负载长度。
        kind = data[offset + 4:offset + 8]  # 四字节 PNG 块名称。
        end = offset + 8 + size  # CRC 前的位置。
        chunks += 1
        if end + 4 > len(data) or chunks > 4096 or not kind.isalpha() or kind[2] & 32:
            raise ImageGenerationError("PNG 块结构无效。")
        payload = data[offset + 8:end]  # CRC 验证后的块负载。
        if zlib.crc32(data[offset + 4:end]) != struct.unpack_from(">I", data, end)[0]:
            raise ImageGenerationError("PNG 校验和无效。")
        if header is None and kind != b"IHDR":
            raise ImageGenerationError("PNG 缺少首部。")
        if kind == b"IHDR":
            if header is not None or size != 13:
                raise ImageGenerationError("PNG 首部无效。")
            header = struct.unpack(">IIBBBBB", payload)
            width, height, depth, color, compression, filtering, interlace = header  # 尺寸与编码参数。
            if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16777216):
                raise ImageGenerationError("PNG 尺寸超出限制。")
            if depth not in _DEPTHS.get(color, ()) or compression or filtering or interlace not in (0, 1):
                raise ImageGenerationError("PNG 编码参数无效。")
        elif kind == b"PLTE":
            if palette or idat_state or color in (0, 4) or not size or size % 3 or size > 768:
                raise ImageGenerationError("PNG 调色板无效。")
            if color == 3 and size // 3 > 2 ** depth:
                raise ImageGenerationError("PNG 调色板超出色深。")
            palette = True
            palette_entries = size // 3
        elif kind == b"tRNS":
            if transparency or idat_state or color not in (0, 2, 3):
                raise ImageGenerationError("PNG 透明度块顺序或颜色类型无效。")
            if ((color == 0 and size != 2) or (color == 2 and size != 6)
                    or (color == 3 and (not palette or not 0 < size <= palette_entries))):
                raise ImageGenerationError("PNG 透明度块长度无效。")
            if color in (0, 2) and any(value >= 2 ** depth for value in struct.unpack(">" + "H" * (size // 2), payload)):
                raise ImageGenerationError("PNG 透明度样本超出色深。")
            transparency = True
        elif kind == b"IDAT":
            if idat_state == 2 or color == 3 and not palette:
                raise ImageGenerationError("PNG 数据块顺序无效。")
            idat_state = 1
            compressed.extend(payload)
        elif kind == b"IEND":
            if size or not idat_state:
                raise ImageGenerationError("PNG 结束块无效。")
            ended = True
        elif not kind[0] & 32:
            raise ImageGenerationError("PNG 包含未知关键块。")
        if kind in (b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"):
            raster.extend(data[offset:end + 4])
        if kind != b"IDAT" and idat_state == 1:
            idat_state = 2
        offset = end + 4
        if ended:
            break
    if not ended or offset != len(data):
        raise ImageGenerationError("PNG 文件不完整。")
    rows = _scanlines(width, height, depth, color, interlace)  # 各遍应有的扫描行布局。
    expected = sum((size + 1) * count for size, count in rows)  # 解压后字节数上限。
    if expected > 64 * 1024 * 1024:
        raise ImageGenerationError("PNG 解压尺寸超出限制。")
    inflater = zlib.decompressobj()  # 只接受一个完整压缩流。
    try:
        raw = inflater.decompress(compressed, expected + 1)  # 多读一个字节以识别解压炸弹。
    except zlib.error:
        raise ImageGenerationError("PNG 压缩内容无效。") from None
    if len(raw) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ImageGenerationError("PNG 扫描数据不完整或超出限制。")
    position = 0  # 当前扫描行过滤器的位置。
    for size, count in rows:  # 当前遍的行长与行数。
        for _ in range(count):
            if raw[position] > 4:
                raise ImageGenerationError("PNG 行过滤器无效。")
            position += size + 1
    return bytes(raster)


# 拒绝符号链接和 Windows 目录联接，调用方必须提供已存在的真实父目录。
def _check_directory_path(directory: Path) -> None:
    for part in (directory, *directory.parents):  # 逐级检查，避免解析时悄悄跟随链接。
        if part.is_symlink() or part.is_junction():
            raise ValueError("输出路径不能经过符号链接或目录联接。")


# 独占创建明确指定的新目录；已有目录和文件均拒绝，不清理用户数据。
def reserve_output_directory(directory: str | Path) -> Path:
    target = Path(directory).absolute()  # 保留待检查的路径，不先解析符号链接。
    _check_directory_path(target)
    target.mkdir(exist_ok=False)
    return target


class HttpImageProvider:
    # 仅保存私有配置；默认对象 repr 不显示端点、模型或密钥。
    def __init__(self, endpoint: str, model: str, key: str, *, timeout: float = 120):
        try:
            parsed = urlsplit(endpoint)  # 在创建请求前检查目标与凭据边界。
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None or "#" in endpoint
                    or any(character.isspace() or ord(character) < 32 for character in endpoint)
                    or parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1")):
                raise ValueError
            parsed.port  # 提前拒绝非法端口，避免请求时泄露目标字符串。
            if not model.strip() or not key.strip() or not math.isfinite(timeout) or not 0 < timeout <= 120:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ImageGenerationError("图像配置无效；远程端点必须使用 HTTPS，超时必须在 120 秒内。") from None
        self._endpoint = endpoint  # 用户显式指定的完整 POST 端点，不自动拼接路径。
        self._model = model  # 当前端点要求的模型标识。
        self._key = key  # 仅用于请求授权头，不进入输出或 repr。
        self._timeout = timeout  # 单次请求超时秒数，不自动重试以免重复计费。

    # 只有三个必需环境变量齐全才能创建实际服务适配器。
    @classmethod
    def from_env(cls) -> "HttpImageProvider":
        endpoint = os.environ.get("STORYBOARD_IMAGE_URL", "")  # 明确选定的 API 端点。
        model = os.environ.get("STORYBOARD_IMAGE_MODEL", "")  # 服务端模型标识。
        key = os.environ.get("STORYBOARD_IMAGE_KEY", "")  # 环境密钥，不接受命令行参数。
        if not endpoint or not model or not key:
            raise ImageGenerationError("缺少图像配置：需要 STORYBOARD_IMAGE_URL、STORYBOARD_IMAGE_MODEL、STORYBOARD_IMAGE_KEY。")
        return cls(endpoint, model, key)

    # 单次 POST 兼容约定的 JSON 架构；只读取 base64 PNG，不重试、不跟随 URL。
    def generate(self, prompt: str) -> bytes:
        body = json.dumps({"model": self._model, "prompt": prompt, "n": 1, "size": "1024x1024", "output_format": "png"}).encode("utf-8")  # 明确请求一张 PNG。
        try:
            request = Request(self._endpoint, data=body, headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json"}, method="POST")  # 密钥仅在授权头内传送。
            with build_opener(_NoRedirect()).open(request, timeout=self._timeout) as response:  # 禁止任何自动重定向。
                if not 200 <= response.getcode() < 300:
                    raise ImageGenerationError("图像服务未返回成功状态。")
                payload = response.read(MAX_RESPONSE_BYTES + 1)  # 不信任 Content-Length。
        except HTTPError as error:  # 只暴露合法状态码，不读取或打印错误正文。
            status = error.code if isinstance(error.code, int) and 100 <= error.code <= 599 else 0  # 安全状态码。
            error.close()
            raise ImageGenerationError(f"图像服务 HTTP 错误（状态 {status}）。") from None
        except (URLError, OSError, HTTPException, ValueError, UnicodeError):
            raise ImageGenerationError("图像服务请求失败。") from None
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ImageGenerationError("图像服务响应超出大小限制。")
        try:
            encoded = json.loads(payload)["data"][0]["b64_json"]  # 仅支持内嵌 PNG，不处理响应 URL。
            if not isinstance(encoded, str) or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
                raise ValueError
            image = base64.b64decode(encoded, validate=True)  # 严格解码并拒绝非 base64 数据。
        except (ValueError, KeyError, IndexError, TypeError, binascii.Error, RecursionError):
            raise ImageGenerationError("图像服务必须返回大小受限的 base64 PNG。") from None
        return _validate_png(image)


# 更新每个镜头的真实生成状态；独占保存成功后才公开相对路径，失败不阻断后续镜头。
def generate_images(board: dict, provider: ImageProvider, directory: str | Path) -> dict:
    target = Path(directory).absolute()  # 只能写入调用方显式提供的目录。
    _check_directory_path(target)
    if not target.is_dir():
        raise ValueError("图像输出目录必须预先保留。")
    board["generation_kind"] = GENERATION_KIND
    seen = set()  # 已处理镜头标识，拒绝重名以避免重复请求与覆盖。
    for shot in board["shots"]:  # 每个镜头单独生成、校验和保存。
        shot["image"] = {"status": "failed", "path": None, "error": "图像生成或保存失败。"}
        try:
            shot_id = shot["id"]  # 文件名只允许受约束的镜头标识。
            if not isinstance(shot_id, str) or not re.fullmatch(r"s[0-9]{2,6}", shot_id) or shot_id in seen:
                continue
            seen.add(shot_id)
            path = target / (shot_id + ".png")  # 不使用供应方提供的任何文件名或路径。
            if path.exists() or path.is_symlink():
                continue
            image = _validate_png(provider.generate(shot["image_prompt"]))  # 验证并规范化实际供应方返回的像素内容。
            _check_directory_path(target)  # 长时间请求后再次检查，拒绝期间被替换为链接的目录。
            with path.open("xb") as output:  # 独占创建，已有文件永不覆盖。
                output.write(image)
            shot["image"] = {"status": "generated", "path": path.name}
        except Exception:  # 不输出任意供应方异常，防止凭据及正文随错误泄露。
            continue
    return board
