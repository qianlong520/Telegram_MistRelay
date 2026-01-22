# Taken from megadlbot_oss <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/webserver/__init__.py>
# Thanks to Eyaadh <https://github.com/eyaadh>
# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import logging
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from .stream_routes import routes

logger = logging.getLogger("server")


@web.middleware
async def error_handler_middleware(request, handler):
    """处理协议级别的错误，如 TLS 握手请求等"""
    try:
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
    except Exception as e:
        # 其他未预期的错误正常记录
        logger.error(f"处理请求时出错: {e}", exc_info=True)
        raise


def web_server():
    logger.info("Initializing..")
    web_app = web.Application(client_max_size=30000000)
    web_app.middlewares.append(error_handler_middleware)
    web_app.add_routes(routes)
    logger.info("Added routes")
    return web_app

