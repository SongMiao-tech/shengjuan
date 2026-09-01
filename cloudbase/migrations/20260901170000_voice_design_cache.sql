-- 音色设计缓存：同一句描述只付一次设计费（全局共享，跨用户复用）
-- 后端用 service_role 访问，不启用 RLS
CREATE TABLE IF NOT EXISTS public.voice_design_cache (
  prompt_hash text PRIMARY KEY,          -- 归一化描述的 sha256（前 32 位）
  prompt      text NOT NULL,              -- 原始描述，便于排查
  voice_id    text NOT NULL,              -- MiniMax ttv-voice-xxx
  provider    text NOT NULL DEFAULT 'minimax',
  created_at  timestamptz DEFAULT now(),
  use_count   integer NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_voice_design_cache_created ON public.voice_design_cache (created_at DESC);
COMMENT ON TABLE public.voice_design_cache IS '音色设计按描述哈希缓存，避免重复调用按次计费的设计接口';
