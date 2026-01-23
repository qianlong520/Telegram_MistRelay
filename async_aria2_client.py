import asyncio
import base64
import functools
import json
import os
import time
import uuid
import subprocess
from datetime import datetime
from pprint import pprint
from typing import List, Dict, Any

import aiohttp
import websockets

from configer import ADMIN_ID, UP_TELEGRAM, RPC_URL, RPC_SECRET, FORWARD_ID, UP_ONEDRIVE, RCLONE_REMOTE, RCLONE_PATH, AUTO_DELETE_AFTER_UPLOAD, ENABLE_STREAM
from util import get_file_name, imgCoverFromFile, progress, byte2_readable, hum_convert
import re

# 导入多客户端负载均衡（如果启用直链功能）
upload_work_loads = {}  # 上传任务的负载跟踪
if ENABLE_STREAM:
    try:
        from WebStreamer.bot import multi_clients as pyrogram_clients, channel_accessible_clients
        # 初始化上传负载跟踪
        upload_work_loads = {index: 0 for index in pyrogram_clients.keys()}
    except ImportError:
        pyrogram_clients = {}
        channel_accessible_clients = set()
        upload_work_loads = {}
else:
    pyrogram_clients = {}
    channel_accessible_clients = set()
    upload_work_loads = {}


# logging.basicConfig(
#     format="%(asctime)s %(message)s",
#     level=logging.DEBUG,
# )


def format_progress_bar(percentage_str):
    """
    根据百分比生成进度条
    返回: 进度条字符串（使用 Unicode 字符）
    """
    try:
        # 提取百分比数字
        percentage = float(percentage_str.replace('%', ''))
        # 限制在 0-100 之间
        percentage = max(0, min(100, percentage))
        
        # 进度条长度（20个字符）
        bar_length = 20
        filled_length = int(bar_length * percentage / 100)
        
        # 使用不同的字符表示进度
        filled_char = '█'
        empty_char = '░'
        
        bar = filled_char * filled_length + empty_char * (bar_length - filled_length)
        return bar
    except:
        return '░' * 20


def format_upload_message(file_path, parsed_progress):
    """
    格式化上传进度消息（美化版）
    """
    file_name = os.path.basename(file_path)
    
    # 构建消息
    message_parts = []
    message_parts.append(f'📤 <b>上传到 OneDrive</b>\n')
    message_parts.append(f'📁 <b>文件:</b> <code>{file_name}</code>\n')
    
    # 进度条和百分比
    if parsed_progress.get('percentage'):
        percentage = parsed_progress['percentage']
        progress_bar = format_progress_bar(percentage)
        message_parts.append(f'\n{progress_bar} <b>{percentage}</b>\n')
    
    # 传输进度
    if parsed_progress.get('transferred') and parsed_progress.get('total'):
        message_parts.append(f'📊 <b>进度:</b> {parsed_progress["transferred"]} / {parsed_progress["total"]}\n')
    elif parsed_progress.get('transferred'):
        message_parts.append(f'📊 <b>已传输:</b> {parsed_progress["transferred"]}\n')
    
    # 速度
    if parsed_progress.get('speed'):
        message_parts.append(f'⚡ <b>速度:</b> {parsed_progress["speed"]}\n')
    
    # ETA
    if parsed_progress.get('eta'):
        eta = parsed_progress['eta']
        message_parts.append(f'⏱️ <b>剩余时间:</b> {eta}\n')
    
    return ''.join(message_parts)


def parse_rclone_progress(line):
    """
    解析 rclone 进度输出行
    格式示例: "Transferred:   1.234 GiB / 2.345 GiB, 53%, 12.34 MiB/s, ETA 0s"
    或者: "Transferred:   1.234 GiB / 2.345 GiB, 53%, 12.34 MiB/s, ETA -"
    或者: "Transferred:   1.234 GiB / 2.345 GiB, 53%, 12.34 MiB/s, ETA 1h11m47s"
    或者: "Speed: 12.34 MiB/s" (单独一行)
    返回: dict 包含 transferred, total, percentage, speed, eta
    """
    result = {
        'transferred': '',
        'total': '',
        'percentage': '',
        'speed': '',
        'eta': ''
    }
    
    try:
        # 首先尝试提取速率信息（可能在单独的行中）
        speed_patterns = [
            r'Speed:\s*([\d.]+)\s+([KMGT]?i?B/s)',  # "Speed: 12.34 MiB/s"
            r'([\d.]+)\s+([KMGT]?i?B/s)',  # "12.34 MiB/s" (通用格式)
        ]
        for pattern in speed_patterns:
            speed_match = re.search(pattern, line, re.IGNORECASE)
            if speed_match:
                result['speed'] = f"{speed_match.group(1)} {speed_match.group(2)}"
                break
        
        # 提取 "Transferred:" 后面的内容
        if "Transferred:" not in line:
            return result
        
        # 匹配格式: Transferred:   X.XXX Unit / Y.YYY Unit, Z%, S.SSS Unit/s, ETA ...
        # 支持 GiB, MiB, KiB, GB, MB, KB 等单位
        # 支持 ETA 格式: 数字s, 数字h数字m数字s, 或 -
        # 先尝试匹配完整格式（包含速率和 ETA）
        full_pattern = r'Transferred:\s+([\d.]+)\s+([KMGT]?i?B)\s+/\s+([\d.]+)\s+([KMGT]?i?B),\s+([\d.]+)%(?:\s*,\s*([\d.]+)\s+([KMGT]?i?B/s))?(?:\s*,\s*ETA\s+([\d]+[hms]+|\d+h\d+m\d+s|\d+m\d+s|\d+s|-))?'
        match = re.search(full_pattern, line, re.IGNORECASE)
        
        if match:
            transferred_size = match.group(1)
            transferred_unit = match.group(2)
            total_size = match.group(3)
            total_unit = match.group(4)
            percentage = match.group(5)
            
            result['transferred'] = f"{transferred_size} {transferred_unit}"
            result['total'] = f"{total_size} {total_unit}"
            result['percentage'] = f"{percentage}%"
            
            # 提取速率信息（group 6 和 7）
            if match.group(6) and match.group(7):
                speed_value = match.group(6)
                speed_unit = match.group(7)
                result['speed'] = f"{speed_value} {speed_unit}"
            
            # 提取 ETA 信息（group 8）
            if match.group(8):
                eta = match.group(8)
                if eta != '-':
                    result['eta'] = eta
                # 如果 ETA 是 '-'，不设置 eta 字段（保持为空）
        else:
            # 如果完整格式匹配失败，尝试简化格式
            simple_pattern = r'Transferred:\s+([\d.]+)\s+([KMGT]?i?B)\s+/\s+([\d.]+)\s+([KMGT]?i?B),\s+([\d.]+)%'
            match = re.search(simple_pattern, line, re.IGNORECASE)
            if match:
                transferred_size = match.group(1)
                transferred_unit = match.group(2)
                total_size = match.group(3)
                total_unit = match.group(4)
                percentage = match.group(5)
                
                result['transferred'] = f"{transferred_size} {transferred_unit}"
                result['total'] = f"{total_size} {total_unit}"
                result['percentage'] = f"{percentage}%"
        
        # 如果还没有提取到速率，尝试从整行中提取（作为后备方案）
        if not result['speed']:
            # 查找 "数字 单位/s" 格式的速率
            # 优先匹配在逗号后面的速率（Transferred 行中的速率格式）
            # 格式: ", 数字 单位/s" 或 ", 数字 单位/s,"
            speed_patterns = [
                r',\s*([\d.]+)\s+([KMGT]?i?B/s)',  # ", 0 B/s" 或 ", 12.34 MiB/s"
                r'([\d.]+)\s+([KMGT]?i?B/s)',  # 通用格式 "0 B/s"
            ]
            for pattern in speed_patterns:
                speed_match = re.search(pattern, line, re.IGNORECASE)
                if speed_match:
                    # 确保不是 ETA 后面的时间（检查是否在 ETA 之前）
                    match_pos = speed_match.start()
                    eta_pos = line.find('ETA', match_pos)
                    if eta_pos == -1 or match_pos < eta_pos:
                        result['speed'] = f"{speed_match.group(1)} {speed_match.group(2)}"
                        break
        
        # 如果还没有提取到 ETA，尝试从整行中提取（作为后备方案）
        if not result['eta']:
            # 匹配 ETA 格式: ETA 数字s, ETA 数字h数字m数字s, 或 ETA -
            eta_patterns = [
                r'ETA\s+(\d+[hms]+|\d+h\d+m\d+s|\d+m\d+s|\d+s)',  # ETA 1h11m47s 或 ETA 32s
                r'ETA\s+(\d+)s',  # ETA 32s
            ]
            for pattern in eta_patterns:
                eta_match = re.search(pattern, line, re.IGNORECASE)
                if eta_match:
                    result['eta'] = eta_match.group(1)
                    break
                
    except Exception as e:
        print(f"解析 rclone 进度失败: {e}, 行内容: {line[:100]}")
    
    return result


class AsyncAria2Client:
    def __init__(self, rpc_secret, ws_url, bot=None):
        self.rpc_secret = rpc_secret
        self.ws_url = ws_url
        self.websocket = None
        self.reconnect = True
        self.bot = bot
        self.progress_cache = {}
        self.download_messages = {}  # 存储每个下载任务的消息对象

    async def connect(self):
        try:
            # 从RPC_URL中提取主机和端口
            url_parts = self.ws_url.split('/')
            ws_protocol = url_parts[0].split(':')[0]  # 获取ws或wss
            host_port = url_parts[2]  # 跳过ws://
            path = '/'.join(url_parts[3:])
            
            # 如果主机名不是localhost或IP地址，则在Docker环境中使用localhost
            if ':' in host_port:
                host, port = host_port.split(':')
                if not (host == 'localhost' or host == '127.0.0.1' or all(c.isdigit() or c == '.' for c in host)):
                    # 在Docker环境中，使用localhost
                    host = 'localhost'
                host_port = f"{host}:{port}"
            
            # 重新构建完整URL
            full_ws_url = f"{ws_protocol}://{host_port}/{path}"
            
            print(f"连接到aria2 WebSocket: {full_ws_url}")
            self.websocket = await websockets.connect(full_ws_url, ping_interval=30)
            print("WebSocket连接成功")
            asyncio.ensure_future(self.listen())
        except Exception as e:
            print(f"WebSocket连接失败: {e}")
            await self.re_connect()

    async def listen(self):
        try:
            async for message in self.websocket:
                result = json.loads(message)
                if 'id' in result and result['id'] is None:
                    continue
                print(f'rec message:{message}')
                if 'error' in result:
                    err_msg = result['error']['message']
                    err_code = result['error']['code']
                elif 'method' in result:
                    method_name = result['method']
                    if method_name == 'aria2.onDownloadStart':
                        await self.on_download_start(result)
                    elif method_name == 'aria2.onDownloadComplete':
                        await self.on_download_complete(result)
                    elif method_name == 'aria2.onDownloadError':
                        await self.on_download_error(result)
                    elif method_name == 'aria2.onDownloadPause':
                        await self.on_download_pause(result)
        except websockets.exceptions.ConnectionClosedError:
            print("WebSocket连接已关闭")
            await self.re_connect()

    def parse_json_to_str(self, method, params):
        params_ = self.get_rpc_body(method, params)
        return json.dumps(params_)

    def get_rpc_body(self, method, params=[]):
        params_ = {
            'jsonrpc': '2.0',
            'id': str(uuid.uuid4()),
            'method': method,
            'params': [f'token:{self.rpc_secret}'] + params
        }
        return params_

    async def add_uri(self, uris: List[str], options: Dict[str, Any] = None):
        params = [uris]
        if options:
            params.append(options)

        rpc_body = self.get_rpc_body('aria2.addUri', params)
        print(rpc_body)
        result = await self.post_body(rpc_body)
        
        return result

    async def add_torrent(self, path, options=None, position: int = None):
        with open(path, "rb") as file:
            # 读取文件内容
            file_content = file.read()
            base64_content = str(base64.b64encode(file_content), "utf-8")
        params = [
            base64_content
        ]
        if options:
            params.append(options)
        if position is not None:
            params.append(position)
        else:
            params.append([999])

        rpc_body = self.get_rpc_body('aria2.addTorrent', params)
        return await self.post_body(rpc_body)

    async def tell_status(self, gid):
        params = [gid]
        rpc_body = self.get_rpc_body('aria2.tellStatus', params)
        data = await self.post_body(rpc_body)
        return data['result']

    async def post_body(self, rpc_body):
        # 从RPC_URL中提取主机和端口
        url_parts = RPC_URL.split('/')
        host_port = url_parts[0]
        path = '/'.join(url_parts[1:])
        
        # 如果主机名不是localhost或IP地址，则在Docker环境中使用localhost
        if ':' in host_port:
            host, port = host_port.split(':')
            if not (host == 'localhost' or host == '127.0.0.1' or all(c.isdigit() or c == '.' for c in host)):
                # 在Docker环境中，使用localhost
                host = 'localhost'
            host_port = f"{host}:{port}"
        
        # 重新构建完整URL
        full_url = f"http://{host_port}/{path}"
        
        print(f"连接到aria2 RPC: {full_url}")
        async with aiohttp.ClientSession() as session:
            async with session.post(full_url, json=rpc_body) as response:
                return await response.json()

    async def re_connect(self):
        if self.reconnect:
            print("等待5秒后尝试重新连接...")
            await asyncio.sleep(5)
            await self.connect()
        else:
            print("已禁用重新连接功能")

    async def on_download_start(self, result):
        gid = result['params'][0]['gid']
        print(f"===========下载 开始 任务id:{gid}")
        if self.bot:
            # 不发送初始消息，直接启动进度检查任务
            # 进度检查任务会在第一次运行时发送消息
            # 初始化消息对象存储
            self.download_messages[gid] = None
            asyncio.create_task(self.check_download_progress(gid, None))
            print('轮训进度')

    async def check_download_progress(self, gid, msg=None):
        """
        检查并更新下载进度
        只使用这一条消息来显示下载进度，避免重复消息
        """
        try:
            last_message_text = ""
            first_run = True
            # 立即获取任务状态，尽快发送第一条消息
            while True:
                task = await self.tell_status(gid)
                completedLength = task['completedLength']
                totalLength = task['totalLength']
                downloadSpeed = task['downloadSpeed']
                status = task['status']
                file_name = get_file_name(task)
                
                # 如果文件名为空，等待一下再重试
                if file_name == '':
                    if first_run:
                        await asyncio.sleep(0.5)  # 第一次运行时短暂等待
                    else:
                        await asyncio.sleep(3)
                    continue
                
                dir_path = task.get("dir", "")
                size = byte2_readable(int(totalLength))
                speed = hum_convert(int(downloadSpeed))
                prog = progress(int(totalLength), int(completedLength))
                
                if status != 'complete':
                    new_message_text = (
                        f'📥 <b>正在下载</b>\n\n'
                        f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                        f'📂 <b>路径:</b> <code>{dir_path}</code>\n\n'
                        f'📊 <b>进度:</b> {prog}\n'
                        f'💾 <b>大小:</b> {size}\n'
                        f'⚡ <b>速度:</b> {speed}/s'
                    )
                    # 第一次运行或消息内容不同时才更新
                    if first_run or new_message_text != last_message_text:
                        try:
                            if first_run and msg is None:
                                # 第一次运行且没有消息对象，立即发送新消息
                                if self.bot:
                                    msg = await self.bot.send_message(ADMIN_ID, new_message_text, parse_mode='html')
                                    # 保存消息对象到字典中，供后续使用
                                    self.download_messages[gid] = msg
                                    first_run = False
                                    last_message_text = new_message_text
                            elif msg:
                                # 编辑现有消息
                                try:
                                    msg = await self.bot.edit_message(msg, new_message_text, parse_mode='html')
                                    # 更新保存的消息对象
                                    self.download_messages[gid] = msg
                                    first_run = False
                                    last_message_text = new_message_text
                                except Exception as edit_err:
                                    # 如果编辑失败，尝试从字典中获取最新消息
                                    if gid in self.download_messages and self.download_messages[gid]:
                                        try:
                                            msg = self.download_messages[gid]
                                            msg = await self.bot.edit_message(msg, new_message_text, parse_mode='html')
                                            self.download_messages[gid] = msg
                                            first_run = False
                                            last_message_text = new_message_text
                                        except:
                                            pass
                        except Exception as e:
                            # 忽略"消息内容未修改"的错误
                            if "not modified" not in str(e).lower():
                                print(f"更新下载进度消息失败: {e}")
                    
                    # 第一次发送消息后，等待3秒再更新
                    await asyncio.sleep(3)
                else:
                    # 下载完成，返回消息对象供后续使用
                    # 消息对象已保存在 self.download_messages[gid] 中
                    return

        except Exception as e:
            print('任务取消111')
            print(e)

    async def on_download_complete(self, result):
        gid = result['params'][0]['gid']
        print(f"===========下载 完成 任务id:{gid}")
        
        # 更新任务完成跟踪状态为 'completed'
        try:
            from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
            import asyncio as asyncio_module
            
            if task_completion_lock:
                async with task_completion_lock:
                    task_completion_tracker[gid] = {
                        'status': 'completed',
                        'completed_at': asyncio_module.get_event_loop().time()
                    }
        except Exception as e:
            print(f"更新任务完成跟踪状态失败: {e}")
        
        tellStatus = await self.tell_status(gid)
        files = tellStatus['files']
        
        # 获取保存的消息对象
        msg = self.download_messages.get(gid)
        
        for file in files:
            path = file['path']
            if self.bot:
                # 处理元数据文件
                if '[METADATA]' in path:
                    if os.path.exists(path):
                        os.unlink(path)
                    return
                
                # 检查文件是否存在，如果不存在则尝试查找实际文件
                actual_path = path
                if not os.path.exists(path):
                    # aria2 可能在下载时重命名了文件（添加 .1, .2 等后缀）
                    # 尝试查找实际文件
                    dir_path = os.path.dirname(path)
                    base_name = os.path.basename(path)
                    name_without_ext, ext = os.path.splitext(base_name)
                    
                    # 检查目录中是否有相似的文件名
                    if os.path.exists(dir_path):
                        try:
                            for file_name in os.listdir(dir_path):
                                # 检查是否是同一个文件（可能是 aria2 重命名的版本）
                                if file_name.startswith(name_without_ext) and file_name.endswith(ext):
                                    potential_path = os.path.join(dir_path, file_name)
                                    # 验证文件大小是否合理（大于0）
                                    if os.path.exists(potential_path) and os.path.getsize(potential_path) > 0:
                                        # 检查是否是最近修改的（5分钟内）
                                        file_mtime = os.path.getmtime(potential_path)
                                        if time.time() - file_mtime < 300:  # 5分钟内
                                            actual_path = potential_path
                                            print(f"找到实际文件路径: {actual_path} (原始路径: {path})")
                                            break
                        except Exception as e:
                            print(f"查找文件时出错: {e}")
                
                # 再次检查文件是否存在
                if not os.path.exists(actual_path):
                    print(f"文件不存在: {path} (尝试查找后仍不存在)")
                    if msg:
                        try:
                            error_message = (
                                f'❌ <b>文件不存在</b>\n\n'
                                f'📁 <b>文件:</b> <code>{os.path.basename(path)}</code>\n'
                                f'📂 <b>路径:</b> <code>{path}</code>\n\n'
                                f'⚠️ 文件下载完成但文件不存在，可能已被删除或路径错误'
                            )
                            await self.bot.edit_message(msg, error_message, parse_mode='html')
                        except Exception as e:
                            print(f"更新错误消息失败: {e}")
                    continue
                
                # 发送下载完成消息
                file_name_display = os.path.basename(actual_path)
                file_size = ""
                try:
                    if os.path.exists(actual_path):
                        file_size_bytes = os.path.getsize(actual_path)
                        file_size = byte2_readable(file_size_bytes)
                except:
                    pass
                
                if msg:
                    try:
                        complete_text = (
                            f'✅ <b>下载完成</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name_display}</code>\n'
                            f'📂 <b>路径:</b> <code>{actual_path}</code>'
                        )
                        if file_size:
                            complete_text += f'\n💾 <b>大小:</b> {file_size}'
                        if actual_path != path:
                            complete_text += f'\n\n💡 <b>注意:</b> 文件路径已自动调整（原始路径: <code>{path}</code>）'
                        msg = await self.bot.edit_message(msg, complete_text, parse_mode='html')
                        self.download_messages[gid] = msg
                    except Exception as e:
                        print(f"更新下载完成消息失败: {e}")
                        # 如果编辑失败，发送新消息
                        complete_text = (
                            f'✅ <b>下载完成</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name_display}</code>\n'
                            f'📂 <b>路径:</b> <code>{actual_path}</code>'
                        )
                        if file_size:
                            complete_text += f'\n💾 <b>大小:</b> {file_size}'
                        if actual_path != path:
                            complete_text += f'\n\n💡 <b>注意:</b> 文件路径已自动调整（原始路径: <code>{path}</code>）'
                        msg = await self.bot.send_message(ADMIN_ID, complete_text, parse_mode='html')
                        self.download_messages[gid] = msg
                else:
                    # 如果没有保存的消息，发送新消息
                    complete_text = (
                        f'✅ <b>下载完成</b>\n\n'
                        f'📁 <b>文件:</b> <code>{file_name_display}</code>\n'
                        f'📂 <b>路径:</b> <code>{actual_path}</code>'
                    )
                    if file_size:
                        complete_text += f'\n💾 <b>大小:</b> {file_size}'
                    if actual_path != path:
                        complete_text += f'\n\n💡 <b>注意:</b> 文件路径已自动调整（原始路径: <code>{path}</code>）'
                    msg = await self.bot.send_message(ADMIN_ID, complete_text, parse_mode='html')
                    self.download_messages[gid] = msg
                
                # 根据配置选择上传方式
                if UP_ONEDRIVE:
                    # 使用rclone上传到OneDrive，传递消息对象、实际路径和GID
                    await self.upload_to_onedrive(actual_path, msg, gid)
                elif UP_TELEGRAM:
                    # 上传到Telegram，使用多客户端负载均衡（如果启用）
                    await self.upload_to_telegram_with_load_balance(actual_path, gid)

    async def on_download_pause(self, result):
        gid = result['params'][0]['gid']
        print(f"===========下载 暂停 任务id:{gid}")
        tellStatus = await self.tell_status(gid)
        filename = get_file_name(tellStatus)
        if self.bot:
            pause_msg = (
                f'⏸️ <b>下载已暂停</b>\n\n'
                f'📁 <b>文件:</b> <code>{filename}</code>\n'
                f'🆔 <b>任务ID:</b> <code>{gid}</code>'
            )
            await self.bot.send_message(ADMIN_ID, pause_msg, parse_mode='html')

    async def on_download_error(self, result):
        gid = result['params'][0]['gid']
        tellStatus = await self.tell_status(gid)
        errorCode = tellStatus['errorCode']
        errorMessage = tellStatus['errorMessage']
        print(f'===========下载 错误 任务id:{gid} 错误码: {errorCode} 错误信息{errorMessage}')
        if self.bot:
            if errorCode == '12':
                await self.bot.send_message(ADMIN_ID, '任务已经在下载,可以删除任务后重新添加')
            else:
                await self.bot.send_message(ADMIN_ID, errorMessage)

    async def tell_stopped(self, offset: int, num: int):
        params = [
            offset, num
        ]
        rpc_body = self.get_rpc_body('aria2.tellStopped', params)
        data = await self.post_body(rpc_body)
        return data['result']

    async def tell_waiting(self, offset: int, num: int):
        params = [
            offset, num
        ]
        rpc_body = self.get_rpc_body('aria2.tellWaiting', params)
        data = await self.post_body(rpc_body)
        return data['result']

    async def tell_active(self):
        params = []
        rpc_body = self.get_rpc_body('aria2.tellActive', params)
        data = await self.post_body(rpc_body)
        return data['result']

    async def pause(self, gid: str):
        params = [gid]
        jsonreq = self.parse_json_to_str('aria2.pause', params)
        print(jsonreq)
        await self.websocket.send(jsonreq)

    async def unpause(self, gid: str):
        params = [gid]
        jsonreq = self.parse_json_to_str('aria2.unpause', params)
        print(jsonreq)
        await self.websocket.send(jsonreq)

    async def remove(self, gid: str):
        params = [gid]
        rpc_body = self.get_rpc_body('aria2.remove', params)
        data = await self.post_body(rpc_body)
        return data

    async def remove_download_result(self, gid: str):
        params = [gid]
        jsonreq = self.parse_json_to_str('aria2.removeDownloadResult', params)
        print(jsonreq)
        await self.websocket.send(jsonreq)

    async def change_global_option(self, params):
        rpc_body = self.get_rpc_body('aria2.changeGlobalOption', params)
        return await self.post_body(rpc_body)

    async def get_global_option(self):
        rpc_body = self.get_rpc_body('aria2.getGlobalOption')
        data = await self.post_body(rpc_body)
        return data['result']

    async def upload_to_onedrive(self, file_path, msg=None, gid=None):
        """
        使用rclone将文件上传到OneDrive
        msg: 可选的消息对象，如果提供则编辑该消息而不是发送新消息
        gid: 下载任务GID，用于跟踪任务完成状态
        上传完成并删除本地文件后，会自动删除该消息
        """
        file_name = os.path.basename(file_path)  # 在函数开始处定义，确保异常处理中可用
        try:
            if not os.path.exists(file_path):
                print(f"文件不存在: {file_path}")
                if self.bot:
                    error_message = (
                        f'❌ <b>文件不存在</b>\n\n'
                        f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                        f'📂 <b>路径:</b> <code>{file_path}</code>\n\n'
                        f'⚠️ 无法上传到 OneDrive'
                    )
                    if msg:
                        try:
                            await self.bot.edit_message(msg, error_message, parse_mode='html')
                        except:
                            await self.bot.send_message(ADMIN_ID, error_message, parse_mode='html')
                    else:
                        await self.bot.send_message(ADMIN_ID, error_message, parse_mode='html')
                return False
                
            # 构建rclone命令
            remote_path = f"{RCLONE_REMOTE}:{RCLONE_PATH}"
            command = [
                "rclone", 
                "copy", 
                file_path, 
                remote_path, 
                "-P",
                "--transfers", "16",         # 并行传输数量（更保守）
                "--checkers", "16",          # 并行检查数量
                "--buffer-size", "250M",     # 缓冲区大小
                "--log-level", "INFO",      # 日志级别
                "--log-file", "/app/rclone.log"  # 日志文件
            ]
            
            # 通知开始上传
            if self.bot:
                # 获取文件大小
                file_size = ""
                try:
                    if os.path.exists(file_path):
                        file_size_bytes = os.path.getsize(file_path)
                        file_size = byte2_readable(file_size_bytes)
                except:
                    pass
                
                if msg:
                    try:
                        upload_start_text = (
                            f'📤 <b>上传到 OneDrive</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                            f'📂 <b>路径:</b> <code>{file_path}</code>'
                        )
                        if file_size:
                            upload_start_text += f'\n💾 <b>大小:</b> {file_size}'
                        upload_start_text += f'\n\n⏳ <b>准备上传中...</b>'
                        msg = await self.bot.edit_message(msg, upload_start_text, parse_mode='html')
                    except Exception as e:
                        print(f"更新上传开始消息失败: {e}")
                else:
                    upload_start_text = (
                        f'📤 <b>上传到 OneDrive</b>\n\n'
                        f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                        f'📂 <b>路径:</b> <code>{file_path}</code>'
                    )
                    if file_size:
                        upload_start_text += f'\n💾 <b>大小:</b> {file_size}'
                    upload_start_text += f'\n\n⏳ <b>准备上传中...</b>'
                    msg = await self.bot.send_message(ADMIN_ID, upload_start_text, parse_mode='html')
            
            # 执行rclone命令
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
            
            # 读取输出并更新进度
            last_progress = ""
            last_message_text = ""
            for line in process.stdout:
                if "Transferred:" in line and self.bot and msg:
                    # 提取进度信息
                    progress_info = line.strip()
                    if progress_info != last_progress:
                        last_progress = progress_info
                        # 解析进度信息
                        parsed = parse_rclone_progress(progress_info)
                        # 格式化美化消息
                        formatted_message = format_upload_message(file_path, parsed)
                        
                        # 每5行更新一次消息，避免频繁更新
                        if hash(progress_info) % 5 == 0:
                            if formatted_message != last_message_text:
                                try:
                                    await self.bot.edit_message(msg, formatted_message, parse_mode='html')
                                    last_message_text = formatted_message
                                except Exception as e:
                                    if "not modified" not in str(e).lower():
                                        print(f"更新上传进度消息失败: {e}")
                
                # 记录错误信息
                if "ERROR" in line:
                    print(f"rclone错误: {line.strip()}")
            
            # 等待进程完成
            process.wait()
            
            # 检查上传是否成功
            if process.returncode == 0:
                if self.bot and msg:
                    try:
                        # 获取文件大小
                        file_size = ""
                        try:
                            if os.path.exists(file_path):
                                file_size_bytes = os.path.getsize(file_path)
                                file_size = byte2_readable(file_size_bytes)
                        except:
                            pass
                        
                        success_message = (
                            f'✅ <b>上传完成</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                            f'📂 <b>路径:</b> <code>{file_path}</code>'
                        )
                        if file_size:
                            success_message += f'\n💾 <b>大小:</b> {file_size}'
                        success_message += f'\n\n☁️ <b>已成功上传到 OneDrive</b>'
                        await self.bot.edit_message(msg, success_message, parse_mode='html')
                    except Exception as e:
                        if "not modified" not in str(e).lower():
                            print(f"更新上传成功消息失败: {e}")
                
                # 更新任务完成跟踪状态为 'uploaded'
                if gid:
                    try:
                        from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                        import asyncio as asyncio_module
                        
                        if task_completion_lock:
                            async with task_completion_lock:
                                task_completion_tracker[gid] = {
                                    'status': 'uploaded',
                                    'completed_at': asyncio_module.get_event_loop().time()
                                }
                                print(f"任务 {gid} 已标记为已上传")
                    except Exception as e:
                        print(f"更新任务上传状态失败: {e}")
                
                # 上传成功后删除本地文件
                if AUTO_DELETE_AFTER_UPLOAD:
                    try:
                        os.unlink(file_path)
                        print(f"已删除本地文件: {file_path}")
                        
                        # 更新任务完成跟踪状态为 'cleaned'
                        if gid:
                            try:
                                from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                                import asyncio as asyncio_module
                                
                                if task_completion_lock:
                                    async with task_completion_lock:
                                        task_completion_tracker[gid] = {
                                            'status': 'cleaned',
                                            'completed_at': asyncio_module.get_event_loop().time()
                                        }
                                        print(f"任务 {gid} 已标记为已清理")
                            except Exception as e:
                                print(f"更新任务清理状态失败: {e}")
                        
                        # 删除本地文件成功后，删除消息
                        if self.bot and msg:
                            try:
                                await msg.delete()
                                print(f"已删除消息（文件已上传并清理）: {file_name}")
                            except Exception as e:
                                print(f"删除消息失败: {e}")
                    except Exception as e:
                        print(f"删除本地文件失败: {e}")
                        if self.bot and msg:
                            try:
                                # 获取文件大小
                                file_size = ""
                                try:
                                    if os.path.exists(file_path):
                                        file_size_bytes = os.path.getsize(file_path)
                                        file_size = byte2_readable(file_size_bytes)
                                except:
                                    pass
                                
                                error_message = (
                                    f'✅ <b>上传完成</b>\n\n'
                                    f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                                    f'📂 <b>路径:</b> <code>{file_path}</code>'
                                )
                                if file_size:
                                    error_message += f'\n💾 <b>大小:</b> {file_size}'
                                error_message += (
                                    f'\n\n☁️ <b>已成功上传到 OneDrive</b>\n\n'
                                    f'⚠️ <b>删除本地文件失败:</b>\n<code>{str(e)}</code>'
                                )
                                await self.bot.edit_message(msg, error_message, parse_mode='html')
                            except Exception as edit_err:
                                if "not modified" not in str(edit_err).lower():
                                    print(f"更新删除文件错误消息失败: {edit_err}")
                
                return True
            else:
                # 上传失败，记录详细错误信息
                error_message = f"上传失败，返回码: {process.returncode}"
                print(error_message)
                
                # 尝试读取日志文件中的最后几行错误
                error_details = ""
                try:
                    if os.path.exists("/app/rclone.log"):
                        with open("/app/rclone.log", "r") as log_file:
                            log_lines = log_file.readlines()
                            last_errors = [line for line in log_lines[-20:] if "ERROR" in line]
                            if last_errors:
                                error_details = "\n".join(last_errors)
                                print(f"rclone错误详情:\n{error_details}")
                except Exception as e:
                    print(f"读取日志文件失败: {e}")
                
                if self.bot and msg:
                    try:
                        # 获取文件大小
                        file_size = ""
                        try:
                            if os.path.exists(file_path):
                                file_size_bytes = os.path.getsize(file_path)
                                file_size = byte2_readable(file_size_bytes)
                        except:
                            pass
                        
                        fail_message = (
                            f'❌ <b>上传失败</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                            f'📂 <b>路径:</b> <code>{file_path}</code>'
                        )
                        if file_size:
                            fail_message += f'\n💾 <b>大小:</b> {file_size}'
                        fail_message += f'\n\n⚠️ <b>返回码:</b> <code>{process.returncode}</code>'
                        if error_details:
                            fail_message += f'\n\n📋 <b>错误详情:</b>\n<code>{error_details[:500]}</code>'
                        await self.bot.edit_message(msg, fail_message, parse_mode='html')
                    except Exception as e:
                        if "not modified" not in str(e).lower():
                            print(f"更新上传失败消息失败: {e}")
                
                # 发送详细错误信息到管理员
                if error_details and self.bot:
                    try:
                        error_detail_msg = (
                            f'📤 <b>上传错误详情</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name}</code>\n\n'
                            f'📋 <b>错误日志:</b>\n<code>{error_details[:3000]}</code>'
                        )
                        await self.bot.send_message(ADMIN_ID, error_detail_msg, parse_mode='html')
                    except:
                        pass
                
                return False
                
        except Exception as e:
            print(f"上传到OneDrive时出错: {e}")
            if self.bot:
                # 获取文件大小
                file_size = ""
                try:
                    if os.path.exists(file_path):
                        file_size_bytes = os.path.getsize(file_path)
                        file_size = byte2_readable(file_size_bytes)
                except:
                    pass
                
                error_message = (
                    f'❌ <b>上传异常</b>\n\n'
                    f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                    f'📂 <b>路径:</b> <code>{file_path}</code>'
                )
                if file_size:
                    error_message += f'\n💾 <b>大小:</b> {file_size}'
                error_message += f'\n\n⚠️ <b>错误信息:</b>\n<code>{str(e)}</code>'
                if msg:
                    try:
                        await self.bot.edit_message(msg, error_message, parse_mode='html')
                    except:
                        await self.bot.send_message(ADMIN_ID, error_message, parse_mode='html')
                else:
                    await self.bot.send_message(ADMIN_ID, error_message, parse_mode='html')
            return False

    async def upload_to_telegram_with_load_balance(self, file_path, gid):
        """
        使用多客户端负载均衡上传文件到Telegram
        """
        client_index = None
        try:
            file_name_display = os.path.basename(file_path)
            upload_start_msg = (
                f'📤 <b>上传到 Telegram</b>\n\n'
                f'📁 <b>文件:</b> <code>{file_name_display}</code>\n'
                f'📂 <b>路径:</b> <code>{file_path}</code>\n\n'
                f'⏳ <b>准备上传中...</b>'
            )
            
            # 选择上传客户端（使用负载均衡）
            upload_client = None
            
            if pyrogram_clients and len(pyrogram_clients) > 0:
                # 使用Pyrogram多客户端负载均衡
                # 优先选择能访问频道的客户端
                if channel_accessible_clients:
                    available_loads = {
                        k: v for k, v in upload_work_loads.items() 
                        if k in channel_accessible_clients and k in pyrogram_clients
                    }
                    if available_loads:
                        client_index = min(available_loads, key=available_loads.get)
                    else:
                        # 回退到所有客户端
                        valid_loads = {k: v for k, v in upload_work_loads.items() if k in pyrogram_clients}
                        if valid_loads:
                            client_index = min(valid_loads, key=valid_loads.get)
                else:
                    # 使用所有客户端
                    valid_loads = {k: v for k, v in upload_work_loads.items() if k in pyrogram_clients}
                    if valid_loads:
                        client_index = min(valid_loads, key=valid_loads.get)
                
                if client_index is not None and client_index in pyrogram_clients:
                    upload_client = pyrogram_clients[client_index]
                    upload_work_loads[client_index] = upload_work_loads.get(client_index, 0) + 1
                    print(f"使用Pyrogram客户端 {client_index} 上传文件（上传负载: {upload_work_loads[client_index]}）")
            
            # 如果没有Pyrogram客户端，使用Telethon bot
            if upload_client is None:
                upload_client = self.bot
                print("使用Telethon bot上传文件（未启用多客户端）")
            
            # 发送开始消息
            if hasattr(upload_client, 'send_message') and not hasattr(upload_client, 'get_me'):  # Telethon
                msg = await upload_client.send_message(ADMIN_ID, upload_start_msg, parse_mode='html')
            else:  # Pyrogram
                msg = await upload_client.send_message(ADMIN_ID, upload_start_msg)
            
            # 根据文件类型上传
            try:
                if file_path.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    # 图片文件
                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path)
                        temp_msg = await upload_client.send_file(ADMIN_ID, file_path, progress_callback=partial_callback)
                    else:  # Pyrogram
                        temp_msg = await upload_client.send_photo(ADMIN_ID, file_path)
                    
                    if FORWARD_ID:
                        if hasattr(temp_msg, 'forward_to'):  # Telethon
                            await temp_msg.forward_to(int(FORWARD_ID))
                        else:  # Pyrogram
                            await upload_client.forward_messages(int(FORWARD_ID), ADMIN_ID, temp_msg.id)
                    
                    if hasattr(msg, 'delete'):
                        await msg.delete()
                    
                    # 更新任务完成跟踪状态为 'uploaded'（Telegram上传）
                    if gid:
                        try:
                            from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                            import asyncio as asyncio_module
                            
                            if task_completion_lock:
                                async with task_completion_lock:
                                    task_completion_tracker[gid] = {
                                        'status': 'uploaded',
                                        'completed_at': asyncio_module.get_event_loop().time()
                                    }
                                    print(f"任务 {gid} 已标记为已上传（Telegram）")
                        except Exception as e:
                            print(f"更新任务上传状态失败: {e}")
                    
                    # 图片上传后不需要清理（图片通常不删除），但如果启用了AUTO_DELETE_AFTER_UPLOAD，也需要清理
                    if AUTO_DELETE_AFTER_UPLOAD and os.path.exists(file_path):
                        try:
                            os.unlink(file_path)
                            # 更新任务完成跟踪状态为 'cleaned'（Telegram上传）
                            if gid:
                                try:
                                    from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                                    import asyncio as asyncio_module
                                    
                                    if task_completion_lock:
                                        async with task_completion_lock:
                                            task_completion_tracker[gid] = {
                                                'status': 'cleaned',
                                                'completed_at': asyncio_module.get_event_loop().time()
                                            }
                                            print(f"任务 {gid} 已标记为已清理（Telegram上传）")
                                except Exception as e:
                                    print(f"更新任务清理状态失败: {e}")
                        except Exception as e:
                            print(f"删除图片文件失败: {e}")
                        
                elif file_path.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                    # 视频文件
                    pat = os.path.dirname(file_path)
                    filename = os.path.basename(file_path).split('.')[0]
                    thumb_path = pat + '/' + filename + '.jpg'
                    
                    # 生成视频封面
                    imgCoverFromFile(file_path, thumb_path)
                    
                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path)
                        temp_msg = await upload_client.send_file(
                            ADMIN_ID, 
                            file_path, 
                            thumb=thumb_path,
                            progress_callback=partial_callback
                        )
                    else:  # Pyrogram
                        temp_msg = await upload_client.send_video(ADMIN_ID, file_path, thumb=thumb_path)
                    
                    if FORWARD_ID:
                        if hasattr(temp_msg, 'forward_to'):  # Telethon
                            await temp_msg.forward_to(int(FORWARD_ID))
                        else:  # Pyrogram
                            await upload_client.forward_messages(int(FORWARD_ID), ADMIN_ID, temp_msg.id)
                    
                    if hasattr(msg, 'delete'):
                        await msg.delete()
                    
                    # 更新任务完成跟踪状态为 'uploaded'（Telegram上传）
                    if gid:
                        try:
                            from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                            import asyncio as asyncio_module
                            
                            if task_completion_lock:
                                async with task_completion_lock:
                                    task_completion_tracker[gid] = {
                                        'status': 'uploaded',
                                        'completed_at': asyncio_module.get_event_loop().time()
                                    }
                                    print(f"任务 {gid} 已标记为已上传（Telegram）")
                        except Exception as e:
                            print(f"更新任务上传状态失败: {e}")
                    
                    # 删除封面
                    if os.path.exists(thumb_path):
                        os.unlink(thumb_path)
                    
                    if AUTO_DELETE_AFTER_UPLOAD:
                        os.unlink(file_path)
                        # 更新任务完成跟踪状态为 'cleaned'（Telegram上传）
                        if gid:
                            try:
                                from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                                import asyncio as asyncio_module
                                
                                if task_completion_lock:
                                    async with task_completion_lock:
                                        task_completion_tracker[gid] = {
                                            'status': 'cleaned',
                                            'completed_at': asyncio_module.get_event_loop().time()
                                        }
                                        print(f"任务 {gid} 已标记为已清理（Telegram上传）")
                            except Exception as e:
                                print(f"更新任务清理状态失败: {e}")
                else:
                    # 其他文件类型
                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path)
                        temp_msg = await upload_client.send_file(ADMIN_ID, file_path, progress_callback=partial_callback)
                    else:  # Pyrogram
                        temp_msg = await upload_client.send_document(ADMIN_ID, file_path)
                    
                    if FORWARD_ID:
                        if hasattr(temp_msg, 'forward_to'):  # Telethon
                            await temp_msg.forward_to(int(FORWARD_ID))
                        else:  # Pyrogram
                            await upload_client.forward_messages(int(FORWARD_ID), ADMIN_ID, temp_msg.id)
                    
                    if hasattr(msg, 'delete'):
                        await msg.delete()
                    
                    if AUTO_DELETE_AFTER_UPLOAD:
                        os.unlink(file_path)
                        # 更新任务完成跟踪状态为 'cleaned'（Telegram上传）
                        if gid:
                            try:
                                from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                                import asyncio as asyncio_module
                                
                                if task_completion_lock:
                                    async with task_completion_lock:
                                        task_completion_tracker[gid] = {
                                            'status': 'cleaned',
                                            'completed_at': asyncio_module.get_event_loop().time()
                                        }
                                        print(f"任务 {gid} 已标记为已清理（Telegram上传）")
                            except Exception as e:
                                print(f"更新任务清理状态失败: {e}")
                        
            finally:
                # 减少上传负载
                if client_index is not None and client_index in upload_work_loads:
                    upload_work_loads[client_index] = max(0, upload_work_loads[client_index] - 1)
                    
        except Exception as e:
            print(f"上传到Telegram失败: {e}")
            import traceback
            traceback.print_exc()
            error_msg = (
                f'❌ <b>上传失败</b>\n\n'
                f'📂 <b>路径:</b> <code>{file_path}</code>\n\n'
                f'⚠️ <b>错误:</b> {str(e)}'
            )
            if self.bot:
                await self.bot.send_message(ADMIN_ID, error_msg, parse_mode='html')
            # 确保减少负载
            if client_index is not None and client_index in upload_work_loads:
                upload_work_loads[client_index] = max(0, upload_work_loads[client_index] - 1)

    async def callback(self, current, total, gid, msg=None, path=None):
        """
        上传进度回调函数
        """
        if not msg or not path:
            return
            
        gid_progress = self.progress_cache.get(gid, 0)
        new_progress = current / total
        formatted_progress = "{:.2%}".format(new_progress)
        if abs(new_progress - gid_progress) >= 0.05:
            self.progress_cache[gid] = new_progress
            file_name = os.path.basename(path)
            file_size = byte2_readable(total)
            current_size = byte2_readable(current)
            progress_bar = progress(int(total), int(current))
            
            new_message_text = (
                f'📤 <b>上传到 Telegram</b>\n\n'
                f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                f'📂 <b>路径:</b> <code>{path}</code>\n\n'
                f'📊 <b>进度:</b> {progress_bar}\n'
                f'💾 <b>已上传:</b> {current_size} / {file_size}\n'
                f'📈 <b>完成度:</b> {formatted_progress}'
            )
            try:
                await self.bot.edit_message(msg, new_message_text, parse_mode='html')
            except Exception as e:
                # 忽略"消息内容未修改"的错误
                if "not modified" not in str(e).lower():
                    print(f"更新进度消息失败: {e}")


async def main():
    client = AsyncAria2Client(RPC_SECRET, f'ws://{RPC_URL}', None)

    await client.connect()
    result = await client.get_global_option()
    pprint(result)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.create_task(main())
        loop.run_forever()
    except KeyboardInterrupt:
        pass
