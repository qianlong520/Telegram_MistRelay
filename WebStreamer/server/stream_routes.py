# Taken from megadlbot_oss <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/webserver/routes.py>
# Thanks to Eyaadh <https://github.com/eyaadh>

import re
import time
import math
import logging
import secrets
import mimetypes
import os
import subprocess
import json
from pathlib import Path
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from WebStreamer.bot import multi_clients, work_loads, channel_accessible_clients
from WebStreamer.server.exceptions import FIleNotFound, InvalidHash
from WebStreamer import Var, utils, StartTime, __version__, StreamBot
from db import fetch_recent_downloads, get_all_configs, get_config, set_config
import configer

# 导入pyrogram错误类型以检测限流
try:
    from pyrogram import errors as pyrogram_errors
except ImportError:
    pyrogram_errors = None

# Docker Python SDK（用于系统管理模块）
try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None

logger = logging.getLogger("routes")

# 前端静态文件路径
FRONTEND_DIST = Path("/app/web/dist")

routes = web.RouteTableDef()

def is_flood_wait_error(e: Exception) -> bool:
    """检查异常是否是Telegram限流错误"""
    if pyrogram_errors:
        # 检查是否是FloodWait错误类型
        if isinstance(e, (pyrogram_errors.FloodWait, pyrogram_errors.Flood)):
            return True
        elif hasattr(pyrogram_errors, 'FloodWait') and isinstance(e, pyrogram_errors.FloodWait):
            return True
    
    # 检查错误消息中是否包含限流关键词
    error_str = str(e)
    error_type = type(e).__name__
    return (
        'FLOOD_WAIT' in error_str or 
        'FloodWait' in error_str or 
        'flood_420' in error_type or
        'Flood' in error_type
    )

@routes.get("/api/status", allow_head=True)
async def api_status_handler(_):
    """API状态接口"""
    # 安全获取bot用户名（可能在Telegram初始化完成前调用）
    bot_username = ""
    if StreamBot:
        try:
            if hasattr(StreamBot, 'username') and StreamBot.username:
                bot_username = "@" + StreamBot.username
            elif hasattr(StreamBot, 'get_me'):
                try:
                    bot_info = await StreamBot.get_me()
                    bot_username = "@" + (bot_info.username if bot_info.username else "unknown")
                except Exception as e:
                    # 检查是否是Telegram限流错误
                    if is_flood_wait_error(e):
                        bot_username = "限流中"
                    else:
                        bot_username = "@unknown"
            else:
                bot_username = "@unknown"
        except Exception as e:
            # 检查是否是Telegram限流错误
            if is_flood_wait_error(e):
                bot_username = "限流中"
            else:
                bot_username = "@unknown"
    
    return web.json_response(
        {
            "server_status": "running",
            "uptime": utils.get_readable_time(time.time() - StartTime),
            "telegram_bot": bot_username or "@unknown",
            "connected_bots": len(multi_clients),
            "loads": dict(
                ("bot" + str(c + 1), l)
                for c, (_, l) in enumerate(
                    sorted(work_loads.items(), key=lambda x: x[1], reverse=True)
                )
            ),
            "version": f"v{__version__}",
        }
    )

@routes.get("/", allow_head=True)
async def root_route_handler(request: web.Request):
    """根路径:返回前端页面"""
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        response = web.FileResponse(index_file)
        # index.html 使用协商缓存,允许浏览器缓存但每次验证
        response.headers['Cache-Control'] = 'no-cache'
        return response
    else:
        # 降级到 API 状态(开发环境或前端未构建时)
        logger.warning("前端 index.html 不存在,返回 API 状态")
        return await api_status_handler(request)


@routes.get("/api/system/docker/status", allow_head=True)
async def docker_status_handler(request: web.Request):
    """获取Docker容器状态"""
    try:
        # 检查是否在Docker容器内
        if not os.path.exists("/.dockerenv"):
            return web.json_response({
                "success": False,
                "error": "不在Docker容器内运行",
                "in_docker": False
            })
        
        # 检查Docker SDK是否可用
        if not DOCKER_AVAILABLE:
            return web.json_response({
                "success": False,
                "error": "Docker Python SDK不可用，请安装docker包",
                "in_docker": True
            })
        
        # 使用Docker Python SDK查找当前容器
        try:
            client = docker.from_env()
            container = None
            
            # 方法1: 尝试通过容器ID查找（从cgroup获取）
            container_id = None
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except:
                pass
            
            # 方法2: 尝试通过容器名称查找（优先使用docker-compose的container_name）
            container_names = ["mistrelay"]  # docker-compose.yml中的container_name
            
            # 方法3: 尝试通过HOSTNAME查找
            hostname = os.environ.get("HOSTNAME", "")
            if hostname and hostname not in container_names:
                container_names.append(hostname)
            
            # 如果从cgroup获取到ID，优先使用ID查找
            if container_id:
                try:
                    container = client.containers.get(container_id)
                except docker.errors.NotFound:
                    pass
            
            # 如果ID查找失败，尝试通过名称查找
            if not container:
                for name in container_names:
                    try:
                        containers = client.containers.list(filters={"name": name})
                        if containers:
                            container = containers[0]
                            break
                    except:
                        continue
            
            # 如果还是找不到，尝试获取所有容器并匹配
            if not container:
                all_containers = client.containers.list(all=True)
                # 尝试通过ID匹配
                if container_id:
                    for c in all_containers:
                        if container_id in c.id or container_id in c.name:
                            container = c
                            break
                # 如果还是找不到，使用第一个运行中的容器（通常是当前容器）
                if not container and all_containers:
                    container = all_containers[0]
            
            if container:
                container.reload()  # 刷新容器信息
                return web.json_response({
                    "success": True,
                    "in_docker": True,
                    "container_name": container.name,
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else container.image.id,
                    "created": container.attrs.get("Created", "")
                })
            else:
                return web.json_response({
                    "success": False,
                    "error": "无法找到容器",
                    "in_docker": True
                })
        except docker.errors.APIError as e:
            logger.error(f"Docker API错误: {e}")
            return web.json_response({
                "success": False,
                "error": f"Docker API错误: {str(e)}"
            })
    except Exception as e:
        logger.error(f"获取Docker状态失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        })


@routes.post("/api/system/docker/restart")
async def docker_restart_handler(request: web.Request):
    """重启Docker容器（热重载）"""
    try:
        # 检查是否在Docker容器内
        if not os.path.exists("/.dockerenv"):
            return web.json_response({
                "success": False,
                "error": "不在Docker容器内运行，无法重启"
            })
        
        # 检查Docker SDK是否可用
        if not DOCKER_AVAILABLE:
            return web.json_response({
                "success": False,
                "error": "Docker Python SDK不可用，请安装docker包"
            })
        
        # 使用Docker Python SDK查找当前容器
        try:
            client = docker.from_env()
            container = None
            
            # 方法1: 尝试通过容器ID查找（从cgroup获取）
            container_id = None
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except:
                pass
            
            # 方法2: 尝试通过容器名称查找（优先使用docker-compose的container_name）
            container_names = ["mistrelay"]  # docker-compose.yml中的container_name
            
            # 方法3: 尝试通过HOSTNAME查找
            hostname = os.environ.get("HOSTNAME", "")
            if hostname and hostname not in container_names:
                container_names.append(hostname)
            
            # 如果从cgroup获取到ID，优先使用ID查找
            if container_id:
                try:
                    container = client.containers.get(container_id)
                except docker.errors.NotFound:
                    pass
            
            # 如果ID查找失败，尝试通过名称查找
            if not container:
                for name in container_names:
                    try:
                        containers = client.containers.list(filters={"name": name})
                        if containers:
                            container = containers[0]
                            break
                    except:
                        continue
            
            # 如果还是找不到，尝试获取所有容器并匹配
            if not container:
                all_containers = client.containers.list(all=True)
                # 尝试通过ID匹配
                if container_id:
                    for c in all_containers:
                        if container_id in c.id or container_id in c.name:
                            container = c
                            break
                # 如果还是找不到，使用第一个运行中的容器（通常是当前容器）
                if not container and all_containers:
                    container = all_containers[0]
            
            if container:
                container.restart(timeout=10)
                return web.json_response({
                    "success": True,
                    "message": f"容器 {container.name} 重启成功",
                    "container_name": container.name
                })
            else:
                return web.json_response({
                    "success": False,
                    "error": f"无法找到容器: {container_id}"
                })
        except docker.errors.APIError as e:
            logger.error(f"Docker API错误: {e}")
            return web.json_response({
                "success": False,
                "error": f"Docker API错误: {str(e)}"
            })
    except Exception as e:
        logger.error(f"重启Docker容器失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        })


@routes.get("/api/system/docker/logs", allow_head=True)
async def docker_logs_handler(request: web.Request):
    """获取Docker容器日志"""
    try:
        # 检查是否在Docker容器内
        if not os.path.exists("/.dockerenv"):
            return web.json_response({
                "success": False,
                "error": "不在Docker容器内运行"
            })
        
        # 检查Docker SDK是否可用
        if not DOCKER_AVAILABLE:
            return web.json_response({
                "success": False,
                "error": "Docker Python SDK不可用，请安装docker包"
            })
        
        # 获取容器ID或名称
        container_id = os.environ.get("HOSTNAME", "")
        if not container_id:
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except:
                pass
        
        if not container_id:
            container_id = "mistrelay"
        
        lines = int(request.query.get("lines", "100"))
        lines = max(1, min(lines, 1000))  # 限制在1-1000行
        
        # 使用Docker Python SDK查找当前容器
        try:
            client = docker.from_env()
            container = None
            
            # 方法1: 尝试通过容器ID查找（从cgroup获取）
            container_id = None
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except:
                pass
            
            # 方法2: 尝试通过容器名称查找（优先使用docker-compose的container_name）
            container_names = ["mistrelay"]  # docker-compose.yml中的container_name
            
            # 方法3: 尝试通过HOSTNAME查找
            hostname = os.environ.get("HOSTNAME", "")
            if hostname and hostname not in container_names:
                container_names.append(hostname)
            
            # 如果从cgroup获取到ID，优先使用ID查找
            if container_id:
                try:
                    container = client.containers.get(container_id)
                except docker.errors.NotFound:
                    pass
            
            # 如果ID查找失败，尝试通过名称查找
            if not container:
                for name in container_names:
                    try:
                        containers = client.containers.list(filters={"name": name})
                        if containers:
                            container = containers[0]
                            break
                    except:
                        continue
            
            # 如果还是找不到，尝试获取所有容器并匹配
            if not container:
                all_containers = client.containers.list(all=True)
                # 尝试通过ID匹配
                if container_id:
                    for c in all_containers:
                        if container_id in c.id or container_id in c.name:
                            container = c
                            break
                # 如果还是找不到，使用第一个运行中的容器（通常是当前容器）
                if not container and all_containers:
                    container = all_containers[0]
            
            if container:
                logs = container.logs(tail=lines, timestamps=False).decode('utf-8', errors='replace')
                return web.json_response({
                    "success": True,
                    "logs": logs,
                    "lines": lines
                })
            else:
                return web.json_response({
                    "success": False,
                    "error": f"无法找到容器: {container_id}"
                })
        except docker.errors.APIError as e:
            logger.error(f"Docker API错误: {e}")
            return web.json_response({
                "success": False,
                "error": f"Docker API错误: {str(e)}"
            })
    except Exception as e:
        logger.error(f"获取Docker日志失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        })


@routes.get("/api/config", allow_head=True)
async def get_config_handler(request: web.Request):
    """获取系统配置"""
    try:
        category = request.query.get('category')
        configs = get_all_configs(category=category)
        return web.json_response({
            "success": True,
            "data": configs
        })
    except Exception as e:
        logger.error(f"获取配置失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.post("/api/config")
async def update_config_handler(request: web.Request):
    """更新系统配置"""
    try:
        data = await request.json()
        
        # 验证请求数据
        if not isinstance(data, dict):
            return web.json_response({
                "success": False,
                "error": "请求数据格式错误"
            }, status=400)
        
        # 配置项定义：key -> (value_type, category, description)
        config_definitions = {
            'API_ID': ('int', 'telegram', 'Telegram API ID'),
            'API_HASH': ('string', 'telegram', 'Telegram API Hash'),
            'BOT_TOKEN': ('string', 'telegram', 'Telegram Bot Token'),
            'ADMIN_ID': ('int', 'telegram', 'Telegram管理员ID'),
            'FORWARD_ID': ('string', 'telegram', '转发ID'),
            'UP_TELEGRAM': ('bool', 'telegram', '是否上传到Telegram'),
            'UP_ONEDRIVE': ('bool', 'rclone', '是否启用rclone上传到OneDrive'),
            'RCLONE_REMOTE': ('string', 'rclone', 'rclone远程名称'),
            'RCLONE_PATH': ('string', 'rclone', 'OneDrive目标路径'),
            'AUTO_DELETE_AFTER_UPLOAD': ('bool', 'rclone', '上传后自动删除本地文件'),
            'SAVE_PATH': ('string', 'download', '下载保存路径'),
            'PROXY_IP': ('string', 'download', '代理IP'),
            'PROXY_PORT': ('string', 'download', '代理端口'),
            'RPC_SECRET': ('string', 'aria2', 'Aria2 RPC密钥'),
            'RPC_URL': ('string', 'aria2', 'Aria2 RPC URL'),
            'ENABLE_STREAM': ('bool', 'stream', '是否启用直链功能'),
            'BIN_CHANNEL': ('string', 'stream', '日志频道ID'),
            'STREAM_PORT': ('int', 'stream', 'Web服务器端口'),
            'STREAM_BIND_ADDRESS': ('string', 'stream', 'Web服务器绑定地址'),
            'STREAM_HASH_LENGTH': ('int', 'stream', '哈希长度'),
            'STREAM_HAS_SSL': ('bool', 'stream', '是否使用SSL'),
            'STREAM_NO_PORT': ('bool', 'stream', '是否隐藏端口'),
            'STREAM_FQDN': ('string', 'stream', '完全限定域名'),
            'STREAM_KEEP_ALIVE': ('bool', 'stream', '是否保持连接活跃'),
            'STREAM_PING_INTERVAL': ('int', 'stream', 'Ping间隔（秒）'),
            'STREAM_USE_SESSION_FILE': ('bool', 'stream', '是否使用会话文件'),
            'STREAM_ALLOWED_USERS': ('string', 'stream', '允许使用直链的用户列表'),
            'STREAM_AUTO_DOWNLOAD': ('bool', 'stream', '是否自动添加到下载队列'),
            'SEND_STREAM_LINK': ('bool', 'stream', '是否发送直链信息给用户'),
            'MULTI_BOT_TOKENS': ('list', 'stream', '多机器人Token列表'),
        }
        
        # 需要重启才能生效的配置项
        requires_restart = {
            'API_ID', 'API_HASH', 'BOT_TOKEN', 'ADMIN_ID', 'BIN_CHANNEL',
            'STREAM_PORT', 'STREAM_BIND_ADDRESS', 'STREAM_HASH_LENGTH',
            'STREAM_HAS_SSL', 'STREAM_NO_PORT', 'STREAM_FQDN',
            'STREAM_USE_SESSION_FILE', 'MULTI_BOT_TOKENS'
        }
        
        updated_count = 0
        errors = []
        needs_restart = False
        
        for key, value in data.items():
            if key in config_definitions:
                value_type, category, description = config_definitions[key]
                try:
                    set_config(key, value, value_type, category, description)
                    updated_count += 1
                    if key in requires_restart:
                        needs_restart = True
                except Exception as e:
                    errors.append(f"{key}: {str(e)}")
            else:
                errors.append(f"{key}: 未知的配置项")
        
        if errors:
            return web.json_response({
                "success": False,
                "error": f"部分配置更新失败: {', '.join(errors)}",
                "updated_count": updated_count,
                "needs_restart": needs_restart
            }, status=400)
        
        # 尝试热重载配置（对于不需要重启的配置）
        if not needs_restart:
            try:
                configer.reload_config()
                logger.info("配置已热重载")
            except Exception as e:
                logger.warning(f"配置热重载失败: {e}")
        
        return web.json_response({
            "success": True,
            "message": f"成功更新 {updated_count} 个配置项" + ("，需要重启服务才能生效" if needs_restart else "，配置已热重载"),
            "updated_count": updated_count,
            "needs_restart": needs_restart
        })
    except Exception as e:
        logger.error(f"更新配置失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.post("/api/config/reload")
async def reload_config_handler(request: web.Request):
    """手动触发配置重载"""
    try:
        configer.reload_config()
        logger.info("配置已手动重载")
        return web.json_response({
            "success": True,
            "message": "配置已重新加载"
        })
    except Exception as e:
        logger.error(f"配置重载失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/downloads", allow_head=True)
async def downloads_api_handler(request: web.Request):
    """
    API接口：返回下载记录JSON数据

    支持查询参数:
      - limit: 返回的最大记录数（默认 100，最大 500）
      - grouped: 是否按消息分组（默认 true）
    """
    try:
        limit_param = int(request.query.get("limit", "100"))
    except ValueError:
        limit_param = 100
    limit_param = max(1, min(limit_param, 500))
    
    grouped = request.query.get("grouped", "true").lower() == "true"

    if grouped:
        from db import fetch_downloads_grouped
        groups = fetch_downloads_grouped(limit_param)
        total_downloads = sum(len(g['downloads']) for g in groups)
        return web.json_response({
            "success": True,
            "limit": limit_param,
            "count": total_downloads,
            "group_count": len(groups),
            "grouped": True,
            "data": groups
        })
    else:
        records = fetch_recent_downloads(limit_param)
        return web.json_response({
            "success": True,
            "limit": limit_param,
            "count": len(records),
            "grouped": False,
            "data": records
        })


@routes.get("/api/monitor/trend", allow_head=True)
async def monitor_trend_handler(request: web.Request):
    """
    API接口：返回系统监控历史趋势数据
    """
    try:
        from monitor import monitor
        history = monitor.get_history()
        return web.json_response({
            "success": True,
            "data": history
        })
    except Exception as e:
        logger.error(f"获取监控数据失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/queue", allow_head=True)
async def queue_api_handler(request: web.Request):
    """
    API接口:返回消息队列状态
    """
    try:
        # 导入队列状态函数
        try:
            from WebStreamer.bot.plugins.stream import get_queue_status
            queue_status = await get_queue_status()
            return web.json_response({
                "success": True,
                **queue_status
            })
        except ImportError:
            # 如果直链功能未启用,返回空队列
            return web.json_response({
                "success": True,
                "current_processing": None,
                "waiting_count": 0,
                "waiting_items": [],
                "queue_size": 0
            })
    except Exception as e:
        logger.error(f"获取队列状态失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get(r"/{path:\S+}", allow_head=True)
async def stream_handler(request: web.Request):
    """处理流媒体请求、静态文件请求或 SPA 路由"""
    path = request.match_info["path"]
    
    # 1. API 路由优先级最高
    if path.startswith("api/"):
        # 这些路径应该由其他路由处理,如果到这里说明路由不存在
        raise web.HTTPNotFound(text="API endpoint not found")
    
    # 2. 静态资源处理 (assets/, favicon.ico, robots.txt 等)
    if path.startswith("assets/"):
        # 前端静态资源 (CSS, JS, 图片等)
        file_path = FRONTEND_DIST / path
        if file_path.exists() and file_path.is_file():
            response = web.FileResponse(file_path)
            # 添加强缓存头(1年),因为 Vite 构建的文件名包含哈希
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            return response
        raise web.HTTPNotFound(text="Static file not found")
    
    if path in ["favicon.ico", "robots.txt"]:
        file_path = FRONTEND_DIST / path
        if file_path.exists():
            return web.FileResponse(file_path)
        return web.Response(status=204)
    
    # 3. 尝试作为流媒体请求处理
    try:
        match = re.search(r"^([0-9a-f]{%s})(\d+)$" % (Var.HASH_LENGTH), path)
        if match:
            secure_hash = match.group(1)
            message_id = int(match.group(2))
            return await media_streamer(request, message_id, secure_hash)
        else:
            # 尝试从路径中提取消息ID
            message_id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
            return await media_streamer(request, message_id, secure_hash)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        # 连接错误,尝试 SPA 回退
        pass
    except (ValueError, TypeError, KeyError):
        # 不是有效的流媒体路径,尝试 SPA 回退
        pass
    except Exception as e:
        logger.debug(f"流媒体请求处理失败: {e}, 尝试 SPA 回退")
    
    # 4. SPA 回退: 所有其他路径返回 index.html (Vue Router)
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return web.FileResponse(index_file)
    
    # 如果前端文件不存在,返回 404
    raise web.HTTPNotFound(text="Not Found")


class_cache = {}

async def media_streamer(request: web.Request, message_id: int, secure_hash: str):
    range_header = request.headers.get("Range", 0)
    
    # 负载均衡：选择负载最小的客户端
    # 优先选择能访问频道的客户端，如果都不可用则使用所有客户端
    
    # 检查是否有可用的客户端
    if not work_loads:
        logger.error("没有可用的客户端")
        raise web.HTTPInternalServerError(text="No available clients")
    
    # 优先选择能访问频道的客户端
    if channel_accessible_clients:
        # 筛选出能访问频道且存在的客户端及其负载
        available_work_loads = {
            k: v for k, v in work_loads.items() 
            if k in channel_accessible_clients and k in multi_clients
        }
        if available_work_loads:
            index = min(available_work_loads, key=available_work_loads.get)
            logger.debug(f"从可访问频道的客户端中选择: 客户端 {index} (负载: {available_work_loads[index]})")
        else:
            # 如果没有可访问频道的客户端，回退到所有客户端
            logger.warning("没有能访问频道的客户端，回退到所有客户端")
            # 确保只选择存在的客户端
            valid_work_loads = {k: v for k, v in work_loads.items() if k in multi_clients}
            if not valid_work_loads:
                logger.error("没有有效的客户端")
                raise web.HTTPInternalServerError(text="No valid clients available")
            index = min(valid_work_loads, key=valid_work_loads.get)
    else:
        # 如果没有记录可访问的客户端，使用所有客户端
        # 确保只选择存在的客户端
        valid_work_loads = {k: v for k, v in work_loads.items() if k in multi_clients}
        if not valid_work_loads:
            logger.error("没有有效的客户端")
            raise web.HTTPInternalServerError(text="No valid clients available")
        index = min(valid_work_loads, key=valid_work_loads.get)
    
    # 验证索引有效性
    if index not in multi_clients:
        logger.error(f"选择的客户端索引 {index} 不存在于 multi_clients 中")
        raise web.HTTPInternalServerError(text=f"Client {index} not found")
    
    faster_client = multi_clients[index]
    
    if Var.MULTI_CLIENT:
        logger.info(f"Client {index} is now serving {request.remote}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logger.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        logger.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    logger.debug("before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(message_id)
    logger.debug("after calling get_file_properties")
    
    
    if utils.get_hash(file_id.unique_id, Var.HASH_LENGTH) != secure_hash:
        logger.debug(f"Invalid hash for message with ID {message_id}")
        raise InvalidHash
    
    file_size = file_id.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = (request.http_range.stop or file_size) - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )
    mime_type = file_id.mime_type
    file_name = utils.get_name(file_id)
    disposition = "attachment"

    if not mime_type:
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    if "video/" in mime_type or "audio/" in mime_type or "/html" in mime_type:
        disposition = "inline"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": f"{mime_type}",
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        },
    )

