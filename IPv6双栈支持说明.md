# IPv6 双栈支持说明

## 概述

系统现已支持 IPv6 双栈（Dual Stack），可以同时使用 IPv4 和 IPv6 进行网络连接，提高连接性和性能。

## 优势

### 1. **更好的连接性**
- 某些网络环境下，IPv6 连接可能更快、更稳定
- 避免 IPv4 地址耗尽问题
- 更好的路由效率

### 2. **更高的可用性**
- 如果 IPv4 连接出现问题，可以自动使用 IPv6
- 双栈提供冗余连接路径
- 提高系统容错能力

### 3. **未来趋势**
- IPv6 是互联网的未来发展方向
- 越来越多的服务优先支持 IPv6
- 提前适配，避免后续迁移问题

## 已实现的改进

### 1. **aria2 配置**
- ✅ 启用 IPv6 支持：`disable-ipv6=false`
- aria2 现在可以通过 IPv6 下载文件

### 2. **Web 服务器**
- ✅ 当 `STREAM_BIND_ADDRESS` 设置为 `0.0.0.0` 时，自动同时绑定 IPv4 和 IPv6
- ✅ 如果系统不支持 IPv6，自动回退到仅 IPv4
- ✅ 支持通过配置指定仅 IPv4 或仅 IPv6

### 3. **Pyrogram 客户端**
- ✅ Python 的 socket 库默认支持双栈
- ✅ Pyrogram 会自动选择最佳连接方式（IPv4 或 IPv6）

## 配置说明

### Web 服务器绑定地址配置

在 `config.yml` 中配置 `STREAM_BIND_ADDRESS`：

```yaml
# 选项1：双栈支持（推荐）
# 设置为 0.0.0.0 将同时绑定 IPv4 和 IPv6
STREAM_BIND_ADDRESS: 0.0.0.0

# 选项2：仅 IPv4
# 设置为具体的 IPv4 地址
STREAM_BIND_ADDRESS: 192.168.1.100

# 选项3：仅 IPv6
# 设置为 IPv6 地址
STREAM_BIND_ADDRESS: ::
```

### aria2 配置

aria2 配置已自动启用 IPv6（`disable-ipv6=false`），无需额外配置。

## 使用建议

### 1. **推荐配置**
```yaml
STREAM_BIND_ADDRESS: 0.0.0.0  # 启用双栈支持
```

### 2. **检查系统 IPv6 支持**
```bash
# 检查 IPv6 是否可用
ip -6 addr show

# 测试 IPv6 连接
ping6 ipv6.google.com
```

### 3. **Docker 环境**
如果使用 Docker，确保 Docker 网络支持 IPv6：
```bash
# 检查 Docker IPv6 支持
docker network inspect bridge | grep EnableIPv6
```

## 故障排除

### 问题1：IPv6 绑定失败
**症状**：日志显示 "IPv6绑定失败，仅使用IPv4"

**原因**：
- 系统未启用 IPv6
- Docker 网络未配置 IPv6
- 防火墙阻止 IPv6

**解决方案**：
1. 检查系统 IPv6 支持：`ip -6 addr show`
2. 如果不需要 IPv6，可以忽略此警告（系统会自动使用 IPv4）
3. 如果需要 IPv6，请配置系统/Docker 网络支持 IPv6

### 问题2：连接速度没有提升
**说明**：IPv6 双栈主要是提供冗余和未来兼容性，不一定在所有环境下都能提升速度。

**建议**：
- 保持双栈配置，获得更好的兼容性
- 监控连接质量，根据实际情况调整

### 问题3：aria2 下载失败
**检查**：
1. 确认 aria2 配置中 `disable-ipv6=false`
2. 检查网络环境是否支持 IPv6
3. 查看 aria2 日志确认连接方式

## 技术细节

### Web 服务器双栈实现
- 使用 aiohttp 的 `TCPSite` 同时绑定 IPv4 (`0.0.0.0`) 和 IPv6 (`::`)
- 如果 IPv6 绑定失败，自动回退到仅 IPv4
- 客户端可以通过 IPv4 或 IPv6 访问，系统自动选择

### aria2 IPv6 支持
- aria2 的 `disable-ipv6=false` 选项启用 IPv6 下载
- aria2 会自动选择最佳连接方式（IPv4 或 IPv6）

### Pyrogram 客户端
- Python 的 socket 库默认支持双栈
- Pyrogram 会自动使用系统的最佳连接方式
- 无需额外配置

## 总结

✅ **已启用 IPv6 双栈支持**
- aria2 支持 IPv6 下载
- Web 服务器支持 IPv4+IPv6 双栈
- Pyrogram 客户端自动使用最佳连接方式

📝 **配置建议**
- 使用 `STREAM_BIND_ADDRESS: 0.0.0.0` 启用双栈
- 如果系统不支持 IPv6，会自动回退到 IPv4

🔍 **监控和调试**
- 查看启动日志确认 IPv6 绑定状态
- 监控连接质量，根据实际情况调整

