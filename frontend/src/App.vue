<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  BookOpen,
  Check,
  Clapperboard,
  Columns3,
  Copy,
  FolderOpen,
  Languages,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Rows3,
  Settings2,
  SkipForward,
  UploadCloud,
  WalletCards,
} from 'lucide-vue-next'

const LAYOUT_STORAGE_KEY = 'echoclip.layout.v2'
const apiUrl = ref(localStorage.getItem('echoclip.apiUrl') || defaultBackendApi())
const baseUrl = ref(localStorage.getItem('echoclip.baseUrl') || 'http://192.168.2.172:8000/v1')
const model = ref(localStorage.getItem('echoclip.model') || 'whisper-1')
const apiKey = ref(localStorage.getItem('echoclip.apiKey') || '')
const language = ref(localStorage.getItem('echoclip.language') || 'en')
const preferEmbedded = ref(localStorage.getItem('echoclip.preferEmbedded') !== 'false')

const file = ref(null)
const fileName = ref('')
const isLoading = ref(false)
const error = ref('')
const transcript = ref(null)
const activeSegmentIndex = ref(0)
const activeWordIndex = ref(-1)
const videoRef = ref(null)
const transcriptWindowRef = ref(null)
const segmentRefs = ref([])
const targetSegmentIndex = ref(0)
const showSettings = ref(false)
const dragActive = ref(false)
const mode = ref(localStorage.getItem('echoclip.mode') || 'guided')
const layout = ref(localStorage.getItem(LAYOUT_STORAGE_KEY) || defaultLayout())
const isPlaying = ref(false)
const copiedSegmentIndex = ref(-1)
const view = ref('practice')
const historyItems = ref([])
const historyLoading = ref(false)

function defaultBackendApi() {
  const protocol = window.location.protocol || 'http:'
  const host = window.location.hostname || 'localhost'
  return `${protocol}//${host}:8000`
}

function defaultLayout() {
  return window.matchMedia('(min-width: 761px)').matches ? 'split' : 'stack'
}

const activeSegment = computed(() => transcript.value?.segments?.[activeSegmentIndex.value] || null)
const hasTranscript = computed(() => Boolean(transcript.value?.segments?.length))
const activeSegmentNumber = computed(() => {
  if (!hasTranscript.value) return '0 / 0'
  return `${activeSegmentIndex.value + 1} / ${transcript.value.segments.length}`
})
const loadingLabel = computed(() => {
  if (!isLoading.value) return 'Build transcript'
  return preferEmbedded.value ? 'Importing subtitles…' : 'Transcribing…'
})
const transcriptSourceLabel = computed(() => {
  if (!transcript.value?.source) return ''
  if (transcript.value.source === 'embedded') {
    const track = transcript.value.subtitle_track ? ` (${transcript.value.subtitle_track})` : ''
    return `Using embedded subtitles${track}`
  }
  return 'Transcribed with Whisper'
})
const layoutIcon = computed(() => (layout.value === 'split' ? Rows3 : Columns3))

watch([apiUrl, baseUrl, model, apiKey, language, preferEmbedded], () => {
  localStorage.setItem('echoclip.apiUrl', apiUrl.value)
  localStorage.setItem('echoclip.baseUrl', baseUrl.value)
  localStorage.setItem('echoclip.model', model.value)
  localStorage.setItem('echoclip.apiKey', apiKey.value)
  localStorage.setItem('echoclip.language', language.value)
  localStorage.setItem('echoclip.preferEmbedded', preferEmbedded.value ? 'true' : 'false')
})

watch(mode, () => {
  localStorage.setItem('echoclip.mode', mode.value)
  if (hasTranscript.value) restartFromBeginning()
})

watch(layout, () => {
  localStorage.setItem(LAYOUT_STORAGE_KEY, layout.value)
  nextTick(scrollActiveSegmentIntoView)
})

watch(activeSegmentIndex, () => {
  nextTick(scrollActiveSegmentIntoView)
})

onMounted(() => {
  const saved = localStorage.getItem('echoclip.lastTranscript')
  if (saved) {
    try {
      transcript.value = JSON.parse(saved)
      nextTick(scrollActiveSegmentIntoView)
    } catch {
      localStorage.removeItem('echoclip.lastTranscript')
    }
  }
  loadHistory()
})

function pickFile(event) {
  const selected = event.target.files?.[0]
  setFile(selected)
}

function setFile(selected) {
  if (!selected) return
  file.value = selected
  fileName.value = selected.name
  error.value = ''
}

function onDrop(event) {
  dragActive.value = false
  setFile(event.dataTransfer.files?.[0])
}

async function submitTranscription() {
  if (!file.value) {
    error.value = 'Choose a video first.'
    return
  }
  isLoading.value = true
  error.value = ''

  const body = new FormData()
  body.append('file', file.value)
  body.append('api_key', apiKey.value.trim())
  body.append('base_url', baseUrl.value.trim())
  body.append('model', model.value.trim())
  if (language.value.trim()) body.append('language', language.value.trim())
  body.append('prefer_embedded', preferEmbedded.value ? 'true' : 'false')

  try {
    const response = await fetch(`${apiUrl.value.replace(/\/$/, '')}/api/transcriptions`, {
      method: 'POST',
      body,
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(payload?.detail || 'Transcription failed.')
    }
    transcript.value = payload
    activeSegmentIndex.value = 0
    activeWordIndex.value = -1
    targetSegmentIndex.value = 0
    segmentRefs.value = []
    localStorage.setItem('echoclip.lastTranscript', JSON.stringify(payload))
    await loadHistory()
    await nextTick()
    view.value = 'practice'
    restartFromBeginning()
  } catch (caught) {
    if (caught instanceof TypeError && caught.message === 'Failed to fetch') {
      error.value = `Cannot reach backend at ${apiUrl.value}. Check Wi-Fi, backend address, or port 8000.`
    } else {
      error.value = caught.message || 'Something went wrong.'
    }
  } finally {
    isLoading.value = false
  }
}

async function loadSampleVideo() {
  error.value = ''
  try {
    const sampleUrl = `${apiUrl.value.replace(/\/$/, '')}/samples/inqscribe-intro.mp4`
    const response = await fetch(sampleUrl)
    if (!response.ok) throw new Error('Could not load sample video.')
    const blob = await response.blob()
    setFile(new File([blob], 'inqscribe-intro.mp4', { type: 'video/mp4' }))
  } catch (caught) {
    error.value = caught.message || 'Could not load sample video.'
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const response = await fetch(`${apiUrl.value.replace(/\/$/, '')}/api/projects`)
    const payload = await response.json().catch(() => null)
    if (!response.ok) throw new Error(payload?.detail || 'Could not load history.')
    historyItems.value = payload?.projects || []
  } catch (caught) {
    error.value = caught.message || 'Could not load history.'
  } finally {
    historyLoading.value = false
  }
}

async function openProject(projectId) {
  error.value = ''
  try {
    const response = await fetch(`${apiUrl.value.replace(/\/$/, '')}/api/projects/${projectId}`)
    const payload = await response.json().catch(() => null)
    if (!response.ok) throw new Error(payload?.detail || 'Could not open history item.')
    transcript.value = payload
    file.value = null
    fileName.value = payload.filename
    activeSegmentIndex.value = 0
    activeWordIndex.value = -1
    targetSegmentIndex.value = 0
    segmentRefs.value = []
    localStorage.setItem('echoclip.lastTranscript', JSON.stringify(payload))
    view.value = 'practice'
    await nextTick()
    seekTo(payload.segments?.[0]?.start || 0, 0, -1, false)
  } catch (caught) {
    error.value = caught.message || 'Could not open history item.'
  }
}

function showLibrary() {
  view.value = 'library'
  loadHistory()
}

function newPractice() {
  view.value = 'practice'
  error.value = ''
}

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '--:--'
  const total = Math.round(seconds)
  const minutes = Math.floor(total / 60)
  const rest = String(total % 60).padStart(2, '0')
  return `${minutes}:${rest}`
}

function formatDate(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function setSegmentRef(element, index) {
  if (element) segmentRefs.value[index] = element
}

function scrollActiveSegmentIntoView() {
  const container = transcriptWindowRef.value
  const element = segmentRefs.value[activeSegmentIndex.value]
  if (!container || !element) return
  const top = element.offsetTop - container.clientHeight / 2 + element.clientHeight / 2
  container.scrollTo({ top: Math.max(top, 0), behavior: 'smooth' })
}

function seekTo(time, segmentIndex = null, wordIndex = -1, autoplay = true) {
  if (segmentIndex !== null) activeSegmentIndex.value = segmentIndex
  if (segmentIndex !== null && mode.value === 'guided') targetSegmentIndex.value = segmentIndex
  activeWordIndex.value = wordIndex
  const video = videoRef.value
  if (!video) return
  video.currentTime = Math.max(time, 0)
  if (autoplay) video.play().catch(() => {})
}

function restartFromBeginning() {
  if (!hasTranscript.value) return
  playSegment(0)
}

function playSegment(index) {
  const segment = transcript.value?.segments?.[index]
  if (!segment) return
  targetSegmentIndex.value = index
  seekTo(segment.start, index, -1, true)
}

function replaySegment() {
  if (!activeSegment.value) return
  playSegment(activeSegmentIndex.value)
}

function nextSegment() {
  if (!transcript.value) return
  const baseIndex = mode.value === 'guided' ? targetSegmentIndex.value : activeSegmentIndex.value
  const nextIndex = Math.min(baseIndex + 1, transcript.value.segments.length - 1)
  playSegment(nextIndex)
}

function pausePlayback() {
  videoRef.value?.pause()
}

async function copySegment(segment, index) {
  try {
    await navigator.clipboard.writeText(segment.text)
    copiedSegmentIndex.value = index
    window.setTimeout(() => {
      if (copiedSegmentIndex.value === index) copiedSegmentIndex.value = -1
    }, 1200)
  } catch {
    error.value = 'Could not copy subtitle.'
  }
}

function toggleLayout() {
  layout.value = layout.value === 'stack' ? 'split' : 'stack'
}

function setMode(nextMode) {
  mode.value = nextMode
}

function onTimeUpdate() {
  const video = videoRef.value
  if (!video || !transcript.value) return
  const time = video.currentTime

  const segmentIndex = findSegmentIndex(time)
  if (segmentIndex >= 0) activeSegmentIndex.value = segmentIndex

  const wordIndex = transcript.value.words.findIndex(
    (word) => time >= word.start && time <= word.end + 0.08,
  )
  activeWordIndex.value = wordIndex

  const targetSegment = transcript.value.segments[targetSegmentIndex.value]
  if (mode.value === 'guided' && targetSegment && time >= targetSegment.end - 0.03) {
    video.pause()
    video.currentTime = targetSegment.end
    activeSegmentIndex.value = targetSegmentIndex.value
  }
}

function findSegmentIndex(time) {
  if (!transcript.value?.segments?.length) return -1
  let index = transcript.value.segments.findIndex((segment) => time >= segment.start && time < segment.end)
  if (index >= 0) return index
  for (let cursor = transcript.value.segments.length - 1; cursor >= 0; cursor -= 1) {
    if (time >= transcript.value.segments[cursor].start) return cursor
  }
  return 0
}

function wordGlobalIndex(word) {
  if (!transcript.value?.words) return -1
  return transcript.value.words.findIndex((item) => {
    return Math.abs(item.start - word.start) < 0.01 && item.text === word.text
  })
}
</script>

<template>
  <main class="app-shell" :class="{ 'has-transcript': hasTranscript && view === 'practice', 'is-library': view === 'library' }">
    <header class="topbar">
      <div>
        <p class="eyebrow">EchoClip</p>
        <h1>{{ view === 'library' ? 'Library.' : 'Listen closer.' }}</h1>
      </div>
      <button class="icon-button" type="button" title="Settings" @click="showSettings = !showSettings">
        <Settings2 :size="20" />
      </button>
    </header>

    <section v-if="showSettings" class="panel settings-panel">
      <label>
        Backend API
        <input v-model="apiUrl" placeholder="http://localhost:8000" />
      </label>
      <label>
        Whisper base URL
        <input v-model="baseUrl" placeholder="https://api.openai.com/v1" />
      </label>
      <div class="field-row">
        <label>
          Model
          <input v-model="model" placeholder="whisper-1" />
        </label>
        <label>
          Language
          <input v-model="language" placeholder="en" />
        </label>
      </div>
      <label>
        API key
        <input v-model="apiKey" type="password" autocomplete="off" placeholder="Optional" />
      </label>
      <label class="checkbox-row">
        <input v-model="preferEmbedded" type="checkbox" />
        <span>Prefer embedded subtitles when available</span>
      </label>
    </section>

    <section v-if="view === 'library'" class="library-page">
      <div class="library-header">
        <div>
          <p class="eyebrow">Saved Clips</p>
          <h2>Continue where you left off.</h2>
        </div>
        <button class="primary-button compact-text" type="button" @click="newPractice">
          <Plus :size="18" />
          New
        </button>
      </div>

      <div v-if="historyLoading" class="library-empty">
        <LoaderCircle class="spin" :size="22" />
        <span>Loading history</span>
      </div>
      <div v-else-if="!historyItems.length" class="library-empty">
        <FolderOpen :size="28" />
        <span>No saved clips yet.</span>
      </div>
      <div v-else class="history-list">
        <button
          v-for="item in historyItems"
          :key="item.id"
          class="history-item"
          type="button"
          @click="openProject(item.id)"
        >
          <span class="history-title">{{ item.filename }}</span>
          <span class="history-preview">{{ item.text_preview }}</span>
          <span class="history-meta">
            <span>{{ formatDuration(item.duration) }}</span>
            <span>{{ item.segment_count }} sentences</span>
            <span>{{ item.word_count }} words</span>
            <span>{{ formatDate(item.updated_at) }}</span>
          </span>
        </button>
      </div>
      <p v-if="error" class="error library-error">{{ error }}</p>
    </section>

    <template v-else>
    <section class="panel upload-panel">
      <label
        class="drop-zone"
        :class="{ active: dragActive }"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="onDrop"
      >
        <input type="file" accept="video/*,audio/*" @change="pickFile" />
        <UploadCloud :size="22" />
        <span>{{ fileName || 'Choose English video' }}</span>
      </label>
      <button class="primary-button" type="button" :disabled="isLoading" @click="submitTranscription">
        <LoaderCircle v-if="isLoading" class="spin" :size="18" />
        <Check v-else :size="18" />
        {{ loadingLabel }}
      </button>
      <button class="sample-button" type="button" :disabled="isLoading" @click="loadSampleVideo">
        <Clapperboard :size="18" />
        Sample
      </button>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="transcriptSourceLabel" class="source-note">{{ transcriptSourceLabel }}</p>
    </section>

    <section class="workbench" :class="{ split: layout === 'split' }">
      <section class="video-stage">
        <video
          v-if="transcript"
          ref="videoRef"
          class="video"
          :src="transcript.media_url"
          controls
          playsinline
          @pause="isPlaying = false"
          @play="isPlaying = true"
          @timeupdate="onTimeUpdate"
        />
        <div v-else class="empty-stage">
          <UploadCloud :size="34" />
          <span>Upload a clip to build a word map.</span>
        </div>
      </section>

      <section v-if="hasTranscript" class="subtitle-panel">
        <div class="control-strip">
          <div class="mode-toggle" role="group" aria-label="Playback mode">
            <button type="button" :class="{ selected: mode === 'guided' }" @click="setMode('guided')">
              <SkipForward :size="16" />
              Sentence
            </button>
            <button type="button" :class="{ selected: mode === 'continuous' }" @click="setMode('continuous')">
              <Play :size="16" />
              Full
            </button>
          </div>
          <button class="icon-button compact" type="button" title="Toggle layout" @click="toggleLayout">
            <component :is="layoutIcon" :size="18" />
          </button>
        </div>

        <div class="transport-row">
          <button v-if="mode === 'guided'" class="tool-button" type="button" @click="nextSegment">
            <SkipForward :size="17" />
            Next
          </button>
          <button v-if="mode === 'guided'" class="tool-button" type="button" @click="replaySegment">
            <RotateCcw :size="17" />
            Replay
          </button>
          <button v-if="mode === 'continuous'" class="tool-button" type="button" @click="pausePlayback">
            <Pause :size="17" />
            Pause
          </button>
          <button class="tool-button" type="button" @click="restartFromBeginning">
            <Play :size="17" />
            Start
          </button>
          <div class="status-pill">{{ activeSegmentNumber }}</div>
          <div v-if="transcriptSourceLabel" class="source-pill">{{ transcriptSourceLabel }}</div>
        </div>

        <div ref="transcriptWindowRef" class="lyric-window">
          <div class="lyric-spacer" />
          <div
            v-for="(segment, index) in transcript.segments"
            :key="`${segment.start}-${index}`"
            :ref="(element) => setSegmentRef(element, index)"
            class="lyric-line"
            :class="{ active: index === activeSegmentIndex }"
          >
            <button v-if="index !== activeSegmentIndex" class="line-button" type="button" @click="seekTo(segment.start, index)">
              <span class="timestamp">{{ segment.start.toFixed(1) }}s</span>
              <span class="line-text">{{ segment.text }}</span>
            </button>
            <div v-else class="active-line">
              <button class="timestamp active-time" type="button" @click="seekTo(segment.start, index)">
                {{ segment.start.toFixed(1) }}s
              </button>
              <span class="inline-words">
                <button
                  v-for="(word, wordIndex) in segment.words"
                  :key="`${word.start}-${word.text}-${wordIndex}`"
                  class="word-chip"
                  :class="{ active: wordGlobalIndex(word) === activeWordIndex }"
                  type="button"
                  @click="seekTo(word.start, index, wordGlobalIndex(word))"
                >
                  {{ word.text }}
                </button>
              </span>
              <button class="copy-button" type="button" title="Copy subtitle" @click="copySegment(segment, index)">
                <Check v-if="copiedSegmentIndex === index" :size="15" />
                <Copy v-else :size="15" />
              </button>
            </div>
          </div>
          <div class="lyric-spacer" />
        </div>
      </section>
    </section>

    </template>

    <nav class="side-nav" aria-label="App navigation">
      <button type="button" title="Library" :class="{ selected: view === 'library' }" @click="showLibrary">
        <FolderOpen :size="19" /><span>Library</span>
      </button>
      <button type="button" title="Practice" :class="{ selected: view === 'practice' }" @click="newPractice">
        <Plus :size="19" /><span>Practice</span>
      </button>
      <button type="button" disabled title="Translate"><Languages :size="19" /><span>Translate</span></button>
      <button type="button" disabled title="Vocabulary"><BookOpen :size="19" /><span>Vocabulary</span></button>
      <button type="button" disabled title="Imports"><WalletCards :size="19" /><span>Imports</span></button>
    </nav>
  </main>
</template>
