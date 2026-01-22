# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import asyncio
import logging
from ..vars import Var
from pyrogram import Client
from . import multi_clients, work_loads, sessions_dir, StreamBot

logger = logging.getLogger("multi_client")

async def initialize_clients():
    multi_clients[0] = StreamBot
    work_loads[0] = 0
    # 目前只支持单客户端，如需多客户端可以后续扩展
    logger.info("Using default client")

