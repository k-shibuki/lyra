# ADR-0006: 8-Layer Security Model

## Date
2025-11-18

## Context

LLMを活用したシステムには固有のセキュリティリスクがある：

| リスク | 詳細 |
|--------|------|
| Prompt Injection | 悪意あるWebページがLLMの動作を操作 |
| Data Exfiltration | 収集したデータの意図しない漏洩 |
| Jailbreak | LLMの安全機能の回避 |
| 出力汚染 | 悪意ある内容がユーザーに到達 |

単一の防御層では不十分。攻撃者は1つの層を突破できても、複数の層を同時に突破することは困難。

## Decision

**8層の多層防御モデルを採用し、各層で独立したセキュリティチェックを実施する。**

### 8層モデル

```
[Input]
   │
   ▼
┌─────────────────────────────────┐
│ L1: Input Validation            │  ← 形式検証
├─────────────────────────────────┤
│ L2: URL Allowlist/Blocklist     │  ← アクセス制御
├─────────────────────────────────┤
│ L3: Content Pre-filter          │  ← 取得前フィルタ
├─────────────────────────────────┤
│ L4: Prompt Injection Detection  │  ← 注入検出
├─────────────────────────────────┤
│ L5: LLM Sandbox                 │  ← 実行隔離
├─────────────────────────────────┤
│ L6: Output Validation           │  ← 出力検証
├─────────────────────────────────┤
│ L7: Response Sanitization       │  ← 無害化
├─────────────────────────────────┤
│ L8: Audit Logging               │  ← 監査記録
└─────────────────────────────────┘
   │
   ▼
[Output]
```

### 各層の責務

#### L1: Input Validation
```python
def validate_input(request: MCPRequest) -> ValidationResult:
    # スキーマ検証
    validate_json_schema(request, TOOL_SCHEMAS[request.tool])
    # 長さ制限
    check_length_limits(request.params)
    # 文字種検証
    check_allowed_characters(request.params)
```

#### L2: URL Allowlist/Blocklist
```python
BLOCKLIST = ["malware.com", "phishing.example", ...]
ALLOWLIST_PATTERNS = [r".*\.edu$", r".*\.gov$", ...]

def check_url_access(url: str) -> bool:
    domain = extract_domain(url)
    if domain in BLOCKLIST:
        return False
    # ユーザー設定のallowlistがあれば適用
    return True
```

#### L3: Content Pre-filter
```python
def prefilter_content(html: str) -> str:
    # 危険なタグを除去
    html = remove_script_tags(html)
    html = remove_style_tags(html)
    # 極端に大きなコンテンツを拒否
    if len(html) > MAX_CONTENT_SIZE:
        raise ContentTooLargeError()
    return html
```

#### L4: Prompt Injection Detection
```python
INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"disregard (?:all|any) (?:prior|previous)",
    r"system:\s*you are",
    r"<\|im_start\|>",
]

def detect_injection(text: str) -> InjectionResult:
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return InjectionResult(detected=True, pattern=pattern)
    return InjectionResult(detected=False)
```

#### L5: LLM Sandbox
```python
# LLMの能力を制限
SANDBOX_CONFIG = {
    "max_tokens": 1000,
    "allowed_tools": [],  # ツール呼び出し禁止
    "system_prompt_locked": True,
}

async def sandboxed_generate(prompt: str) -> str:
    # 隔離された環境で実行
    return await ollama.generate(
        prompt=prompt,
        **SANDBOX_CONFIG
    )
```

#### L6: Output Validation
```python
def validate_output(output: LLMOutput) -> ValidationResult:
    # NLI結果が有効な値か
    if output.relation not in ["SUPPORTS", "REFUTES", "NEUTRAL"]:
        return ValidationResult(valid=False, reason="Invalid relation")
    # 信頼度が範囲内か
    if not 0 <= output.confidence <= 1:
        return ValidationResult(valid=False, reason="Invalid confidence")
    return ValidationResult(valid=True)
```

#### L7: Response Sanitization
```python
def sanitize_response(response: dict) -> dict:
    # ユーザーに返す前に無害化
    sanitized = deep_copy(response)
    # 内部情報を除去
    remove_internal_fields(sanitized)
    # HTMLエスケープ
    escape_html_in_strings(sanitized)
    return sanitized
```

#### L8: Audit Logging
```python
def audit_log(event: SecurityEvent) -> None:
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event.type,
        "layer": event.layer,
        "details": event.details,
        "request_id": event.request_id,
    }
    # 改ざん防止のためappend-only
    append_to_audit_log(log_entry)
```

## Consequences

### Positive
- **多層防御**: 1層突破でも残りが防御
- **独立性**: 各層が独立してテスト可能
- **可視性**: どの層で検出されたか明確
- **拡張性**: 新しい層の追加が容易

### Negative
- **パフォーマンス**: 8層すべてを通過するオーバーヘッド
- **複雑性**: 層間の整合性維持が必要
- **誤検知**: 厳格すぎると正当なコンテンツもブロック

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| 単一フィルタ | シンプル | 突破されると終わり | 却下 |
| 外部WAF | 専門的 | ローカル実行に不適 | 却下 |
| LLM自己防御のみ | 簡単 | 信頼性不十分 | 却下 |

## References
- `src/filter/llm_security.py` - L4/L5実装
- `src/mcp/response_sanitizer.py` - L7実装
- `src/filter/source_verification.py` - L2/L6実装
- OWASP LLM Top 10: https://owasp.org/www-project-top-10-for-large-language-model-applications/
