<template>
  <div class="settings-page">
    <div class="page-header">
      <el-button type="info" @click="handleReloadConfig" :loading="reloading" :disabled="reloading">
        从config.yml重新导入配置
      </el-button>
      <div style="margin-left: 10px; color: #909399; font-size: 12px;">
        提示：配置保存后会自动从数据库读取，无需手动重载
      </div>
    </div>

    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane label="客户端连接" name="client">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>客户端连接配置</span>
              <div class="card-actions">
                <el-button @click="testConnection" :loading="testingConnection">
                  测试连接
                </el-button>
                <el-button type="primary" @click="saveClientConnection" :loading="savingClientConnection">
                  保存并应用
                </el-button>
              </div>
            </div>
          </template>

          <el-alert
            title="浏览器端可选择同源访问，也可以指定远程服务器。"
            type="info"
            :closable="false"
            style="margin-bottom: 20px"
          />

          <el-form label-width="180px">
            <el-form-item label="客户端类型">
              <el-tag type="info">浏览器客户端</el-tag>
            </el-form-item>
            <el-form-item label="服务器地址">
              <el-input
                v-model="clientServerUrl"
                placeholder="https://mistrelay.example.com"
                clearable
              />
              <div class="el-form-item__help">
                留空时继续使用当前同源服务。
              </div>
            </el-form-item>
            <el-form-item label="当前生效地址">
              <el-input :model-value="effectiveServerUrlLabel" readonly />
            </el-form-item>
            <el-form-item label="连接状态">
              <div class="connection-status">
                <el-tag :type="connectionStatusTagType">
                  {{ connectionStatusLabel }}
                </el-tag>
                <span v-if="connectionStatusText" class="connection-status-text">
                  {{ connectionStatusText }}
                </span>
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- Telegram配置 -->
      <el-tab-pane label="Telegram配置" name="telegram">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>Telegram Bot配置</span>
              <el-button type="primary" @click="saveConfig('telegram')" :loading="saving" :disabled="reloading">
                保存配置
              </el-button>
            </div>
          </template>
          <el-alert
            type="warning"
            :closable="false"
            style="margin-bottom: 20px"
          >
            <template #title>
              <div style="font-size: 13px">
                <strong>注意：</strong>修改 API ID、API Hash、Bot Token 或管理员ID 后需要重启服务才能生效。
                <br />其他配置（如上传到Telegram）保存后会在下次使用时自动从数据库读取最新配置。
              </div>
            </template>
          </el-alert>
          <el-form :model="configs.telegram" label-width="180px" :rules="rules" :disabled="reloading">
            <el-form-item label="API ID" prop="API_ID">
              <el-input-number v-model="configs.telegram.API_ID" :min="0" style="width: 100%" />
            </el-form-item>
            <el-form-item label="API Hash" prop="API_HASH">
              <el-input v-model="configs.telegram.API_HASH" type="password" show-password />
            </el-form-item>
            <el-form-item label="Bot Token" prop="BOT_TOKEN">
              <el-input v-model="configs.telegram.BOT_TOKEN" type="password" show-password />
            </el-form-item>
            <el-form-item label="管理员ID" prop="ADMIN_ID">
              <el-input-number v-model="configs.telegram.ADMIN_ID" :min="0" style="width: 100%" />
            </el-form-item>
            <el-form-item label="转发ID" prop="FORWARD_ID">
              <el-input v-model="configs.telegram.FORWARD_ID" />
            </el-form-item>
            <el-form-item label="上传到Telegram">
              <el-switch v-model="configs.telegram.UP_TELEGRAM" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- Rclone配置 -->
      <el-tab-pane label="Rclone配置" name="rclone">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>Rclone上传配置</span>
              <el-button type="primary" @click="saveConfig('rclone')" :loading="saving">
                保存配置
              </el-button>
            </div>
          </template>
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 20px"
          >
            <template #title>
              <div style="font-size: 13px">
                <strong>提示：</strong>Rclone配置保存后会立即生效，下次上传时会自动从数据库读取最新配置，无需重启服务。
              </div>
            </template>
          </el-alert>
          <el-form :model="configs.rclone" label-width="180px">
            <el-divider content-position="left">OneDrive配置</el-divider>
            <el-form-item label="启用OneDrive上传">
              <el-switch v-model="configs.rclone.UP_ONEDRIVE" />
            </el-form-item>
            <el-form-item label="Rclone远程名称" v-if="configs.rclone.UP_ONEDRIVE">
              <el-select 
                v-model="configs.rclone.RCLONE_REMOTE" 
                placeholder="选择 OneDrive Remote"
                filterable
                allow-create
                default-first-option
              >
                <el-option
                  v-for="remote in availableRemotes.filter(r => r.type === 'onedrive')"
                  :key="remote.name"
                  :label="`${remote.name} (${remote.type})`"
                  :value="remote.name"
                >
                  <span style="float: left">{{ remote.name }}</span>
                  <span style="float: right; color: #8492a6; font-size: 12px">{{ remote.type }}</span>
                </el-option>
              </el-select>
              <div class="el-form-item__help">OneDrive的rclone远程名称(自动过滤 type=onedrive 的 remote)</div>
            </el-form-item>
            <el-form-item label="OneDrive路径" v-if="configs.rclone.UP_ONEDRIVE">
              <el-input v-model="configs.rclone.RCLONE_PATH" />
              <div class="el-form-item__help">OneDrive上的目标路径（默认：/Downloads）</div>
            </el-form-item>
            
            <el-divider content-position="left">Google Drive配置</el-divider>
            <el-form-item label="启用Google Drive上传">
              <el-switch v-model="configs.rclone.UP_GOOGLE_DRIVE" />
            </el-form-item>
            <el-alert
              v-if="configs.rclone.UP_GOOGLE_DRIVE"
              type="info"
              :closable="false"
              style="margin-bottom: 20px"
            >
              <template #title>
                <div style="font-size: 13px">
                  <strong>提示：</strong>Google Drive 上传使用 rclone，需要在 rclone 配置文件中配置 OAuth2 token。
                  <br />请确保已在 <code>rclone.conf</code> 中配置了名为 <code>{{ configs.rclone.GOOGLE_DRIVE_REMOTE || 'gdrive' }}</code> 的远程配置。
                </div>
              </template>
            </el-alert>
            <el-form-item label="Google Drive远程名称" v-if="configs.rclone.UP_GOOGLE_DRIVE">
              <el-select 
                v-model="configs.rclone.GOOGLE_DRIVE_REMOTE" 
                placeholder="选择 Google Drive Remote"
                filterable
                allow-create
                default-first-option
              >
                <el-option
                  v-for="remote in availableRemotes.filter(r => r.type === 'drive')"
                  :key="remote.name"
                  :label="`${remote.name} (${remote.type})`"
                  :value="remote.name"
                >
                  <span style="float: left">{{ remote.name }}</span>
                  <span style="float: right; color: #8492a6; font-size: 12px">{{ remote.type }}</span>
                </el-option>
              </el-select>
              <div class="el-form-item__help">Google Drive的rclone远程名称(自动过滤 type=drive 的 remote)</div>
            </el-form-item>
            <el-form-item label="Google Drive路径" v-if="configs.rclone.UP_GOOGLE_DRIVE">
              <el-input v-model="configs.rclone.GOOGLE_DRIVE_PATH" />
              <div class="el-form-item__help">Google Drive上的目标路径（默认：/Downloads）</div>
            </el-form-item>
            
            <el-divider content-position="left">通用设置</el-divider>
            <el-form-item label="上传后删除本地文件">
              <el-switch v-model="configs.rclone.AUTO_DELETE_AFTER_UPLOAD" />
              <div class="el-form-item__help">上传成功后自动删除本地文件以节省磁盘空间</div>
            </el-form-item>
            
            <el-divider content-position="left">Rclone 配置文件管理</el-divider>
            <el-alert
              type="info"
              :closable="false"
              style="margin-bottom: 20px"
            >
              <template #title>
                <div style="font-size: 13px">
                  <strong>提示:</strong>直接编辑 rclone.conf 文件内容,保存时会自动备份原文件。配置采用 INI 格式,每个远程存储以 <code>[remote_name]</code> 开始。
                </div>
              </template>
            </el-alert>
            <el-form-item label="配置文件路径">
              <el-input v-model="rcloneConfigPath" readonly />
            </el-form-item>
            <el-form-item label="配置文件内容">
              <el-input
                v-model="rcloneConfigContent"
                type="textarea"
                :rows="15"
                placeholder="rclone.conf 配置文件内容将在此显示..."
                style="font-family: 'Courier New', monospace; font-size: 12px;"
              />
              <div class="el-form-item__help">
                支持添加多个远程存储配置,修改后立即生效无需重启服务
              </div>
            </el-form-item>
            <el-form-item>
              <el-button 
                type="primary" 
                @click="saveRcloneConfigFile" 
                :loading="savingRcloneConfig"
                :disabled="!rcloneConfigContent"
              >
                保存配置文件
              </el-button>
              <el-button @click="loadRcloneConfigFile" :loading="loadingRcloneConfig">
                重新加载
              </el-button>
              <span v-if="rcloneConfigLastSaved" style="margin-left: 10px; color: #909399; font-size: 12px;">
                {{ rcloneConfigLastSaved }}
              </span>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 下载配置 -->
      <el-tab-pane label="下载配置" name="download">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>下载设置</span>
              <el-button type="primary" @click="saveConfig('download')" :loading="saving">
                保存配置
              </el-button>
            </div>
          </template>
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 20px"
          >
            <template #title>
              <div style="font-size: 13px">
                <strong>提示：</strong>下载配置保存后会立即生效，下次下载时会自动从数据库读取最新配置，无需重启服务。
              </div>
            </template>
          </el-alert>
          <el-form :model="configs.download" label-width="180px" :disabled="reloading">
            <el-form-item label="保存路径">
              <el-input v-model="configs.download.SAVE_PATH" />
            </el-form-item>
            <el-form-item label="代理IP">
              <el-input v-model="configs.download.PROXY_IP" placeholder="留空则不使用代理" />
            </el-form-item>
            <el-form-item label="代理端口">
              <el-input v-model="configs.download.PROXY_PORT" placeholder="留空则不使用代理" />
            </el-form-item>
            <el-divider />
            <el-form-item label="跳过小文件">
              <el-switch v-model="configs.download.SKIP_SMALL_FILES" />
              <div class="el-form-item__help">
                启用后，小于指定大小的媒体文件将不会被下载
              </div>
            </el-form-item>
            <el-form-item 
              label="最小文件大小（MB）" 
              v-if="configs.download.SKIP_SMALL_FILES"
            >
              <el-input-number 
                v-model="configs.download.MIN_FILE_SIZE_MB" 
                :min="1" 
                :max="10000" 
                style="width: 100%" 
              />
              <div class="el-form-item__help">
                小于此大小的文件将被跳过下载（默认：100MB）
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- Aria2配置 -->
      <el-tab-pane label="Aria2配置" name="aria2">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>Aria2 RPC配置</span>
              <el-button type="primary" @click="saveConfig('aria2')" :loading="saving">
                保存配置
              </el-button>
            </div>
          </template>
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 20px"
          >
            <template #title>
              <div style="font-size: 13px">
                <strong>提示：</strong>Aria2配置保存后会立即生效，下次连接时会自动从数据库读取最新配置，无需重启服务。
              </div>
            </template>
          </el-alert>
          <el-form :model="configs.aria2" label-width="180px">
            <el-form-item label="RPC密钥">
              <el-input v-model="configs.aria2.RPC_SECRET" type="password" show-password />
            </el-form-item>
            <el-form-item label="RPC URL">
              <el-input v-model="configs.aria2.RPC_URL" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 直链功能配置 -->
      <el-tab-pane label="直链功能" name="stream">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>直链功能配置</span>
              <el-button type="primary" @click="saveConfig('stream')" :loading="saving">
                保存配置
              </el-button>
            </div>
          </template>
          <el-form :model="configs.stream" label-width="180px">
            <el-form-item label="启用直链功能">
              <el-switch v-model="configs.stream.ENABLE_STREAM" />
            </el-form-item>
            <el-form-item label="日志频道ID">
              <el-input v-model="configs.stream.BIN_CHANNEL" />
            </el-form-item>
            <el-form-item label="Web服务器端口">
              <el-input-number v-model="configs.stream.STREAM_PORT" :min="1" :max="65535" style="width: 100%" />
            </el-form-item>
            <el-form-item label="绑定地址">
              <el-input v-model="configs.stream.STREAM_BIND_ADDRESS" />
            </el-form-item>
            <el-form-item label="哈希长度">
              <el-input-number v-model="configs.stream.STREAM_HASH_LENGTH" :min="5" :max="64" style="width: 100%" />
            </el-form-item>
            <el-form-item label="使用SSL">
              <el-switch v-model="configs.stream.STREAM_HAS_SSL" />
            </el-form-item>
            <el-form-item label="隐藏端口">
              <el-switch v-model="configs.stream.STREAM_NO_PORT" />
            </el-form-item>
            <el-form-item label="完全限定域名">
              <el-input v-model="configs.stream.STREAM_FQDN" />
            </el-form-item>
            <el-form-item label="保持连接活跃">
              <el-switch v-model="configs.stream.STREAM_KEEP_ALIVE" />
            </el-form-item>
            <el-form-item label="Ping间隔（秒）">
              <el-input-number v-model="configs.stream.STREAM_PING_INTERVAL" :min="60" style="width: 100%" />
            </el-form-item>
            <el-form-item label="使用会话文件">
              <el-switch v-model="configs.stream.STREAM_USE_SESSION_FILE" />
            </el-form-item>
            <el-form-item label="允许使用直链的用户">
              <el-input v-model="configs.stream.STREAM_ALLOWED_USERS" placeholder="逗号分隔，留空则允许所有人" />
            </el-form-item>
            <el-form-item label="自动添加到下载队列">
              <el-switch v-model="configs.stream.STREAM_AUTO_DOWNLOAD" />
            </el-form-item>
            <el-form-item label="只使用TG网盘">
              <el-switch v-model="configs.stream.STREAM_TG_DISK_ONLY" />
              <div class="el-form-item__help">
                开启后仅转发媒体到 TG 网盘频道，不再走服务端 aria2 下载和后续上传链路
              </div>
            </el-form-item>
            <el-form-item label="发送直链信息给用户">
              <el-switch v-model="configs.stream.SEND_STREAM_LINK" />
            </el-form-item>
            <el-form-item label="多机器人Token列表">
              <el-input
                v-model="multiBotTokensText"
                type="textarea"
                :rows="4"
                placeholder="每行一个Token，或逗号分隔"
                @input="updateMultiBotTokens"
              />
              <div class="el-form-item__help">
                当前配置了 {{ (configs.stream.MULTI_BOT_TOKENS || []).length }} 个额外的Bot Token
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getConfig, updateConfig, reloadConfig, getRcloneConfig, saveRcloneConfig, getRcloneRemotes, type RcloneRemote } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { checkServerConnection } from '@/utils/connection'
import { getServerBaseUrl, isValidServerBaseUrl, setServerBaseUrl } from '@/utils/runtime'
import { useRouter } from 'vue-router'

const router = useRouter()
const authStore = useAuthStore()
const activeTab = ref('client')
const saving = ref(false)
const reloading = ref(false)
const clientServerUrl = ref(getServerBaseUrl())
const testingConnection = ref(false)
const savingClientConnection = ref(false)
const connectionState = ref<'idle' | 'success' | 'error'>('idle')
const connectionStatusText = ref('')
// Rclone 配置文件管理相关状态
const rcloneConfigContent = ref('')
const rcloneConfigPath = ref('/root/.config/rclone/rclone.conf')
const loadingRcloneConfig = ref(false)
const savingRcloneConfig = ref(false)
const rcloneConfigLastSaved = ref('')

// Rclone remotes 列表
const availableRemotes = ref<RcloneRemote[]>([])
const configCategories = ['telegram', 'rclone', 'download', 'aria2', 'stream'] as const
type ConfigCategory = typeof configCategories[number]

const effectiveServerUrlLabel = computed(() => clientServerUrl.value || '同源 /api')
const connectionStatusLabel = computed(() => {
  if (connectionState.value === 'success') return '已连接'
  if (connectionState.value === 'error') return '不可用'
  return '未检测'
})
const connectionStatusTagType = computed(() => {
  if (connectionState.value === 'success') return 'success'
  if (connectionState.value === 'error') return 'danger'
  return 'info'
})
// 配置数据
const configs = ref({
  telegram: {
    API_ID: 0,
    API_HASH: '',
    BOT_TOKEN: '',
    ADMIN_ID: 0,
    FORWARD_ID: '',
    UP_TELEGRAM: false
  },
  rclone: {
    UP_ONEDRIVE: false,
    RCLONE_REMOTE: 'onedrive',
    RCLONE_PATH: '/Downloads',
    UP_GOOGLE_DRIVE: false,
    GOOGLE_DRIVE_REMOTE: 'gdrive',
    GOOGLE_DRIVE_PATH: '/Downloads',
    AUTO_DELETE_AFTER_UPLOAD: true
  },
  download: {
    SAVE_PATH: '/root/mistrelay_downloads',
    PROXY_IP: '',
    PROXY_PORT: '',
    SKIP_SMALL_FILES: false,
    MIN_FILE_SIZE_MB: 100
  },
  aria2: {
    RPC_SECRET: '',
    RPC_URL: 'localhost:6800/jsonrpc'
  },
  stream: {
    ENABLE_STREAM: true,
    BIN_CHANNEL: '',
    STREAM_PORT: 8080,
    STREAM_BIND_ADDRESS: '127.0.0.1',
    STREAM_HASH_LENGTH: 6,
    STREAM_HAS_SSL: false,
    STREAM_NO_PORT: false,
    STREAM_FQDN: '',
    STREAM_KEEP_ALIVE: false,
    STREAM_PING_INTERVAL: 1200,
    STREAM_USE_SESSION_FILE: false,
    STREAM_ALLOWED_USERS: '',
    STREAM_AUTO_DOWNLOAD: true,
    STREAM_TG_DISK_ONLY: false,
    SEND_STREAM_LINK: false,
    MULTI_BOT_TOKENS: [] as string[]
  }
})

// 多机器人Token文本（用于显示和编辑）
const multiBotTokensText = computed({
  get: () => {
    const tokens = configs.value.stream.MULTI_BOT_TOKENS || []
    return tokens.join('\n')
  },
  set: (val: string) => {
    updateMultiBotTokens(val)
  }
})

function updateMultiBotTokens(text: string) {
  if (!text.trim()) {
    configs.value.stream.MULTI_BOT_TOKENS = []
    return
  }
  // 支持换行和逗号分隔
  const tokens = text
    .split(/[,\n]/)
    .map(t => t.trim())
    .filter(t => t.length > 0)
  configs.value.stream.MULTI_BOT_TOKENS = tokens
}

// 表单验证规则
const rules = {
  API_ID: [{ required: true, message: '请输入API ID', trigger: 'blur' }],
  API_HASH: [{ required: true, message: '请输入API Hash', trigger: 'blur' }],
  BOT_TOKEN: [{ required: true, message: '请输入Bot Token', trigger: 'blur' }],
  ADMIN_ID: [{ required: true, message: '请输入管理员ID', trigger: 'blur' }]
}

async function testConnection(showMessage = true) {
  if (!isValidServerBaseUrl(clientServerUrl.value)) {
    connectionState.value = 'error'
    connectionStatusText.value = '服务器地址格式不正确'
    if (showMessage) {
      ElMessage.error(connectionStatusText.value)
    }
    return false
  }

  testingConnection.value = true
  try {
    const result = await checkServerConnection(clientServerUrl.value)
    connectionState.value = result.ok ? 'success' : 'error'
    connectionStatusText.value = result.message

    if (showMessage) {
      if (result.ok) {
        ElMessage.success(result.message)
      } else {
        ElMessage.error(result.message)
      }
    }

    return result.ok
  } finally {
    testingConnection.value = false
  }
}

async function saveClientConnection() {
  if (!isValidServerBaseUrl(clientServerUrl.value)) {
    ElMessage.error('服务器地址格式不正确')
    return
  }

  savingClientConnection.value = true
  try {
    const ok = await testConnection(false)
    if (!ok) {
      ElMessage.error(connectionStatusText.value || '服务器连接失败，未保存')
      return
    }

    const previousServerUrl = getServerBaseUrl()
    const nextServerUrl = setServerBaseUrl(clientServerUrl.value)

    if (nextServerUrl !== previousServerUrl) {
      authStore.logout()
      ElMessage.success('客户端连接已更新，请重新登录')
      router.push('/login')
      return
    }

    ElMessage.success('客户端连接已保存')
  } finally {
    savingClientConnection.value = false
  }
}

async function fetchConfigs() {
  try {
    for (const category of configCategories) {
      const response = await getConfig(category)
      if (response.success && response.data) {
        // 合并配置，保留默认值
        configs.value[category] = {
          ...configs.value[category],
          ...response.data
        }
      }
    }
  } catch (err) {
    console.error('获取配置失败:', err)
    ElMessage.error('获取配置失败')
  }
}

async function saveConfig(category: ConfigCategory) {
  if (reloading.value) {
    ElMessage.warning('配置正在重载中，请稍候...')
    return
  }
  
  saving.value = true
  try {
    const categoryConfig = configs.value[category]
    const response = await updateConfig(categoryConfig)
    
    if (response.success) {
      if (response.needs_restart) {
        ElMessage.warning({
          message: response.message || '配置已保存，但需要重启服务才能生效',
          duration: 5000
        })
      } else {
        ElMessage.success(response.message || '配置已保存，下次使用时将从数据库读取最新配置')
      }
      // 重新获取配置以确保同步
      await fetchConfigs()
    } else {
      ElMessage.error(response.error || '配置保存失败')
    }
  } catch (err: any) {
    console.error('保存配置失败:', err)
    ElMessage.error(err.message || '配置保存失败')
  } finally {
    saving.value = false
  }
}

async function handleReloadConfig() {
  try {
    await ElMessageBox.confirm(
      '确定要从config.yml重新导入配置到数据库吗？这将会覆盖数据库中的现有配置。',
      '确认导入配置',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info'
      }
    )
    
    // 开始重载，锁定页面
    reloading.value = true
    
    try {
      const response = await reloadConfig()
      if (response.success) {
        ElMessage.success(response.message || '配置已从config.yml重新导入到数据库')
        // 重新获取配置
        await fetchConfigs()
      } else {
        ElMessage.error(response.error || '配置导入失败')
      }
    } catch (err: any) {
      console.error('导入配置失败:', err)
      ElMessage.error(err.message || '配置导入失败')
    } finally {
      // 重载完成，解锁页面
      reloading.value = false
    }
  } catch (err: any) {
    if (err !== 'cancel') {
      console.error('重载配置失败:', err)
      ElMessage.error(err.message || '配置重载失败')
    }
  }
}

// Rclone 配置文件管理函数
async function loadRcloneConfigFile() {
  loadingRcloneConfig.value = true
  try {
    const response = await getRcloneConfig()
    if (response.success) {
      rcloneConfigContent.value = response.content || ''
      rcloneConfigPath.value = response.file_path || '/root/.config/rclone/rclone.conf'
      if (!response.exists) {
        ElMessage.info(response.message || '配置文件不存在')
      } else {
        ElMessage.success('配置文件加载成功')
      }
      rcloneConfigLastSaved.value = ''
    } else {
      ElMessage.error(response.error || '加载配置文件失败')
    }
  } catch (err: any) {
    console.error('加载 Rclone 配置失败:', err)
    ElMessage.error(err.message || '加载配置文件失败')
  } finally {
    loadingRcloneConfig.value = false
  }
}

async function saveRcloneConfigFile() {
  if (!rcloneConfigContent.value.trim()) {
    ElMessage.warning('配置内容不能为空')
    return
  }
  
  try {
    await ElMessageBox.confirm(
      '确定要保存 Rclone 配置文件吗?原文件将被备份为 rclone.conf.bak',
      '确认保存',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    savingRcloneConfig.value = true
    
    try {
      const response = await saveRcloneConfig(rcloneConfigContent.value)
      if (response.success) {
        ElMessage.success(response.message || '配置文件保存成功')
        const now = new Date()
        rcloneConfigLastSaved.value = `最后保存: ${now.toLocaleString()}`
        // 重新加载配置以确保同步
        await loadRcloneConfigFile()
        // 刷新 remotes 列表
        await loadRcloneRemotes()
      } else {
        ElMessage.error(response.error || '保存配置文件失败')
      }
    } catch (err: any) {
      console.error('保存 Rclone 配置失败:', err)
      ElMessage.error(err.message || '保存配置文件失败')
    } finally {
      savingRcloneConfig.value = false
    }
  } catch (err: any) {
    if (err !== 'cancel') {
      console.error('保存配置失败:', err)
    }
  }
}

// 加载 Rclone Remotes 列表
async function loadRcloneRemotes() {
  try {
    const response = await getRcloneRemotes()
    if (response.success && response.remotes) {
      availableRemotes.value = response.remotes
    } else {
      availableRemotes.value = []
    }
  } catch (err: any) {
    console.error('加载 Rclone remotes 失败:', err)
    availableRemotes.value = []
  }
}

onMounted(() => {
  fetchConfigs()
  void testConnection(false)
  // 自动加载 Rclone 配置文件
  loadRcloneConfigFile()
  // 自动加载 Rclone remotes 列表
  loadRcloneRemotes()
})
</script>

<style scoped>
.settings-page {
  @apply space-y-6;
}

.page-header {
  @apply mb-6 flex items-center justify-between;
}

.page-title {
  @apply text-3xl font-bold text-gray-800 mb-2;
}

.page-subtitle {
  @apply text-gray-600;
}

.card-header {
  @apply flex items-center justify-between;
}

.card-actions {
  @apply flex items-center gap-3;
}

.connection-status {
  @apply flex items-center gap-3;
}

.connection-status-text {
  @apply text-sm text-gray-500;
}

.quick-actions {
  @apply space-y-3;
}

.el-form-item__help {
  @apply text-xs text-gray-500 mt-1;
}
</style>
