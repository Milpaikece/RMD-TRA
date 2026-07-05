"""
RMD-TRA — policy_server.py
Hybrid Policy Server: Structural Gating + Semantic Gating (Context Hygiene)

Implementasi Day 5: Spec-Driven Production Grade Development
Referensi whitepaper hal. 30–35: PolicyService + tool_policy_engine pattern
"""

from __future__ import annotations

import asyncio
import os
import re
import yaml
from pathlib import Path
from typing import Any

from google.genai import Client
from litellm import completion as litellm_completion

from .config import GEMINI_MODEL, LLM_PROVIDER, SEMANTIC_CHECK_MODEL


# ---------------------------------------------------------------------------
# PolicyService — Structural + Semantic Gating
# ---------------------------------------------------------------------------
class PolicyService:
    """
    Intercepts agent tool calls sebelum dieksekusi.
    Layer 1 (Structural): cek YAML rules — deterministik, cepat.
    Layer 2 (Semantic): tanya Gemini — untuk kasus yang tidak bisa di-regex.
    """

    def __init__(self, role: str = "mahasiswa"):
        self.role = role
        self.env  = os.getenv("ENVIRONMENT", "localhost")
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        self.location   = os.getenv("GOOGLE_CLOUD_LOCATION", "us-east1")

        policy_path = Path(__file__).parent.parent / "policies" / "policies.yaml"
        with open(policy_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    # ── Layer 1: Structural Gating ───────────────────────────────────────────
    def is_tool_allowed(self, tool_name: str) -> tuple[bool, str]:
        """
        Memeriksa apakah tool diizinkan berdasarkan role dan environment.
        Returns: (allowed: bool, reason: str)
        """
        # Cek environment blocks
        env_cfg = self.config.get("environments", {}).get(self.env, {})
        if tool_name in env_cfg.get("blocked_tools", []):
            return False, f"Tool '{tool_name}' diblokir di lingkungan '{self.env}'"

        # Cek role permissions
        role_cfg = self.config.get("roles", {}).get(self.role, {})
        allowed = role_cfg.get("allowed_tools", [])
        blocked = role_cfg.get("blocked_tools", [])

        if tool_name in blocked:
            return False, f"Role '{self.role}' tidak memiliki akses ke tool '{tool_name}'"

        if "*" in allowed or tool_name in allowed:
            return True, "OK"

        return False, f"Tool '{tool_name}' tidak ada dalam daftar izin role '{self.role}'"

    # ── Layer 2: Semantic Gating ─────────────────────────────────────────────
    async def check_action_semantic(self, action_description: str) -> tuple[bool, str]:
        """
        Menggunakan Gemini untuk memeriksa apakah argumen tool mengandung
        data sensitif (PII, data riset internal) yang tidak boleh keluar.
        """
        try:
            prompt = (
                "Kamu adalah pengawas keamanan data riset akademik. "
                "Periksa apakah teks berikut mengandung informasi sensitif yang "
                "TIDAK boleh dikirim ke layanan eksternal, seperti: "
                "NIM mahasiswa, nilai akademik, data pribadi, API keys, atau "
                "dokumen internal yang belum dipublikasikan.\n\n"
                f"Teks yang diperiksa:\n{action_description}\n\n"
                "Jawab hanya dengan: AMAN atau PELANGGARAN"
            )

            if LLM_PROVIDER == "glm":
                response = await asyncio.to_thread(
                    litellm_completion,
                    model=SEMANTIC_CHECK_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    num_retries=6,
                    timeout=180,
                )
                result = response.choices[0].message.content.strip().upper()
            else:
                client = Client(
                    vertexai=True,
                    project=self.project_id,
                    location=self.location
                )
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt
                )
                result = response.text.strip().upper()

            if result.startswith("PELANGGARAN"):
                return False, "Semantic check: terdeteksi data sensitif dalam argumen tool"
            return True, "OK"
        except Exception:
            # Jika semantic check gagal, default ke AMAN (jangan blokir operasi normal)
            return True, "OK (semantic check skipped)"

    # ── Kombinasi: Full Policy Check ─────────────────────────────────────────
    async def validate_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any]
    ) -> tuple[bool, str]:
        """
        Entry point utama: jalankan structural check dulu, lalu semantic.
        """
        # Layer 1
        allowed, reason = self.is_tool_allowed(tool_name)
        if not allowed:
            return False, reason

        # Layer 2: hanya untuk tools yang menyentuh data eksternal
        external_tools = {"google_search", "generate_scopus_manuscript"}
        if tool_name in external_tools:
            args_str = str(tool_args)
            ok, sem_reason = await self.check_action_semantic(args_str)
            if not ok:
                return False, sem_reason

        return True, "OK"


# ---------------------------------------------------------------------------
# Context Hygiene — sanitize output sebelum dikembalikan ke pengguna
# ---------------------------------------------------------------------------
class ContextHygiene:
    """
    Membersihkan output agen dari data sensitif sebelum dikirim ke browser.
    Implementasi Day 5 whitepaper hal. 32–35.
    """

    def __init__(self):
        policy_path = Path(__file__).parent.parent / "policies" / "policies.yaml"
        with open(policy_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.patterns = config.get("context_hygiene", {}).get("sensitive_patterns", [])

    def sanitize(self, text: str) -> tuple[str, list[str]]:
        """
        Scan dan bersihkan teks output dari pola sensitif.
        Returns: (sanitized_text, list_of_violations_found)
        """
        violations = []
        result = text

        for rule in self.patterns:
            pattern = rule["pattern"]
            label   = rule["label"]
            action  = rule["action"]

            matches = re.findall(pattern, result, re.IGNORECASE)
            if not matches:
                continue

            violations.append(f"{label} ({len(matches)} kejadian)")

            if action == "mask":
                placeholder = f"[{label.upper().replace(' ', '_')}]"
                result = re.sub(pattern, placeholder, result, flags=re.IGNORECASE)
            elif action == "block":
                result = "[OUTPUT DIBLOKIR: terdeteksi data sangat sensitif]"
                break

        return result, violations
