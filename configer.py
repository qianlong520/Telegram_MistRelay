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
