"""
Aria2异步客户端 - 向后兼容入口

此文件保留用于向后兼容,所有功能已迁移到 aria2_client 包中。
建议使用: from aria2_client import AsyncAria2Client

原始功能已拆分为以下模块:
- aria2_client.constants - 常量和配置
- aria2_client.utils - 工具函数
- aria2_client.download_handler - 下载事件处理
- aria2_client.upload_handler - 上传处理
- aria2_client.client - 核心客户端类
"""
import asyncio
from pprint import pprint

# 从新模块导入所有内容,保持向后兼容
from aria2_client import AsyncAria2Client
from aria2_client.constants import (
    DOWNLOAD_PROGRESS_UPDATE_INTERVAL,
    FILE_MODIFIED_TIME_WINDOW,
    PROGRESS_UPDATE_FREQUENCY,
    RCLONE_MAX_RETRIES,
    RCLONE_RETRY_BASE_DELAY,
    RCLONE_RETRY_EXTRA_DELAY,
    PROCESS_TERMINATE_TIMEOUT,
    upload_work_loads,
    pyrogram_clients,
    channel_accessible_clients,
    logger
)
from aria2_client.utils import (
    format_progress_bar,
    format_upload_message,
    parse_rclone_progress
)
from configer import RPC_URL, RPC_SECRET

# 导出所有公共接口
__all__ = [
    'AsyncAria2Client',
    'format_progress_bar',
    'format_upload_message',
    'parse_rclone_progress',
]


async def main():
    """测试主函数"""
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
