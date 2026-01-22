import math
import asyncio
import logging
from WebStreamer import Var
from typing import Dict, Union
from WebStreamer.bot import work_loads
from pyrogram import Client, utils, raw
from .file_properties import get_file_ids
from pyrogram.session import Session, Auth
from pyrogram.errors import AuthBytesInvalid
from WebStreamer.server.exceptions import FIleNotFound
from pyrogram.file_id import FileId, FileType, ThumbnailSource

logger = logging.getLogger("streamer")

# 用于同步授权导出的锁字典（按DC ID）
export_auth_locks: Dict[int, asyncio.Lock] = {}

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
        Modded from <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/telegram/utils/custom_download.py#L20>
        Thanks to Eyaadh <https://github.com/eyaadh>
        """
        client = self.client
        work_loads[index] += 1
        logger.debug(f"Starting to yielding file with client {index}.")
        
        try:
            media_session = await self.generate_media_session(client, file_id)
        except Exception as e:
            logger.error(f"Failed to generate media session: {e}", exc_info=True)
            work_loads[index] -= 1
            return

        current_part = 1
        location = await self.get_location(file_id)

        try:
            r = await media_session.invoke(
                raw.functions.upload.GetFile(
                    location=location, offset=offset, limit=chunk_size
                ),
            )
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

                    try:
                        r = await media_session.invoke(
                            raw.functions.upload.GetFile(
                                location=location, offset=offset, limit=chunk_size
                            ),
                        )
                    except (TimeoutError, AttributeError, TypeError, AuthBytesInvalid) as e:
                        logger.warning(f"Error getting file chunk at offset {offset}: {e}")
                        # 如果媒体会话出现问题，清除缓存并重新生成
                        try:
                            # 清除无效的会话缓存
                            if file_id.dc_id in client.media_sessions:
                                try:
                                    await client.media_sessions[file_id.dc_id].stop()
                                except:
                                    pass
                                del client.media_sessions[file_id.dc_id]
                            # 等待一小段时间，避免立即重试
                            await asyncio.sleep(1)
                            # 重新生成会话
                            media_session = await self.generate_media_session(client, file_id)
                            r = await media_session.invoke(
                                raw.functions.upload.GetFile(
                                    location=location, offset=offset, limit=chunk_size
                                ),
                            )
                        except Exception as retry_e:
                            logger.error(f"Failed to retry getting file chunk: {retry_e}", exc_info=True)
                            break
        except (TimeoutError, AttributeError, TypeError) as e:
            logger.error(f"Error in yield_file: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error in yield_file: {e}", exc_info=True)
        finally:
            logger.debug(f"Finished yielding file with {current_part} parts.")
            work_loads[index] -= 1

    
    async def clean_cache(self) -> None:
        """
        function to clean the cache to reduce memory usage
        """
        while True:
            await asyncio.sleep(self.clean_timer)
            self.cached_file_ids.clear()
            logger.debug("Cleaned the cache")

