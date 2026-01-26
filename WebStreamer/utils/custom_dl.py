import math
import asyncio
import logging
from WebStreamer import Var
from typing import Dict, Union, Optional
from WebStreamer.bot import work_loads, multi_clients, channel_accessible_clients
from pyrogram import Client, utils, raw
from .file_properties import get_file_ids
from pyrogram.session import Session, Auth
from pyrogram.errors import AuthBytesInvalid
from WebStreamer.server.exceptions import FIleNotFound
from pyrogram.file_id import FileId, FileType, ThumbnailSource

logger = logging.getLogger("streamer")

# 用于同步授权导出的锁字典（按DC ID）
export_auth_locks: Dict[int, asyncio.Lock] = {}

def get_next_available_client(current_index: int, exclude_indices: Optional[set] = None) -> Optional[int]:
    """
    获取下一个可用的客户端索引
    优先选择能访问频道的客户端，排除当前客户端和已失败的客户端
    """
    if exclude_indices is None:
        exclude_indices = set()
    exclude_indices.add(current_index)
    
    # 优先选择能访问频道的客户端
    if channel_accessible_clients:
        available_loads = {
            k: v for k, v in work_loads.items()
            if k in channel_accessible_clients 
            and k in multi_clients
            and k not in exclude_indices
        }
        if available_loads:
            return min(available_loads, key=available_loads.get)
    
    # 回退到所有可用客户端
    valid_loads = {
        k: v for k, v in work_loads.items()
        if k in multi_clients
        and k not in exclude_indices
    }
    if valid_loads:
        return min(valid_loads, key=valid_loads.get)
    
    return None

class ByteStreamer:
    def __init__(self, client: Client):
        """A custom class that holds the cache of a specific client and class functions.
        attributes:
            client: the client that the cache is for.
            cached_file_ids: a dict of cached file IDs.
            cached_file_properties: a dict of cached file properties.
        
        functions:
            generate_file_properties: returns the properties for a media of a specific message contained in Tuple.
            generate_media_session: returns the media session for the DC that contains the media file.
            yield_file: yield a file from telegram servers for streaming.
            
        This is a modified version of the <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/telegram/utils/custom_download.py>
        Thanks to Eyaadh <https://github.com/eyaadh>
        """
        self.clean_timer = 30 * 60
        self.client: Client = client
        self.cached_file_ids: Dict[int, FileId] = {}
        asyncio.create_task(self.clean_cache())

    async def get_file_properties(self, message_id: int) -> FileId:
        """
        Returns the properties of a media of a specific message in a FIleId class.
        if the properties are cached, then it'll return the cached results.
        or it'll generate the properties from the Message ID and cache them.
        """
        if message_id not in self.cached_file_ids:
            await self.generate_file_properties(message_id)
            logger.debug(f"Cached file properties for message with ID {message_id}")
        return self.cached_file_ids[message_id]
    
    async def generate_file_properties(self, message_id: int) -> FileId:
        """
        Generates the properties of a media file on a specific message.
        returns ths properties in a FIleId class.
        """
        file_id = await get_file_ids(self.client, Var.BIN_CHANNEL, message_id)
        logger.debug(f"Generated file ID and Unique ID for message with ID {message_id}")
        if not file_id:
            logger.debug(f"Message with ID {message_id} not found")
            raise FIleNotFound
        self.cached_file_ids[message_id] = file_id
        logger.debug(f"Cached media message with ID {message_id}")
        return self.cached_file_ids[message_id]

    async def generate_media_session(self, client: Client, file_id: FileId) -> Session:
        """
        Generates the media session for the DC that contains the media file.
        This is required for getting the bytes from Telegram servers.
        """

        media_session = client.media_sessions.get(file_id.dc_id, None)

        # 检查缓存的会话是否仍然有效
        if media_session is not None:
            try:
                # 检查会话的连接状态和加密参数
                if (hasattr(media_session, 'connection') and media_session.connection and
                    hasattr(media_session.connection, 'protocol') and media_session.connection.protocol and
                    hasattr(media_session.connection.protocol, 'encrypt') and 
                    media_session.connection.protocol.encrypt is not None):
                    logger.debug(f"Using cached media session for DC {file_id.dc_id}")
                    return media_session
                # 如果会话无效，清除它
                logger.debug(f"Cached media session for DC {file_id.dc_id} is invalid, recreating...")
                try:
                    await media_session.stop()
                except:
                    pass
                if file_id.dc_id in client.media_sessions:
                    del client.media_sessions[file_id.dc_id]
                media_session = None
            except Exception as e:
                logger.warning(f"Error checking cached media session: {e}")
                try:
                    await media_session.stop()
                except:
                    pass
                if file_id.dc_id in client.media_sessions:
                    del client.media_sessions[file_id.dc_id]
                media_session = None

        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                # 获取或创建该DC的锁，防止并发导出授权
                if file_id.dc_id not in export_auth_locks:
                    export_auth_locks[file_id.dc_id] = asyncio.Lock()
                
                lock = export_auth_locks[file_id.dc_id]
                
                # 使用锁来防止并发导出授权
                async with lock:
                    # 再次检查是否在等待期间已经创建了会话
                    if file_id.dc_id in client.media_sessions:
                        cached_session = client.media_sessions[file_id.dc_id]
                        try:
                            if (hasattr(cached_session, 'connection') and cached_session.connection and
                                hasattr(cached_session.connection, 'protocol') and cached_session.connection.protocol and
                                hasattr(cached_session.connection.protocol, 'encrypt') and 
                                cached_session.connection.protocol.encrypt is not None):
                                logger.debug(f"Using newly created media session for DC {file_id.dc_id}")
                                return cached_session
                        except:
                            pass
                    
                    media_session = Session(
                        client,
                        file_id.dc_id,
                        await Auth(
                            client, file_id.dc_id, await client.storage.test_mode()
                        ).create(),
                        await client.storage.test_mode(),
                        is_media=True,
                    )
                    await media_session.start()

                    # 尝试导入授权，最多重试6次
                    auth_imported = False
                    for attempt in range(6):
                        try:
                            # 导出授权
                            exported_auth = await client.invoke(
                                raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id)
                            )
                            
                            # 导入授权
                            await media_session.invoke(
                                raw.functions.auth.ImportAuthorization(
                                    id=exported_auth.id, bytes=exported_auth.bytes
                                )
                            )
                            auth_imported = True
                            logger.debug(f"Successfully imported authorization for DC {file_id.dc_id} (attempt {attempt + 1})")
                            break
                        except AuthBytesInvalid as e:
                            logger.warning(
                                f"Invalid authorization bytes for DC {file_id.dc_id} (attempt {attempt + 1}/6): {e}"
                            )
                            if attempt < 5:
                                # 等待一小段时间后重试，避免立即重试
                                await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        except Exception as e:
                            logger.error(f"Unexpected error during auth import for DC {file_id.dc_id}: {e}", exc_info=True)
                            if attempt < 5:
                                await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                    
                    if not auth_imported:
                        await media_session.stop()
                        raise AuthBytesInvalid(f"Failed to import authorization for DC {file_id.dc_id} after 6 attempts")
                    
                    logger.debug(f"Created media session for DC {file_id.dc_id}")
                    client.media_sessions[file_id.dc_id] = media_session
            else:
                media_session = Session(
                    client,
                    file_id.dc_id,
                    await client.storage.auth_key(),
                    await client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()
            logger.debug(f"Created media session for DC {file_id.dc_id}")
            client.media_sessions[file_id.dc_id] = media_session
        
        return media_session


    @staticmethod
    async def get_location(file_id: FileId) -> Union[raw.types.InputPhotoFileLocation,
                                                     raw.types.InputDocumentFileLocation,
                                                     raw.types.InputPeerPhotoFileLocation,]:
        """
        Returns the file location for the media file.
        """
        file_type = file_id.file_type

        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id, access_hash=file_id.chat_access_hash
                )
            else:
                if file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
                else:
                    peer = raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(file_id.chat_id),
                        access_hash=file_id.chat_access_hash,
                    )

            location = raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                volume_id=file_id.volume_id,
                local_id=file_id.local_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
            )
        elif file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size,
            )
        else:
            location = raw.types.InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size,
            )
        return location

    async def _try_get_file_chunk(
        self,
        client: Client,
        file_id: FileId,
        location,
        offset: int,
        chunk_size: int,
        max_retries: int = 3
    ):
        """
        尝试获取文件块，支持重试和客户端切换
        返回: (success: bool, result, new_client, new_index)
        """
        for retry_attempt in range(max_retries):
            try:
                # 生成或获取媒体会话
                media_session = await self.generate_media_session(client, file_id)
                
                # 尝试获取文件块
                r = await media_session.invoke(
                    raw.functions.upload.GetFile(
                        location=location, offset=offset, limit=chunk_size
                    ),
                )
                return True, r, client, None
                
            except (OSError, ConnectionError, TimeoutError, AuthBytesInvalid, TypeError, AttributeError) as e:
                error_msg = str(e)
                error_type = type(e).__name__
                
                # 检查是否是加密相关的错误
                is_encryption_error = (
                    isinstance(e, TypeError) and
                    ('Value after * must be an iterable' in error_msg or
                     'NoneType' in error_msg or
                     'encrypt' in error_msg.lower())
                )
                
                # 检查是否是连接错误
                is_connection_error = (
                    isinstance(e, (OSError, ConnectionError)) or
                    'Connection lost' in error_msg or
                    'Connection closed' in error_msg or
                    'Broken pipe' in error_msg
                )
                
                if retry_attempt < max_retries - 1:
                    if is_encryption_error:
                        logger.debug(f"加密状态异常，清除会话并重试 (offset: {offset}, 尝试 {retry_attempt + 1}/{max_retries})")
                    elif is_connection_error:
                        logger.debug(f"连接错误，尝试重新建立媒体会话 (offset: {offset}, 尝试 {retry_attempt + 1}/{max_retries})")
                    else:
                        logger.debug(f"获取文件块失败，重试 (offset: {offset}, 尝试 {retry_attempt + 1}/{max_retries}): {error_type}")
                    
                    # 清除无效的会话缓存（加密错误和连接错误都需要清除）
                    if file_id.dc_id in client.media_sessions:
                        try:
                            await client.media_sessions[file_id.dc_id].stop()
                        except Exception as stop_error:
                            logger.debug(f"停止媒体会话时出错（可能已断开）: {stop_error}")
                        del client.media_sessions[file_id.dc_id]
                    
                    # 等待后重试（加密错误需要稍长的等待时间）
                    wait_time = 1.5 + retry_attempt * 0.5 if is_encryption_error else 1 + retry_attempt * 0.5
                    await asyncio.sleep(wait_time)
                else:
                    # 最后一次重试失败，返回失败
                    if is_encryption_error:
                        logger.warning(f"加密状态异常，重试失败 (offset: {offset}): {error_type}")
                    elif is_connection_error:
                        logger.warning(f"连接错误，重试失败 (offset: {offset}): {error_type}")
                    else:
                        logger.warning(f"获取文件块失败，已达到最大重试次数 (offset: {offset}): {error_type}")
                    return False, None, client, None
        
        return False, None, client, None

    async def yield_file(
        self,
        file_id: FileId,
        index: int,
        offset: int,
        first_part_cut: int,
        last_part_cut: int,
        part_count: int,
        chunk_size: int,
    ) -> Union[str, None]:
        """
        Custom generator that yields the bytes of the media file.
        支持客户端切换：当连接失败时，自动切换到其他可用客户端继续传输
        Modded from <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/telegram/utils/custom_download.py#L20>
        Thanks to Eyaadh <https://github.com/eyaadh>
        """
        client = self.client
        current_index = index
        failed_indices = set()  # 记录失败的客户端索引
        
        # 确保索引存在于 work_loads 中
        if current_index not in work_loads:
            logger.error(f"客户端索引 {current_index} 不存在于 work_loads 中")
            return
        
        work_loads[current_index] += 1
        logger.debug(f"Starting to yielding file with client {current_index} (当前负载: {work_loads[current_index]}).")
        
        current_part = 1
        location = await self.get_location(file_id)

        # 获取初始文件块，支持客户端切换
        success, r, client, _ = await self._try_get_file_chunk(
            client, file_id, location, offset, chunk_size, max_retries=3
        )
        
        # 如果失败，尝试切换到其他客户端
        if not success:
            logger.warning(f"客户端 {current_index} 获取初始文件块失败，尝试切换到其他客户端")
            failed_indices.add(current_index)
            
            # 减少当前客户端负载
            if current_index in work_loads:
                work_loads[current_index] -= 1
            
            # 尝试切换到其他客户端
            max_client_switches = 3  # 最多尝试切换3个客户端
            switch_success = False
            
            for switch_attempt in range(max_client_switches):
                next_index = get_next_available_client(current_index, failed_indices)
                if next_index is None:
                    logger.error("没有其他可用的客户端")
                    return
                
                logger.info(f"切换到客户端 {next_index} (尝试 {switch_attempt + 1}/{max_client_switches})")
                current_index = next_index
                client = multi_clients[current_index]
                work_loads[current_index] += 1
                
                # 更新 ByteStreamer 的客户端引用
                self.client = client
                
                # 尝试获取文件块
                success, r, client, _ = await self._try_get_file_chunk(
                    client, file_id, location, offset, chunk_size, max_retries=2
                )
                
                if success:
                    switch_success = True
                    logger.info(f"成功切换到客户端 {current_index} 并获取文件块")
                    break
                else:
                    failed_indices.add(current_index)
                    if current_index in work_loads:
                        work_loads[current_index] -= 1
            
            if not switch_success:
                logger.error("所有客户端都无法获取初始文件块，停止文件流传输")
                return
        
        try:
            if isinstance(r, raw.types.upload.File):
                while True:
                    chunk = r.bytes
                    if not chunk:
                        break
                    elif part_count == 1:
                        yield chunk[first_part_cut:last_part_cut]
                    elif current_part == 1:
                        yield chunk[first_part_cut:]
                    elif current_part == part_count:
                        yield chunk[:last_part_cut]
                    else:
                        yield chunk

                    current_part += 1
                    offset += chunk_size

                    if current_part > part_count:
                        break

                    # 尝试获取下一个文件块
                    success, r, new_client, _ = await self._try_get_file_chunk(
                        client, file_id, location, offset, chunk_size, max_retries=2
                    )
                    
                    if not success:
                        # 当前客户端失败，尝试切换到其他客户端
                        logger.warning(f"客户端 {current_index} 获取文件块失败 (offset: {offset})，尝试切换到其他客户端")
                        failed_indices.add(current_index)
                        
                        # 减少当前客户端负载
                        if current_index in work_loads:
                            work_loads[current_index] -= 1
                        
                        # 尝试切换到其他客户端
                        max_client_switches = 3
                        switch_success = False
                        
                        for switch_attempt in range(max_client_switches):
                            next_index = get_next_available_client(current_index, failed_indices)
                            if next_index is None:
                                logger.error(f"没有其他可用的客户端 (offset: {offset})")
                                break
                            
                            logger.info(f"切换到客户端 {next_index} 继续传输 (offset: {offset}, 尝试 {switch_attempt + 1}/{max_client_switches})")
                            current_index = next_index
                            client = multi_clients[current_index]
                            work_loads[current_index] += 1
                            
                            # 更新 ByteStreamer 的客户端引用
                            self.client = client
                            
                            # 尝试获取文件块
                            success, r, client, _ = await self._try_get_file_chunk(
                                client, file_id, location, offset, chunk_size, max_retries=2
                            )
                            
                            if success:
                                switch_success = True
                                logger.info(f"成功切换到客户端 {current_index} 并继续传输 (offset: {offset})")
                                break
                            else:
                                failed_indices.add(current_index)
                                if current_index in work_loads:
                                    work_loads[current_index] -= 1
                        
                        if not switch_success:
                            logger.error(f"所有客户端都无法获取文件块，停止文件流传输 (offset: {offset})")
                            break
        except (TimeoutError, AttributeError, TypeError, OSError, ConnectionError) as e:
            error_msg = str(e)
            if 'Connection lost' in error_msg or 'Connection closed' in error_msg:
                logger.error(f"连接丢失错误 in yield_file: {e}")
            else:
                logger.error(f"Error in yield_file: {e}", exc_info=True)
        except Exception as e:
            error_msg = str(e)
            if 'Connection lost' in error_msg or 'Connection closed' in error_msg:
                logger.error(f"连接丢失错误 in yield_file: {e}")
            else:
                logger.error(f"Unexpected error in yield_file: {e}", exc_info=True)
        finally:
            logger.debug(f"Finished yielding file with {current_part} parts.")
            # 确保索引存在后再减少负载（使用当前使用的客户端索引）
            if current_index in work_loads:
                work_loads[current_index] -= 1
                logger.debug(f"客户端 {current_index} 负载已减少 (当前负载: {work_loads[current_index]})")
            else:
                logger.warning(f"尝试减少客户端 {current_index} 的负载，但索引不存在于 work_loads 中")

    
    async def clean_cache(self) -> None:
        """
        function to clean the cache to reduce memory usage
        """
        while True:
            await asyncio.sleep(self.clean_timer)
            self.cached_file_ids.clear()
            logger.debug("Cleaned the cache")

