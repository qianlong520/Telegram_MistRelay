#!/bin/bash

# 前端构建脚本 - 构建后自动重启Docker容器

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
echo -e "${BLUE}  前端构建脚本${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查参数
AUTO_RELOAD=${1:-true}  # 默认自动重载
SKIP_BUILD=${2:-false}  # 是否跳过构建

# 1. 构建前端
if [ "$SKIP_BUILD" != "true" ]; then
    echo -e "${BLUE}[1/2] 构建前端...${NC}"
    cd web
    
    # 检查依赖是否已安装
    if [ ! -d "node_modules" ]; then
        echo -e "${YELLOW}依赖未安装，正在安装...${NC}"
        npm install
    fi
    
    echo -e "${GREEN}开始构建前端...${NC}"
    npm run build
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 前端构建成功${NC}"
    else
        echo -e "${RED}✗ 前端构建失败${NC}"
        exit 1
    fi
    
    cd ..
else
    echo -e "${YELLOW}跳过构建步骤${NC}"
fi

# 2. 重启Docker容器（如果启用）
if [ "$AUTO_RELOAD" = "true" ]; then
    echo ""
    echo -e "${BLUE}[2/2] 重启Docker容器...${NC}"
    
    # 检查Docker是否运行
    if ! docker ps &> /dev/null; then
        echo -e "${YELLOW}Docker未运行，跳过容器重启${NC}"
        exit 0
    fi
    
    # 检查容器是否存在
    if docker ps -a --format '{{.Names}}' | grep -q "^mistrelay$"; then
        echo -e "${GREEN}重启Docker容器...${NC}"
        docker-compose restart 2>/dev/null || docker compose restart
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ Docker容器重启成功${NC}"
            echo ""
            echo -e "${YELLOW}提示: 查看容器日志: ${BLUE}docker-compose logs -f${NC}"
        else
            echo -e "${RED}✗ Docker容器重启失败${NC}"
            exit 1
        fi
    else
        echo -e "${YELLOW}容器不存在，请先启动: ${BLUE}docker-compose up -d${NC}"
    fi
else
    echo -e "${YELLOW}自动重载已禁用，跳过容器重启${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  构建完成！${NC}"
echo -e "${GREEN}========================================${NC}"
