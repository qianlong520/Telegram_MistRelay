"""
Aria2客户端常量和配置定义
"""
import logging
from configer import ENABLE_STREAM

# 配置日志
logger = logging.getLogger(__name__)

# 常量定义
DOWNLOAD_PROGRESS_UPDATE_INTERVAL = 3  # 下载进度更新间隔(秒)
FILE_MODIFIED_TIME_WINDOW = 300  # 文件修改时间窗口(秒) - 5分钟
PROGRESS_UPDATE_FREQUENCY = 5  # 进度消息更新频率(每N次更新一次)
RCLONE_MAX_RETRIES = 3  # rclone上传最大重试次数
RCLONE_RETRY_BASE_DELAY = 10  # rclone重试基础延迟(秒)
RCLONE_RETRY_EXTRA_DELAY = 5  # rclone重试额外延迟(秒)
PROCESS_TERMINATE_TIMEOUT = 5  # 进程终止超时时间(秒)

# 轮询配置
POLL_INTERVAL = 30  # 活动任务轮询间隔(秒)
IDLE_CHECK_INTERVAL = 60  # 空闲时检查间隔(秒)

# 导入多客户端负载均衡（如果启用直链功能）
upload_work_loads = {}  # 上传任务的负载跟踪
pyrogram_clients = {}
channel_accessible_clients = set()

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
