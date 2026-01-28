import yaml
import os

# 配置缓存
_config_cache = None
_config_cache_time = None

def _load_config():
    """从数据库或YAML文件加载配置"""
    global _config_cache, _config_cache_time
    
    # 优先从数据库读取配置，如果数据库中没有则从config.yml读取
    try:
        from db import get_config, get_all_configs, init_config_from_yaml
        
        # 尝试从数据库读取配置
        db_config = get_all_configs()
        
        if db_config:
            # 从数据库读取配置
            result = db_config
            # 补充缺失的配置项（向后兼容）
            if not result.get('API_ID'):
                # 如果数据库中没有配置，尝试从config.yml导入
                config_file = './db/config.yml'
                if os.path.exists(config_file):
                    with open(config_file, 'r', encoding='utf-8') as f:
                        yaml_config = yaml.load(f.read(), Loader=yaml.FullLoader)
                    # 导入到数据库
                    init_config_from_yaml()
                    # 重新从数据库读取
                    result = get_all_configs()
        else:
            # 数据库中没有配置，从config.yml读取并导入
            config_file = './db/config.yml'
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    result = yaml.load(f.read(), Loader=yaml.FullLoader)
                # 导入到数据库
                init_config_from_yaml()
            else:
                result = {}
        
        _config_cache = result
        _config_cache_time = os.path.getmtime('./db/downloads.db') if os.path.exists('./db/downloads.db') else None
        return result
    except Exception as e:
        # 如果数据库操作失败，回退到从config.yml读取
        print(f"[CONFIG] 警告: 无法从数据库读取配置，使用config.yml: {e}")
        config_file = './db/config.yml'
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                result = yaml.load(f.read(), Loader=yaml.FullLoader)
            _config_cache = result
            _config_cache_time = os.path.getmtime(config_file)
            return result
        else:
            _config_cache = {}
            return {}


def reload_config():
    """重新加载配置（热重载）"""
    global _config_cache, _config_cache_time
    _config_cache = None
    _config_cache_time = None
    return _load_config()


def get_config_value(key, default=None):
    """动态获取配置值（每次从数据库读取）"""
    try:
        from db import get_config as db_get_config
        return db_get_config(key, default)
    except:
        # 如果数据库读取失败，使用缓存
        if _config_cache is None:
            _load_config()
        return _config_cache.get(key, default) if _config_cache else default


# 初始加载配置
result = _load_config()

# 从配置中读取值，支持数据库和YAML两种方式
# 注意：这些变量在模块导入时初始化，如果需要热重载，请使用 get_config_value() 函数
API_ID = result.get('API_ID') or 0
API_HASH = result.get('API_HASH') or ''
BOT_TOKEN = result.get('BOT_TOKEN') or ''
PROXY_IP = result.get('PROXY_IP') or None
PROXY_PORT = result.get('PROXY_PORT') or None
ADMIN_ID = result.get('ADMIN_ID') or 0
FORWARD_ID = result.get('FORWARD_ID') or None
UP_TELEGRAM = result.get('UP_TELEGRAM', False)
# rclone相关配置
UP_ONEDRIVE = result.get('UP_ONEDRIVE', False)
RCLONE_REMOTE = result.get('RCLONE_REMOTE', 'onedrive')
RCLONE_PATH = result.get('RCLONE_PATH', '/Downloads')
# 谷歌网盘配置
UP_GOOGLE_DRIVE = result.get('UP_GOOGLE_DRIVE', False)
GOOGLE_DRIVE_REMOTE = result.get('GOOGLE_DRIVE_REMOTE', 'gdrive')
GOOGLE_DRIVE_PATH = result.get('GOOGLE_DRIVE_PATH', '/Downloads')
# 自动删除本地文件设置
AUTO_DELETE_AFTER_UPLOAD = result.get('AUTO_DELETE_AFTER_UPLOAD', True)
RPC_SECRET = result.get('RPC_SECRET') or ''
RPC_URL = result.get('RPC_URL') or 'localhost:6800/jsonrpc'

# 直链功能配置（默认启用，作为TG媒体文件下载的前置功能）
ENABLE_STREAM = result.get('ENABLE_STREAM', True)  # 默认启用
BIN_CHANNEL = result.get('BIN_CHANNEL')
STREAM_PORT = result.get('STREAM_PORT', 8080)
STREAM_BIND_ADDRESS = result.get('STREAM_BIND_ADDRESS', '0.0.0.0')
STREAM_HASH_LENGTH = result.get('STREAM_HASH_LENGTH', 6)
STREAM_HAS_SSL = result.get('STREAM_HAS_SSL', False)
STREAM_NO_PORT = result.get('STREAM_NO_PORT', False)
STREAM_FQDN = result.get('STREAM_FQDN', '')
STREAM_KEEP_ALIVE = result.get('STREAM_KEEP_ALIVE', False)
STREAM_PING_INTERVAL = result.get('STREAM_PING_INTERVAL', 1200)
STREAM_USE_SESSION_FILE = result.get('STREAM_USE_SESSION_FILE', False)
STREAM_ALLOWED_USERS = result.get('STREAM_ALLOWED_USERS', '')
# 是否自动将直链添加到aria2下载（默认启用）
STREAM_AUTO_DOWNLOAD = result.get('STREAM_AUTO_DOWNLOAD', True)
# 是否发送直链信息给用户（默认不启用，设置为 True 后才会发送直链信息给用户，关闭后仍会生成直链并添加到下载队列）
SEND_STREAM_LINK = result.get('SEND_STREAM_LINK', False)
# 是否跳过小于指定大小的媒体文件（默认False）
SKIP_SMALL_FILES = result.get('SKIP_SMALL_FILES', False)
# 最小文件大小（MB），小于此大小的文件将被跳过（默认100MB）
MIN_FILE_SIZE_MB = result.get('MIN_FILE_SIZE_MB', 100)
# 消息队列最大并发处理数量（默认5，限制同时处理的消息数量）
MAX_CONCURRENT_MESSAGES = result.get('MAX_CONCURRENT_MESSAGES', 5)
# aria2最大并发下载数（默认5，限制同时下载的任务数量）
ARIA2_MAX_CONCURRENT_DOWNLOADS = result.get('ARIA2_MAX_CONCURRENT_DOWNLOADS', 5)
# 多机器人负载配置
# 如果配置了额外的BOT_TOKEN，将启用多机器人负载均衡
# MULTI_BOT_TOKENS 可以是字符串（逗号分隔）或列表
# 注意：这些是额外的token，默认的BOT_TOKEN会作为第一个客户端
MULTI_BOT_TOKENS_raw = result.get('MULTI_BOT_TOKENS', [])
# 调试：打印原始配置值（使用print因为配置加载在日志初始化之前）
print(f"[CONFIG] 读取 MULTI_BOT_TOKENS 配置: 值={MULTI_BOT_TOKENS_raw}, 类型={type(MULTI_BOT_TOKENS_raw)}")

# 处理配置：支持字符串和列表两种格式
if MULTI_BOT_TOKENS_raw:
    if isinstance(MULTI_BOT_TOKENS_raw, str):
        # 如果是字符串，按逗号分割并去除空白
        MULTI_BOT_TOKENS = [token.strip() for token in MULTI_BOT_TOKENS_raw.split(',') if token.strip()]
        print(f"[CONFIG] 从字符串解析 MULTI_BOT_TOKENS: {len(MULTI_BOT_TOKENS)} 个token")
    elif isinstance(MULTI_BOT_TOKENS_raw, list):
        # 如果是列表，去除空白
        MULTI_BOT_TOKENS = [token.strip() for token in MULTI_BOT_TOKENS_raw if token.strip()]
        print(f"[CONFIG] 从列表解析 MULTI_BOT_TOKENS: {len(MULTI_BOT_TOKENS)} 个token")
    else:
        # 其他类型，尝试转换为列表
        MULTI_BOT_TOKENS = []
        print(f"[CONFIG] ⚠️ 未知的 MULTI_BOT_TOKENS 类型: {type(MULTI_BOT_TOKENS_raw)}")
    
    # 如果配置了至少一个额外的token，启用多客户端模式（加上默认的BOT_TOKEN，至少有两个客户端）
    STREAM_MULTI_CLIENT = len(MULTI_BOT_TOKENS) > 0
    if STREAM_MULTI_CLIENT:
        print(f"[CONFIG] ✅ 多机器人配置: 找到 {len(MULTI_BOT_TOKENS)} 个额外的BOT_TOKEN，启用多客户端模式")
    else:
        print(f"[CONFIG] ⚠️ 多机器人配置: MULTI_BOT_TOKENS 配置存在但为空，使用单客户端模式")
else:
    MULTI_BOT_TOKENS = []
    STREAM_MULTI_CLIENT = False
    print(f"[CONFIG] ℹ️ 多机器人配置: 未配置额外的BOT_TOKEN，使用单客户端模式")
