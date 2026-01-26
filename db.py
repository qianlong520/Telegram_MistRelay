"""
SQLite 数据库模块
=================

本模块主要用于记录两个维度的数据：

- tg_media  表：存放从 Telegram（Pyrogram Message/Media）解析出来的“媒体元数据”
  - file_unique_id       : Telegram 提供的全局唯一 ID，作为主键
  - chat_id / message_id : 消息所在聊天与消息 ID，用于去重与回查原消息
  - from_user_id         : 发送用户 ID（私聊/群聊）
  - sender_chat_id       : 频道 ID（频道帖子）
  - file_id              : 真正下载用的 file_id（bot 专属）
  - file_name            : 文件名
  - mime_type            : MIME 类型（video/mp4 等）
  - file_size            : 文件大小（字节）
  - duration/width/height: 媒体时长与分辨率
  - caption              : 说明文本
  - caption_entities     : 说明文本中的实体（hashtag、粗体等），JSON 字符串
  - message_date         : 消息时间（ISO8601 字符串）
  - media_group_id       : 媒体组 ID，相册/多媒体时使用
  - has_media_spoiler    : 是否剧透遮罩（0/1）
  - supports_streaming   : 是否支持流式播放（0/1）
  - thumbs               : 缩略图相关信息，预留为 JSON 字符串
  - extra                : 预留扩展字段（JSON 字符串）

- downloads 表：存放下载任务（aria2）与本地/网盘路径信息
  - id               : 自增主键
  - file_unique_id   : 外键，关联 tg_media
  - gid              : aria2 任务 ID
  - source_url       : 用于下载的直链 URL（WebStreamer 生成）
  - status           : 下载状态（pending/downloading/completed/failed）
  - total_length     : 文件总大小（字节）
  - completed_length : 已完成大小（字节）
  - download_speed   : 当前下载速度（字节/秒）
  - error_message    : 失败原因
  - retry_count      : 重试次数
  - local_path       : 本地最终文件路径
  - save_dir         : 本地保存目录
  - remote_path      : 网盘路径（如 OneDrive/rclone）
  - upload_status    : 上传状态（pending/uploading/uploaded/failed 等）
  - created_at       : 创建时间（加入下载队列）
  - started_at       : 实际开始下载时间
  - completed_at     : 完成时间
  - updated_at       : 最近更新时间
"""

import os
import sqlite3
import json
import logging
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

# 数据库路径：优先使用环境变量，否则使用 /app/db/downloads.db（确保在挂载的卷中）
_default_db_path = os.path.join("/app/db", "downloads.db")
DB_PATH = os.environ.get("MISTRELAY_DB_PATH", _default_db_path)

# 确保数据库目录存在
_db_dir = os.path.dirname(DB_PATH)
if _db_dir and not os.path.exists(_db_dir):
    os.makedirs(_db_dir, exist_ok=True)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # 启用 Write-Ahead Logging 模式，提升并发性能
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()


def init_db():
    """初始化 SQLite 数据库（如果不存在就建表）"""
    with db_cursor() as cur:
        # Telegram 媒体信息
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tg_media (
                file_unique_id     TEXT PRIMARY KEY, -- Telegram 提供的全局唯一 ID，主键
                chat_id            INTEGER NOT NULL, -- 消息所属聊天 ID（频道/群/私聊）
                message_id         INTEGER NOT NULL, -- 消息 ID
                from_user_id       INTEGER,          -- 发送用户 ID（私聊/群聊）
                sender_chat_id     INTEGER,          -- 发送频道 ID（频道帖子）
                file_id            TEXT NOT NULL,    -- 实际用于下载的 file_id（bot 专属）
                file_name          TEXT,             -- 文件名
                mime_type          TEXT,             -- MIME 类型，如 video/mp4
                file_size          INTEGER,          -- 文件大小（字节）
                duration           INTEGER,          -- 媒体时长（秒）
                width              INTEGER,          -- 媒体宽度（像素）
                height             INTEGER,          -- 媒体高度（像素）
                caption            TEXT,             -- 说明文本
                caption_entities   TEXT,             -- 说明文本中的实体（hashtag 等），JSON 字符串
                message_date       TEXT NOT NULL,    -- 消息时间，ISO8601 字符串
                media_group_id     TEXT,             -- 媒体组 ID（相册/多媒体）
                has_media_spoiler  INTEGER,          -- 是否启用剧透遮罩（0/1）
                supports_streaming INTEGER,          -- 是否支持流式播放（0/1）
                thumbs             TEXT,             -- 缩略图信息，JSON 字符串（预留）
                extra              TEXT              -- 扩展字段，JSON 字符串（预留）
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_media_chat_msg ON tg_media (chat_id, message_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_media_media_group ON tg_media (media_group_id)"
        )

        # 下载任务信息
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                id               INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
                file_unique_id   TEXT NOT NULL,                     -- 关联 tg_media.file_unique_id
                gid              TEXT,                              -- aria2 任务 ID
                source_url       TEXT,                              -- 用于下载的直链 URL
                status           TEXT NOT NULL DEFAULT 'pending',   -- 下载状态：pending/downloading/completed/failed
                total_length     INTEGER,                           -- 文件总大小（字节）
                completed_length INTEGER,                           -- 已完成大小（字节）
                download_speed   INTEGER,                           -- 当前下载速度（字节/秒）
                error_message    TEXT,                              -- 错误信息（失败原因）
                retry_count      INTEGER DEFAULT 0,                 -- 重试次数
                local_path       TEXT,                              -- 本地最终文件路径
                save_dir         TEXT,                              -- 本地保存目录
                remote_path      TEXT,                              -- 网盘路径（如 OneDrive/rclone）
                upload_status    TEXT,                              -- 上传状态：pending/uploading/uploaded/failed
                created_at       TEXT NOT NULL,                     -- 创建时间（加入下载队列）
                started_at       TEXT,                              -- 实际开始下载时间
                completed_at     TEXT,                              -- 下载完成时间
                updated_at       TEXT NOT NULL,                     -- 最近更新时间
                FOREIGN KEY (file_unique_id) REFERENCES tg_media(file_unique_id) ON DELETE CASCADE -- 关联 Telegram 媒体
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_file_unique_id ON downloads (file_unique_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads (status)"
        )

        # 上传任务信息
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
                download_id         INTEGER NOT NULL,                  -- 关联 downloads.id
                upload_target       TEXT NOT NULL,                     -- 上传目标：onedrive/telegram/other
                remote_path         TEXT,                              -- 远程路径
                status              TEXT NOT NULL DEFAULT 'pending',   -- 上传状态：pending/waiting_download/uploading/completed/failed/cancelled/paused
                failure_reason      TEXT,                              -- 失败原因分类：download_failed/code_error/network_error等
                error_message       TEXT,                              -- 详细错误信息
                error_code          TEXT,                              -- 错误代码
                total_size          INTEGER,                           -- 文件总大小（字节）
                uploaded_size       INTEGER DEFAULT 0,                 -- 已上传大小（字节）
                upload_speed        INTEGER,                           -- 上传速度（字节/秒）
                retry_count         INTEGER DEFAULT 0,                 -- 重试次数
                max_retries         INTEGER DEFAULT 3,                 -- 最大重试次数
                created_at          TEXT NOT NULL,                     -- 创建时间
                started_at          TEXT,                              -- 开始上传时间
                completed_at        TEXT,                              -- 完成时间
                updated_at          TEXT NOT NULL,                     -- 最近更新时间
                extra               TEXT,                              -- 扩展字段（JSON）
                FOREIGN KEY (download_id) REFERENCES downloads(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_download_id ON uploads (download_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads (status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_target ON uploads (upload_target)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_failure_reason ON uploads (failure_reason)"
        )

        # 系统配置表
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS config_settings (
                key             TEXT PRIMARY KEY,  -- 配置键名
                value           TEXT,              -- 配置值（JSON字符串，支持复杂类型）
                value_type      TEXT NOT NULL,     -- 值类型：string, int, bool, list, json
                category        TEXT NOT NULL,     -- 配置分类：telegram, rclone, aria2, stream, etc.
                description     TEXT,              -- 配置说明
                updated_at      TEXT NOT NULL      -- 更新时间
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_config_category ON config_settings (category)"
        )
    
    # 检查是否需要从config.yml迁移配置（在with块外执行，因为需要独立的连接）
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM config_settings")
        count = cur.fetchone()['count']
        if count == 0:
            # 配置表为空，尝试从config.yml导入
            try:
                if init_config_from_yaml():
                    logger.info("已从config.yml成功导入配置到数据库")
                else:
                    logger.warning("配置表为空，且无法从config.yml导入配置")
            except Exception as e:
                logger.warning(f"从config.yml导入配置时出错: {e}")


def save_tg_media(message, media) -> str:
    """
    保存/忽略一条 Telegram 媒体元数据，返回 file_unique_id。
    """
    file_unique_id = media.file_unique_id
    file_id = media.file_id

    caption_entities = message.caption_entities or []
    try:
        ce_json = json.dumps(
            [e.__dict__ for e in caption_entities], ensure_ascii=False
        )
    except Exception:
        ce_json = "[]"

    # thumbs 可以以后再扩展，现在先占位为空列表
    thumbs_json = "[]"

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT OR IGNORE INTO tg_media (
                file_unique_id, chat_id, message_id, from_user_id, sender_chat_id,
                file_id, file_name, mime_type, file_size,
                duration, width, height,
                caption, caption_entities, message_date,
                media_group_id, has_media_spoiler, supports_streaming,
                thumbs
            ) VALUES (?, ?, ?, ?, ?,
                      ?, ?, ?, ?,
                      ?, ?, ?,
                      ?, ?, ?,
                      ?, ?, ?,
                      ?)
            """,
            (
                file_unique_id,
                message.chat.id,
                message.id,
                message.from_user.id if message.from_user else None,
                message.sender_chat.id if message.sender_chat else None,
                file_id,
                getattr(media, "file_name", None),
                getattr(media, "mime_type", None),
                getattr(media, "file_size", None),
                getattr(media, "duration", None),
                getattr(media, "width", None),
                getattr(media, "height", None),
                message.caption,
                ce_json,
                message.date.isoformat() if getattr(message, "date", None) else _now_iso(),
                message.media_group_id,
                int(bool(getattr(message, "has_media_spoiler", False))),
                int(bool(getattr(media, "supports_streaming", False))),
                thumbs_json,
            ),
        )

    return file_unique_id


def create_download(file_unique_id: str, gid: str | None, source_url: str | None) -> int:
    """创建一条下载记录，返回 downloads.id。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO downloads (
                file_unique_id, gid, source_url, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (file_unique_id, gid, source_url, now, now),
        )
        return cur.lastrowid


def mark_download_started(gid: str):
    """标记下载开始时间。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'downloading',
                   started_at = COALESCE(started_at, ?),
                   updated_at = ?
             WHERE gid = ?
            """,
            (now, now, gid),
        )


def get_download_id_by_gid(gid: str) -> int | None:
    """根据 GID 获取下载记录 ID。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM downloads WHERE gid = ?", (gid,))
        row = cur.fetchone()
        return row['id'] if row else None


def mark_download_completed(gid: str, local_path: str | None, total_length: int | None):
    """标记下载完成状态和本地路径。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'completed',
                   local_path = COALESCE(?, local_path),
                   total_length = COALESCE(?, total_length),
                   completed_length = COALESCE(?, completed_length),
                   completed_at = ?,
                   updated_at = ?
             WHERE gid = ?
            """,
            (local_path, total_length, total_length, now, now, gid),
        )


def mark_download_failed(gid: str, error_message: str | None):
    """标记下载失败。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'failed',
                   error_message = ?,
                   updated_at = ?
             WHERE gid = ?
            """,
            (error_message, now, gid),
        )


def fetch_recent_downloads(limit: int = 100):
    """
    查询最近的下载记录（按创建时间倒序），包含部分 Telegram 媒体字段，
    用于 Web 管理页面展示。
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                d.id,
                d.gid,
                d.source_url,
                d.status,
                d.total_length,
                d.completed_length,
                d.local_path,
                d.remote_path,
                d.upload_status,
                d.created_at,
                d.started_at,
                d.completed_at,
                m.file_name,
                m.mime_type,
                m.file_size,
                m.chat_id,
                m.message_id,
                m.media_group_id,
                m.caption,
                m.message_date
            FROM downloads AS d
            LEFT JOIN tg_media AS m
              ON d.file_unique_id = m.file_unique_id
            ORDER BY d.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def fetch_downloads_grouped(limit: int = 100):
    """
    查询下载记录并按消息分组。
    返回格式：按消息组（media_group_id 或 chat_id+message_id）分组的数据
    """
    records = fetch_recent_downloads(limit)
    
    # 按消息分组
    groups: dict[str, list] = {}
    
    for record in records:
        # 确定分组键：优先使用 media_group_id，否则使用 chat_id+message_id
        if record.get('media_group_id'):
            group_key = f"group_{record['media_group_id']}"
        elif record.get('chat_id') and record.get('message_id'):
            group_key = f"msg_{record['chat_id']}_{record['message_id']}"
        else:
            # 如果没有分组信息，使用下载ID作为独立组
            group_key = f"single_{record['id']}"
        
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(record)
    
    # 转换为列表格式，每个组包含组信息和下载列表
    result = []
    for group_key, downloads in groups.items():
        # 获取组的第一条记录作为组信息
        first_record = downloads[0]
        
        # 计算组统计信息
        total_files = len(downloads)
        completed = sum(1 for d in downloads if d.get('status') == 'completed')
        downloading = sum(1 for d in downloads if d.get('status') == 'downloading')
        failed = sum(1 for d in downloads if d.get('status') == 'failed')
        pending = sum(1 for d in downloads if d.get('status') == 'pending')
        # 统计跳过的文件（状态为failed且错误信息包含"跳过"）
        skipped = sum(1 for d in downloads if d.get('status') == 'failed' and d.get('error_message', '').find('跳过') != -1)
        
        total_size = sum(d.get('total_length') or d.get('file_size') or 0 for d in downloads)
        completed_size = sum(d.get('completed_length') or 0 for d in downloads)
        
        result.append({
            'group_key': group_key,
            'group_type': 'media_group' if first_record.get('media_group_id') else 'message',
            'chat_id': first_record.get('chat_id'),
            'message_id': first_record.get('message_id'),
            'media_group_id': first_record.get('media_group_id'),
            'caption': first_record.get('caption'),
            'message_date': first_record.get('message_date') or first_record.get('created_at'),
            'created_at': min(d.get('created_at', '') for d in downloads if d.get('created_at')),
            'stats': {
                'total_files': total_files,
                'completed': completed,
                'downloading': downloading,
                'failed': failed,
                'pending': pending,
                'skipped': skipped,
                'total_size': total_size,
                'completed_size': completed_size
            },
            'downloads': downloads
        })
    
    # 按创建时间倒序排序
    result.sort(key=lambda x: x['created_at'], reverse=True)
    
    return result


def get_config(key: str, default=None):
    """获取配置值"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT value, value_type FROM config_settings WHERE key = ?",
            (key,)
        )
        row = cur.fetchone()
        if row:
            value = row['value']
            value_type = row['value_type']
            # 根据类型转换值
            if value_type == 'int':
                return int(value) if value else default
            elif value_type == 'bool':
                return value.lower() in ('true', '1', 'yes', 'on') if value else default
            elif value_type == 'list':
                return json.loads(value) if value else default
            elif value_type == 'json':
                return json.loads(value) if value else default
            else:
                return value if value else default
        return default


def set_config(key: str, value: any, value_type: str = 'string', category: str = 'general', description: str = None):
    """设置配置值"""
    now = _now_iso()
    
    # 根据类型转换值
    if value_type == 'list' or value_type == 'json':
        value_str = json.dumps(value, ensure_ascii=False) if value else ''
    else:
        value_str = str(value) if value is not None else ''
    
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT OR REPLACE INTO config_settings (key, value, value_type, category, description, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key, value_str, value_type, category, description, now)
        )


def get_all_configs(category: str = None):
    """获取所有配置或指定分类的配置"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if category:
            cur.execute(
                "SELECT key, value, value_type, category, description FROM config_settings WHERE category = ? ORDER BY key",
                (category,)
            )
        else:
            cur.execute(
                "SELECT key, value, value_type, category, description FROM config_settings ORDER BY category, key"
            )
        rows = cur.fetchall()
        result = {}
        for row in rows:
            key = row['key']
            value = row['value']
            value_type = row['value_type']
            # 根据类型转换值
            if value_type == 'int':
                result[key] = int(value) if value else None
            elif value_type == 'bool':
                result[key] = value.lower() in ('true', '1', 'yes', 'on') if value else False
            elif value_type == 'list':
                result[key] = json.loads(value) if value else []
            elif value_type == 'json':
                result[key] = json.loads(value) if value else {}
            else:
                result[key] = value if value else ''
        return result


def init_config_from_yaml():
    """从config.yml初始化配置到数据库（迁移函数）"""
    import yaml
    import os
    
    config_file = './db/config.yml'
    if not os.path.exists(config_file):
        return False
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            yaml_config = yaml.load(f.read(), Loader=yaml.FullLoader)
        
        # 配置项定义：key -> (value_type, category, description)
        config_definitions = {
            # Telegram配置
            'API_ID': ('int', 'telegram', 'Telegram API ID'),
            'API_HASH': ('string', 'telegram', 'Telegram API Hash'),
            'BOT_TOKEN': ('string', 'telegram', 'Telegram Bot Token'),
            'ADMIN_ID': ('int', 'telegram', 'Telegram管理员ID'),
            'FORWARD_ID': ('string', 'telegram', '转发ID'),
            'UP_TELEGRAM': ('bool', 'telegram', '是否上传到Telegram'),
            
            # Rclone配置
            'UP_ONEDRIVE': ('bool', 'rclone', '是否启用rclone上传到OneDrive'),
            'RCLONE_REMOTE': ('string', 'rclone', 'rclone远程名称'),
            'RCLONE_PATH': ('string', 'rclone', 'OneDrive目标路径'),
            'AUTO_DELETE_AFTER_UPLOAD': ('bool', 'rclone', '上传后自动删除本地文件'),
            
            # 下载配置
            'SAVE_PATH': ('string', 'download', '下载保存路径'),
            'PROXY_IP': ('string', 'download', '代理IP'),
            'PROXY_PORT': ('string', 'download', '代理端口'),
            'SKIP_SMALL_FILES': ('bool', 'download', '是否跳过小于指定大小的媒体文件'),
            'MIN_FILE_SIZE_MB': ('int', 'download', '最小文件大小（MB），小于此大小的文件将被跳过'),
            
            # Aria2配置
            'RPC_SECRET': ('string', 'aria2', 'Aria2 RPC密钥'),
            'RPC_URL': ('string', 'aria2', 'Aria2 RPC URL'),
            
            # 直链功能配置
            'ENABLE_STREAM': ('bool', 'stream', '是否启用直链功能'),
            'BIN_CHANNEL': ('string', 'stream', '日志频道ID'),
            'STREAM_PORT': ('int', 'stream', 'Web服务器端口'),
            'STREAM_BIND_ADDRESS': ('string', 'stream', 'Web服务器绑定地址'),
            'STREAM_HASH_LENGTH': ('int', 'stream', '哈希长度'),
            'STREAM_HAS_SSL': ('bool', 'stream', '是否使用SSL'),
            'STREAM_NO_PORT': ('bool', 'stream', '是否隐藏端口'),
            'STREAM_FQDN': ('string', 'stream', '完全限定域名'),
            'STREAM_KEEP_ALIVE': ('bool', 'stream', '是否保持连接活跃'),
            'STREAM_PING_INTERVAL': ('int', 'stream', 'Ping间隔（秒）'),
            'STREAM_USE_SESSION_FILE': ('bool', 'stream', '是否使用会话文件'),
            'STREAM_ALLOWED_USERS': ('string', 'stream', '允许使用直链的用户列表'),
            'STREAM_AUTO_DOWNLOAD': ('bool', 'stream', '是否自动添加到下载队列'),
            'SEND_STREAM_LINK': ('bool', 'stream', '是否发送直链信息给用户'),
            'MULTI_BOT_TOKENS': ('list', 'stream', '多机器人Token列表'),
        }
        
        # 导入配置
        imported_count = 0
        for key, (value_type, category, description) in config_definitions.items():
            if key in yaml_config:
                value = yaml_config[key]
                set_config(key, value, value_type, category, description)
                imported_count += 1
        
        return imported_count > 0
    except Exception as e:
        import logging
        logging.error(f"从config.yml导入配置失败: {e}")
        return False


# ============================================================================
# 上传任务相关函数
# ============================================================================

def create_upload(download_id: int, upload_target: str, remote_path: str = None, max_retries: int = 3) -> int:
    """
    创建一条上传记录，返回 uploads.id。
    
    Args:
        download_id: 关联的下载任务 ID
        upload_target: 上传目标（onedrive/telegram/other）
        remote_path: 远程路径（可选）
        max_retries: 最大重试次数（默认3次）
    
    Returns:
        上传记录的 ID
    """
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO uploads (
                download_id, upload_target, remote_path, status,
                max_retries, created_at, updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """,
            (download_id, upload_target, remote_path, max_retries, now, now),
        )
        return cur.lastrowid


def update_upload_status(upload_id: int, status: str, **kwargs):
    """
    更新上传状态及其他字段。
    
    Args:
        upload_id: 上传记录 ID
        status: 新状态
        **kwargs: 其他要更新的字段（uploaded_size, upload_speed, error_message等）
    """
    now = _now_iso()
    
    # 构建动态更新语句
    fields = ["status = ?", "updated_at = ?"]
    values = [status, now]
    
    for key, value in kwargs.items():
        if key in ['uploaded_size', 'upload_speed', 'error_message', 'error_code', 
                   'failure_reason', 'retry_count', 'remote_path', 'total_size', 'extra']:
            fields.append(f"{key} = ?")
            values.append(value)
    
    values.append(upload_id)
    
    with db_cursor() as cur:
        cur.execute(
            f"""
            UPDATE uploads
               SET {', '.join(fields)}
             WHERE id = ?
            """,
            tuple(values),
        )


def mark_upload_started(upload_id: int):
    """标记上传开始时间。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE uploads
               SET status = 'uploading',
                   started_at = COALESCE(started_at, ?),
                   updated_at = ?
             WHERE id = ?
            """,
            (now, now, upload_id),
        )


def mark_upload_completed(upload_id: int, remote_path: str = None):
    """标记上传完成状态和远程路径。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE uploads
               SET status = 'completed',
                   remote_path = COALESCE(?, remote_path),
                   uploaded_size = COALESCE(total_size, uploaded_size),
                   completed_at = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (remote_path, now, now, upload_id),
        )


def mark_upload_failed(upload_id: int, failure_reason: str, error_message: str = None, error_code: str = None):
    """
    标记上传失败。
    
    Args:
        upload_id: 上传记录 ID
        failure_reason: 失败原因分类（download_failed/code_error/network_error等）
        error_message: 详细错误信息
        error_code: 错误代码
    """
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE uploads
               SET status = 'failed',
                   failure_reason = ?,
                   error_message = ?,
                   error_code = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (failure_reason, error_message, error_code, now, upload_id),
        )


def increment_upload_retry(upload_id: int) -> int:
    """
    增加上传重试次数，返回新的重试次数。
    
    Returns:
        新的重试次数
    """
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE uploads
               SET retry_count = retry_count + 1,
                   updated_at = ?
             WHERE id = ?
            """,
            (now, upload_id),
        )
        
        # 查询新的重试次数
        cur.execute("SELECT retry_count FROM uploads WHERE id = ?", (upload_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def get_upload_by_id(upload_id: int):
    """根据 ID 获取上传记录。"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.*, d.local_path, d.status as download_status
            FROM uploads AS u
            LEFT JOIN downloads AS d ON u.download_id = d.id
            WHERE u.id = ?
            """,
            (upload_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_uploads_by_download(download_id: int):
    """获取某个下载任务的所有上传记录。"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM uploads
            WHERE download_id = ?
            ORDER BY created_at DESC
            """,
            (download_id,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def fetch_recent_uploads(limit: int = 100, status: str = None, upload_target: str = None):
    """
    查询最近的上传记录（按创建时间倒序）。
    
    Args:
        limit: 返回记录数量限制
        status: 可选，按状态过滤
        upload_target: 可选，按上传目标过滤
    
    Returns:
        上传记录列表
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        conditions = []
        params = []
        
        if status:
            conditions.append("u.status = ?")
            params.append(status)
        
        if upload_target:
            conditions.append("u.upload_target = ?")
            params.append(upload_target)
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        
        cur.execute(
            f"""
            SELECT
                u.*,
                d.local_path,
                d.status as download_status,
                d.gid,
                m.file_name,
                m.file_size,
                m.chat_id,
                m.message_id
            FROM uploads AS u
            LEFT JOIN downloads AS d ON u.download_id = d.id
            LEFT JOIN tg_media AS m ON d.file_unique_id = m.file_unique_id
            {where_clause}
            ORDER BY u.created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def count_uploads_by_status():
    """统计各状态的上传数量。"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM uploads
            GROUP BY status
            """
        )
        rows = cur.fetchall()
        return {row['status']: row['count'] for row in rows}


def count_uploads_by_failure_reason():
    """统计各失败原因的数量。"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT failure_reason, COUNT(*) as count
            FROM uploads
            WHERE status = 'failed' AND failure_reason IS NOT NULL
            GROUP BY failure_reason
            """
        )
        rows = cur.fetchall()
        return {row['failure_reason']: row['count'] for row in rows}


def get_upload_statistics():
    """
    获取上传统计信息。
    
    Returns:
        包含各种统计数据的字典
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 总体统计
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'uploading' THEN 1 ELSE 0 END) as uploading,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(total_size) as total_size,
                SUM(uploaded_size) as uploaded_size
            FROM uploads
            """
        )
        stats = dict(cur.fetchone())
        
        # 按目标统计
        cur.execute(
            """
            SELECT upload_target, COUNT(*) as count
            FROM uploads
            GROUP BY upload_target
            """
        )
        stats['by_target'] = {row['upload_target']: row['count'] for row in cur.fetchall()}
        
        # 失败原因统计
        stats['by_failure_reason'] = count_uploads_by_failure_reason()
        
        return stats


def get_pending_uploads(upload_target: str = None):
    """
    获取待上传的记录（状态为 pending 且关联的下载已完成）。
    
    Args:
        upload_target: 可选，按上传目标过滤
    
    Returns:
        待上传记录列表
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        target_filter = "AND u.upload_target = ?" if upload_target else ""
        params = [upload_target] if upload_target else []
        
        cur.execute(
            f"""
            SELECT
                u.*,
                d.local_path,
                d.status as download_status,
                m.file_name,
                m.file_size
            FROM uploads AS u
            INNER JOIN downloads AS d ON u.download_id = d.id
            LEFT JOIN tg_media AS m ON d.file_unique_id = m.file_unique_id
            WHERE u.status = 'pending'
              AND d.status = 'completed'
              {target_filter}
            ORDER BY u.created_at ASC
            """,
            tuple(params),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def migrate_upload_data():
    """
    将 downloads 表中的上传数据迁移到 uploads 表。
    仅迁移有 upload_status 或 remote_path 的记录。
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 查询所有有上传信息的下载记录
        cur.execute(
            """
            SELECT id, upload_status, remote_path, created_at
            FROM downloads
            WHERE upload_status IS NOT NULL OR remote_path IS NOT NULL
            """
        )
        downloads = cur.fetchall()
        
        migrated_count = 0
        for download in downloads:
            download_id = download['id']
            old_status = download['upload_status'] or 'pending'
            remote_path = download['remote_path']
            created_at = download['created_at']
            
            # 映射旧状态到新状态
            status_map = {
                'pending': 'pending',
                'uploading': 'uploading',
                'uploaded': 'completed',
                'failed': 'failed'
            }
            new_status = status_map.get(old_status, 'pending')
            
            # 检查是否已经迁移过
            cur.execute(
                "SELECT COUNT(*) as count FROM uploads WHERE download_id = ?",
                (download_id,)
            )
            if cur.fetchone()['count'] > 0:
                continue  # 已迁移，跳过
            
            # 创建上传记录（假设目标是 onedrive）
            cur.execute(
                """
                INSERT INTO uploads (
                    download_id, upload_target, remote_path, status,
                    created_at, updated_at
                ) VALUES (?, 'onedrive', ?, ?, ?, ?)
                """,
                (download_id, remote_path, new_status, created_at, created_at)
            )
            migrated_count += 1
        
        conn.commit()
        logger.info(f"已迁移 {migrated_count} 条上传记录")
        return migrated_count

