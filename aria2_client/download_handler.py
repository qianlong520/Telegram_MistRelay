"""
Aria2下载事件处理模块
"""
import asyncio
import os
import time
from typing import Optional

from configer import ADMIN_ID, UP_TELEGRAM, UP_ONEDRIVE, FORWARD_ID, AUTO_DELETE_AFTER_UPLOAD
from util import get_file_name, byte2_readable, hum_convert, progress
from db import (
    mark_download_completed, mark_download_failed, get_download_id_by_gid,
    create_upload, get_uploads_by_download
)

from .constants import (
    DOWNLOAD_PROGRESS_UPDATE_INTERVAL,
    FILE_MODIFIED_TIME_WINDOW
)


class DownloadHandler:
    """处理Aria2下载事件"""
    
    def __init__(self, bot, download_messages, completed_gids, upload_handler, client=None):
        """
        初始化下载处理器
        
        Args:
            bot: Telegram bot实例
            download_messages: 下载消息字典 {gid: message}
            completed_gids: 已完成的GID集合
            upload_handler: 上传处理器实例
            client: Aria2客户端实例（用于移除任务）
        """
        self.bot = bot
        self.download_messages = download_messages
        self.completed_gids = completed_gids
        self.upload_handler = upload_handler
        self.client = client
    
    async def on_download_start(self, result, tell_status_func):
        """
        处理下载开始事件
        
        Args:
            result: Aria2事件结果
            tell_status_func: 获取任务状态的函数
        """
        gid = result['params'][0]['gid']
        print(f"===========下载 开始 任务id:{gid}")
        if self.bot:
            # 不发送初始消息，直接启动进度检查任务
            # 进度检查任务会在第一次运行时发送消息
            # 初始化消息对象存储
            self.download_messages[gid] = None
            asyncio.create_task(self.check_download_progress(gid, None, tell_status_func))
            print('轮训进度')
    
    async def check_download_progress(self, gid, msg, tell_status_func):
        """
        检查并更新下载进度
        只使用这一条消息来显示下载进度，避免重复消息
        
        Args:
            gid: 下载任务GID
            msg: 消息对象
            tell_status_func: 获取任务状态的函数
        """
        try:
            last_message_text = ""
            first_run = True
            # 立即获取任务状态，尽快发送第一条消息
            while True:
                task = await tell_status_func(gid)
                completedLength = task['completedLength']
                totalLength = task['totalLength']
                downloadSpeed = task['downloadSpeed']
                status = task['status']
                file_name = get_file_name(task)
                
                # 如果文件名为空，等待一下再重试
                if file_name == '':
                    if first_run:
                        await asyncio.sleep(0.5)  # 第一次运行时短暂等待
                    else:
                        await asyncio.sleep(3)
                    continue
                
                # 检查是否需要跳过小文件
                # 动态获取配置值（支持热重载）
                from configer import get_config_value
                skip_small_files = get_config_value('SKIP_SMALL_FILES', False)
                min_file_size_mb = get_config_value('MIN_FILE_SIZE_MB', 100)
                
                # 调试信息：仅在第一次运行时打印配置
                if first_run:
                    print(f"[跳过小文件] 配置检查: SKIP_SMALL_FILES={skip_small_files}, MIN_FILE_SIZE_MB={min_file_size_mb}MB, totalLength={totalLength}")
                
                # 如果文件大小还未获取到（totalLength为0或None），等待一下再检查
                if skip_small_files and (not totalLength or int(totalLength) == 0):
                    if first_run:
                        # 第一次运行时，如果文件大小为0，等待一下再重试
                        await asyncio.sleep(0.5)
                        continue
                
                if skip_small_files and totalLength and int(totalLength) > 0:
                    min_size_bytes = min_file_size_mb * 1024 * 1024  # 转换为字节
                    file_size_bytes = int(totalLength)
                    if file_size_bytes < min_size_bytes:
                        # 文件小于最小大小，移除任务
                        print(f"[跳过小文件] ✅ 任务 {gid} 文件大小 {byte2_readable(file_size_bytes)} ({file_size_bytes} 字节) 小于 {min_file_size_mb}MB ({min_size_bytes} 字节)，移除任务")
                        print(f"[跳过小文件] 配置: SKIP_SMALL_FILES={skip_small_files}, MIN_FILE_SIZE_MB={min_file_size_mb}")
                        
                        # 移除任务
                        if self.client:
                            try:
                                await self.client.remove(gid)
                                print(f"[跳过小文件] 已移除任务 {gid}")
                            except Exception as e:
                                print(f"[跳过小文件] 移除任务失败: {e}")
                        
                        # 静默处理，不发送通知消息
                        
                        # 记录到数据库：标记为失败状态，并在错误信息中记录跳过原因
                        try:
                            from db import mark_download_failed
                            error_msg = f"文件大小 {byte2_readable(int(totalLength))} 小于最小限制 {min_file_size_mb}MB，已跳过下载"
                            mark_download_failed(gid, error_msg)
                            print(f"[跳过小文件] 已记录到数据库: {gid}")
                        except Exception as e:
                            print(f"[跳过小文件] 记录到数据库失败: {e}")
                        
                        # 从消息字典中移除
                        if gid in self.download_messages:
                            del self.download_messages[gid]
                        
                        # 标记为已完成（避免重复处理）
                        self.completed_gids.add(gid)
                        
                        return  # 退出进度检查循环
                
                dir_path = task.get("dir", "")
                size = byte2_readable(int(totalLength))
                speed = hum_convert(int(downloadSpeed))
                prog = progress(int(totalLength), int(completedLength))
                
                if status != 'complete':
                    new_message_text = (
                        f'📥 <b>正在下载</b>\n\n'
                        f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                        f'📂 <b>路径:</b> <code>{dir_path}</code>\n\n'
                        f'📊 <b>进度:</b> {prog}\n'
                        f'💾 <b>大小:</b> {size}\n'
                        f'⚡ <b>速度:</b> {speed}/s'
                    )
                    # 第一次运行或消息内容不同时才更新
                    if first_run or new_message_text != last_message_text:
                        try:
                            if first_run and msg is None:
                                # 第一次运行且没有消息对象，立即发送新消息
                                if self.bot:
                                    msg = await self.bot.send_message(ADMIN_ID, new_message_text, parse_mode='html')
                                    # 保存消息对象到字典中，供后续使用
                                    self.download_messages[gid] = msg
                                    first_run = False
                                    last_message_text = new_message_text
                            elif msg:
                                # 编辑现有消息
                                try:
                                    msg = await self.bot.edit_message(msg, new_message_text, parse_mode='html')
                                    # 更新保存的消息对象
                                    self.download_messages[gid] = msg
                                    first_run = False
                                    last_message_text = new_message_text
                                except Exception as edit_err:
                                    # 如果编辑失败，尝试从字典中获取最新消息
                                    if gid in self.download_messages and self.download_messages[gid]:
                                        try:
                                            msg = self.download_messages[gid]
                                            msg = await self.bot.edit_message(msg, new_message_text, parse_mode='html')
                                            self.download_messages[gid] = msg
                                            first_run = False
                                            last_message_text = new_message_text
                                        except:
                                            pass
                        except Exception as e:
                            # 忽略"消息内容未修改"的错误
                            if "not modified" not in str(e).lower():
                                print(f"更新下载进度消息失败: {e}")
                    
                    # 第一次发送消息后，等待指定间隔再更新
                    await asyncio.sleep(DOWNLOAD_PROGRESS_UPDATE_INTERVAL)
                else:
                    # 下载完成，返回消息对象供后续使用
                    # 消息对象已保存在 self.download_messages[gid] 中
                    return

        except Exception as e:
            print('任务取消111')
            print(e)
    
    async def on_download_complete(self, result, tell_status_func):
        """
        处理下载完成事件
        
        Args:
            result: Aria2事件结果
            tell_status_func: 获取任务状态的函数
        """
        gid = result['params'][0]['gid']
        upload_id = None  # 初始化upload_id,避免在错误处理分支中使用未定义变量
        
        # 防重复处理：如果该GID已经处理过，直接跳过
        if gid in self.completed_gids:
            print(f"[防重复] 任务 {gid} 已在内存集合中，跳过重复通知")
            return
        
        # 立即添加到completed_gids，防止并发情况下的重复处理
        self.completed_gids.add(gid)
        print(f"[防重复] 任务 {gid} 已添加到内存集合")
            
        # 数据库查重（更可靠的持久化检查）
        try:
            download_id = get_download_id_by_gid(gid)
            if download_id:
                existing_uploads = get_uploads_by_download(download_id)
                for upload in existing_uploads:
                    if upload['status'] in ['completed', 'uploading', 'cleaned']:
                         print(f"[防重复] 检测到数据库中已有处理记录 (upload_id: {upload['id']}, 状态: {upload['status']})，跳过")
                         return
                print(f"[防重复] 数据库查重通过，download_id: {download_id}")
        except Exception as e:
            print(f"[防重复] 数据库查重失败: {e}，继续处理")
        
        print(f"===========下载 完成 任务id:{gid}")
        
        # 更新任务完成跟踪状态为 'completed'
        try:
            from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
            import asyncio as asyncio_module
            
            if task_completion_lock:
                async with task_completion_lock:
                    task_completion_tracker[gid] = {
                        'status': 'completed',
                        'completed_at': asyncio_module.get_event_loop().time()
                    }
        except Exception as e:
            print(f"更新任务完成跟踪状态失败: {e}")
        
        tellStatus = await tell_status_func(gid)
        files = tellStatus['files']
        
        # 获取保存的消息对象
        msg = self.download_messages.get(gid)
        
        for file in files:
            path = file['path']
            if self.bot:
                # 处理元数据文件
                if '[METADATA]' in path:
                    if os.path.exists(path):
                        os.unlink(path)
                    return
                
                # 检查文件是否存在，如果不存在则尝试查找实际文件
                actual_path = path
                if not os.path.exists(path):
                    # aria2 可能在下载时重命名了文件（添加 .1, .2 等后缀）
                    # 尝试查找实际文件
                    dir_path = os.path.dirname(path)
                    base_name = os.path.basename(path)
                    name_without_ext, ext = os.path.splitext(base_name)
                    
                    # 检查目录中是否有相似的文件名
                    if os.path.exists(dir_path):
                        try:
                            # 获取期望的文件大小
                            expected_size = int(tellStatus.get('totalLength', 0))
                            
                            for file_name in os.listdir(dir_path):
                                # 检查是否是同一个文件（可能是 aria2 重命名的版本）
                                if file_name.startswith(name_without_ext) and file_name.endswith(ext):
                                    potential_path = os.path.join(dir_path, file_name)
                                    # 验证文件大小是否合理（大于0）
                                    if os.path.exists(potential_path) and os.path.getsize(potential_path) > 0:
                                        # 检查是否是最近修改的（5分钟内）
                                        file_mtime = os.path.getmtime(potential_path)
                                        if time.time() - file_mtime < FILE_MODIFIED_TIME_WINDOW:  # 文件修改时间窗口内
                                            # 校验文件大小
                                            if expected_size > 0:
                                                from .utils import verify_file_size
                                                if not verify_file_size(potential_path, expected_size, tolerance=1024):
                                                    print(f"[下载] 文件大小不匹配,跳过: {potential_path}")
                                                    continue  # 继续查找其他文件
                                            
                                            actual_path = potential_path
                                            print(f"找到实际文件路径: {actual_path} (原始路径: {path})")
                                            break
                        except Exception as e:
                            print(f"查找文件时出错: {e}")

                
                # 再次检查文件是否存在
                if not os.path.exists(actual_path):
                    # 双重保险：再次检查数据库是否有成功上传记录（防止清理后的重复通知导致误报）
                    try:
                        download_id_check = get_download_id_by_gid(gid)
                        if download_id_check:
                            existing_uploads_check = get_uploads_by_download(download_id_check)
                            for up in existing_uploads_check:
                                # 只要有完成、上传中或已清理的记录，就说明之前的流程已经跑通了
                                if up['status'] in ['completed', 'uploading', 'cleaned']:
                                    print(f"虽然文件不存在，但发现已有处理记录 (ID: {up['id']}, 状态: {up['status']})，忽略文件缺失错误")
                                    return
                    except Exception as double_check_e:
                        print(f"二次查重失败: {double_check_e}")

                    print(f"文件不存在: {path} (尝试查找后仍不存在)")
                    
                    # 调试：列出目录文件
                    try:
                        dir_path = os.path.dirname(path)
                        if os.path.exists(dir_path):
                            files_in_dir = os.listdir(dir_path)
                            print(f"目录 {dir_path} 下的文件: {files_in_dir}")
                            # 记录到错误消息中（前5个文件）
                            file_list_str = ', '.join(files_in_dir[:5])
                            if len(files_in_dir) > 5:
                                file_list_str += ', ...'
                        else:
                            print(f"目录不存在: {dir_path}")
                            file_list_str = "目录不存在"
                    except Exception as ls_e:
                        print(f"列出目录失败: {ls_e}")
                        file_list_str = f"无法列出目录: {ls_e}"

                    # 记录失败
                    if upload_id:
                        try:
                            from db import mark_upload_failed
                            mark_upload_failed(upload_id, 'file_not_found', f"文件不存在: {actual_path or path}\n当前目录文件: {file_list_str}")
                        except Exception as e:
                            print(f"记录上传失败出错: {e}")
                    
                    if self.bot:
                        if msg:
                            try:
                                error_message = (
                                    f'❌ <b>文件不存在</b>\n\n'
                                    f'📁 <b>文件:</b> <code>{os.path.basename(path)}</code>\n'
                                    f'📂 <b>路径:</b> <code>{path}</code>\n\n'
                                    f'⚠️ 文件下载完成但文件不存在，可能已被删除或路径错误\n'
                                    f'🔍 <b>目录检查:</b> {file_list_str}'
                                )
                                await self.bot.edit_message(msg, error_message, parse_mode='html')
                            except Exception as e:
                                print(f"更新错误消息失败: {e}")
                    continue
                
                # 发送下载完成消息
                file_name_display = os.path.basename(actual_path)
                file_size = ""
                try:
                    if os.path.exists(actual_path):
                        file_size_bytes = os.path.getsize(actual_path)
                        file_size = byte2_readable(file_size_bytes)
                except:
                    pass
                
                # 标记数据库中的下载任务为完成
                try:
                    total_length = int(tellStatus.get("totalLength") or 0)
                    mark_download_completed(gid, actual_path, total_length or None)
                except Exception as db_e:
                    print(f"更新数据库下载完成状态出错: {db_e}")

                if msg:
                    try:
                        complete_text = (
                            f'✅ <b>下载完成</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name_display}</code>\n'
                            f'📂 <b>路径:</b> <code>{actual_path}</code>'
                        )
                        if file_size:
                            complete_text += f'\n💾 <b>大小:</b> {file_size}'
                        if actual_path != path:
                            complete_text += f'\n\n💡 <b>注意:</b> 文件路径已自动调整（原始路径: <code>{path}</code>）'
                        msg = await self.bot.edit_message(msg, complete_text, parse_mode='html')
                        self.download_messages[gid] = msg
                    except Exception as e:
                        print(f"更新下载完成消息失败: {e}")
                        # 如果编辑失败，发送新消息
                        complete_text = (
                            f'✅ <b>下载完成</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name_display}</code>\n'
                            f'📂 <b>路径:</b> <code>{actual_path}</code>'
                        )
                        if file_size:
                            complete_text += f'\n💾 <b>大小:</b> {file_size}'
                        if actual_path != path:
                            complete_text += f'\n\n💡 <b>注意:</b> 文件路径已自动调整（原始路径: <code>{path}</code>）'
                        msg = await self.bot.send_message(ADMIN_ID, complete_text, parse_mode='html')
                        self.download_messages[gid] = msg
                else:
                    # 如果没有保存的消息，发送新消息
                    complete_text = (
                        f'✅ <b>下载完成</b>\n\n'
                        f'📁 <b>文件:</b> <code>{file_name_display}</code>\n'
                        f'📂 <b>路径:</b> <code>{actual_path}</code>'
                    )
                    if file_size:
                        complete_text += f'\n💾 <b>大小:</b> {file_size}'
                    if actual_path != path:
                        complete_text += f'\n\n💡 <b>注意:</b> 文件路径已自动调整（原始路径: <code>{path}</code>）'
                    msg = await self.bot.send_message(ADMIN_ID, complete_text, parse_mode='html')
                    self.download_messages[gid] = msg
                
                # 根据配置选择上传方式
                if UP_ONEDRIVE:
                    # 创建上传记录
                    upload_id = None
                    try:
                        download_id = get_download_id_by_gid(gid)
                        if download_id:
                            # 预估远程路径
                            from configer import RCLONE_REMOTE, RCLONE_PATH
                            file_name_display = os.path.basename(actual_path)
                            remote_path = f"{RCLONE_REMOTE}:{RCLONE_PATH}/{file_name_display}"
                            upload_id = create_upload(download_id, 'onedrive', remote_path=remote_path)
                            print(f"创建上传记录成功，ID: {upload_id}")
                    except Exception as e:
                        print(f"创建上传记录失败: {e}")

                    # 使用rclone上传到OneDrive，异步非阻塞执行
                    asyncio.create_task(
                        self.upload_handler.upload_to_onedrive(actual_path, msg, gid, upload_id=upload_id)
                    )
                    print(f"[上传] 已启动OneDrive上传任务(异步): {os.path.basename(actual_path)}")
                elif UP_TELEGRAM:
                    # 创建上传记录
                    upload_id = None
                    try:
                        download_id = get_download_id_by_gid(gid)
                        if download_id:
                            upload_id = create_upload(download_id, 'telegram')
                            print(f"创建上传记录成功，ID: {upload_id}")
                    except Exception as e:
                        print(f"创建上传记录失败: {e}")
                        
                    # 上传到Telegram，异步非阻塞执行
                    asyncio.create_task(
                        self.upload_handler.upload_to_telegram_with_load_balance(actual_path, gid, upload_id=upload_id)
                    )
                    print(f"[上传] 已启动Telegram上传任务(异步): {os.path.basename(actual_path)}")
    
    async def on_download_pause(self, result, tell_status_func):
        """
        处理下载暂停事件
        
        Args:
            result: Aria2事件结果
            tell_status_func: 获取任务状态的函数
        """
        gid = result['params'][0]['gid']
        print(f"===========下载 暂停 任务id:{gid}")
        tellStatus = await tell_status_func(gid)
        filename = get_file_name(tellStatus)
        if self.bot:
            pause_msg = (
                f'⏸️ <b>下载已暂停</b>\n\n'
                f'📁 <b>文件:</b> <code>{filename}</code>\n'
                f'🆔 <b>任务ID:</b> <code>{gid}</code>'
            )
            await self.bot.send_message(ADMIN_ID, pause_msg, parse_mode='html')
    
    async def on_download_error(self, result, tell_status_func):
        """
        处理下载错误事件
        
        Args:
            result: Aria2事件结果
            tell_status_func: 获取任务状态的函数
        """
        gid = result['params'][0]['gid']
        tellStatus = await tell_status_func(gid)
        errorCode = tellStatus['errorCode']
        errorMessage = tellStatus['errorMessage']
        print(f'===========下载 错误 任务id:{gid} 错误码: {errorCode} 错误信息{errorMessage}')
        if self.bot:
            if errorCode == '12':
                await self.bot.send_message(ADMIN_ID, '任务已经在下载,可以删除任务后重新添加')
            else:
                await self.bot.send_message(ADMIN_ID, errorMessage)
