#!/bin/bash

# 后端文件监听脚本 - 监听后端代码变化并自动重启Docker容器

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
echo -e "${BLUE}  后端文件监听脚本（热重载）${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查inotify-tools是否安装
if ! command -v inotifywait &> /dev/null; then
    echo -e "${YELLOW}未找到inotifywait，正在安装inotify-tools...${NC}"
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y inotify-tools
    elif command -v yum &> /dev/null; then
        sudo yum install -y inotify-tools
    else
        echo -e "${RED}无法自动安装inotify-tools，请手动安装${NC}"
        exit 1
    fi
fi

# 清理函数
cleanup() {
    echo ""
    echo -e "${YELLOW}停止文件监听...${NC}"
    kill $INOTIFY_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# 监听的文件和目录
WATCH_DIRS=(
    "app.py"
    "async_aria2_client.py"
    "configer.py"
    "db.py"
    "util.py"
    "WebStreamer/"
    "start.sh"
)

# 排除的文件模式
EXCLUDE_PATTERNS="\.pyc$|__pycache__|\.git|\.db$|node_modules|dist|\.log$"

echo -e "${GREEN}开始监听以下文件/目录的变化:${NC}"
for dir in "${WATCH_DIRS[@]}"; do
    echo -e "  - ${BLUE}$dir${NC}"
done
echo ""
echo -e "${YELLOW}提示: 按 Ctrl+C 停止监听${NC}"
echo ""

# 文件变化处理函数
handle_change() {
    local file=$1
    local event=$2
    
    echo ""
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] 检测到变化: ${BLUE}$file${NC} (事件: $event)"
    
    # 检查Docker容器是否运行
    if ! docker ps --format '{{.Names}}' | grep -q "^mistrelay$"; then
        echo -e "${RED}容器未运行，跳过重启${NC}"
        return
    fi
    
    echo -e "${GREEN}重启Docker容器...${NC}"
    docker-compose restart 2>/dev/null || docker compose restart
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 容器重启成功${NC}"
    else
        echo -e "${RED}✗ 容器重启失败${NC}"
    fi
    
    echo ""
}

# 构建inotifywait命令
INOTIFY_CMD="inotifywait -m -r -e modify,create,delete,move"

# 添加监听目录
for dir in "${WATCH_DIRS[@]}"; do
    if [ -e "$dir" ]; then
        INOTIFY_CMD="$INOTIFY_CMD '$dir'"
    fi
done

# 启动监听（使用后台进程）
(
    while true; do
        # 使用find和inotifywait组合来监听多个目录
        for dir in "${WATCH_DIRS[@]}"; do
            if [ -e "$dir" ]; then
                inotifywait -q -r -e modify,create,delete,move --format '%w%f %e' "$dir" 2>/dev/null | while read file event; do
                    # 排除不需要的文件
                    if echo "$file" | grep -qE "$EXCLUDE_PATTERNS"; then
                        continue
                    fi
                    handle_change "$file" "$event"
                done &
            fi
        done
        wait
    done
) &
INOTIFY_PID=$!

# 等待
wait $INOTIFY_PID
