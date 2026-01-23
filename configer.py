import yaml

with open('./db/config.yml', 'r', encoding='utf-8') as f:
    result = yaml.load(f.read(), Loader=yaml.FullLoader)

API_ID = result['API_ID']
API_HASH = result['API_HASH']
BOT_TOKEN = result['BOT_TOKEN']
PROXY_IP = result.get('PROXY_IP')
PROXY_PORT = result.get('PROXY_PORT')
ADMIN_ID = result['ADMIN_ID']
FORWARD_ID = result.get('FORWARD_ID')
UP_TELEGRAM = result.get('UP_TELEGRAM', False)
# rclone相关配置
UP_ONEDRIVE = result.get('UP_ONEDRIVE', False)
RCLONE_REMOTE = result.get('RCLONE_REMOTE', 'onedrive')
RCLONE_PATH = result.get('RCLONE_PATH', '/Downloads')
# 自动删除本地文件设置
AUTO_DELETE_AFTER_UPLOAD = result.get('AUTO_DELETE_AFTER_UPLOAD', True)
RPC_SECRET = result['RPC_SECRET']
RPC_URL = result['RPC_URL']

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
# 多机器人负载配置
# 如果配置了额外的BOT_TOKEN，将启用多机器人负载均衡
# MULTI_BOT_TOKENS 可以是字符串（逗号分隔）或列表
# 注意：这些是额外的token，默认的BOT_TOKEN会作为第一个客户端
MULTI_BOT_TOKENS_raw = result.get('MULTI_BOT_TOKENS', '')
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
        config_logger.warning(f"未知的 MULTI_BOT_TOKENS 类型: {type(MULTI_BOT_TOKENS_raw)}")
    
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
