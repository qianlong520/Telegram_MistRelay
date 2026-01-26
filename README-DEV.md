# MistRelay 开发模式启动指南

## 概述

本项目支持两种部署模式:

### 开发环境(前后端分离)
- **后端**: Python + aiohttp,运行在Docker容器中(端口8080)
- **前端**: Vue3 + Vite,独立运行(端口5173)
- **优势**: 支持热重载,开发体验好

### 生产环境(前端集成)
- **后端**: Python + aiohttp,运行在Docker容器中(端口8080)
- **前端**: 已通过多阶段构建集成到Docker镜像中
- **访问**: 直接访问 `http://your-server:8080` 即可使用Web界面
- **优势**: 单容器部署,简单方便

## 快速开始

### 前置要求

1. **Docker** 和 **Docker Compose**
2. **Node.js** (推荐 v18+)
3. **npm** 或 **yarn**

### 一键启动

```bash
./start-dev.sh
```

脚本会自动：
1. 检查依赖环境
2. 启动Docker后端服务
3. 安装前端依赖（如需要）
4. 启动前端开发服务器

### 手动启动

#### 1. 启动后端服务

```bash
# 构建并启动Docker容器
docker-compose up -d --build

# 查看日志
docker-compose logs -f
```

#### 2. 启动前端开发服务器

```bash
cd web
npm install  # 首次运行需要安装依赖
npm run dev
```

## 服务地址

- **前端开发服务器**: http://localhost:5173
- **后端API服务**: http://localhost:8080
- **API状态接口**: http://localhost:8080/api/status

## 开发说明

### 前端开发

前端使用Vite开发服务器，支持：
- 热模块替换（HMR）
- API请求自动代理到后端（`/api` -> `http://localhost:8080/api`）
- TypeScript支持
- Tailwind CSS + Element Plus

### 后端开发

后端运行在Docker容器中：
- 修改代码后需要重启容器：`docker-compose restart`
- 或者重新构建：`docker-compose up -d --build`

### API代理配置

前端开发服务器的API代理配置在 `web/vite.config.ts`：

```typescript
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8080',
      changeOrigin: true,
      secure: false
    }
  }
}
```

## 停止服务

### 使用一键脚本启动的

按 `Ctrl+C` 会自动停止所有服务。

### 手动停止

```bash
# 停止前端（在运行前端的终端按 Ctrl+C）

# 停止后端
docker-compose down
```

## 生产环境部署

生产环境部署请参考主 README.md，使用Docker构建包含前端的完整镜像。

## 常见问题

### 1. 端口被占用

如果8080或5173端口被占用，可以：

**修改后端端口**（docker-compose.yml）:
```yaml
ports:
  - "8081:8080"  # 主机端口:容器端口
```

**修改前端端口**（web/vite.config.ts）:
```typescript
server: {
  port: 5174,  // 修改为其他端口
}
```

### 2. Docker容器启动失败

检查日志：
```bash
docker-compose logs
```

### 3. 前端无法连接后端API

确保：
- 后端服务已启动：`docker-compose ps`
- 后端端口正确：`curl http://localhost:8080/api/status`
- 前端代理配置正确（`web/vite.config.ts`）

## 生产环境部署

生产环境使用单容器部署,前端已集成到Docker镜像中:

```bash
# 构建生产镜像
docker compose up -d --build

# 访问Web界面
# http://your-server:8080
```

**工作原理**:
1. Dockerfile 使用多阶段构建,先用 Node.js 构建前端
2. 前端 `dist` 目录被复制到最终镜像的 `/app/web/dist`
3. 后端 aiohttp 服务器提供静态文件服务
4. 访问根路径 `/` 返回前端 `index.html`
5. `/api/*` 路径提供 API 接口
6. `/assets/*` 路径提供静态资源
7. 其他路径通过 SPA 回退返回 `index.html`

**注意事项**:
- 生产环境无需单独运行前端开发服务器
- 修改前端代码后需要重新构建镜像
- 开发时仍然使用 `./start-dev.sh` 启动前后端分离模式
