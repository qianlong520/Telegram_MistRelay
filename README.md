# Telegram_MistRelay

基于 Telegram 机器人的自动化下载上传系统，整合了文件直链生成和 aria2 下载控制功能

## 📖 项目简介

**Telegram_MistRelay** 是一个功能强大的 Telegram 机器人项目，通过整合两个优秀的开源项目，实现了完整的自动化下载上传流程：

- **直链生成**：基于 [TG-FileStreamBot](https://github.com/rong6/TG-FileStreamBot) 的文件直链功能
- **下载管理**：基于 [MistRelay](https://github.com/Lapis0x0/MistRelay) 的 aria2 下载控制系统
- **自动上传**：集成 rclone 自动上传到 OneDrive

### 🎯 核心功能

1. ✅ **Telegram 文件直链生成** - 为 Telegram 文件生成可访问的直链
2. ✅ **aria2 下载管理** - 支持 HTTP、磁力、种子等多种下载方式
3. ✅ **OneDrive 自动上传** - 下载完成后自动上传到 OneDrive
4. ✅ **实时进度显示** - 美化的下载和上传进度显示
5. ✅ **批量任务处理** - 支持批量添加下载任务
6. ✅ **媒体组支持** - 智能处理 Telegram 媒体组
7. ✅ **Docker 一键部署** - 简单快速的部署方式

## 🚀 快速开始

### 1. 配置文件设置

下载项目到本地：

```bash
git clone https://github.com/qianlong520/Telegram_MistRelay.git
cd Telegram_MistRelay
```

复制示例配置文件并设置参数：

```bash
# 复制配置文件示例
cp db/config.example.yml db/config.yml
cp rclone/rclone.conf.example rclone/rclone.conf
```

然后编辑 `db/config.yml` 文件，填入您的配置信息：

```yaml
# Telegram API 配置
API_ID: xxxx                      # Telegram API ID
API_HASH: xxxxxxxx                # Telegram API Hash
BOT_TOKEN: xxxx:xxxxxxxxxxxx      # Telegram Bot Token
ADMIN_ID: 管理员ID                 # 管理员的Telegram ID
FORWARD_ID: 文件转发目标id          # 可选，文件转发目标ID

# 上传设置
UP_TELEGRAM: false                # 是否上传到电报
UP_ONEDRIVE: true                 # 是否启用rclone上传到OneDrive

# rclone配置
RCLONE_REMOTE: onedrive           # rclone配置的远程名称
RCLONE_PATH: /Downloads           # OneDrive上的目标路径

# aria2c设置（Docker集成后可使用默认值）
RPC_SECRET: xxxxxxx               # RPC密钥（建议修改为自定义密钥）
RPC_URL: localhost:6800/jsonrpc   # 使用Docker部署时必须使用localhost或127.0.0.1

# 直链功能配置
ENABLE_STREAM: true               # 是否启用直链功能
BIN_CHANNEL: -100xxxxxxxxx        # 日志频道ID（必须配置）
SEND_STREAM_LINK: false           # 是否发送直链信息给用户（默认false）
STREAM_AUTO_DOWNLOAD: true        # 是否自动添加到下载队列（仅管理员）
STREAM_ALLOWED_USERS: []          # 允许使用直链功能的用户列表（留空则允许所有人）

# 代理设置（可选）
PROXY_IP:                         # 代理IP，不需要则留空
PROXY_PORT:                       # 代理端口，不需要则留空

# 自动删除本地文件设置
AUTO_DELETE_AFTER_UPLOAD: true    # 是否在成功上传到OneDrive后自动删除本地文件
```

### 2. 配置 rclone

由于 VPS 通常没有图形界面，无法直接完成 OneDrive 的 OAuth 认证流程，建议先在本地电脑上配置 rclone，然后将配置文件上传到项目：

```bash
# 在本地电脑上安装rclone（如果尚未安装）
# Windows: 下载安装包 https://rclone.org/downloads/
# macOS: brew install rclone
# Linux: curl https://rclone.org/install.sh | sudo bash

# 在本地电脑上配置rclone（会打开浏览器进行OneDrive授权）
rclone config

# 配置完成后，在本地找到配置文件
# Windows: %USERPROFILE%\.config\rclone\rclone.conf
# macOS/Linux: ~/.config/rclone/rclone.conf

# 在项目目录中创建rclone目录
mkdir -p rclone

# 将本地的配置文件复制到项目的rclone目录
# 然后将此目录上传到您的VPS
```

配置文件包含敏感的访问令牌，请妥善保管，不要分享给他人。

### 3. 使用 Docker 部署

安装 Docker 和 Docker Compose：

```bash
curl -fsSL get.docker.com -o get-docker.sh && sh get-docker.sh && systemctl enable docker && systemctl start docker
```

构建并启动容器：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f --tail=4000
```

**端口说明**：
- 如果启用了直链功能（`ENABLE_STREAM: true`），Web 服务器默认监听 8080 端口
- 由于使用了 `network_mode: host`，端口会自动映射到主机
- 如果需要修改端口映射，可以在 `docker-compose.yml` 中取消注释 `ports` 部分

### 4. 使用方法

1. 在 Telegram 中找到您的机器人并发送 `/start` 命令
2. 使用 `/help` 查看帮助信息
3. **发送文件给机器人**：机器人会自动生成直链（如果启用）
4. **发送下载链接**：发送 HTTP 链接、磁力链接或种子文件开始下载
5. 使用菜单按钮管理下载任务
6. 使用 `/path` 命令设置下载目录
7. 使用 `/web` 命令获取 ariaNg 在线控制地址

## 📋 命令列表

- `/start` - 开始使用
- `/help` - 查看帮助
- `/info` - 查看系统信息
- `/web` - 获取 ariaNg 在线地址
- `/path [目录]` - 设置下载目录

## 🎮 菜单功能

- ⬇️ 正在下载 - 查看正在下载的任务
- ⌛️ 正在等待 - 查看等待中的任务
- ✅ 已完成/停止 - 查看已完成或停止的任务
- ⏸️ 暂停任务 - 暂停选中的任务
- ▶️ 恢复任务 - 恢复选中的任务
- ❌ 删除任务 - 删除选中的任务
- ❌ ❌ 清空已完成/停止 - 清空所有已完成或停止的任务

## 🔗 直链功能说明

### 工作流程

1. **用户发送文件** → 机器人自动生成直链
2. **自动下载**（可选）：如果启用了 `STREAM_AUTO_DOWNLOAD` 且是管理员，自动添加到下载队列
3. **下载完成** → 自动上传到 OneDrive
4. **上传完成** → 自动删除本地文件（如果启用）

### 支持的文件类型

- 📄 文档（Document）
- 🎥 视频（Video）
- 🎵 音频（Audio）
- 🖼️ 图片（Photo）
- 🎬 动画（Animation/GIF）
- 🎤 语音（Voice）
- 📹 视频笔记（Video Note）
- 🎨 贴纸（Sticker）

### 配置说明

- **BIN_CHANNEL**：必须配置，用于存储文件的日志频道 ID
- **SEND_STREAM_LINK**：是否发送直链信息给用户（默认 `false`）
- **STREAM_AUTO_DOWNLOAD**：是否自动添加到下载队列（默认 `true`，仅管理员）
- **STREAM_ALLOWED_USERS**：允许使用直链功能的用户列表（留空则允许所有人）

## 📊 功能特性

### 下载管理

- ✅ 支持 HTTP/HTTPS、磁力链接、种子文件下载
- ✅ 实时进度显示（每 3 秒更新）
- ✅ 批量添加下载任务
- ✅ 自定义下载目录
- ✅ 任务暂停/恢复/删除
- ✅ 自动重连机制

### 上传功能

- ✅ 自动上传到 OneDrive（通过 rclone）
- ✅ 美化的上传进度显示
- ✅ 上传完成后自动删除本地文件（可选）
- ✅ 上传失败自动重试

### 消息美化

- ✅ 统一的 HTML 格式消息
- ✅ 丰富的 emoji 图标
- ✅ 清晰的进度条显示
- ✅ 详细的文件信息展示

## 🔧 高级配置

### OneDrive 上传速度优化

项目已经针对 OneDrive 上传速度进行了优化，使用了以下 rclone 参数：

- `--transfers 32`: 增加并行传输数量
- `--checkers 16`: 增加并行检查数量
- `--onedrive-chunk-size 64M`: 增加 OneDrive 上传分块大小
- `--buffer-size 64M`: 增加缓冲区大小
- `--drive-pacer-min-sleep 10ms`: 减少 API 请求间隔
- `--drive-pacer-burst 1000`: 增加爆发限制

### 自动删除本地文件

- `AUTO_DELETE_AFTER_UPLOAD`: 设置为 `true` 时，文件成功上传到 OneDrive 后会自动删除本地文件
- 只有在文件成功上传后才会删除本地文件
- 如果上传失败或中断，本地文件会保留

## 📝 更新项目

当有新版本发布时，您可以按照以下步骤更新项目：

```bash
# 1. 备份配置文件
cp db/config.yml db/config.yml.backup
cp rclone/rclone.conf rclone/rclone.conf.backup

# 2. 拉取最新代码
git pull

# 3. 重新构建并启动容器
docker compose down
docker compose up -d --build

# 4. 检查日志
docker compose logs -f
```

## 🙏 致谢

本项目整合了以下优秀的开源项目：

1. **[TG-FileStreamBot](https://github.com/rong6/TG-FileStreamBot)** - 文件直链生成功能
   - 原作者：[@rong6](https://github.com/rong6)
   - 功能：为 Telegram 文件生成可访问的直链

2. **[MistRelay](https://github.com/Lapis0x0/MistRelay)** - aria2 下载控制系统
   - 原作者：[@Lapis0x0](https://github.com/Lapis0x0)
   - 功能：基于 Telegram Bot 的 aria2 下载管理

3. **其他参考项目**：
   - [tele-aria2](https://github.com/HouCoder/tele-aria2)
   - [aria2bot](https://github.com/jw-star/aria2bot)

## 📄 许可证

本项目采用 [GPL-3.0](LICENSE) 许可证。

## 🗺️ 项目结构

```
Telegram_MistRelay/
├── WebStreamer/          # 直链功能模块（基于 TG-FileStreamBot）
│   ├── bot/              # Bot 相关代码
│   ├── server/           # Web 服务器
│   └── utils/            # 工具函数
├── async_aria2_client.py  # aria2 客户端（基于 MistRelay）
├── app.py                # 主应用入口
├── configer.py           # 配置管理
├── db/                   # 配置文件目录
│   └── config.yml        # 主配置文件
├── rclone/               # rclone 配置目录
├── docker-compose.yml     # Docker Compose 配置
├── Dockerfile            # Docker 镜像构建文件
└── README.md             # 项目说明文档
```

## 🎯 版本历史

### v1.0.0 (2026-01-22)

**第一版发布** - 整合两个项目的核心功能

- ✅ 整合 TG-FileStreamBot 的文件直链功能
- ✅ 整合 MistRelay 的 aria2 下载管理功能
- ✅ 集成 rclone 自动上传到 OneDrive
- ✅ 实现美化的消息格式
- ✅ 支持媒体组处理
- ✅ 实现自动删除本地文件功能
- ✅ Docker 一键部署支持
- ✅ 完整的文档和配置说明

## 🔮 未来计划

- [ ] 支持重命名文件
- [ ] 更清晰、强大的菜单键
- [ ] 支持通过大模型来自动管理文件列表
- [ ] 优化直链功能的性能
- [ ] 支持更多云存储服务（Google Drive、Dropbox 等）
- [ ] 添加文件预览功能
- [ ] 支持文件搜索功能

## 📞 问题反馈

如果您在使用过程中遇到问题，欢迎提交 Issue：

- GitHub Issues: [https://github.com/qianlong520/Telegram_MistRelay/issues](https://github.com/qianlong520/Telegram_MistRelay/issues)

---

**⭐ 如果这个项目对您有帮助，欢迎 Star！**
