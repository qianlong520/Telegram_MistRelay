"""
Aria2客户端包

提供异步Aria2 WebSocket客户端功能,支持下载管理和文件上传
"""
from .client import AsyncAria2Client
from .constants import *

__all__ = ['AsyncAria2Client']
__version__ = '1.0.0'
