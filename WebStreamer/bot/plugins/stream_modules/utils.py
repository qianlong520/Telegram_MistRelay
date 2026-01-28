# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
工具函数模块
提供通用工具函数和aria2客户端管理
"""

import logging
import asyncio
from pyrogram.types import Message
from pyrogram.enums.parse_mode import ParseMode

logger = logging.getLogger(__name__)

# aria2客户端实例（延迟导入，避免循环依赖）
aria2_client = None

# aria2最大并发下载数缓存（避免频繁查询）
_aria2_max_concurrent_cache = None


def set_aria2_client(client):
    """设置aria2客户端"""
    global aria2_client
    aria2_client = client


async def get_aria2_max_concurrent_downloads():
    """
    获取aria2的最大并发下载数（统一管理，避免多处配置）
    
    优先顺序：
    1. 从配置文件读取 ARIA2_MAX_CONCURRENT_DOWNLOADS
    2. 从aria2配置读取 max-concurrent-downloads
    3. 使用默认值 5
    
    Returns:
        int: 最大并发下载数
    """
    global _aria2_max_concurrent_cache
    
    # 如果缓存存在，直接返回
    if _aria2_max_concurrent_cache is not None:
        return _aria2_max_concurrent_cache
    
    # 优先从配置文件读取
    try:
        from configer import get_config_value
        config_value = get_config_value('ARIA2_MAX_CONCURRENT_DOWNLOADS', None)
        if config_value is not None:
            _aria2_max_concurrent_cache = int(config_value)
            logger.debug(f"从配置文件读取aria2最大并发下载数: {_aria2_max_concurrent_cache}")
            return _aria2_max_concurrent_cache
    except Exception as e:
        logger.debug(f"无法从配置文件读取aria2最大并发下载数: {e}")
    
    # 如果配置文件中没有，尝试从aria2配置读取
    if aria2_client:
        try:
            global_options = await aria2_client.get_global_option()
            max_concurrent = int(global_options.get('max-concurrent-downloads', 5))
            _aria2_max_concurrent_cache = max_concurrent
            logger.debug(f"从aria2配置读取最大并发下载数: {max_concurrent}")
            return max_concurrent
        except Exception as e:
            logger.debug(f"无法从aria2配置读取最大并发下载数: {e}")
    
    # 使用默认值
    _aria2_max_concurrent_cache = 5
    logger.debug(f"使用默认aria2最大并发下载数: 5")
    return 5


async def wait_for_download_slot(max_wait_time=60):
    """
    等待有空闲下载槽位（统一控制，确保不超过最大并发数）
    
    此函数会检查当前aria2的任务数，如果已达到最大并发数，则等待直到有空闲槽位。
    无论是否启用小文件跳过，都必须调用此函数来确保不超过最大并发数。
    
    Args:
        max_wait_time: 最大等待时间（秒），默认60秒
    
    Returns:
        bool: True表示有空闲槽位，False表示超时（但任务仍可添加到等待队列）
    """
    if not aria2_client:
        logger.warning("aria2客户端未初始化，跳过槽位检查")
        return True
    
    max_concurrent = await get_aria2_max_concurrent_downloads()
    wait_start = asyncio.get_event_loop().time()
    last_log_time = 0
    check_interval = 2.0  # 每2秒检查一次
    
    while True:
        try:
            # 获取当前正在下载和等待的任务数
            active_tasks = await aria2_client.tell_active()
            waiting_tasks = await aria2_client.tell_waiting(0, 100)
            current_count = len(active_tasks) + len(waiting_tasks)
            elapsed_time = asyncio.get_event_loop().time() - wait_start
            
            # 如果当前任务数小于最大并发数，有空闲槽位
            if current_count < max_concurrent:
                if elapsed_time > 1:  # 如果等待了超过1秒，记录日志
                    logger.debug(f"等待空闲槽位成功，当前任务数: {current_count}/{max_concurrent}，等待时间: {elapsed_time:.1f}秒")
                return True
            
            # 定期记录等待状态（每5秒记录一次）
            if elapsed_time - last_log_time >= 5:
                logger.debug(
                    f"等待空闲槽位中... 当前任务数: {current_count}/{max_concurrent}，"
                    f"已等待: {elapsed_time:.1f}秒"
                )
                last_log_time = elapsed_time
            
            # 检查是否超时
            if elapsed_time > max_wait_time:
                logger.warning(
                    f"等待空闲槽位超时（{max_wait_time}秒），当前任务数: {current_count}/{max_concurrent}，"
                    f"将继续尝试添加任务（任务将进入等待队列）"
                )
                # 即使超时也返回True，让任务添加到等待队列
                return True
            
            # 等待后重试
            await asyncio.sleep(check_interval)
        except Exception as e:
            logger.error(f"检查aria2任务状态失败: {e}")
            # 如果检查失败，等待一下再继续
            await asyncio.sleep(1.0)
            # 如果检查失败，假设有空闲位置，继续尝试
            return True


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


# GID到队列通知消息的映射（用于清理完成后更新通知）
# 格式: {gid: queue_reply_msg}
_gid_to_queue_msg_map = {}
# GID到原始消息的映射（用于清理完成后发送完成通知）
# 格式: {gid: original_message}
_gid_to_original_msg_map = {}
_gid_to_queue_msg_lock = asyncio.Lock() if asyncio else None


def register_gid_queue_msg(gid: str, queue_reply_msg, original_msg=None):
    """
    注册GID和队列通知消息的关联，以及原始消息（如果提供）
    
    Args:
        gid: 下载任务GID
        queue_reply_msg: 队列通知消息对象（可选）
        original_msg: 原始消息对象（可选，用于发送完成通知）
    """
    global _gid_to_queue_msg_map, _gid_to_original_msg_map, _gid_to_queue_msg_lock
    if gid:
        try:
            # 注册队列通知消息（如果提供）
            if queue_reply_msg:
                _gid_to_queue_msg_map[gid] = queue_reply_msg
                logger.debug(f"已注册GID {gid} 的队列通知消息")
            # 注册原始消息（如果提供）
            if original_msg:
                _gid_to_original_msg_map[gid] = original_msg
                logger.debug(f"已注册GID {gid} 的原始消息")
        except Exception as e:
            logger.debug(f"注册GID消息失败: {e}")


async def update_queue_msg_on_cleanup(gid: str):
    """
    在清理完成时更新队列通知消息或发送完成通知到原始消息
    
    Args:
        gid: 下载任务GID
    """
    global _gid_to_queue_msg_map, _gid_to_original_msg_map, _gid_to_queue_msg_lock
    
    if not gid:
        return
    
    completion_text = (
        "✅ <b>任务已完成</b>\n\n"
        "📥 消息已处理完成\n"
        "☁️ 文件已上传\n"
        "🗑️ 本地文件已清理\n\n"
        "🎉 所有操作已完成！"
    )
    
    try:
        queue_reply_msg = None
        original_msg = None
        
        if _gid_to_queue_msg_lock:
            async with _gid_to_queue_msg_lock:
                queue_reply_msg = _gid_to_queue_msg_map.get(gid)
                original_msg = _gid_to_original_msg_map.get(gid)
                # 清理映射（避免内存泄漏）
                if gid in _gid_to_queue_msg_map:
                    del _gid_to_queue_msg_map[gid]
                if gid in _gid_to_original_msg_map:
                    del _gid_to_original_msg_map[gid]
        else:
            queue_reply_msg = _gid_to_queue_msg_map.get(gid)
            original_msg = _gid_to_original_msg_map.get(gid)
            if gid in _gid_to_queue_msg_map:
                del _gid_to_queue_msg_map[gid]
            if gid in _gid_to_original_msg_map:
                del _gid_to_original_msg_map[gid]
        
        # 优先更新队列通知消息（如果存在）
        if queue_reply_msg:
            try:
                await queue_reply_msg.edit_text(
                    text=completion_text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"已更新GID {gid} 的队列通知消息为完成状态")
            except Exception as e:
                logger.error(f"更新队列通知消息失败: {e}", exc_info=True)
        # 如果没有队列通知消息，但有原始消息，则回复原始消息
        elif original_msg:
            try:
                await original_msg.reply_text(
                    text=completion_text,
                    quote=True,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"已向GID {gid} 的原始消息发送完成通知")
            except Exception as e:
                logger.error(f"向原始消息发送完成通知失败: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"处理清理完成通知失败: {e}", exc_info=True)


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
            queue_text = (
                "✅ <b>已收到您的消息</b>\n\n"
                "📥 消息已加入处理队列\n"
                "🔄 正在处理中，请稍候..."
            )
        else:
            queue_text = (
                f"✅ <b>已收到您的消息</b>\n\n"
                f"📥 <b>消息已加入处理队列</b>\n"
                f"📊 <b>队列位置:</b> 第 {queue_size} 位\n"
                f"⏰ 请耐心等待，正在按顺序处理..."
            )
        
        reply_msg = await message.reply_text(
            text=queue_text,
            quote=True,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"已发送队列通知给用户，队列位置: {queue_size}")
        return reply_msg
    except Exception as e:
        logger.error(f"发送排队通知失败: {e}", exc_info=True)
        return None
