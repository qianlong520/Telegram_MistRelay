"""
Aria2上传处理模块 - 处理OneDrive和Telegram上传
"""
import asyncio
import functools
import os
import subprocess
from typing import Optional

from configer import (
    ADMIN_ID, RCLONE_REMOTE, RCLONE_PATH, AUTO_DELETE_AFTER_UPLOAD, FORWARD_ID
)
from util import byte2_readable, progress as util_progress
from db import (
    mark_upload_started, mark_upload_completed, mark_upload_failed,
    increment_upload_retry, update_upload_status
)
from util import imgCoverFromFile

from .constants import (
    RCLONE_MAX_RETRIES,
    RCLONE_RETRY_BASE_DELAY,
    RCLONE_RETRY_EXTRA_DELAY,
    PROCESS_TERMINATE_TIMEOUT,
    pyrogram_clients,
    channel_accessible_clients,
    upload_work_loads
)
from .utils import parse_rclone_progress, format_upload_message


class UploadHandler:
    """处理文件上传到OneDrive和Telegram"""
    
    def __init__(self, bot, progress_cache):
        """
        初始化上传处理器
        
        Args:
            bot: Telegram bot实例
            progress_cache: 进度缓存字典
        """
        self.bot = bot
        self.progress_cache = progress_cache
    
    async def upload_to_onedrive(self, file_path, msg=None, gid=None, upload_id=None):
        """
        使用rclone将文件上传到OneDrive
        
        Args:
            file_path: 文件路径
            msg: 可选的消息对象，如果提供则编辑该消息而不是发送新消息
            gid: 下载任务GID，用于跟踪任务完成状态
            upload_id: 上传记录ID，用于追踪状态
        
        Returns:
            bool: 上传是否成功
        """
        file_name = os.path.basename(file_path)  # 在函数开始处定义，确保异常处理中可用
        
        # 标记上传开始
        if upload_id:
            try:
                mark_upload_started(upload_id)
            except Exception as e:
                print(f"标记上传开始失败: {e}")
        
        try:
            if not os.path.exists(file_path):
                print(f"文件不存在: {file_path}")
                
                # 记录失败
                if upload_id:
                    try:
                        mark_upload_failed(upload_id, 'file_not_found', f"文件不存在: {file_path}")
                    except Exception as e:
                        print(f"记录上传失败出错: {e}")
                
                if self.bot:
                    error_message = (
                        f'❌ <b>文件不存在</b>\n\n'
                        f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                        f'📂 <b>路径:</b> <code>{file_path}</code>\n\n'
                        f'⚠️ 无法上传到 OneDrive'
                    )
                    if msg:
                        try:
                            await self.bot.edit_message(msg, error_message, parse_mode='html')
                        except:
                            await self.bot.send_message(ADMIN_ID, error_message, parse_mode='html')
                    else:
                        await self.bot.send_message(ADMIN_ID, error_message, parse_mode='html')
                return False
                
            # 构建rclone命令
            remote_path = f"{RCLONE_REMOTE}:{RCLONE_PATH}"
            command = [
                "rclone", 
                "copy", 
                file_path, 
                remote_path, 
                "-P",
                "--transfers", "4",          # 并行传输数量（从16降到4，减少IO竞争）
                "--checkers", "8",           # 并行检查数量（从16降到8）
                "--buffer-size", "64M",      # 缓冲区大小（从250M降到64M，防止内存耗尽导致Swap）
                "--log-level", "INFO",      # 日志级别
                "--log-file", "/app/rclone.log"  # 日志文件
            ]
            
            # 通知开始上传
            if self.bot:
                # 获取文件大小
                file_size = ""
                try:
                    if os.path.exists(file_path):
                        file_size_bytes = os.path.getsize(file_path)
                        file_size = byte2_readable(file_size_bytes)
                except:
                    pass
                
                if msg:
                    try:
                        upload_start_text = (
                            f'📤 <b>上传到 OneDrive</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                            f'📂 <b>路径:</b> <code>{file_path}</code>'
                        )
                        if file_size:
                            upload_start_text += f'\n💾 <b>大小:</b> {file_size}'
                        upload_start_text += f'\n\n⏳ <b>准备上传中...</b>'
                        msg = await self.bot.edit_message(msg, upload_start_text, parse_mode='html')
                    except Exception as e:
                        print(f"更新上传开始消息失败: {e}")
                else:
                    upload_start_text = (
                        f'📤 <b>上传到 OneDrive</b>\n\n'
                        f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                        f'📂 <b>路径:</b> <code>{file_path}</code>'
                    )
                    if file_size:
                        upload_start_text += f'\n💾 <b>大小:</b> {file_size}'
                    upload_start_text += f'\n\n⏳ <b>准备上传中...</b>'
                    msg = await self.bot.send_message(ADMIN_ID, upload_start_text, parse_mode='html')
            
            # 重试循环
            max_retries = RCLONE_MAX_RETRIES
            current_retry = 0
            upload_success = False
            last_return_code = 0
            last_error_details = ""
            
            while current_retry < max_retries:
                if current_retry > 0:
                    wait_seconds = current_retry * RCLONE_RETRY_BASE_DELAY + RCLONE_RETRY_EXTRA_DELAY  # 15s, 25s, ...
                    print(f"[重试] 第 {current_retry} 次重试，等待 {wait_seconds} 秒...")
                    
                    # 更新状态为重试中
                    if upload_id:
                        try:
                            increment_upload_retry(upload_id)
                            print(f"[重试] 已更新数据库重试计数: {current_retry}")
                        except Exception as retry_err:
                            print(f"[重试] 警告: 更新数据库重试计数失败: {retry_err}")
                    
                    if self.bot and msg:
                         try:
                             retry_msg = f"{upload_start_text}\n\n⚠️ <b>上传失败，等待 {wait_seconds} 秒后重试 ({current_retry}/{max_retries-1})...</b>"
                             await self.bot.edit_message(msg, retry_msg, parse_mode='html')
                         except Exception as msg_err:
                             print(f"[重试] 更新重试消息失败: {msg_err}")
                    
                    await asyncio.sleep(wait_seconds)
                    
                
                # 执行rclone命令
                process = None
                try:
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        universal_newlines=True
                    )
                    
                    # 读取输出并更新进度
                    last_progress = ""
                    last_message_text = ""
                    progress_counter = 0
                    error_lines = []
                    
                    for line in process.stdout:
                        # 收集错误日志
                        if "ERROR" in line:
                            error_lines.append(line.strip())
                        
                        # 集成进度更新
                        progress_counter += 1
                        if upload_id and progress_counter % 10 == 0:
                            try:
                                update_upload_status(upload_id, 'uploading')
                            except Exception as db_err:
                                print(f"[上传] 更新数据库状态失败: {db_err}")
        
                        if "Transferred:" in line and self.bot and msg:
                            # 提取进度信息
                            progress_info = line.strip()
                            if progress_info != last_progress:
                                last_progress = progress_info
                                # 解析进度信息
                                parsed = parse_rclone_progress(progress_info)
                                # 格式化美化消息
                                formatted_message = format_upload_message(file_path, parsed)
                                
                                # 每5行更新一次消息，避免频繁更新
                                if hash(progress_info) % 5 == 0:
                                    if formatted_message != last_message_text:
                                        try:
                                            await self.bot.edit_message(msg, formatted_message, parse_mode='html')
                                            last_message_text = formatted_message
                                        except Exception as e:
                                            if "not modified" not in str(e).lower():
                                                print(f"更新上传进度消息失败: {e}")
                    
                    # 等待进程完成
                    process.wait()
                    last_return_code = process.returncode
                    if error_lines:
                        last_error_details = "\n".join(error_lines[-10:])
                    
                    # 检查上传是否成功
                    if last_return_code == 0:
                        upload_success = True
                        break
                    else:
                        result_msg = f"Rclone 退出码: {last_return_code}"
                        if error_lines:
                            result_msg += f", 错误: {error_lines[-1]}"
                        print(f"上传尝试 {current_retry + 1} 失败: {result_msg}")
                        current_retry += 1
                finally:
                    # 确保进程被正确清理,防止僵尸进程
                    if process and process.poll() is None:
                        try:
                            process.terminate()
                            process.wait(timeout=PROCESS_TERMINATE_TIMEOUT)
                        except:
                            try:
                                process.kill()
                            except:
                                pass
            
            # 循环结束，检查最终结果
            if upload_success:
                if upload_id:
                    try:
                        mark_upload_completed(upload_id)
                    except Exception as e:
                        print(f"标记上传完成出错: {e}")
                        
                if self.bot and msg:
                    try:
                        # 获取文件大小
                        file_size = ""
                        try:
                            if os.path.exists(file_path):
                                file_size_bytes = os.path.getsize(file_path)
                                file_size = byte2_readable(file_size_bytes)
                        except:
                            pass
                        
                        success_message = (
                            f'✅ <b>上传完成</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                            f'📂 <b>路径:</b> <code>{file_path}</code>'
                        )
                        if file_size:
                            success_message += f'\n💾 <b>大小:</b> {file_size}'
                        success_message += f'\n\n☁️ <b>已成功上传到 OneDrive</b>'
                        await self.bot.edit_message(msg, success_message, parse_mode='html')
                    except Exception as e:
                        if "not modified" not in str(e).lower():
                            print(f"更新上传成功消息失败: {e}")
                
                # 更新任务完成跟踪状态为 'uploaded'
                if gid:
                    try:
                        from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                        import asyncio as asyncio_module
                        
                        if task_completion_lock:
                            async with task_completion_lock:
                                task_completion_tracker[gid] = {
                                    'status': 'uploaded',
                                    'completed_at': asyncio_module.get_event_loop().time()
                                }
                                print(f"任务 {gid} 已标记为已上传")
                    except Exception as e:
                        print(f"更新任务上传状态失败: {e}")
                
                # 上传成功后删除本地文件
                if AUTO_DELETE_AFTER_UPLOAD:
                    try:
                        os.unlink(file_path)
                        print(f"已删除本地文件: {file_path}")
                        
                        # 更新任务完成跟踪状态为 'cleaned'
                        if gid:
                            try:
                                from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                                import asyncio as asyncio_module
                                
                                if task_completion_lock:
                                    async with task_completion_lock:
                                        task_completion_tracker[gid] = {
                                            'status': 'cleaned',
                                            'completed_at': asyncio_module.get_event_loop().time()
                                        }
                                        print(f"任务 {gid} 已标记为已清理")
                            except Exception as e:
                                print(f"更新任务清理状态失败: {e}")
                        
                        # 删除本地文件成功后，删除消息
                        if self.bot and msg:
                            try:
                                await msg.delete()
                                print(f"已删除消息（文件已上传并清理）: {file_name}")
                            except Exception as e:
                                print(f"删除消息失败: {e}")
                    except Exception as e:
                        print(f"删除本地文件失败: {e}")
                        if self.bot and msg:
                            try:
                                # 获取文件大小
                                file_size = ""
                                try:
                                    if os.path.exists(file_path):
                                        file_size_bytes = os.path.getsize(file_path)
                                        file_size = byte2_readable(file_size_bytes)
                                except:
                                    pass
                                
                                error_message = (
                                    f'✅ <b>上传完成</b>\n\n'
                                    f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                                    f'📂 <b>路径:</b> <code>{file_path}</code>'
                                )
                                if file_size:
                                    error_message += f'\n💾 <b>大小:</b> {file_size}'
                                error_message += (
                                    f'\n\n☁️ <b>已成功上传到 OneDrive</b>\n\n'
                                    f'⚠️ <b>删除本地文件失败:</b>\n<code>{str(e)}</code>'
                                )
                                await self.bot.edit_message(msg, error_message, parse_mode='html')
                            except Exception as edit_err:
                                if "not modified" not in str(edit_err).lower():
                                    print(f"更新删除文件错误消息失败: {edit_err}")
                
                return True
            else:
                # 最终失败
                error_message = f"上传失败，返回码: {last_return_code}"
                print(error_message)
                
                # 使用收集到的错误日志
                error_details = last_error_details
                if not error_details:
                    # 尝试读取日志文件中的最后几行错误
                    try:
                        if os.path.exists("/app/rclone.log"):
                            with open("/app/rclone.log", "r") as log_file:
                                log_lines = log_file.readlines()
                                last_errors = [line for line in log_lines[-20:] if "ERROR" in line]
                                if last_errors:
                                    error_details = "\n".join(last_errors)
                                    print(f"rclone错误详情:\n{error_details}")
                    except Exception as e:
                        print(f"读取日志文件失败: {e}")
                
                if upload_id:
                    try:
                        mark_upload_failed(upload_id, 'upload_failed', f"rclone返回码: {last_return_code}\n{error_details[:200]}")
                    except Exception as e:
                        print(f"标记上传失败出错: {e}")
                
                if self.bot and msg:
                    try:
                        # 获取文件大小
                        file_size = ""
                        try:
                            if os.path.exists(file_path):
                                file_size_bytes = os.path.getsize(file_path)
                                file_size = byte2_readable(file_size_bytes)
                        except:
                            pass
                        
                        fail_message = (
                            f'❌ <b>上传失败</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                            f'📂 <b>路径:</b> <code>{file_path}</code>'
                        )
                        if file_size:
                            fail_message += f'\n💾 <b>大小:</b> {file_size}'
                        fail_message += f'\n\n⚠️ <b>返回码:</b> <code>{last_return_code}</code>'
                        if error_details:
                            fail_message += f'\n\n📋 <b>错误详情:</b>\n<code>{error_details[:500]}</code>'
                        await self.bot.edit_message(msg, fail_message, parse_mode='html')
                    except Exception as e:
                        if "not modified" not in str(e).lower():
                            print(f"更新上传失败消息失败: {e}")
                
                # 发送详细错误信息到管理员
                if error_details and self.bot:
                    try:
                        error_detail_msg = (
                            f'📤 <b>上传错误详情</b>\n\n'
                            f'📁 <b>文件:</b> <code>{file_name}</code>\n\n'
                            f'📋 <b>错误日志:</b>\n<code>{error_details[:3000]}</code>'
                        )
                        await self.bot.send_message(ADMIN_ID, error_detail_msg, parse_mode='html')
                    except:
                        pass
                
                return False
                
        except Exception as e:
            print(f"上传到OneDrive时出错: {e}")
            if upload_id:
                try:
                    mark_upload_failed(upload_id, 'code_error', str(e), 'EXCEPTION')
                except:
                    pass

            if self.bot:
                # 获取文件大小
                file_size = ""
                try:
                    if os.path.exists(file_path):
                        file_size_bytes = os.path.getsize(file_path)
                        file_size = byte2_readable(file_size_bytes)
                except:
                    pass
                
                error_message = (
                    f'❌ <b>上传异常</b>\n\n'
                    f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                    f'📂 <b>路径:</b> <code>{file_path}</code>'
                )
                if file_size:
                    error_message += f'\n💾 <b>大小:</b> {file_size}'
                error_message += f'\n\n⚠️ <b>错误信息:</b>\n<code>{str(e)}</code>'
                if msg:
                    try:
                        await self.bot.edit_message(msg, error_message, parse_mode='html')
                    except:
                        await self.bot.send_message(ADMIN_ID, error_message, parse_mode='html')
                else:
                    await self.bot.send_message(ADMIN_ID, error_message, parse_mode='html')
            return False

    async def upload_to_telegram_with_load_balance(self, file_path, gid, upload_id=None):
        """
        使用多客户端负载均衡上传文件到Telegram
        
        Args:
            file_path: 文件路径
            gid: 下载任务GID
            upload_id: 上传记录ID
        """
        # 标记上传开始
        if upload_id:
            try:
                mark_upload_started(upload_id)
            except:
                pass

        client_index = None
        try:
            file_name_display = os.path.basename(file_path)
            upload_start_msg = (
                f'📤 <b>上传到 Telegram</b>\n\n'
                f'📁 <b>文件:</b> <code>{file_name_display}</code>\n'
                f'📂 <b>路径:</b> <code>{file_path}</code>\n\n'
                f'⏳ <b>准备上传中...</b>'
            )
            
            # 选择上传客户端（使用负载均衡）
            upload_client = None
            
            if pyrogram_clients and len(pyrogram_clients) > 0:
                # 使用Pyrogram多客户端负载均衡
                # 优先选择能访问频道的客户端
                if channel_accessible_clients:
                    available_loads = {
                        k: v for k, v in upload_work_loads.items() 
                        if k in channel_accessible_clients and k in pyrogram_clients
                    }
                    if available_loads:
                        client_index = min(available_loads, key=available_loads.get)
                    else:
                        # 回退到所有客户端
                        valid_loads = {k: v for k, v in upload_work_loads.items() if k in pyrogram_clients}
                        if valid_loads:
                            client_index = min(valid_loads, key=valid_loads.get)
                else:
                    # 使用所有客户端
                    valid_loads = {k: v for k, v in upload_work_loads.items() if k in pyrogram_clients}
                    if valid_loads:
                        client_index = min(valid_loads, key=valid_loads.get)
                
                if client_index is not None and client_index in pyrogram_clients:
                    upload_client = pyrogram_clients[client_index]
                    upload_work_loads[client_index] = upload_work_loads.get(client_index, 0) + 1
                    print(f"使用Pyrogram客户端 {client_index} 上传文件（上传负载: {upload_work_loads[client_index]}）")
            
            # 如果没有Pyrogram客户端，使用Telethon bot
            if upload_client is None:
                upload_client = self.bot
                print("使用Telethon bot上传文件（未启用多客户端）")
            
            # 发送开始消息
            if hasattr(upload_client, 'send_message') and not hasattr(upload_client, 'get_me'):  # Telethon
                msg = await upload_client.send_message(ADMIN_ID, upload_start_msg, parse_mode='html')
            else:  # Pyrogram
                msg = await upload_client.send_message(ADMIN_ID, upload_start_msg)
            
            # 根据文件类型上传
            try:
                if file_path.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    # 图片文件
                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path, upload_id=upload_id)
                        temp_msg = await upload_client.send_file(ADMIN_ID, file_path, progress_callback=partial_callback)
                    else:  # Pyrogram
                        temp_msg = await upload_client.send_photo(ADMIN_ID, file_path)
                    
                    if FORWARD_ID:
                        if hasattr(temp_msg, 'forward_to'):  # Telethon
                            await temp_msg.forward_to(int(FORWARD_ID))
                        else:  # Pyrogram
                            await upload_client.forward_messages(int(FORWARD_ID), ADMIN_ID, temp_msg.id)
                    
                    if hasattr(msg, 'delete'):
                        await msg.delete()
                    
                    # 更新任务完成跟踪状态为 'uploaded'（Telegram上传）
                    if gid:
                        try:
                            from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                            import asyncio as asyncio_module
                            
                            if task_completion_lock:
                                async with task_completion_lock:
                                    task_completion_tracker[gid] = {
                                        'status': 'uploaded',
                                        'completed_at': asyncio_module.get_event_loop().time()
                                    }
                                    print(f"任务 {gid} 已标记为已上传（Telegram）")
                        except Exception as e:
                            print(f"更新任务上传状态失败: {e}")
                    
                    # 图片上传后不需要清理（图片通常不删除），但如果启用了AUTO_DELETE_AFTER_UPLOAD，也需要清理
                    if AUTO_DELETE_AFTER_UPLOAD and os.path.exists(file_path):
                        try:
                            os.unlink(file_path)
                            # 更新任务完成跟踪状态为 'cleaned'（Telegram上传）
                            if gid:
                                try:
                                    from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                                    import asyncio as asyncio_module
                                    
                                    if task_completion_lock:
                                        async with task_completion_lock:
                                            task_completion_tracker[gid] = {
                                                'status': 'cleaned',
                                                'completed_at': asyncio_module.get_event_loop().time()
                                            }
                                            print(f"任务 {gid} 已标记为已清理（Telegram上传）")
                                except Exception as e:
                                    print(f"更新任务清理状态失败: {e}")
                        except Exception as e:
                            print(f"删除图片文件失败: {e}")
                        
                elif file_path.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                    # 视频文件
                    pat = os.path.dirname(file_path)
                    filename = os.path.basename(file_path).split('.')[0]
                    thumb_path = pat + '/' + filename + '.jpg'
                    
                    # 生成视频封面
                    await imgCoverFromFile(file_path, thumb_path)
                    
                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path, upload_id=upload_id)
                        temp_msg = await upload_client.send_file(
                            ADMIN_ID, 
                            file_path, 
                            thumb=thumb_path,
                            progress_callback=partial_callback
                        )
                    else:  # Pyrogram
                        temp_msg = await upload_client.send_video(ADMIN_ID, file_path, thumb=thumb_path)
                    
                    if FORWARD_ID:
                        if hasattr(temp_msg, 'forward_to'):  # Telethon
                            await temp_msg.forward_to(int(FORWARD_ID))
                        else:  # Pyrogram
                            await upload_client.forward_messages(int(FORWARD_ID), ADMIN_ID, temp_msg.id)
                    
                    if hasattr(msg, 'delete'):
                        await msg.delete()
                    
                    # 更新任务完成跟踪状态为 'uploaded'（Telegram上传）
                    if gid:
                        try:
                            from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                            import asyncio as asyncio_module
                            
                            if task_completion_lock:
                                async with task_completion_lock:
                                    task_completion_tracker[gid] = {
                                        'status': 'uploaded',
                                        'completed_at': asyncio_module.get_event_loop().time()
                                    }
                                    print(f"任务 {gid} 已标记为已上传（Telegram）")
                        except Exception as e:
                            print(f"更新任务上传状态失败: {e}")
                    
                    # 删除封面
                    if os.path.exists(thumb_path):
                        os.unlink(thumb_path)
                    
                    if AUTO_DELETE_AFTER_UPLOAD:
                        os.unlink(file_path)
                        # 更新任务完成跟踪状态为 'cleaned'（Telegram上传）
                        if gid:
                            try:
                                from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                                import asyncio as asyncio_module
                                
                                if task_completion_lock:
                                    async with task_completion_lock:
                                        task_completion_tracker[gid] = {
                                            'status': 'cleaned',
                                            'completed_at': asyncio_module.get_event_loop().time()
                                        }
                                        print(f"任务 {gid} 已标记为已清理（Telegram上传）")
                            except Exception as e:
                                print(f"更新任务清理状态失败: {e}")
                else:
                    # 其他文件类型
                    if hasattr(upload_client, 'send_file'):  # Telethon
                        partial_callback = functools.partial(self.callback, gid=gid, msg=msg, path=file_path, upload_id=upload_id)
                        temp_msg = await upload_client.send_file(ADMIN_ID, file_path, progress_callback=partial_callback)
                    else:  # Pyrogram
                        temp_msg = await upload_client.send_document(ADMIN_ID, file_path)
                    
                    if FORWARD_ID:
                        if hasattr(temp_msg, 'forward_to'):  # Telethon
                            await temp_msg.forward_to(int(FORWARD_ID))
                        else:  # Pyrogram
                            await upload_client.forward_messages(int(FORWARD_ID), ADMIN_ID, temp_msg.id)
                    
                    if hasattr(msg, 'delete'):
                        await msg.delete()
                    
                    if AUTO_DELETE_AFTER_UPLOAD:
                        os.unlink(file_path)
                        # 更新任务完成跟踪状态为 'cleaned'（Telegram上传）
                        if gid:
                            try:
                                from WebStreamer.bot.plugins.stream import task_completion_tracker, task_completion_lock
                                import asyncio as asyncio_module
                                
                                if task_completion_lock:
                                    async with task_completion_lock:
                                        task_completion_tracker[gid] = {
                                            'status': 'cleaned',
                                            'completed_at': asyncio_module.get_event_loop().time()
                                        }
                                        print(f"任务 {gid} 已标记为已清理（Telegram上传）")
                            except Exception as e:
                                print(f"更新任务清理状态失败: {e}")
                        
                    # 标记上传完成（如果上面的逻辑没有抛出异常）
                    if upload_id:
                        try:
                            mark_upload_completed(upload_id)
                        except:
                            pass
                            
            finally:
                # 减少上传负载
                if client_index is not None and client_index in upload_work_loads:
                    upload_work_loads[client_index] = max(0, upload_work_loads[client_index] - 1)
                    
        except Exception as e:
            print(f"上传到Telegram失败: {e}")
            import traceback
            traceback.print_exc()
            error_msg = (
                f'❌ <b>上传失败</b>\n\n'
                f'📂 <b>路径:</b> <code>{file_path}</code>\n\n'
                f'⚠️ <b>错误:</b> {str(e)}'
            )
            
            if upload_id:
                try:
                    mark_upload_failed(upload_id, 'code_error', str(e), 'EXCEPTION')
                except:
                    pass

            if self.bot:
                await self.bot.send_message(ADMIN_ID, error_msg, parse_mode='html')
            # 确保减少负载
            if client_index is not None and client_index in upload_work_loads:
                upload_work_loads[client_index] = max(0, upload_work_loads[client_index] - 1)

    async def callback(self, current, total, gid, msg=None, path=None, upload_id=None):
        """
        上传进度回调函数
        
        Args:
            current: 当前上传字节数
            total: 总字节数
            gid: 下载任务GID
            msg: 消息对象
            path: 文件路径
            upload_id: 上传记录ID
        """
        if upload_id:
            try:
                update_upload_status(upload_id, 'uploading', uploaded_size=current, total_size=total)
            except:
                pass

        if not msg or not path:
            return
            
        gid_progress = self.progress_cache.get(gid, 0)
        new_progress = current / total
        formatted_progress = "{:.2%}".format(new_progress)
        if abs(new_progress - gid_progress) >= 0.05:
            self.progress_cache[gid] = new_progress
            file_name = os.path.basename(path)
            file_size = byte2_readable(total)
            current_size = byte2_readable(current)
            progress_bar = util_progress(int(total), int(current))
            
            new_message_text = (
                f'📤 <b>上传到 Telegram</b>\n\n'
                f'📁 <b>文件:</b> <code>{file_name}</code>\n'
                f'📂 <b>路径:</b> <code>{path}</code>\n\n'
                f'📊 <b>进度:</b> {progress_bar}\n'
                f'💾 <b>已上传:</b> {current_size} / {file_size}\n'
                f'📈 <b>完成度:</b> {formatted_progress}'
            )
            try:
                await self.bot.edit_message(msg, new_message_text, parse_mode='html')
            except Exception as e:
                # 忽略"消息内容未修改"的错误
                if "not modified" not in str(e).lower():
                    print(f"更新进度消息失败: {e}")
