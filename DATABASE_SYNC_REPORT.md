# 数据库使用和数据同步一致性报告

## 1. 数据库架构

### 1.1 数据库文件
- **路径**: `/app/db/downloads.db` (可通过环境变量 `MISTRELAY_DB_PATH` 配置)
- **类型**: SQLite3
- **WAL模式**: 已启用 (Write-Ahead Logging)，提升并发性能
- **连接管理**: 使用上下文管理器 `db_cursor()` 确保自动提交和关闭

### 1.2 数据表结构

#### tg_media 表
- **主键**: `file_unique_id` (Telegram 全局唯一 ID)
- **用途**: 存储 Telegram 媒体元数据
- **关联**: 通过 `file_unique_id` 与 `downloads` 表关联

#### downloads 表
- **主键**: `id` (自增)
- **外键**: `file_unique_id` → `tg_media.file_unique_id` (ON DELETE CASCADE)
- **关键字段**:
  - `gid`: aria2 任务 ID
  - `status`: 下载状态 (pending/downloading/completed/failed/paused/waiting)
  - `completed_length`, `total_length`, `download_speed`: 进度信息
  - `local_path`: 本地文件路径
  - `created_at`, `started_at`, `completed_at`, `updated_at`: 时间戳

#### uploads 表
- **主键**: `id` (自增)
- **外键**: `download_id` → `downloads.id` (ON DELETE CASCADE)
- **关键字段**:
  - `status`: 上传状态 (pending/waiting_download/uploading/completed/failed/cancelled/paused)
  - `upload_target`: 上传目标 (onedrive/telegram/gdrive)
  - `uploaded_size`, `total_size`, `upload_speed`: 进度信息
  - `cleaned_at`: 清理时间

---

## 2. 数据库操作函数清单

### 2.1 Telegram 媒体相关
- `save_tg_media(message, media) -> str`: 保存 Telegram 媒体元数据

### 2.2 下载任务相关
- `create_download(file_unique_id, gid, source_url) -> int`: 创建下载记录
- `mark_download_started(gid)`: 标记下载开始
- `mark_download_completed(gid, local_path, total_length)`: 标记下载完成
- `mark_download_failed(gid, error_message)`: 标记下载失败
- `mark_download_paused(gid)`: 标记下载暂停
- `mark_download_resumed(gid)`: 标记下载恢复
- `update_download_progress(gid, completed_length, total_length, download_speed)`: 更新下载进度
- `get_download_id_by_gid(gid) -> int | None`: 根据 GID 获取下载 ID
- `get_download_by_id(download_id)`: 根据 ID 获取下载记录
- `fetch_recent_downloads(limit)`: 获取最近下载记录
- `fetch_downloads_grouped(limit)`: 获取分组下载记录
- `delete_download_record(download_id, delete_local_file)`: 删除下载记录
- `delete_all_downloads()`: 删除所有下载记录
- `get_download_statistics()`: 获取下载统计信息

### 2.3 上传任务相关
- `create_upload(download_id, upload_target, remote_path, max_retries) -> int`: 创建上传记录
- `update_upload_status(upload_id, status, **kwargs)`: 更新上传状态
- `mark_upload_started(upload_id, total_size)`: 标记上传开始
- `mark_upload_completed(upload_id, remote_path)`: 标记上传完成
- `mark_upload_failed(upload_id, failure_reason, error_message, error_code)`: 标记上传失败
- `mark_upload_cleaned(upload_id)`: 标记上传已清理
- `check_and_update_download_status_if_file_exists(upload_id, file_path)`: 检查并更新下载状态
- `get_upload_by_id(upload_id)`: 根据 ID 获取上传记录
- `get_uploads_by_download(download_id)`: 根据下载 ID 获取上传记录
- `fetch_recent_uploads(limit, status, upload_target)`: 获取最近上传记录
- `get_upload_statistics()`: 获取上传统计信息
- `get_pending_uploads(upload_target)`: 获取待处理的上传任务
- `increment_upload_retry(upload_id) -> int`: 增加上传重试次数

### 2.4 WebSocket 通知相关
- `_notify_ws_download_update(gid)`: 推送下载状态更新
- `_notify_ws_upload_update(upload_id)`: 推送上传状态更新
- `_notify_ws_cleanup_update(upload_id)`: 推送清理状态更新
- `_notify_ws_statistics_update()`: 推送统计信息更新

---

## 3. 数据同步机制

### 3.1 Aria2 状态同步

#### 3.1.1 WebSocket 事件监听 (`aria2_client/client.py`)
- `onDownloadStart`: 触发 `on_download_start()` → `mark_download_started()`
- `onDownloadComplete`: 触发 `on_download_complete()` → `mark_download_completed()`
- `onDownloadError`: 触发 `on_download_error()` → `mark_download_failed()`
- `onDownloadPause`: 触发 `on_download_pause()` → `mark_download_paused()`

#### 3.1.2 轮询同步 (`aria2_client/client.py::poll_active_downloads`)
- **轮询间隔**: 通过 `POLL_INTERVAL` 和 `IDLE_CHECK_INTERVAL` 控制
- **同步方法**: `sync_download_status(gid, aria2_status)`
  - 检查 aria2 状态: `active`, `waiting`, `paused`, `complete`, `error`, `removed`
  - 对比数据库状态，确保一致性
  - 处理状态转换（如 paused → active）

#### 3.1.3 进度更新 (`aria2_client/download_handler.py::check_download_progress`)
- 定期调用 `update_download_progress()` 更新进度
- 自动触发 WebSocket 通知

### 3.2 上传状态同步

#### 3.2.1 上传处理器 (`aria2_client/upload_handler.py`)
- OneDrive/Google Drive: rclone 进程监控
- Telegram: 上传进度回调
- 完成后调用 `mark_upload_completed()` 或 `mark_upload_failed()`
- 清理后调用 `mark_upload_cleaned()` → 更新下载状态为 `completed`

### 3.3 WebSocket 实时推送

#### 3.3.1 推送时机
- **下载更新**: 每次状态变更、进度更新时
- **上传更新**: 每次状态变更、进度更新时
- **清理更新**: 文件清理完成时
- **统计更新**: 统计信息变更时

#### 3.3.2 推送内容
- 下载: `gid`, `download_id`, `status`, `completed_length`, `total_length`, `download_speed`
- 上传: `upload_id`, `download_id`, `status`, `uploaded_size`, `total_size`, `upload_speed`, `cleaned_at`
- 统计: `downloads`, `uploads` 统计信息

---

## 4. 使用数据库的模块清单

### 4.1 核心模块
1. **db.py** (数据库核心模块)
   - 所有数据库操作函数定义
   - WebSocket 通知函数

2. **aria2_client/client.py**
   - 导入: `get_download_by_id`, `get_download_id_by_gid`, `mark_download_paused`, `mark_download_resumed`
   - 用途: 状态同步

3. **aria2_client/download_handler.py**
   - 导入: `mark_download_completed`, `mark_download_failed`, `mark_download_paused`, `mark_download_resumed`, `get_download_id_by_gid`, `create_upload`, `get_uploads_by_download`, `update_download_progress`
   - 用途: 下载事件处理，状态更新

4. **aria2_client/upload_handler.py**
   - 导入: `check_and_update_download_status_if_file_exists`, `mark_upload_cleaned`, `update_upload_status`, `mark_upload_started`, `mark_upload_completed`, `mark_upload_failed`, `get_upload_by_id`, `increment_upload_retry`
   - 用途: 上传处理，状态更新

### 4.2 Web 服务模块
5. **WebStreamer/server/stream_routes.py**
   - 导入: `init_config_from_yaml`, `fetch_downloads_grouped`, `get_download_statistics`, `delete_all_downloads`, `get_upload_statistics`, `fetch_recent_uploads`, `get_connection`
   - 用途: API 路由，数据查询

6. **WebStreamer/server/ws_manager.py**
   - 用途: WebSocket 连接管理，消息推送

### 4.3 Bot 模块
7. **WebStreamer/bot/plugins/stream_modules/media_processor.py**
   - 导入: `save_tg_media`, `create_download`, `mark_download_started`
   - 用途: 媒体处理，创建下载任务

8. **app.py**
   - 导入: `init_db`
   - 用途: 数据库初始化

9. **configer.py**
   - 导入: `get_config`, `get_all_configs`, `init_config_from_yaml`
   - 用途: 配置管理

---

## 5. 数据一致性保证机制

### 5.1 事务管理
- **上下文管理器**: `db_cursor()` 确保自动提交和关闭连接
- **WAL 模式**: 提升并发性能，减少锁竞争

### 5.2 状态转换规则

#### 下载状态转换
```
pending → downloading → completed
         ↓
       failed
         ↓
       paused → downloading (resume)
```

#### 上传状态转换
```
pending → uploading → completed → cleaned
         ↓
       failed → pending (retry)
         ↓
       cancelled
```

### 5.3 外键约束
- `downloads.file_unique_id` → `tg_media.file_unique_id` (ON DELETE CASCADE)
- `uploads.download_id` → `downloads.id` (ON DELETE CASCADE)
- 确保数据完整性

### 5.4 同步检查点
1. **Aria2 事件**: 立即更新数据库
2. **轮询检查**: 定期同步 aria2 状态与数据库
3. **WebSocket 推送**: 每次数据库更新后推送
4. **上传完成**: 自动更新下载状态

---

## 6. 潜在的数据不一致风险点

### 6.1 已识别风险
1. **Aria2 重启**: 任务丢失，但数据库记录仍存在
   - **处理**: 轮询时检查任务是否存在，允许状态不一致

2. **并发更新**: 多个进程同时更新同一记录
   - **处理**: WAL 模式 + SQLite 事务保证

3. **WebSocket 推送失败**: 数据库已更新但前端未收到通知
   - **处理**: 静默失败，前端通过轮询 API 获取最新状态

### 6.2 建议改进
1. **状态校验**: 定期校验 aria2 状态与数据库状态一致性
2. **重试机制**: WebSocket 推送失败时重试
3. **日志记录**: 记录所有状态变更，便于排查问题

---

## 7. 数据库操作调用链

### 7.1 下载任务生命周期
```
媒体接收 → save_tg_media()
         → create_download()
         → mark_download_started() (onDownloadStart)
         → update_download_progress() (定期更新)
         → mark_download_completed() (onDownloadComplete)
         → create_upload() (如果需要上传)
         → mark_upload_completed() (上传完成)
         → mark_upload_cleaned() (清理完成)
         → mark_download_completed() (最终状态)
```

### 7.2 上传任务生命周期
```
create_upload() (下载完成后)
         → mark_upload_started() (开始上传)
         → update_upload_status() (进度更新)
         → mark_upload_completed() (上传完成)
         → mark_upload_cleaned() (清理完成)
         → check_and_update_download_status_if_file_exists() (更新下载状态)
```

---

## 8. 总结

### 8.1 数据同步机制完整性
✅ **WebSocket 事件监听**: 实时响应 aria2 状态变化
✅ **轮询同步**: 定期检查并同步状态
✅ **WebSocket 推送**: 实时推送状态更新到前端
✅ **外键约束**: 保证数据完整性
✅ **事务管理**: 确保操作原子性

### 8.2 一致性保证
✅ **状态转换**: 有明确的状态转换规则
✅ **同步检查**: 轮询机制确保 aria2 与数据库一致
✅ **错误处理**: 静默失败不影响主流程
✅ **级联删除**: 外键约束确保关联数据一致性

### 8.3 建议
1. 添加状态一致性校验脚本
2. 增强日志记录，便于问题排查
3. 考虑添加数据库备份机制
4. 监控 WebSocket 推送成功率
