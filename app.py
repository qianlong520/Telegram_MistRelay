import asyncio
import base64
import datetime
import logging
import re
import shutil
from typing import Any

import python_socks

from telethon import TelegramClient, events, Button
import coloredlogs
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault, Message

from async_aria2_client import AsyncAria2Client
from configer import (
    API_ID, API_HASH, PROXY_IP, PROXY_PORT, BOT_TOKEN, ADMIN_ID, RPC_SECRET, RPC_URL,
    ENABLE_STREAM
)
from util import get_file_name, progress, byte2_readable, hum_convert

coloredlogs.install(level='INFO')
log = logging.getLogger('bot')

# 导入直链功能（默认启用，作为TG媒体文件下载的前置功能）
stream_server = None
StreamBot = None
Var = None
utils = None
web = None
web_server = None
initialize_clients = None

if ENABLE_STREAM:
    try:
        from aiohttp import web
        from WebStreamer.server import web_server
        from WebStreamer.bot.clients import initialize_clients, StreamBot
        from WebStreamer import Var, utils
    except ImportError as e:
        log.warning(f"直链功能导入失败: {e}，将禁用直链功能")
        ENABLE_STREAM = False

# 如果RPC_URL中的主机名不是localhost或IP地址，则在Docker环境中使用localhost
url_parts = RPC_URL.split(':')
host = url_parts[0]
if not (host == 'localhost' or host == '127.0.0.1' or all(c.isdigit() or c == '.' for c in host)):
    # 在Docker环境中，使用localhost
    host = 'localhost'
    port_path = ':'.join(url_parts[1:])
    docker_rpc_url = f"{host}:{port_path}"
    print(f"在Docker环境中使用本地RPC URL: {docker_rpc_url}")
else:
    docker_rpc_url = RPC_URL

proxy = (python_socks.ProxyType.HTTP, PROXY_IP, PROXY_PORT) if PROXY_IP is not None else None
bot = TelegramClient('./db/bot', API_ID, API_HASH, proxy=proxy).start(bot_token=BOT_TOKEN)
client = AsyncAria2Client(RPC_SECRET, f'ws://{docker_rpc_url}', bot)

# 将aria2客户端设置为全局变量，供直链功能使用
aria2_client = client


@bot.on(events.NewMessage(pattern="/start"))
async def handler(event):
    welcome_msg = (
        f"🤖 <b>MistRelay 下载机器人</b>\n\n"
        f"📥 支持HTTP、磁力、种子下载\n"
        f"☁️ 支持OneDrive自动上传\n"
        f"🔗 支持Telegram文件直链生成\n\n"
        f"👤 你的ID: <code>{event.chat_id}</code>\n\n"
        f"💡 使用下方菜单按钮或发送 <code>/help</code> 查看帮助"
    )
    await event.reply(welcome_msg, parse_mode='html', buttons=get_menu())


@bot.on(events.NewMessage(pattern="/menu", from_users=ADMIN_ID))
async def handler(event):
    await event.reply("📋 功能菜单", parse_mode='html', buttons=get_menu())


@bot.on(events.NewMessage(pattern="/web", from_users=ADMIN_ID))
async def handler(event):
    base_key = base64.b64encode(RPC_SECRET.encode("utf-8")).decode('utf-8')
    await event.respond(f'http://ariang.js.org/#!/settings/rpc/set/ws/{RPC_URL.replace(":", "/", 1)}/{base_key}')


@bot.on(events.NewMessage(pattern="/info", from_users=ADMIN_ID))
async def handler(event):
    result = await client.get_global_option()
    await event.respond(
        f'下载目录: {result["dir"]}\n'
        f'最大同时下载数: {result["max-concurrent-downloads"]}\n'
        f'允许覆盖: {"是" if result["allow-overwrite"] else "否"}'
    )


@bot.on(events.NewMessage(pattern="/path", from_users=ADMIN_ID))
async def handler(event):
    text = event.raw_text
    text = text.replace('/path ', '').strip()
    params = [{"dir": text}]
    data = await client.change_global_option(params)
    if data['result'] == 'OK':
        await event.respond(f'默认路径设置成功 {text}\n'
                            f'注意: docker启动的话，要在配置文件docker-compose.yml中配置挂载目录')
    else:
        await event.respond(f'默认路径设置失败 {text}')


@bot.on(events.NewMessage(pattern="/help"))
async def handler(event):
    help_text = (
        f"📖 <b>MistRelay 使用帮助</b>\n\n"
        f"<b>📋 基本命令：</b>\n"
        f"• <code>/start</code> - 开始使用并显示菜单\n"
        f"• <code>/menu</code> - 显示功能菜单\n"
        f"• <code>/help</code> - 显示此帮助信息\n"
        f"• <code>/info</code> - 查看系统信息\n"
        f"• <code>/web</code> - 获取ariaNg在线控制地址\n"
        f"• <code>/path [目录]</code> - 设置下载目录\n\n"
        f"<b>📥 下载方式：</b>\n"
        f"• 发送HTTP链接\n"
        f"• 发送磁力链接（magnet:）\n"
        f"• 发送种子文件（.torrent）\n"
        f"• 发送Telegram文件（自动生成直链并下载）\n\n"
        f"<b>🎛️ 菜单功能：</b>\n"
        f"• ⬇️正在下载 - 查看正在下载的任务\n"
        f"• ⌛️ 正在等待 - 查看等待中的任务\n"
        f"• ✅ 已完成/停止 - 查看已完成的任务\n"
        f"• ⏸️暂停任务 - 暂停选中的任务\n"
        f"• ▶️恢复任务 - 恢复选中的任务\n"
        f"• ❌ 删除任务 - 删除选中的任务\n"
        f"• 📊 系统信息 - 查看系统配置信息\n"
        f"• 🔗 直链状态 - 查看直链功能状态\n"
        f"• 🗑️ 清空已完成 - 清空所有已完成的任务\n\n"
        f"👤 你的ID: <code>{event.chat_id}</code>"
    )
    await event.reply(help_text, parse_mode='html', buttons=[
        [Button.url('📚 更多帮助', 'https://github.com/jw-star/aria2bot')],
        [Button.text('📋 显示菜单', resize=True)]
    ])


@bot.on(events.NewMessage(from_users=ADMIN_ID))
async def send_welcome(event):
    text = event.raw_text
    log.info(str(datetime.datetime.now()) + ':' + text)
    
    # 任务查看菜单
    if text == '⬇️正在下载':
        await downloading(event)
        return
    elif text == '⌛️ 正在等待':
        await waiting(event)
        return
    elif text == '✅ 已完成/停止':
        await stoped(event)
        return
    # 任务管理菜单
    elif text == '⏸️暂停任务':
        await stop_task(event)
        return
    elif text == '▶️恢复任务':
        await unpause_task(event)
        return
    elif text == '❌ 删除任务':
        await remove_task(event)
        return
    elif text == '🗑️ 清空已完成':
        await remove_all(event)
        return
    # 系统功能菜单
    elif text == '📊 系统信息':
        result = await client.get_global_option()
        await event.respond(
            f'📁 下载目录: <code>{result["dir"]}</code>\n'
            f'🔢 最大同时下载数: <code>{result["max-concurrent-downloads"]}</code>\n'
            f'🔄 允许覆盖: {"是" if result["allow-overwrite"] else "否"}\n'
            f'📎 直链功能: {"已启用" if ENABLE_STREAM else "已禁用"}',
            parse_mode='html'
        )
        return
    elif text == '🔗 直链状态':
        if ENABLE_STREAM and Var:
            status = "✅ 已启用" if Var.ENABLE_STREAM else "❌ 已禁用"
            auto_download = "✅ 已启用" if Var.AUTO_DOWNLOAD else "❌ 已禁用"
            bin_channel = f"<code>{Var.BIN_CHANNEL}</code>" if Var.BIN_CHANNEL else "❌ 未配置"
            stream_url = Var.URL if Var else "未配置"
            await event.respond(
                f'📎 <b>直链功能状态</b>\n\n'
                f'状态: {status}\n'
                f'自动下载: {auto_download}\n'
                f'日志频道: {bin_channel}\n'
                f'Web地址: <code>{stream_url}</code>',
                parse_mode='html'
            )
        else:
            await event.respond('❌ 直链功能未启用', parse_mode='html')
        return
    elif text == '📋 显示菜单':
        await event.reply("📋 功能菜单", parse_mode='html', buttons=get_menu())
        return
    elif text == '🔄 刷新菜单':
        await event.reply("菜单已刷新", buttons=get_menu())
        return
    elif text == '❌ 关闭键盘':
        await event.reply("键盘已关闭，发送 <code>/start</code> 或 <code>/menu</code> 重新开启", parse_mode='html', buttons=Button.clear())
        return
    # 获取输入信息
    if text.startswith('http'):
        url_arr = text.split('\n')
        for url in url_arr:
            await client.add_uri(
                uris=[url],
            )
    elif text.startswith('magnet'):
        pattern_res = re.findall('magnet:\?xt=urn:btih:[0-9a-fA-F]{40,}.*', text)
        for text in pattern_res:
            await client.add_uri(
                uris=[text],
            )
    elif event.media:
        # 处理媒体文件
        # 如果直链功能启用，媒体文件由Pyrogram客户端处理，Telethon只处理种子文件
        if ENABLE_STREAM:
            # 检查是否是种子文件（种子文件需要Telethon处理）
            if hasattr(event.media, 'document') and event.media.document:
                if event.media.document.mime_type == 'application/x-bittorrent':
                    # 种子文件：直接下载并添加到aria2（Telethon处理）
                    await event.reply('收到了一个种子')
                    path = await bot.download_media(event.message)
                    await client.add_torrent(path)
                else:
                    # 其他文档类型：由Pyrogram客户端通过直链功能处理，Telethon不处理
                    log.debug(f"媒体文件由Pyrogram直链功能处理，Telethon跳过")
                    return
            else:
                # 照片、视频等媒体文件：由Pyrogram客户端通过直链功能处理，Telethon不处理
                log.debug(f"媒体文件由Pyrogram直链功能处理，Telethon跳过")
                return
        else:
            # 如果直链功能未启用，Telethon可以处理媒体文件（如果需要）
            # 目前Telethon不处理非种子文件的媒体文件
            if hasattr(event.media, 'document') and event.media.document:
                if event.media.document.mime_type == 'application/x-bittorrent':
                    # 种子文件：直接下载并添加到aria2
                    await event.reply('收到了一个种子')
                    path = await bot.download_media(event.message)
                    await client.add_torrent(path)
                else:
                    log.info("直链功能未启用，媒体文件不进行自动下载")
                    return
            else:
                log.info("直链功能未启用，媒体文件不进行自动下载")
                return


def get_media_from_message(message: "Message") -> Any:
    media_types = (
        "audio",
        "document",
        "photo",
        "sticker",
        "animation",
        "video",
        "voice",
        "video_note",
    )
    for attr in media_types:
        media = getattr(message, attr, None)
        if media:
            return media


async def remove_all(event):
    # 过滤 已完成或停止
    tasks = await client.tell_stopped(0, 500)
    for task in tasks:
        await client.remove_download_result(task['gid'])
    result = await client.get_global_option()
    print('清空目录 ', result['dir'])
    shutil.rmtree(result['dir'], ignore_errors=True)
    await event.respond('任务已清空,所有文件已删除', parse_mode='html')


async def unpause_task(event):
    tasks = await client.tell_waiting(0, 50)
    # 筛选send_id对应的任务
    if len(tasks) == 0:
        await event.respond('没有已暂停的任务,无法恢复下载', parse_mode='markdown')
        return
    buttons = []
    for task in tasks:
        file_name = get_file_name(task)
        gid = task['gid']
        buttons.append([Button.inline(file_name, 'unpause-task.' + gid)])
    await event.respond('请选择要恢复▶️的任务', parse_mode='html', buttons=buttons)


async def remove_task(event):
    temp_task = []
    # 正在下载的任务
    tasks = await client.tell_active()
    for task in tasks:
        temp_task.append(task)
    # 正在等待的任务
    tasks = await  client.tell_waiting(0, 50)
    for task in tasks:
        temp_task.append(task)
    if len(temp_task) == 0:
        await event.respond('没有正在运行或等待的任务,无删除选项', parse_mode='markdown')
        return
    # 拼接所有任务
    buttons = []
    for task in temp_task:
        file_name = get_file_name(task)
        gid = task['gid']
        buttons.append([Button.inline(file_name, 'del-task.' + gid)])
    await event.respond('请选择要删除❌ 的任务', parse_mode='html', buttons=buttons)


async def stop_task(event):
    tasks = await client.tell_active()
    if len(tasks) == 0:
        await event.respond('没有正在运行的任务,无暂停选项,请先添加任务', parse_mode='markdown')
        return
    buttons = []
    for task in tasks:
        fileName = get_file_name(task)
        gid = task['gid']
        buttons.append([Button.inline(fileName, 'pause-task.' + gid)])

    await event.respond('请选择要暂停⏸️的任务', parse_mode='html', buttons=buttons)


async def downloading(event):
    tasks = await client.tell_active()
    if len(tasks) == 0:
        await event.respond('没有正在运行的任务', parse_mode='html')
        return
    send_msg = ''
    for task in tasks:
        completedLength = task['completedLength']
        totalLength = task['totalLength']
        downloadSpeed = task['downloadSpeed']
        fileName = get_file_name(task)
        if fileName == '':
            continue
        prog = progress(int(totalLength), int(completedLength))
        size = byte2_readable(int(totalLength))
        speed = hum_convert(int(downloadSpeed))

        send_msg = send_msg + '任务名称: <b>' + fileName + '</b>\n进度: ' + prog + '\n大小: ' + size + '\n速度: ' + speed + '/s\n\n'
    if send_msg == '':
        await event.respond('个别任务无法识别名称，请使用aria2Ng查看', parse_mode='html')
        return
    await event.respond(send_msg, parse_mode='html')


async def waiting(event):
    tasks = await client.tell_waiting(0, 30)
    if len(tasks) == 0:
        await event.respond('没有正在等待的任务', parse_mode='markdown')
        return
    send_msg = ''
    for task in tasks:
        completedLength = task['completedLength']
        totalLength = task['totalLength']
        downloadSpeed = task['downloadSpeed']
        fileName = get_file_name(task)
        prog = progress(int(totalLength), int(completedLength))
        size = byte2_readable(int(totalLength))
        speed = hum_convert(int(downloadSpeed))
        send_msg = send_msg + '任务名称: ' + fileName + '\n进度: ' + prog + '\n大小: ' + size + '\n速度: ' + speed + '\n\n'
    await event.respond(send_msg, parse_mode='html')


async def stoped(event):
    tasks = await client.tell_stopped(0, 30)
    if len(tasks) == 0:
        await event.respond('没有已完成或停止的任务', parse_mode='markdown')
        return
    send_msg = ''
    for task in reversed(tasks):
        completedLength = task['completedLength']
        totalLength = task['totalLength']
        downloadSpeed = task['downloadSpeed']
        fileName = get_file_name(task)
        prog = progress(int(totalLength), int(completedLength))
        size = byte2_readable(int(totalLength))
        speed = hum_convert(int(downloadSpeed))
        send_msg = send_msg + '任务名称: ' + fileName + '\n进度: ' + prog + '\n大小: ' + size + '\n速度: ' + speed + '\n\n'
    await event.respond(send_msg, parse_mode='html')


@events.register(events.CallbackQuery)
async def BotCallbackHandler(event):
    d = str(event.data, encoding="utf-8")
    [type, gid] = d.split('.', 1)
    if type == 'pause-task':
        await client.pause(gid)
    elif type == 'unpause-task':
        await client.unpause(gid)
    elif type == 'del-task':
        data = await client.remove(gid)
        if 'error' in data:
            error_msg = (
                f'❌ <b>操作失败</b>\n\n'
                f'⚠️ <b>错误信息:</b>\n<code>{data["error"]["message"]}</code>'
            )
            await bot.send_message(ADMIN_ID, error_msg, parse_mode='html')
        else:
            success_msg = (
                f'✅ <b>删除成功</b>\n\n'
                f'🗑️ 任务已从下载队列中移除'
            )
            await bot.send_message(ADMIN_ID, success_msg, parse_mode='html')


def get_menu():
    """
    优化的菜单布局
    第一行：任务查看（下载中、等待中、已完成）
    第二行：任务管理（暂停、恢复、删除）
    第三行：系统功能（系统信息、直链状态）
    第四行：其他功能（清空已完成、刷新菜单、关闭键盘）
    """
    return [
        [
            Button.text('⬇️正在下载', resize=True),
            Button.text('⌛️ 正在等待', resize=True),
            Button.text('✅ 已完成/停止', resize=True)
        ],
        [
            Button.text('⏸️暂停任务', resize=True),
            Button.text('▶️恢复任务', resize=True),
            Button.text('❌ 删除任务', resize=True),
        ],
        [
            Button.text('📊 系统信息', resize=True),
            Button.text('🔗 直链状态', resize=True),
        ],
        [
            Button.text('🗑️ 清空已完成', resize=True),
            Button.text('🔄 刷新菜单', resize=True),
            Button.text('❌ 关闭键盘', resize=True),
        ],
    ]


# 入口
async def main():
    await client.connect()
    bot.add_event_handler(BotCallbackHandler)
    bot_me = await bot.get_me()
    commands = [
        BotCommand(command="start", description='开始使用并显示菜单'),
        BotCommand(command="menu", description='显示功能菜单'),
        BotCommand(command="help", description='查看帮助信息'),
        BotCommand(command="info", description='查看系统信息'),
        BotCommand(command="web", description='获取ariaNg在线地址'),
        BotCommand(command="path", description='设置下载目录'),
    ]
    await bot(
        SetBotCommandsRequest(
            scope=BotCommandScopeDefault(),
            lang_code='',
            commands=commands
        )
    )
    log.info(f'{bot_me.username} bot启动成功...')
    
    # 启动直链功能（默认启用，作为TG媒体文件下载的前置功能）
    if ENABLE_STREAM and StreamBot is not None:
        try:
            log.info('正在启动直链功能（作为TG媒体文件前置处理）...')
            
            # 配置 Pyrogram 日志级别，屏蔽速率限制等待的警告消息
            # 这些警告是正常的速率限制行为，不需要显示
            pyrogram_session_logger = logging.getLogger('pyrogram.session.session')
            pyrogram_session_logger.setLevel(logging.ERROR)  # 只显示 ERROR 及以上级别
            
            if not Var or not Var.BIN_CHANNEL:
                log.warning('BIN_CHANNEL未配置，直链功能可能无法正常工作')
            
            # 启动机器人，处理 FLOOD_WAIT 错误
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    await StreamBot.start()
                    bot_info = await StreamBot.get_me()
                    StreamBot.username = bot_info.username
                    log.info(f'直链机器人启动成功: @{bot_info.username}')
                    break
                except Exception as e:
                    error_str = str(e)
                    error_type = type(e).__name__
                    
                    # 检查是否是 FLOOD_WAIT 错误
                    if 'FLOOD_WAIT' in error_str or 'FloodWait' in error_str or 'flood_420' in error_type:
                        # 提取等待时间（秒）
                        wait_time = None
                        
                        # 尝试多种格式提取等待时间
                        patterns = [
                            r'(\d+)\s+seconds?',  # "502 seconds"
                            r'FLOOD_WAIT_X.*?(\d+)',  # "FLOOD_WAIT_X 502"
                            r'wait of (\d+)',  # "wait of 502"
                            r'(\d+)\s+second',  # "502 second"
                        ]
                        
                        for pattern in patterns:
                            wait_match = re.search(pattern, error_str, re.IGNORECASE)
                            if wait_match:
                                wait_time = int(wait_match.group(1))
                                break
                        
                        # 如果无法提取时间，默认等待 10 分钟（600秒）
                        if wait_time is None:
                            wait_time = 600
                            log.warning(f'无法从错误消息中提取等待时间，使用默认值 10 分钟（600秒）')
                        
                        retry_count += 1
                        
                        # 将秒数转换为更易读的格式
                        if wait_time >= 60:
                            wait_minutes = wait_time // 60
                            wait_seconds = wait_time % 60
                            if wait_seconds > 0:
                                wait_str = f'{wait_minutes} 分 {wait_seconds} 秒'
                            else:
                                wait_str = f'{wait_minutes} 分钟'
                        else:
                            wait_str = f'{wait_time} 秒'
                        
                        if retry_count < max_retries:
                            log.warning(f'遇到 Telegram 限流，需要等待 {wait_str}（{wait_time} 秒）后重试 (尝试 {retry_count}/{max_retries})...')
                            await asyncio.sleep(wait_time + 5)  # 多等待5秒，确保安全
                        else:
                            log.error(f'遇到 Telegram 限流，需要等待 {wait_str}（{wait_time} 秒），但已达到最大重试次数 ({max_retries})')
                            raise Exception(f'启动直链机器人失败：Telegram 限流，需要等待 {wait_str}（{wait_time} 秒）')
                    else:
                        # 其他错误，直接抛出
                        raise
            else:
                # 如果所有重试都失败（不应该到达这里，因为上面已经抛出异常）
                raise Exception(f'启动直链机器人失败：已达到最大重试次数 ({max_retries})')
            
            await initialize_clients()
            
            # 将aria2客户端传递给直链功能
            try:
                from WebStreamer.bot.plugins.stream import set_aria2_client
                set_aria2_client(client)
                log.info('已设置aria2客户端到直链功能')
            except Exception as e:
                log.warning(f'设置aria2客户端失败: {e}')
            
            if Var and Var.KEEP_ALIVE and utils:
                asyncio.create_task(utils.ping_server())
            
            global stream_server
            if web and web_server:
                # 配置 aiohttp 日志记录器，将协议级错误降级为 DEBUG
                # 这些错误通常是扫描或恶意请求（如 TLS 握手），不需要记录为 ERROR
                aiohttp_logger = logging.getLogger('aiohttp.server')
                
                # 创建自定义过滤器来过滤 BadStatusLine 错误
                class BadStatusLineFilter(logging.Filter):
                    def filter(self, record):
                        # 检查是否是 BadStatusLine 错误（通常是 TLS 握手或扫描请求）
                        msg = str(record.getMessage())
                        
                        # 检查错误消息中是否包含 BadStatusLine 或 Invalid method
                        if 'BadStatusLine' in msg or 'Invalid method' in msg:
                            # 检查是否是 TLS 握手请求（\x16\x03\x01 是 TLS Client Hello）
                            if r'\x16\x03\x01' in msg or 'b\'\\x16\\x03\\x01\'' in msg:
                                # 将错误降级为 DEBUG 级别，不记录为 ERROR
                                record.levelno = logging.DEBUG
                                record.levelname = 'DEBUG'
                                return True
                        
                        # 检查异常信息
                        if hasattr(record, 'exc_info') and record.exc_info:
                            exc_type, exc_value, _ = record.exc_info
                            if exc_type:
                                exc_type_name = exc_type.__name__ if hasattr(exc_type, '__name__') else str(exc_type)
                                if 'BadStatusLine' in exc_type_name:
                                    # 将错误降级为 DEBUG 级别
                                    record.levelno = logging.DEBUG
                                    record.levelname = 'DEBUG'
                                    return True
                        
                        return True
                
                # 添加过滤器
                bad_status_filter = BadStatusLineFilter()
                aiohttp_logger.addFilter(bad_status_filter)
                
                stream_server = web.AppRunner(web_server())
                await stream_server.setup()
                site = web.TCPSite(stream_server, Var.BIND_ADDRESS, Var.PORT)
                await site.start()
                log.info(f'Web服务器启动成功: {Var.URL}')
            
            auto_download_status = "启用" if (Var and Var.AUTO_DOWNLOAD) else "禁用"
            log.info(f'直链功能已启用，将作为Telegram媒体文件的前置处理')
            log.info(f'自动下载功能: {auto_download_status}')
        except Exception as e:
            log.error(f'启动直链功能失败: {e}', exc_info=True)
            log.warning('直链功能启动失败，但主应用将继续运行')


async def cleanup():
    """清理资源"""
    if stream_server:
        await stream_server.cleanup()
    if ENABLE_STREAM:
        try:
            await StreamBot.stop()
        except:
            pass


loop = asyncio.get_event_loop()
try:
    loop.create_task(main())
    loop.run_forever()
except KeyboardInterrupt:
    pass
finally:
    loop.run_until_complete(cleanup())
    loop.stop()
