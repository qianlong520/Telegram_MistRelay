# Taken from megadlbot_oss <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/webserver/__init__.py>
# Thanks to Eyaadh <https://github.com/eyaadh>
# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import logging
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from .stream_routes import routes

logger = logging.getLogger("server")


class _SuppressConnectAccessFilter(logging.Filter):
    """
    屏蔽常见扫描器/代理探测产生的 CONNECT access log。

    说明：aiohttp.access 的 record 内容依赖 aiohttp 版本与 formatter，
    这里用 getMessage() 做最稳妥的字符串匹配。
    """

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover
        try:
            msg = record.getMessage()
        except Exception:
            return True
        # 例：`"CONNECT  HTTP/1.0" 404 ...`
        if '"CONNECT ' in msg:
            return False
        return True


@web.middleware
async def error_handler_middleware(request, handler):
    """处理协议级别的错误，如 TLS 握手请求等"""
    try:
        # 常见扫描/代理探测：CONNECT 方法不属于本服务用途，直接静默返回
        if request.method == "CONNECT":
            return web.Response(status=404, text="Not Found")
        return await handler(request)
    except (BadStatusLine, ConnectionResetError, OSError) as e:
        # 检查是否是 TLS 握手请求（常见的安全扫描）
        error_str = str(e)
        if "Invalid method" in error_str or "BadStatusLine" in error_str:
            # 静默处理 TLS 握手请求和无效的 HTTP 请求
            # 这些通常是扫描或恶意请求，不需要记录为错误
            logger.debug(f"收到无效请求（可能是 TLS/HTTPS 扫描）: {request.remote}")
            return web.Response(status=400, text="Bad Request")
        # 其他连接错误也静默处理
        logger.debug(f"连接错误: {request.remote} - {error_str}")
        return web.Response(status=400, text="Bad Request")
    except web.HTTPException:
        # 诸如 404/405 等属于正常 HTTP 流程，不应记录为 ERROR/堆栈
        raise
    except Exception as e:
        # 其他未预期的错误正常记录
        logger.error(f"处理请求时出错: {e}", exc_info=True)
        raise


@web.middleware
async def compression_middleware(request, handler):
    """添加 gzip 压缩支持"""
    response = await handler(request)
    
    # 只压缩文本类型的响应
    if isinstance(response, web.FileResponse):
        content_type = response.content_type
        if content_type and any(t in content_type for t in ['text/', 'application/javascript', 'application/json']):
            # 检查客户端是否支持 gzip
            accept_encoding = request.headers.get('Accept-Encoding', '')
            if 'gzip' in accept_encoding.lower():
                response.enable_compression()
    
    return response


def web_server():
    logger.info("Initializing..")
    # 屏蔽 CONNECT 探测带来的 access log 噪音(不影响其它请求日志)
    logging.getLogger("aiohttp.access").addFilter(_SuppressConnectAccessFilter())
    web_app = web.Application(client_max_size=30000000)
    
    # 添加中间件(顺序很重要)
    web_app.middlewares.append(compression_middleware)
    web_app.middlewares.append(error_handler_middleware)
    
    web_app.add_routes(routes)
    logger.info("Added routes")
    return web_app

