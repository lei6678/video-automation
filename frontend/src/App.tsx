import { useState, useEffect, useRef } from 'react'

// API 基地址：开发时走 VITE_API_BASE_URL，生产构建为空 → 同源相对路径（局域网部署）
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''


// ============== 接口定义 ==============

interface ExtractResult {
  task_id: number
  title: string
  author: string
  likes: number
  comments: number
  shares: number
  duration: string
  cover_url: string
  video_url: string
  transcript: string
  is_mock: boolean
}

interface TaskDetail {
  id: number
  source_url: string
  status: string
  current_step: number
  raw_transcript: string | null
  cleaned_transcript: string | null
  rewritten_transcript: string | null
  douyin_meta: Record<string, unknown>
  book_title: string | null
  book_author: string | null
  video_title: string | null
  content_mode: string | null
  visual_context: string | null
  image_summary?: { total: number; success: number; failed: number; generating: boolean; complete: boolean } | null
  error_msg: string | null
  created_at: string
}

interface CleanResult { cleaned: string }
interface RewriteResult { rewritten: string; video_title?: string }
interface BookInfoResult {
  book_title: string
  book_author: string
  confidence: number
  evidence: string
}

// ---- TTS 相关 ----
type SegmentStatus = 'pending' | 'success' | 'failed'

interface SegmentInfo {
  index: number
  text: string
  audio_url: string
  audio_exists: boolean
  status: SegmentStatus
  error_msg?: string | null
}

// ---- 音色选项（v5：极致精简 3 黄金音色）----
// vc_shuangsisi → 火山引擎 seed-tts 标准带货音色
// vc_clone_female → SiliconFlow 历史克隆女声
// vc_clone_wanglq → 火山引擎声音复刻 王立群
const VOICE_OPTIONS = [
  { id: "vc_shuangsisi",    label: "爽快思思 —— 通用带货首选",            preview: "/audio/vc_shuangsisi_sample.mp3" },
  { id: "vc_clone_female",  label: "我的克隆音色 —— 女声1",               preview: "/audio/vc_clone_female_sample.mp3" },
  { id: "vc_clone_wanglq",  label: "我的克隆音色 —— 王立群",              preview: "/audio/vc_clone_wanglq_sample.mp3" },
]

const RATE_OPTIONS = [
  { label: "1.0x", value: "+0%" },
  { label: "1.1x", value: "+10%" },
  { label: "1.2x", value: "+20%" },
  { label: "0.9x", value: "-10%" },
]

// ============== 主应用 ==============

function App() {
  // URL 持久化：从 ?task=51 读取 taskId，刷新不丢失
  const getTaskIdFromURL = () => {
    const p = new URLSearchParams(window.location.search)
    const id = p.get('task')
    if (id) { sessionStorage.setItem('last_task_id', id); return parseInt(id) }
    // 兜底：从 sessionStorage 恢复
    const cached = sessionStorage.getItem('last_task_id')
    return cached ? parseInt(cached) : null
  }
  const [taskId, setTaskIdRaw] = useState<number | null>(getTaskIdFromURL)

  const setTaskId = (id: number | null) => {
    setTaskIdRaw(id)
    if (id) {
      sessionStorage.setItem('last_task_id', String(id))
      const url = new URL(window.location.href)
      url.searchParams.set('task', String(id))
      window.history.replaceState({}, '', url)
    }
  }

  // Step 1: 逐字稿
  const [originalText, setOriginalText] = useState('')
  const [cleanedText, setCleanedText] = useState('')

  // Step 2: 改写
  const [rewrittenText, setRewrittenText] = useState('')

  // Step 3: 书籍信息
  const [bookTitle, setBookTitle] = useState('')
  const [bookAuthor, setBookAuthor] = useState('')
  const [contentMode, setContentMode] = useState<'book' | 'general'>('general')  // 图书 / 百货赛道
  const [videoTitle, setVideoTitle] = useState('')  // AI 生成的爆款标题
  const [cardSlogan, setCardSlogan] = useState('- 品读传奇人生 -')
  const [cardSubtitleLine, setCardSubtitleLine] = useState('图片由AI生成与网络下载\n科普视频 无不良引导')

  // Step01 双模输入
  const [inputMode, setInputMode] = useState<'standard' | 'import'>('import')  // 标准模式 | 直接导入
  const [manualText, setManualText] = useState('')
  const [manualTitle, setManualTitle] = useState('')
  // 导入模式专用状态
  const [importRewrittenText, setImportRewrittenText] = useState('')
  const [importVideoTitle, setImportVideoTitle] = useState('')
  const [importContentMode, setImportContentMode] = useState<'book' | 'general'>('general')
  const [selectedVoice, setSelectedVoice] = useState("vc_clone_wanglq")
  const [selectedRate, setSelectedRate] = useState("+10%")
  const [segments, setSegments] = useState<SegmentInfo[]>([])
  const [finalAudioUrl, setFinalAudioUrl] = useState('')
  const [editingSegmentIndex, setEditingSegmentIndex] = useState<number | null>(null)
  const [editingText, setEditingText] = useState('')
  const [regeneratingIndex, setRegeneratingIndex] = useState<number | null>(null)
  const [previewingIndex, setPreviewingIndex] = useState<number | null>(null)
  const [isMerging, setIsMerging] = useState(false)
  // v5: 音色试听
  const previewAudioRef = useRef<HTMLAudioElement | null>(null)
  const [isPreviewPlaying, setIsPreviewPlaying] = useState(false)

  // ---- Step 04: 配图 + Step 05: 视频合成 ----
  const [isImageLoading, setIsImageLoading] = useState(false)
  const [images, setImages] = useState<any[]>([])
  const [imageMessage, setImageMessage] = useState('')
  const [selectedImageStyle, setSelectedImageStyle] = useState('default')
  const [selectedAspectRatio, setSelectedAspectRatio] = useState('8:9')  // v4: 16:9 横图 | 9:16 竖图 | 8:9 对标卡片
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)  // 轮询定时器

  const [selectedImageIndex, setSelectedImageIndex] = useState<number | null>(null)  // 当前大图预览的段号
  const [isRegeneratingImage, setIsRegeneratingImage] = useState<number | null>(null)  // 正在单段重跑的段号
  const [imageSummary, setImageSummary] = useState<{total: number; success: number; failed: number; generating: boolean; complete: boolean} | null>(null)  // v9: 后端权威配图进度
  const [, setImageTotalExpected] = useState(0)  // 预期总张数（仅 setter）
  const [forceRegen, setForceRegen] = useState(false)  // 强制重跑：忽略已有图片+视觉档案缓存
  const [genderOverride, setGenderOverride] = useState("auto")  // 性别覆写：auto/male/female
  const [isVideoLoading, setIsVideoLoading] = useState(false)
  const [videoUrl, setVideoUrl] = useState('')
  const [videoMessage, setVideoMessage] = useState('')
  const [videoDuration, setVideoDuration] = useState(0)
  const [videoSizeMb, setVideoSizeMb] = useState(0)
  const [draftDownloadUrl, setDraftDownloadUrl] = useState('')
  const [srtDownloadUrl, setSrtDownloadUrl] = useState('')
  const [assDownloadUrl, setAssDownloadUrl] = useState('')
  const [jianyingPublished, setJianyingPublished] = useState(false)
  const [jianyingDraftName, setJianyingDraftName] = useState('')
  const [selectedVideoStyle, setSelectedVideoStyle] = useState('card_bench')
  const [videoUrlCard, setVideoUrlCard] = useState('')
  const [archivePath, setArchivePath] = useState('')  // v9: 成品库归档路径


  // 全局状态
  const [isLoading, setIsLoading] = useState(false)
  const [isRewriteLoading, setIsRewriteLoading] = useState(false)
  const [isBookInfoLoading, setIsBookInfoLoading] = useState(false)
  const [isAudioLoading, setIsAudioLoading] = useState(false)
  const [backendStatus, setBackendStatus] = useState<'checking' | 'healthy' | 'offline'>('checking')
  const [videoMeta, setVideoMeta] = useState<ExtractResult | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/health`)
      .then((res) => res.json())
      .then((data) => setBackendStatus(data.status))
      .catch(() => setBackendStatus('offline'))
  }, [])

  // ============== API 调用 ==============

  const handleManualSubmit = async () => {
    if (!manualText.trim()) return
    setIsLoading(true)
    setRewrittenText('')
    setSegments([])
    setFinalAudioUrl('')
    setVideoMeta(null)

    // Step A: 创建任务（跳过爬虫/ASR）
    let taskId = null
    try {
      const resp = await fetch(`${API_BASE}/api/tasks/from-text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_text: manualText, title: manualTitle || '手动录入' }),
      })
      const data = await resp.json()
      if (!data.task_id) throw new Error('任务创建失败')
      taskId = data.task_id
      setTaskId(taskId)
      setOriginalText(manualText)
    } catch (e) {
      console.error('录入失败:', e)
      setIsLoading(false)
      return;
    }

    // Step B: 自动触发清洗
    setIsLoading(false)   // clean-text 接口会自己重置
    setIsLoading(true)
    try {
      const cleanResp = await fetch(`${API_BASE}/api/clean-text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, raw_text: manualText }),
      })
      const cleanData = await cleanResp.json()
      setCleanedText(cleanData.cleaned)
    } catch (e) {
      console.error('清洗失败:', e)
    }

    // Step C: 自动触发深度改写
    try {
      const rewriteResp = await fetch(`${API_BASE}/api/rewrite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, mode: 'rewrite' }),
      })
      const rewriteData = await rewriteResp.json()
      setRewrittenText(rewriteData.rewritten)
      // v5: 自动改写也需要捕获爆款标题，填入画面顶部文案
      if (rewriteData.video_title) {
        setVideoTitle(rewriteData.video_title)
      }
    } catch (e) {
      console.error('改写失败:', e)
    } finally {
      setIsLoading(false)
    }
  }

  const handleImportRewritten = async () => {
    if (!importRewrittenText.trim()) return
    setIsLoading(true)
    setRewrittenText('')
    setSegments([])
    setFinalAudioUrl('')
    setVideoMeta(null)

    try {
      const resp = await fetch(`${API_BASE}/api/tasks/import-rewritten`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rewritten_text: importRewrittenText,
          video_title: importVideoTitle,
          raw_text: manualText,
          content_mode: importContentMode,
        }),
      })
      const data = await resp.json()
      if (!data.task_id) throw new Error('导入失败')
      setTaskId(data.task_id)
      setOriginalText(manualText || importRewrittenText)
      setCleanedText(importRewrittenText)
      setRewrittenText(data.rewritten)
      setVideoTitle(data.video_title)
      setContentMode(importContentMode)
    } catch (e) {
      console.error('导入改写失败:', e)
    } finally {
      setIsLoading(false)
    }
  }

  const handleClean = async () => {
    if (!originalText.trim() || !taskId) return
    setIsLoading(true)
    try {
      const response = await fetch(`${API_BASE}/api/clean-text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, raw_text: originalText }),
      })
      const data: CleanResult = await response.json()
      setCleanedText(data.cleaned)
    } catch (error) {
      console.error('清洗失败:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleRewrite = async () => {
    if (!cleanedText.trim() || !taskId) return
    setIsRewriteLoading(true)
    try {
      const response = await fetch(`${API_BASE}/api/rewrite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, mode: 'rewrite' }),
      })
      const data: RewriteResult = await response.json()
      setRewrittenText(data.rewritten)
      // v5: 自动灌装爆款标题
      if (data.video_title) {
        setVideoTitle(data.video_title)
      }
    } catch (error) {
      console.error('改写失败:', error)
    } finally {
      setIsRewriteLoading(false)
    }
  }

  const handleBookInfo = async () => {
    if (!taskId) return
    setIsBookInfoLoading(true)
    try {
      const response = await fetch(`${API_BASE}/api/book-info`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId }),
      })
      const data: BookInfoResult = await response.json()
      setBookTitle(data.book_title)
      setBookAuthor(data.book_author)
      if (data.confidence < 0.6) {
        alert(`⚠️ 识别置信度较低（${(data.confidence * 100).toFixed(0)}%），请人工核对书籍信息。\n依据：${data.evidence}`)
      }
    } catch (error) {
      console.error('书籍信息识别失败:', error)
    } finally {
      setIsBookInfoLoading(false)
    }
  }

  // ============== TTS 核心操作（v5 极简版）==============

  const handleGenerateAudio = async () => {
    if (!taskId) return
    setIsAudioLoading(true)
    setFinalAudioUrl('')

    // v5: 统一走标准模式，clone 音色由后端路由
    try {
      const response = await fetch(`${API_BASE}/api/generate-audio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: taskId,
          voice: selectedVoice,
          rate: selectedRate,
        }),
      })
      const data = await response.json()
      if (data.segments) {
        setSegments(data.segments.map((s: SegmentInfo) => ({
          ...s,
          audio_url: s.audio_url ? `${API_BASE}${s.audio_url}` : s.audio_url,
        })))
      }
      if (data.audio_url) {
        setFinalAudioUrl(`${API_BASE}${data.audio_url}`)
      }
      if (data.message) {
        console.log(`[TTS] ${data.message}`)
      }
    } catch (error) {
      console.error('TTS 生成失败:', error)
    } finally {
      setIsAudioLoading(false)
    }
  }

  const handleRegenerateSegment = async (index: number, text: string) => {
    if (!taskId) return
    setRegeneratingIndex(index)
    try {
      const response = await fetch(`${API_BASE}/api/tts/regenerate-segment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: taskId,
          segment_index: index,
          text,
          voice: selectedVoice,
          rate: selectedRate,
        }),
      })
      const data = await response.json()
      // 用后端返回的完整片段列表更新状态
      if (data.segments) {
        setSegments(data.segments.map((s: SegmentInfo) => ({
          ...s,
          audio_url: s.audio_url ? `${API_BASE}${s.audio_url}` : s.audio_url,
        })))
      }
      if (data.final_audio_url) {
        setFinalAudioUrl(`${API_BASE}${data.final_audio_url}`)
      }
    } catch (error) {
      console.error('片段重跑失败:', error)
    } finally {
      setRegeneratingIndex(null)
      setEditingSegmentIndex(null)
    }
  }

  const handleMerge = async () => {
    if (!taskId) return
    setIsMerging(true)
    try {
      await fetch(`${API_BASE}/api/tts/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId }),
      })
      // 直接更新 final audio URL（加时间戳防缓存）
      setFinalAudioUrl(`${API_BASE}/audio/${taskId}/final_tts.mp3?t=${Date.now()}`)
    } catch (error) {
      console.error('拼装失败:', error)
    } finally {
      setIsMerging(false)
    }
  }

  // v5: 音色试听
  const handlePreviewVoice = () => {
    const voice = VOICE_OPTIONS.find(v => v.id === selectedVoice)
    if (!voice?.preview) return
    if (previewAudioRef.current) {
      previewAudioRef.current.pause()
      previewAudioRef.current = null
    }
    const audio = new Audio(voice.preview)
    audio.onplay = () => setIsPreviewPlaying(true)
    audio.onended = () => setIsPreviewPlaying(false)
    audio.onpause = () => setIsPreviewPlaying(false)
    previewAudioRef.current = audio
    audio.play()
  }

  // ============== Step 04: 配图生成 ==============

  const handleGenerateImages = async () => {
    if (!taskId) return
    setIsImageLoading(true)
    setImageMessage('')
    setImageSummary(null)  // v9: 清除旧进度，等待后端返回新摘要
    // 清除之前的轮询
    if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null }

    // ★ v4 轮询模式：POST 发完就走，不等待，用定时器每秒拉取最新图片
    fetch(`${API_BASE}/api/images/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId, style: selectedImageStyle, aspect_ratio: selectedAspectRatio, force: forceRegen, gender: genderOverride }),
    }).then(async (resp) => {
      const data = await resp.json()
      setImageTotalExpected(data.total_segments || 0)
      // v9: 如果后端返回错误（如"正在生成中"），显示给操作者
      if (data.message && data.total_segments === 0) {
        setImageMessage(data.message)
        setIsImageLoading(false)
        if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null }
      }
    }).catch((e) => {
      console.error('配图生成请求失败:', e)
      setImageMessage('配图生成请求失败，请检查后端日志')
      setIsImageLoading(false)
      if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null }
    })

    // 立即开始轮询，每 2 秒刷新一次图片列表
    pollTimerRef.current = setInterval(async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/images/${taskId}?_=${Date.now()}`)
        if (!resp.ok) return
        const data = await resp.json()
        setImages(data.images || [])
        // v9: 使用后端权威的 image_summary（不再前端自己数）
        if (data.image_summary) {
          setImageSummary(data.image_summary)
          const s = data.image_summary
          setImageMessage(`已生成 ${s.success} / ${s.total} 张配图`)
          // 终止条件：后端标记 complete=true（权威判断，无论成功还是失败）
          if (s.complete) {
            if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null }
            setIsImageLoading(false)
            setImageMessage(
              s.failed > 0
                ? `配图生成完成：${s.success} 张成功，${s.failed} 张失败`
                : `配图生成完成：${s.success} 张全部成功`
            )
          }
        } else {
          // 兜底：后端未返回 image_summary 时用旧逻辑
          const successCount = (data.images || []).filter((i: any) => i.status === 'success').length
          const total = data.total || 0
          setImageMessage(`已生成 ${successCount} / ${total} 张配图`)
        }
      } catch (e) {
        // 网络抖动不中断轮询
      }
    }, 2000)
  }

  const refreshImages = async () => {
    if (!taskId) return
    try {
      const resp = await fetch(`${API_BASE}/api/images/${taskId}?_=${Date.now()}`)
      if (resp.ok) {
        const data = await resp.json()
        setImages(data.images || [])
        if (data.image_summary) {
          setImageSummary(data.image_summary)
        }
        setSelectedImageIndex(null)
      }
    } catch (e) {
      console.error('获取配图失败:', e)
    }
  }

  const handleRegenerateSegmentImage = async (segmentIndex: number) => {
    if (!taskId) return
    setIsRegeneratingImage(segmentIndex)
    setImageMessage('')
    try {
      const resp = await fetch(`${API_BASE}/api/images/regenerate-segment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, segment_index: segmentIndex, style: selectedImageStyle, aspect_ratio: selectedAspectRatio }),
      })
      const data = await resp.json()
      await refreshImages()
      setImageMessage(data.message || (data.status === 'success' ? `段 ${segmentIndex + 1} 已重新生成` : '重跑失败'))
    } catch (e) {
      console.error('单段配图重跑失败:', e)
      setImageMessage('单段配图重跑失败，请检查后端日志')
    } finally {
      setIsRegeneratingImage(null)
    }
  }

  // ============== Step 05: 视频合成 ==============

  // v7: video styles removed - only card_16x9 and card_3x4 available

  const checkVideoStatus = async () => {
    if (!taskId) return
    try {
      const resp = await fetch(`${API_BASE}/api/video/status/${taskId}`)
      if (resp.ok) {
        const data = await resp.json()
        if (data.exists) {
          const cacheBust = Date.now()
          setVideoUrl(`${API_BASE}${data.video_url}?t=${cacheBust}`)
          setVideoDuration(data.duration_sec)
          setVideoSizeMb(data.size_mb)
          // v4: 同步下载链接
          if (data.jianying_draft_url) {
            setDraftDownloadUrl(`${API_BASE}${data.jianying_draft_url}`)
          }
          if (data.srt_url) {
            setSrtDownloadUrl(`${API_BASE}${data.srt_url}`)
          }
          if (data.ass_url) {
            setAssDownloadUrl(`${API_BASE}${data.ass_url}`)
          }
        }
      }
    } catch (e) {
      console.error('检查视频状态失败:', e)
    }
  }

  const handleComposeVideo = async () => {
    if (!taskId) return
    setIsVideoLoading(true)
    setVideoMessage('')
    try {
      // v7: 根据风格动态选择合成模式（v8: card_bench → bench 对标卡片）
      const isBench = selectedVideoStyle === 'card_bench'
      const isCard = !isBench && selectedVideoStyle.startsWith('card_')
      const modes: string[] = isBench ? ['bench'] : isCard ? ['card'] : ['cinematic']
      const resp = await fetch(`${API_BASE}/api/video/compose`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: taskId,
          style: selectedVideoStyle,
          aspect_ratio: selectedAspectRatio,
          watermark_text: bookTitle ? `《${bookTitle}》${bookAuthor}` : (videoTitle || ''),
          bottom_disclaimer: '',
          modes,
          content_mode: contentMode,
          video_title: videoTitle,
          slogan: cardSlogan,
          subtitle_line: cardSubtitleLine,
          skip_ffmpeg: true,  // v11: 跳过本地合成，直接出剪映草稿（GPU导出更快）
        }),
      })
      const data = await resp.json()
      // v5: 缓存爆破时间戳 — 强制浏览器加载最新画面
      const cacheBust = Date.now()
      if (data.video_url) {
        setVideoUrl(`${API_BASE}${data.video_url}?t=${cacheBust}`)
        setVideoDuration(data.duration_sec)
        setVideoSizeMb(data.size_mb)
      }
      // v9: 成品库归档路径
      setArchivePath(data.archive_path || '')
      // v7: card 卡片成品
      if (data.video_url_card) {
        setVideoUrlCard(`${API_BASE}${data.video_url_card}?t=${cacheBust}`)
      }
      // v4: 捕获下载链接
      if (data.jianying_draft_url) {
        setDraftDownloadUrl(`${API_BASE}${data.jianying_draft_url}`)
      }
      if (data.srt_url) {
        setSrtDownloadUrl(`${API_BASE}${data.srt_url}`)
      }
      if (data.ass_url) {
        setAssDownloadUrl(`${API_BASE}${data.ass_url}`)
      }
      // 剪映自动发布状态
      if (data.jianying_published) {
        setJianyingPublished(true)
        setJianyingDraftName(data.jianying_draft_name || '')
      }
      setVideoMessage(data.message || '')
    } catch (e) {
      console.error('视频合成失败:', e)
      setVideoMessage('视频合成失败，请检查后端日志')
    } finally {
      setIsVideoLoading(false)
    }
  }

  // ============== 页面恢复：taskId 变化时自动从后端拉回全部数据 ==============

  useEffect(() => {
    if (!taskId) return
    console.log(`[restore] taskId=${taskId}, loading state from backend...`)

    // 1. 拉任务详情（文案/改写稿/标题/赛道 + v9: 配图进度摘要）
    fetch(`${API_BASE}/api/tasks/${taskId}`)
      .then(r => r.json())
      .then((t: TaskDetail) => {
        if (t.raw_transcript) setOriginalText(t.raw_transcript)
        if (t.rewritten_transcript) setRewrittenText(t.rewritten_transcript)
        if (t.book_title) setBookTitle(t.book_title)
        if (t.book_author) setBookAuthor(t.book_author)
        if (t.video_title) setVideoTitle(t.video_title)
        if (t.content_mode) setContentMode(t.content_mode as 'book' | 'general')
        // v9: 恢复配图进度（刷新页面后状态不丢）
        if (t.image_summary) {
          setImageSummary(t.image_summary)
          // 如果正在生成中，自动恢复轮询
          if (t.image_summary.generating) {
            setIsImageLoading(true)
            setImageTotalExpected(t.image_summary.total)
            if (pollTimerRef.current) clearInterval(pollTimerRef.current)
            pollTimerRef.current = setInterval(async () => {
              try {
                const resp = await fetch(`${API_BASE}/api/images/${taskId}?_=${Date.now()}`)
                if (!resp.ok) return
                const data = await resp.json()
                setImages(data.images || [])
                if (data.image_summary) {
                  setImageSummary(data.image_summary)
                  if (data.image_summary.complete) {
                    if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null }
                    setIsImageLoading(false)
                  }
                }
              } catch (_) {}
            }, 2000)
          }
        }
      })
      .catch(e => console.error('[restore] task fetch failed:', e))

    // 2. 拉清洗稿
    fetch(`${API_BASE}/audio/${taskId}/cleaned.txt?_=${Date.now()}`)
      .then(r => { if (r.ok) return r.text(); throw new Error('not found') })
      .then(t => setCleanedText(t))
      .catch(() => {})

    // 3. 拉配音片段
    fetch(`${API_BASE}/api/tts/segments/${taskId}`)
      .then(r => r.json())
      .then(d => {
        if (d.segments?.length > 0) {
          setSegments(d.segments.map((s: SegmentInfo) => ({
            ...s,
            audio_url: s.audio_url ? `${API_BASE}${s.audio_url}` : s.audio_url,
          })))
        }
        if (d.final_audio_url) {
          setFinalAudioUrl(`${API_BASE}${d.final_audio_url}?t=${Date.now()}`)
        }
      })
      .catch(() => {})

    // 4. 拉配图 + 视频
    refreshImages()
    checkVideoStatus()
  }, [taskId])

  // 键盘导航：← → 切换配图段
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return
      if (images.length === 0) return
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault()
        const sorted = [...images].sort((a, b) => (a.segment_index ?? 0) - (b.segment_index ?? 0))
        if (sorted.length === 0) return
        let currentIdx = selectedImageIndex ?? sorted[0]?.segment_index ?? 0
        if (e.key === 'ArrowLeft') currentIdx = Math.max(sorted[0]?.segment_index ?? 0, currentIdx - 1)
        else currentIdx = Math.min(sorted[sorted.length - 1]?.segment_index ?? 0, currentIdx + 1)
        setSelectedImageIndex(currentIdx)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [images, selectedImageIndex])

  return (
    <div className="min-h-screen bg-gray-50">

      {/* 顶部标题栏 */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-6 py-5">
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            🎬 视频自动化制作工作流
          </h1>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-6">

        {/* ===== 工作流进度条 ===== */}
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
          <div className="flex items-center justify-between">
            {[
              { step: 1, label: '文案导入', done: !!originalText },
              { step: 2, label: '文本清洗', done: !!rewrittenText },
              { step: 3, label: 'TTS 配音', done: segments.length > 0 && segments.some(s => s.status === 'success') },
              { step: 4, label: '配图生成', done: imageSummary?.complete === true },
              { step: 5, label: '视频合成', done: !!videoUrl },
            ].map((s, i, arr) => (
              <div key={s.step} className="flex items-center gap-2 flex-1 last:flex-none">
                <div className={`flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium transition-colors ${
                  s.done ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'
                }`}>
                  <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${
                    s.done ? 'bg-green-500 text-white' : 'bg-gray-300 text-gray-500'
                  }`}>
                    {s.done ? '✓' : s.step}
                  </span>
                  <span className="whitespace-nowrap">{s.label}</span>
                </div>
                {i < arr.length - 1 && (
                  <div className={`flex-1 h-0.5 rounded-full ${s.done ? 'bg-green-300' : 'bg-gray-200'}`} />
                )}
              </div>
            ))}
          </div>
        </section>

        {/* ===== 文案输入工作台 ===== */}
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-gray-700">📥 文案输入</h2>
            {/* 模式切换 */}
            <div className="flex bg-gray-100 rounded-lg p-0.5">
              <button
                onClick={() => setInputMode('standard')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${inputMode === 'standard' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
              >
                标准模式
              </button>
              <button
                onClick={() => setInputMode('import')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${inputMode === 'import' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
              >
                直接导入
              </button>
            </div>
          </div>

          {/* ===== 标准模式：粘贴原文 → AI 改写 ===== */}
          {inputMode === 'standard' && (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <input
                  type="text"
                  value={manualTitle}
                  onChange={(e) => setManualTitle(e.target.value)}
                  placeholder="视频标题（选填）"
                  className="flex-1 px-4 py-2 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <textarea
                value={manualText}
                onChange={(e) => setManualText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && e.ctrlKey) handleManualSubmit() }}
                placeholder="请在此粘贴原始文案内容..."
                rows={10}
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none leading-relaxed"
                style={{ fontSize: '14px', lineHeight: '1.8' }}
              />
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Ctrl+Enter 快捷提交 · {manualText.length} 字</span>
                <button
                  onClick={handleManualSubmit}
                  disabled={!manualText.trim() || isLoading}
                  className="flex items-center gap-2 px-6 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed transition-colors shadow-sm"
                >
                  {isLoading ? <span>⏳</span> : <span>📥</span>}
                  <span>{isLoading ? '处理中...' : '确认文案，进入 AI 改写'}</span>
                </button>
              </div>
            </div>
          )}

          {/* ===== 导入模式：直接粘贴改好的文案 ===== */}
          {inputMode === 'import' && (
            <div className="space-y-3">
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-700">
                💡 将网页版 DeepSeek 改好的文案直接粘贴到下方，导入后即可跳过 AI 改写，直接进入配音/生图/合成。
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">爆款标题</label>
                  <input
                    type="text"
                    value={importVideoTitle}
                    onChange={(e) => setImportVideoTitle(e.target.value)}
                    placeholder="填写爆款标题..."
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">内容赛道</label>
                  <select
                    value={importContentMode}
                    onChange={(e) => setImportContentMode(e.target.value as 'book' | 'general')}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 focus:outline-none focus:ring-2 focus:ring-amber-500 text-sm"
                  >
                    <option value="book">📚 图书赛道</option>
                    <option value="general">🛒 百货与流量赛道</option>
                  </select>
                </div>
              </div>
              <textarea
                value={importRewrittenText}
                onChange={(e) => setImportRewrittenText(e.target.value)}
                placeholder="粘贴改写好的完整文案正文..."
                rows={12}
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 resize-none leading-relaxed"
                style={{ fontSize: '14px', lineHeight: '1.8' }}
              />
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">已改好的文案 · {importRewrittenText.length} 字</span>
                <button
                  onClick={handleImportRewritten}
                  disabled={!importRewrittenText.trim() || isLoading}
                  className="flex items-center gap-2 px-6 py-3 bg-amber-600 text-white font-medium rounded-xl hover:bg-amber-700 disabled:bg-amber-300 disabled:cursor-not-allowed transition-colors shadow-sm"
                >
                  {isLoading ? <span>⏳</span> : <span>📥</span>}
                  <span>{isLoading ? '导入中...' : '一键导入，进入后续工序'}</span>
                </button>
              </div>
            </div>
          )}
        </section>
        {/* ===== 视频数据看板 ===== */}
        {videoMeta && (
          <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold text-gray-700">📊 视频数据看板</h2>
              {videoMeta.is_mock && (
                <span className="inline-flex items-center gap-1 px-3 py-1 bg-amber-50 text-amber-600 text-xs font-medium rounded-full">
                  <span>⚠️</span> Mock 数据
                </span>
              )}
              {taskId && (
                <span className="inline-flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-600 text-xs font-medium rounded-full">
                  Task #{taskId}
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              {[
                { label: "👤 作者", value: videoMeta.author, cls: "from-purple-50 to-purple-100 text-purple-800" },
                { label: "⏱️ 时长", value: videoMeta.duration, cls: "from-green-50 to-green-100 text-green-800" },
                { label: "❤️ 点赞", value: videoMeta.likes.toLocaleString(), cls: "from-orange-50 to-orange-100 text-orange-800" },
                { label: "💬 评论", value: videoMeta.comments.toLocaleString(), cls: "from-cyan-50 to-cyan-100 text-cyan-800" },
                { label: "🔗 分享", value: videoMeta.shares.toLocaleString(), cls: "from-pink-50 to-pink-100 text-pink-800" },
              ].map(({ label, value, cls }) => (
                <div key={label} className={`bg-gradient-to-br rounded-xl p-4 ${cls}`}>
                  <p className="text-xs font-medium mb-1 opacity-70">{label}</p>
                  <p className="text-sm font-bold truncate">{value}</p>
                </div>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-gradient-to-br from-indigo-50 to-indigo-100 rounded-xl p-4">
                <p className="text-xs text-indigo-600 font-medium mb-1">📌 标题</p>
                <p className="text-sm font-bold text-indigo-800 line-clamp-2">{videoMeta.title}</p>
              </div>
              {videoMeta.cover_url && (
                <div className="bg-gradient-to-br from-gray-50 to-gray-100 rounded-xl p-4">
                  <p className="text-xs text-gray-600 font-medium mb-1">🖼️ 封面</p>
                  <img src={videoMeta.cover_url} alt="封面" className="h-16 w-auto object-cover rounded-lg" />
                </div>
              )}
            </div>
          </section>
        )}

        {/* ===== Step 01: 逐字稿修复 ===== */}
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-semibold text-gray-700">逐字稿修复</h2>
            {cleanedText && (
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-green-50 text-green-600 text-sm font-medium rounded-full">
                <span>✓</span> 已清洗
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-6">
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-600">原始逐字稿（ASR 修复前）</h3>
              <textarea
                value={originalText}
                onChange={(e) => setOriginalText(e.target.value)}
                placeholder="请粘贴或导入原始逐字稿内容..."
                className="w-full h-72 px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none leading-relaxed"
                style={{ fontSize: '14px', lineHeight: '1.8' }}
              />
              <p className="text-xs text-gray-400 pl-1">粗糙 ASR 文本提示</p>
            </div>
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-600">修复后正文（清洗完成）</h3>
              <textarea
                value={cleanedText}
                readOnly
                placeholder="清洗后的文本将显示在这里..."
                className="w-full h-72 px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 resize-none leading-relaxed"
                style={{ fontSize: '14px', lineHeight: '1.8' }}
              />
            </div>
          </div>
          <div className="flex justify-center mt-4">
            <button
              onClick={handleClean}
              disabled={!originalText.trim() || !taskId || isLoading}
              className="flex items-center gap-2 px-8 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed transition-colors shadow-md"
            >
              {isLoading ? <><span>⏳</span><span>清洗中...</span></> : <><span>✨</span><span>开始清洗</span></>}
            </button>
          </div>
        </section>

        {/* ===== Step 02: 候选稿生成 ===== */}
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-semibold text-gray-700">Step 02: 候选稿生成（过查重）</h2>
            {rewrittenText && (
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-green-50 text-green-600 text-sm font-medium rounded-full">
                <span>✓</span> 已生成
              </span>
            )}
          </div>
          <div className="grid grid-cols-3 gap-6">
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-600">清洗后正文（参考）</h3>
              <textarea
                value={cleanedText}
                readOnly
                placeholder={cleanedText ? "" : "请先完成 Step 01 清洗"}
                className={`w-full h-64 px-4 py-3 border rounded-xl text-gray-700 resize-none leading-relaxed ${cleanedText ? 'bg-gray-50 border-gray-200' : 'bg-gray-100 border-dashed border-gray-300'}`}
                style={{ fontSize: '14px', lineHeight: '1.8' }}
              />
              {!cleanedText && <p className="text-xs text-gray-400 pl-1">需先完成逐字稿清洗</p>}
            </div>
            <div className="flex flex-col justify-center items-center gap-4">
              <button
                onClick={() => handleRewrite()}
                disabled={!cleanedText.trim() || !taskId || isRewriteLoading}
                className="flex items-center gap-2 w-full px-4 py-3 bg-purple-600 text-white font-medium rounded-xl hover:bg-purple-700 disabled:bg-purple-300 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {isRewriteLoading ? <span>⏳</span> : <span>✍️</span>}
                <span>{isRewriteLoading ? '改写中...' : '深度改写'}</span>
              </button>
              <p className="text-xs text-gray-500 text-center">AI 深度洗稿：口语化重写、去 AI 味、破除连续七字查重</p>
            </div>
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-600">候选稿（改写结果）</h3>
              <textarea
                value={rewrittenText}
                readOnly
                placeholder="改写后的候选稿将显示在这里..."
                className="w-full h-64 px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 placeholder-gray-400 resize-none leading-relaxed"
                style={{ fontSize: '14px', lineHeight: '1.8' }}
              />
            </div>
          </div>
        </section>

        {/* ===== Step 03: 配音工作台 ===== */}
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">

          {/* 卡片标题栏 */}
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-semibold text-gray-700">🎙️ TTS 配音工作台</h2>
            {finalAudioUrl && (
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-green-50 text-green-600 text-sm font-medium rounded-full">
                <span>✓</span> 已生成 {segments.length} 段
              </span>
            )}
          </div>

          {/* ===== 熔断报错 Banner ===== */}
          {isAudioLoading && (
            <div className="mb-4 px-4 py-3 bg-blue-50 border border-blue-200 rounded-xl flex items-center gap-3">
              <span className="inline-block w-3 h-3 bg-blue-500 rounded-full animate-pulse" />
              <span className="text-sm text-blue-700">
                配音生成中，请勿关闭页面...
              </span>
              <span className="text-xs text-blue-500 ml-auto">若长时间无响应，请检查网络</span>
            </div>
          )}

          {/* ===== 全局控制栏 v5 ===== */}
          <div className="bg-gray-50 rounded-xl p-4 mb-5 flex flex-wrap items-center gap-6">

            {/* 音色选择 */}
            <div className="flex items-center gap-3">
              <label className="text-sm font-medium text-gray-600 whitespace-nowrap">🎵 音色：</label>
              <select
                value={selectedVoice}
                onChange={(e) => setSelectedVoice(e.target.value)}
                disabled={isAudioLoading}
                className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              >
                {VOICE_OPTIONS.map(v => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
              </select>
              {/* v5: 音色试听按钮 */}
              <button
                onClick={handlePreviewVoice}
                disabled={isAudioLoading}
                className={`flex items-center gap-1 px-3 py-2 text-sm font-medium rounded-lg border transition-colors disabled:opacity-50 ${
                  isPreviewPlaying
                    ? 'bg-green-500 text-white border-green-500'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-green-400 hover:text-green-700'
                }`}
                title="试听当前音色（5 秒小样）"
              >
                {isPreviewPlaying ? '⏸️ 播放中' : '🔊 试听'}
              </button>
            </div>

            {/* 语速调节 */}
            <div className="flex items-center gap-3">
              <label className="text-sm font-medium text-gray-600 whitespace-nowrap">⏱️ 语速：</label>
              <div className="flex gap-1">
                {RATE_OPTIONS.map(r => (
                  <button
                    key={r.value}
                    onClick={() => setSelectedRate(r.value)}
                    disabled={isAudioLoading}
                    className={`px-3 py-1.5 text-sm rounded-lg border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                      selectedRate === r.value
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-white text-gray-600 border-gray-200 hover:border-blue-400'
                    }`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 生成按钮 */}
            <button
              onClick={handleGenerateAudio}
              disabled={!taskId || isAudioLoading}
              className="flex items-center gap-2 px-5 py-2 bg-orange-500 text-white font-medium rounded-xl hover:bg-orange-600 disabled:bg-orange-300 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              {isAudioLoading ? <><span>⏳</span><span>生成中...</span></> : <><span>🔊</span><span>生成配音</span></>}
            </button>

            {/* 拼装按钮 */}
            {segments.length > 0 && !isAudioLoading && (
              <button
                onClick={handleMerge}
                disabled={isMerging}
                className="flex items-center gap-2 px-4 py-2 bg-gray-600 text-white font-medium rounded-xl hover:bg-gray-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {isMerging ? <><span>⏳</span><span>拼装中...</span></> : <><span>🎞️</span><span>重新拼装</span></>}
              </button>
            )}
          </div>

          {/* ===== 分段控制台 ===== */}
          {segments.length > 0 && (
            <div className="space-y-4">
              {segments.map((seg) => {
                const isSuccess = seg.status === 'success'
                const isFailed  = seg.status === 'failed'
                const isPending = seg.status === 'pending'
                const isRegen   = regeneratingIndex === seg.index
                return (
                  <div key={seg.index} className={`border rounded-xl overflow-hidden ${
                    isFailed  ? 'border-red-200 bg-red-50'
                    : isSuccess ? 'border-green-200 bg-white'
                    : 'border-gray-100 bg-white'
                  }`}>
                    <div className="px-4 py-2 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-semibold ${
                          isFailed ? 'text-red-600' : isSuccess ? 'text-green-600' : 'text-gray-500'
                        }`}>
                          片段 {seg.index + 1} / {segments.length}
                        </span>
                        {isPending && <span className="flex items-center gap-1 text-xs text-blue-500">
                          <span className="inline-block w-2 h-2 bg-blue-400 rounded-full animate-pulse" /> 生成中
                        </span>}
                        {isSuccess && <span className="text-xs text-green-600 font-medium">&#10003; 成功</span>}
                        {isFailed  && <span className="text-xs text-red-600 font-medium">&#10007; 失败</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        {isSuccess && (
                          <button
                            onClick={() => setPreviewingIndex(previewingIndex === seg.index ? null : seg.index)}
                            className={`flex items-center gap-1 px-3 py-1 text-xs rounded-lg border transition-colors ${
                              previewingIndex === seg.index
                                ? 'bg-blue-100 text-blue-700 border-blue-300'
                                : 'bg-white text-gray-600 border-gray-200 hover:border-blue-400'
                            }`}
                          >
                            &#127908; 试听
                          </button>
                        )}
                        {(isFailed || isPending) && (
                          <button
                            onClick={() => handleRegenerateSegment(seg.index, seg.text)}
                            disabled={isRegen || isAudioLoading}
                            className="flex items-center gap-1 px-3 py-1 text-xs bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:bg-red-300 transition-colors"
                          >
                            {isRegen ? '&#9203; 生成中...' : '&#128260; 重试'}
                          </button>
                        )}
                      </div>
                    </div>
                    {isSuccess && previewingIndex === seg.index && (
                      <div className="px-4 py-3 bg-blue-50 border-t border-blue-100">
                        <audio controls src={seg.audio_url.startsWith('http') ? seg.audio_url : `${API_BASE}${seg.audio_url}`} className="w-full" />
                      </div>
                    )}
                    {isFailed && seg.error_msg && (
                      <div className="px-4 py-2 bg-red-100 border-t border-red-200 text-xs text-red-600">
                        &#38169;&#35823;&#65306;{seg.error_msg}
                      </div>
                    )}
                    <div
                      className="px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors"
                      onClick={() => { setEditingSegmentIndex(seg.index); setEditingText(seg.text) }}
                    >
                      <p className="text-sm text-gray-700 whitespace-pre-wrap" style={{ fontSize: '13px', lineHeight: '1.8' }}>
                        {seg.text}
                      </p>
                    </div>
                    {editingSegmentIndex === seg.index && (
                      <div className="px-4 py-3 bg-amber-50 border-t border-amber-100 space-y-2">
                        <textarea
                          value={editingText}
                          onChange={(e) => setEditingText(e.target.value)}
                          rows={3}
                          className="w-full px-3 py-2 bg-white border border-amber-200 rounded-lg text-sm text-gray-700 resize-none focus:outline-none focus:ring-2 focus:ring-amber-400"
                          style={{ fontSize: '13px', lineHeight: '1.7' }}
                        />
                        <div className="flex gap-2 justify-end">
                          <button
                            onClick={() => setEditingSegmentIndex(null)}
                            className="px-4 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                          >
                            &#21462;&#28040;
                          </button>
                          <button
                            onClick={() => handleRegenerateSegment(seg.index, editingText)}
                            disabled={isRegen || isAudioLoading}
                            className="flex items-center gap-1 px-4 py-1.5 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600 disabled:bg-orange-300 transition-colors"
                          >
                            {isRegen ? '&#9203; 生成中...' : '&#128260; &#30830;&#35748;&#37325;&#36305;'}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
          {segments.length === 0 && !isAudioLoading && (
            <div className="text-center py-10 text-gray-400 text-sm">
              &#8593; &#19978;&#26041;&#36873;&#25321;&#38899;&#33394;&#21644;&#35821;&#36895;&#65292;&#28857;&#20987;&#12290;&#29983;&#25104;&#37197;&#38899;&#12290;&#24320;&#22987;
            </div>
          )}
          {isAudioLoading && segments.length === 0 && (
            <div className="text-center py-10 text-gray-400 text-sm">
              &#9203; &#21021;&#22987;&#21270;&#29255;&#27573;&#20013;...
            </div>
          )}


          {/* ===== 最终音频播放器 ===== */}
          {finalAudioUrl && (
            <div className="mt-5 pt-5 border-t border-gray-100">
              <div className="flex items-center gap-3 mb-3">
                <span className="text-sm font-semibold text-gray-600">🎧 完整配音</span>
                <span className="text-xs text-gray-400">（{segments.length} 个片段无损拼接）</span>
              </div>
              <audio controls src={finalAudioUrl} className="w-full" />
            </div>
          )}
        </section>

        {/* ===== Step 03: 画面顶部文案识别与填充 ===== */}
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-semibold text-gray-700">🎬 画面顶部文案识别与填充</h2>
          </div>

          {/* 赛道选择器 */}
          <div className="flex items-center gap-4 mb-5 bg-gray-50 rounded-xl p-3">
            <span className="text-sm font-medium text-gray-600">📌 赛道：</span>
            <div className="flex bg-white border border-gray-200 rounded-lg overflow-hidden">
              <button
                onClick={() => setContentMode('book')}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  contentMode === 'book' ? 'bg-indigo-600 text-white' : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                📚 图书赛道
              </button>
              <button
                onClick={() => setContentMode('general')}
                className={`px-4 py-2 text-sm font-medium transition-colors border-l border-gray-200 ${
                  contentMode === 'general' ? 'bg-orange-600 text-white' : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                🛒 百货与流量赛道
              </button>
            </div>
            {contentMode === 'general' && (
              <span className="text-xs text-orange-600 bg-orange-50 px-2 py-0.5 rounded-full font-medium">
                视频顶部渲染标题框
              </span>
            )}
          </div>

          {/* 图书赛道 */}
          {contentMode === 'book' && (
            <div className="grid grid-cols-2 gap-6">
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">书籍名称</label>
                  <input
                    type="text"
                    value={bookTitle}
                    onChange={(e) => setBookTitle(e.target.value)}
                    placeholder="AI 识别或手动输入"
                    className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">作者名称</label>
                  <input
                    type="text"
                    value={bookAuthor}
                    onChange={(e) => setBookAuthor(e.target.value)}
                    placeholder="AI 识别或手动输入"
                    className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <button
                  onClick={handleBookInfo}
                  disabled={!taskId || isBookInfoLoading}
                  className="flex items-center gap-2 px-5 py-2 bg-indigo-600 text-white font-medium rounded-xl hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed transition-colors shadow-sm"
                >
                  {isBookInfoLoading ? <span>⏳</span> : <span>🔍</span>}
                  <span>{isBookInfoLoading ? '识别中...' : 'AI 识别书籍信息'}</span>
                </button>
              </div>
              <div className="flex items-center justify-center text-gray-300 text-6xl">📖</div>
            </div>
          )}

          {/* 百货与流量赛道 */}
          {contentMode === 'general' && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  🎯 视频爆款标题（AI 改写后自动生成，也可手动输入）
                </label>
                <input
                  type="text"
                  value={videoTitle}
                  onChange={(e) => setVideoTitle(e.target.value)}
                  placeholder="如：10岁失去双臂的男孩，用脚弹上金色大厅"
                  className="w-full px-4 py-3 bg-orange-50 border-2 border-orange-200 rounded-xl text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-500 font-semibold text-lg"
                />
              </div>
              <p className="text-xs text-gray-400">
                💡 标题由 AI 在改写时同步生成（15-25 字），采用极限反差或数字具象化爆款公式。改写完成后自动填充，也可手动修改。
              </p>
            </div>
          )}
        </section>

        {/* ===== Step 04: 配图批量生成（v2 缩略图网格）===== */}
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-semibold text-gray-700">🖼️ Step 04: 配图批量生成（高密度按句分镜）</h2>
            <div className="flex items-center gap-3">
              {images.length > 0 && (
                <span className="inline-flex items-center gap-1 px-3 py-1 bg-green-50 text-green-600 text-sm font-medium rounded-full">
                  <span>✓</span> {images.filter((i: any) => i.status === 'success').length}/{images.length} 张
                </span>
              )}
            </div>
          </div>

          {/* 生成控制栏 v4：风格 + 画幅 + 导演指南 */}
          <div className="bg-gray-50 rounded-xl p-4 mb-5 space-y-3">
            {/* 第一行：风格下拉 + 画幅比例 */}
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium text-gray-600 whitespace-nowrap">🎨 风格：</label>
                <select
                  value={selectedImageStyle}
                  onChange={(e) => setSelectedImageStyle(e.target.value)}
                  disabled={isImageLoading}
                  className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                >
                  <option value="default">默认电影感</option>
                  <option value="warm_book">温暖治愈书单</option>
                  <option value="clean_health">明亮健康生活</option>
                  <option value="philosophy">哲学思辨风</option>
                </select>
              </div>

              {/* v4: 画幅尺寸 Radio Group */}
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium text-gray-600 whitespace-nowrap">📐 画幅：</label>
                <div className="flex bg-white border border-gray-200 rounded-lg overflow-hidden">
                  <button
                    onClick={() => setSelectedAspectRatio('16:9')}
                    disabled={isImageLoading}
                    className={`px-3 py-2 text-sm font-medium transition-colors ${
                      selectedAspectRatio === '16:9'
                        ? 'bg-blue-600 text-white'
                        : 'text-gray-600 hover:bg-gray-100'
                    } disabled:opacity-50`}
                  >
                    16:9 横图原画
                  </button>
                  <button
                    onClick={() => setSelectedAspectRatio('3:4')}
                    disabled={isImageLoading}
                    className={`px-3 py-2 text-sm font-medium transition-colors border-l border-gray-200 ${
                      selectedAspectRatio === '3:4'
                        ? 'bg-blue-600 text-white'
                        : 'text-gray-600 hover:bg-gray-100'
                    } disabled:opacity-50`}
                  >
                    3:4 黄金比例
                  </button>
                  <button
                    onClick={() => setSelectedAspectRatio('9:16')}
                    disabled={isImageLoading}
                    className={`px-3 py-2 text-sm font-medium transition-colors border-l border-gray-200 ${
                      selectedAspectRatio === '9:16'
                        ? 'bg-blue-600 text-white'
                        : 'text-gray-600 hover:bg-gray-100'
                    } disabled:opacity-50`}
                  >
                    9:16 满屏竖图
                  </button>
                  <button
                    onClick={() => setSelectedAspectRatio('8:9')}
                    disabled={isImageLoading}
                    className={`px-3 py-2 text-sm font-medium transition-colors border-l border-gray-200 ${
                      selectedAspectRatio === '8:9'
                        ? 'bg-blue-600 text-white'
                        : 'text-gray-600 hover:bg-gray-100'
                    } disabled:opacity-50`}
                  >
                    8:9 对标卡片
                  </button>
                </div>
              </div>
            </div>

            {/* 第二行：导演开机指南 */}
            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500 bg-white rounded-lg px-3 py-2 border border-gray-100">
              <span className="font-medium text-gray-600">🎬 导演指南：</span>
              {selectedImageStyle === 'default' && (
                <span>💡 画面调性：强调电影质感、强烈的明暗对比、背景虚化，充满高级的故事叙事感。 | 🎯 推荐赛道：全赛道通用，尤其是情感故事、长文案解说、图书带货。</span>
              )}
              {selectedImageStyle === 'warm_book' && (
                <span>💡 画面调性：整体色调柔和温暖、像早晨铺满阳光的房间，有动漫治愈感。 | 🎯 推荐赛道：家庭教育、习惯培养、母婴育儿心得、温暖励志书单。</span>
              )}
              {selectedImageStyle === 'clean_health' && (
                <span>💡 画面调性：干净明亮的自然光、画面极简洁、色彩鲜艳生动、大厂广告片质感。 | 🎯 推荐赛道：中老年健康调理、中草药养生、家居好物、生活日用品带货。</span>
              )}
              {selectedImageStyle === 'philosophy' && (
                <span>💡 画面调性：偏向暗沉深邃的色调、阴影感强烈、带有一点艺术史诗的孤独与深思氛围。 | 🎯 推荐赛道：深度人生感悟、中年危机破局、商业认知觉醒、高端思维模型。</span>
              )}
            </div>

            {/* 第三行：操作按钮 */}
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={handleGenerateImages}
                disabled={!taskId || isImageLoading || imageSummary?.generating === true}
                title={imageSummary?.generating ? '配图正在生成中，请等待完成' : imageSummary?.complete ? '配图已完成，点击重新生成' : ''}
                className="flex items-center gap-2 px-5 py-2 bg-purple-600 text-white font-medium rounded-xl hover:bg-purple-700 disabled:bg-purple-300 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {isImageLoading || imageSummary?.generating ? <><span>⏳</span><span>生成中...</span></>
                  : imageSummary?.complete ? <><span>🔄</span><span>重新生成全部配图（{selectedAspectRatio} 单图直生）</span></>
                  : <><span>🎨</span><span>生成全部配图（{selectedAspectRatio} 单图直生）</span></>}
              </button>
              <label className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border cursor-pointer select-none transition-colors ${
                forceRegen ? 'bg-red-50 border-red-400 text-red-700' : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300'
              }`}>
                <input
                  type="checkbox"
                  checked={forceRegen}
                  onChange={(e) => setForceRegen(e.target.checked)}
                  className="accent-red-500 w-3.5 h-3.5"
                />
                🗑️ 强制重跑（忽略缓存）
              </label>
              <div className="flex items-center gap-1 px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg select-none">
                <span className="text-gray-400 mr-1">性别</span>
                {[
                  { v: "auto", l: "自动" },
                  { v: "male", l: "男" },
                  { v: "female", l: "女" },
                ].map(({ v, l }) => (
                  <label key={v} className={`px-2 py-0.5 rounded cursor-pointer text-xs font-medium transition-colors ${
                    genderOverride === v ? 'bg-purple-600 text-white' : 'text-gray-500 hover:bg-gray-100'
                  }`}>
                    <input type="radio" name="genderOverride" value={v} checked={genderOverride === v}
                      onChange={(e) => setGenderOverride(e.target.value)} className="sr-only" />
                    {l}
                  </label>
                ))}
              </div>
              <button
                onClick={refreshImages}
                disabled={!taskId}
                className="flex items-center gap-1 px-3 py-2 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-100 disabled:opacity-50 transition-colors"
              >
                🔄 刷新
              </button>
            </div>
          </div>

          {/* v9: 智能状态条（后端权威数据驱动） */}
          {imageSummary?.generating && (
            <div className="mb-4 px-4 py-3 bg-orange-50 border border-orange-300 rounded-xl flex items-center gap-3">
              <span className="inline-block w-3 h-3 bg-orange-500 rounded-full animate-pulse" />
              <span className="text-sm text-orange-700 font-medium">
                🎨 正在生成配图…（{imageSummary.success}/{imageSummary.total}）
              </span>
              <span className="text-xs text-orange-500 ml-auto">请勿刷新页面，等待完成即可</span>
            </div>
          )}
          {imageSummary?.complete && imageSummary.failed === 0 && (
            <div className="mb-4 px-4 py-3 bg-green-50 border border-green-300 rounded-xl flex items-center gap-3">
              <span className="text-lg">✅</span>
              <span className="text-sm text-green-700 font-medium">
                全部配图生成完成（{imageSummary.success}/{imageSummary.total}），可以合成视频了
              </span>
            </div>
          )}
          {imageSummary?.complete && imageSummary.failed > 0 && (
            <div className="mb-4 px-4 py-3 bg-yellow-50 border border-yellow-300 rounded-xl flex items-center gap-3">
              <span className="text-lg">⚠️</span>
              <span className="text-sm text-yellow-700 font-medium">
                配图生成完成（{imageSummary.success}/{imageSummary.total}，{imageSummary.failed} 张失败），
                可点击失败图片单独重跑，或直接合成视频
              </span>
            </div>
          )}
          {/* 旧版进度提示（后端未返回 image_summary 时的兜底） */}
          {isImageLoading && !imageSummary && (
            <div className="mb-4 px-4 py-3 bg-purple-50 border border-purple-200 rounded-xl flex items-center gap-3">
              <span className="inline-block w-3 h-3 bg-purple-500 rounded-full animate-pulse" />
              <span className="text-sm text-purple-700">配图生成中（单图逐张直出，已生成的可即时预览）...</span>
              {imageMessage && (
                <span className="text-sm text-purple-600 font-semibold ml-2">{imageMessage}</span>
              )}
            </div>
          )}
          {imageMessage && !isImageLoading && !imageSummary && (
            <div className={`mb-4 px-4 py-3 border rounded-xl text-sm ${
              imageMessage.includes('失败')
                ? 'bg-red-50 border-red-200 text-red-700'
                : 'bg-green-50 border-green-200 text-green-700'
            }`}>
              {imageMessage}
            </div>
          )}

          {/* ===== v2 缩略图网格布局 ===== */}
          {images.length > 0 && (
            <div className="space-y-4">
              {/* 工具栏：切换布局 + 按九宫格筛选 */}
              <div className="flex items-center gap-3 text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2">
                <span>📐 共 {images.length} 张候选图 | </span>
                <button
                  onClick={() => setSelectedImageIndex(null)}
                  className="text-blue-500 hover:text-blue-700 underline"
                >
                  收起大图预览
                </button>
                <span className="ml-auto">← → 方向键快速切换 | 点击卡片查看大图</span>
              </div>

              {/* 缩略图网格：响应式 4-8 列 */}
              <div className="grid gap-3"
                style={{
                  gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
                  maxHeight: selectedImageIndex !== null ? 'none' : undefined,
                }}
              >
                {[...images]
                  .sort((a: any, b: any) => (a.segment_index ?? 0) - (b.segment_index ?? 0))
                  .map((img: any) => {
                    const sentIdx = img.segment_index ?? 0
                    const isSelected = selectedImageIndex === sentIdx
                    const isSuccess = img.status === 'success'
                    const isRegenning = isRegeneratingImage === sentIdx

                    return (
                      <div
                        key={img.id || sentIdx}
                        className={`relative group rounded-xl overflow-hidden border-2 transition-all cursor-pointer ${
                          isSelected
                            ? 'border-purple-500 shadow-lg shadow-purple-200 scale-[1.02]'
                            : isSuccess
                              ? 'border-gray-200 hover:border-blue-300 hover:shadow-md'
                              : 'border-red-200 bg-red-50'
                        }`}
                        onClick={() => setSelectedImageIndex(isSelected ? null : sentIdx)}
                        style={{ aspectRatio: '9/16', maxWidth: '220px', justifySelf: 'center', width: '100%' }}
                      >
                        {/* 图片 */}
                        {isSuccess && img.image_url ? (
                          <img
                            src={`${API_BASE}${img.image_url}`}
                            alt={`分镜 ${sentIdx + 1}`}
                            className="w-full h-full object-cover"
                            loading="lazy"
                            onError={(e) => {
                              (e.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 90 160"><rect fill="%23f0f0f0" width="90" height="160"/><text x="45" y="80" text-anchor="middle" fill="%23999" font-size="12">加载失败</text></svg>'
                            }}
                          />
                        ) : (
                          <div className="w-full h-full flex flex-col items-center justify-center bg-gray-100 text-gray-400">
                            <span className="text-2xl mb-1">{isRegenning ? '⏳' : '❌'}</span>
                            <span className="text-[10px] text-center px-1">{isRegenning ? '生成中' : '失败'}</span>
                          </div>
                        )}

                        {/* Hover 遮罩 + 操作栏 */}
                        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-2">
                          <span className="text-white text-xs font-bold drop-shadow-md">
                            🎬 分镜 {sentIdx + 1}
                          </span>
                          {img.sentence_text && (
                            <span className="text-white/80 text-[10px] truncate drop-shadow-sm mt-0.5">
                              {img.sentence_text.slice(0, 30)}
                            </span>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              handleRegenerateSegmentImage(sentIdx)
                            }}
                            disabled={isRegenning || isImageLoading}
                            className="mt-1.5 px-2 py-1 text-[10px] bg-amber-500/90 text-white rounded hover:bg-amber-600 disabled:bg-amber-400/50 disabled:cursor-not-allowed transition-colors font-medium self-start"
                          >
                            {isRegenning ? '⏳' : '🔄 单独重跑此张'}
                          </button>
                        </div>

                        {/* 状态角标 */}
                        <div className={`absolute top-1.5 right-1.5 w-2.5 h-2.5 rounded-full shadow-sm ${
                          isSuccess ? 'bg-green-400' : 'bg-red-400'
                        }`} title={isSuccess ? '已生成' : '失败'} />

                        {/* 选中态：底部序号条 */}
                        {isSelected && (
                          <div className="absolute bottom-0 left-0 right-0 h-1 bg-purple-500" />
                        )}
                      </div>
                    )
                  })}
              </div>

              {/* 大图预览弹窗（点击卡片时显示在网格下方） */}
              {selectedImageIndex !== null && (() => {
                const selectedImg = images.find((i: any) => i.segment_index === selectedImageIndex)
                const segIdx = selectedImageIndex
                const isRegenning = isRegeneratingImage === segIdx
                if (!selectedImg) return null

                return (
                  <div className="border-2 border-purple-300 rounded-xl overflow-hidden bg-gray-900">
                    <div className="flex items-center justify-between px-4 py-2 bg-gray-800">
                      <div className="flex items-center gap-3">
                        <span className="text-sm text-white font-medium">
                          🎬 分镜 {segIdx + 1}
                        </span>
                        <span className={`text-xs ${selectedImg.status === 'success' ? 'text-green-400' : 'text-red-400'}`}>
                          {selectedImg.status === 'success' ? '🟢 已生成' : '🔴 失败'}
                        </span>
                        <span className="text-xs text-purple-400">单图直生 v4</span>
                        {selectedImg.sentence_text && (
                          <span className="text-xs text-gray-300 truncate max-w-md ml-2 border-l border-gray-600 pl-3">
                            {selectedImg.sentence_text.slice(0, 60)}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => {
                            const sorted = [...images].sort((a, b) => (a.segment_index ?? 0) - (b.segment_index ?? 0))
                            const minIdx = sorted[0]?.segment_index ?? 0
                            setSelectedImageIndex(Math.max(minIdx, segIdx - 1))
                          }}
                          disabled={segIdx <= (images.length > 0 ? [...images].sort((a, b) => (a.segment_index ?? 0) - (b.segment_index ?? 0))[0]?.segment_index ?? 0 : 0)}
                          className="px-3 py-1 text-xs text-gray-300 bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                        >
                          ← 上一张
                        </button>
                        <button
                          onClick={() => {
                            const sorted = [...images].sort((a, b) => (a.segment_index ?? 0) - (b.segment_index ?? 0))
                            const maxIdx = sorted[sorted.length - 1]?.segment_index ?? 0
                            setSelectedImageIndex(Math.min(maxIdx, segIdx + 1))
                          }}
                          disabled={segIdx >= (images.length - 1)}
                          className="px-3 py-1 text-xs text-gray-300 bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                        >
                          下一张 →
                        </button>
                        <button
                          onClick={() => handleRegenerateSegmentImage(segIdx)}
                          disabled={isRegenning || isImageLoading}
                          className="flex items-center gap-1 px-4 py-1.5 text-sm bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:bg-amber-300 disabled:cursor-not-allowed transition-colors font-medium"
                        >
                          {isRegenning ? '⏳ 生成中' : '🔄 单独重跑此张'}
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center justify-center p-4" style={{ minHeight: '400px', maxHeight: '70vh' }}>
                      {selectedImg.status === 'success' && selectedImg.image_url ? (
                        <img
                          src={`${API_BASE}${selectedImg.image_url}`}
                          alt={`分镜 ${segIdx + 1} 配图`}
                          className="max-h-full object-contain rounded-lg shadow-2xl"
                          style={{ maxHeight: '65vh' }}
                        />
                      ) : (
                        <div className="text-gray-500 text-center py-16">
                          <div className="text-5xl mb-3">❌</div>
                          <p className="text-sm">该分镜配图生成失败</p>
                          {selectedImg.error_msg && (
                            <p className="text-xs text-red-400 mt-1 max-w-sm">{selectedImg.error_msg}</p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}
            </div>
          )}

          {images.length === 0 && !isImageLoading && !imageSummary?.generating && (
            <div className="text-center py-8 text-gray-400 text-sm">
              ↑ 选择风格后点击「生成全部配图」，逐句独立生成单张配图<br />
              生成中可即时预览已完成图片，完成后按钮会自动亮起通知你合成
            </div>
          )}
        </section>

        {/* ===== Step 05: 视频合成 ===== */}
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-semibold text-gray-700">🎬 Step 05: 视频合成（Ken Burns + 字幕）</h2>
            {videoUrl && (
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-green-50 text-green-600 text-sm font-medium rounded-full">
                <span>✓</span> 已合成 · {videoDuration}秒 · {videoSizeMb}MB
              </span>
            )}
          </div>

          {/* 合成控制栏 */}
          <div className="bg-gray-50 rounded-xl p-4 mb-5 flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-gray-600 whitespace-nowrap">🎬 风格：</label>
              <select
                value={selectedVideoStyle}
                onChange={(e) => setSelectedVideoStyle(e.target.value)}
                disabled={isVideoLoading}
                className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              >
                <option value="cinematic">满屏电影感 (全幅 Ken Burns)</option>
                <option value="card_16x9">经典图书三段式 (16:9 视窗版)</option>
                <option value="card_3x4">黄金遮罩三段式 (3:4 视窗版)</option>
                <option value="card_bench">对标卡片 (深藏青 + 8:9 满宽大图)</option>
              </select>
            </div>
            {(() => {
              const imagesReady = imageSummary?.complete === true
              const imagesGenerating = imageSummary?.generating === true
              const canCompose = imagesReady && !isVideoLoading && taskId
              const btnTitle = !taskId ? '请先创建任务'
                : imagesGenerating ? '配图生成中，请等待完成后再合成'
                : !imagesReady ? '请先生成配图'
                : ''
              return (
                <button
                  onClick={handleComposeVideo}
                  disabled={!canCompose}
                  title={btnTitle}
                  className={`flex items-center gap-2 px-5 py-2 text-white font-medium rounded-xl transition-colors shadow-sm ${
                    canCompose
                      ? 'bg-red-600 hover:bg-red-700'
                      : 'bg-gray-300 text-gray-500 cursor-not-allowed'
                  }`}
                >
                  {isVideoLoading ? <><span>⏳</span><span>合成中...</span></>
                    : imagesGenerating ? <><span>🔒</span><span>等待配图完成</span></>
                    : !imagesReady ? <><span>🔒</span><span>请先生成配图</span></>
                    : <><span>🎬</span><span>合成最终成片</span></>
                  }
                </button>
              )
            })()}
            <button
              onClick={checkVideoStatus}
              disabled={!taskId}
              className="flex items-center gap-1 px-3 py-2 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors"
            >
              🔄 检查已有成片
            </button>
          </div>

          {/* v7: 底部标语配置 */}
          <div className="bg-gray-50 rounded-xl p-4 mb-5 space-y-3">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">💬 底部核心标语 (Slogan)</label>
                <input
                  type="text"
                  value={cardSlogan}
                  onChange={(e) => setCardSlogan(e.target.value)}
                  disabled={isVideoLoading}
                  placeholder="- 品读传奇人生 -"
                  className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-amber-400 disabled:opacity-50"
                />
                <p className="text-xs text-gray-400 mt-1">楷体/手写体 · 哑光金 #CBA052 · 48-50px</p>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">📜 底部免责声明小字 (Subtitle)</label>
                <textarea
                  value={cardSubtitleLine}
                  onChange={(e) => setCardSubtitleLine(e.target.value)}
                  disabled={isVideoLoading}
                  rows={2}
                  placeholder={"图片由AI生成与网络下载\n科普视频 无不良引导"}
                  className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 resize-none focus:outline-none focus:ring-2 focus:ring-amber-400 disabled:opacity-50"
                />
                <p className="text-xs text-gray-400 mt-1">\\n 换行 · 思源黑体 · 浅灰 #666666 · 24-26px</p>
              </div>
            </div>
          </div>

          {/* 进度消息 */}
          {isVideoLoading && (
            <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-xl flex items-center gap-3">
              <span className="inline-block w-3 h-3 bg-red-500 rounded-full animate-pulse" />
              <span className="text-sm text-red-700">视频合成中，正在逐段渲染 Ken Burns 动效 + 字幕...</span>
            </div>
          )}
          {videoMessage && !isVideoLoading && (
            <div className={`mb-4 px-4 py-3 border rounded-xl text-sm ${
              videoMessage.includes('失败') || videoMessage.includes('错误')
                ? 'bg-red-50 border-red-200 text-red-700'
                : 'bg-green-50 border-green-200 text-green-700'
            }`}>
              {videoMessage}
            </div>
          )}

          {/* 视频播放器 */}
          {videoUrl && (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-gray-600">📺 最终成片</span>
                <span className="text-xs text-gray-400">1080×1920 · {videoDuration}秒 · {videoSizeMb}MB</span>
              </div>
              <div className="bg-black rounded-xl overflow-hidden" style={{ maxHeight: '70vh' }}>
                <video
                  controls
                  src={videoUrl}
                  className="w-full"
                  style={{ maxHeight: '70vh', objectFit: 'contain' }}
                  poster={`${API_BASE}/images/${taskId}/seg_000.png`}
                />
              </div>
              {/* v4: 下载按钮行 —— SRT / ASS + 剪映自动发布状态 */}
              <div className="flex items-center gap-3 flex-wrap">
                <a
                  href={videoUrl}
                  download={`成片_${videoTitle || taskId || ''}.mp4`}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-red-50 text-red-700 border border-red-200 rounded-lg hover:bg-red-100 transition-colors font-medium"
                >
                  <span className="text-base">⬇️</span> 下载成片
                </a>
                <button
                  onClick={() => fetch(`${API_BASE}/api/open-output-dir`, { method: 'POST' })}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-gray-50 text-gray-700 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors"
                  title="在服务器主机上打开成品库文件夹（远程同事请用下载按钮）"
                >
                  <span className="text-base">📂</span> 打开成品库
                </button>
                {srtDownloadUrl && (
                  <a
                    href={srtDownloadUrl}
                    download
                    className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-blue-50 text-blue-700 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors"
                  >
                    <span className="text-base">📝</span> SRT 字幕下载
                  </a>
                )}
                {assDownloadUrl && (
                  <a
                    href={assDownloadUrl}
                    download
                    className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-purple-50 text-purple-700 border border-purple-200 rounded-lg hover:bg-purple-100 transition-colors"
                  >
                    <span className="text-base">🎨</span> ASS 高级字幕下载
                  </a>
                )}
                {jianyingPublished && (
                  <span className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-green-50 text-green-700 border border-green-200 rounded-lg font-medium">
                    <span className="text-base">✅</span> 已自动发送到剪映草稿箱{jianyingDraftName ? ` · ${jianyingDraftName}` : ''}
                  </span>
                )}
                {!jianyingPublished && draftDownloadUrl && (
                  <a
                    href={draftDownloadUrl}
                    download
                    className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-amber-50 text-amber-700 border border-amber-200 rounded-lg hover:bg-amber-100 transition-colors font-medium"
                  >
                    <span className="text-base">⚠️</span> 剪映草稿（未自动发布，点此下载）
                  </a>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>💡 提示：视频编码为 H.264，可直接上传抖音/视频号/小红书</span>
                {archivePath && <span>· 已归档: {archivePath}</span>}
              </div>
            </div>
          )}

          {/* v7: 三段式卡片成品 */}
          {videoUrlCard && (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-gray-600">📚 图书口播卡片（三段式）</span>
                <span className="text-xs text-gray-400">1080×1920 · 顶部书名 + 中部动图 + 底部声明</span>
              </div>
              <div className="bg-black rounded-xl overflow-hidden" style={{ maxHeight: '70vh' }}>
                <video
                  controls
                  src={videoUrlCard}
                  className="w-full"
                  style={{ maxHeight: '70vh', objectFit: 'contain' }}
                />
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>💡 提示：黄金三段式布局，书名+配图+声明三段独立，适合图书带货口播</span>
              </div>
            </div>
          )}

          {!videoUrl && !isVideoLoading && (
            <div className="text-center py-8 text-gray-400 text-sm">
              {imageSummary?.complete
                ? '↑ 配图已完成，选择风格点击「合成最终成片」'
                : imageSummary?.generating
                  ? '⏳ 配图生成中，完成后合成按钮将自动亮起'
                  : '↑ 请先生成配图，完成后合成按钮会自动亮起'}
            </div>
          )}
        </section>

        {/* ===== 底部状态栏 ===== */}
        <footer className="flex items-center gap-2 px-2 py-3 text-sm text-gray-500">
          <span className={`inline-block w-2 h-2 rounded-full ${
            backendStatus === 'healthy' ? 'bg-green-500' : backendStatus === 'offline' ? 'bg-red-400' : 'bg-gray-400'
          }`} />
          <span>后端状态: {backendStatus === 'checking' ? '检测中...' : backendStatus}</span>
        </footer>

      </main>
    </div>
  )
}

export default App
