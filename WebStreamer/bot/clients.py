# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import asyncio
import logging
from ..vars import Var
from pyrogram import Client
from . import multi_clients, work_loads, sessions_dir, StreamBot, channel_accessible_clients

logger = logging.getLogger("multi_client")

# 配置 Pyrogram 日志级别，降低连接警告的级别
# 这些警告通常是正常的网络波动，Pyrogram 会自动重连
pyrogram_transport_logger = logging.getLogger('pyrogram.connection.transport.tcp.tcp')
pyrogram_transport_logger.setLevel(logging.ERROR)  # 只显示 ERROR 及以上级别

# 过滤 asyncio 的 socket.send() 警告
pyrogram_asyncio_logger = logging.getLogger('asyncio')
class BrokenPipeFilter(logging.Filter):
    """过滤 BrokenPipeError 相关的警告，这些通常是正常的网络波动"""
    def filter(self, record):
        msg = str(record.getMessage())
        # 过滤 BrokenPipeError 和 socket.send() 相关的警告
        if any(keyword in msg for keyword in ['BrokenPipeError', 'Broken pipe', 'socket.send() raised exception']):
            # 将警告降级为 DEBUG 级别，不显示在日志中
            record.levelno = logging.DEBUG
            record.levelname = 'DEBUG'
        return True

broken_pipe_filter = BrokenPipeFilter()
pyrogram_asyncio_logger.addFilter(broken_pipe_filter)

# 过滤 Pyrogram 加密相关的错误（客户端断开连接时的已知问题）
class EncryptionErrorFilter(logging.Filter):
    """过滤 Pyrogram 加密状态异常的错误，这些通常在客户端断开连接时发生"""
    def filter(self, record):
        msg = str(record.getMessage())
        # 过滤加密相关的 TypeError（Value after * must be an iterable）
        if any(keyword in msg for keyword in [
            'Value after * must be an iterable',
            'not NoneType',
            'Task exception was never retrieved',
            'handle_packet',
            'ctr256_encrypt'
        ]):
            # 检查是否是加密相关的错误
            if 'encrypt' in msg.lower() or 'NoneType' in msg:
                # 将错误降级为 DEBUG 级别，不显示在日志中
                # 这个错误会在健康检查时自动修复
                record.levelno = logging.DEBUG
                record.levelname = 'DEBUG'
        return True

encryption_error_filter = EncryptionErrorFilter()
pyrogram_asyncio_logger.addFilter(encryption_error_filter)

async def initialize_clients():
    """
    初始化客户端
    如果配置了多个BOT_TOKEN，将创建多个客户端以实现负载均衡
    """
    # 第一个客户端始终使用默认的StreamBot（已用BOT_TOKEN初始化）
    multi_clients[0] = StreamBot
    work_loads[0] = 0
    # 默认客户端应该能访问频道（因为它是主客户端）
    if Var.BIN_CHANNEL:
        try:
            await StreamBot.get_chat(Var.BIN_CHANNEL)
            channel_accessible_clients.add(0)
            logger.info(f"客户端 0 已成功访问 BIN_CHANNEL: {Var.BIN_CHANNEL}")
        except Exception as e:
            logger.warning(f"客户端 0 无法访问 BIN_CHANNEL: {e}")
    
    # 调试日志：检查配置状态
    logger.info(f"🔍 多客户端初始化检查: MULTI_CLIENT={Var.MULTI_CLIENT}, MULTI_BOT_TOKENS数量={len(Var.MULTI_BOT_TOKENS) if Var.MULTI_BOT_TOKENS else 0}")
    if Var.MULTI_BOT_TOKENS:
        logger.info(f"📋 配置的额外BOT_TOKEN: {[token[:15] + '...' for token in Var.MULTI_BOT_TOKENS]}")
    
    # 如果配置了额外的BOT_TOKEN，创建额外的客户端
    if Var.MULTI_CLIENT and Var.MULTI_BOT_TOKENS and len(Var.MULTI_BOT_TOKENS) > 0:
        # 多客户端模式：为每个额外的BOT_TOKEN创建客户端
        total_clients = 1 + len(Var.MULTI_BOT_TOKENS)
        logger.info(f"启用多机器人负载均衡模式，将初始化 {total_clients} 个客户端（1个默认 + {len(Var.MULTI_BOT_TOKENS)}个额外）")
        logger.info(f"客户端 0 已初始化（默认客户端，使用主BOT_TOKEN）")
        
        # 为额外的BOT_TOKEN创建客户端
        for index, bot_token in enumerate(Var.MULTI_BOT_TOKENS, start=1):
            try:
                client_name = f"WebStreamer_{index}"
                client = Client(
                    name=client_name,
                    api_id=Var.API_ID,
                    api_hash=Var.API_HASH,
                    workdir=sessions_dir if Var.USE_SESSION_FILE else "WebStreamer",
                    plugins={"root": "WebStreamer.bot.plugins"},
                    bot_token=bot_token,
                    sleep_threshold=Var.SLEEP_THRESHOLD,
                    workers=Var.WORKERS,
                    in_memory=not Var.USE_SESSION_FILE,
                )
                
                # 启动客户端
                await client.start()
                bot_info = await client.get_me()
                client.username = bot_info.username
                
                # 尝试访问 BIN_CHANNEL 以建立连接（多客户端模式下必需）
                if Var.BIN_CHANNEL:
                    try:
                        # 尝试获取频道信息以建立连接
                        await client.get_chat(Var.BIN_CHANNEL)
                        channel_accessible_clients.add(index)
                        logger.info(f"客户端 {index} 已成功访问 BIN_CHANNEL: {Var.BIN_CHANNEL}")
                    except Exception as channel_error:
                        logger.warning(f"客户端 {index} 无法访问 BIN_CHANNEL ({Var.BIN_CHANNEL}): {channel_error}")
                        logger.warning(f"⚠️ 请确保机器人 @{bot_info.username} 已加入频道 {Var.BIN_CHANNEL} 并具有管理员权限")
                        # 不阻止客户端初始化，但会在使用时出错
                
                multi_clients[index] = client
                work_loads[index] = 0
                logger.info(f"客户端 {index} 已初始化: @{bot_info.username}")
            except Exception as e:
                logger.error(f"初始化客户端 {index} 失败 (token: {bot_token[:10]}...): {e}", exc_info=True)
                # 继续初始化其他客户端，不因单个失败而停止
        
        successful_clients = len(multi_clients)
        logger.info(f"多机器人负载均衡初始化完成，共 {successful_clients} 个客户端可用")
        
        # 启动客户端健康检查任务（仅多客户端模式）
        if Var.MULTI_CLIENT:
            asyncio.create_task(client_health_check())
    else:
        # 单客户端模式：只使用默认的StreamBot
        logger.info("使用单客户端模式（默认客户端）")


async def client_health_check():
    """
    定期检查客户端连接健康状态
    如果客户端断开连接，尝试重新连接
    """
    check_interval = 300  # 每5分钟检查一次
    logger.info(f"启动客户端健康检查任务（每 {check_interval} 秒检查一次）")
    
    async def reconnect_client(index, client):
        """安全地重新连接客户端"""
        try:
            # 先停止客户端（如果已连接），确保完全清理状态
            try:
                if hasattr(client, 'is_connected') and client.is_connected:
                    await client.stop()
                    # 等待一小段时间，确保连接完全关闭
                    await asyncio.sleep(1)
            except Exception as stop_error:
                logger.debug(f"停止客户端 {index} 时出错（可能已断开）: {stop_error}")
            
            # 重新启动客户端
            await client.start()
            
            # 验证连接是否正常
            await client.get_me()
            
            logger.info(f"客户端 {index} 重新连接成功")
            return True
        except Exception as reconnect_error:
            error_msg = str(reconnect_error)
            error_type = type(reconnect_error).__name__
            
            # 检查是否是加密相关的错误（这是已知问题，会在重连时自动修复）
            if 'Value after * must be an iterable' in error_msg or 'NoneType' in error_msg:
                logger.debug(f"客户端 {index} 加密状态异常（将在下次检查时重连）: {error_type}")
            else:
                logger.error(f"客户端 {index} 重新连接失败: {reconnect_error}")
            return False
    
    while True:
        try:
            await asyncio.sleep(check_interval)
            
            # 检查所有客户端
            for index, client in list(multi_clients.items()):
                try:
                    # 检查连接状态
                    is_connected = False
                    if hasattr(client, 'is_connected'):
                        is_connected = client.is_connected
                    
                    if not is_connected:
                        logger.warning(f"客户端 {index} 连接已断开，尝试重新连接...")
                        await reconnect_client(index, client)
                    else:
                        # 连接正常，尝试一个简单的 API 调用来验证
                        try:
                            await asyncio.wait_for(client.get_me(), timeout=10)
                        except asyncio.TimeoutError:
                            logger.warning(f"客户端 {index} API 调用超时，尝试重新连接...")
                            await reconnect_client(index, client)
                        except TypeError as e:
                            # 捕获加密相关的 TypeError（Value after * must be an iterable）
                            error_msg = str(e)
                            if 'Value after * must be an iterable' in error_msg or 'NoneType' in error_msg:
                                logger.warning(f"客户端 {index} 加密状态异常，尝试重新连接...")
                                await reconnect_client(index, client)
                            else:
                                raise
                        except Exception as check_error:
                            error_msg = str(check_error)
                            error_type = type(check_error).__name__
                            
                            # 检查是否是加密相关的错误
                            if 'Value after * must be an iterable' in error_msg or 'NoneType' in error_msg:
                                logger.warning(f"客户端 {index} 加密状态异常，尝试重新连接...")
                                await reconnect_client(index, client)
                            else:
                                logger.warning(f"客户端 {index} 连接检查失败: {check_error}，尝试重新连接...")
                                await reconnect_client(index, client)
                except Exception as e:
                    error_msg = str(e)
                    # 过滤加密相关的错误，这些是已知问题
                    if 'Value after * must be an iterable' in error_msg or 'NoneType' in error_msg:
                        logger.debug(f"客户端 {index} 检查时出现加密状态异常（将在下次检查时重连）: {type(e).__name__}")
                    else:
                        logger.debug(f"检查客户端 {index} 时出错: {e}")
                    
        except Exception as e:
            logger.error(f"客户端健康检查任务出错: {e}", exc_info=True)
            await asyncio.sleep(60)  # 出错后等待1分钟再继续

