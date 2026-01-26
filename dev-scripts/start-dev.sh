#!/bin/bash

# MistRelay 一键启动脚本（开发模式）
# 同时启动Docker后端服务和前端开发服务器

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  MistRelay 一键启动脚本（开发模式）${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: 未找到Docker，请先安装Docker${NC}"
    exit 1
fi

# 检查Docker Compose是否安装
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}错误: 未找到Docker Compose，请先安装Docker Compose${NC}"
    exit 1
fi

# 检查Node.js是否安装
if ! command -v node &> /dev/null; then
    echo -e "${RED}错误: 未找到Node.js，请先安装Node.js${NC}"
    exit 1
fi

# 检查npm是否安装
if ! command -v npm &> /dev/null; then
    echo -e "${RED}错误: 未找到npm，请先安装npm${NC}"
    exit 1
fi

# 清理函数
cleanup() {
    echo ""
    echo -e "${YELLOW}正在清理资源...${NC}"
    # 停止前端开发服务器
    if [ ! -z "$FRONTEND_PID" ]; then
        echo -e "${YELLOW}停止前端开发服务器 (PID: $FRONTEND_PID)${NC}"
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    # 停止Docker容器
    echo -e "${YELLOW}停止Docker容器...${NC}"
    docker-compose down 2>/dev/null || docker compose down 2>/dev/null || true
    echo -e "${GREEN}清理完成${NC}"
    exit 0
}

# 注册清理函数
trap cleanup SIGINT SIGTERM EXIT

# 1. 启动Docker后端服务
echo -e "${BLUE}[1/2] 启动Docker后端服务...${NC}"
if docker-compose ps | grep -q "mistrelay.*Up" || docker compose ps | grep -q "mistrelay.*Up"; then
    echo -e "${YELLOW}后端服务已在运行中${NC}"
else
    echo -e "${GREEN}构建并启动Docker容器...${NC}"
    docker-compose up -d --build 2>/dev/null || docker compose up -d --build
    
    # 等待容器启动
    echo -e "${YELLOW}等待后端服务启动...${NC}"
    sleep 5
    
    # 检查容器状态
    if docker-compose ps | grep -q "mistrelay.*Up" || docker compose ps | grep -q "mistrelay.*Up"; then
        echo -e "${GREEN}✓ 后端服务启动成功${NC}"
    else
        echo -e "${RED}✗ 后端服务启动失败，请检查日志: docker-compose logs${NC}"
        exit 1
    fi
fi

# 2. 启动前端开发服务器
echo ""
echo -e "${BLUE}[2/2] 启动前端开发服务器...${NC}"

# 检查前端依赖是否已安装
if [ ! -d "web/node_modules" ]; then
    echo -e "${YELLOW}前端依赖未安装，正在安装...${NC}"
    cd web
    npm install
    cd ..
fi

# 启动前端开发服务器
cd web
echo -e "${GREEN}启动Vite开发服务器...${NC}"
npm run dev &
FRONTEND_PID=$!
cd ..

# 等待前端服务器启动
sleep 3

# 检查前端服务器是否启动成功
if ps -p $FRONTEND_PID > /dev/null; then
    echo -e "${GREEN}✓ 前端开发服务器启动成功 (PID: $FRONTEND_PID)${NC}"
else
    echo -e "${RED}✗ 前端开发服务器启动失败${NC}"
    exit 1
fi

# 显示服务信息
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  服务启动成功！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}后端API服务:${NC} http://localhost:8080"
echo -e "${BLUE}前端开发服务器:${NC} http://localhost:5173"
echo ""
echo -e "${YELLOW}提示:${NC}"
echo -e "  - 前端会自动代理API请求到后端"
echo -e "  - 按 Ctrl+C 停止所有服务"
echo -e "  - 查看后端日志: ${BLUE}docker-compose logs -f${NC}"
echo ""

# 等待用户中断
wait $FRONTEND_PID
