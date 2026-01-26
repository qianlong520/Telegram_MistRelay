# 开发脚本说明

本目录包含MistRelay项目的开发辅助脚本。

## 脚本列表

### 1. start-dev.sh
**用途**: 一键启动开发环境  
**功能**:
- 启动Docker后端服务
- 启动前端开发服务器(Vite)
- 同时运行前后端,方便开发调试

**使用方法**:
```bash
./dev-scripts/start-dev.sh
```

---

### 2. build-frontend.sh
**用途**: 构建前端并重启Docker  
**功能**:
- 构建前端生产版本
- 自动重启Docker容器以应用更改

**使用方法**:
```bash
./dev-scripts/build-frontend.sh
```

---

### 3. watch-backend.sh
**用途**: 监听后端代码变化  
**功能**:
- 监听Python后端文件变化
- 自动重启Docker容器
- 提高开发效率

**使用方法**:
```bash
./dev-scripts/watch-backend.sh
```

---

## 生产环境

生产环境请使用根目录的标准Docker命令:

```bash
# 构建并启动
docker compose up -d --build

# 停止
docker compose down

# 查看日志
docker compose logs -f
```

根目录的 `start.sh` 是Docker容器内部使用的启动脚本,无需手动执行。
