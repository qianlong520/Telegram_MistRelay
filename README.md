# MistRelay

基于 Telegram 机器人的 aria2 下载控制系统，支持 OneDrive 自动上传，并集成了文件直链功能。

## ✨ 功能特点

### 核心功能
- **Telegram 控制**: 基于电报机器人控制 aria2，支持任务管理。
- **自动上传**: 下载完成后通过 rclone 自动上传到 OneDrive。
- **数据完整性保障**: 
  - 下载文件大小校验（与 aria2 报告对比）。
  - OneDrive 上传后远程文件校验（存在性 + 大小 + MD5）。
  - 校验失败自动重试（最多3次）。
  - 确保数据安全，防止数据丢失。
- **文件直链**: 整合 [TG-FileStreamBot](https://github.com/rong6/TG-FileStreamBot)，为 Telegram 文件生成可访问的直链。
- **下载管理**:
  - 支持 HTTP/HTTPS、磁力链接、种子文件下载。
  - 支持批量添加任务。
  - 支持自定义下载目录。
  - 实时进度显示（Bot 消息 & Web 界面）。
  - 任务暂停/恢复/删除/自动重连。
  - **智能文件过滤**: 支持跳过小于指定大小的媒体文件（可配置最小文件大小）。
- **Web 管理界面**: 
  - 集成 AriaNg 和自定义系统管理页面。
  - 实时日志流（WebSocket）支持，无需刷新即可查看容器日志。
  - 下载记录管理，支持查看跳过文件状态。
- **部署友好**: Docker 一键部署，集成 aria2、rclone 和前端。
- **性能优化**: 
  - 上传操作完全异步化，不阻塞 API 响应。
  - 支持配置热重载，无需重启服务。

## 🚀 快速开始

### 1. 配置文件设置

下载项目到本地：

```bash
git clone https://github.com/Lapis0x0/MistRelay.git
cd MistRelay
```

重命名 `db/config.example.yml` 为 `config.yml` 并设置参数（详细配置见文件内注释）：

```yaml
API_ID: xxxx                      # Telegram API ID
API_HASH: xxxxxxxx                # Telegram API Hash
BOT_TOKEN: xxxx:xxxxxxxxxxxx      # Telegram Bot Token
ADMIN_ID: management_id           # 管理员 Telegram ID

# 下载配置
SKIP_SMALL_FILES: false          # 是否跳过小于指定大小的媒体文件
MIN_FILE_SIZE_MB: 100            # 最小文件大小（MB），小于此大小的文件将被跳过

# ... 其他配置 ...
```

### 2. 配置 Rclone

由于 VPS 通常没有图形界面，建议在本地配置 rclone 后上传配置文件：

1.  **本地配置**: 在本地电脑运行 `rclone config` 完成 OneDrive 授权。
2.  **上传配置**: 将本地生成的 `rclone.conf` 复制到项目的 `rclone/` 目录下。

```bash
# 示例：创建目录并上传
mkdir -p rclone
# 将 rclone.conf 放入此目录
```

### 3. Docker 部署 (生产环境)

MistRelay 使用 Docker Compose 进行一键部署，集成了前后端和所有依赖。

```bash
# 构建并启动服务
docker compose up -d --build

# 查看日志
docker compose logs -f --tail=100
```

**端口说明**:
- **Web 界面**: `http://your-server:8080` (端口映射可在 `docker-compose.yml` 中修改)
- **API 接口**: `http://your-server:8080/api/*`

### 4. 访问服务

启动后，访问 `http://your-server:8080` 即可使用 Web 管理界面。
- **AriaNg**: 用于管理 Aria2 下载任务。
- **系统管理**: `http://your-server:8080/system` 用于管理 Docker 容器状态。

## 📖 使用指南

### Telegram Bot 命令
- `/start` - 开始使用
- `/help` - 查看帮助
- `/info` - 查看系统信息
- `/web` - 获取 Web 控制台地址
- `/path [目录]` - 设置下载目录

### 菜单功能
- **正在下载/等待/已完成**: 查看各状态的任务列表。
- **暂停/恢复/删除**: 管理选中任务。

### 文件直链功能
默认启用（可配置）。
1. **使用**: 发送或转发文件给 Bot。
2. **结果**: Bot 会返回文件的直链地址（支持文档、视频、音频等）。
3. **自动下载**: 
   - 若开启 `STREAM_AUTO_DOWNLOAD: true`，管理员发送的文件会自动加入 Aria2 下载队列。
   - 需配置 `BIN_CHANNEL` 以确保日志存储正常。

### 快捷提示
- **OneDrive 上传优化**: 项目默认配置了优化参数（如 `--transfers 4`, `--checkers 8`, `--buffer-size 64M` 等）以提升速度。
- **自动删除**: 配置 `AUTO_DELETE_AFTER_UPLOAD: true` 可在上传成功后自动清理本地文件。
- **跳过小文件**: 
  - 配置 `SKIP_SMALL_FILES: true` 启用跳过小文件功能。
  - 配置 `MIN_FILE_SIZE_MB: 100` 设置最小文件大小（默认 100MB）。
  - 小于指定大小的文件会被静默跳过，不会下载和上传。
  - 可在下载页面查看被跳过的文件状态。

## 🛠 系统管理模块

系统管理模块 (`/system`) 提供 Docker 容器的实时监控与控制。

### 功能
- **状态查看**: 实时查看容器运行状态、镜像信息。
- **热重载**: 支持通过 Web 界面一键重启容器 (Restart Container)。
- **日志查看**: 
  - 支持 HTTP 方式获取历史日志（支持筛选行数：50/100/200/500）。
  - **WebSocket 实时日志流**: 点击播放按钮开启实时日志流，自动推送最新日志，无需手动刷新。
  - 支持清空日志显示。

### 配置要求
系统管理模块依赖于 Docker Socket 挂载 (已在 `docker-compose.yml` 默认配置):
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

## 💻 开发者指南

如果您想参与开发或进行二次开发，请参考以下信息。

### 架构概述
- **后端**: Python + aiohttp (Port 8080)
- **前端**: Vue3 + Vite + Element Plus (Dev Port 5173)

### 开发模式启动
使用 `start-dev.sh` 脚本可一键启动前后端分离的开发环境：

```bash
./start-dev.sh
```

此模式下：
- 前端支持 HMR (热重载)。
- API 请求会自动代理到后端容器。
- 访问 `http://localhost:5173` 进行开发。

### 生产构建原理
Dockerfile 使用多阶段构建：
1. `node` 阶段构建前端静态资源 (`dist` 目录)。
2. `python` 阶段通过 aiohttp 提供 API 服务，并将 `/` 路由指向前端 `index.html`。

## 📝 更新日志

### [1.2.0] - 2026-01-26 (功能增强与性能优化)
- **🎯 智能文件过滤**:
  - 新增跳过小文件功能，可配置最小文件大小（默认 100MB）。
  - 在添加下载任务前检查文件大小，避免不必要的下载。
  - 下载页面显示跳过状态和统计信息。
  - 静默处理，不发送通知消息。
- **⚡ 性能优化**:
  - 上传操作完全异步化，使用 `asyncio.create_subprocess_exec` 替代阻塞的 `subprocess.Popen`。
  - API 响应不再被上传操作阻塞，提升系统响应速度。
  - 支持配置热重载，修改配置后无需重启服务。
- **📊 Web 管理界面增强**:
  - 新增 WebSocket 实时日志流功能，无需刷新即可查看最新日志。
  - 支持开始/停止实时日志流。
  - 支持清空日志显示。
  - 下载页面适配显示跳过文件状态。
- **🔧 代码优化**:
  - 修复 `asyncio.subprocess.Process` 的 `poll()` 方法错误。
  - 优化异步日志读取，避免阻塞事件循环。

### [1.1.0] - 2026-01-26 (数据完整性增强)
- **🔒 数据安全**:
  - 新增下载文件大小校验（与 aria2 totalLength 对比）。
  - 新增 OneDrive 上传后远程文件校验（存在性 + 大小）。
  - 新增 MD5 哈希校验（可选，提供字节级完整性保证）。
  - 新增自动重试机制（校验失败时自动重试最多3次）。
- **🛡️ 防护机制**:
  - 校验失败时保留本地文件，防止数据丢失。
  - 智能降级策略（MD5 不可用时降级为大小校验）。
  - 详细的错误日志和用户通知。

### [1.0.0] - 2026-01-22 (首个发行版)
- **🎉 发布**: 整合了 [MistRelay](https://github.com/Lapis0x0/MistRelay) 和 [TG-FileStreamBot](https://github.com/rong6/TG-FileStreamBot)。
- **✨ 新增**:
  - 完整的 Aria2 + Rclone 自动化流程。
  - 统一的 Web UI。
  - Docker 容器集成与系统管理功能。
  - 消息美化与实时进度展示。

## 🗓 未来计划
- [ ] 支持文件重命名
- [ ] 优化菜单交互 (更清晰的键盘布局)
- [ ] 引入大模型 (LLM) 自动整理文件列表
- [ ] 更多云存储服务支持
- [ ] 文件预览与搜索功能

## 🙏 致谢
本项目整合了以下优秀的开源项目：
- [TG-FileStreamBot](https://github.com/rong6/TG-FileStreamBot) - 文件直链生成
- [MistRelay](https://github.com/Lapis0x0/MistRelay) - Aria2 下载控制
- [HouCoder/tele-aria2](https://github.com/HouCoder/tele-aria2)
- [jw-star/aria2bot](https://github.com/jw-star/aria2bot)
