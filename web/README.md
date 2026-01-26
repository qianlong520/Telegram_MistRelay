# MistRelay Web 前端

基于 Vue3 + TypeScript + Tailwind CSS + Element Plus 的 MistRelay 下载机器人 Web 管理界面。

## 技术栈

- **Vue 3** - 渐进式 JavaScript 框架
- **TypeScript** - 类型安全的 JavaScript
- **Vue Router 4** - 官方路由管理器
- **Pinia** - 状态管理
- **Element Plus** - Vue 3 组件库
- **Tailwind CSS** - 实用优先的 CSS 框架
- **VueUse** - Vue Composition API 工具集
- **Axios** - HTTP 客户端
- **Vite** - 下一代前端构建工具

## 开发规范

本项目遵循以下开发规范：

### 代码风格

- 使用 TypeScript 编写所有代码
- 使用 Composition API `<script setup>` 语法
- 使用函数式编程，避免类
- 使用描述性变量名（如 `isLoading`, `hasError`）
- 使用 named exports

### 目录结构

- 使用小写加横线命名目录（如 `components/auth-wizard`）
- 文件组织：每个文件只包含相关内容

### UI 和样式

- 使用 Element Plus 组件
- 使用 Tailwind CSS 进行样式设计
- 响应式设计，移动端优先

### 性能优化

- 使用 VueUse 函数增强响应性和性能
- 使用 Suspense 包装异步组件
- 动态加载非关键组件
- Vite 构建时进行代码分割

## 开发

### 安装依赖

```bash
npm install
```

### 开发模式

```bash
npm run dev
```

### 类型检查

```bash
npm run type-check
```

### 构建生产版本

```bash
npm run build
```

构建产物将输出到 `dist/` 目录，并自动进行代码分割优化。

## API 接口

前端通过以下 API 接口与后端通信：

- `GET /api/status` - 获取服务器状态
- `GET /api/downloads?limit=100` - 获取下载记录

## 路由

- `/` - 首页
- `/status` - 系统状态页面
- `/downloads` - 下载记录页面

## 项目结构

```
src/
├── api/              # API 服务
├── components/       # 组件
│   ├── layout/      # 布局组件
│   └── common/      # 通用组件
├── router/          # 路由配置
├── stores/          # Pinia 状态管理
├── types/           # TypeScript 类型定义
├── utils/           # 工具函数
└── views/           # 页面组件
```

## 特性

- 📊 **系统状态** - 查看服务器运行状态、机器人信息和负载情况
- 📥 **下载记录** - 查看和管理所有下载任务记录
- 🎨 **现代化UI** - 使用 Element Plus 和 Tailwind CSS 构建的美观界面
- 📱 **响应式设计** - 完美适配各种屏幕尺寸
- ⚡ **性能优化** - 代码分割、懒加载等优化策略
- 🔒 **类型安全** - 完整的 TypeScript 类型支持
