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
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from WebStreamer.bot import multi_clients, work_loads, channel_accessible_clients
from WebStreamer.server.exceptions import FIleNotFound, InvalidHash
from WebStreamer.server.ws_manager import ws_manager
from WebStreamer import Var, utils, StartTime, __version__, StreamBot
from db import (
    fetch_recent_downloads, get_all_configs, get_config, set_config,
    get_download_id_by_gid, get_download_by_id, get_upload_by_id,
    mark_download_failed, update_upload_status, mark_upload_failed,
    delete_download_record
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
            except:
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
                    except:
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
                logger.error(f"获取历史日志失败: {e}")
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
                                        asyncio.get_event_loop()
                                    )
                            except Exception as e:
                                logger.error(f"处理日志行失败: {e}")
                                continue
                                
                    except Exception as e:
                        logger.error(f"日志流线程错误: {e}")
                        if not ws.closed:
                            asyncio.run_coroutine_threadsafe(
                                ws.send_json({
                                    "type": "error",
                                    "message": f"日志流错误: {str(e)}"
                                }),
                                asyncio.get_event_loop()
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
                logger.error(f"日志流错误: {e}")
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
        except:
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
                except:
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

