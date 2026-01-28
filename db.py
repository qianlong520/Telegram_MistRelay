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
    """返回UTC时间的ISO8601格式字符串，带'Z'后缀表示UTC时区"""
    return datetime.utcnow().isoformat(timespec="seconds") + 'Z'


def _format_message_date(msg_date) -> str:
    """格式化消息日期为ISO8601格式，确保带时区信息"""
    if not msg_date:
        return _now_iso()
    # Pyrogram的message.date是UTC时间的datetime对象
    # 转换为ISO格式并添加'Z'后缀表示UTC
    iso_str = msg_date.isoformat()
    # 如果已经有时区信息（带+或-），保持不变；否则添加'Z'
    if 'Z' in iso_str or '+' in iso_str or (len(iso_str) > 10 and iso_str[-6] in '+-'):
        return iso_str
    # 移除微秒部分（如果有），只保留秒级精度
    if '.' in iso_str:
        iso_str = iso_str.split('.')[0]
    return iso_str + 'Z'


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
        
        # 数据库迁移：为 uploads 表添加 cleaned_at 字段（如果不存在）
        try:
            cur.execute("ALTER TABLE uploads ADD COLUMN cleaned_at TEXT")
            logging.info("已为 uploads 表添加 cleaned_at 字段")
        except sqlite3.OperationalError as e:
            # 字段已存在，忽略错误
            if "duplicate column name" not in str(e).lower():
                logging.warning(f"添加 cleaned_at 字段时出错（可能已存在）: {e}")

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
                _format_message_date(message.date) if getattr(message, "date", None) else _now_iso(),
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
        download_id = cur.lastrowid
    # 如果有 gid，推送 WebSocket 更新（新记录通知）
    if gid:
        _notify_ws_download_update(gid)
    # 推送统计更新，确保前端刷新列表
    _notify_ws_statistics_update()
    return download_id


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
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def get_download_id_by_gid(gid: str) -> int | None:
    """根据 GID 获取下载记录 ID。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM downloads WHERE gid = ?", (gid,))
        row = cur.fetchone()
        return row['id'] if row else None


def get_download_by_id(download_id: int):
    """根据 ID 获取下载记录。"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM downloads
            WHERE id = ?
            """,
            (download_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _notify_ws_download_update(gid: str):
    """通过 WebSocket 推送下载状态更新（异步，不阻塞）"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        import asyncio
        
        # 获取下载记录
        download_id = get_download_id_by_gid(gid)
        if download_id:
            download = get_download_by_id(download_id)
            if download:
                # 获取关联的上传记录，确保数据一致性
                uploads = get_uploads_by_download(download_id)
                uploads_data = []
                for upload in uploads:
                    uploads_data.append({
                        "id": upload.get('id'),
                        "upload_target": upload.get('upload_target'),
                        "status": upload.get('status'),
                        "uploaded_size": upload.get('uploaded_size'),
                        "total_size": upload.get('total_size'),
                        "upload_speed": upload.get('upload_speed'),
                        "cleaned_at": upload.get('cleaned_at'),
                    })
                
                # 异步推送更新
                loop = None
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    # 如果没有事件循环，创建一个新的
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                if loop and not loop.is_closed():
                    asyncio.create_task(ws_manager.send_download_update({
                        "gid": gid,
                        "download_id": download_id,
                        "status": download.get('status'),
                        "completed_length": download.get('completed_length'),
                        "total_length": download.get('total_length'),
                        "download_speed": download.get('download_speed'),
                        "uploads": uploads_data,  # 包含上传信息，确保数据一致性
                    }))
    except Exception as e:
        # 静默失败，不影响主流程
        pass


def _notify_ws_upload_update(upload_id: int):
    """通过 WebSocket 推送上传状态更新（异步，不阻塞）"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        import asyncio
        
        upload = get_upload_by_id(upload_id)
        if upload:
            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop and not loop.is_closed():
                asyncio.create_task(ws_manager.send_upload_update({
                    "upload_id": upload_id,
                    "download_id": upload.get('download_id'),
                    "status": upload.get('status'),
                    "uploaded_size": upload.get('uploaded_size'),
                    "total_size": upload.get('total_size'),
                    "upload_speed": upload.get('upload_speed'),
                    "cleaned_at": upload.get('cleaned_at'),  # 包含清理状态
                }))
    except Exception as e:
        pass


def _notify_ws_cleanup_update(upload_id: int):
    """通过 WebSocket 推送清理状态更新（异步，不阻塞）"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        import asyncio
        
        upload = get_upload_by_id(upload_id)
        if upload:
            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop and not loop.is_closed():
                asyncio.create_task(ws_manager.send_cleanup_update({
                    "upload_id": upload_id,
                    "download_id": upload.get('download_id'),
                    "cleaned_at": upload.get('cleaned_at'),
                }))
    except Exception as e:
        pass


def _notify_ws_statistics_update():
    """通过 WebSocket 推送统计信息更新（异步，不阻塞）"""
    try:
        from WebStreamer.server.ws_manager import ws_manager
        import asyncio
        
        # 获取统计信息
        download_stats = get_download_statistics()
        upload_stats = get_upload_statistics()
        
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop and not loop.is_closed():
            asyncio.create_task(ws_manager.send_statistics_update({
                "downloads": download_stats,
                "uploads": upload_stats,
            }))
    except Exception as e:
        # 静默失败，不影响主流程
        pass


def mark_download_completed(gid: str, local_path: str | None, total_length: int | None):
    """
    标记下载完成状态和本地路径。
    注意：这里不立即标记为 completed，而是保持当前状态（downloading）。
    只有在清理完成后，才会通过 mark_upload_cleaned 更新为 completed。
    """
    now = _now_iso()
    with db_cursor() as cur:
        # 检查是否有上传任务，如果有，保持 downloading 状态；如果没有，标记为 completed
        download_id = get_download_id_by_gid(gid)
        has_uploads = False
        if download_id:
            cur.execute("SELECT COUNT(*) FROM uploads WHERE download_id = ?", (download_id,))
            upload_count = cur.fetchone()[0]
            has_uploads = upload_count > 0
        
        # 如果有上传任务，保持 downloading 状态；否则标记为 completed
        if has_uploads:
            # 保持当前状态（通常是 downloading），只更新路径和大小
            cur.execute(
                """
                UPDATE downloads
                   SET local_path = COALESCE(?, local_path),
                       total_length = COALESCE(?, total_length),
                       completed_length = COALESCE(?, completed_length),
                       updated_at = ?
                 WHERE gid = ?
                """,
                (local_path, total_length, total_length, now, gid),
            )
        else:
            # 没有上传任务，直接标记为 completed
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
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


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
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def mark_download_paused(gid: str):
    """标记下载暂停。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'paused',
                   download_speed = 0,
                   updated_at = ?
             WHERE gid = ?
            """,
            (now, gid),
        )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def mark_download_resumed(gid: str):
    """标记下载恢复。"""
    now = _now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE downloads
               SET status = 'downloading',
                   updated_at = ?
             WHERE gid = ? AND status = 'paused'
            """,
            (now, gid),
        )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def update_download_progress(gid: str, completed_length: int | None = None, 
                             total_length: int | None = None, 
                             download_speed: int | None = None):
    """更新下载进度。"""
    now = _now_iso()
    updates = ["updated_at = ?"]
    values = [now]
    
    if completed_length is not None:
        updates.append("completed_length = ?")
        values.append(completed_length)
    
    if total_length is not None:
        updates.append("total_length = ?")
        values.append(total_length)
    
    if download_speed is not None:
        updates.append("download_speed = ?")
        values.append(download_speed)
    
    values.append(gid)
    
    with db_cursor() as cur:
        cur.execute(
            f"""
            UPDATE downloads
               SET {', '.join(updates)}
             WHERE gid = ?
            """,
            tuple(values),
        )
    # 推送 WebSocket 更新
    _notify_ws_download_update(gid)


def fetch_recent_downloads(limit: int = 100):
    """
    查询最近的下载记录（按创建时间倒序），包含部分 Telegram 媒体字段和上传信息，
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
                d.download_speed,
                d.local_path,
                d.remote_path,
                d.upload_status,
                d.created_at,
                d.started_at,
                d.completed_at,
                d.updated_at,
                m.file_name,
                m.mime_type,
                m.file_size,
                m.chat_id,
                m.message_id,
                m.media_group_id,
                m.caption,
                m.message_date,
                u.id as upload_id,
                u.upload_target,
                u.remote_path as upload_remote_path,
                u.status as upload_status_detail,
                u.total_size as upload_total_size,
                u.uploaded_size,
                u.upload_speed,
                u.failure_reason,
                u.error_message as upload_error_message,
                u.created_at as upload_created_at,
                u.started_at as upload_started_at,
                u.completed_at as upload_completed_at,
                u.cleaned_at as upload_cleaned_at
            FROM downloads AS d
            LEFT JOIN tg_media AS m
              ON d.file_unique_id = m.file_unique_id
            LEFT JOIN uploads AS u
              ON u.download_id = d.id
            ORDER BY d.created_at DESC, u.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        # 将结果转换为字典，并处理多个上传记录的情况
        result_dict = {}
        for row in rows:
            download_id = row['id']
            if download_id not in result_dict:
                # 创建下载记录
                download_record = {
                    'id': row['id'],
                    'gid': row['gid'],
                    'source_url': row['source_url'],
                    'status': row['status'],
                    'total_length': row['total_length'],
                    'completed_length': row['completed_length'],
                    'download_speed': row['download_speed'],
                    'local_path': row['local_path'],
                    'remote_path': row['remote_path'],
                    'upload_status': row['upload_status'],
                    'created_at': row['created_at'],
                    'started_at': row['started_at'],
                    'completed_at': row['completed_at'],
                    'updated_at': row['updated_at'],
                    'file_name': row['file_name'],
                    'mime_type': row['mime_type'],
                    'file_size': row['file_size'],
                    'chat_id': row['chat_id'],
                    'message_id': row['message_id'],
                    'media_group_id': row['media_group_id'],
                    'caption': row['caption'],
                    'message_date': row['message_date'],
                    'uploads': []
                }
                result_dict[download_id] = download_record
            
            # 添加上传记录（如果有）
            if row['upload_id']:
                upload_id = row['upload_id']
                # 检查是否已经添加过这个上传记录
                existing_upload_ids = [u['id'] for u in result_dict[download_id]['uploads']]
                if upload_id not in existing_upload_ids:
                    upload_record = {
                        'id': upload_id,
                        'upload_target': row['upload_target'],
                        'remote_path': row['upload_remote_path'],
                        'status': row['upload_status_detail'],
                        'total_size': row['upload_total_size'],
                        'uploaded_size': row['uploaded_size'],
                        'upload_speed': row['upload_speed'],
                        'failure_reason': row['failure_reason'],
                        'error_message': row['upload_error_message'],
                        'created_at': row['upload_created_at'],
                        'started_at': row['upload_started_at'],
                        'completed_at': row['upload_completed_at'],
                        'cleaned_at': row['upload_cleaned_at']
                    }
                    result_dict[download_id]['uploads'].append(upload_record)
        
        # 对每个下载记录的上传列表按创建时间倒序排序（保持稳定排序）
        # 使用ID作为次要排序键，确保排序稳定
        for download_record in result_dict.values():
            if download_record.get('uploads'):
                download_record['uploads'].sort(key=lambda u: (
                    u.get('created_at') or '',  # 字符串排序（ISO格式天然支持）
                    u.get('id') or 0
                ), reverse=False)  # 正序：先创建的在前，后创建的在后
        
        return list(result_dict.values())


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
        
        # 计算已完成数量：下载完成且所有上传任务都已完成（或没有上传任务）
        def is_truly_completed(download_record):
            """判断一个下载记录是否真正完成（下载完成且所有上传都完成）"""
            if download_record.get('status') != 'completed':
                return False
            
            # 检查上传任务
            uploads = download_record.get('uploads', [])
            if not uploads:
                # 没有上传任务，下载完成即完成
                return True
            
            # 检查所有上传任务是否都已完成或失败
            for upload in uploads:
                upload_status = upload.get('status')
                # 如果有正在上传、等待下载或待处理的上传任务，不算完成
                if upload_status in ['uploading', 'pending', 'waiting_download']:
                    return False
            
            # 所有上传任务都已完成或失败
            return True
        
        completed = sum(1 for d in downloads if is_truly_completed(d))
        downloading = sum(1 for d in downloads if d.get('status') == 'downloading')
        failed = sum(1 for d in downloads if d.get('status') == 'failed')
        pending = sum(1 for d in downloads if d.get('status') == 'pending')
        # 统计跳过的文件（状态为failed且错误信息包含"跳过"）
        skipped = sum(1 for d in downloads if d.get('status') == 'failed' and d.get('error_message', '').find('跳过') != -1)
        
        total_size = sum(d.get('total_length') or d.get('file_size') or 0 for d in downloads)
        completed_size = sum(d.get('completed_length') or 0 for d in downloads)
        
        # 对组内的下载记录按创建时间正序排序（保持稳定排序）
        # 使用ID作为次要排序键，确保排序稳定
        # 正序：先创建的在前，后创建的在后
        downloads_sorted = sorted(downloads, key=lambda d: (
            d.get('created_at') or '',  # 字符串排序（ISO格式天然支持）
            d.get('id') or 0
        ), reverse=False)
        
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
            'downloads': downloads_sorted
        })
    
    # 按创建时间倒序排序（后创建的在前，先创建的在后）
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
            # 谷歌网盘配置
            'UP_GOOGLE_DRIVE': ('bool', 'rclone', '是否上传到Google Drive'),
            'GOOGLE_DRIVE_REMOTE': ('string', 'rclone', 'Google Drive Rclone远程名称（默认gdrive），需与rclone.conf中的配置名称一致'),
            'GOOGLE_DRIVE_PATH': ('string', 'rclone', 'Google Drive上传路径（默认/Downloads）'),
            
            # 下载配置
            'SAVE_PATH': ('string', 'download', '下载保存路径'),
            'PROXY_IP': ('string', 'download', '代理IP'),
            'PROXY_PORT': ('string', 'download', '代理端口'),
            'SKIP_SMALL_FILES': ('bool', 'download', '是否跳过小于指定大小的媒体文件'),
            'MIN_FILE_SIZE_MB': ('int', 'download', '最小文件大小（MB），小于此大小的文件将被跳过'),
            
            # Aria2配置
            'RPC_SECRET': ('string', 'aria2', 'Aria2 RPC密钥'),
            'RPC_URL': ('string', 'aria2', 'Aria2 RPC URL'),
            'MAX_CONCURRENT_UPLOADS': ('int', 'upload', '最大并发上传数（默认10）'),
            
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
        upload_id = cur.lastrowid
    # 推送 WebSocket 更新（新记录通知）
    _notify_ws_upload_update(upload_id)
    # 推送统计更新，确保前端刷新列表
    _notify_ws_statistics_update()
    return upload_id


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
    # 推送 WebSocket 更新（仅在状态变化或关键字段更新时）
    if status == 'uploading' or 'uploaded_size' in kwargs or 'upload_speed' in kwargs:
        _notify_ws_upload_update(upload_id)


def check_and_update_download_status_if_file_exists(upload_id: int, file_path: str):
    """
    检查并更新下载记录状态：如果文件已存在且下载记录状态为pending，则标记为completed。
    
    Args:
        upload_id: 上传记录 ID
        file_path: 文件路径
    """
    import os
    try:
        # 获取关联的下载ID
        download_id = None
        with db_cursor() as cur:
            cur.execute("SELECT download_id FROM uploads WHERE id = ?", (upload_id,))
            row = cur.fetchone()
            if row:
                download_id = row[0]
        
        if not download_id:
            return
        
        # 获取下载记录
        download_record = get_download_by_id(download_id)
        if not download_record:
            return
        
        # 如果下载记录状态为pending且文件已存在，更新为completed
        if download_record.get('status') == 'pending' and os.path.exists(file_path):
            try:
                file_size = os.path.getsize(file_path)
                now = _now_iso()
                with db_cursor() as cur:
                    cur.execute(
                        """
                        UPDATE downloads
                           SET status = 'completed',
                               local_path = COALESCE(?, local_path),
                               total_length = COALESCE(?, total_length),
                               completed_length = COALESCE(?, completed_length),
                               completed_at = COALESCE(completed_at, ?),
                               updated_at = ?
                         WHERE id = ?
                        """,
                        (file_path, file_size, file_size, now, now, download_id),
                    )
                # 推送 WebSocket 更新
                gid = download_record.get('gid')
                if gid:
                    _notify_ws_download_update(gid)
                else:
                    _notify_ws_statistics_update()
                logging.info(f"下载记录 {download_id} 已更新为completed（文件已存在）")
            except Exception as e:
                logging.warning(f"更新下载记录状态失败: {e}")
    except Exception as e:
        logging.debug(f"检查下载记录状态失败: {e}")


def mark_upload_started(upload_id: int, total_size: int = None):
    """
    标记上传开始时间。
    
    Args:
        upload_id: 上传记录 ID
        total_size: 可选，文件总大小（字节）
    """
    now = _now_iso()
    with db_cursor() as cur:
        if total_size and total_size > 0:
            cur.execute(
                """
                UPDATE uploads
                   SET status = 'uploading',
                       started_at = COALESCE(started_at, ?),
                       total_size = COALESCE(total_size, ?),
                       updated_at = ?
                 WHERE id = ?
                """,
                (now, total_size, now, upload_id),
            )
        else:
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
    # 推送 WebSocket 更新
    _notify_ws_upload_update(upload_id)


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
    # 推送 WebSocket 更新
    _notify_ws_upload_update(upload_id)


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
    # 推送 WebSocket 更新
    _notify_ws_upload_update(upload_id)


def mark_upload_cleaned(upload_id: int):
    """
    标记上传任务对应的文件已被清理（删除）。
    如果该下载任务的所有上传都已清理完成，则将下载状态更新为 completed。
    
    Args:
        upload_id: 上传记录 ID
    """
    now = _now_iso()
    download_id = None
    
    with db_cursor() as cur:
        # 获取关联的下载ID
        cur.execute("SELECT download_id FROM uploads WHERE id = ?", (upload_id,))
        row = cur.fetchone()
        if row:
            download_id = row[0]
        
        # 更新清理状态
        cur.execute(
            """
            UPDATE uploads
               SET cleaned_at = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (now, now, upload_id),
        )
        
        # 如果有关联的下载任务，检查是否所有上传都已清理
        if download_id:
            # 获取该下载任务的所有上传记录
            cur.execute(
                """
                SELECT id, status, cleaned_at
                FROM uploads
                WHERE download_id = ?
                """,
                (download_id,)
            )
            uploads = cur.fetchall()
            
            # 检查是否所有上传都已清理完成
            if uploads:
                all_cleaned = all(
                    upload[2] is not None  # cleaned_at 不为空
                    for upload in uploads
                )
                
                # 如果所有上传都已清理，更新下载状态为 completed
                if all_cleaned:
                    cur.execute(
                        """
                        UPDATE downloads
                           SET status = 'completed',
                               updated_at = ?
                         WHERE id = ? AND status != 'failed'
                        """,
                        (now, download_id)
                    )
                    # 获取 gid 以便推送 WebSocket 更新和更新队列通知消息
                    cur.execute("SELECT gid FROM downloads WHERE id = ?", (download_id,))
                    gid_row = cur.fetchone()
                    if gid_row and gid_row[0]:
                        gid = gid_row[0]
                        _notify_ws_download_update(gid)
                        # 更新队列通知消息（如果存在）
                        try:
                            from WebStreamer.bot.plugins.stream_modules.utils import update_queue_msg_on_cleanup
                            import asyncio
                            loop = None
                            try:
                                loop = asyncio.get_event_loop()
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                            
                            if loop.is_running():
                                loop.create_task(update_queue_msg_on_cleanup(gid))
                            else:
                                loop.run_until_complete(update_queue_msg_on_cleanup(gid))
                        except Exception as update_e:
                            logging.debug(f"更新队列通知消息失败: {update_e}")
    
    # 推送 WebSocket 更新
    # 同时推送清理更新和上传更新（因为清理状态是上传记录的一部分）
    _notify_ws_cleanup_update(upload_id)
    _notify_ws_upload_update(upload_id)  # 推送上传更新，包含清理状态


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


def get_download_statistics():
    """
    获取下载统计信息（按消息分组统计，而不是按下载记录统计）。
    
    Returns:
        包含各种统计数据的字典
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 获取所有下载记录，包含消息分组信息
        cur.execute(
            """
            SELECT
                d.id,
                d.status,
                d.total_length,
                d.completed_length,
                m.media_group_id,
                m.chat_id,
                m.message_id
            FROM downloads AS d
            LEFT JOIN tg_media AS m ON d.file_unique_id = m.file_unique_id
            """
        )
        rows = cur.fetchall()
        
        # 按消息分组
        message_groups: dict[str, list] = {}
        
        for row in rows:
            row_dict = dict(row)
            # 确定分组键：优先使用 media_group_id，否则使用 chat_id+message_id
            if row_dict.get('media_group_id'):
                group_key = f"group_{row_dict['media_group_id']}"
            elif row_dict.get('chat_id') and row_dict.get('message_id'):
                group_key = f"msg_{row_dict['chat_id']}_{row_dict['message_id']}"
            else:
                # 如果没有分组信息，使用下载ID作为独立消息
                group_key = f"single_{row_dict['id']}"
            
            if group_key not in message_groups:
                message_groups[group_key] = []
            message_groups[group_key].append(row_dict)
        
        # 统计消息状态
        total_messages = len(message_groups)
        completed_messages = 0
        downloading_messages = 0
        failed_messages = 0
        pending_messages = 0
        total_size = 0
        completed_size = 0
        
        for group_key, downloads in message_groups.items():
            # 获取该消息下所有文件的状态
            statuses = [d.get('status') for d in downloads]
            
            # 计算消息状态（优先级：downloading > failed > pending > completed）
            # 如果消息下有任何一个文件正在下载，则消息状态为 downloading
            # 如果消息下有任何一个文件失败，则消息状态为 failed
            # 如果消息下有任何一个文件等待中，则消息状态为 pending
            # 否则，如果所有文件都已完成，则消息状态为 completed
            if any(s == 'downloading' for s in statuses):
                downloading_messages += 1
            elif any(s == 'failed' for s in statuses):
                failed_messages += 1
            elif any(s == 'pending' for s in statuses):
                pending_messages += 1
            elif all(s == 'completed' for s in statuses):
                completed_messages += 1
            
            # 累计文件大小
            for d in downloads:
                total_size += d.get('total_length') or 0
                completed_size += d.get('completed_length') or 0
        
        stats = {
            'total': total_messages,
            'completed': completed_messages,
            'downloading': downloading_messages,
            'failed': failed_messages,
            'pending': pending_messages,
            'waiting': pending_messages,  # waiting 和 pending 相同
            'total_size': total_size or 0,
            'completed_size': completed_size or 0
        }
        
        return stats


def delete_all_downloads():
    """
    删除所有下载记录、上传记录和关联的 Telegram 媒体记录。
    
    注意：
    - 外键约束在 downloads 表上（downloads.file_unique_id 引用 tg_media.file_unique_id），
      所以删除 downloads 不会自动删除 tg_media。我们需要手动删除所有 tg_media 记录。
    - uploads 表有外键约束（uploads.download_id 引用 downloads.id ON DELETE CASCADE），
      删除 downloads 时会自动级联删除 uploads，但为了确保完整性，我们也显式删除。
    
    Returns:
        包含删除记录数的字典
    """
    with get_connection() as conn:
        cur = conn.cursor()
        
        # 先统计要删除的记录数
        cur.execute("SELECT COUNT(*) FROM downloads")
        download_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM uploads")
        upload_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM tg_media")
        media_count = cur.fetchone()[0]
        
        # 删除所有上传记录（先删除，避免外键约束问题）
        cur.execute("DELETE FROM uploads")
        
        # 删除所有下载记录
        cur.execute("DELETE FROM downloads")
        
        # 删除所有 Telegram 媒体记录（因为下载记录已删除，这些媒体记录也没有用了）
        cur.execute("DELETE FROM tg_media")
        
        conn.commit()
        
        return {
            'deleted_downloads': download_count,
            'deleted_uploads': upload_count,
            'deleted_media': media_count
        }


def delete_download_record(download_id: int, delete_local_file: bool = True):
    """
    删除单个下载记录及其关联的上传记录和本地文件。
    
    Args:
        download_id: 下载记录ID
        delete_local_file: 是否删除本地文件（默认True）
    
    Returns:
        dict: 包含删除结果的字典
    """
    import os
    
    with get_connection() as conn:
        cur = conn.cursor()
        
        # 获取下载记录信息（包括GID和本地路径）
        cur.execute(
            """
            SELECT gid, local_path, file_unique_id
            FROM downloads
            WHERE id = ?
            """,
            (download_id,)
        )
        download_row = cur.fetchone()
        
        if not download_row:
            return {
                'success': False,
                'error': '下载记录不存在'
            }
        
        gid = download_row[0]
        local_path = download_row[1]
        file_unique_id = download_row[2]
        
        # 注意：删除记录时不尝试从Aria2移除任务
        # 因为删除记录是删除数据库记录，不是删除Aria2任务
        # 如果用户想删除Aria2任务，应该使用删除任务的API（DELETE /api/downloads/{gid}）
        # 这样可以避免历史遗留记录（GID已不存在）导致的错误
        
        # 删除本地文件（如果存在且需要删除）
        deleted_file = False
        if delete_local_file and local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
                deleted_file = True
            except Exception as e:
                logging.warning(f"删除本地文件失败: {e}")
        
        # 删除上传记录（外键约束会自动级联删除，但显式删除更清晰）
        cur.execute("DELETE FROM uploads WHERE download_id = ?", (download_id,))
        upload_count = cur.rowcount
        
        # 删除下载记录
        cur.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
        download_deleted = cur.rowcount > 0
        
        # 检查是否还有其他下载记录使用同一个 file_unique_id
        cur.execute(
            "SELECT COUNT(*) FROM downloads WHERE file_unique_id = ?",
            (file_unique_id,)
        )
        remaining_downloads = cur.fetchone()[0]
        
        # 如果没有其他下载记录使用这个媒体，删除媒体记录
        media_deleted = False
        if remaining_downloads == 0:
            cur.execute("DELETE FROM tg_media WHERE file_unique_id = ?", (file_unique_id,))
            media_deleted = cur.rowcount > 0
        
        conn.commit()
        
        return {
            'success': True,
            'download_deleted': download_deleted,
            'upload_count': upload_count,
            'media_deleted': media_deleted,
            'file_deleted': deleted_file,
            'local_path': local_path if deleted_file else None
        }


def get_upload_statistics():
    """
    获取上传统计信息。
    
    Returns:
        包含各种统计数据的字典
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 统计各状态的数量
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM uploads
            GROUP BY status
            """
        )
        status_counts = {row['status']: row['count'] for row in cur.fetchall()}
        
        # 统计已清理的数量
        cur.execute(
            """
            SELECT COUNT(*) as count
            FROM uploads
            WHERE cleaned_at IS NOT NULL
            """
        )
        cleaned_count = cur.fetchone()['count']
        
        # 总体统计
        cur.execute(
            """
            SELECT
                SUM(total_size) as total_size,
                SUM(uploaded_size) as uploaded_size
            FROM uploads
            """
        )
        size_stats = dict(cur.fetchone())
        
        # 按目标统计
        cur.execute(
            """
            SELECT upload_target, COUNT(*) as count
            FROM uploads
            GROUP BY upload_target
            """
        )
        by_target = {row['upload_target']: row['count'] for row in cur.fetchall()}
        
        # 失败原因统计
        by_failure_reason = count_uploads_by_failure_reason()
        
        return {
            'total': sum(status_counts.values()),
            'uploading': status_counts.get('uploading', 0),
            'completed': status_counts.get('completed', 0),
            'failed': status_counts.get('failed', 0),
            'pending': status_counts.get('pending', 0) + status_counts.get('waiting_download', 0),
            'cleaned': cleaned_count,
            'total_size': size_stats.get('total_size'),
            'uploaded_size': size_stats.get('uploaded_size') or 0,
            'by_target': by_target,
            'by_failure_reason': by_failure_reason
        }


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

