"""
RMD-TRA — config.py
Konfigurasi model LLM terpusat, dibaca dari env var.
Ganti provider/model cukup ubah .env, tanpa menyentuh kode agen.

LLM_PROVIDER=gemini (default) -> pakai Gemini via Vertex AI (google-adk native)
LLM_PROVIDER=glm              -> pakai GLM (Zhipu AI / Z.ai) via LiteLLM
"""
from __future__ import annotations
import os

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GLM_MODEL = os.getenv("GLM_MODEL", "zai/glm-5.2")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

if LLM_PROVIDER == "glm":
    from google.adk.models.lite_llm import LiteLlm

    # GLM free tier (glm-*-flash) punya rate limit ketat per detik. Pilar 5/3
    # menembak beberapa sub-agen sekaligus (paralel), jadi retry otomatis
    # dengan backoff diperlukan supaya tidak langsung gagal saat kena limit.
    # num_retries diteruskan LiteLlm ke litellm.acompletion() (retry bawaan litellm).
    AGENT_MODEL = LiteLlm(model=GLM_MODEL, num_retries=6, timeout=180)
    # Model string dipakai policy_server.py untuk panggilan litellm.completion langsung
    SEMANTIC_CHECK_MODEL = GLM_MODEL
else:
    AGENT_MODEL = GEMINI_MODEL
    SEMANTIC_CHECK_MODEL = GEMINI_MODEL
