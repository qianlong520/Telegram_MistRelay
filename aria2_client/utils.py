"""
Aria2客户端工具函数
"""
import os
import re


def format_progress_bar(percentage_str):
    """
    根据百分比生成进度条
    返回: 进度条字符串（使用 Unicode 字符）
    """
    try:
        # 提取百分比数字
        percentage = float(percentage_str.replace('%', ''))
        # 限制在 0-100 之间
        percentage = max(0, min(100, percentage))
        
        # 进度条长度（20个字符）
        bar_length = 20
        filled_length = int(bar_length * percentage / 100)
        
        # 使用不同的字符表示进度
        filled_char = '█'
        empty_char = '░'
        
        bar = filled_char * filled_length + empty_char * (bar_length - filled_length)
        return bar
    except:
        return '░' * 20


def format_upload_message(file_path, parsed_progress):
    """
    格式化上传进度消息（美化版）
    """
    file_name = os.path.basename(file_path)
    
    # 构建消息
    message_parts = []
    message_parts.append(f'📤 <b>上传到 OneDrive</b>\n')
    message_parts.append(f'📁 <b>文件:</b> <code>{file_name}</code>\n')
    
    # 进度条和百分比
    if parsed_progress.get('percentage'):
        percentage = parsed_progress['percentage']
        progress_bar = format_progress_bar(percentage)
        message_parts.append(f'\n{progress_bar} <b>{percentage}</b>\n')
    
    # 传输进度
    if parsed_progress.get('transferred') and parsed_progress.get('total'):
        message_parts.append(f'📊 <b>进度:</b> {parsed_progress["transferred"]} / {parsed_progress["total"]}\n')
    elif parsed_progress.get('transferred'):
        message_parts.append(f'📊 <b>已传输:</b> {parsed_progress["transferred"]}\n')
    
    # 速度
    if parsed_progress.get('speed'):
        message_parts.append(f'⚡ <b>速度:</b> {parsed_progress["speed"]}\n')
    
    # ETA
    if parsed_progress.get('eta'):
        eta = parsed_progress['eta']
        message_parts.append(f'⏱️ <b>剩余时间:</b> {eta}\n')
    
    return ''.join(message_parts)


def parse_rclone_progress(line):
    """
    解析 rclone 进度输出行
    格式示例: "Transferred:   1.234 GiB / 2.345 GiB, 53%, 12.34 MiB/s, ETA 0s"
    或者: "Transferred:   1.234 GiB / 2.345 GiB, 53%, 12.34 MiB/s, ETA -"
    或者: "Transferred:   1.234 GiB / 2.345 GiB, 53%, 12.34 MiB/s, ETA 1h11m47s"
    或者: "Speed: 12.34 MiB/s" (单独一行)
    返回: dict 包含 transferred, total, percentage, speed, eta
    """
    result = {
        'transferred': '',
        'total': '',
        'percentage': '',
        'speed': '',
        'eta': ''
    }
    
    try:
        # 首先尝试提取速率信息（可能在单独的行中）
        speed_patterns = [
            r'Speed:\s*([\d.]+)\s+([KMGT]?i?B/s)',  # "Speed: 12.34 MiB/s"
            r'([\d.]+)\s+([KMGT]?i?B/s)',  # "12.34 MiB/s" (通用格式)
        ]
        for pattern in speed_patterns:
            speed_match = re.search(pattern, line, re.IGNORECASE)
            if speed_match:
                result['speed'] = f"{speed_match.group(1)} {speed_match.group(2)}"
                break
        
        # 提取 "Transferred:" 后面的内容
        if "Transferred:" not in line:
            return result
        
        # 匹配格式: Transferred:   X.XXX Unit / Y.YYY Unit, Z%, S.SSS Unit/s, ETA ...
        # 支持 GiB, MiB, KiB, GB, MB, KB 等单位
        # 支持 ETA 格式: 数字s, 数字h数字m数字s, 或 -
        # 先尝试匹配完整格式（包含速率和 ETA）
        full_pattern = r'Transferred:\s+([\d.]+)\s+([KMGT]?i?B)\s+/\s+([\d.]+)\s+([KMGT]?i?B),\s+([\d.]+)%(?:\s*,\s*([\d.]+)\s+([KMGT]?i?B/s))?(?:\s*,\s*ETA\s+([\d]+[hms]+|\d+h\d+m\d+s|\d+m\d+s|\d+s|-))?'
        match = re.search(full_pattern, line, re.IGNORECASE)
        
        if match:
            transferred_size = match.group(1)
            transferred_unit = match.group(2)
            total_size = match.group(3)
            total_unit = match.group(4)
            percentage = match.group(5)
            
            result['transferred'] = f"{transferred_size} {transferred_unit}"
            result['total'] = f"{total_size} {total_unit}"
            result['percentage'] = f"{percentage}%"
            
            # 提取速率信息（group 6 和 7）
            if match.group(6) and match.group(7):
                speed_value = match.group(6)
                speed_unit = match.group(7)
                result['speed'] = f"{speed_value} {speed_unit}"
            
            # 提取 ETA 信息（group 8）
            if match.group(8):
                eta = match.group(8)
                if eta != '-':
                    result['eta'] = eta
                # 如果 ETA 是 '-'，不设置 eta 字段（保持为空）
        else:
            # 如果完整格式匹配失败，尝试简化格式
            simple_pattern = r'Transferred:\s+([\d.]+)\s+([KMGT]?i?B)\s+/\s+([\d.]+)\s+([KMGT]?i?B),\s+([\d.]+)%'
            match = re.search(simple_pattern, line, re.IGNORECASE)
            if match:
                transferred_size = match.group(1)
                transferred_unit = match.group(2)
                total_size = match.group(3)
                total_unit = match.group(4)
                percentage = match.group(5)
                
                result['transferred'] = f"{transferred_size} {transferred_unit}"
                result['total'] = f"{total_size} {total_unit}"
                result['percentage'] = f"{percentage}%"
        
        # 如果还没有提取到速率，尝试从整行中提取（作为后备方案）
        if not result['speed']:
            # 查找 "数字 单位/s" 格式的速率
            # 优先匹配在逗号后面的速率（Transferred 行中的速率格式）
            # 格式: ", 数字 单位/s" 或 ", 数字 单位/s,"
            speed_patterns = [
                r',\s*([\d.]+)\s+([KMGT]?i?B/s)',  # ", 0 B/s" 或 ", 12.34 MiB/s"
                r'([\d.]+)\s+([KMGT]?i?B/s)',  # 通用格式 "0 B/s"
            ]
            for pattern in speed_patterns:
                speed_match = re.search(pattern, line, re.IGNORECASE)
                if speed_match:
                    # 确保不是 ETA 后面的时间（检查是否在 ETA 之前）
                    match_pos = speed_match.start()
                    eta_pos = line.find('ETA', match_pos)
                    if eta_pos == -1 or match_pos < eta_pos:
                        result['speed'] = f"{speed_match.group(1)} {speed_match.group(2)}"
                        break
        
        # 如果还没有提取到 ETA，尝试从整行中提取（作为后备方案）
        if not result['eta']:
            # 匹配 ETA 格式: ETA 数字s, ETA 数字h数字m数字s, 或 ETA -
            eta_patterns = [
                r'ETA\s+(\d+[hms]+|\d+h\d+m\d+s|\d+m\d+s|\d+s)',  # ETA 1h11m47s 或 ETA 32s
                r'ETA\s+(\d+)s',  # ETA 32s
            ]
            for pattern in eta_patterns:
                eta_match = re.search(pattern, line, re.IGNORECASE)
                if eta_match:
                    result['eta'] = eta_match.group(1)
                    break
                
    except Exception as e:
        print(f"解析 rclone 进度失败: {e}, 行内容: {line[:100]}")
    
    return result


def verify_file_size(file_path, expected_size, tolerance=1024):
    """
    校验文件大小是否与期望值匹配
    
    Args:
        file_path: 文件路径
        expected_size: 期望的文件大小(字节)
        tolerance: 允许的误差范围(字节),默认1KB
    
    Returns:
        bool: 大小是否匹配
    """
    try:
        if not os.path.exists(file_path):
            print(f"[校验] 文件不存在: {file_path}")
            return False
        
        actual_size = os.path.getsize(file_path)
        size_diff = abs(actual_size - expected_size)
        
        if size_diff <= tolerance:
            return True
        else:
            from util import byte2_readable
            print(f"[校验] 文件大小不匹配:")
            print(f"  文件: {os.path.basename(file_path)}")
            print(f"  期望: {byte2_readable(expected_size)}")
            print(f"  实际: {byte2_readable(actual_size)}")
            print(f"  差异: {byte2_readable(size_diff)}")
            return False
    except Exception as e:
        print(f"[校验] 校验文件大小时出错: {e}")
        return False


async def run_rclone_command_async(args, timeout=30):
    """
    异步执行rclone命令的统一接口（不阻塞事件循环）
    
    Args:
        args: rclone命令参数列表,例如 ['lsf', 'remote:path']
        timeout: 超时时间(秒)
    
    Returns:
        tuple: (returncode, stdout, stderr)
    """
    import asyncio
    
    try:
        cmd = ['rclone'] + args
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            returncode = process.returncode
            stdout_str = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_str = stderr.decode('utf-8', errors='replace') if stderr else ""
            return returncode, stdout_str, stderr_str
        except asyncio.TimeoutError:
            print(f"[rclone] 命令超时: {' '.join(args)}")
            try:
                process.kill()
                await process.wait()
            except:
                pass
            return -1, "", "命令执行超时"
    except Exception as e:
        print(f"[rclone] 命令执行出错: {e}")
        return -1, "", str(e)


def run_rclone_command(args, timeout=30):
    """
    执行rclone命令的统一接口（同步版本，用于向后兼容）
    
    Args:
        args: rclone命令参数列表,例如 ['lsf', 'remote:path']
        timeout: 超时时间(秒)
    
    Returns:
        tuple: (returncode, stdout, stderr)
    """
    import subprocess
    
    try:
        cmd = ['rclone'] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        print(f"[rclone] 命令超时: {' '.join(args)}")
        return -1, "", "命令执行超时"
    except Exception as e:
        print(f"[rclone] 执行命令失败: {e}")
        return -1, "", str(e)


def calculate_file_md5(file_path, chunk_size=8192):
    """
    计算文件的MD5哈希值
    
    Args:
        file_path: 文件路径
        chunk_size: 读取块大小(字节),默认8KB
    
    Returns:
        str: MD5哈希值(小写十六进制),失败返回None
    """
    import hashlib
    
    try:
        if not os.path.exists(file_path):
            print(f"[MD5] 文件不存在: {file_path}")
            return None
        
        md5_hash = hashlib.md5()
        
        with open(file_path, 'rb') as f:
            # 分块读取文件,避免大文件占用过多内存
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                md5_hash.update(chunk)
        
        result = md5_hash.hexdigest()
        print(f"[MD5] 计算完成: {os.path.basename(file_path)} = {result}")
        return result
        
    except Exception as e:
        print(f"[MD5] 计算MD5失败: {e}")
        import traceback
        traceback.print_exc()
        return None
