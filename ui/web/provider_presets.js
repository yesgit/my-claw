/**
 * 国内常见模型提供商预设数据
 *
 * 每个 preset 包含：
 * - name: 提供商显示名
 * - slug: 唯一标识（用于生成 provider id）
 * - baseUrls: 可选的 baseUrl 列表，label 标注用途
 * - suggestedModels: 推荐的模型列表（仅作参考，用户可自由修改）
 *
 * 模型列表来源：各提供商官方文档 / API，最后更新 2026-05-18
 */
const PROVIDER_PRESETS = [
  // ===== DeepSeek =====
  {
    name: "DeepSeek",
    slug: "deepseek",
    baseUrls: [
      { label: "OpenAI 兼容", url: "https://api.deepseek.com" },
      { label: "Anthropic 兼容", url: "https://api.deepseek.com/anthropic" },
    ],
    suggestedModels: [
      { id: "deepseek-v4-flash", name: "DeepSeek V4 Flash", flash: true, vision: true },
      { id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", vision: true },
    ],
  },

  // ===== 阿里百炼（通义千问） =====
  {
    name: "阿里百炼（通义千问）",
    slug: "aliyun-dashscope",
    baseUrls: [
      { label: "默认", url: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
    ],
    suggestedModels: [
      { id: "qwen3.6-flash", name: "Qwen3.6 Flash", flash: true, vision: true },
      { id: "qwen3.6-plus", name: "Qwen3.6 Plus", vision: true },
      { id: "qwen3.6-max-preview", name: "Qwen3.6 Max Preview", vision: true },
      { id: "qwen3.5-omni-plus", name: "Qwen3.5 Omni Plus", vision: true },
    ],
  },

  // ===== 智谱 AI =====
  {
    name: "智谱 AI（GLM）",
    slug: "zhipu",
    baseUrls: [
      { label: "通用 API", url: "https://open.bigmodel.cn/api/paas/v4" },
      { label: "Coding API（编码套餐专用）", url: "https://open.bigmodel.cn/api/coding/paas/v4" },
    ],
    suggestedModels: [
      { id: "glm-4-flash", name: "GLM-4 Flash", flash: true },
      { id: "glm-4-plus", name: "GLM-4 Plus" },
      { id: "glm-4-air", name: "GLM-4 Air" },
      { id: "glm-4-long", name: "GLM-4 Long" },
      { id: "glm-4", name: "GLM-4" },
      { id: "glm-4-airx", name: "GLM-4 AirX" },
    ],
  },

  // ===== 月之暗面（Kimi） =====
  {
    name: "月之暗面（Kimi）",
    slug: "moonshot",
    baseUrls: [
      { label: "默认", url: "https://api.moonshot.cn/v1" },
    ],
    suggestedModels: [
      { id: "kimi-k2.6", name: "Kimi K2.6" },
      { id: "kimi-k2.5", name: "Kimi K2.5" },
      { id: "kimi-k2", name: "Kimi K2" },
      { id: "moonshot-v1-8k", name: "Moonshot V1 8K", flash: true },
      { id: "moonshot-v1-32k", name: "Moonshot V1 32K" },
      { id: "moonshot-v1-128k", name: "Moonshot V1 128K" },
    ],
  },

  // ===== 硅基流动（SiliconFlow） =====
  {
    name: "硅基流动（SiliconFlow）",
    slug: "siliconflow",
    baseUrls: [
      { label: "默认", url: "https://api.siliconflow.cn/v1" },
    ],
    suggestedModels: [
      { id: "Qwen/Qwen3-8B", name: "Qwen3-8B", flash: true },
      { id: "Qwen/Qwen3-32B", name: "Qwen3-32B" },
      { id: "deepseek-ai/DeepSeek-V3", name: "DeepSeek-V3" },
      { id: "deepseek-ai/DeepSeek-R1", name: "DeepSeek-R1" },
      { id: "Qwen/Qwen2.5-72B-Instruct", name: "Qwen2.5-72B" },
    ],
  },

  // ===== 字节豆包（Doubao） =====
  {
    name: "字节豆包（Doubao）",
    slug: "doubao",
    baseUrls: [
      { label: "默认", url: "https://ark.cn-beijing.volces.com/api/v3" },
    ],
    suggestedModels: [
      { id: "doubao-1.5-lite-32k", name: "Doubao 1.5 Lite 32K", flash: true },
      { id: "doubao-1.5-pro-32k", name: "Doubao 1.5 Pro 32K" },
      { id: "doubao-1.5-pro-128k", name: "Doubao 1.5 Pro 128K" },
    ],
  },

  // ===== 零一万物（Yi） =====
  {
    name: "零一万物（Yi）",
    slug: "lingyiwanwu",
    baseUrls: [
      { label: "默认", url: "https://api.lingyiwanwu.com/v1" },
    ],
    suggestedModels: [
      { id: "yi-lightning", name: "Yi Lightning", flash: true },
      { id: "yi-large", name: "Yi Large" },
      { id: "yi-large-turbo", name: "Yi Large Turbo" },
      { id: "yi-medium", name: "Yi Medium" },
    ],
  },

  // ===== 讯飞星火 =====
  {
    name: "讯飞星火",
    slug: "xfyun-spark",
    baseUrls: [
      { label: "默认", url: "https://spark-api-open.xf-yun.com/v1" },
    ],
    suggestedModels: [
      { id: "generalv3.5", name: "星火 3.5", flash: true },
      { id: "4.0Ultra", name: "星火 4.0 Ultra" },
      { id: "generalv3", name: "星火 3.0" },
    ],
  },

  // ===== MiniMax =====
  {
    name: "MiniMax",
    slug: "minimax",
    baseUrls: [
      { label: "默认", url: "https://api.minimaxi.chat/v1" },
    ],
    suggestedModels: [
      { id: "MiniMax-Text-01", name: "MiniMax Text 01" },
      { id: "abab6.5s-chat", name: "ABAB 6.5S Chat", flash: true },
      { id: "abab6.5-chat", name: "ABAB 6.5 Chat" },
    ],
  },

  // ===== 百度千帆 =====
  {
    name: "百度千帆",
    slug: "baidu-qianfan",
    baseUrls: [
      { label: "默认", url: "https://qianfan.baidubce.com/v2" },
    ],
    suggestedModels: [
      { id: "ernie-4.0-8k", name: "ERNIE 4.0 8K" },
      { id: "ernie-3.5-8k", name: "ERNIE 3.5 8K", flash: true },
      { id: "ernie-4.0-turbo-8k", name: "ERNIE 4.0 Turbo 8K" },
    ],
  },

  // ===== Groq =====
  {
    name: "Groq",
    slug: "groq",
    baseUrls: [
      { label: "默认", url: "https://api.groq.com/openai/v1" },
    ],
    suggestedModels: [
      { id: "llama-3.3-70b-versatile", name: "Llama 3.3 70B" },
      { id: "llama-3.1-8b-instant", name: "Llama 3.1 8B", flash: true },
      { id: "llama-3.2-3b-instruct", name: "Llama 3.2 3B" },
    ],
  },

  // ===== OpenRouter =====
  {
    name: "OpenRouter",
    slug: "openrouter",
    baseUrls: [
      { label: "默认", url: "https://openrouter.ai/api/v1" },
    ],
    suggestedModels: [
      { id: "deepseek/deepseek-v4-flash", name: "DeepSeek V4 Flash", flash: true },
      { id: "deepseek/deepseek-v4-pro", name: "DeepSeek V4 Pro" },
      { id: "google/gemini-2.5-flash", name: "Gemini 2.5 Flash", vision: true },
      { id: "google/gemini-2.5-pro", name: "Gemini 2.5 Pro", vision: true },
      { id: "meta-llama/llama-3.3-70b-instruct", name: "Llama 3.3 70B" },
      { id: "moonshotai/kimi-k2.6", name: "Kimi K2.6" },
    ],
  },

  // ===== OpenAI =====
  {
    name: "OpenAI",
    slug: "openai",
    baseUrls: [
      { label: "官方", url: "https://api.openai.com/v1" },
    ],
    suggestedModels: [
      { id: "gpt-4.1-mini", name: "GPT-4.1 Mini", flash: true },
      { id: "gpt-4.1", name: "GPT-4.1" },
      { id: "gpt-4o-mini", name: "GPT-4o Mini", vision: true },
      { id: "gpt-4o", name: "GPT-4o", vision: true },
      { id: "o4-mini", name: "O4 Mini" },
    ],
  },
];