/**
 * WebSocket 工具类
 * 用于连接服务器并接收实时状态更新
 */

export type WSMessageType = 
  | 'initial' 
  | 'download_update' 
  | 'upload_update' 
  | 'cleanup_update' 
  | 'statistics_update'
  | 'pong'
  | 'error'

export interface WSMessage {
  type: WSMessageType
  seq?: number  // 序列号，用于消息重排
  data?: any
  message?: string
}

export type WSMessageHandler = (message: WSMessage) => void

// 消息缓冲区，用于重排序
interface BufferedMessage {
  message: WSMessage
  receivedAt: number
}

class WebSocketClient {
  private ws: WebSocket | null = null
  private url: string
  private handlers: Map<WSMessageType, Set<WSMessageHandler>> = new Map()
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  private shouldReconnect = true
  private pingInterval: number | null = null
  
  // 消息缓冲和重排
  private messageBuffer: Map<WSMessageType, BufferedMessage[]> = new Map()
  private expectedSeq: Map<WSMessageType, number> = new Map()
  private bufferTimeout: number = 50  // 缓冲超时时间（毫秒），用于处理乱序消息（降低延迟）
  private bufferCheckInterval: number | null = null

  constructor(url: string = '') {
    // 自动检测 WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    this.url = url || `${protocol}//${host}/api/ws/status`
  }

  connect(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return
    }

    try {
      this.ws = new WebSocket(this.url)
      
      this.ws.onopen = () => {
        console.log('WebSocket 连接已建立')
        this.reconnectAttempts = 0
        
        // 清空缓冲区和序列号
        this.messageBuffer.clear()
        this.expectedSeq.clear()
        
        // 启动心跳
        this.startPing()
        
        // 启动缓冲区检查
        this.startBufferCheck()
      }

      this.ws.onmessage = (event) => {
        try {
          const message: WSMessage = JSON.parse(event.data)
          this.handleMessage(message)
        } catch (e) {
          console.error('解析 WebSocket 消息失败:', e)
        }
      }

      this.ws.onerror = (error) => {
        console.error('WebSocket 错误:', error)
      }

      this.ws.onclose = () => {
        console.log('WebSocket 连接已关闭')
        this.stopPing()
        this.stopBufferCheck()
        
        // 清空缓冲区
        this.messageBuffer.clear()
        this.expectedSeq.clear()
        
        // 自动重连
        if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
          this.reconnectAttempts++
          const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1)
          console.log(`将在 ${delay}ms 后重连 (尝试 ${this.reconnectAttempts}/${this.maxReconnectAttempts})`)
          setTimeout(() => this.connect(), delay)
        }
      }
    } catch (error) {
      console.error('WebSocket 连接失败:', error)
    }
  }

  disconnect(): void {
    this.shouldReconnect = false
    this.stopPing()
    this.stopBufferCheck()
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    // 清空缓冲区
    this.messageBuffer.clear()
    this.expectedSeq.clear()
  }

  on(type: WSMessageType, handler: WSMessageHandler): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set())
    }
    this.handlers.get(type)!.add(handler)

    // 返回取消订阅函数
    return () => {
      this.handlers.get(type)?.delete(handler)
    }
  }

  private handleMessage(message: WSMessage): void {
    // 如果消息没有序列号，直接处理（向后兼容）
    if (message.seq === undefined) {
      this.dispatchMessage(message)
      return
    }
    
    // 有序列号的消息，需要缓冲和重排
    const messageType = message.type
    
    // 初始化期望序列号（第一条消息，期望收到当前消息的序列号）
    if (!this.expectedSeq.has(messageType)) {
      // 第一条消息，直接处理并设置期望序列号为下一条
      this.dispatchMessage(message)
      this.expectedSeq.set(messageType, message.seq + 1)
      // 检查缓冲区是否有后续消息可以处理
      this.processBufferedMessages(messageType)
      return
    }
    
    const expectedSeq = this.expectedSeq.get(messageType)!
    
    // 如果消息序列号正好是期望的，直接处理
    if (message.seq === expectedSeq) {
      this.dispatchMessage(message)
      // 期望下一条消息的序列号
      this.expectedSeq.set(messageType, expectedSeq + 1)
      
      // 检查缓冲区是否有后续消息可以处理
      this.processBufferedMessages(messageType)
    } else if (message.seq > expectedSeq) {
      // 消息乱序到达，放入缓冲区
      if (!this.messageBuffer.has(messageType)) {
        this.messageBuffer.set(messageType, [])
      }
      const buffer = this.messageBuffer.get(messageType)!
      buffer.push({
        message,
        receivedAt: Date.now()
      })
      // 按序列号排序
      buffer.sort((a, b) => a.message.seq! - b.message.seq!)
      
      // 如果缓冲区中有期望的消息，尝试处理
      this.processBufferedMessages(messageType)
    } else {
      // 序列号小于期望值，可能是重复消息，忽略
      console.warn(`收到过期的消息: type=${messageType}, seq=${message.seq}, expected=${expectedSeq}`)
    }
  }
  
  private processBufferedMessages(messageType: WSMessageType): void {
    const buffer = this.messageBuffer.get(messageType)
    if (!buffer || buffer.length === 0) {
      return
    }
    
    const expectedSeq = this.expectedSeq.get(messageType)!
    
    // 处理缓冲区中连续的消息
    while (buffer.length > 0) {
      const buffered = buffer[0]
      if (buffered.message.seq === expectedSeq) {
        // 处理消息
        this.dispatchMessage(buffered.message)
        buffer.shift()
        this.expectedSeq.set(messageType, expectedSeq + 1)
      } else {
        // 还有缺失的消息，等待
        break
      }
    }
  }
  
  private dispatchMessage(message: WSMessage): void {
    const handlers = this.handlers.get(message.type)
    if (handlers) {
      handlers.forEach(handler => {
        try {
          handler(message)
        } catch (e) {
          console.error('处理 WebSocket 消息失败:', e)
        }
      })
    }
  }
  
  private startBufferCheck(): void {
    // 定期检查缓冲区，处理超时的消息（防止因消息丢失导致永久等待）
    this.bufferCheckInterval = window.setInterval(() => {
      const now = Date.now()
      for (const [messageType, buffer] of this.messageBuffer.entries()) {
        if (buffer.length === 0) continue
        
        const expectedSeq = this.expectedSeq.get(messageType)!
        const oldest = buffer[0]
        
        // 如果最老的消息已经超时，允许跳过缺失的序列号
        if (now - oldest.receivedAt > this.bufferTimeout) {
          // 允许跳过缺失的序列号，直接处理缓冲区中最老的消息
          // 只在跳过多个序列号时才警告（避免频繁警告）
          if (oldest.message.seq! - expectedSeq > 1) {
            console.warn(`缓冲区超时，跳过序列号 ${expectedSeq} 到 ${oldest.message.seq! - 1}，处理消息 type=${messageType}, seq=${oldest.message.seq}`)
          }
          this.expectedSeq.set(messageType, oldest.message.seq!)
          this.processBufferedMessages(messageType)
        } else if (buffer.length > 10) {
          // 如果缓冲区积压超过10条消息，也尝试处理（防止缓冲区过大）
          console.warn(`缓冲区积压过多（${buffer.length}条），跳过序列号 ${expectedSeq} 到 ${oldest.message.seq! - 1}`)
          this.expectedSeq.set(messageType, oldest.message.seq!)
          this.processBufferedMessages(messageType)
        }
      }
    }, this.bufferTimeout)
  }
  
  private stopBufferCheck(): void {
    if (this.bufferCheckInterval !== null) {
      clearInterval(this.bufferCheckInterval)
      this.bufferCheckInterval = null
    }
  }

  private startPing(): void {
    this.pingInterval = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000) // 每30秒发送一次心跳
  }

  private stopPing(): void {
    if (this.pingInterval !== null) {
      clearInterval(this.pingInterval)
      this.pingInterval = null
    }
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }
}

// 导出单例实例
export const wsClient = new WebSocketClient()
