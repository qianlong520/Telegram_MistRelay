# 系统管理模块使用说明

## 功能概述

系统管理模块提供了Docker容器的管理和控制功能，包括：

- **容器状态查看**：实时查看Docker容器的运行状态、镜像信息等
- **热重载控制**：一键重启Docker容器，实现热重载
- **日志查看**：查看容器运行日志，支持自定义行数

## 前置要求

### 1. Docker Socket 挂载

为了在容器内控制Docker，需要挂载Docker socket。`docker-compose.yml` 已配置：

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

### 2. Docker CLI 可用性

容器内需要能够访问Docker CLI。有两种方式：

#### 方式一：使用主机Docker CLI（推荐）

如果主机已安装Docker，挂载socket后即可使用。确保：
- 主机已安装Docker CLI
- Socket权限正确（通常需要root或docker组权限）

#### 方式二：在容器内安装Docker CLI

如果需要，可以在Dockerfile中添加：

```dockerfile
RUN apt-get update && apt-get install -y docker.io
```

**注意**：这会使镜像变大，不推荐。

## 使用方法

### 1. 启动服务

确保 `docker-compose.yml` 中已挂载Docker socket：

```bash
docker-compose up -d --build
```

### 2. 访问系统管理页面

打开浏览器访问：`http://localhost:5173/system`

### 3. 功能说明

#### 查看容器状态

- 页面会自动加载容器状态
- 显示容器名称、运行状态、镜像信息等
- 点击刷新按钮可手动刷新状态

#### 重启容器（热重载）

1. 点击"重启容器（热重载）"按钮
2. 确认重启操作
3. 等待容器重启完成（约5-10秒）
4. 状态会自动刷新

**注意**：
- 重启会导致服务短暂中断
- 重启后需要等待几秒钟服务才能完全恢复
- 如果重启失败，请检查Docker socket权限

#### 查看容器日志

- 选择要查看的日志行数（50/100/200/500）
- 点击刷新按钮获取最新日志
- 日志以深色背景显示，便于阅读

## API接口

### 获取容器状态

```http
GET /api/system/docker/status
```

响应示例：
```json
{
  "success": true,
  "in_docker": true,
  "container_name": "mistrelay",
  "status": "running",
  "image": "mistrelay:latest",
  "created": "2024-01-01T00:00:00Z"
}
```

### 重启容器

```http
POST /api/system/docker/restart
```

响应示例：
```json
{
  "success": true,
  "message": "容器 mistrelay 重启成功",
  "container_name": "mistrelay"
}
```

### 获取容器日志

```http
GET /api/system/docker/logs?lines=100
```

响应示例：
```json
{
  "success": true,
  "logs": "...",
  "lines": 100
}
```

## 安全注意事项

⚠️ **重要安全提示**：

1. **Docker Socket权限**：挂载Docker socket意味着容器内可以完全控制Docker，包括：
   - 启动/停止/删除容器
   - 访问主机文件系统
   - 创建特权容器

2. **生产环境建议**：
   - 仅在受信任的环境中使用
   - 考虑使用Docker API的访问控制
   - 限制容器网络访问
   - 定期审查日志

3. **权限最小化**：
   - 如果可能，使用非root用户运行容器
   - 限制Docker socket的访问权限
   - 使用Docker API的认证机制

## 故障排查

### 问题1：无法获取容器状态

**症状**：页面显示"无法获取容器状态"

**解决方案**：
1. 检查Docker socket是否已挂载：`docker exec mistrelay ls -la /var/run/docker.sock`
2. 检查Docker CLI是否可用：`docker exec mistrelay docker --version`
3. 检查容器名称是否正确：查看 `HOSTNAME` 环境变量

### 问题2：重启操作失败

**症状**：点击重启后显示错误

**解决方案**：
1. 检查Docker socket权限：确保容器有权限访问socket
2. 检查容器名称：确保 `HOSTNAME` 环境变量正确
3. 查看后端日志：`docker-compose logs`

### 问题3：日志无法显示

**症状**：日志区域显示为空

**解决方案**：
1. 检查容器是否正在运行
2. 尝试减少日志行数
3. 检查后端日志是否有错误信息

## 开发说明

### 后端实现

后端API实现在 `WebStreamer/server/stream_routes.py`：

- `docker_status_handler`: 获取容器状态
- `docker_restart_handler`: 重启容器
- `docker_logs_handler`: 获取容器日志

### 前端实现

前端页面在 `web/src/views/system.vue`：

- 使用Element Plus组件构建UI
- 通过Axios调用后端API
- 实时更新容器状态和日志

## 未来改进

- [ ] 添加容器健康检查
- [ ] 支持查看多个容器
- [ ] 添加容器资源使用监控
- [ ] 支持容器配置修改
- [ ] 添加操作历史记录
