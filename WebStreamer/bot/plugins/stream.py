# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import logging
import asyncio
import time
from collections import defaultdict
from pyrogram import filters, errors
from WebStreamer.vars import Var
from urllib.parse import quote_plus
from WebStreamer.bot import StreamBot, logger
from WebStreamer.utils import get_hash, get_name
from pyrogram.enums.parse_mode import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# 导入aria2客户端（延迟导入，避免循环依赖）
aria2_client = None

# 媒体组缓存：用于收集同一媒体组的所有消息
media_group_cache = defaultdict(list)
media_group_tasks = {}

# 消息处理队列（严格串行执行）
# 每条转发给bot的信息都当成一条队列数据
# 如果当前队列没有执行完，等待队列就不进入（严格按顺序执行，一个完成后再执行下一个）
message_processing_queue = None
queue_processor_task = None
queue_processing_lock = None  # 用于确保队列处理器只有一个实例在运行

# 任务完成跟踪：跟踪每个下载任务的完成状态（包括上传和清理）
# 格式: {gid: {'status': 'downloading'|'completed'|'uploaded'|'cleaned', 'completed_at': timestamp}}
task_completion_tracker = {}
task_completion_lock = asyncio.Lock() if asyncio else None

# 队列项信息跟踪：跟踪每个队列项的详细信息
# 格式: {queue_id: {'message_id': int, 'chat_id': int, 'title': str, 'type': 'single'|'media_group', 
#                    'media_group_total': int, 'status': 'waiting'|'processing'|'completed', 
#                    'task_gids': list, 'added_at': timestamp}}
queue_item_tracker = {}
current_processing_queue_id = None  # 当前正在处理的队列ID
queue_tracker_lock = asyncio.Lock() if asyncio else None
queue_id_counter = 0  # 队列ID计数器


def _ensure_queue_initialized():
    """
    确保队列已初始化（延迟初始化，在事件循环中创建）
    """
    global message_processing_queue, queue_processing_lock, task_completion_lock, queue_tracker_lock
    
    if message_processing_queue is None:
        message_processing_queue = asyncio.Queue()
    
    if queue_processing_lock is None:
        queue_processing_lock = asyncio.Lock()
    
    if task_completion_lock is None:
        try:
            task_completion_lock = asyncio.Lock()
        except RuntimeError:
            # 如果没有事件循环，稍后初始化
            pass
    
    if queue_tracker_lock is None:
        try:
            queue_tracker_lock = asyncio.Lock()
        except RuntimeError:
            # 如果没有事件循环，稍后初始化
            pass

def set_aria2_client(client):
    """设置aria2客户端"""
    global aria2_client
    aria2_client = client


async def message_queue_processor():
    """
    消息队列处理器：严格串行执行，一个任务完成后再执行下一个
    每条转发给bot的信息都当成一条队列数据，如果当前队列没有执行完，等待队列就不进入
    """
    # 确保队列已初始化
    _ensure_queue_initialized()
    
    logger.info("消息队列处理器已启动（严格串行模式：一个任务完成后再执行下一个）")
    while True:
        try:
            # 从队列中获取消息处理任务（这里会阻塞等待，直到有任务）
            # 队列项格式: (task_func, args, kwargs, queue_notification, queue_id)
            queue_item = await message_processing_queue.get()
            
            # 解包队列项（兼容旧格式）
            queue_id = None
            if len(queue_item) >= 5:
                task_func, task_args, task_kwargs, queue_notification, queue_id = queue_item
            elif len(queue_item) == 4:
                task_func, task_args, task_kwargs, queue_notification = queue_item
            else:
                # 兼容旧格式（没有排队通知和队列ID）
                task_func, task_args, task_kwargs = queue_item[:3]
                queue_notification = None
            
            # 更新队列项状态为"正在处理"
            global current_processing_queue_id
            if queue_id and queue_tracker_lock:
                try:
                    async with queue_tracker_lock:
                        if queue_id in queue_item_tracker:
                            queue_item_tracker[queue_id]['status'] = 'processing'
                            current_processing_queue_id = queue_id
                except Exception as e:
                    logger.debug(f"更新队列项状态失败: {e}")
            
            queue_size = message_processing_queue.qsize()
            if queue_size > 0:  # 只有当队列中还有任务时才记录
                logger.debug(f"开始处理消息任务，队列中还有 {queue_size} 个任务等待处理")
            
            # 等待排队通知发送完成（如果有）
            queue_reply_msg = None
            if queue_notification:
                try:
                    queue_reply_msg = await queue_notification
                except Exception as e:
                    logger.error(f"获取排队通知消息失败: {e}", exc_info=True)
            
            try:
                # 执行任务（严格串行，一个完成后再执行下一个）
                # 将排队回复消息传递给处理函数（如果支持）
                task_gids = []  # 记录本次处理添加的所有下载任务GID
                
                if task_args and task_kwargs:
                    # 尝试传递排队回复消息
                    if 'queue_reply_msg' not in task_kwargs:
                        task_kwargs['queue_reply_msg'] = queue_reply_msg
                    result = await task_func(*task_args, **task_kwargs)
                    # 如果函数返回了任务GID列表，记录下来
                    if isinstance(result, list):
                        task_gids = result
                elif task_args:
                    # 对于只有位置参数的情况，需要修改函数签名来支持
                    # 这里先尝试直接调用，如果函数支持queue_reply_msg参数，会在函数内部处理
                    result = await task_func(*task_args, queue_reply_msg=queue_reply_msg)
                    if isinstance(result, list):
                        task_gids = result
                elif task_kwargs:
                    task_kwargs['queue_reply_msg'] = queue_reply_msg
                    result = await task_func(**task_kwargs)
                    if isinstance(result, list):
                        task_gids = result
                else:
                    result = await task_func(queue_reply_msg=queue_reply_msg)
                    if isinstance(result, list):
                        task_gids = result
                
                # 更新队列项的任务GID列表
                if queue_id and queue_tracker_lock and task_gids:
                    try:
                        async with queue_tracker_lock:
                            if queue_id in queue_item_tracker:
                                queue_item_tracker[queue_id]['task_gids'] = task_gids
                    except Exception as e:
                        logger.debug(f"更新队列项任务GID失败: {e}")
                
                # 如果有下载任务，等待所有任务完成（包括上传和清理）
                if task_gids and aria2_client:
                    await wait_for_tasks_completion(task_gids)
                
                # 更新队列项状态为"已完成"
                if queue_id and queue_tracker_lock:
                    try:
                        async with queue_tracker_lock:
                            if queue_id in queue_item_tracker:
                                queue_item_tracker[queue_id]['status'] = 'completed'
                            if current_processing_queue_id == queue_id:
                                current_processing_queue_id = None
                    except Exception as e:
                        logger.debug(f"更新队列项完成状态失败: {e}")
                
                remaining = message_processing_queue.qsize()
                if remaining > 0:
                    logger.debug(f"消息任务处理完成，队列中还有 {remaining} 个任务等待")
            except TypeError as e:
                # 如果函数不支持queue_reply_msg参数，使用原始调用方式
                if 'queue_reply_msg' in str(e):
                    try:
                        if task_args and task_kwargs:
                            await task_func(*task_args, **task_kwargs)
                        elif task_args:
                            await task_func(*task_args)
                        elif task_kwargs:
                            await task_func(**task_kwargs)
                        else:
                            await task_func()
                    except Exception as e2:
                        logger.error(f"处理消息队列任务失败: {e2}", exc_info=True)
                else:
                    logger.error(f"处理消息队列任务失败: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"处理消息队列任务失败: {e}", exc_info=True)
            finally:
                # 更新队列项状态（即使出错也标记）
                if queue_id and queue_tracker_lock:
                    try:
                        async with queue_tracker_lock:
                            if queue_id in queue_item_tracker:
                                if queue_item_tracker[queue_id]['status'] != 'completed':
                                    queue_item_tracker[queue_id]['status'] = 'completed'  # 出错也标记为完成
                            if current_processing_queue_id == queue_id:
                                current_processing_queue_id = None
                    except Exception as e:
                        logger.debug(f"更新队列项最终状态失败: {e}")
                
                # 标记任务完成（必须在finally中执行，确保即使出错也标记完成）
                message_processing_queue.task_done()
        except Exception as e:
            logger.error(f"消息队列处理器出错: {e}", exc_info=True)
            await asyncio.sleep(1)  # 出错后等待1秒再继续


async def wait_for_tasks_completion(task_gids: list):
    """
    等待所有下载任务完成（包括上传和清理）
    
    Args:
        task_gids: 下载任务GID列表
    """
    global task_completion_lock  # 必须在函数开头声明global
    
    if not task_gids:
        return
    
    logger.info(f"等待 {len(task_gids)} 个下载任务完成（包括上传和清理）...")
    
    # 确保锁已初始化
    if task_completion_lock is None:
        try:
            task_completion_lock = asyncio.Lock()
        except RuntimeError:
            logger.warning("无法创建任务完成锁，跳过等待")
            return
    
    completed_gids = set()
    check_interval = 5  # 每5秒检查一次
    max_wait_time = 3600 * 24  # 最大等待24小时（防止无限等待）
    wait_start = asyncio.get_event_loop().time()
    last_log_time = 0
    
    while len(completed_gids) < len(task_gids):
        # 检查是否超时
        elapsed_time = asyncio.get_event_loop().time() - wait_start
        if elapsed_time > max_wait_time:
            logger.warning(f"等待任务完成超时（{max_wait_time}秒），已等待: {elapsed_time:.1f}秒")
            break
        
        # 定期记录等待状态（每30秒记录一次）
        if elapsed_time - last_log_time >= 30:
            remaining_count = len(task_gids) - len(completed_gids)
            logger.info(f"等待任务完成中... 已完成: {len(completed_gids)}/{len(task_gids)}，剩余: {remaining_count}")
            last_log_time = elapsed_time
        
        # 检查每个任务的状态
        for gid in task_gids:
            if gid in completed_gids:
                continue
            
            try:
                # 检查任务完成状态
                async with task_completion_lock:
                    task_status = task_completion_tracker.get(gid, {})
                    status = task_status.get('status', 'downloading')
                    
                    # 如果任务已完成、已上传或已清理，标记为完成
                    if status in ['completed', 'uploaded', 'cleaned']:
                        completed_gids.add(gid)
                        continue
                
                # 检查aria2任务状态
                if aria2_client:
                    try:
                        aria2_status = await aria2_client.tell_status(gid)
                        aria2_task_status = aria2_status.get('status', '')
                        
                        # 如果aria2任务已完成，检查上传和清理状态
                        if aria2_task_status == 'complete':
                            # 检查任务完成跟踪器中的状态
                            async with task_completion_lock:
                                task_status = task_completion_tracker.get(gid, {})
                                status = task_status.get('status', 'completed')
                                
                                # 如果状态是cleaned（已清理），标记为完成
                                if status == 'cleaned':
                                    completed_gids.add(gid)
                                # 如果状态是uploaded（已上传），检查是否需要等待清理
                                elif status == 'uploaded':
                                    # 检查配置（需要从configer导入）
                                    try:
                                        from configer import AUTO_DELETE_AFTER_UPLOAD
                                        # 如果AUTO_DELETE_AFTER_UPLOAD为False，上传完成即视为完成
                                        if not AUTO_DELETE_AFTER_UPLOAD:
                                            completed_gids.add(gid)
                                        # 如果AUTO_DELETE_AFTER_UPLOAD为True，需要等待清理（状态变为cleaned）
                                    except ImportError:
                                        # 如果无法导入配置，检查是否有上传配置（UP_ONEDRIVE或UP_TELEGRAM）
                                        try:
                                            from configer import UP_ONEDRIVE, UP_TELEGRAM
                                            # 如果没有启用上传，下载完成即视为完成
                                            if not UP_ONEDRIVE and not UP_TELEGRAM:
                                                completed_gids.add(gid)
                                        except ImportError:
                                            # 如果无法导入配置，假设需要等待清理
                                            pass
                                # 如果状态是completed（仅下载完成），检查是否启用了上传
                                elif status == 'completed':
                                    try:
                                        from configer import UP_ONEDRIVE, UP_TELEGRAM
                                        # 如果没有启用上传，下载完成即视为完成
                                        if not UP_ONEDRIVE and not UP_TELEGRAM:
                                            completed_gids.add(gid)
                                    except ImportError:
                                        # 如果无法导入配置，假设需要等待上传
                                        pass
                        elif aria2_task_status in ['error', 'removed']:
                            # 任务失败或被移除，标记为完成（不再等待）
                            completed_gids.add(gid)
                            logger.warning(f"任务 {gid} 状态为 {aria2_task_status}，不再等待")
                    except Exception as e:
                        # 如果无法获取状态，可能是任务不存在或已删除
                        logger.debug(f"无法获取任务 {gid} 状态: {e}")
                        # 检查任务完成跟踪器
                        async with task_completion_lock:
                            task_status = task_completion_tracker.get(gid, {})
                            if task_status.get('status') == 'cleaned':
                                completed_gids.add(gid)
            except Exception as e:
                logger.debug(f"检查任务 {gid} 完成状态时出错: {e}")
        
        # 如果还有未完成的任务，等待一段时间后重试
        if len(completed_gids) < len(task_gids):
            await asyncio.sleep(check_interval)
    
    completed_count = len(completed_gids)
    logger.info(f"任务完成等待结束：{completed_count}/{len(task_gids)} 个任务已完成")
    
    # 清理已完成的任务跟踪记录（保留最近1小时内的记录）
    if task_completion_lock:
        try:
            async with task_completion_lock:
                current_time = asyncio.get_event_loop().time()
                gids_to_remove = []
                for gid, status_info in task_completion_tracker.items():
                    completed_at = status_info.get('completed_at', 0)
                    if completed_at > 0 and current_time - completed_at > 3600:  # 1小时前完成的
                        gids_to_remove.append(gid)
                for gid in gids_to_remove:
                    del task_completion_tracker[gid]
        except Exception as e:
            logger.debug(f"清理任务跟踪记录时出错: {e}")


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


def enqueue_message_task(task_func, *args, **kwargs):
    """
    将消息处理任务加入队列（严格串行执行）
    每条转发给bot的信息都当成一条队列数据，如果当前队列没有执行完，等待队列就不进入
    
    Args:
        task_func: 要执行的异步函数
        *args: 位置参数
        **kwargs: 关键字参数
    
    Returns:
        排队通知消息（如果有）
    """
    global queue_processor_task, queue_id_counter
    
    # 确保队列已初始化
    _ensure_queue_initialized()
    
    # 确保队列处理器任务已启动（使用锁确保只有一个处理器实例）
    async def _ensure_processor_started():
        global queue_processor_task
        
        # 确保锁已初始化
        if queue_processing_lock is None:
            return
        
        async with queue_processing_lock:
            if queue_processor_task is None or queue_processor_task.done():
                try:
                    loop = asyncio.get_event_loop()
                    queue_processor_task = loop.create_task(message_queue_processor())
                    logger.info("消息队列处理器任务已创建")
                except RuntimeError:
                    # 如果没有事件循环，尝试创建新的事件循环（不应该发生，但为了安全）
                    logger.warning("无法获取事件循环，尝试创建新的事件循环")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    queue_processor_task = loop.create_task(message_queue_processor())
    
    # 在事件循环中启动处理器（如果还没有启动）
    try:
        loop = asyncio.get_event_loop()
        if queue_processor_task is None or queue_processor_task.done():
            # 创建任务来启动处理器
            loop.create_task(_ensure_processor_started())
    except RuntimeError:
        logger.warning("无法获取事件循环，队列处理器将在下次使用时启动")
    
    # 将任务加入队列
    try:
        # 计算队列大小（包括即将加入的任务）
        queue_size = message_processing_queue.qsize() + 1
        
        # 从参数中提取消息对象（用于发送排队通知和跟踪队列信息）
        message_obj = None
        is_media_group = False
        media_group_total = 0
        
        if args and len(args) > 0:
            # 检查第一个参数是否是Message对象（单个媒体）或消息列表（媒体组）
            first_arg = args[0]
            if isinstance(first_arg, Message):
                message_obj = first_arg
                is_media_group = False
            elif isinstance(first_arg, list) and len(first_arg) > 0 and isinstance(first_arg[0], Message):
                # 媒体组的情况
                message_obj = first_arg[0]
                is_media_group = True
                media_group_total = len(first_arg)
        
        # 生成队列ID并记录队列项信息
        queue_id = None
        if message_obj and queue_tracker_lock:
            try:
                queue_id_counter += 1
                queue_id = queue_id_counter
                
                # 获取消息标题
                title = get_name(message_obj) if hasattr(message_obj, 'document') or hasattr(message_obj, 'video') or hasattr(message_obj, 'audio') else "媒体文件"
                if not title or title == "":
                    title = "媒体文件"
                
                # 记录队列项信息
                import asyncio as asyncio_module
                try:
                    loop = asyncio_module.get_event_loop()
                    if loop.is_running():
                        # 如果事件循环正在运行，使用异步方式
                        async def _track_queue_item():
                            async with queue_tracker_lock:
                                queue_item_tracker[queue_id] = {
                                    'message_id': message_obj.id,
                                    'chat_id': message_obj.chat.id,
                                    'title': title,
                                    'type': 'media_group' if is_media_group else 'single',
                                    'media_group_total': media_group_total,
                                    'status': 'waiting',
                                    'task_gids': [],
                                    'added_at': asyncio_module.get_event_loop().time()
                                }
                        loop.create_task(_track_queue_item())
                    else:
                        # 如果事件循环未运行，直接设置（不应该发生）
                        queue_item_tracker[queue_id] = {
                            'message_id': message_obj.id,
                            'chat_id': message_obj.chat.id,
                            'title': title,
                            'type': 'media_group' if is_media_group else 'single',
                            'media_group_total': media_group_total,
                            'status': 'waiting',
                            'task_gids': [],
                            'added_at': time.time() if hasattr(time, 'time') else 0
                        }
                except Exception as e:
                    logger.debug(f"记录队列项信息失败: {e}")
            except Exception as e:
                logger.debug(f"生成队列ID失败: {e}")
        
        # 发送排队通知（如果有消息对象）
        queue_notification = None
        if message_obj:
            try:
                # 在事件循环中发送通知
                loop = asyncio.get_event_loop()
                queue_notification = loop.create_task(send_queue_notification(message_obj, queue_size))
            except Exception as e:
                logger.error(f"创建排队通知任务失败: {e}", exc_info=True)
        
        # 将任务加入队列（包含排队通知任务和队列ID）
        message_processing_queue.put_nowait((task_func, args, kwargs, queue_notification, queue_id))
        
        if queue_size > 10:  # 当队列积压超过10个任务时，记录警告
            logger.warning(f"消息处理队列积压: {queue_size} 个任务等待处理（严格串行模式，请耐心等待）")
        elif queue_size > 5:  # 当队列积压超过5个任务时，记录信息
            logger.info(f"消息已加入处理队列，当前队列大小: {queue_size}（严格串行模式，按顺序处理）")
        else:
            logger.debug(f"消息已加入处理队列，当前队列大小: {queue_size}")
    except Exception as e:
        logger.error(f"将任务加入队列失败: {e}", exc_info=True)


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


async def get_queue_status():
    """
    获取消息队列状态
    
    Returns:
        dict: 包含队列状态信息的字典
    """
    global current_processing_queue_id
    
    if not queue_tracker_lock or message_processing_queue is None:
        return {
            'current_processing': None,
            'waiting_count': 0,
            'waiting_items': [],
            'queue_size': 0
        }
    
    try:
        async with queue_tracker_lock:
            # 获取当前正在处理的项目
            current_item = None
            if current_processing_queue_id and current_processing_queue_id in queue_item_tracker:
                current_item = queue_item_tracker[current_processing_queue_id].copy()
            
            # 获取等待中的项目
            waiting_items = []
            for queue_id, item_info in queue_item_tracker.items():
                if item_info['status'] == 'waiting':
                    waiting_items.append({
                        'queue_id': queue_id,
                        'title': item_info['title'],
                        'type': item_info['type'],
                        'media_group_total': item_info.get('media_group_total', 0),
                        'added_at': item_info.get('added_at', 0)
                    })
            
            # 按添加时间排序
            waiting_items.sort(key=lambda x: x['added_at'])
            
            # 获取队列大小
            queue_size = message_processing_queue.qsize() if message_processing_queue else 0
            
            return {
                'current_processing': current_item,
                'waiting_count': len(waiting_items),
                'waiting_items': waiting_items,
                'queue_size': queue_size
            }
    except Exception as e:
        logger.error(f"获取队列状态失败: {e}", exc_info=True)
        return {
            'current_processing': None,
            'waiting_count': 0,
            'waiting_items': [],
            'queue_size': 0
        }


async def process_media_group(messages: list, queue_reply_msg=None):
    """
    处理媒体组：一次性转发所有媒体文件到频道，保持消息完整性
    
    Args:
        messages: 媒体组消息列表
        queue_reply_msg: 排队通知消息（如果存在，将在处理完成后更新或删除）
    """
    if not messages:
        return
    
    first_msg = messages[0]
    
    # 如果有排队通知，先删除它（因为我们要发送实际的处理结果）
    if queue_reply_msg:
        try:
            await queue_reply_msg.delete()
        except Exception as e:
            logger.debug(f"删除排队通知失败: {e}")
    # 生成唯一的媒体组ID（使用时间戳和第一条消息ID）
    media_group_id = f"mg_{first_msg.chat.id}_{first_msg.media_group_id}_{first_msg.id}"
    
    # 权限检查
    if Var.ALLOWED_USERS and not ((str(first_msg.from_user.id) in Var.ALLOWED_USERS) or (first_msg.from_user.username in Var.ALLOWED_USERS)):
        return
    
    # BIN_CHANNEL检查
    if not Var.BIN_CHANNEL:
        logger.warning(f"BIN_CHANNEL未配置，无法为 {first_msg.from_user.first_name} 生成直链")
        return
    
    try:
        # 一次性转发整个媒体组到频道（保持消息完整性）
        # 使用 forward_messages 一次性转发所有消息，保持媒体组完整性
        try:
            # 获取所有消息的 ID
            message_ids = [msg.id for msg in messages]
            chat_id = messages[0].chat.id
            
            # 一次性转发整个媒体组
            forwarded_msgs = await StreamBot.forward_messages(
                chat_id=Var.BIN_CHANNEL,
                from_chat_id=chat_id,
                message_ids=message_ids
            )
            
            # 构建 (原始消息, 转发消息) 的配对列表
            forwarded_messages = []
            if isinstance(forwarded_msgs, list):
                # 如果返回的是列表（多条消息）
                for i, log_msg in enumerate(forwarded_msgs):
                    if i < len(messages):
                        forwarded_messages.append((messages[i], log_msg))
            else:
                # 如果返回的是单个消息对象（理论上不应该发生）
                forwarded_messages.append((messages[0], forwarded_msgs))
                
        except Exception as e:
            logger.error(f"转发媒体组失败: {e}", exc_info=True)
            # 如果一次性转发失败，回退到逐条转发
            forwarded_messages = []
            for msg in messages:
                try:
                    log_msg = await msg.forward(chat_id=Var.BIN_CHANNEL)
                    forwarded_messages.append((msg, log_msg))
                except Exception as e2:
                    logger.error(f"转发单条消息失败: {e2}", exc_info=True)
        
        if not forwarded_messages:
            return
        
        # 为每个媒体文件生成直链
        stream_links = []
        download_links = []
        
        for original_msg, log_msg in forwarded_messages:
            try:
                file_hash = get_hash(log_msg, Var.HASH_LENGTH)
                stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(original_msg))}?hash={file_hash}"
                short_link = f"{Var.URL}{file_hash}{log_msg.id}"
                file_name = get_name(original_msg)
                
                stream_links.append({
                    'name': file_name,
                    'full_link': stream_link,
                    'short_link': short_link
                })
                
                # 检查是否应该下载（图片类不下载）
                if should_download_file(original_msg):
                    download_links.append(stream_link)
                    logger.info(f"直链已生成（将下载）： {stream_link} for {first_msg.from_user.first_name}")
                else:
                    logger.info(f"直链已生成（仅转发）： {stream_link} for {first_msg.from_user.first_name}")
                    
            except Exception as e:
                logger.error(f"生成直链失败: {e}", exc_info=True)
        
        # 构建回复消息
        if len(stream_links) == 1:
            # 单个文件
            link_info = stream_links[0]
            download_status = "（将下载）" if len(download_links) > 0 else "（仅转发）"
            reply_text = (
                f"🔗 <b>直链已准备好{download_status}</b>\n\n"
                f"📁 <b>文件:</b> <code>{link_info['name']}</code>\n\n"
                f"🌐 <b>完整链接:</b>\n<code>{link_info['full_link']}</code>\n\n"
                f"🔗 <b>短链接:</b>\n<code>{link_info['short_link']}</code>"
            )
            main_link = link_info['full_link']
        else:
            # 多个文件（媒体组）
            download_count = len(download_links)
            skip_count = len(stream_links) - download_count
            reply_text = (
                f"🔗 <b>媒体组直链已准备好</b>\n\n"
                f"📊 <b>统计信息:</b>\n"
                f"  • 总文件数: {len(stream_links)}\n"
            )
            if download_count > 0:
                reply_text += f"  • ⬇️ 将下载: {download_count}\n"
            if skip_count > 0:
                reply_text += f"  • 📷 仅转发: {skip_count}\n"
            reply_text += "\n📋 <b>文件列表:</b>\n\n"
            
            for i, link_info in enumerate(stream_links, 1):
                # 检查这个文件是否在下载列表中
                is_download = link_info['full_link'] in download_links
                status_icon = "⬇️" if is_download else "📷"
                status_text = "将下载" if is_download else "仅转发"
                reply_text += (
                    f"{status_icon} <b>{i}. {link_info['name']}</b>\n"
                    f"   <code>{link_info['full_link']}</code>\n"
                    f"   <i>{status_text}</i>\n\n"
                )
            main_link = stream_links[0]['full_link'] if stream_links else None
        
        # 检查是否是管理员
        is_admin = False
        if Var.ADMIN_ID:
            if isinstance(Var.ADMIN_ID, list):
                is_admin = str(first_msg.from_user.id) in [str(admin_id) for admin_id in Var.ADMIN_ID]
            else:
                is_admin = str(first_msg.from_user.id) == str(Var.ADMIN_ID)
        
        # 自动添加到aria2下载队列（如果启用且是管理员）
        task_gids = []  # 记录添加的下载任务GID
        if Var.AUTO_DOWNLOAD and aria2_client and is_admin and download_links:
            try:
                # 批量添加下载任务，智能等待避免并发过高
                success_count = 0
                failed_count = 0
                
                # 从aria2配置获取最大并发数
                try:
                    global_options = await aria2_client.get_global_option()
                    max_concurrent = int(global_options.get('max-concurrent-downloads', 5))
                except Exception as e:
                    logger.debug(f"无法获取aria2最大并发数配置，使用默认值5: {e}")
                    max_concurrent = 5  # aria2默认最大并发数
                
                max_wait_time = 60  # 最大等待时间（秒），增加到60秒
                
                async def wait_for_slot():
                    """等待有空闲下载槽位"""
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
                            
                            # 如果有空闲位置（至少留一个位置），返回
                            if current_count < max_concurrent - 1:
                                if elapsed_time > 1:  # 如果等待了超过1秒，记录日志
                                    logger.debug(f"等待空闲槽位成功，当前任务数: {current_count}，等待时间: {elapsed_time:.1f}秒")
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
                            
                            # 等待后重试（使用动态间隔）
                            await asyncio.sleep(check_interval)
                        except Exception as e:
                            logger.error(f"检查aria2任务状态失败: {e}")
                            # 如果检查失败，等待一下再继续
                            await asyncio.sleep(1.0)
                            # 如果检查失败，假设有空闲位置，继续尝试
                            return True
                
                async def wait_for_task_start(gid, timeout=5):
                    """等待任务真正开始（状态变为active或waiting）"""
                    wait_start = asyncio.get_event_loop().time()
                    while True:
                        try:
                            status = await aria2_client.tell_status(gid)
                            task_status = status.get('status', '')
                            
                            if task_status in ['active', 'waiting']:
                                return True
                            
                            if task_status == 'complete':
                                return True  # 任务已完成，也算成功
                            
                            if task_status == 'error' or task_status == 'removed':
                                return False  # 任务失败或被移除
                            
                            # 检查超时
                            if asyncio.get_event_loop().time() - wait_start > timeout:
                                logger.warning(f"等待任务开始超时，GID: {gid}, 状态: {task_status}")
                                return False
                            
                            await asyncio.sleep(0.3)
                        except Exception as e:
                            logger.error(f"检查任务状态失败: {e}")
                            # 如果无法检查状态，假设成功
                            return True
                
                for i, link in enumerate(download_links):
                    retry_count = 0
                    max_retries = 3
                    added_successfully = False
                    
                    while retry_count <= max_retries and not added_successfully:
                        try:
                            # 等待有空闲槽位（除了第一个任务和重试时）
                            if i > 0 or retry_count > 0:
                                await wait_for_slot()
                            
                            # 添加任务
                            result = await aria2_client.add_uri(uris=[link])
                            
                            # 检查返回结果
                            if result and 'result' in result:
                                gid = result.get('result')
                                
                                # 等待任务真正开始
                                if await wait_for_task_start(gid):
                                    success_count += 1
                                    added_successfully = True
                                    task_gids.append(gid)  # 记录任务GID
                                    logger.debug(f"成功添加任务 {i+1}/{len(download_links)}: {link[:50]}...")
                                else:
                                    # 任务被中止或失败，重试
                                    if retry_count < max_retries:
                                        retry_count += 1
                                        logger.warning(f"任务被中止，重试 {retry_count}/{max_retries}: {link[:50]}...")
                                        await asyncio.sleep(2)  # 重试前等待2秒
                                    else:
                                        failed_count += 1
                                        logger.error(f"任务添加失败，已达到最大重试次数: {link[:50]}...")
                                        break  # 达到最大重试次数，跳出重试循环
                            else:
                                # 添加失败
                                error_msg = result.get('error', {}).get('message', '未知错误') if result else '无返回结果'
                                if retry_count < max_retries:
                                    retry_count += 1
                                    logger.warning(f"添加任务失败，重试 {retry_count}/{max_retries}: {error_msg}")
                                    await asyncio.sleep(1)  # 重试前等待1秒
                                else:
                                    failed_count += 1
                                    logger.error(f"添加任务失败 (第{i+1}个): {error_msg}")
                                    break  # 达到最大重试次数，跳出重试循环
                            
                            # 添加延迟，避免请求过快
                            if added_successfully and i < len(download_links) - 1:
                                await asyncio.sleep(1.0)  # 成功添加后延迟1秒，确保任务稳定
                                
                        except Exception as e:
                            if retry_count < max_retries:
                                retry_count += 1
                                logger.warning(f"添加任务异常，重试 {retry_count}/{max_retries}: {e}")
                                await asyncio.sleep(1)  # 重试前等待1秒
                            else:
                                failed_count += 1
                                logger.error(f"添加直链到aria2失败 (第{i+1}个): {e}", exc_info=True)
                                break  # 达到最大重试次数，跳出重试循环
                
                # 根据结果更新回复消息
                if success_count > 0:
                    reply_text += "\n\n📥 <b>下载队列状态:</b>\n"
                    if failed_count > 0:
                        reply_text += f"  ✅ 成功添加: {success_count} 个任务\n"
                        reply_text += f"  ⚠️ 添加失败: {failed_count} 个任务"
                    else:
                        reply_text += f"  ✅ 已自动添加 {success_count} 个任务到下载队列"
                    logger.info(f"已将 {success_count}/{len(download_links)} 个直链添加到aria2下载队列")
                else:
                    reply_text += "\n\n⚠️ <b>所有任务添加失败，请手动添加</b>"
                    logger.error(f"所有 {len(download_links)} 个直链添加失败")
            except Exception as e:
                logger.error(f"批量添加直链到aria2失败: {e}", exc_info=True)
                reply_text += "\n\n⚠️ <b>添加到下载队列失败，请手动添加</b>"
        
        # 回复用户（只回复第一条消息）- 如果启用了发送直链信息
        reply_msg = None
        if Var.SEND_STREAM_LINK:
            try:
                buttons = []
                if main_link:
                    buttons.append([InlineKeyboardButton("🔗 打开直链", url=main_link)])
                
                reply_msg = await first_msg.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
                )
            except errors.ButtonUrlInvalid:
                reply_msg = await first_msg.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                )
        else:
            # 如果不发送直链信息，只记录日志
            logger.info(f"已处理媒体组（不发送直链信息）：共 {len(stream_links)} 个文件，{len(download_links)} 个已添加到下载队列")
        
        # 返回任务GID列表，供队列处理器等待完成
        return task_gids
    except Exception as e:
        logger.error(f"处理媒体组失败: {e}", exc_info=True)
        try:
            error_reply = (
                f'❌ <b>处理失败</b>\n\n'
                f'⚠️ 处理媒体组时出错，请稍后重试'
            )
            await first_msg.reply(error_reply, quote=True, parse_mode=ParseMode.HTML)
        except:
            pass
        return []  # 返回空列表


async def process_single_media(m: Message, queue_reply_msg=None):
    """
    处理单个媒体文件
    
    Args:
        m: 消息对象
        queue_reply_msg: 排队通知消息（如果存在，将在处理完成后更新或删除）
    """
    if not Var.ENABLE_STREAM:
        return
    
    # 如果有排队通知，先删除它（因为我们要发送实际的处理结果）
    if queue_reply_msg:
        try:
            await queue_reply_msg.delete()
        except Exception as e:
            logger.debug(f"删除排队通知失败: {e}")
    
    # 权限检查
    if Var.ALLOWED_USERS and not ((str(m.from_user.id) in Var.ALLOWED_USERS) or (m.from_user.username in Var.ALLOWED_USERS)):
        permission_msg = (
            f'🚫 <b>权限不足</b>\n\n'
            f'⚠️ 你没有权限使用这个机器人'
        )
        return await m.reply(permission_msg, quote=True, parse_mode=ParseMode.HTML)
    
    # BIN_CHANNEL检查
    if not Var.BIN_CHANNEL:
        logger.warning(f"BIN_CHANNEL未配置，无法为 {m.from_user.first_name} 生成直链")
        return await m.reply("直链功能未配置，请在配置文件中设置 BIN_CHANNEL", quote=True)
    
    try:
        # 转发到日志频道并生成直链
        log_msg = await m.forward(chat_id=Var.BIN_CHANNEL)
        file_hash = get_hash(log_msg, Var.HASH_LENGTH)
        stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(m))}?hash={file_hash}"
        short_link = f"{Var.URL}{file_hash}{log_msg.id}"
        
        # 检查是否应该下载
        should_download = should_download_file(m)
        download_status = "（将下载）" if should_download else "（仅转发）"
        logger.info(f"直链已生成{download_status}： {stream_link} for {m.from_user.first_name}")
        
        # 后续处理：自动将直链添加到aria2下载队列（如果启用且是管理员，且文件类型需要下载）
        download_added = False
        task_gid = None  # 记录任务GID
        if Var.AUTO_DOWNLOAD and aria2_client and should_download:
            # 检查是否是管理员
            is_admin = False
            if Var.ADMIN_ID:
                if isinstance(Var.ADMIN_ID, list):
                    is_admin = str(m.from_user.id) in [str(admin_id) for admin_id in Var.ADMIN_ID]
                else:
                    is_admin = str(m.from_user.id) == str(Var.ADMIN_ID)
            
            if is_admin:
                try:
                    # 将直链URL添加到aria2下载队列
                    result = await aria2_client.add_uri(uris=[stream_link])
                    if result and 'result' in result:
                        task_gid = result.get('result')
                    download_added = True
                    logger.info(f"已将直链添加到aria2下载队列: {stream_link}, GID: {task_gid}")
                except Exception as e:
                    logger.error(f"添加直链到aria2失败: {e}", exc_info=True)
        
        # 返回直链给用户（如果启用了发送直链信息）
        if Var.SEND_STREAM_LINK:
            file_name = ""
            if m.document:
                file_name = m.document.file_name or "未知文件"
            elif m.video:
                file_name = m.video.file_name or "视频文件"
            elif m.audio:
                file_name = m.audio.file_name or "音频文件"
            elif m.photo:
                file_name = "图片文件"
            elif m.animation:
                file_name = m.animation.file_name or "动画文件"
            else:
                file_name = "媒体文件"
            
            reply_text = (
                f"🔗 <b>直链已准备好{download_status}</b>\n\n"
                f"📁 <b>文件:</b> <code>{file_name}</code>\n\n"
                f"🌐 <b>完整链接:</b>\n<code>{stream_link}</code>\n\n"
                f"🔗 <b>短链接:</b>\n<code>{short_link}</code>"
            )
            
            if download_added:
                reply_text += "\n\n✅ <b>已自动添加到下载队列</b>"
            elif Var.AUTO_DOWNLOAD and aria2_client and should_download:
                reply_text += "\n\n⚠️ <b>添加到下载队列失败，请手动添加</b>"
            
            try:
                await m.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔗 打开直链", url=stream_link)]]
                    ),
                )
            except errors.ButtonUrlInvalid:
                await m.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                )
        else:
            # 如果不发送直链信息，只记录日志
            if download_added:
                logger.info(f"已处理文件（不发送直链信息）：{get_name(m)}，已添加到下载队列")
            else:
                logger.info(f"已处理文件（不发送直链信息）：{get_name(m)}，仅转发")
        
        # 返回任务GID列表，供队列处理器等待完成
        return [task_gid] if task_gid else []
    except Exception as e:
        logger.error(f"生成直链失败: {e}", exc_info=True)
        await m.reply("生成直链时出错，请稍后重试", quote=True)
        return []  # 返回空列表


@StreamBot.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
        | filters.animation
        | filters.voice
        | filters.video_note
        | filters.photo
        | filters.sticker
    ),
    group=4,
)
async def media_receive_handler(_, m: Message):
    """
    处理Telegram媒体文件，生成直链（作为下载的前置功能）
    支持单个媒体文件和媒体组（保持消息完整性）
    """
    if not Var.ENABLE_STREAM:
        return
    
    # 检查是否是媒体组
    if m.media_group_id:
        # 媒体组：收集所有消息，延迟处理
        group_id = f"{m.chat.id}_{m.media_group_id}"
        media_group_cache[group_id].append(m)
        
        # 取消之前的任务（如果有）
        if group_id in media_group_tasks:
            media_group_tasks[group_id].cancel()
        
        # 创建新任务：等待500ms后处理（给其他消息时间到达）
        async def delayed_process():
            await asyncio.sleep(0.5)  # 等待500ms
            if group_id in media_group_cache:
                messages = media_group_cache.pop(group_id)
                # 按照消息 ID 排序，确保顺序正确
                messages.sort(key=lambda x: x.id)
                if group_id in media_group_tasks:
                    del media_group_tasks[group_id]
                # 将媒体组处理任务加入队列，而不是直接执行
                # 注意：排队通知会在enqueue_message_task中自动发送
                enqueue_message_task(process_media_group, messages)
        
        task = asyncio.create_task(delayed_process())
        media_group_tasks[group_id] = task
    else:
        # 单个媒体文件：加入队列处理，而不是立即处理
        enqueue_message_task(process_single_media, m)

