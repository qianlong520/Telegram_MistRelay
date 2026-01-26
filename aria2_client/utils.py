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
