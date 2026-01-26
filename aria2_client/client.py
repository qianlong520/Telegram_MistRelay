"""
Aria2 WebSocket客户端核心模块
"""
import asyncio
import base64
import json
import uuid
from typing import List, Dict, Any, Optional

import aiohttp
import websockets

from configer import RPC_URL, RPC_SECRET

from .download_handler import DownloadHandler
from .upload_handler import UploadHandler


class AsyncAria2Client:
    """Aria2异步WebSocket客户端"""
    
    def __init__(self, rpc_secret, ws_url, bot=None):
        """
        初始化Aria2客户端
        
        Args:
            rpc_secret: RPC密钥
            ws_url: WebSocket URL
            bot: Telegram bot实例(可选)
        """
        self.rpc_secret = rpc_secret
        self.ws_url = ws_url
        self.websocket = None
        self.reconnect = True
        self.bot = bot
        self.progress_cache = {}
        self.download_messages = {}  # 存储每个下载任务的消息对象
        self.completed_gids = set()  # 记录已完成的GID，防止重复处理
        
        # 初始化处理器
        self.upload_handler = UploadHandler(bot, self.progress_cache)
        self.download_handler = DownloadHandler(
            bot, 
            self.download_messages, 
            self.completed_gids,
            self.upload_handler
        )

    async def connect(self):
        """连接到Aria2 WebSocket服务器"""
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
        """监听WebSocket消息"""
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
                        await self.download_handler.on_download_start(result, self.tell_status)
                    elif method_name == 'aria2.onDownloadComplete':
                        await self.download_handler.on_download_complete(result, self.tell_status)
                    elif method_name == 'aria2.onDownloadError':
                        await self.download_handler.on_download_error(result, self.tell_status)
                    elif method_name == 'aria2.onDownloadPause':
                        await self.download_handler.on_download_pause(result, self.tell_status)
        except websockets.exceptions.ConnectionClosedError:
            print("WebSocket连接已关闭")
            await self.re_connect()

    def parse_json_to_str(self, method, params):
        """将RPC方法和参数转换为JSON字符串"""
        params_ = self.get_rpc_body(method, params)
        return json.dumps(params_)

    def get_rpc_body(self, method, params=[]):
        """构建RPC请求体"""
        params_ = {
            'jsonrpc': '2.0',
            'id': str(uuid.uuid4()),
            'method': method,
            'params': [f'token:{self.rpc_secret}'] + params
        }
        return params_

    async def add_uri(self, uris: List[str], options: Dict[str, Any] = None):
        """
        添加URI下载任务
        
        Args:
            uris: URI列表
            options: 下载选项
            
        Returns:
            dict: RPC响应结果
        """
        params = [uris]
        if options:
            params.append(options)

        rpc_body = self.get_rpc_body('aria2.addUri', params)
        print(rpc_body)
        result = await self.post_body(rpc_body)
        
        return result

    async def add_torrent(self, path, options=None, position: int = None):
        """
        添加种子下载任务
        
        Args:
            path: 种子文件路径
            options: 下载选项
            position: 队列位置
            
        Returns:
            dict: RPC响应结果
        """
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
        """
        获取任务状态
        
        Args:
            gid: 任务GID
            
        Returns:
            dict: 任务状态信息
        """
        params = [gid]
        rpc_body = self.get_rpc_body('aria2.tellStatus', params)
        data = await self.post_body(rpc_body)
        return data['result']

    async def post_body(self, rpc_body):
        """
        发送RPC请求
        
        Args:
            rpc_body: RPC请求体
            
        Returns:
            dict: RPC响应
        """
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
        """重新连接到WebSocket服务器"""
        if self.reconnect:
            print("等待5秒后尝试重新连接...")
            await asyncio.sleep(5)
            await self.connect()
        else:
            print("已禁用重新连接功能")

    async def tell_stopped(self, offset: int, num: int):
        """获取已停止的任务列表"""
        params = [
            offset, num
        ]
        rpc_body = self.get_rpc_body('aria2.tellStopped', params)
        data = await self.post_body(rpc_body)
        return data['result']

    async def tell_waiting(self, offset: int, num: int):
        """获取等待中的任务列表"""
        params = [
            offset, num
        ]
        rpc_body = self.get_rpc_body('aria2.tellWaiting', params)
        data = await self.post_body(rpc_body)
        return data['result']

    async def tell_active(self):
        """获取活动任务列表"""
        params = []
        rpc_body = self.get_rpc_body('aria2.tellActive', params)
        data = await self.post_body(rpc_body)
        return data['result']

    async def pause(self, gid: str):
        """暂停任务"""
        params = [gid]
        jsonreq = self.parse_json_to_str('aria2.pause', params)
        print(jsonreq)
        await self.websocket.send(jsonreq)

    async def unpause(self, gid: str):
        """恢复任务"""
        params = [gid]
        jsonreq = self.parse_json_to_str('aria2.unpause', params)
        print(jsonreq)
        await self.websocket.send(jsonreq)

    async def remove(self, gid: str):
        """移除任务"""
        params = [gid]
        rpc_body = self.get_rpc_body('aria2.remove', params)
        data = await self.post_body(rpc_body)
        return data

    async def remove_download_result(self, gid: str):
        """移除下载结果"""
        params = [gid]
        jsonreq = self.parse_json_to_str('aria2.removeDownloadResult', params)
        print(jsonreq)
        await self.websocket.send(jsonreq)

    async def change_global_option(self, params):
        """修改全局选项"""
        rpc_body = self.get_rpc_body('aria2.changeGlobalOption', params)
        return await self.post_body(rpc_body)

    async def get_global_option(self):
        """获取全局选项"""
        rpc_body = self.get_rpc_body('aria2.getGlobalOption')
        data = await self.post_body(rpc_body)
        return data['result']
