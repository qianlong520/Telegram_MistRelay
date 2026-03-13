<template>
  <div class="settings-page">
      <div class="scope-bar">
      <el-radio-group v-model="settingsScope" size="large" class="scope-switch">
        <el-radio-button label="client">客户端设置</el-radio-button>
        <el-radio-button label="server">服务端设置</el-radio-button>
      </el-radio-group>
    </div>

    <div v-if="settingsScope === 'client'" class="scope-panel">
      <el-tabs v-model="activeClientTab" type="border-card">
        <el-tab-pane label="连接" name="connection">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <div class="card-actions">
                <el-button @click="testConnection" :loading="testingConnection">
                  测试连接
                </el-button>
                <el-button type="primary" @click="saveClientConnection" :loading="savingClientConnection">
                  保存并应用
                </el-button>
              </div>
            </div>

            <el-form label-width="180px">
              <el-form-item label="服务器地址">
                <el-input
                  v-model="clientServerUrl"
                  placeholder="https://mistrelay.example.com"
                  clearable
                />
                <div class="el-form-item__help">
                  这里只配置桌面端要连接的服务端地址，不影响服务器本身的运行参数。
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

        <el-tab-pane label="更新" name="update">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <div class="card-actions">
                <el-button @click="handleCheckUpdate" :loading="checkingUpdate" :disabled="installingUpdate">
                  检查更新
                </el-button>
                <el-button
                  v-if="updateAvailable"
                  type="primary"
                  @click="handleInstallUpdate"
                  :loading="installingUpdate"
                >
                  更新到 v{{ updateVersion }}
                </el-button>
              </div>
            </div>

            <el-form label-width="180px">
              <el-form-item label="当前版本">
                <div class="version-row">
                  <el-tag type="info">v{{ appVersion }}</el-tag>
                </div>
              </el-form-item>
              <el-form-item v-if="updateStatusText" label="更新状态">
                <div class="connection-status">
                  <el-tag :type="updateStatusTagType">{{ updateStatusLabel }}</el-tag>
                  <span class="connection-status-text">{{ updateStatusText }}</span>
                </div>
              </el-form-item>
              <el-form-item v-if="installingUpdate && updateProgressPercent >= 0" label="下载进度">
                <el-progress :percentage="updateProgressPercent" :stroke-width="18" striped striped-flow />
              </el-form-item>
              <el-form-item v-if="updateBody" label="发布说明">
                <div class="release-notes">{{ updateBody }}</div>
              </el-form-item>
            </el-form>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="代理" name="proxy">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <div class="card-actions">
                <el-button @click="loadDesktopProxyConfig" :loading="loadingDesktopProxyConfig">
                  重新读取
                </el-button>
                <el-button type="primary" @click="saveDesktopProxyConfig" :loading="savingDesktopProxyConfig">
                  保存代理配置
                </el-button>
                <el-button type="warning" @click="restartDesktopClient" :loading="restartingDesktopClient">
                  立即重启客户端
                </el-button>
              </div>
            </div>

            <el-form label-width="180px">
              <el-form-item label="启用桌面代理">
                <el-switch v-model="desktopProxyEnabled" />
              </el-form-item>
              <el-form-item label="代理地址">
                <el-input
                  v-model="desktopProxyUrl"
                  :disabled="!desktopProxyEnabled"
                  placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:1080"
                  clearable
                />
                <div class="el-form-item__help">
                  支持 `http://` 和 `socks5://`，如需认证可写成 `http://user:pass@host:port`。启用后，PC 客户端所有网络流量都会走这个代理。
                </div>
              </el-form-item>
              <el-form-item label="代理状态">
                <div class="connection-status">
                  <el-tag :type="desktopProxyStatusTagType">
                    {{ desktopProxyStatusLabel }}
                  </el-tag>
                  <span v-if="desktopProxyStatusText" class="connection-status-text">
                    {{ desktopProxyStatusText }}
                  </span>
                </div>
              </el-form-item>
            </el-form>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="下载" name="download">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <div class="card-actions">
                <el-button @click="loadDownloadConfig" :loading="loadingDownloadConfig">重新读取</el-button>
                <el-button type="primary" @click="saveDownloadConfig" :loading="savingDownloadConfig">保存配置</el-button>
              </div>
            </div>

            <div class="download-summary-grid">
              <div class="download-summary-tile">
                <div class="download-summary-label">当前生效目录</div>
                <div class="download-summary-value is-path" :title="effectiveDesktopDownloadDir">{{ effectiveDesktopDownloadDir }}</div>
              </div>
              <div class="download-summary-tile">
                <div class="download-summary-label">默认目录</div>
                <div class="download-summary-value is-path" :title="defaultDesktopDownloadDir || '读取中...'">{{ defaultDesktopDownloadDir || '读取中...' }}</div>
              </div>
              <div class="download-summary-tile">
                <div class="download-summary-label">下载并发</div>
                <div class="download-summary-value">{{ desktopMaxConcurrent }}</div>
              </div>
              <div class="download-summary-tile">
                <div class="download-summary-label">单文件线程</div>
                <div class="download-summary-value">{{ desktopThreadsPerDownload }}</div>
              </div>
            </div>

            <el-form label-width="180px" style="margin-top: 20px; max-width: 860px;">
              <el-form-item label="下载目录">
                <div class="download-dir-row">
                  <el-input
                    v-model="desktopDownloadDir"
                    placeholder="留空则使用系统下载目录下的 MistRelay 文件夹"
                    clearable
                  />
                  <el-button @click="handlePickDownloadDir">选择文件夹</el-button>
                </div>
                <div class="el-form-item__help">
                  请输入绝对路径。留空则自动恢复默认目录。
                </div>
              </el-form-item>

              <el-form-item label="最大并行下载数">
                <el-input-number
                  v-model="desktopMaxConcurrent"
                  :min="1"
                  :max="10"
                  :step="1"
                />
                <div class="el-form-item__help">
                  同时下载多少个文件，超过的任务会排队等待。
                </div>
              </el-form-item>

              <el-form-item label="每文件下载线程数">
                <el-input-number
                  v-model="desktopThreadsPerDownload"
                  :min="2"
                  :max="32"
                  :step="1"
                />
                <div class="el-form-item__help">
                  单个文件至少使用 2 个线程；如果服务端有 4 个可用 bot，实际下载会至少提升到 4 个连接。下载源不支持 Range 时会直接报错。
                </div>
              </el-form-item>

              <el-form-item>
                <el-button @click="desktopDownloadDir = ''">恢复默认目录</el-button>
              </el-form-item>
            </el-form>
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </div>

    <div v-else class="scope-panel">
      <div class="server-actions">
        <el-button type="info" @click="handleReloadConfig" :loading="reloading" :disabled="reloading">
          从 config.yml 重新导入
        </el-button>
      </div>

      <el-tabs v-model="activeServerTab" type="border-card">
        <el-tab-pane label="Telegram配置" name="telegram">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <el-button type="primary" @click="saveConfig('telegram')" :loading="saving" :disabled="reloading">
                保存配置
              </el-button>
            </div>
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

        <el-tab-pane label="Rclone配置" name="rclone">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <el-button type="primary" @click="saveConfig('rclone')" :loading="saving">
                保存配置
              </el-button>
            </div>
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

        <el-tab-pane label="下载配置" name="download">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <el-button type="primary" @click="saveConfig('download')" :loading="saving">
                保存配置
              </el-button>
            </div>
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
                v-if="configs.download.SKIP_SMALL_FILES"
                label="最小文件大小（MB）"
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

        <el-tab-pane label="Aria2配置" name="aria2">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <el-button type="primary" @click="saveConfig('aria2')" :loading="saving">
                保存配置
              </el-button>
            </div>
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

        <el-tab-pane label="直链功能" name="stream">
          <el-card shadow="hover">
            <div class="panel-toolbar">
              <el-button type="primary" @click="saveConfig('stream')" :loading="saving">
                保存配置
              </el-button>
            </div>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getConfig, updateConfig, reloadConfig, getRcloneConfig, saveRcloneConfig, getRcloneRemotes, type RcloneRemote } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { checkServerConnection } from '@/utils/connection'
import { DEFAULT_DOWNLOAD_CONFIG, getDefaultDesktopDownloadDir, getDesktopClientConfig, isValidDesktopProxyUrl, pickDesktopDownloadDir, restartDesktopApp, saveDesktopClientConfig, checkForUpdate, downloadAndInstallUpdate, type UpdateProgress } from '@/utils/desktop'
import type { Update } from '@tauri-apps/plugin-updater'
import { getServerBaseUrl, isValidServerBaseUrl, setServerBaseUrl } from '@/utils/runtime'
import { useRouter } from 'vue-router'

const router = useRouter()
const authStore = useAuthStore()
const settingsScope = ref<'client' | 'server'>('client')
const activeClientTab = ref('connection')
const activeServerTab = ref('telegram')
const saving = ref(false)
const reloading = ref(false)
const clientServerUrl = ref(getServerBaseUrl())
const testingConnection = ref(false)
const savingClientConnection = ref(false)
const connectionState = ref<'idle' | 'success' | 'error'>('idle')
const connectionStatusText = ref('')
const loadingDesktopProxyConfig = ref(false)
const savingDesktopProxyConfig = ref(false)
const restartingDesktopClient = ref(false)
const desktopProxyEnabled = ref(false)
const desktopProxyUrl = ref('')
const desktopProxyStatus = ref<'idle' | 'enabled' | 'disabled' | 'pending'>('idle')
const desktopProxyStatusText = ref('')

const loadingDownloadConfig = ref(false)
const savingDownloadConfig = ref(false)
const defaultDesktopDownloadDir = ref('')
const desktopDownloadDir = ref(DEFAULT_DOWNLOAD_CONFIG.downloadDir)
const desktopMaxConcurrent = ref(DEFAULT_DOWNLOAD_CONFIG.maxConcurrentDownloads)
const desktopThreadsPerDownload = ref(DEFAULT_DOWNLOAD_CONFIG.threadsPerDownload)

const effectiveDesktopDownloadDir = computed(() => {
  const configured = desktopDownloadDir.value.trim()
  return configured || defaultDesktopDownloadDir.value || '读取中...'
})

const appVersion = __APP_VERSION__
const checkingUpdate = ref(false)
const installingUpdate = ref(false)
const updateAvailable = ref(false)
const updateVersion = ref('')
const updateBody = ref('')
const updateStatusText = ref('')
const updateStatus = ref<'idle' | 'available' | 'latest' | 'downloading' | 'error'>('idle')
const updateProgressPercent = ref(-1)
let pendingUpdate: Update | null = null

const updateStatusLabel = computed(() => {
  if (updateStatus.value === 'available') return '有新版本'
  if (updateStatus.value === 'latest') return '已是最新'
  if (updateStatus.value === 'downloading') return '下载中'
  if (updateStatus.value === 'error') return '检查失败'
  return ''
})
const updateStatusTagType = computed(() => {
  if (updateStatus.value === 'available') return 'warning'
  if (updateStatus.value === 'latest') return 'success'
  if (updateStatus.value === 'downloading') return ''
  if (updateStatus.value === 'error') return 'danger'
  return 'info'
})

const rcloneConfigContent = ref('')
const rcloneConfigPath = ref('/root/.config/rclone/rclone.conf')
const loadingRcloneConfig = ref(false)
const savingRcloneConfig = ref(false)
const rcloneConfigLastSaved = ref('')

const availableRemotes = ref<RcloneRemote[]>([])
const configCategories = ['telegram', 'rclone', 'download', 'aria2', 'stream'] as const
type ConfigCategory = typeof configCategories[number]
const loadedClientTabs = ref({
  proxy: false,
  download: false,
})
const loadedServerCategories = ref<Partial<Record<ConfigCategory, boolean>>>({})
const rcloneConfigLoaded = ref(false)
const rcloneRemotesLoaded = ref(false)

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
const desktopProxyStatusLabel = computed(() => {
  if (desktopProxyStatus.value === 'enabled') return '已启用'
  if (desktopProxyStatus.value === 'disabled') return '未启用'
  if (desktopProxyStatus.value === 'pending') return '待重启生效'
  return '未读取'
})
const desktopProxyStatusTagType = computed(() => {
  if (desktopProxyStatus.value === 'enabled') return 'success'
  if (desktopProxyStatus.value === 'pending') return 'warning'
  return 'info'
})

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

  const tokens = text
    .split(/[,\n]/)
    .map(t => t.trim())
    .filter(t => t.length > 0)
  configs.value.stream.MULTI_BOT_TOKENS = tokens
}

const rules = {
  API_ID: [{ required: true, message: '请输入API ID', trigger: 'blur' }],
  API_HASH: [{ required: true, message: '请输入API Hash', trigger: 'blur' }],
  BOT_TOKEN: [{ required: true, message: '请输入Bot Token', trigger: 'blur' }],
  ADMIN_ID: [{ required: true, message: '请输入管理员ID', trigger: 'blur' }]
}

async function testConnection(showMessage = true) {
  if (!clientServerUrl.value) {
    connectionState.value = 'error'
    connectionStatusText.value = '桌面端必须填写服务器地址'
    if (showMessage) {
      ElMessage.error(connectionStatusText.value)
    }
    return false
  }

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
  if (!clientServerUrl.value) {
    ElMessage.error('桌面端必须填写服务器地址')
    return
  }

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

async function loadDesktopProxyConfig(showMessage = false) {
  loadingDesktopProxyConfig.value = true
  try {
    const config = await getDesktopClientConfig()
    desktopProxyEnabled.value = config.proxy.enabled
    desktopProxyUrl.value = config.proxy.url
    desktopProxyStatus.value = config.proxy.enabled ? 'enabled' : 'disabled'
    desktopProxyStatusText.value = config.proxy.enabled
      ? `当前客户端重启后会通过 ${config.proxy.url} 走全局代理`
      : '当前客户端处于直连模式，不使用全局代理'
    loadedClientTabs.value = {
      ...loadedClientTabs.value,
      proxy: true,
    }

    if (showMessage) {
      ElMessage.success('桌面代理配置已读取')
    }
  } catch (err: any) {
    console.error('加载桌面代理配置失败:', err)
    desktopProxyStatus.value = 'idle'
    desktopProxyStatusText.value = err.message || '读取失败'
    ElMessage.error(err.message || '加载桌面代理配置失败')
  } finally {
    loadingDesktopProxyConfig.value = false
  }
}

async function saveDesktopProxyConfig() {
  const proxyUrl = desktopProxyUrl.value.trim()

  if (desktopProxyEnabled.value && !proxyUrl) {
    ElMessage.error('启用桌面代理时必须填写代理地址')
    return
  }

  if (desktopProxyEnabled.value && !isValidDesktopProxyUrl(proxyUrl)) {
    ElMessage.error('代理地址格式不正确，只支持 http:// 或 socks5://')
    return
  }

  savingDesktopProxyConfig.value = true
  try {
    const current = await getDesktopClientConfig()
    await saveDesktopClientConfig({
      ...current,
      proxy: {
        enabled: desktopProxyEnabled.value,
        url: proxyUrl,
      },
    })

    desktopProxyUrl.value = proxyUrl
    desktopProxyStatus.value = 'pending'
    desktopProxyStatusText.value = desktopProxyEnabled.value
      ? '全局代理配置已保存，重启客户端后所有网络流量都会切到该代理'
      : '全局代理关闭已保存，重启客户端后会恢复直连模式'

    ElMessage.success('桌面全局代理配置已保存，重启客户端后生效')
  } catch (err: any) {
    console.error('保存桌面代理配置失败:', err)
    ElMessage.error(err.message || '保存桌面代理配置失败')
  } finally {
    savingDesktopProxyConfig.value = false
  }
}

async function restartDesktopClient() {
  try {
    await ElMessageBox.confirm(
      '桌面客户端将立即重启，以应用最新的代理配置。',
      '确认重启客户端',
      {
        confirmButtonText: '立即重启',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    restartingDesktopClient.value = true
    await restartDesktopApp()
  } catch (err: any) {
    if (err !== 'cancel') {
      console.error('重启桌面客户端失败:', err)
      ElMessage.error(err.message || '重启桌面客户端失败')
    }
  } finally {
    restartingDesktopClient.value = false
  }
}

async function loadDownloadConfig(showMessage = false) {
  loadingDownloadConfig.value = true
  try {
    const [config, defaultDir] = await Promise.all([
      getDesktopClientConfig(),
      getDefaultDesktopDownloadDir(),
    ])
    const downloadConfig = config.download ?? DEFAULT_DOWNLOAD_CONFIG
    defaultDesktopDownloadDir.value = defaultDir
    desktopDownloadDir.value = downloadConfig.downloadDir ?? ''
    desktopMaxConcurrent.value = downloadConfig.maxConcurrentDownloads
    desktopThreadsPerDownload.value = downloadConfig.threadsPerDownload
    loadedClientTabs.value = {
      ...loadedClientTabs.value,
      download: true,
    }
    if (showMessage) {
      ElMessage.success('本地下载配置已读取')
    }
  } catch (err: any) {
    console.error('加载本地下载配置失败:', err)
    ElMessage.error(err.message || '加载本地下载配置失败')
  } finally {
    loadingDownloadConfig.value = false
  }
}

async function saveDownloadConfig() {
  savingDownloadConfig.value = true
  try {
    const current = await getDesktopClientConfig()
    await saveDesktopClientConfig({
      ...current,
      download: {
        downloadDir: desktopDownloadDir.value.trim(),
        maxConcurrentDownloads: desktopMaxConcurrent.value,
        threadsPerDownload: desktopThreadsPerDownload.value,
      },
    })
    ElMessage.success('本地下载配置已保存并立即生效')
    await loadDownloadConfig(false)
  } catch (err: any) {
    console.error('保存本地下载配置失败:', err)
    ElMessage.error(err.message || '保存本地下载配置失败')
  } finally {
    savingDownloadConfig.value = false
  }
}

async function handlePickDownloadDir() {
  try {
    const selected = await pickDesktopDownloadDir(desktopDownloadDir.value || defaultDesktopDownloadDir.value)
    if (selected) {
      desktopDownloadDir.value = selected
    }
  } catch (err: any) {
    console.error('选择下载目录失败:', err)
    ElMessage.error(err.message || '选择下载目录失败')
  }
}

async function handleCheckUpdate() {
  checkingUpdate.value = true
  updateStatusText.value = ''
  updateStatus.value = 'idle'
  updateAvailable.value = false
  updateBody.value = ''
  pendingUpdate = null
  try {
    const { result, update } = await checkForUpdate()
    if (result.available && update) {
      updateAvailable.value = true
      updateVersion.value = result.version || ''
      updateBody.value = result.body || ''
      updateStatus.value = 'available'
      updateStatusText.value = result.body
        ? `v${result.version} — ${result.body}`
        : `v${result.version} 可用`
      pendingUpdate = update
    } else if (result.available) {
      updateAvailable.value = false
      updateVersion.value = result.version || ''
      updateBody.value = [result.body, result.manualUrl ? `下载地址：${result.manualUrl}` : '']
        .filter(Boolean)
        .join('\n')
      updateStatus.value = 'available'
      updateStatusText.value = result.message || `发现 v${result.version}`
      pendingUpdate = null
    } else {
      updateStatus.value = 'latest'
      updateStatusText.value = result.message || '当前已是最新版本'
    }
  } catch (err: any) {
    console.error('检查更新失败:', err)
    updateStatus.value = 'error'
    updateStatusText.value = err.message || '检查更新失败'
    ElMessage.error(updateStatusText.value)
  } finally {
    checkingUpdate.value = false
  }
}

async function handleInstallUpdate() {
  if (!pendingUpdate) return

  try {
    await ElMessageBox.confirm(
      `确定要更新到 v${updateVersion.value} 吗？更新完成后客户端将自动重启。`,
      '确认更新',
      {
        confirmButtonText: '立即更新',
        cancelButtonText: '取消',
        type: 'info',
      },
    )
  } catch {
    return
  }

  installingUpdate.value = true
  updateStatus.value = 'downloading'
  updateProgressPercent.value = 0
  updateStatusText.value = '正在下载更新…'

  try {
    await downloadAndInstallUpdate(pendingUpdate, (progress: UpdateProgress) => {
      if (progress.total && progress.total > 0) {
        updateProgressPercent.value = Math.round((progress.downloaded / progress.total) * 100)
      }
      if (progress.done) {
        updateStatusText.value = '下载完成，正在安装并重启…'
      }
    })
  } catch (err: any) {
    console.error('安装更新失败:', err)
    updateStatus.value = 'error'
    updateStatusText.value = err.message || '安装更新失败'
    ElMessage.error(updateStatusText.value)
    installingUpdate.value = false
    updateProgressPercent.value = -1
  }
}

async function loadServerConfigCategory(category: ConfigCategory, force = false) {
  if (!force && loadedServerCategories.value[category]) {
    return
  }

  try {
    const response = await getConfig(category)
    if (response.success && response.data) {
      configs.value[category] = {
        ...configs.value[category],
        ...response.data
      }
      loadedServerCategories.value = {
        ...loadedServerCategories.value,
        [category]: true,
      }
    }
  } catch (err) {
    console.error(`获取 ${category} 配置失败:`, err)
    ElMessage.error(`获取${category}配置失败`)
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
      await loadServerConfigCategory(category, true)
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

    reloading.value = true

    try {
      const response = await reloadConfig()
      if (response.success) {
        ElMessage.success(response.message || '配置已从config.yml重新导入到数据库')
        loadedServerCategories.value = {}
        await loadServerConfigCategory(activeServerTab.value as ConfigCategory, true)
      } else {
        ElMessage.error(response.error || '配置导入失败')
      }
    } catch (err: any) {
      console.error('导入配置失败:', err)
      ElMessage.error(err.message || '配置导入失败')
    } finally {
      reloading.value = false
    }
  } catch (err: any) {
    if (err !== 'cancel') {
      console.error('重载配置失败:', err)
      ElMessage.error(err.message || '配置重载失败')
    }
  }
}

async function loadRcloneConfigFile(showMessage = false) {
  loadingRcloneConfig.value = true
  try {
    const response = await getRcloneConfig()
    if (response.success) {
      rcloneConfigContent.value = response.content || ''
      rcloneConfigPath.value = response.file_path || '/root/.config/rclone/rclone.conf'
      rcloneConfigLoaded.value = true
      if (showMessage) {
        if (!response.exists) {
          ElMessage.info(response.message || '配置文件不存在')
        } else {
          ElMessage.success('配置文件加载成功')
        }
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
        await Promise.all([
          loadRcloneConfigFile(false),
          loadRcloneRemotes(),
        ])
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

async function loadRcloneRemotes() {
  try {
    const response = await getRcloneRemotes()
    if (response.success && response.remotes) {
      availableRemotes.value = response.remotes
      rcloneRemotesLoaded.value = true
    } else {
      availableRemotes.value = []
    }
  } catch (err: any) {
    console.error('加载 Rclone remotes 失败:', err)
    availableRemotes.value = []
  }
}

async function ensureClientTabLoaded(tab: string) {
  if (tab === 'proxy' && !loadedClientTabs.value.proxy) {
    await loadDesktopProxyConfig()
    return
  }

  if (tab === 'download' && !loadedClientTabs.value.download) {
    await loadDownloadConfig()
  }
}

async function ensureServerTabLoaded(tab: string) {
  if (!configCategories.includes(tab as ConfigCategory)) {
    return
  }

  const category = tab as ConfigCategory
  const tasks: Promise<unknown>[] = [loadServerConfigCategory(category)]

  if (category === 'rclone') {
    if (!rcloneConfigLoaded.value) {
      tasks.push(loadRcloneConfigFile(false))
    }
    if (!rcloneRemotesLoaded.value) {
      tasks.push(loadRcloneRemotes())
    }
  }

  await Promise.all(tasks)
}

onMounted(() => {
  void testConnection(false)
  if (settingsScope.value === 'client') {
    void ensureClientTabLoaded(activeClientTab.value)
  } else {
    void ensureServerTabLoaded(activeServerTab.value)
  }
})

watch(settingsScope, (scope) => {
  if (scope === 'client') {
    void ensureClientTabLoaded(activeClientTab.value)
  } else {
    void ensureServerTabLoaded(activeServerTab.value)
  }
})

watch(activeClientTab, (tab) => {
  if (settingsScope.value === 'client') {
    void ensureClientTabLoaded(tab)
  }
})

watch(activeServerTab, (tab) => {
  if (settingsScope.value === 'server') {
    void ensureServerTabLoaded(tab)
  }
})
</script>

<style scoped>
.settings-page {
  @apply space-y-6;
}

.scope-bar {
  @apply flex items-center;
}

.scope-switch {
  @apply self-start lg:self-auto;
}

.scope-panel {
  @apply space-y-4;
}

.server-actions {
  @apply flex items-center justify-end;
}

.card-actions {
  @apply flex items-center gap-3 flex-wrap;
}

.panel-toolbar {
  @apply mb-5 flex flex-col gap-3 border-b border-slate-100 pb-4 lg:flex-row lg:items-center lg:justify-between;
}

.connection-status {
  @apply flex items-center gap-3 flex-wrap;
}

.connection-status-text {
  @apply text-sm text-gray-500;
}

.version-row {
  @apply flex items-center gap-3 flex-wrap;
}

.release-notes {
  @apply rounded-xl bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-600 whitespace-pre-wrap;
}

.download-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
}

.download-summary-tile {
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid #dbeafe;
  background: linear-gradient(135deg, #f8fbff 0%, #ffffff 100%);
}

.download-summary-label {
  font-size: 12px;
  color: #64748b;
}

.download-summary-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
}

.download-summary-value.is-path {
  font-size: 13px;
  line-height: 1.6;
  font-weight: 600;
  word-break: break-all;
}

.download-dir-row {
  display: flex;
  gap: 10px;
  width: 100%;
}

.download-dir-row :deep(.el-input) {
  flex: 1;
}

.el-form-item__help {
  @apply mt-1 text-xs text-gray-500;
}
</style>
