# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import logging
import asyncio
from collections import defaultdict
from pyrogram import filters, errors
from WebStreamer.vars import Var
from urllib.parse import quote_plus
from WebStreamer.bot import StreamBot, logger
from WebStreamer.utils import get_hash, get_name
from pyrogram.enums.parse_mode import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# 导入aria2客户端（延迟导入，避免循环依赖）
aria2_client = None

# 媒体组缓存：用于收集同一媒体组的所有消息
media_group_cache = defaultdict(list)
media_group_tasks = {}

def set_aria2_client(client):
    """设置aria2客户端"""
    global aria2_client
    aria2_client = client


def should_download_file(message: Message) -> bool:
    """
    判断文件是否应该下载
    返回 True 表示应该下载，False 表示只转发不下载
    现在所有媒体文件都会下载，包括图片和贴纸
    """
    # 检查是否有任何媒体文件
    if (message.photo or message.video or message.animation or message.video_note or 
        message.document or message.audio or message.voice or message.sticker):
        return True
    
    # 默认不下载（如果没有媒体文件）
    return False


async def process_media_group(messages: list):
    """
    处理媒体组：一次性转发所有媒体文件到频道，保持消息完整性
    """
    if not messages:
        return
    
    first_msg = messages[0]
    # 生成唯一的媒体组ID（使用时间戳和第一条消息ID）
    media_group_id = f"mg_{first_msg.chat.id}_{first_msg.media_group_id}_{first_msg.id}"
    
    # 权限检查
    if Var.ALLOWED_USERS and not ((str(first_msg.from_user.id) in Var.ALLOWED_USERS) or (first_msg.from_user.username in Var.ALLOWED_USERS)):
        return
    
    # BIN_CHANNEL检查
    if not Var.BIN_CHANNEL:
        logger.warning(f"BIN_CHANNEL未配置，无法为 {first_msg.from_user.first_name} 生成直链")
        return
    
    try:
        # 一次性转发整个媒体组到频道（保持消息完整性）
        # 使用 forward_messages 一次性转发所有消息，保持媒体组完整性
        try:
            # 获取所有消息的 ID
            message_ids = [msg.id for msg in messages]
            chat_id = messages[0].chat.id
            
            # 一次性转发整个媒体组
            forwarded_msgs = await StreamBot.forward_messages(
                chat_id=Var.BIN_CHANNEL,
                from_chat_id=chat_id,
                message_ids=message_ids
            )
            
            # 构建 (原始消息, 转发消息) 的配对列表
            forwarded_messages = []
            if isinstance(forwarded_msgs, list):
                # 如果返回的是列表（多条消息）
                for i, log_msg in enumerate(forwarded_msgs):
                    if i < len(messages):
                        forwarded_messages.append((messages[i], log_msg))
            else:
                # 如果返回的是单个消息对象（理论上不应该发生）
                forwarded_messages.append((messages[0], forwarded_msgs))
                
        except Exception as e:
            logger.error(f"转发媒体组失败: {e}", exc_info=True)
            # 如果一次性转发失败，回退到逐条转发
            forwarded_messages = []
            for msg in messages:
                try:
                    log_msg = await msg.forward(chat_id=Var.BIN_CHANNEL)
                    forwarded_messages.append((msg, log_msg))
                except Exception as e2:
                    logger.error(f"转发单条消息失败: {e2}", exc_info=True)
        
        if not forwarded_messages:
            return
        
        # 为每个媒体文件生成直链
        stream_links = []
        download_links = []
        
        for original_msg, log_msg in forwarded_messages:
            try:
                file_hash = get_hash(log_msg, Var.HASH_LENGTH)
                stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(original_msg))}?hash={file_hash}"
                short_link = f"{Var.URL}{file_hash}{log_msg.id}"
                file_name = get_name(original_msg)
                
                stream_links.append({
                    'name': file_name,
                    'full_link': stream_link,
                    'short_link': short_link
                })
                
                # 检查是否应该下载（图片类不下载）
                if should_download_file(original_msg):
                    download_links.append(stream_link)
                    logger.info(f"直链已生成（将下载）： {stream_link} for {first_msg.from_user.first_name}")
                else:
                    logger.info(f"直链已生成（仅转发）： {stream_link} for {first_msg.from_user.first_name}")
                    
            except Exception as e:
                logger.error(f"生成直链失败: {e}", exc_info=True)
        
        # 构建回复消息
        if len(stream_links) == 1:
            # 单个文件
            link_info = stream_links[0]
            download_status = "（将下载）" if len(download_links) > 0 else "（仅转发）"
            reply_text = (
                f"🔗 <b>直链已准备好{download_status}</b>\n\n"
                f"📁 <b>文件:</b> <code>{link_info['name']}</code>\n\n"
                f"🌐 <b>完整链接:</b>\n<code>{link_info['full_link']}</code>\n\n"
                f"🔗 <b>短链接:</b>\n<code>{link_info['short_link']}</code>"
            )
            main_link = link_info['full_link']
        else:
            # 多个文件（媒体组）
            download_count = len(download_links)
            skip_count = len(stream_links) - download_count
            reply_text = (
                f"🔗 <b>媒体组直链已准备好</b>\n\n"
                f"📊 <b>统计信息:</b>\n"
                f"  • 总文件数: {len(stream_links)}\n"
            )
            if download_count > 0:
                reply_text += f"  • ⬇️ 将下载: {download_count}\n"
            if skip_count > 0:
                reply_text += f"  • 📷 仅转发: {skip_count}\n"
            reply_text += "\n📋 <b>文件列表:</b>\n\n"
            
            for i, link_info in enumerate(stream_links, 1):
                # 检查这个文件是否在下载列表中
                is_download = link_info['full_link'] in download_links
                status_icon = "⬇️" if is_download else "📷"
                status_text = "将下载" if is_download else "仅转发"
                reply_text += (
                    f"{status_icon} <b>{i}. {link_info['name']}</b>\n"
                    f"   <code>{link_info['full_link']}</code>\n"
                    f"   <i>{status_text}</i>\n\n"
                )
            main_link = stream_links[0]['full_link'] if stream_links else None
        
        # 检查是否是管理员
        is_admin = False
        if Var.ADMIN_ID:
            if isinstance(Var.ADMIN_ID, list):
                is_admin = str(first_msg.from_user.id) in [str(admin_id) for admin_id in Var.ADMIN_ID]
            else:
                is_admin = str(first_msg.from_user.id) == str(Var.ADMIN_ID)
        
        # 自动添加到aria2下载队列（如果启用且是管理员）
        if Var.AUTO_DOWNLOAD and aria2_client and is_admin and download_links:
            try:
                # 批量添加下载任务，智能等待避免并发过高
                success_count = 0
                failed_count = 0
                max_concurrent = 5  # aria2默认最大并发数
                max_wait_time = 30  # 最大等待时间（秒）
                
                async def wait_for_slot():
                    """等待有空闲下载槽位"""
                    wait_start = asyncio.get_event_loop().time()
                    while True:
                        try:
                            # 获取当前正在下载和等待的任务数
                            active_tasks = await aria2_client.tell_active()
                            waiting_tasks = await aria2_client.tell_waiting(0, 100)
                            current_count = len(active_tasks) + len(waiting_tasks)
                            
                            # 如果有空闲位置（至少留一个位置），返回
                            if current_count < max_concurrent - 1:
                                return True
                            
                            # 检查是否超时
                            if asyncio.get_event_loop().time() - wait_start > max_wait_time:
                                logger.warning(f"等待空闲槽位超时，当前任务数: {current_count}")
                                return False
                            
                            # 等待1秒后重试
                            await asyncio.sleep(1.0)
                        except Exception as e:
                            logger.error(f"检查aria2任务状态失败: {e}")
                            # 如果检查失败，等待一下再继续
                            await asyncio.sleep(1.0)
                            return True  # 假设有空闲位置，继续尝试
                
                async def wait_for_task_start(gid, timeout=5):
                    """等待任务真正开始（状态变为active或waiting）"""
                    wait_start = asyncio.get_event_loop().time()
                    while True:
                        try:
                            status = await aria2_client.tell_status(gid)
                            task_status = status.get('status', '')
                            
                            if task_status in ['active', 'waiting']:
                                return True
                            
                            if task_status == 'complete':
                                return True  # 任务已完成，也算成功
                            
                            if task_status == 'error' or task_status == 'removed':
                                return False  # 任务失败或被移除
                            
                            # 检查超时
                            if asyncio.get_event_loop().time() - wait_start > timeout:
                                logger.warning(f"等待任务开始超时，GID: {gid}, 状态: {task_status}")
                                return False
                            
                            await asyncio.sleep(0.3)
                        except Exception as e:
                            logger.error(f"检查任务状态失败: {e}")
                            # 如果无法检查状态，假设成功
                            return True
                
                for i, link in enumerate(download_links):
                    retry_count = 0
                    max_retries = 3
                    added_successfully = False
                    
                    while retry_count <= max_retries and not added_successfully:
                        try:
                            # 等待有空闲槽位（除了第一个任务和重试时）
                            if i > 0 or retry_count > 0:
                                await wait_for_slot()
                            
                            # 添加任务
                            result = await aria2_client.add_uri(uris=[link])
                            
                            # 检查返回结果
                            if result and 'result' in result:
                                gid = result.get('result')
                                
                                # 等待任务真正开始
                                if await wait_for_task_start(gid):
                                    success_count += 1
                                    added_successfully = True
                                    logger.debug(f"成功添加任务 {i+1}/{len(download_links)}: {link[:50]}...")
                                else:
                                    # 任务被中止或失败，重试
                                    if retry_count < max_retries:
                                        retry_count += 1
                                        logger.warning(f"任务被中止，重试 {retry_count}/{max_retries}: {link[:50]}...")
                                        await asyncio.sleep(2)  # 重试前等待2秒
                                    else:
                                        failed_count += 1
                                        logger.error(f"任务添加失败，已达到最大重试次数: {link[:50]}...")
                                        break  # 达到最大重试次数，跳出重试循环
                            else:
                                # 添加失败
                                error_msg = result.get('error', {}).get('message', '未知错误') if result else '无返回结果'
                                if retry_count < max_retries:
                                    retry_count += 1
                                    logger.warning(f"添加任务失败，重试 {retry_count}/{max_retries}: {error_msg}")
                                    await asyncio.sleep(1)  # 重试前等待1秒
                                else:
                                    failed_count += 1
                                    logger.error(f"添加任务失败 (第{i+1}个): {error_msg}")
                                    break  # 达到最大重试次数，跳出重试循环
                            
                            # 添加延迟，避免请求过快
                            if added_successfully and i < len(download_links) - 1:
                                await asyncio.sleep(1.0)  # 成功添加后延迟1秒，确保任务稳定
                                
                        except Exception as e:
                            if retry_count < max_retries:
                                retry_count += 1
                                logger.warning(f"添加任务异常，重试 {retry_count}/{max_retries}: {e}")
                                await asyncio.sleep(1)  # 重试前等待1秒
                            else:
                                failed_count += 1
                                logger.error(f"添加直链到aria2失败 (第{i+1}个): {e}", exc_info=True)
                                break  # 达到最大重试次数，跳出重试循环
                
                # 根据结果更新回复消息
                if success_count > 0:
                    reply_text += "\n\n📥 <b>下载队列状态:</b>\n"
                    if failed_count > 0:
                        reply_text += f"  ✅ 成功添加: {success_count} 个任务\n"
                        reply_text += f"  ⚠️ 添加失败: {failed_count} 个任务"
                    else:
                        reply_text += f"  ✅ 已自动添加 {success_count} 个任务到下载队列"
                    logger.info(f"已将 {success_count}/{len(download_links)} 个直链添加到aria2下载队列")
                else:
                    reply_text += "\n\n⚠️ <b>所有任务添加失败，请手动添加</b>"
                    logger.error(f"所有 {len(download_links)} 个直链添加失败")
            except Exception as e:
                logger.error(f"批量添加直链到aria2失败: {e}", exc_info=True)
                reply_text += "\n\n⚠️ <b>添加到下载队列失败，请手动添加</b>"
        
        # 回复用户（只回复第一条消息）- 如果启用了发送直链信息
        reply_msg = None
        if Var.SEND_STREAM_LINK:
            try:
                buttons = []
                if main_link:
                    buttons.append([InlineKeyboardButton("🔗 打开直链", url=main_link)])
                
                reply_msg = await first_msg.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
                )
            except errors.ButtonUrlInvalid:
                reply_msg = await first_msg.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                )
        else:
            # 如果不发送直链信息，只记录日志
            logger.info(f"已处理媒体组（不发送直链信息）：共 {len(stream_links)} 个文件，{len(download_links)} 个已添加到下载队列")
    except Exception as e:
        logger.error(f"处理媒体组失败: {e}", exc_info=True)
        try:
            error_reply = (
                f'❌ <b>处理失败</b>\n\n'
                f'⚠️ 处理媒体组时出错，请稍后重试'
            )
            await first_msg.reply(error_reply, quote=True, parse_mode=ParseMode.HTML)
        except:
            pass


async def process_single_media(m: Message):
    """
    处理单个媒体文件
    """
    if not Var.ENABLE_STREAM:
        return
    
    # 权限检查
    if Var.ALLOWED_USERS and not ((str(m.from_user.id) in Var.ALLOWED_USERS) or (m.from_user.username in Var.ALLOWED_USERS)):
        permission_msg = (
            f'🚫 <b>权限不足</b>\n\n'
            f'⚠️ 你没有权限使用这个机器人'
        )
        return await m.reply(permission_msg, quote=True, parse_mode=ParseMode.HTML)
    
    # BIN_CHANNEL检查
    if not Var.BIN_CHANNEL:
        logger.warning(f"BIN_CHANNEL未配置，无法为 {m.from_user.first_name} 生成直链")
        return await m.reply("直链功能未配置，请在配置文件中设置 BIN_CHANNEL", quote=True)
    
    try:
        # 转发到日志频道并生成直链
        log_msg = await m.forward(chat_id=Var.BIN_CHANNEL)
        file_hash = get_hash(log_msg, Var.HASH_LENGTH)
        stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(m))}?hash={file_hash}"
        short_link = f"{Var.URL}{file_hash}{log_msg.id}"
        
        # 检查是否应该下载
        should_download = should_download_file(m)
        download_status = "（将下载）" if should_download else "（仅转发）"
        logger.info(f"直链已生成{download_status}： {stream_link} for {m.from_user.first_name}")
        
        # 后续处理：自动将直链添加到aria2下载队列（如果启用且是管理员，且文件类型需要下载）
        download_added = False
        if Var.AUTO_DOWNLOAD and aria2_client and should_download:
            # 检查是否是管理员
            is_admin = False
            if Var.ADMIN_ID:
                if isinstance(Var.ADMIN_ID, list):
                    is_admin = str(m.from_user.id) in [str(admin_id) for admin_id in Var.ADMIN_ID]
                else:
                    is_admin = str(m.from_user.id) == str(Var.ADMIN_ID)
            
            if is_admin:
                try:
                    # 将直链URL添加到aria2下载队列
                    await aria2_client.add_uri(uris=[stream_link])
                    download_added = True
                    logger.info(f"已将直链添加到aria2下载队列: {stream_link}")
                except Exception as e:
                    logger.error(f"添加直链到aria2失败: {e}", exc_info=True)
        
        # 返回直链给用户（如果启用了发送直链信息）
        if Var.SEND_STREAM_LINK:
            file_name = ""
            if m.document:
                file_name = m.document.file_name or "未知文件"
            elif m.video:
                file_name = m.video.file_name or "视频文件"
            elif m.audio:
                file_name = m.audio.file_name or "音频文件"
            elif m.photo:
                file_name = "图片文件"
            elif m.animation:
                file_name = m.animation.file_name or "动画文件"
            else:
                file_name = "媒体文件"
            
            reply_text = (
                f"🔗 <b>直链已准备好{download_status}</b>\n\n"
                f"📁 <b>文件:</b> <code>{file_name}</code>\n\n"
                f"🌐 <b>完整链接:</b>\n<code>{stream_link}</code>\n\n"
                f"🔗 <b>短链接:</b>\n<code>{short_link}</code>"
            )
            
            if download_added:
                reply_text += "\n\n✅ <b>已自动添加到下载队列</b>"
            elif Var.AUTO_DOWNLOAD and aria2_client and should_download:
                reply_text += "\n\n⚠️ <b>添加到下载队列失败，请手动添加</b>"
            
            try:
                await m.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔗 打开直链", url=stream_link)]]
                    ),
                )
            except errors.ButtonUrlInvalid:
                await m.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                )
        else:
            # 如果不发送直链信息，只记录日志
            if download_added:
                logger.info(f"已处理文件（不发送直链信息）：{get_name(m)}，已添加到下载队列")
            else:
                logger.info(f"已处理文件（不发送直链信息）：{get_name(m)}，仅转发")
    except Exception as e:
        logger.error(f"生成直链失败: {e}", exc_info=True)
        await m.reply("生成直链时出错，请稍后重试", quote=True)


@StreamBot.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
        | filters.animation
        | filters.voice
        | filters.video_note
        | filters.photo
        | filters.sticker
    ),
    group=4,
)
async def media_receive_handler(_, m: Message):
    """
    处理Telegram媒体文件，生成直链（作为下载的前置功能）
    支持单个媒体文件和媒体组（保持消息完整性）
    """
    if not Var.ENABLE_STREAM:
        return
    
    # 检查是否是媒体组
    if m.media_group_id:
        # 媒体组：收集所有消息，延迟处理
        group_id = f"{m.chat.id}_{m.media_group_id}"
        media_group_cache[group_id].append(m)
        
        # 取消之前的任务（如果有）
        if group_id in media_group_tasks:
            media_group_tasks[group_id].cancel()
        
        # 创建新任务：等待500ms后处理（给其他消息时间到达）
        async def delayed_process():
            await asyncio.sleep(0.5)  # 等待500ms
            if group_id in media_group_cache:
                messages = media_group_cache.pop(group_id)
                # 按照消息 ID 排序，确保顺序正确
                messages.sort(key=lambda x: x.id)
                if group_id in media_group_tasks:
                    del media_group_tasks[group_id]
                await process_media_group(messages)
        
        task = asyncio.create_task(delayed_process())
        media_group_tasks[group_id] = task
    else:
        # 单个媒体文件：立即处理
        await process_single_media(m)

