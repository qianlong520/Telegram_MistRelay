# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
Stream模块包初始化
导出所有子模块的公共接口
"""

# 从各子模块导入公共接口

# 工具函数模块
from .utils import (
    aria2_client,
    set_aria2_client,
    should_download_file,
    send_queue_notification,
    register_gid_queue_msg,
    update_queue_msg_on_cleanup
)

# 限流控制模块
from .flood_control import (
    flood_wait_status,
    flood_wait_lock,
    extract_flood_wait_seconds,
    handle_flood_wait_start,
    handle_flood_wait_end,
    send_flood_wait_notification,
    delete_flood_wait_notification
)

# 任务跟踪模块
from .task_tracker import (
    task_completion_tracker,
    task_completion_lock,
    wait_for_tasks_completion
)

# 队列管理模块
from .queue_manager import (
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
    get_queue_status
)

# 媒体处理模块
from .media_processor import (
    media_group_cache,
    media_group_tasks,
    process_media_group,
    process_single_media,
    media_receive_handler
)

__all__ = [
    # utils
    'aria2_client',
    'set_aria2_client',
    'should_download_file',
    'send_queue_notification',
    'register_gid_queue_msg',
    'update_queue_msg_on_cleanup',
    
    # flood_control
    'flood_wait_status',
    'flood_wait_lock',
    'extract_flood_wait_seconds',
    'handle_flood_wait_start',
    'handle_flood_wait_end',
    'send_flood_wait_notification',
    'delete_flood_wait_notification',
    
    # task_tracker
    'task_completion_tracker',
    'task_completion_lock',
    'wait_for_tasks_completion',
    
    # queue_manager
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
    
    # media_processor
    'media_group_cache',
    'media_group_tasks',
    'process_media_group',
    'process_single_media',
    'media_receive_handler',
]
