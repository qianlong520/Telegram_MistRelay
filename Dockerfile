# Build stage
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

# 安装rclone（根据系统架构自动选择）
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
    curl -O https://downloads.rclone.org/rclone-current-linux-${RCLONE_ARCH}.zip \
    && unzip rclone-current-linux-${RCLONE_ARCH}.zip \
    && cd rclone-*-linux-${RCLONE_ARCH} \
    && cp rclone /usr/bin/ \
    && chmod 755 /usr/bin/rclone \
    && cd .. \
    && rm -rf rclone-*-linux-${RCLONE_ARCH} \
    && rm -f rclone-current-linux-${RCLONE_ARCH}.zip \
    && rclone version

# Copy installed dependencies from the build stage
COPY --from=build /root/.local /root/.local

# Copy the rest of the application files
COPY . /app

WORKDIR /app

# 确保PATH包含.local/bin
ENV PATH=/root/.local/bin:$PATH

# 设置启动脚本权限
RUN chmod +x /app/start.sh

# 使用启动脚本
CMD ["/bin/bash", "-c", "set -e && /app/start.sh"]