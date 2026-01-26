# 阶段1: 构建前端
FROM node:20-slim AS frontend-builder

WORKDIR /app/web

# 复制 package.json 和 package-lock.json
COPY web/package*.json ./

# 安装依赖（仅生产依赖）
RUN npm ci --only=production

# 复制前端源码
COPY web/ ./

# 构建前端
RUN npm run build

# 阶段2: Python 依赖构建
FROM python:3.11-slim-bookworm AS build

# 安装编译工具（TgCrypto需要编译）
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file first to leverage Docker cache if it hasn't changed
COPY requirements.txt /app/requirements.txt

# Install dependencies in a temporary container
RUN python -m pip install --upgrade pip && \
    pip3 --no-cache-dir install --user -r /app/requirements.txt

FROM python:3.11-slim-bookworm

# 安装必要的工具和依赖（合并所有apt-get命令以减少层数）
# 注意：使用 Docker Python SDK 代替 Docker CLI，更可靠且不需要安装二进制文件
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    gnupg2 \
    ca-certificates \
    gcc \
    g++ \
    aria2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安装rclone（根据系统架构自动选择，添加重试机制和错误处理）
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        RCLONE_ARCH="amd64"; \
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        RCLONE_ARCH="arm64"; \
    elif [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armhf" ]; then \
        RCLONE_ARCH="arm-v7"; \
    else \
        RCLONE_ARCH="amd64"; \
    fi && \
    echo "检测到系统架构: $ARCH, 使用 rclone 架构: $RCLONE_ARCH" && \
    echo "测试网络连接..." && \
    if ! nslookup downloads.rclone.org >/dev/null 2>&1 && ! getent hosts downloads.rclone.org >/dev/null 2>&1; then \
        echo "警告: 无法解析 downloads.rclone.org，尝试使用备用 DNS..." && \
        echo "nameserver 8.8.8.8" > /etc/resolv.conf.tmp && \
        echo "nameserver 8.8.4.4" >> /etc/resolv.conf.tmp && \
        cat /etc/resolv.conf.tmp > /etc/resolv.conf 2>/dev/null || true; \
    fi && \
    MAX_RETRIES=5 && \
    RETRY_COUNT=0 && \
    DOWNLOAD_SUCCESS=false && \
    while [ $RETRY_COUNT -lt $MAX_RETRIES ] && [ "$DOWNLOAD_SUCCESS" = "false" ]; do \
        echo "尝试下载 rclone (第 $((RETRY_COUNT + 1))/$MAX_RETRIES 次)..." && \
        if wget --timeout=30 --tries=1 --no-check-certificate -O rclone-current-linux-${RCLONE_ARCH}.zip \
            https://downloads.rclone.org/rclone-current-linux-${RCLONE_ARCH}.zip 2>&1 | tee /tmp/wget.log || \
           curl --connect-timeout 30 --max-time 300 -f -L --retry 2 --retry-delay 3 -o rclone-current-linux-${RCLONE_ARCH}.zip \
            https://downloads.rclone.org/rclone-current-linux-${RCLONE_ARCH}.zip 2>&1 | tee /tmp/curl.log; then \
            if [ -f rclone-current-linux-${RCLONE_ARCH}.zip ] && [ -s rclone-current-linux-${RCLONE_ARCH}.zip ]; then \
                DOWNLOAD_SUCCESS=true && \
                echo "rclone 下载成功" && \
                unzip -q rclone-current-linux-${RCLONE_ARCH}.zip && \
                cd rclone-*-linux-${RCLONE_ARCH} && \
                cp rclone /usr/bin/ && \
                chmod 755 /usr/bin/rclone && \
                cd .. && \
                rm -rf rclone-*-linux-${RCLONE_ARCH} && \
                rm -f rclone-current-linux-${RCLONE_ARCH}.zip && \
                rclone version; \
            else \
                echo "下载的文件为空或不存在" && \
                rm -f rclone-current-linux-${RCLONE_ARCH}.zip; \
            fi; \
        else \
            echo "下载失败，错误信息:" && \
            [ -f /tmp/wget.log ] && cat /tmp/wget.log || true && \
            [ -f /tmp/curl.log ] && cat /tmp/curl.log || true; \
        fi; \
        if [ "$DOWNLOAD_SUCCESS" = "false" ]; then \
            RETRY_COUNT=$((RETRY_COUNT + 1)) && \
            if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then \
                echo "等待 5 秒后重试..." && \
                sleep 5; \
            else \
                echo "错误: 无法下载 rclone，已达到最大重试次数 ($MAX_RETRIES)" && \
                echo "可能的解决方案:" && \
                echo "1. 检查网络连接" && \
                echo "2. 检查 DNS 设置（尝试: docker build --network=host ...）" && \
                echo "3. 使用代理: docker build --build-arg HTTP_PROXY=... --build-arg HTTPS_PROXY=..." && \
                exit 1; \
            fi; \
        fi; \
    done

# Copy installed dependencies from the build stage
COPY --from=build /root/.local /root/.local

# 从前端构建阶段复制 dist 目录
COPY --from=frontend-builder /app/web/dist /app/web/dist

# 设置工作目录
WORKDIR /app

# Copy the rest of the application files
# 前端已通过多阶段构建集成到镜像中
COPY app.py async_aria2_client.py configer.py db.py util.py monitor.py requirements.txt start.sh ./
COPY aria2_client/ ./aria2_client/
COPY WebStreamer/ ./WebStreamer/

# 确保PATH包含.local/bin
ENV PATH=/root/.local/bin:$PATH

# 设置启动脚本权限
RUN chmod +x /app/start.sh

# 使用启动脚本
CMD ["/bin/bash", "-c", "set -e && /app/start.sh"]