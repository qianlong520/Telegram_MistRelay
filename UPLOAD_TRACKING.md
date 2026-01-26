# 上传追踪表使用指南

## 概述

新增 `uploads` 表用于追踪上传任务，**核心功能是区分下载失败和代码错误导致的上传失败**。

## 快速开始

### 1. 创建上传任务

```python
import db

upload_id = db.create_upload(
    download_id=123,              # 关联的下载任务 ID
    upload_target='onedrive',     # 上传目标：onedrive/telegram/other
    remote_path='/videos/file.mp4' # 远程路径（可选）
)
```

### 2. 更新上传状态

```python
# 开始上传
db.mark_upload_started(upload_id)

# 更新进度
db.update_upload_status(
    upload_id,
    status='uploading',
    uploaded_size=5000000,
    upload_speed=500000
)

# 完成
db.mark_upload_completed(upload_id, remote_path='/videos/file.mp4')
```

### 3. 标记失败（关键）

**下载失败导致上传失败**：
```python
db.mark_upload_failed(
    upload_id,
    failure_reason='download_failed',  # 明确标记是下载失败
    error_message='Download incomplete'
)
```

**代码错误导致上传失败**：
```python
db.mark_upload_failed(
    upload_id,
    failure_reason='code_error',  # 明确标记是代码错误
    error_message='AttributeError: ...'
)
```

### 4. 查询和统计

```python
# 查询上传记录
upload = db.get_upload_by_id(upload_id)

# 获取某个下载的所有上传
uploads = db.get_uploads_by_download(download_id)

# 统计失败原因（核心功能）
failure_stats = db.count_uploads_by_failure_reason()
# 返回: {'download_failed': 10, 'code_error': 5, ...}

# 完整统计
stats = db.get_upload_statistics()
```

## 失败原因分类

| 原因 | 说明 |
|------|------|
| `download_failed` | 下载阶段失败（源头问题） |
| `code_error` | 代码逻辑错误 |
| `network_error` | 网络错误 |
| `auth_error` | 认证失败 |
| `quota_exceeded` | 配额超限 |
| `timeout` | 超时 |

## 完整示例

参见 [upload_example.py](file:///root/MistRelay-dev/upload_example.py)

## 数据迁移

如果已有数据在 `downloads` 表中：

```python
db.migrate_upload_data()
```

## 核心优势

✓ 精确区分失败原因（下载失败 vs 代码错误）  
✓ 支持多目标上传（一个下载对应多个上传）  
✓ 详细追踪上传进度和速度  
✓ 支持重试逻辑  
✓ 多维度统计分析
