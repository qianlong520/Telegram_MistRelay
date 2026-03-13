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
import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from WebStreamer.bot import (
    multi_clients,
    work_loads,
    channel_accessible_clients,
    select_stream_bot,
    get_available_channel_bot_count,
    get_bot_runtime_snapshot,
    mark_bot_failure,
    mark_bot_success,
)
from WebStreamer.server.exceptions import FIleNotFound, InvalidHash
from WebStreamer.server.ws_manager import ws_manager
from WebStreamer import Var, utils, StartTime, __version__, StreamBot
from db import (
    fetch_recent_downloads, get_all_configs, get_config, set_config,
    get_download_id_by_gid, get_download_by_id, get_upload_by_id,
    mark_download_failed, update_upload_status, mark_upload_failed,
    delete_download_record, browse_tg_media, get_tg_media_stats,
    get_tg_media_record_by_message_id, get_tg_media_records_by_media_group,
    list_all_tg_media_records, delete_tg_media_records,
)
import configer

# 导入全局 aria2 客户端
# 优先直接从app模块获取（客户端在app.py启动时就已经初始化）
# 如果app模块不可用，则从utils模块获取（通过set_aria2_client设置）
def get_aria2_client():
    """获取全局aria2客户端实例（优先从utils模块获取，然后从app模块）"""
    # 首先尝试从utils模块获取（因为set_aria2_client会在启动时设置）
    try:
        from WebStreamer.bot.plugins.stream_modules.utils import aria2_client
        if aria2_client is not None:
            return aria2_client
    except ImportError:
        pass
    except Exception:
        pass
    
    # 如果utils模块不可用，尝试从app模块直接获取
    try:
        import sys
        import importlib
        
        # 尝试导入app模块（如果还没有导入）
        if 'app' not in sys.modules:
            try:
                importlib.import_module('app')
            except ImportError:
                pass
        
        if 'app' in sys.modules:
            app_module = sys.modules['app']
            if hasattr(app_module, 'client') and app_module.client is not None:
                return app_module.client
        
        # 如果sys.modules中没有，尝试直接导入
        app_module = importlib.import_module('app')
        if hasattr(app_module, 'client') and app_module.client is not None:
            return app_module.client
    except Exception:
        pass
    
    # 如果都失败，记录错误
    logger.error("无法获取Aria2客户端！请检查服务是否正常启动")
    return None

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

# psutil（用于系统资源监控）
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

logger = logging.getLogger("routes")

# 前端静态文件路径
FRONTEND_DIST = Path("/app/web/dist")

routes = web.RouteTableDef()

# 缩略图生成信号量（限制并发数为1，实现"一个一个加载"）
thumbnail_semaphore = asyncio.Semaphore(1)

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

# ======================== 认证 API ========================

@routes.post("/api/auth/login")
async def auth_login_handler(request: web.Request):
    """用户登录，返回 JWT token"""
    try:
        body = await request.json()
        username = body.get("username", "").strip()
        password = body.get("password", "")
        if not username or not password:
            return web.json_response({"success": False, "error": "用户名和密码不能为空"}, status=400)

        from db import get_user_by_username
        from auth import verify_password, create_token
        user = get_user_by_username(username)
        if not user or not verify_password(password, user["password_hash"]):
            return web.json_response({"success": False, "error": "用户名或密码错误"}, status=401)

        token = create_token(user["id"], user["username"])
        return web.json_response({
            "success": True,
            "token": token,
            "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
        })
    except Exception as e:
        logger.error(f"登录失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": "登录失败"}, status=500)


@routes.get("/api/auth/me", allow_head=True)
async def auth_me_handler(request: web.Request):
    """获取当前登录用户信息"""
    user = request.get("user")
    if not user:
        return web.json_response({"success": False, "error": "未登录"}, status=401)
    from db import get_user_by_id
    db_user = get_user_by_id(user["uid"])
    if not db_user:
        return web.json_response({"success": False, "error": "用户不存在"}, status=401)
    return web.json_response({"success": True, "user": db_user})


@routes.post("/api/auth/password")
async def auth_change_password_handler(request: web.Request):
    """修改密码"""
    try:
        user = request.get("user")
        if not user:
            return web.json_response({"success": False, "error": "未登录"}, status=401)
        body = await request.json()
        old_password = body.get("old_password", "")
        new_password = body.get("new_password", "")
        if not old_password or not new_password:
            return web.json_response({"success": False, "error": "请填写旧密码和新密码"}, status=400)
        if len(new_password) < 6:
            return web.json_response({"success": False, "error": "新密码长度不能少于6位"}, status=400)

        from db import get_user_by_username, update_user_password
        from auth import verify_password, hash_password
        db_user = get_user_by_username(user["sub"])
        if not db_user or not verify_password(old_password, db_user["password_hash"]):
            return web.json_response({"success": False, "error": "旧密码错误"}, status=400)

        update_user_password(db_user["id"], hash_password(new_password))
        return web.json_response({"success": True, "message": "密码修改成功"})
    except Exception as e:
        logger.error(f"修改密码失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": "修改密码失败"}, status=500)


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
                ("bot" + str(index + 1), work_loads.get(index, 0))
                for index in sorted(multi_clients.keys())
            ),
            "bot_metrics": dict(
                (
                    "bot" + str(index + 1),
                    {
                        "active_requests": metrics["active_requests"],
                        "cooldown_remaining": metrics["cooldown_remaining"],
                        "failure_streak": metrics["failure_streak"],
                        "throughput_bps": metrics["throughput_bps"],
                        "bytes_served": metrics["bytes_served"],
                    },
                )
                for index, metrics in get_bot_runtime_snapshot().items()
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
            except Exception:
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
                    except Exception:
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
            except Exception:
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
                    except Exception:
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
            except Exception:
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
            except Exception:
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
                    except Exception:
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


@routes.get("/api/system/resources", allow_head=True)
async def system_resources_handler(request: web.Request):
    """获取系统资源使用情况（CPU、内存、硬盘）"""
    try:
        if not PSUTIL_AVAILABLE:
            return web.json_response({
                "success": False,
                "error": "psutil不可用，请安装psutil包"
            })
        
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=0.1)
        
        # 内存使用情况
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_total = memory.total
        memory_used = memory.used
        memory_available = memory.available
        
        # 硬盘使用情况（获取根目录所在分区）
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_total = disk.total
        disk_used = disk.used
        disk_free = disk.free
        
        return web.json_response({
            "success": True,
            "data": {
                "cpu": {
                    "percent": round(cpu_percent, 2)
                },
                "memory": {
                    "percent": round(memory_percent, 2),
                    "total": memory_total,
                    "used": memory_used,
                    "available": memory_available
                },
                "disk": {
                    "percent": round(disk_percent, 2),
                    "total": disk_total,
                    "used": disk_used,
                    "free": disk_free
                }
            }
        })
    except Exception as e:
        logger.error(f"获取系统资源失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        })


@routes.get("/api/system/docker/logs/ws")
async def docker_logs_ws_handler(request: web.Request):
    """WebSocket实时推送Docker容器日志"""
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    
    try:
        # 检查是否在Docker容器内
        if not os.path.exists("/.dockerenv"):
            await ws.send_json({
                "type": "error",
                "message": "不在Docker容器内运行"
            })
            await ws.close()
            return ws
        
        # 检查Docker SDK是否可用
        if not DOCKER_AVAILABLE:
            await ws.send_json({
                "type": "error",
                "message": "Docker Python SDK不可用，请安装docker包"
            })
            await ws.close()
            return ws
        
        # 获取初始日志行数（从查询参数）
        tail_lines = int(request.query.get("tail", "100"))
        tail_lines = max(1, min(tail_lines, 1000))  # 限制在1-1000行
        
        # 查找容器
        container = None
        try:
            client = docker.from_env()
            container_id = None
            
            # 方法1: 尝试通过容器ID查找（从cgroup获取）
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            container_id = line.split("/")[-1].strip()
                            break
            except Exception:
                pass
            
            # 方法2: 尝试通过容器名称查找
            container_names = ["mistrelay"]
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
                    except Exception:
                        continue
            
            # 如果还是找不到，尝试获取所有容器并匹配
            if not container:
                all_containers = client.containers.list(all=True)
                if container_id:
                    for c in all_containers:
                        if container_id in c.id or container_id in c.name:
                            container = c
                            break
                if not container and all_containers:
                    container = all_containers[0]
            
            if not container:
                await ws.send_json({
                    "type": "error",
                    "message": "无法找到容器"
                })
                await ws.close()
                return ws
            
            # 先发送历史日志
            try:
                logs = container.logs(tail=tail_lines, timestamps=False).decode('utf-8', errors='replace')
                await ws.send_json({
                    "type": "history",
                    "logs": logs
                })
            except Exception as e:
                logger.error(f"获取历史日志失败: {e}", exc_info=True)
                await ws.send_json({
                    "type": "error",
                    "message": f"获取历史日志失败: {str(e)}"
                })
            
            # 开始实时流式推送日志
            await ws.send_json({
                "type": "stream_start",
                "message": "开始实时日志流"
            })
            
            # 使用Docker的logs API的stream模式（异步处理）
            try:
                import asyncio
                import threading
                
                # 创建事件来控制日志流
                stop_event = threading.Event()
                log_queue = asyncio.Queue()
                
                # 获取当前事件循环
                loop = asyncio.get_running_loop()

                def read_logs_thread():
                    """在后台线程中读取Docker日志流"""
                    try:
                        log_stream = container.logs(stream=True, follow=True, timestamps=False, tail=0)
                        
                        for log_chunk in log_stream:
                            if stop_event.is_set() or ws.closed:
                                break
                            
                            try:
                                log_line = log_chunk.decode('utf-8', errors='replace').rstrip('\n\r')
                                if log_line:
                                    # 将日志行放入队列
                                    asyncio.run_coroutine_threadsafe(
                                        log_queue.put(log_line),
                                        loop
                                    )
                            except Exception as e:
                                logger.error(f"处理日志行失败: {e}", exc_info=True)
                                continue
                                
                    except Exception as e:
                        logger.error(f"日志流线程错误: {e}", exc_info=True)
                        if not ws.closed:
                            asyncio.run_coroutine_threadsafe(
                                ws.send_json({
                                    "type": "error",
                                    "message": f"日志流错误: {str(e)}"
                                }),
                                loop
                            )
                
                # 启动后台线程读取日志
                log_thread = threading.Thread(target=read_logs_thread, daemon=True)
                log_thread.start()
                
                # 从队列中读取日志并发送
                try:
                    while not ws.closed and not stop_event.is_set():
                        try:
                            # 等待日志行，设置超时以便定期检查连接状态
                            log_line = await asyncio.wait_for(log_queue.get(), timeout=1.0)
                            await ws.send_json({
                                "type": "log",
                                "line": log_line
                            })
                        except asyncio.TimeoutError:
                            # 超时是正常的，继续循环检查连接状态
                            continue
                        except Exception as e:
                            logger.error(f"发送日志行失败: {e}")
                            break
                finally:
                    # 停止日志流线程
                    stop_event.set()
                    log_thread.join(timeout=2)
                    
                        
            except Exception as e:
                logger.error(f"日志流错误: {e}", exc_info=True)
                await ws.send_json({
                    "type": "error",
                    "message": f"日志流错误: {str(e)}"
                })
                
        except docker.errors.APIError as e:
            logger.error(f"Docker API错误: {e}")
            await ws.send_json({
                "type": "error",
                "message": f"Docker API错误: {str(e)}"
            })
        except Exception as e:
            logger.error(f"WebSocket日志流错误: {e}", exc_info=True)
            await ws.send_json({
                "type": "error",
                "message": f"错误: {str(e)}"
            })
            
    except Exception as e:
        logger.error(f"WebSocket连接错误: {e}", exc_info=True)
        try:
            await ws.send_json({
                "type": "error",
                "message": f"连接错误: {str(e)}"
            })
        except Exception:
            pass
    
    finally:
        await ws.close()
    
    return ws


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
            'UP_GOOGLE_DRIVE': ('bool', 'rclone', '是否上传到Google Drive'),
            'GOOGLE_DRIVE_REMOTE': ('string', 'rclone', 'Google Drive Rclone远程名称（默认gdrive），需与rclone.conf中的配置名称一致'),
            'GOOGLE_DRIVE_PATH': ('string', 'rclone', 'Google Drive上传路径（默认/Downloads）'),
            'AUTO_DELETE_AFTER_UPLOAD': ('bool', 'rclone', '上传后自动删除本地文件'),
            'SAVE_PATH': ('string', 'download', '下载保存路径'),
            'PROXY_IP': ('string', 'download', '代理IP'),
            'PROXY_PORT': ('string', 'download', '代理端口'),
            'SKIP_SMALL_FILES': ('bool', 'download', '是否跳过小于指定大小的媒体文件'),
            'MIN_FILE_SIZE_MB': ('int', 'download', '最小文件大小（MB），小于此大小的文件将被跳过'),
            'RPC_SECRET': ('string', 'aria2', 'Aria2 RPC密钥'),
            'RPC_URL': ('string', 'aria2', 'Aria2 RPC URL'),
            'MAX_CONCURRENT_UPLOADS': ('int', 'upload', '最大并发上传数（默认10）'),
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
            'STREAM_TG_DISK_ONLY': ('bool', 'stream', '是否只使用TG网盘直转频道'),
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
        
        # 配置已保存到数据库，下次使用时将从数据库读取
        # 对于需要重启的配置，提示用户重启服务
        # 对于不需要重启的配置，下次使用时自动从数据库读取最新值
        
        return web.json_response({
            "success": True,
            "message": f"成功更新 {updated_count} 个配置项" + ("，需要重启服务才能生效" if needs_restart else "，下次使用时将从数据库读取最新配置"),
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
    """手动触发配置重载（从config.yml重新导入到数据库）"""
    try:
        from db import init_config_from_yaml
        # 从config.yml重新导入到数据库
        imported = init_config_from_yaml()
        logger.info("配置已从config.yml重新导入到数据库")
        return web.json_response({
            "success": True,
            "message": "配置已从config.yml重新导入到数据库，下次使用时将从数据库读取最新配置",
            "imported": imported
        })
    except Exception as e:
        logger.error(f"配置重载失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/rclone/config", allow_head=True)
async def get_rclone_config_handler(request: web.Request):
    """获取 Rclone 配置文件内容"""
    try:
        # Rclone 配置文件路径 (容器内挂载路径)
        rclone_config_path = Path("/root/.config/rclone/rclone.conf")
        
        # 检查文件是否存在
        if not rclone_config_path.exists():
            return web.json_response({
                "success": True,
                "content": "",
                "file_path": str(rclone_config_path),
                "exists": False,
                "message": "配置文件不存在,请先创建配置"
            })
        
        # 读取配置文件
        try:
            with open(rclone_config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return web.json_response({
                "success": True,
                "content": content,
                "file_path": str(rclone_config_path),
                "exists": True
            })
        except Exception as e:
            logger.error(f"读取 Rclone 配置文件失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": f"读取配置文件失败: {str(e)}",
                "file_path": str(rclone_config_path)
            }, status=500)
            
    except Exception as e:
        logger.error(f"获取 Rclone 配置失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.post("/api/rclone/config")
async def save_rclone_config_handler(request: web.Request):
    """保存 Rclone 配置文件内容"""
    try:
        data = await request.json()
        
        # 验证请求数据
        if not isinstance(data, dict) or 'content' not in data:
            return web.json_response({
                "success": False,
                "error": "请求数据格式错误,需要包含 content 字段"
            }, status=400)
        
        content = data.get('content', '')
        
        # Rclone 配置文件路径 (容器内挂载路径)
        rclone_config_path = Path("/root/.config/rclone/rclone.conf")
        backup_path = Path("/root/.config/rclone/rclone.conf.bak")
        
        # 确保目录存在
        rclone_config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 基本验证:检查配置格式(可选,简单检查是否包含配置节)
        if content.strip():
            # 检查是否包含至少一个配置节 [remote_name]
            import re
            if not re.search(r'\[[\w\-]+\]', content):
                logger.warning("配置内容格式可能有误:未找到配置节")
                # 不阻止保存,只是警告
        
        # 如果原文件存在,创建备份
        if rclone_config_path.exists():
            try:
                import shutil
                shutil.copy2(rclone_config_path, backup_path)
                logger.info(f"已备份原配置文件到: {backup_path}")
            except Exception as e:
                logger.warning(f"创建备份文件失败: {e}")
                # 备份失败不阻止保存
        
        # 保存新配置
        try:
            with open(rclone_config_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"Rclone 配置已更新: {rclone_config_path}")
            
            return web.json_response({
                "success": True,
                "message": "配置已保存,修改将在下次上传时生效",
                "file_path": str(rclone_config_path),
                "backup_path": str(backup_path) if backup_path.exists() else None
            })
        except Exception as e:
            logger.error(f"写入 Rclone 配置文件失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": f"保存配置文件失败: {str(e)}"
            }, status=500)
            
    except Exception as e:
        logger.error(f"保存 Rclone 配置失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/rclone/remotes", allow_head=True)
async def get_rclone_remotes_handler(request: web.Request):
    """获取 rclone.conf 中所有已配置的 remote"""
    try:
        # Rclone 配置文件路径
        rclone_config_path = Path("/root/.config/rclone/rclone.conf")
        
        # 检查文件是否存在
        if not rclone_config_path.exists():
            return web.json_response({
                "success": True,
                "remotes": []
            })
        
        # 读取并解析配置文件
        try:
            with open(rclone_config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析 remote 配置
            remotes = []
            import re
            
            # 匹配所有 [remote_name] 格式的行
            remote_pattern = re.compile(r'^\[([^\]]+)\]', re.MULTILINE)
            remote_names = remote_pattern.findall(content)
            
            # 为每个 remote 提取类型信息
            for remote_name in remote_names:
                # 查找该 remote 下的 type 配置
                type_pattern = re.compile(
                    rf'\[{re.escape(remote_name)}\].*?^type\s*=\s*(.+?)$',
                    re.MULTILINE | re.DOTALL
                )
                type_match = type_pattern.search(content)
                remote_type = type_match.group(1).strip() if type_match else "unknown"
                
                remotes.append({
                    "name": remote_name,
                    "type": remote_type
                })
            
            logger.info(f"解析到 {len(remotes)} 个 rclone remote")
            
            return web.json_response({
                "success": True,
                "remotes": remotes
            })
            
        except Exception as e:
            logger.error(f"解析 Rclone 配置文件失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": f"解析配置文件失败: {str(e)}"
            }, status=500)
            
    except Exception as e:
        logger.error(f"获取 Rclone remotes 失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/rclone/about", allow_head=True)
async def get_rclone_about_handler(request: web.Request):
    """获取 remote 容量信息"""
    try:
        remote = request.query.get('remote', '').strip()

        if not remote:
            return web.json_response({
                "success": False,
                "error": "remote 参数不能为空"
            }, status=400)

        cmd = ['rclone', 'about', f'{remote}:', '--json']
        logger.info(f"执行 rclone about 命令: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20
            )
        except subprocess.TimeoutExpired:
            logger.error("rclone about 命令超时")
            return web.json_response({
                "success": False,
                "error": "获取网盘容量超时,请重试"
            }, status=504)

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "未知错误"
            if re.search(r"unsupported|not supported|doesn'?t support|quota", error_msg, re.IGNORECASE):
                return web.json_response({
                    "success": True,
                    "supported": False,
                    "remote": remote,
                    "error": error_msg
                })

            logger.error(f"rclone about 命令失败: {error_msg}")
            return web.json_response({
                "success": False,
                "error": f"获取网盘容量失败: {error_msg}"
            }, status=500)

        try:
            about = json.loads(result.stdout or '{}')
        except json.JSONDecodeError as e:
            logger.error(f"解析 rclone about 输出失败: {e}")
            return web.json_response({
                "success": False,
                "error": "解析网盘容量信息失败"
            }, status=500)

        numeric_fields = ["total", "used", "free", "trashed", "other", "objects"]
        data = {}
        for field in numeric_fields:
            value = about.get(field)
            data[field] = value if isinstance(value, (int, float)) else None

        if all(data[field] is None for field in ["total", "used", "free"]):
            return web.json_response({
                "success": True,
                "supported": False,
                "remote": remote,
                "error": "当前网盘暂不支持容量统计"
            })

        return web.json_response({
            "success": True,
            "supported": True,
            "remote": remote,
            "data": data
        })

    except Exception as e:
        logger.error(f"获取 Rclone 容量信息失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/rclone/browse", allow_head=True)
async def browse_drive_handler(request: web.Request):
    """浏览云盘文件和目录"""
    try:
        remote = request.query.get('remote', 'onedrive')
        path = request.query.get('path', '/')
        
        # 验证参数
        if not remote:
            return web.json_response({
                "success": False,
                "error": "remote 参数不能为空"
            }, status=400)
        
        # 构建 rclone 路径
        rclone_path = f"{remote}:{path}"
        
        # 调用 rclone lsjson 命令
        try:
            import subprocess
            import json
            
            cmd = ['rclone', 'lsjson', rclone_path, '--no-modtime=false']
            
            logger.info(f"执行 rclone 命令: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                logger.error(f"rclone 命令失败: {error_msg}")
                return web.json_response({
                    "success": False,
                    "error": f"获取文件列表失败: {error_msg}"
                }, status=500)
            
            # 解析 JSON 输出
            items_raw = json.loads(result.stdout)
            
            # 转换为统一格式
            # 转换为统一格式
            items = []
            
            # 处理父目录路径: 确保不以/开头(rclone路径习惯), 且不为/
            parent_path = path.strip('/')
            
            for item in items_raw:
                name = item.get("Name", "")
                rel_path = item.get("Path", "") # rclone lsjson返回的是相对路径
                
                # 构建完整路径
                if parent_path:
                    full_path = f"{parent_path}/{rel_path}"
                else:
                    full_path = rel_path
                    
                items.append({
                    "name": name,
                    "path": full_path, # 返回完整路径
                    "size": item.get("Size", 0),
                    "mimeType": item.get("MimeType", ""),
                    "modTime": item.get("ModTime", ""),
                    "isDir": item.get("IsDir", False),
                    "id": item.get("ID", "")  # 添加文件ID
                })
            
            logger.info(f"成功获取 {len(items)} 个文件/目录")
            
            return web.json_response({
                "success": True,
                "remote": remote,
                "path": path,
                "items": items
            })
            
        except subprocess.TimeoutExpired:
            logger.error("rclone 命令超时")
            return web.json_response({
                "success": False,
                "error": "获取文件列表超时,请重试"
            }, status=504)
        except json.JSONDecodeError as e:
            logger.error(f"解析 rclone 输出失败: {e}")
            return web.json_response({
                "success": False,
                "error": "解析文件列表失败"
            }, status=500)
        except Exception as e:
            logger.error(f"执行 rclone 命令失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": f"执行命令失败: {str(e)}"
            }, status=500)
            
    except Exception as e:
        logger.error(f"浏览云盘失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/rclone/thumbnail", allow_head=True)
async def get_thumbnail_handler(request: web.Request):
    """获取文件缩略图(使用 VFS 本地生成)"""
    try:
        remote = request.query.get('remote')
        path = request.query.get('path')
        # 获取当前目录(用于拼接完整路径)
        current_dir = request.query.get('dir', '/')
        
        if not remote or not path:
            return web.json_response({
                "success": False,
                "error": "remote 和 path 参数不能为空"
            }, status=400)

        # 兼容旧逻辑:构建完整路径
        # 如果 path 是相对路径且提供了 current_dir,则尝试拼接
        if current_dir and current_dir != '/':
            clean_dir = current_dir.strip('/')
            # 如果 path 不包含目录前缀,则拼接
            if not path.startswith(clean_dir + '/'):
                path = f"{clean_dir}/{path}"
        
        # 确保路径开头没有 /
        path = path.lstrip('/')
        
        try:
            # 导入 VFS 管理器和缩略图生成器
            import sys
            sys.path.insert(0, '/app')
            from rclone_vfs_manager import get_vfs_manager
            from thumbnail_generator import get_thumbnail_generator
            
            vfs_manager = get_vfs_manager()
            thumb_generator = get_thumbnail_generator()
            
            # 确保 remote 已挂载
            if not vfs_manager.ensure_mounted(remote):
                return web.json_response({
                    "success": False,
                    "error": f"无法挂载 remote: {remote}"
                }, status=500)
            
            # 获取文件在挂载点的本地路径
            local_file_path = vfs_manager.get_file_path(remote, path)
            if not local_file_path:
                return web.json_response({
                    "success": False,
                    "error": "无法获取文件路径"
                }, status=500)
            
            # 生成缩略图 (使用信号量限制并发，并放入线程池避免阻塞主循环)
            async with thumbnail_semaphore:
                thumbnail_path = await asyncio.get_running_loop().run_in_executor(
                    None,
                    thumb_generator.generate_thumbnail,
                    remote,
                    path,
                    local_file_path
                )
            
            if not thumbnail_path:
                return web.json_response({
                    "success": False,
                    "error": "生成缩略图失败"
                }, status=500)
            
            # 生成缓存key(用于前端请求)
            import hashlib
            cache_key = hashlib.md5(f"{remote}:{path}".encode()).hexdigest()
            
            # 返回缩略图URL
            thumbnail_url = f"/api/rclone/thumbnail/serve/{remote}/{cache_key}.webp"
            
            return web.json_response({
                "success": True,
                "thumbnail_url": thumbnail_url
            })
            
        except ImportError as e:
            logger.error(f"导入模块失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": f"系统模块加载失败: {str(e)}"
            }, status=500)
        except Exception as e:
            logger.error(f"生成缩略图失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": str(e)
            }, status=500)
            
    except Exception as e:
        logger.error(f"缩略图处理失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/rclone/thumbnail/serve/{remote}/{filename}", allow_head=True)
async def serve_thumbnail_handler(request: web.Request):
    """提供缩略图文件服务"""
    try:
        remote = request.match_info['remote']
        filename = request.match_info['filename']
        
        # 导入缩略图生成器
        import sys
        sys.path.insert(0, '/app')
        from thumbnail_generator import get_thumbnail_generator
        
        thumb_generator = get_thumbnail_generator()
        
        # 构建缩略图文件路径
        thumbnail_path = thumb_generator.cache_dir / remote / filename
        
        if not thumbnail_path.exists():
            return web.Response(
                text="缩略图不存在",
                status=404
            )
        
        # 返回文件
        return web.FileResponse(
            thumbnail_path,
            headers={
                'Cache-Control': 'public, max-age=86400',  # 缓存24小时
                'Content-Type': 'image/webp'
            }
        )
        
    except Exception as e:
        logger.error(f"提供缩略图失败: {e}", exc_info=True)
        return web.Response(text=str(e), status=500)


@routes.get("/api/rclone/file", allow_head=True)
async def get_rclone_file_handler(request: web.Request):
    """获取云盘文件内容(支持流式传输和Range请求)"""
    try:
        remote = request.query.get('remote')
        path = request.query.get('path')
        is_download = request.query.get('download', 'false').lower() == 'true'
        
        if not remote or not path:
            return web.json_response({
                "success": False,
                "error": "remote 和 path 参数不能为空"
            }, status=400)
            
        # 获取 VFS 管理器
        from rclone_vfs_manager import get_vfs_manager
        vfs_manager = get_vfs_manager()
        
        # 确保 remote 已挂载
        if not vfs_manager.ensure_mounted(remote):
            return web.json_response({
                "success": False,
                "error": f"无法挂载 remote: {remote}"
            }, status=500)
        
        # 获取文件在挂载点的本地路径
        local_file_path = vfs_manager.get_file_path(remote, path)
        if not local_file_path or not local_file_path.exists():
            return web.json_response({
                "success": False,
                "error": "文件不存在或无法访问"
            }, status=404)
            
        # 准备响应头
        headers = {}
        if is_download:
            filename = path.split('/')[-1]
            # 编码文件名以支持非 ASCII 字符
            from urllib.parse import quote
            encoded_filename = quote(filename)
            headers['Content-Disposition'] = f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}'
            
        # 使用 aiohttp 的 FileResponse 直接服务本地文件
        return web.FileResponse(local_file_path, headers=headers)
            
    except Exception as e:
        logger.error(f"获取文件失败: {e}", exc_info=True)
        return web.Response(text=str(e), status=500)


@routes.delete("/api/rclone/file")
async def delete_rclone_file_handler(request: web.Request):
    """删除云盘文件或目录"""
    try:
        remote = request.query.get('remote')
        path = request.query.get('path')
        is_dir = request.query.get('is_dir', 'false').lower() == 'true'
        
        if not remote or not path:
            return web.json_response({
                "success": False,
                "error": "remote 和 path 参数不能为空"
            }, status=400)
            
        # 构建 rclone 路径
        rclone_path = f"{remote}:{path}"
        
        try:
            import subprocess
            
            # 根据类型选择命令
            if is_dir:
                # 删除目录及其内容
                cmd = ['rclone', 'purge', rclone_path]
            else:
                # 删除单个文件
                cmd = ['rclone', 'deletefile', rclone_path]
            
            logger.info(f"执行删除操作: {' '.join(cmd)}")
            
            # 在线程池中执行耗时操作
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                # 如果是 deletefile 但文件不存在，rclone 可能会报错，这里视情况处理
                # 但 purge 也会报错如果目录不存在
                logger.error(f"删除失败: {error_msg}")
                return web.json_response({
                    "success": False,
                    "error": f"删除失败: {error_msg}"
                }, status=500)
            
            logger.info(f"成功删除: {rclone_path}")
            return web.json_response({
                "success": True,
                "message": "删除成功"
            })
            
        except subprocess.TimeoutExpired:
            logger.error("删除超时")
            return web.json_response({
                "success": False,
                "error": "删除操作超时"
            }, status=504)
        except Exception as e:
            logger.error(f"删除失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": f"删除失败: {str(e)}"
            }, status=500)
            
    except Exception as e:
        logger.error(f"处理删除请求失败: {e}", exc_info=True)
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


@routes.get("/api/downloads/statistics", allow_head=True)
async def downloads_statistics_handler(request: web.Request):
    """
    API接口：返回下载统计信息
    """
    try:
        from db import get_download_statistics
        stats = get_download_statistics()
        return web.json_response({
            "success": True,
            "data": stats
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"获取下载统计失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.delete("/api/downloads/all")
async def delete_all_downloads_handler(request: web.Request):
    """
    API接口：删除所有下载记录、上传记录和媒体记录
    """
    try:
        from db import delete_all_downloads
        result = delete_all_downloads()
        return web.json_response({
            "success": True,
            "message": f"已删除 {result['deleted_downloads']} 条下载记录、{result['deleted_uploads']} 条上传记录和 {result['deleted_media']} 条媒体记录",
            "data": result
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"删除所有记录失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


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


@routes.get("/api/uploads/statistics", allow_head=True)
async def uploads_statistics_handler(request: web.Request):
    """
    API接口：返回上传统计信息
    """
    try:
        from db import get_upload_statistics
        stats = get_upload_statistics()
        return web.json_response({
            "success": True,
            "data": stats
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"获取上传统计失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/uploads", allow_head=True)
async def uploads_api_handler(request: web.Request):
    """
    API接口：返回上传记录JSON数据
    
    支持查询参数:
      - limit: 返回的最大记录数（默认 100，最大 500）
      - status: 按状态过滤（uploading/completed/failed/pending等）
      - upload_target: 按上传目标过滤（onedrive/telegram）
    """
    try:
        limit_param = int(request.query.get("limit", "100"))
    except ValueError:
        limit_param = 100
    limit_param = max(1, min(limit_param, 500))
    
    status_filter = request.query.get("status")
    upload_target_filter = request.query.get("upload_target")
    
    try:
        from db import fetch_recent_uploads
        records = fetch_recent_uploads(
            limit=limit_param,
            status=status_filter,
            upload_target=upload_target_filter
        )
        return web.json_response({
            "success": True,
            "limit": limit_param,
            "count": len(records),
            "data": records
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"获取上传记录失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/ws/status")
async def ws_status_handler(request: web.Request):
    """
    WebSocket 端点：实时推送下载/上传/清理状态更新
    """
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    
    try:
        # 添加连接到管理器
        await ws_manager.add_connection(ws)
        
        # 发送初始状态
        try:
            from db import get_download_statistics, get_upload_statistics
            download_stats = get_download_statistics()
            upload_stats = get_upload_statistics()
            
            await ws.send_json({
                "type": "initial",
                "data": {
                    "downloads": download_stats,
                    "uploads": upload_stats
                }
            })
        except Exception as e:
            logger.error(f"发送初始状态失败: {e}")
        
        # 保持连接，等待客户端关闭
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                # 可以处理客户端发送的消息（如果需要）
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                except Exception:
                    pass
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"WebSocket 错误: {ws.exception()}")
                break
            elif msg.type == web.WSMsgType.CLOSE:
                break
                
    except Exception as e:
        logger.error(f"WebSocket 连接错误: {e}", exc_info=True)
    finally:
        # 移除连接
        await ws_manager.remove_connection(ws)
        await ws.close()
    
    return ws


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


# ==================== 下载任务控制 API ====================

@routes.post("/api/downloads/{gid}/retry")
async def retry_download_handler(request: web.Request):
    """重试下载任务（重新提交到aria2）"""
    try:
        gid = request.match_info["gid"]
        
        client = get_aria2_client()
        if not client:
            logger.error("Aria2客户端未初始化，这不应该发生！请检查服务启动流程")
            return web.json_response({
                "success": False,
                "error": "Aria2客户端未初始化，请检查服务是否正常启动"
            }, status=503)
        
        # 获取下载记录
        download_id = get_download_id_by_gid(gid)
        if not download_id:
            return web.json_response({
                "success": False,
                "error": "找不到下载记录"
            }, status=404)
        
        download_record = get_download_by_id(download_id)
        if not download_record:
            return web.json_response({
                "success": False,
                "error": "下载记录不存在"
            }, status=404)
        
        source_url = download_record.get('source_url')
        if not source_url:
            return web.json_response({
                "success": False,
                "error": "无法获取下载源URL，无法重试"
            }, status=400)
        
        try:
            # 尝试移除旧任务（如果还在aria2中）
            try:
                remove_result = await client.remove(gid)
                # 检查返回结果中是否包含错误
                if remove_result and isinstance(remove_result, dict) and 'error' in remove_result:
                    error_info = remove_result['error']
                    error_msg = error_info.get('message', '') if isinstance(error_info, dict) else str(error_info)
                    # 如果错误是"not found"，这是正常的（历史遗留记录），静默处理
                    if 'not found' in error_msg.lower():
                        logger.debug(f"移除旧任务失败（任务已不存在，历史遗留记录）: {error_msg}")
                    else:
                        logger.debug(f"移除旧任务失败: {error_msg}")
            except Exception as remove_err:
                # 如果移除失败（任务可能已经不存在），继续执行
                error_msg = str(remove_err)
                if 'not found' not in error_msg.lower():
                    logger.debug(f"移除旧任务失败（可能已不存在）: {remove_err}")
            
            # 重新提交到aria2
            result = await client.add_uri(uris=[source_url])
            
            if not result or 'result' not in result:
                return web.json_response({
                    "success": False,
                    "error": "重新提交到aria2失败"
                }, status=500)
            
            new_gid = result.get('result')
            
            # 更新数据库中的 gid 和状态
            from db import get_connection
            now_iso = datetime.utcnow().isoformat(timespec="seconds") + 'Z'
            with get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "UPDATE downloads SET gid = ?, status = 'pending', error_message = NULL, retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                    (new_gid, now_iso, download_id)
                )
                conn.commit()
            
            return web.json_response({
                "success": True,
                "message": f"任务已重新提交到aria2，新GID: {new_gid}",
                "new_gid": new_gid
            })
        except Exception as e:
            error_msg = str(e)
            # 如果是Aria2任务不存在的错误，忽略它（历史遗留记录）
            if 'not found' in error_msg.lower():
                logger.info(f"重试下载任务时Aria2任务不存在（历史遗留记录）: {gid}")
                # 即使任务不存在，也尝试重新提交
                try:
                    result = await client.add_uri(uris=[source_url])
                    if result and 'result' in result:
                        new_gid = result.get('result')
                        # 更新数据库中的 gid 和状态
                        from db import get_connection
                        now_iso = datetime.utcnow().isoformat(timespec="seconds") + 'Z'
                        with get_connection() as conn:
                            conn.row_factory = sqlite3.Row
                            cur = conn.cursor()
                            cur.execute(
                                "UPDATE downloads SET gid = ?, status = 'pending', error_message = NULL, retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                                (new_gid, now_iso, download_id)
                            )
                            conn.commit()
                        
                        return web.json_response({
                            "success": True,
                            "message": f"任务已重新提交到aria2（旧任务不存在，已跳过），新GID: {new_gid}",
                            "new_gid": new_gid
                        })
                except Exception as retry_err:
                    logger.error(f"重新提交任务失败: {retry_err}", exc_info=True)
            
            logger.error(f"重试下载任务失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": error_msg
            }, status=500)
    except Exception as e:
        logger.error(f"重试下载任务API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.delete("/api/downloads/{gid}")
async def delete_download_handler(request: web.Request):
    """删除下载任务（从aria2移除，并删除数据库记录）"""
    try:
        gid = request.match_info["gid"]
        
        # 先尝试从Aria2移除任务
        client = get_aria2_client()
        aria2_removed = False
        if client:
            try:
                result = await client.remove(gid)
                if 'error' not in result:
                    aria2_removed = True
                else:
                    error_info = result['error']
                    error_msg = error_info.get('message', '删除失败') if isinstance(error_info, dict) else str(error_info)
                    # 如果任务不存在（Aria2重启后任务会消失），这是正常的，继续删除数据库记录
                    error_msg_lower = error_msg.lower()
                    if any(keyword in error_msg_lower for keyword in ['not found', 'is not found', '不存在', '找不到']):
                        logger.info(f"Aria2任务 {gid} 不存在（Aria2重启后任务已消失），将删除数据库记录")
                    else:
                        # 其他错误，记录但不阻止删除数据库记录
                        logger.warning(f"从Aria2移除任务失败: {error_msg}，将继续删除数据库记录")
            except Exception as e:
                error_msg = str(e)
                error_msg_lower = error_msg.lower()
                # 如果任务不存在（Aria2重启后任务会消失），这是正常的，继续删除数据库记录
                if any(keyword in error_msg_lower for keyword in ['not found', 'is not found', '不存在', '找不到']):
                    logger.info(f"Aria2任务 {gid} 不存在（Aria2重启后任务已消失），将删除数据库记录")
                else:
                    logger.warning(f"从Aria2移除任务失败: {error_msg}，将继续删除数据库记录")
        else:
            logger.warning("Aria2客户端未初始化，将直接删除数据库记录")
        
        # 无论Aria2任务是否存在，都删除数据库中的下载记录
        download_id = get_download_id_by_gid(gid)
        if download_id:
            try:
                result = delete_download_record(download_id, delete_local_file=False)  # 不删除本地文件，只删除记录
                if result.get('success'):
                    message = f"任务 {gid} 已删除"
                    if aria2_removed:
                        message += "（Aria2任务和数据库记录已删除）"
                    else:
                        message += "（Aria2任务不存在，已删除数据库记录）"
                    return web.json_response({
                        "success": True,
                        "message": message,
                        "data": result
                    })
                else:
                    return web.json_response({
                        "success": False,
                        "error": result.get('error', '删除数据库记录失败')
                    }, status=400)
            except Exception as e:
                logger.error(f"删除数据库记录失败: {e}", exc_info=True)
                return web.json_response({
                    "success": False,
                    "error": f"删除数据库记录失败: {str(e)}"
                }, status=500)
        else:
            # 数据库中没有记录，只返回成功（Aria2任务可能已经不存在）
            if aria2_removed:
                return web.json_response({
                    "success": True,
                    "message": f"任务 {gid} 已从Aria2删除（数据库中没有记录）"
                })
            else:
                return web.json_response({
                    "success": True,
                    "message": f"任务 {gid} 不存在（Aria2和数据库中都没有记录）"
                })
    except Exception as e:
        logger.error(f"删除下载任务API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.delete("/api/downloads/record/{download_id}")
async def delete_download_record_handler(request: web.Request):
    """删除下载记录（从数据库删除记录和本地文件）"""
    try:
        download_id = int(request.match_info["download_id"])
        
        # 获取是否删除本地文件的参数（默认为true）
        delete_file = request.query.get("delete_file", "true").lower() == "true"
        
        try:
            result = delete_download_record(download_id, delete_local_file=delete_file)
            if result.get('success'):
                return web.json_response({
                    "success": True,
                    "message": f"下载记录 {download_id} 已删除",
                    "data": result
                })
            else:
                # 如果删除失败，返回错误信息
                error_msg = result.get('error', '删除失败')
                # 如果是Aria2任务不存在的错误，忽略它（历史遗留记录）
                if 'not found' in error_msg.lower():
                    # 即使Aria2任务不存在，也认为删除成功（因为记录已删除）
                    return web.json_response({
                        "success": True,
                        "message": f"下载记录 {download_id} 已删除（Aria2任务不存在，已跳过）",
                        "data": result
                    })
                return web.json_response({
                    "success": False,
                    "error": error_msg
                }, status=400)
        except Exception as e:
            error_msg = str(e)
            # 如果是Aria2任务不存在的错误，忽略它（历史遗留记录）
            if 'not found' in error_msg.lower() or 'GID' in error_msg:
                logger.info(f"删除下载记录时出现Aria2相关错误（历史遗留记录）: {download_id}, 错误: {error_msg}")
                # 尝试直接删除记录（不尝试移除Aria2任务）
                try:
                    result = delete_download_record(download_id, delete_local_file=delete_file)
                    if result.get('success'):
                        return web.json_response({
                            "success": True,
                            "message": f"下载记录 {download_id} 已删除（Aria2任务不存在，已跳过）",
                            "data": result
                        })
                    else:
                        # 如果删除记录也失败，返回记录删除的错误
                        return web.json_response({
                            "success": False,
                            "error": result.get('error', '删除记录失败')
                        }, status=400)
                except Exception as retry_err:
                    logger.error(f"重新尝试删除记录失败: {retry_err}", exc_info=True)
                    # 如果重新尝试也失败，返回原始错误
                    return web.json_response({
                        "success": False,
                        "error": f"删除记录失败: {str(retry_err)}"
                    }, status=500)
            logger.error(f"删除下载记录失败: {e}", exc_info=True)
            return web.json_response({
                "success": False,
                "error": error_msg
            }, status=500)
    except ValueError:
        return web.json_response({
            "success": False,
            "error": "无效的下载记录ID"
        }, status=400)
    except Exception as e:
        logger.error(f"删除下载记录API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


# ==================== 上传任务控制 API ====================

# 存储正在运行的上传任务进程（用于暂停/取消）
_upload_processes = {}
_upload_processes_lock = asyncio.Lock() if asyncio else None

@routes.post("/api/uploads/{upload_id}/retry")
async def retry_upload_handler(request: web.Request):
    """重试上传任务（重新提交rclone上传）"""
    try:
        upload_id = int(request.match_info["upload_id"])
        
        upload_record = get_upload_by_id(upload_id)
        if not upload_record:
            return web.json_response({
                "success": False,
                "error": "上传记录不存在"
            }, status=404)
        
        current_status = upload_record.get('status')
        # 允许所有状态重试，但已完成且已清理的任务可能需要特殊处理
        if current_status == 'completed' and upload_record.get('cleaned_at'):
            # 如果已完成且已清理，检查文件是否存在
            pass  # 继续检查文件是否存在
        
        download_id = upload_record.get('download_id')
        download_record = get_download_by_id(download_id) if download_id else None
        
        if not download_record:
            return web.json_response({
                "success": False,
                "error": "关联的下载记录不存在"
            }, status=404)
        
        local_path = download_record.get('local_path')
        if not local_path or not os.path.exists(local_path):
            return web.json_response({
                "success": False,
                "error": "本地文件不存在，无法重试上传"
            }, status=404)
        
        upload_target = upload_record.get('upload_target')
        gid = download_record.get('gid')
        
        # 重置重试计数和状态
        update_upload_status(
            upload_id, 
            'pending',
            retry_count=0,
            error_message=None,
            error_code=None,
            failure_reason=None
        )
        
        # 根据上传目标选择重试方式
        try:
            if upload_target in ['onedrive', 'gdrive']:
                # OneDrive/Google Drive: 直接重新提交rclone上传
                from aria2_client.upload_handler import UploadHandler
                
                upload_handler = UploadHandler(None, {})
                
                if upload_target == 'onedrive':
                    asyncio.create_task(
                        upload_handler.upload_to_onedrive(local_path, None, gid, upload_id=upload_id)
                    )
                elif upload_target == 'gdrive':
                    asyncio.create_task(
                        upload_handler.upload_to_google_drive(local_path, None, gid, upload_id=upload_id)
                    )
                
                return web.json_response({
                    "success": True,
                    "message": f"上传任务 {upload_id} 已重新提交rclone上传"
                })
            elif upload_target == 'telegram':
                # Telegram: 使用上传处理器
                from aria2_client.upload_handler import UploadHandler
                
                upload_handler = UploadHandler(None, {})
                asyncio.create_task(
                    upload_handler.upload_to_telegram_with_load_balance(local_path, gid, upload_id=upload_id)
                )
                
                return web.json_response({
                    "success": True,
                    "message": f"上传任务 {upload_id} 已重新提交Telegram上传"
                })
            else:
                return web.json_response({
                    "success": False,
                    "error": f"不支持的上传目标: {upload_target}"
                }, status=400)
        except Exception as e:
            logger.error(f"重试上传任务失败: {e}", exc_info=True)
            mark_upload_failed(upload_id, 'code_error', str(e), 'EXCEPTION')
            return web.json_response({
                "success": False,
                "error": f"重试上传失败: {str(e)}"
            }, status=500)
    except ValueError:
        return web.json_response({
            "success": False,
            "error": "无效的上传ID"
        }, status=400)
    except Exception as e:
        logger.error(f"重试上传任务API错误: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.delete("/api/uploads/{upload_id}")
async def delete_upload_handler(request: web.Request):
    """删除/取消上传任务"""
    try:
        upload_id = int(request.match_info["upload_id"])
        
        upload_record = get_upload_by_id(upload_id)
        if not upload_record:
            return web.json_response({
                "success": False,
                "error": "上传记录不存在"
            }, status=404)
        
        current_status = upload_record.get('status')
        
        # 如果正在上传，先停止进程
        if current_status == 'uploading':
            if _upload_processes_lock:
                async with _upload_processes_lock:
                    if upload_id in _upload_processes:
                        process = _upload_processes[upload_id]
                        try:
                            if process and process.returncode is None:
                                process.terminate()
                                await asyncio.wait_for(process.wait(), timeout=5)
                        except Exception as e:
                            logger.warning(f"停止上传进程失败: {e}")
                        finally:
                            del _upload_processes[upload_id]
        
        # 更新状态为 cancelled
        update_upload_status(upload_id, 'cancelled')
        
        return web.json_response({
            "success": True,
            "message": f"上传任务 {upload_id} 已取消"
        })
    except ValueError:
        return web.json_response({
            "success": False,
            "error": "无效的上传ID"
        }, status=400)
    except Exception as e:
        logger.error(f"删除上传任务API错误: {e}", exc_info=True)
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


def build_telegram_stream_url(item: dict, hash_len: int) -> str | None:
    uid = item.get("file_unique_id", "")
    mid = item.get("message_id")
    if not uid or not mid:
        return None

    secure_hash = utils.get_hash(uid, hash_len)
    raw_name = (item.get("file_name") or "").strip() or f"media_{mid}"
    safe_name = quote(raw_name, safe="")
    return f"/{mid}/{safe_name}?hash={secure_hash}"


def get_channel_deletion_clients() -> list[tuple[int, object]]:
    """按负载升序返回可访问频道的 bot 客户端。"""
    candidate_indices = [
        idx for idx in channel_accessible_clients
        if idx in multi_clients
    ]

    if not candidate_indices:
        candidate_indices = list(multi_clients.keys())

    candidate_indices.sort(key=lambda idx: work_loads.get(idx, 0))
    return [(idx, multi_clients[idx]) for idx in candidate_indices if idx in multi_clients]


def is_ignorable_delete_message_error(error: Exception) -> bool:
    """消息已经不存在时允许继续清理数据库记录。"""
    error_text = str(error).lower()
    ignorable_markers = [
        "message_id_invalid",
        "msg_id_invalid",
        "message ids are empty",
        "message to delete not found",
        "message not found",
        "message identifier is not specified",
    ]
    return any(marker in error_text for marker in ignorable_markers)


async def delete_bin_channel_messages(message_ids: list[int]) -> dict:
    """删除 BIN_CHANNEL 中的消息，支持多 bot 回退。"""
    normalized_ids = [int(message_id) for message_id in dict.fromkeys(message_ids) if message_id]
    if not normalized_ids:
        return {
            "deleted_message_count": 0,
            "cleanup_only": False,
            "client_index": None,
        }

    if not Var.BIN_CHANNEL:
        raise RuntimeError("BIN_CHANNEL 未配置，无法删除频道消息")

    clients = get_channel_deletion_clients()
    if not clients:
        raise RuntimeError("没有可用的 bot 客户端用于删除频道消息")

    last_error = None

    for index, client in clients:
        deleted_message_count = 0
        cleanup_only = False
        try:
            for offset in range(0, len(normalized_ids), 100):
                chunk = normalized_ids[offset:offset + 100]
                try:
                    result = await client.delete_messages(
                        chat_id=Var.BIN_CHANNEL,
                        message_ids=chunk,
                    )
                    if isinstance(result, int):
                        deleted_message_count += result
                    elif isinstance(result, list):
                        deleted_message_count += len(result)
                    else:
                        deleted_message_count += len(chunk)
                except Exception as chunk_error:
                    if is_ignorable_delete_message_error(chunk_error):
                        cleanup_only = True
                        logger.info(
                            f"频道消息已不存在，继续清理数据库记录: {chunk} (bot {index})"
                        )
                        continue
                    raise

            return {
                "deleted_message_count": deleted_message_count,
                "cleanup_only": cleanup_only,
                "client_index": index,
            }
        except Exception as error:
            last_error = error
            logger.warning(f"bot {index} 删除频道消息失败: {error}")

    if last_error and is_ignorable_delete_message_error(last_error):
        return {
            "deleted_message_count": 0,
            "cleanup_only": True,
            "client_index": None,
        }

    raise RuntimeError(f"删除频道消息失败: {last_error}" if last_error else "删除频道消息失败")

async def media_streamer(request: web.Request, message_id: int, secure_hash: str):
    range_header = request.headers.get("Range", 0)

    # 检查是否有可用的客户端
    if not work_loads:
        logger.error("没有可用的客户端")
        raise web.HTTPInternalServerError(text="No available clients")

    attempted_indices = set()
    file_id = None
    tg_connect = None
    index = None

    while True:
        index = select_stream_bot(prefer_channel=True, exclude_indices=attempted_indices)
        if index is None:
            logger.error("没有有效的客户端")
            raise web.HTTPInternalServerError(text="No valid clients available")

        # 验证索引有效性
        if index not in multi_clients:
            attempted_indices.add(index)
            logger.error(f"选择的客户端索引 {index} 不存在于 multi_clients 中")
            continue

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

        try:
            logger.debug("before calling get_file_properties")
            file_id = await tg_connect.get_file_properties(message_id)
            logger.debug("after calling get_file_properties")
            mark_bot_success(index)
            break
        except FIleNotFound:
            raise
        except Exception as error:
            attempted_indices.add(index)
            mark_bot_failure(index, error)
            logger.warning(f"客户端 {index} 获取文件属性失败，尝试切换: {error}")
            if len(attempted_indices) >= max(1, len(multi_clients)):
                raise
    
    
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
            "X-MistRelay-Min-Threads": str(max(2, get_available_channel_bot_count())),
        },
    )

# ==================== Telegram 频道浏览 API ====================

@routes.get("/api/telegram/browse", allow_head=True)
async def telegram_browse_handler(request: web.Request):
    """浏览 Telegram 频道中已入库的媒体文件（分页、搜索、筛选）"""
    try:
        page = int(request.query.get('page', '1'))
        page_size = int(request.query.get('page_size', '50'))
        search = request.query.get('search', '').strip() or None
        mime_filter = request.query.get('type', '').strip() or None
        sort_by = request.query.get('sort_by', 'message_date')
        sort_desc = request.query.get('sort_desc', 'true').lower() != 'false'

        page_size = min(page_size, 200)

        result = browse_tg_media(
            page=page,
            page_size=page_size,
            search=search,
            mime_filter=mime_filter,
            sort_by=sort_by,
            sort_desc=sort_desc,
        )

        hash_len = Var.HASH_LENGTH
        for item in result['items']:
            uid = item.get('file_unique_id', '')
            mid = item.get('message_id')
            if uid and mid:
                item['hash'] = utils.get_hash(uid, hash_len)
                item['stream_url'] = build_telegram_stream_url(item, hash_len) or f"{item['hash']}{mid}"

        return web.json_response({"success": True, **result})
    except Exception as e:
        logger.error(f"Telegram browse API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/telegram/usage", allow_head=True)
async def telegram_usage_handler(request: web.Request):
    """获取 Telegram 频道存储统计"""
    try:
        stats = get_tg_media_stats()
        return web.json_response({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"Telegram usage API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.delete("/api/telegram/item/{message_id}")
async def telegram_delete_item_handler(request: web.Request):
    """删除单个 tg 网盘文件对应的频道消息和数据库记录。"""
    try:
        message_id = int(request.match_info["message_id"])
        record = get_tg_media_record_by_message_id(message_id)
        if not record:
            return web.json_response({"success": False, "error": "Telegram 文件记录不存在"}, status=404)

        deletion = await delete_bin_channel_messages([message_id])
        cleanup = delete_tg_media_records([record["file_unique_id"]])

        action_message = "频道消息已删除并清理记录"
        if deletion["cleanup_only"]:
            action_message = "频道消息不存在，已清理数据库记录"

        return web.json_response({
            "success": True,
            "message": action_message,
            "data": {
                **cleanup,
                **deletion,
                "message_id": message_id,
            },
        })
    except ValueError:
        return web.json_response({"success": False, "error": "无效的 message_id"}, status=400)
    except Exception as e:
        logger.error(f"Telegram delete item API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.delete("/api/telegram/group/{media_group_id}")
async def telegram_delete_group_handler(request: web.Request):
    """删除整个 Telegram 媒体组对应的频道消息和数据库记录。"""
    try:
        media_group_id = request.match_info["media_group_id"].strip()
        if not media_group_id:
            return web.json_response({"success": False, "error": "media_group_id 不能为空"}, status=400)

        records = get_tg_media_records_by_media_group(media_group_id)
        if not records:
            return web.json_response({"success": False, "error": "Telegram 媒体组不存在"}, status=404)

        message_ids = [record["message_id"] for record in records]
        file_unique_ids = [record["file_unique_id"] for record in records]

        deletion = await delete_bin_channel_messages(message_ids)
        cleanup = delete_tg_media_records(file_unique_ids)

        action_message = "媒体组已删除并清理记录"
        if deletion["cleanup_only"]:
            action_message = "频道媒体组消息不存在，已清理数据库记录"

        return web.json_response({
            "success": True,
            "message": action_message,
            "data": {
                **cleanup,
                **deletion,
                "media_group_id": media_group_id,
                "message_count": len(message_ids),
            },
        })
    except Exception as e:
        logger.error(f"Telegram delete group API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.delete("/api/telegram/all")
async def telegram_clear_all_handler(request: web.Request):
    """清空整个 tg 网盘：删除频道消息并清理 tg_media/downloads/uploads 记录。"""
    try:
        records = list_all_tg_media_records()
        if not records:
            return web.json_response({
                "success": True,
                "message": "tg 网盘已为空",
                "data": {
                    "deleted_media": 0,
                    "deleted_downloads": 0,
                    "deleted_uploads": 0,
                    "deleted_message_count": 0,
                    "cleanup_only": False,
                    "client_index": None,
                },
            })

        message_ids = [record["message_id"] for record in records]
        file_unique_ids = [record["file_unique_id"] for record in records]

        deletion = await delete_bin_channel_messages(message_ids)
        cleanup = delete_tg_media_records(file_unique_ids)

        action_message = "tg 网盘已清空"
        if deletion["cleanup_only"]:
            action_message = "频道消息不存在，已清空 tg 网盘数据库记录"

        return web.json_response({
            "success": True,
            "message": action_message,
            "data": {
                **cleanup,
                **deletion,
                "message_count": len(message_ids),
            },
        })
    except Exception as e:
        logger.error(f"Telegram clear all API error: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/rclone/cache/monitor")
async def monitor_cache_status(request: web.Request):
    """WebSocket monitor for rclone cache status"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    try:
        remote = request.query.get('remote')
        path = request.query.get('path')

        if not remote or not path:
            await ws.send_json({"error": "Missing remote or path"})
            await ws.close()
            return ws

        # Construct cache file path
        # cache dir: /app/cache/rclone/{remote}/vfs/{path}
        cache_base = Path(f"/app/cache/rclone/{remote}/vfs")
        cache_file = cache_base / path.lstrip('/')

        # Get total size from vfs manager or by querying file info?
        # Use rclone lsjson to get total size? or just lstat the mount point?
        # Better to stat the mount point file to get total size.
        from rclone_vfs_manager import get_vfs_manager
        vfs = get_vfs_manager()
        mount_file = vfs.get_file_path(remote, path)
        
        if not mount_file or not mount_file.exists():
             await ws.send_json({"error": "File not found on mount"})
             await ws.close()
             return ws
             
        total_size = mount_file.stat().st_size

        while True:
            if ws.closed:
                break

            try:
                if cache_file.exists():
                    stat = cache_file.stat()
                    cached_size = stat.st_blocks * 512
                    
                    if cached_size > total_size:
                        cached_size = total_size
                    
                    percent = (cached_size / total_size) * 100 if total_size > 0 else 0
                    
                    status = "caching"
                    if cached_size >= total_size or percent >= 100:
                        status = "fully_cached"
                    
                    if ws.closed:
                        break
                    await ws.send_json({
                        "status": status,
                        "cached_size": cached_size,
                        "total_size": total_size,
                        "percent": round(percent, 2)
                    })
                    
                    if status == "fully_cached":
                        break
                else:
                    if ws.closed:
                        break
                    await ws.send_json({
                        "status": "waiting",
                        "cached_size": 0,
                        "total_size": total_size,
                        "percent": 0
                    })
            except Exception as e:
                if ws.closed or "closing transport" in str(e).lower():
                    logger.debug("Cache monitor: WebSocket connection closed by client")
                    break
                logger.error(f"Error checking cache: {e}", exc_info=True)
                
            await asyncio.sleep(2) # Poll every 2 seconds

    except Exception as e:
        logger.error(f"Cache monitor error: {e}", exc_info=True)
    finally:
        if not ws.closed:
            await ws.close()
    return ws

# ==================== 文件管理 API ====================

@routes.get("/api/files/list")
async def list_files_handler(request: web.Request):
    """
    API接口: 列出指定目录下的文件和文件夹
    参数: path (可选, 默认为根目录 /)
    """
    try:
        # 获取请求路径
        path_param = request.query.get("path", "/")
        
        # 基础目录 (默认为下载目录或者根目录, 这里为了灵活暂时设为根目录, 实际应限制在安全目录下)
        # 注意: 生产环境应严格限制 base_path 以防止路径遍历攻击
        base_path = "/" 
        
        # 拼接完整路径
        if path_param == "/":
            target_path = base_path
        else:
            # 移除开头的 /
            clean_path = path_param.lstrip("/")
            target_path = os.path.join(base_path, clean_path)
        
        if not os.path.exists(target_path):
             return web.json_response({
                "success": False,
                "error": f"路径不存在: {path_param}"
            }, status=404)
            
        if not os.path.isdir(target_path):
            return web.json_response({
                "success": False,
                "error": f"路径不是目录: {path_param}"
            }, status=400)
            
        # 遍历目录
        files = []
        try:
            with os.scandir(target_path) as entries:
                for entry in entries:
                    try:
                        stat = entry.stat()
                        files.append({
                            "name": entry.name,
                            "path": os.path.join(path_param if path_param != "/" else "", entry.name), # 相对 API 的路径
                            "is_dir": entry.is_dir(),
                            "size": stat.st_size,
                            "modified_time": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        })
                    except Exception as e:
                        logger.warning(f"无法获取文件信息 {entry.name}: {e}")
                        continue
        except PermissionError:
             return web.json_response({
                "success": False,
                "error": f"没有权限访问目录: {path_param}"
            }, status=403)
            
        # 排序: 文件夹在前, 然后按名称排序
        files.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        
        return web.json_response({
            "success": True,
            "path": path_param,
            "files": files
        })
        
    except Exception as e:
        logger.error(f"列出文件失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.get("/api/files/download")
async def download_file_handler(request: web.Request):
    """
    API接口: 下载文件
    参数: path
    """
    try:
        path_param = request.query.get("path")
        if not path_param:
            return web.json_response({"success": False, "error": "缺少 path 参数"}, status=400)
            
        base_path = "/"
        clean_path = path_param.lstrip("/")
        target_path = os.path.join(base_path, clean_path)
        
        if not os.path.exists(target_path):
            return web.json_response({"success": False, "error": "文件不存在"}, status=404)
        
        if os.path.isdir(target_path):
            return web.json_response({"success": False, "error": "无法直接下载文件夹"}, status=400)
            
        # 使用 FileResponse 发送文件
        return web.FileResponse(target_path)
        
    except Exception as e:
        logger.error(f"下载文件失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


@routes.post("/api/files/upload")
async def upload_file_handler(request: web.Request):
    """
    API接口: 上传文件
    Form Data: 
      - path: 目标文件夹路径 (可选, 默认为 /)
      - file: 文件内容
    """
    try:
        reader = await request.multipart()
        
        # 读取字段
        target_dir = "/"
        file_field = None
        
        while True:
            field = await reader.next()
            if field is None:
                break
            
            if field.name == 'path':
                path_val = await field.read(decode=True)
                target_dir = path_val.decode('utf-8')
            elif field.name == 'file':
                file_field = field
                break # 找到文件就开始处理
        
        if not file_field:
            return web.json_response({"success": False, "error": "未找到文件字段"}, status=400)
            
        filename = file_field.filename
        if not filename:
             return web.json_response({"success": False, "error": "文件名为空"}, status=400)
             
        # 构建保存路径
        if target_dir == "/":
            save_dir = "/"
        else:
            save_dir = os.path.join("/", target_dir.lstrip("/"))
            
        if not os.path.exists(save_dir):
             os.makedirs(save_dir, exist_ok=True)
             
        save_path = os.path.join(save_dir, filename)
        
        # 写入文件
        size = 0
        with open(save_path, 'wb') as f:
            while True:
                chunk = await file_field.read_chunk()
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
                
        return web.json_response({
            "success": True,
            "message": "上传成功",
            "file": {
                "name": filename,
                "path": os.path.join(target_dir if target_dir != "/" else "", filename),
                "size": size
            }
        })

    except Exception as e:
        logger.error(f"上传文件失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)

@routes.post("/api/files/mkdir")
async def mkdir_handler(request: web.Request):
    """
    API接口: 创建文件夹
    JSON: {"path": "/foo/bar"}
    """
    try:
        data = await request.json()
        path_param = data.get("path")
        
        if not path_param:
            return web.json_response({"success": False, "error": "缺少 path 参数"}, status=400)
            
        target_path = os.path.join("/", path_param.lstrip("/"))
        
        if os.path.exists(target_path):
             return web.json_response({"success": False, "error": "目录已存在"}, status=400)
             
        os.makedirs(target_path, exist_ok=True)
        
        return web.json_response({
            "success": True,
            "message": f"目录 {path_param} 创建成功"
        })
        
    except Exception as e:
        logger.error(f"创建目录失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)

@routes.delete("/api/files/delete")
async def delete_file_handler(request: web.Request):
    """
    API接口: 删除文件或文件夹
    参数: path
    """
    try:
        path_param = request.query.get("path")
        if not path_param:
            return web.json_response({"success": False, "error": "缺少 path 参数"}, status=400)
            
        target_path = os.path.join("/", path_param.lstrip("/"))
        
        if not os.path.exists(target_path):
            return web.json_response({"success": False, "error": "文件或目录不存在"}, status=404)
        
        # 安全检查: 防止删除根目录
        if target_path == "/":
             return web.json_response({"success": False, "error": "不能删除根目录"}, status=403)

        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)
            
        return web.json_response({
            "success": True,
            "message": f"已删除 {path_param}"
        })
        
    except Exception as e:
        logger.error(f"删除失败: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


# ======================== 日志管理 API ========================

@routes.get("/api/logs", allow_head=True)
async def get_logs_handler(request: web.Request):
    """
    API接口: 获取日志内容
    参数:
        file: 日志文件名（可选，默认当前日志）
        tail: 返回最后 N 行（默认 200）
        level: 按级别过滤（如 ERROR, WARNING, INFO）
        keyword: 关键词搜索
    """
    try:
        from log_config import read_log_lines
        filename = request.query.get("file")
        tail = int(request.query.get("tail", 200))
        level_filter = request.query.get("level")
        keyword = request.query.get("keyword")

        lines = read_log_lines(
            filename=filename,
            tail=tail,
            level_filter=level_filter,
            keyword=keyword,
        )
        return web.json_response({
            "success": True,
            "total": len(lines),
            "lines": lines,
        })
    except Exception as e:
        logger.error(f"获取日志失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/logs/files", allow_head=True)
async def get_log_files_handler(request: web.Request):
    """API接口: 列出所有日志文件"""
    try:
        from log_config import get_log_files
        files = get_log_files()
        return web.json_response({"success": True, "files": files})
    except Exception as e:
        logger.error(f"获取日志文件列表失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/logs/download/{filename}")
async def download_log_file_handler(request: web.Request):
    """API接口: 下载指定日志文件"""
    try:
        from log_config import LOG_DIR
        filename = request.match_info["filename"]
        safe_name = os.path.basename(filename)
        path = os.path.join(LOG_DIR, safe_name)

        if not os.path.isfile(path):
            return web.json_response({"success": False, "error": "文件不存在"}, status=404)

        return web.FileResponse(
            path,
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"'
            },
        )
    except Exception as e:
        logger.error(f"下载日志文件失败: {e}", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)
