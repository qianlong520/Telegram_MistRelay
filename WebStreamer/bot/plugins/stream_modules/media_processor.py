# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
媒体处理模块
处理媒体组和单个媒体文件，生成直链并添加到下载队列
"""

import logging
import asyncio
from collections import defaultdict
from urllib.parse import quote_plus
from pyrogram import filters, errors
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums.parse_mode import ParseMode

from WebStreamer.vars import Var
from WebStreamer.bot import StreamBot, logger
from WebStreamer.utils import get_hash, get_name
from db import save_tg_media, create_download, mark_download_started

# 媒体组缓存：用于收集同一媒体组的所有消息
media_group_cache = defaultdict(list)
media_group_tasks = {}


def get_stream_runtime_flags():
    """动态读取直链处理相关配置，避免必须重启服务。"""
    from configer import get_config_value

    tg_disk_only = get_config_value('STREAM_TG_DISK_ONLY', False)
    auto_download = get_config_value('STREAM_AUTO_DOWNLOAD', True)
    send_stream_link = get_config_value('SEND_STREAM_LINK', False)
    return {
        'tg_disk_only': tg_disk_only,
        'auto_download': auto_download and not tg_disk_only,
        'send_stream_link': send_stream_link,
    }


async def process_media_group(messages: list, queue_reply_msg=None):
    """
    处理媒体组：一次性转发所有媒体文件到频道，保持消息完整性
    
    Args:
        messages: 媒体组消息列表
        queue_reply_msg: 排队通知消息（如果存在，将在处理完成后更新或删除）
    """
    # 延迟导入避免循环依赖
    from .utils import aria2_client, should_download_file
    runtime_flags = get_stream_runtime_flags()
    tg_disk_only = runtime_flags['tg_disk_only']
    auto_download_enabled = runtime_flags['auto_download']
    send_stream_link = runtime_flags['send_stream_link']
    
    if not messages:
        return
    
    first_msg = messages[0]
    
    # 保留排队通知消息，用于清理完成后更新（不再删除）
    # 如果后续没有创建下载任务，会在发送直链信息后删除
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
        
        # 为每个媒体文件生成直链，并把已转发到频道的消息写入 tg_media
        stream_links = []
        download_entries = []

        for original_msg, log_msg in forwarded_messages:
            try:
                file_hash = get_hash(log_msg, Var.HASH_LENGTH)
                stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(original_msg))}?hash={file_hash}"
                short_link = f"{Var.URL}{file_hash}{log_msg.id}"
                file_name = get_name(original_msg)
                log_media = getattr(log_msg, log_msg.media.value, None) if getattr(log_msg, "media", None) else None
                file_unique_id = None

                if log_media:
                    try:
                        file_unique_id = save_tg_media(log_msg, log_media)
                    except Exception as db_e:
                        logger.error(f"记录频道媒体到数据库失败: {db_e}", exc_info=True)

                should_download = should_download_file(original_msg)
                should_enqueue_download = should_download and not tg_disk_only
                
                link_entry = {
                    'name': file_name,
                    'full_link': stream_link,
                    'short_link': short_link,
                    'should_download': should_enqueue_download,
                    'original_msg': original_msg,
                    'log_msg': log_msg,
                    'log_media': log_media,
                    'file_unique_id': file_unique_id,
                }
                stream_links.append(link_entry)
                
                # 检查是否应该下载（图片类不下载）
                if should_enqueue_download:
                    download_entries.append(link_entry)
                    logger.info(f"直链已生成（将下载）： {stream_link} for {first_msg.from_user.first_name}")
                elif tg_disk_only:
                    logger.info(f"文件已直转TG网盘： {stream_link} for {first_msg.from_user.first_name}")
                else:
                    logger.info(f"直链已生成（仅转发）： {stream_link} for {first_msg.from_user.first_name}")
                    
            except Exception as e:
                logger.error(f"生成直链失败: {e}", exc_info=True)
        
        # 构建回复消息
        if len(stream_links) == 1:
            # 单个文件
            link_info = stream_links[0]
            if link_info['should_download']:
                download_status = "（将下载）"
            elif tg_disk_only:
                download_status = "（仅转发到TG网盘）"
            else:
                download_status = "（仅转发）"
            reply_text = (
                f"🔗 <b>直链已准备好{download_status}</b>\n\n"
                f"📁 <b>文件:</b> <code>{link_info['name']}</code>\n\n"
                f"🌐 <b>完整链接:</b>\n<code>{link_info['full_link']}</code>\n\n"
                f"🔗 <b>短链接:</b>\n<code>{link_info['short_link']}</code>"
            )
            main_link = link_info['full_link']
        else:
            # 多个文件（媒体组）
            download_count = len(download_entries)
            skip_count = len(stream_links) - download_count
            reply_text = (
                f"🔗 <b>媒体组直链已准备好</b>\n\n"
                f"📊 <b>统计信息:</b>\n"
                f"  • 总文件数: {len(stream_links)}\n"
            )
            if download_count > 0:
                reply_text += f"  • ⬇️ 将下载: {download_count}\n"
            if skip_count > 0 and tg_disk_only:
                reply_text += f"  • 📦 已转入TG网盘: {skip_count}\n"
            elif skip_count > 0:
                reply_text += f"  • 📷 仅转发: {skip_count}\n"
            reply_text += "\n📋 <b>文件列表:</b>\n\n"
            
            for i, link_info in enumerate(stream_links, 1):
                is_download = link_info['should_download']
                if is_download:
                    status_icon = "⬇️"
                    status_text = "将下载"
                elif tg_disk_only:
                    status_icon = "📦"
                    status_text = "仅转发到TG网盘"
                else:
                    status_icon = "📷"
                    status_text = "仅转发"
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
        task_gids = []  # 记录添加的下载任务GID
        if auto_download_enabled and aria2_client and is_admin and download_entries:
            try:
                # 批量添加下载任务，智能等待避免并发过高
                success_count = 0
                failed_count = 0
                
                # 使用统一的等待槽位函数（确保不超过最大并发数）
                from .utils import wait_for_download_slot
                
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
                            logger.error(f"检查任务状态失败: {e}", exc_info=True)
                            # 如果无法检查状态，假设成功
                            return True
                
                # 动态获取配置值
                from configer import get_config_value
                skip_small_files = get_config_value('SKIP_SMALL_FILES', False)
                min_file_size_mb = get_config_value('MIN_FILE_SIZE_MB', 100)
                min_size_bytes = min_file_size_mb * 1024 * 1024 if skip_small_files else 0
                
                # 如果启用小文件跳过，允许并发下载；否则串行下载
                if skip_small_files:
                    logger.info(f"[媒体组下载] 已启用小文件跳过，将并发添加 {len(download_entries)} 个下载任务")
                else:
                    logger.info(f"[媒体组下载] 未启用小文件跳过，将串行添加 {len(download_entries)} 个下载任务（避免并发过高）")
                
                for i, entry in enumerate(download_entries):
                    link = entry['full_link']
                    retry_count = 0
                    max_retries = 3
                    added_successfully = False
                    
                    # 检查文件大小（在添加下载任务之前）
                    if skip_small_files:
                        try:
                            original_msg = entry['original_msg']
                            if original_msg and original_msg.media:
                                media = getattr(original_msg, original_msg.media.value, None)
                                if media:
                                    file_size = getattr(media, 'file_size', None)
                                    if file_size and file_size > 0 and file_size < min_size_bytes:
                                        file_name = getattr(media, 'file_name', None) or f"文件{i+1}"
                                        size_mb = file_size / 1024 / 1024
                                        logger.info(f"[跳过小文件] 媒体组文件 {file_name} 大小 {file_size} 字节 ({size_mb:.2f}MB) 小于 {min_file_size_mb}MB，静默跳过下载")
                                        # 跳过这个文件，继续处理下一个（静默处理，不发送通知）
                                        continue
                        except Exception as e:
                            logger.error(f"检查文件大小失败: {e}", exc_info=True)
                            # 如果检查失败，继续添加下载任务
                    
                    while retry_count <= max_retries and not added_successfully:
                        try:
                            # 无论是否启用小文件跳过，都必须等待空闲槽位，确保不超过最大并发数
                            # 只有在添加第一个任务且不是重试时，才可能跳过等待（但为了安全，仍然检查）
                            if i > 0 or retry_count > 0:
                                await wait_for_download_slot(max_wait_time=60)
                            else:
                                # 即使是第一个任务，也检查一下当前任务数，确保不超过限制
                                try:
                                    active_tasks = await aria2_client.tell_active()
                                    waiting_tasks = await aria2_client.tell_waiting(0, 100)
                                    current_count = len(active_tasks) + len(waiting_tasks)
                                    from .utils import get_aria2_max_concurrent_downloads
                                    max_concurrent = await get_aria2_max_concurrent_downloads()
                                    if current_count >= max_concurrent:
                                        logger.debug(f"当前任务数已达上限 ({current_count}/{max_concurrent})，等待空闲槽位")
                                        await wait_for_download_slot(max_wait_time=60)
                                except Exception as e:
                                    logger.debug(f"检查任务数失败，继续添加: {e}")
                            
                            # 添加任务
                            result = await aria2_client.add_uri(uris=[link])
                            
                            # 检查返回结果
                            if result and 'result' in result:
                                gid = result.get('result')

                                # 记录 Telegram 媒体与下载任务到数据库
                                try:
                                    file_unique_id = entry['file_unique_id']
                                    if not file_unique_id and entry['log_media']:
                                        file_unique_id = save_tg_media(entry['log_msg'], entry['log_media'])
                                    if file_unique_id:
                                        create_download(file_unique_id, gid, link)
                                except Exception as db_e:
                                    logger.error(f"记录下载任务到数据库失败: {db_e}", exc_info=True)
                                
                                # 如果启用小文件跳过，允许并发下载（不等待任务开始）
                                # 如果未启用小文件跳过，等待任务开始以确保稳定性
                                if skip_small_files:
                                    # 并发模式：不等待任务开始，直接标记为成功并继续
                                    try:
                                        mark_download_started(gid)
                                    except Exception as db_e:
                                        logger.error(f"更新任务开始状态失败: {db_e}", exc_info=True)
                                    success_count += 1
                                    added_successfully = True
                                    task_gids.append(gid)  # 记录任务GID
                                    # 注册GID和队列通知消息的关联（用于清理完成后更新通知）
                                    if queue_reply_msg:
                                        try:
                                            from .utils import register_gid_queue_msg
                                            register_gid_queue_msg(gid, queue_reply_msg)
                                        except Exception as reg_e:
                                            logger.debug(f"注册GID队列消息失败: {reg_e}")
                                    logger.debug(f"成功添加任务 {i+1}/{len(download_entries)}: {link[:50]}...")
                                else:
                                    # 串行模式：等待任务真正开始
                                    if await wait_for_task_start(gid):
                                        try:
                                            mark_download_started(gid)
                                        except Exception as db_e:
                                            logger.error(f"更新任务开始状态失败: {db_e}", exc_info=True)
                                        success_count += 1
                                        added_successfully = True
                                        task_gids.append(gid)  # 记录任务GID
                                        # 注册GID和队列通知消息的关联（用于清理完成后更新通知）
                                        if queue_reply_msg:
                                            try:
                                                from .utils import register_gid_queue_msg
                                                register_gid_queue_msg(gid, queue_reply_msg)
                                            except Exception as reg_e:
                                                logger.debug(f"注册GID队列消息失败: {reg_e}")
                                        logger.debug(f"成功添加任务 {i+1}/{len(download_entries)}: {link[:50]}...")
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
                            
                            # 如果未启用小文件跳过，添加延迟避免请求过快
                            # 如果启用小文件跳过，允许并发下载，不需要延迟
                            if not skip_small_files and added_successfully and i < len(download_entries) - 1:
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
                    logger.info(f"已将 {success_count}/{len(download_entries)} 个直链添加到aria2下载队列")
                else:
                    reply_text += "\n\n⚠️ <b>所有任务添加失败，请手动添加</b>"
                    logger.error(f"所有 {len(download_entries)} 个直链添加失败")
            except Exception as e:
                logger.error(f"批量添加直链到aria2失败: {e}", exc_info=True)
                reply_text += "\n\n⚠️ <b>添加到下载队列失败，请手动添加</b>"
        
        # 回复用户（只回复第一条消息）- 如果启用了发送直链信息
        reply_msg = None
        if send_stream_link:
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
            # 如果不发送直链信息，更新队列通知消息为处理中状态
            if queue_reply_msg:
                try:
                    processing_text = (
                        "✅ <b>已收到您的消息</b>\n\n"
                        "📥 消息正在处理中...\n"
                        f"📊 共 {len(stream_links)} 个文件\n"
                        f"⬇️ {len(download_entries)} 个将下载\n"
                        "🔄 请稍候，处理完成后会通知您"
                    )
                    await queue_reply_msg.edit_text(
                        text=processing_text,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.debug(f"更新队列通知消息失败: {e}")
            
            # 记录日志
            logger.info(f"已处理媒体组（不发送直链信息）：共 {len(stream_links)} 个文件，{len(download_entries)} 个已添加到下载队列")
        
        # 如果没有创建下载任务，且没有发送直链信息，保留队列通知消息以便后续更新
        # 如果创建了下载任务，队列通知消息会在清理完成时更新为完成状态
        # 如果没有创建下载任务且发送了直链信息，队列通知消息已被删除，不需要处理
        
        # 返回任务GID列表，供队列处理器等待完成
        return task_gids
    except Exception as e:
        logger.error(f"处理媒体组失败: {e}", exc_info=True)
        try:
            error_reply = (
                f'❌ <b>处理失败</b>\n\n'
                f'⚠️ 处理媒体组时出错，请稍后重试'
            )
            await first_msg.reply(error_reply, quote=True, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return []  # 返回空列表


async def process_single_media(m: Message, queue_reply_msg=None):
    """
    处理单个媒体文件
    
    Args:
        m: 消息对象
        queue_reply_msg: 排队通知消息（如果存在，将在处理完成后更新或删除）
    """
    # 延迟导入避免循环依赖
    from .utils import aria2_client, should_download_file
    runtime_flags = get_stream_runtime_flags()
    tg_disk_only = runtime_flags['tg_disk_only']
    auto_download_enabled = runtime_flags['auto_download']
    send_stream_link = runtime_flags['send_stream_link']
    
    if not Var.ENABLE_STREAM:
        return
    
    # 如果有排队通知，且启用了发送直链信息，则删除它（因为我们要发送实际的处理结果）
    # 如果没有启用发送直链信息，保留队列通知消息，以便后续更新为完成状态
    if queue_reply_msg and send_stream_link:
        try:
            await queue_reply_msg.delete()
        except Exception as e:
            logger.debug(f"删除排队通知失败: {e}")
    
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
        log_media = getattr(log_msg, log_msg.media.value, None) if getattr(log_msg, "media", None) else None
        saved_file_unique_id = None
        if log_media:
            try:
                saved_file_unique_id = save_tg_media(log_msg, log_media)
            except Exception as db_e:
                logger.error(f"记录频道媒体到数据库失败: {db_e}", exc_info=True)
        file_hash = get_hash(log_msg, Var.HASH_LENGTH)
        stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(m))}?hash={file_hash}"
        short_link = f"{Var.URL}{file_hash}{log_msg.id}"
        
        # 检查是否应该下载
        should_download = should_download_file(m)
        should_enqueue_download = should_download and not tg_disk_only
        if should_enqueue_download:
            download_status = "（将下载）"
        elif tg_disk_only:
            download_status = "（仅转发到TG网盘）"
        else:
            download_status = "（仅转发）"
        logger.info(f"直链已生成{download_status}： {stream_link} for {m.from_user.first_name}")
        
        # 后续处理：自动将直链添加到aria2下载队列（如果启用且是管理员，且文件类型需要下载）
        download_added = False
        task_gid = None  # 记录任务GID
        if auto_download_enabled and aria2_client and should_enqueue_download:
            # 检查是否是管理员
            is_admin = False
            if Var.ADMIN_ID:
                if isinstance(Var.ADMIN_ID, list):
                    is_admin = str(m.from_user.id) in [str(admin_id) for admin_id in Var.ADMIN_ID]
                else:
                    is_admin = str(m.from_user.id) == str(Var.ADMIN_ID)
            
            if is_admin:
                try:
                    # 检查文件大小（在添加下载任务之前）
                    media = m.document or m.video or m.audio or m.photo or m.animation
                    file_size = getattr(media, 'file_size', None) if media else None
                    
                    # 动态获取配置值
                    from configer import get_config_value
                    skip_small_files = get_config_value('SKIP_SMALL_FILES', False)
                    min_file_size_mb = get_config_value('MIN_FILE_SIZE_MB', 100)
                    
                    # 如果启用了跳过小文件功能，且文件大小已知且小于限制，则跳过
                    skip_this_file = False
                    if skip_small_files and file_size and file_size > 0:
                        min_size_bytes = min_file_size_mb * 1024 * 1024
                        if file_size < min_size_bytes:
                            file_name = getattr(media, 'file_name', None) or get_name(m) or '未知文件'
                            size_mb = file_size / 1024 / 1024
                            logger.info(f"[跳过小文件] 文件 {file_name} 大小 {file_size} 字节 ({size_mb:.2f}MB) 小于 {min_file_size_mb}MB，静默跳过下载")
                            # 不添加到下载队列，但继续执行后续逻辑（返回直链等）（静默处理，不发送通知）
                            download_added = False
                            task_gid = None
                            skip_this_file = True
                    
                    # 将直链URL添加到aria2下载队列（如果文件未被跳过）
                    if not skip_this_file:
                        # 等待有空闲下载槽位，确保不超过最大并发数
                        from .utils import wait_for_download_slot
                        await wait_for_download_slot(max_wait_time=60)
                        
                        result = await aria2_client.add_uri(uris=[stream_link])
                        if result and 'result' in result:
                            task_gid = result.get('result')
                            # 记录 Telegram 媒体与下载任务到数据库
                            try:
                                file_unique_id = saved_file_unique_id
                                if not file_unique_id and log_media:
                                    file_unique_id = save_tg_media(log_msg, log_media)
                                if file_unique_id:
                                    create_download(file_unique_id, task_gid, stream_link)
                                    mark_download_started(task_gid)
                            except Exception as db_e:
                                logger.error(f"记录单文件下载任务到数据库失败: {db_e}", exc_info=True)
                            
                            # 注册GID和队列通知消息的关联（用于清理完成后更新通知）
                            try:
                                from .utils import register_gid_queue_msg
                                register_gid_queue_msg(task_gid, queue_reply_msg, original_msg=m)
                            except Exception as reg_e:
                                logger.debug(f"注册GID队列消息失败: {reg_e}")
                            
                        download_added = True
                        logger.info(f"已将直链添加到aria2下载队列: {stream_link}, GID: {task_gid}")
                except Exception as e:
                    logger.error(f"添加直链到aria2失败: {e}", exc_info=True)
        
        # 返回直链给用户（如果启用了发送直链信息）
        if send_stream_link:
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
            elif auto_download_enabled and aria2_client and should_enqueue_download:
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
            # 如果不发送直链信息，更新队列通知消息为处理中状态
            if queue_reply_msg:
                try:
                    processing_text = (
                        "✅ <b>已收到您的消息</b>\n\n"
                        "📥 消息正在处理中...\n"
                        "🔄 请稍候，处理完成后会通知您"
                    )
                    await queue_reply_msg.edit_text(
                        text=processing_text,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.debug(f"更新队列通知消息失败: {e}")
            
            # 记录日志
            if download_added:
                logger.info(f"已处理文件（不发送直链信息）：{get_name(m)}，已添加到下载队列")
            else:
                logger.info(f"已处理文件（不发送直链信息）：{get_name(m)}，仅转发")
        
        # 如果没有创建下载任务，且没有发送直链信息，保留队列通知消息以便后续更新
        # 如果创建了下载任务，队列通知消息会在清理完成时更新为完成状态
        # 如果没有创建下载任务且发送了直链信息，队列通知消息已被删除，不需要处理
        
        # 返回任务GID列表，供队列处理器等待完成
        return [task_gid] if task_gid else []
    except Exception as e:
        logger.error(f"生成直链失败: {e}", exc_info=True)
        await m.reply("生成直链时出错，请稍后重试", quote=True)
        return []  # 返回空列表


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
    # 延迟导入避免循环依赖
    from .queue_manager import enqueue_message_task
    
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
                # 将媒体组处理任务加入队列，而不是直接执行
                # 注意：排队通知会在enqueue_message_task中自动发送
                enqueue_message_task(process_media_group, messages)
        
        task = asyncio.create_task(delayed_process())
        media_group_tasks[group_id] = task
    else:
        # 单个媒体文件：加入队列处理，而不是立即处理
        enqueue_message_task(process_single_media, m)
