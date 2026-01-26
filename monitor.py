
import psutil
import time
import threading
import logging
from collections import deque
from typing import Dict, List, Any

log = logging.getLogger('monitor')

class SystemMonitor:
    def __init__(self, history_size: int = 60, interval: int = 2):
        """
        初始化系统监控器
        :param history_size: 保留的历史数据点数量
        :param interval: 采样间隔(秒)
        """
        self.history_size = history_size
        self.interval = interval
        self.running = False
        self._thread = None
        
        # 存储历史数据
        self.history: deque = deque(maxlen=history_size)
        
        # 上一次的计数器值
        self._last_net_io = None
        self._last_disk_io = None
        self._last_time = None

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        log.info("System Monitor started")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            log.info("System Monitor stopped")

    def _monitor_loop(self):
        # 初始化基准值
        self._last_net_io = psutil.net_io_counters()
        self._last_disk_io = psutil.disk_io_counters()
        self._last_time = time.time()
        
        while self.running:
            try:
                time.sleep(self.interval)
                self._collect_metrics()
            except Exception as e:
                log.error(f"Error collecting metrics: {e}")

    def _collect_metrics(self):
        current_time = time.time()
        current_net_io = psutil.net_io_counters()
        current_disk_io = psutil.disk_io_counters()
        
        # 计算时间差
        dt = current_time - self._last_time
        if dt <= 0:
            return

        # 计算网络速率 (bytes/s)
        # bytes_sent: 上传
        # bytes_recv: 下载
        up_speed = (current_net_io.bytes_sent - self._last_net_io.bytes_sent) / dt
        down_speed = (current_net_io.bytes_recv - self._last_net_io.bytes_recv) / dt
        
        # 计算磁盘IO速率 (bytes/s)
        # read_bytes: 读取
        # write_bytes: 写入
        # 合并为 IO Usage
        disk_read_speed = (current_disk_io.read_bytes - self._last_disk_io.read_bytes) / dt
        disk_write_speed = (current_disk_io.write_bytes - self._last_disk_io.write_bytes) / dt
        io_usage = disk_read_speed + disk_write_speed

        # 更新基准值
        self._last_net_io = current_net_io
        self._last_disk_io = current_disk_io
        self._last_time = current_time

        # 记录数据点
        point = {
            'timestamp': int(current_time * 1000),
            'upload': int(up_speed),
            'download': int(down_speed),
            'io': int(io_usage)
        }
        self.history.append(point)

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self.history)

# 全局单例
monitor = SystemMonitor()
