<template>
  <div class="multi-source-sync">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="header-info">
          <h1 class="page-title">
            <el-icon class="title-icon"><Connection /></el-icon>
            多数据源同步
          </h1>
          <p class="page-description">
            管理和监控多个数据源的股票基础信息同步，支持自动fallback和优先级配置
          </p>
        </div>
        <div class="header-actions">
          <el-button
            type="primary"
            size="large"
            :loading="testing"
            @click="runFullTest"
          >
            <el-icon><Operation /></el-icon>
            全面测试
          </el-button>
        </div>
      </div>
    </div>

    <!-- 主要内容 -->
    <div class="page-content">
      <el-row :gutter="24">
        <!-- 左侧列 -->
        <el-col :lg="12" :md="24" :sm="24">
          <!-- 数据源状态 -->
          <div class="content-section">
            <DataSourceStatus ref="dataSourceStatusRef" />
          </div>
          
          <!-- 使用建议 -->
          <div class="content-section">
            <SyncRecommendations />
          </div>
        </el-col>

        <!-- 右侧列 -->
        <el-col :lg="12" :md="24" :sm="24">
          <!-- 同步控制 -->
          <div class="content-section">
            <SyncControl @sync-completed="handleSyncCompleted" />
          </div>

          <!-- A股内容同步 -->
          <div class="content-section">
            <el-card class="content-sync-card" shadow="hover">
              <template #header>
                <div class="card-header">
                  <el-icon class="header-icon"><Operation /></el-icon>
                  <span class="header-title">A股内容同步</span>
                </div>
              </template>

              <div class="content-sync-body">
                <p class="content-sync-description">
                  手动触发单只 A 股的原生社媒同步或新闻回退同步，结果会写入内容数据与同步记录。
                </p>

                <el-form :model="contentSyncForm" label-width="96px">
                  <el-form-item label="股票代码">
                    <el-input
                      v-model="contentSyncForm.symbol"
                      clearable
                      placeholder="请输入 6 位 A 股代码，如 600519"
                      @keyup.enter="runContentSync('native')"
                    />
                  </el-form-item>
                </el-form>

                <div class="content-sync-actions">
                  <el-button
                    type="primary"
                    :loading="contentSyncLoading && contentSyncMode === 'native'"
                    @click="runContentSync('native')"
                  >
                    原生社媒同步
                  </el-button>
                  <el-button
                    :loading="contentSyncLoading && contentSyncMode === 'news_proxy'"
                    @click="runContentSync('news_proxy')"
                  >
                    新闻回退同步
                  </el-button>
                </div>

                <el-alert
                  class="content-sync-alert"
                  type="info"
                  :closable="false"
                  show-icon
                  title="原生社媒同步优先抓取互动问答与热度信号；新闻回退同步会把已同步新闻转换为社媒快照。"
                />
              </div>
            </el-card>
          </div>
          
          <!-- 同步历史 -->
          <div class="content-section">
            <SyncHistory />
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 测试结果对话框 -->
    <el-dialog
      v-model="testDialogVisible"
      title="全面测试结果"
      width="80%"
      :close-on-click-modal="false"
    >
      <div v-if="testResults" class="test-results-dialog">
        <div class="test-summary">
          <el-alert
            :title="`测试完成，共测试 ${testResults.length} 个数据源`"
            :type="getOverallTestResult()"
            :closable="false"
            show-icon
          />
        </div>
        
        <div class="test-details">
          <el-row :gutter="16">
            <el-col
              v-for="result in testResults"
              :key="result.name"
              :lg="8"
              :md="12"
              :sm="24"
            >
              <div class="test-result-item">
                <div class="result-header">
                  <el-tag
                    :type="result.available ? 'success' : 'danger'"
                    size="large"
                  >
                    {{ result.name.toUpperCase() }}
                  </el-tag>
                  <span class="priority-info">优先级: {{ result.priority }}</span>
                </div>

                <div class="result-message">
                  <el-alert
                    :title="result.message"
                    :type="result.available ? 'success' : 'error'"
                    :closable="false"
                    show-icon
                  />
                </div>
              </div>
            </el-col>
          </el-row>
        </div>
      </div>
      
      <template #footer>
        <el-button @click="testDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="exportTestResults">
          <el-icon><Download /></el-icon>
          导出结果
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Connection,
  Operation,
  Download
} from '@element-plus/icons-vue'
import { testDataSources, type DataSourceTestResult } from '@/api/sync'
import { socialMediaApi } from '@/api/socialMedia'
import DataSourceStatus from '@/components/Sync/DataSourceStatus.vue'
import SyncControl from '@/components/Sync/SyncControl.vue'
import SyncRecommendations from '@/components/Sync/SyncRecommendations.vue'
import SyncHistory from '@/components/Sync/SyncHistory.vue'

type ContentSyncMode = 'native' | 'news_proxy'

// 响应式数据
const testing = ref(false)
const testDialogVisible = ref(false)
const testResults = ref<DataSourceTestResult[] | null>(null)
const dataSourceStatusRef = ref()
const contentSyncLoading = ref(false)
const contentSyncMode = ref<ContentSyncMode>('native')
const contentSyncForm = ref({
  symbol: ''
})

const normalizeAShareSymbol = (value: string) => {
  const symbol = String(value || '').trim().toUpperCase()
  return /^\d{6}$/.test(symbol) ? symbol : ''
}

const buildContentSyncSummaryHtml = (symbol: string, mode: ContentSyncMode, stats: any) => {
  const summary = stats?.summary || {}
  const sections = summary.sections || {}
  const details = summary.details || {}
  const sourceDetails = Array.isArray(stats?.source_details)
    ? stats.source_details.filter((item: string) => String(item || '').trim())
    : []
  const sourceLabel = sourceDetails.length > 0
    ? sourceDetails.join(' + ')
    : (stats?.source || (mode === 'native' ? 'a_share_native' : 'news_proxy'))
  const modeLabel = mode === 'native' ? '原生社媒' : '新闻回退'

  return [
    `<div style="line-height:1.7;">`,
    `<div><b>${symbol}</b> ${modeLabel}同步完成</div>`,
    `<div>来源：${sourceLabel}</div>`,
    `<div>写入：${stats?.saved_messages || 0} 条，失败：${stats?.failed_messages || 0} 条</div>`,
    `<div style="margin-top:8px;"><b>分类摘要</b></div>`,
    `<div>官方互动问答：${sections.official_ir || 0} 条</div>`,
    `<div>社区热度：${sections.community_heat || 0} 条</div>`,
    `<div>新闻回退：${sections.news_fallback || 0} 条</div>`,
    `<div style="margin-top:8px;"><b>明细</b></div>`,
    `<div>投资者提问：${details.investor_questions || 0} 条</div>`,
    `<div>公司回答：${details.company_answers || 0} 条</div>`,
    `<div>热度快照：${details.heat_snapshots || 0} 条</div>`,
    `<div>关键词快照：${details.keyword_snapshots || 0} 条</div>`,
    `<div>新闻代理消息：${details.news_proxy_messages || 0} 条</div>`,
    `</div>`
  ].join('')
}

const runContentSync = async (mode: ContentSyncMode) => {
  const symbol = normalizeAShareSymbol(contentSyncForm.value.symbol)
  if (!symbol) {
    ElMessage.warning('请输入 6 位 A 股代码')
    return
  }

  contentSyncLoading.value = true
  contentSyncMode.value = mode

  try {
    const response = mode === 'native'
      ? await socialMediaApi.syncAShareNative({
        symbol,
        days_back: 30,
        max_items: 40,
        allow_news_fallback: false
      })
      : await socialMediaApi.syncFromNews({
        symbol,
        hours_back: 72,
        max_items: 30
      })

    if (response.success === false) {
      throw new Error(response.message || '社媒同步失败')
    }

    const stats = response.data?.sync_stats || {}
    const savedMessages = Number(stats.saved_messages || 0)
    if (savedMessages <= 0) {
      ElMessage.warning(response.message || '未获取到可用内容数据')
      return
    }

    const modeLabel = mode === 'native' ? '原生社媒' : '新闻回退'
    ElMessage.success(`${symbol} ${modeLabel}同步完成，写入 ${savedMessages} 条`)
    await ElMessageBox.alert(
      buildContentSyncSummaryHtml(symbol, mode, stats),
      '内容同步摘要',
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '知道了'
      }
    )
  } catch (err: any) {
    console.error('A股内容同步失败:', err)
    ElMessage.error(err.message || 'A股内容同步失败')
  } finally {
    contentSyncLoading.value = false
  }
}

// 运行全面测试
const runFullTest = async () => {
  try {
    testing.value = true
    ElMessage.info('正在进行全面测试，请稍候...')

    // 不传递 sourceName，测试所有数据源
    const response = await testDataSources()
    if (response.success) {
      testResults.value = response.data.test_results
      testDialogVisible.value = true
      const availableCount = testResults.value.filter(r => r.available).length
      ElMessage.success(`全面测试完成: ${availableCount}/${testResults.value.length} 数据源可用`)
    } else {
      ElMessage.error(`测试失败: ${response.message}`)
    }
  } catch (err: any) {
    console.error('全面测试失败:', err)
    if (err.code === 'ECONNABORTED') {
      ElMessage.error('测试超时，请稍后重试。请确保网络连接稳定。')
    } else {
      ElMessage.error(`测试失败: ${err.message}`)
    }
  } finally {
    testing.value = false
  }
}

// 获取整体测试结果
const getOverallTestResult = (): 'success' | 'warning' | 'info' | 'error' => {
  if (!testResults.value) return 'info'

  const hasFailure = testResults.value.some(result => !result.available)

  return hasFailure ? 'warning' : 'success'
}

// 导出测试结果
const exportTestResults = () => {
  if (!testResults.value) return
  
  const data = {
    timestamp: new Date().toISOString(),
    results: testResults.value
  }
  
  const blob = new Blob([JSON.stringify(data, null, 2)], { 
    type: 'application/json' 
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `data-source-test-results-${new Date().toISOString().split('T')[0]}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  
  ElMessage.success('测试结果已导出')
}

// 处理同步完成事件
const handleSyncCompleted = (status: string) => {
  console.log('🎉 收到同步完成事件，状态:', status)
  // 这里可以触发历史记录刷新
  // 由于我们使用了组件引用，可以直接调用子组件的刷新方法
  // 或者发射一个全局事件让历史组件监听
}
</script>

<style scoped lang="scss">
.multi-source-sync {
  .page-header {
    margin-bottom: 24px;
    padding: 24px;
    background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-primary-light-8) 100%);
    border-radius: 12px;
    
    .header-content {
      display: flex;
      align-items: center;
      justify-content: space-between;
      
      .header-info {
        .page-title {
          display: flex;
          align-items: center;
          margin: 0 0 8px 0;
          font-size: 28px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          
          .title-icon {
            margin-right: 12px;
            color: var(--el-color-primary);
          }
        }
        
        .page-description {
          margin: 0;
          font-size: 16px;
          color: var(--el-text-color-regular);
          line-height: 1.5;
        }
      }
      
      .header-actions {
        flex-shrink: 0;
      }
    }
  }

  .page-content {
    .content-section {
      margin-bottom: 24px;
      
      &:last-child {
        margin-bottom: 0;
      }
    }

    .content-sync-card {
      .content-sync-body {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }

      .content-sync-description {
        margin: 0;
        color: var(--el-text-color-regular);
        line-height: 1.6;
      }

      .content-sync-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
      }

      .content-sync-alert {
        margin-top: 4px;
      }
    }
  }

  .test-results-dialog {
    .test-summary {
      margin-bottom: 24px;
    }
    
    .test-details {
      .test-result-item {
        margin-bottom: 24px;
        padding: 20px;
        border: 1px solid var(--el-border-color-light);
        border-radius: 8px;
        
        &:last-child {
          margin-bottom: 0;
        }
        
        .result-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
          
          .priority-info {
            font-size: 14px;
            color: var(--el-text-color-secondary);
          }
        }
        
        .result-tests {
          .test-item {
            padding: 12px;
            border: 1px solid var(--el-border-color-lighter);
            border-radius: 6px;
            height: 100%;
            
            .test-header {
              display: flex;
              align-items: center;
              gap: 6px;
              margin-bottom: 8px;
              
              .success-icon {
                color: var(--el-color-success);
              }
              
              .error-icon {
                color: var(--el-color-danger);
              }
              
              .test-name {
                font-weight: 500;
                font-size: 14px;
              }
            }
            
            .test-message {
              font-size: 12px;
              color: var(--el-text-color-regular);
              margin-bottom: 4px;
              line-height: 1.4;
            }
            
            .test-count,
            .test-date {
              font-size: 12px;
              color: var(--el-text-color-secondary);
            }
          }
        }
      }
    }
  }
}

@media (max-width: 768px) {
  .multi-source-sync {
    .page-header {
      .header-content {
        flex-direction: column;
        align-items: flex-start;
        gap: 16px;
        
        .header-actions {
          width: 100%;
          
          .el-button {
            width: 100%;
          }
        }
      }
    }

    .content-sync-card {
      .content-sync-actions {
        .el-button {
          width: 100%;
        }
      }
    }
    
    .test-results-dialog {
      .test-details {
        .test-result-item {
          .result-tests {
            .el-col {
              margin-bottom: 12px;
            }
          }
        }
      }
    }
  }
}
</style>
