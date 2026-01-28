"""
WebSocket 连接管理器
用于管理所有 WebSocket 客户端连接，并推送实时状态更新
"""
import asyncio
import json
import logging
from typing import Set, Dict, Any
from aiohttp import web
from threading import Lock

logger = logging.getLogger(__name__)

class WebSocketManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.connections: Set[web.WebSocketResponse] = set()
        self.lock = asyncio.Lock()
        # 为每种消息类型维护独立的序列号生成器（线程安全）
        self._seq_lock = Lock()
        self._sequence_numbers: Dict[str, int] = {
            'download_update': 0,
            'upload_update': 0,
            'cleanup_update': 0,
            'statistics_update': 0
        }
    
    def _get_next_seq(self, message_type: str) -> int:
        """获取指定消息类型的下一个序列号（线程安全）"""
        with self._seq_lock:
            if message_type not in self._sequence_numbers:
                self._sequence_numbers[message_type] = 0
            self._sequence_numbers[message_type] += 1
            return self._sequence_numbers[message_type]
    
    async def add_connection(self, ws: web.WebSocketResponse):
        """添加 WebSocket 连接"""
        async with self.lock:
            self.connections.add(ws)
            logger.info(f"WebSocket 连接已添加，当前连接数: {len(self.connections)}")
    
    async def remove_connection(self, ws: web.WebSocketResponse):
        """移除 WebSocket 连接"""
        async with self.lock:
            self.connections.discard(ws)
            logger.info(f"WebSocket 连接已移除，当前连接数: {len(self.connections)}")
    
    async def broadcast(self, message: Dict[str, Any]):
        """广播消息到所有连接的客户端"""
        if not self.connections:
            return
        
        message_json = json.dumps(message, ensure_ascii=False)
        disconnected = set()
        
        async with self.lock:
            for ws in self.connections:
                try:
                    if not ws.closed:
                        await ws.send_str(message_json)
                    else:
                        disconnected.add(ws)
                except Exception as e:
                    logger.error(f"发送 WebSocket 消息失败: {e}")
                    disconnected.add(ws)
            
            # 清理已断开的连接
            for ws in disconnected:
                self.connections.discard(ws)
    
    async def send_download_update(self, download_data: Dict[str, Any]):
        """发送下载状态更新"""
        await self.broadcast({
            "type": "download_update",
            "seq": self._get_next_seq("download_update"),
            "data": download_data
        })
    
    async def send_upload_update(self, upload_data: Dict[str, Any]):
        """发送上传状态更新"""
        await self.broadcast({
            "type": "upload_update",
            "seq": self._get_next_seq("upload_update"),
            "data": upload_data
        })
    
    async def send_cleanup_update(self, cleanup_data: Dict[str, Any]):
        """发送清理状态更新"""
        await self.broadcast({
            "type": "cleanup_update",
            "seq": self._get_next_seq("cleanup_update"),
            "data": cleanup_data
        })
    
    async def send_statistics_update(self, statistics: Dict[str, Any]):
        """发送统计信息更新"""
        await self.broadcast({
            "type": "statistics_update",
            "seq": self._get_next_seq("statistics_update"),
            "data": statistics
        })

# 全局 WebSocket 管理器实例
ws_manager = WebSocketManager()
