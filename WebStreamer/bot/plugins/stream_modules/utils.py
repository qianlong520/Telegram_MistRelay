# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
工具函数模块
提供通用工具函数和aria2客户端管理
"""

import logging
from pyrogram.types import Message
from pyrogram.enums.parse_mode import ParseMode

logger = logging.getLogger(__name__)

# aria2客户端实例（延迟导入，避免循环依赖）
aria2_client = None


def set_aria2_client(client):
    """设置aria2客户端"""
    global aria2_client
    aria2_client = client


def should_download_file(message: Message) -> bool:
    """
    判断文件是否应该下载
    返回 True 表示应该下载，False 表示只转发不下载
    现在所有媒体文件都会下载，包括图片和贴纸
    """
    # 检查是否有任何媒体文件
    if (message.photo or message.video or message.animation or message.video_note or 
        message.document or message.audio or message.voice or message.sticker):
        return True
    
    # 默认不下载（如果没有媒体文件）
    return False


async def send_queue_notification(message: Message, queue_size: int):
    """
    发送排队通知给用户
    
    Args:
        message: 用户发送的消息
        queue_size: 当前队列大小（包括当前任务）
    
    Returns:
        回复消息对象
    """
    try:
        # 构建排队通知消息
        if queue_size == 1:
            queue_text = "⏳ <b>消息已加入处理队列</b>\n\n正在处理中..."
        else:
            queue_text = (
                f"⏳ <b>消息已加入处理队列</b>\n\n"
                f"📊 <b>队列位置:</b> {queue_size}\n"
                f"⏰ 请耐心等待，正在按顺序处理..."
            )
        
        reply_msg = await message.reply_text(
            text=queue_text,
            quote=True,
            parse_mode=ParseMode.HTML
        )
        return reply_msg
    except Exception as e:
        logger.error(f"发送排队通知失败: {e}", exc_info=True)
        return None
