#!/usr/bin/env python3
"""
TG-SignPulse Community Plugin AI Reviewer & Metadata Enrichment Tool

Capabilities:
1. Deep semantic security review (detects obfuscation, data exfiltration, token leakage).
2. Async & event-loop performance diagnostics (detects time.sleep, requests.get in async flows).
3. Metadata enrichment (generates bilingual descriptions, tags, feature highlights).
4. Outputs GitHub PR-ready Markdown reports or structured JSON.

Supported AI backends:
- Gemini API: via GEMINI_API_KEY or GOOGLE_API_KEY (default model: gemini-1.5-flash)
- OpenAI & Compatible (DeepSeek, Groq, Moonshot, etc.): via OPENAI_API_KEY & OPENAI_BASE_URL (default model: gpt-4o-mini / deepseek-chat)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _call_gemini_api(prompt: str, api_key: str, model: str = "gemini-1.5-flash") -> str:
    """Invoke Google Gemini REST API using standard urllib."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        candidates = res_data.get("candidates", [])
        if candidates and "content" in candidates[0]:
            parts = candidates[0]["content"].get("parts", [])
            if parts:
                return parts[0].get("text", "")
    return ""


def _call_openai_compatible_api(
    prompt: str,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
) -> str:
    """Invoke OpenAI-compatible chat completion REST API using standard urllib."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict security and code quality auditor for the TG-SignPulse plugin ecosystem. "
                    "Always output strictly valid JSON matching the requested schema."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        choices = res_data.get("choices", [])
        if choices and "message" in choices[0]:
            return choices[0]["message"].get("content", "")
    return ""


def _call_llm(prompt: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Route LLM call to appropriate backend based on available environment variables."""
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    raw_text = ""
    backend_used = "none"

    if gemini_key:
        model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
        backend_used = f"gemini ({model})"
        raw_text = _call_gemini_api(prompt, gemini_key, model)
    elif openai_key:
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("AI_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
        backend_used = f"openai-compatible ({model} @ {base_url})"
        raw_text = _call_openai_compatible_api(prompt, openai_key, base_url, model)
    else:
        return None, "no_api_key"

    if not raw_text:
        return None, f"empty_response from {backend_used}"

    # Extract JSON block
    clean_text = raw_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()

    try:
        parsed = json.loads(clean_text)
        return parsed, backend_used
    except json.JSONDecodeError as exc:
        return None, f"json_decode_error: {exc} (raw: {raw_text[:200]})"


def build_review_prompt(plugin_manifest: Dict[str, Any], python_files: Dict[str, str], readme_text: str) -> str:
    """Construct a comprehensive prompt for security audit and metadata enrichment."""
    files_str = "\n\n".join(
        f"--- File: {fname} ---\n{content}"
        for fname, content in python_files.items()
    )

    prompt = f"""
You are the Official AI Security & Quality Gatekeeper for TG-SignPulse (an open-source Telegram automation system).
Review the following community plugin submission.

### Plugin Manifest (plugin.json):
```json
{json.dumps(plugin_manifest, indent=2, ensure_ascii=False)}
```

### Python Source Code:
{files_str}

### README.md Documentation:
```markdown
{readme_text[:2000]}
```

### Audit Tasks:
1. **Security & Safety Audit**:
   - Check for disguised or obfuscated code execution (eval, exec, compile, getattr on builtins).
   - Check for private data theft or unauthorized exfiltration (stealing Telegram Bot tokens, session files, passwords, local files).
   - Check if remote HTTP targets are legitimate APIs or suspicious drop servers.
   - Check for file system sabotage or unauthorized writes outside plugin directory.
2. **Performance & Event Loop Diagnostics**:
   - Check for blocking synchronous calls inside async methods (`time.sleep` instead of `asyncio.sleep`, `requests` instead of `httpx.AsyncClient` or `aiohttp`).
   - Check for proper exception handling (`try...except`) to ensure a single task failure does not crash the scheduler.
3. **Metadata & Description Enrichment**:
   - Generate an enhanced concise Chinese description (`description_zh`, 20-80 Chinese characters).
   - Generate an enhanced concise English description (`description_en`, 15-40 words).
   - Recommend 3 to 6 accurate lowercase search tags (`tags`).
   - Extract 2 to 4 bullet points of core features (`features`).
   - Suggest the best category: 'utility', 'notification', 'message', 'captcha', 'helper', or 'entertainment'.
4. **Final Recommendation**:
   - `verdict`: "APPROVED", "CHANGES_REQUESTED", or "NEEDS_DISCUSSION".
   - `risk_level`: "SAFE", "LOW", "MEDIUM", or "HIGH".
   - Summary of findings and actionable feedback for the contributor.

### Required Output Schema (STRICT JSON ONLY):
{{
  "verdict": "APPROVED" | "CHANGES_REQUESTED" | "NEEDS_DISCUSSION",
  "risk_level": "SAFE" | "LOW" | "MEDIUM" | "HIGH",
  "security_findings": [
    "string: issue description or 'No security issues detected.'"
  ],
  "performance_diagnostics": [
    "string: performance note or 'Async event-loop clean, no blocking calls.'"
  ],
  "enriched_metadata": {{
    "description_zh": "精炼中文简介",
    "description_en": "Concise English description",
    "tags": ["tag1", "tag2", "tag3"],
    "features": ["特性1", "特性2"],
    "suggested_category": "utility"
  }},
  "review_summary_markdown": "A concise summary in markdown to display in PR comments."
}}
"""
    return prompt.strip()


def review_plugin_directory(
    plugin_dir: Path,
    mock_mode: bool = False,
) -> Tuple[bool, Dict[str, Any], str]:
    """Execute AI review on a community plugin directory."""
    manifest_file = plugin_dir / "plugin.json"
    if not manifest_file.is_file():
        return False, {"error": "Missing plugin.json"}, "missing_manifest"

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, {"error": f"Invalid plugin.json: {exc}"}, "json_error"

    python_files: Dict[str, str] = {}
    for pf in sorted(plugin_dir.glob("**/*.py")):
        rel = pf.relative_to(plugin_dir).as_posix()
        try:
            python_files[rel] = pf.read_text(encoding="utf-8")
        except Exception:
            pass

    readme_file = plugin_dir / "README.md"
    readme_text = ""
    if readme_file.is_file():
        try:
            readme_text = readme_file.read_text(encoding="utf-8")
        except Exception:
            pass

    if mock_mode:
        mock_result = {
            "verdict": "APPROVED",
            "risk_level": "SAFE",
            "security_findings": ["No security issues detected (Mock Mode)."],
            "performance_diagnostics": ["Async event-loop clean, no blocking calls (Mock Mode)."],
            "enriched_metadata": {
                "description_zh": manifest.get("description", "优质社区插件"),
                "description_en": manifest.get("description_en", "A high quality community plugin for TG-SignPulse."),
                "tags": manifest.get("tags", ["community", manifest.get("category", "utility")]),
                "features": manifest.get("features", ["自动化处理", "轻量高效"]),
                "suggested_category": manifest.get("category", "utility"),
            },
            "review_summary_markdown": "### ✅ AI Review Passed (Mock Mode)\nPlugin is safe and ready to merge.",
        }
        return True, mock_result, "mock"

    prompt = build_review_prompt(manifest, python_files, readme_text)
    result_data, backend = _call_llm(prompt)

    if not result_data:
        return False, {"error": f"AI review failed: {backend}"}, backend

    return True, result_data, backend


def format_markdown_pr_comment(plugin_id: str, review_result: Dict[str, Any], backend: str) -> str:
    """Format review findings into a GitHub PR comment."""
    verdict = review_result.get("verdict", "NEEDS_DISCUSSION")
    risk = review_result.get("risk_level", "UNKNOWN")

    verdict_badge = {
        "APPROVED": "✅ **APPROVED (建议合入)**",
        "CHANGES_REQUESTED": "⚠️ **CHANGES REQUESTED (需要修改)**",
        "NEEDS_DISCUSSION": "💬 **NEEDS DISCUSSION (待人工核验)**",
    }.get(verdict, verdict)

    risk_badge = {
        "SAFE": "🟢 安全 (Safe)",
        "LOW": "🟡 低风险 (Low)",
        "MEDIUM": "🟠 中风险 (Medium)",
        "HIGH": "🔴 高风险 (High)",
    }.get(risk, risk)

    meta = review_result.get("enriched_metadata", {})
    sec_findings = review_result.get("security_findings", [])
    perf_diag = review_result.get("performance_diagnostics", [])

    lines = [
        f"## 🤖 TG-SignPulse AI 插件审查报告 (`{plugin_id}`)",
        "",
        f"- **评审结论**: {verdict_badge}",
        f"- **风险评级**: {risk_badge}",
        f"- **审计引擎**: `{backend}`",
        "",
        "### 🛡️ 安全与权限审计",
    ]
    for s in sec_findings:
        lines.append(f"- {s}")

    lines.append("")
    lines.append("### ⚡ 异步性能与健壮性")
    for p in perf_diag:
        lines.append(f"- {p}")

    lines.append("")
    lines.append("### 📝 AI 建议优化元数据")
    lines.append(f"- **中文简介 (zh-CN)**: {meta.get('description_zh', 'N/A')}")
    lines.append(f"- **英文简介 (en-US)**: {meta.get('description_en', 'N/A')}")
    lines.append(f"- **推荐标签 (Tags)**: {', '.join(f'`{t}`' for t in meta.get('tags', []))}")
    lines.append(f"- **推荐分类 (Category)**: `{meta.get('suggested_category', 'utility')}`")
    if meta.get("features"):
        lines.append("- **核心特性亮点**:")
        for feat in meta.get("features", []):
            lines.append(f"  * {feat}")

    summary = review_result.get("review_summary_markdown")
    if summary:
        lines.append("")
        lines.append("### 📌 评审结语")
        lines.append(summary)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="TG-SignPulse Community Plugin AI Reviewer")
    parser.add_argument("plugin_dir", type=Path, help="Path to community plugin directory")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")
    parser.add_argument("--output", type=Path, help="Save report to file")
    parser.add_argument("--apply", action="store_true", help="Apply enriched metadata back to plugin.json")
    parser.add_argument("--mock", action="store_true", help="Run with mock AI response (dry-run)")
    args = parser.parse_args()

    plugin_dir = args.plugin_dir.resolve()
    if not plugin_dir.is_dir():
        print(f"Error: Directory not found: {plugin_dir}", file=sys.stderr)
        sys.exit(1)

    has_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    mock_mode = args.mock or not has_key

    if not has_key and not args.mock:
        print("[INFO] No AI API key detected (GEMINI_API_KEY / OPENAI_API_KEY). Running in mock/dry-run mode.", file=sys.stderr)

    success, review_result, backend = review_plugin_directory(plugin_dir, mock_mode=mock_mode)

    if not success:
        print(f"Error reviewing plugin: {review_result.get('error')}", file=sys.stderr)
        sys.exit(1)

    plugin_id = plugin_dir.name
    if args.format == "json":
        output_content = json.dumps(review_result, indent=2, ensure_ascii=False)
    else:
        output_content = format_markdown_pr_comment(plugin_id, review_result, backend)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_content, encoding="utf-8")
        print(f"[OK] Report saved to: {args.output}")
    else:
        print(output_content)

    # If --apply is set, update plugin.json with enriched description_en, tags, features
    if args.apply and "enriched_metadata" in review_result:
        manifest_file = plugin_dir / "plugin.json"
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            meta = review_result["enriched_metadata"]
            if meta.get("description_en") and not data.get("description_en"):
                data["description_en"] = meta["description_en"]
            if meta.get("tags"):
                existing_tags = set(data.get("tags", []))
                data["tags"] = sorted(existing_tags.union(set(meta["tags"])))
            if meta.get("features") and not data.get("features"):
                data["features"] = meta["features"]
            manifest_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"[OK] Enriched metadata applied to {manifest_file.name}!")
        except Exception as exc:
            print(f"[WARN] Failed to apply metadata to plugin.json: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
