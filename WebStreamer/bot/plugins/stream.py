# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
Stream插件主文件
整合各子模块，提供统一的接口
"""

# 从子模块导入所有公共接口
from .stream_modules import (
    # 工具函数
    aria2_client,
    set_aria2_client,
    should_download_file,
    send_queue_notification,
    
    # 限流控制
    flood_wait_status,
    flood_wait_lock,
    extract_flood_wait_seconds,
    handle_flood_wait_start,
    handle_flood_wait_end,
    send_flood_wait_notification,
    delete_flood_wait_notification,
    
    # 任务跟踪
    task_completion_tracker,
    task_completion_lock,
    wait_for_tasks_completion,
    
    # 队列管理
    message_processing_queue,
    queue_processor_task,
    queue_processing_lock,
    queue_item_tracker,
    current_processing_queue_id,
    queue_tracker_lock,
    queue_id_counter,
    _ensure_queue_initialized,
    message_queue_processor,
    enqueue_message_task,
    get_queue_status,
    
    # 媒体处理
    media_group_cache,
    media_group_tasks,
    process_media_group,
    process_single_media,
    media_receive_handler,
)

# 导出所有接口（保持向后兼容）
__all__ = [
    # 工具函数
    'aria2_client',
    'set_aria2_client',
    'should_download_file',
    'send_queue_notification',
    
    # 限流控制
    'flood_wait_status',
    'flood_wait_lock',
    'extract_flood_wait_seconds',
    'handle_flood_wait_start',
    'handle_flood_wait_end',
    'send_flood_wait_notification',
    'delete_flood_wait_notification',
    
    # 任务跟踪
    'task_completion_tracker',
    'task_completion_lock',
    'wait_for_tasks_completion',
    
    # 队列管理
    'message_processing_queue',
    'queue_processor_task',
    'queue_processing_lock',
    'queue_item_tracker',
    'current_processing_queue_id',
    'queue_tracker_lock',
    'queue_id_counter',
    '_ensure_queue_initialized',
    'message_queue_processor',
    'enqueue_message_task',
    'get_queue_status',
    
    # 媒体处理
    'media_group_cache',
    'media_group_tasks',
    'process_media_group',
    'process_single_media',
    'media_receive_handler',
]
