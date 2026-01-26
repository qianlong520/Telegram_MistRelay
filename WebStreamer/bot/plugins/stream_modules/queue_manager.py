# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
队列管理模块
管理消息处理队列，实现严格串行执行
"""

import logging
import asyncio
import time
from pyrogram.types import Message
from WebStreamer.utils import get_name

logger = logging.getLogger(__name__)

# 消息处理队列（严格串行执行）
# 每条转发给bot的信息都当成一条队列数据
# 如果当前队列没有执行完，等待队列就不进入（严格按顺序执行，一个完成后再执行下一个）
message_processing_queue = None
queue_processor_task = None
queue_processing_lock = None  # 用于确保队列处理器只有一个实例在运行

# 队列项信息跟踪:跟踪每个队列项的详细信息
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
    global message_processing_queue, queue_processing_lock, queue_tracker_lock
    
    if message_processing_queue is None:
        message_processing_queue = asyncio.Queue()
    
    if queue_processing_lock is None:
        queue_processing_lock = asyncio.Lock()
    
    if queue_tracker_lock is None:
        try:
            queue_tracker_lock = asyncio.Lock()
        except RuntimeError:
            # 如果没有事件循环，稍后初始化
            pass


def is_flood_wait_error(e: Exception) -> bool:
    """检查是否是限流错误"""
    # 延迟导入避免循环依赖
    from pyrogram import errors
    return isinstance(e, errors.FloodWait)


async def message_queue_processor():
    """
    消息队列处理器：严格串行执行，一个任务完成后再执行下一个
    每条转发给bot的信息都当成一条队列数据，如果当前队列没有执行完，等待队列就不进入
    """
    # 延迟导入避免循环依赖
    from .flood_control import flood_wait_status, handle_flood_wait_start, handle_flood_wait_end
    from .task_tracker import wait_for_tasks_completion
    from .utils import aria2_client
    
    # 确保队列已初始化
    _ensure_queue_initialized()
    
    logger.info("消息队列处理器已启动(严格串行模式:一个任务完成后再执行下一个)")
    while True:
        try:
            # 检查是否处于限流状态
            if flood_wait_status['is_flood_waiting']:
                current_time = time.time()
                if current_time < flood_wait_status['flood_wait_until']:
                    # 仍在限流期间,等待
                    wait_seconds = flood_wait_status['flood_wait_until'] - current_time
                    logger.info(f"处于限流状态,等待 {wait_seconds:.0f} 秒后恢复")
                    await asyncio.sleep(min(wait_seconds, 10))  # 每10秒检查一次
                    continue
                else:
                    # 限流结束,恢复处理
                    await handle_flood_wait_end()
            
            # 从队列中获取消息处理任务(这里会阻塞等待,直到有任务)
            # 队列项格式: (task_func, args, kwargs, queue_notification, queue_id)
            queue_item = await message_processing_queue.get()
            
            # 解包队列项(兼容旧格式)
            queue_id = None
            if len(queue_item) >= 5:
                task_func, task_args, task_kwargs, queue_notification, queue_id = queue_item
            elif len(queue_item) == 4:
                task_func, task_args, task_kwargs, queue_notification = queue_item
            else:
                # 兼容旧格式(没有排队通知和队列ID)
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
                logger.debug(f"开始处理消息任务,队列中还有 {queue_size} 个任务等待处理")
            
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
                        # 检查是否是限流错误
                        if is_flood_wait_error(e2):
                            logger.warning(f"检测到限流错误,触发限流处理")
                            await handle_flood_wait_start(e2)
                            # 将当前任务重新放回队列头部
                            await message_processing_queue.put((task_func, task_args, task_kwargs, queue_notification, queue_id))
                        else:
                            logger.error(f"处理消息队列任务失败: {e2}", exc_info=True)
                else:
                    logger.error(f"处理消息队列任务失败: {e}", exc_info=True)
            except Exception as e:
                # 检查是否是限流错误
                if is_flood_wait_error(e):
                    logger.warning(f"检测到限流错误,触发限流处理")
                    await handle_flood_wait_start(e)
                    # 将当前任务重新放回队列头部,等限流结束后继续处理
                    # 注意:使用 put_nowait 而不是 put,避免阻塞
                    try:
                        # 创建新的队列,将当前任务放在最前面
                        temp_items = [(task_func, task_args, task_kwargs, queue_notification, queue_id)]
                        while not message_processing_queue.empty():
                            try:
                                item = message_processing_queue.get_nowait()
                                temp_items.append(item)
                            except:
                                break
                        # 重新放回队列
                        for item in temp_items:
                            message_processing_queue.put_nowait(item)
                        logger.info(f"已将当前任务和 {len(temp_items)-1} 个等待任务重新放回队列")
                    except Exception as requeue_error:
                        logger.error(f"重新放回队列失败: {requeue_error}", exc_info=True)
                else:
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
    
    # 延迟导入避免循环依赖
    from .utils import send_queue_notification
    
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


async def get_queue_status():
    """
    获取消息队列状态
    
    Returns:
        dict: 包含队列状态信息的字典
    """
    global current_processing_queue_id
    
    # 延迟导入避免循环依赖
    from .flood_control import flood_wait_status
    
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
            
            # 添加限流状态信息
            flood_wait_info = None
            if flood_wait_status['is_flood_waiting']:
                remaining_seconds = max(0, flood_wait_status['flood_wait_until'] - time.time())
                flood_wait_info = {
                    'is_waiting': True,
                    'wait_seconds': flood_wait_status['flood_wait_seconds'],
                    'remaining_seconds': int(remaining_seconds),
                    'resume_time': flood_wait_status['flood_wait_until']
                }
            
            return {
                'current_processing': current_item,
                'waiting_count': len(waiting_items),
                'waiting_items': waiting_items,
                'queue_size': queue_size,
                'flood_wait': flood_wait_info  # 新增限流状态
            }
    except Exception as e:
        logger.error(f"获取队列状态失败: {e}", exc_info=True)
        return {
            'current_processing': None,
            'waiting_count': 0,
            'waiting_items': [],
            'queue_size': 0
        }
