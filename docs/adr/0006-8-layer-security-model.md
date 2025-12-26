# ADR-0006: 8-Layer Security Model

## Date
2025-11-18

## Context

LLM-based systems have unique security risks:

| Risk | Details |
|------|---------|
| Prompt Injection | Malicious web pages manipulate LLM behavior |
| Data Exfiltration | Unintended leakage of collected data |
| Jailbreak | Bypassing LLM safety features |
| Output Pollution | Malicious content reaching users |

A single defense layer is insufficient. Even if an attacker breaches one layer, breaching multiple layers simultaneously is difficult.

## Decision

**Adopt an 8-layer defense-in-depth model with independent security checks at each layer.**

### 8-Layer Model

```
[Input]
   │
   ▼
┌─────────────────────────────────┐
│ L1: Input Validation            │  ← Format validation
├─────────────────────────────────┤
│ L2: URL Allowlist/Blocklist     │  ← Access control
├─────────────────────────────────┤
│ L3: Content Pre-filter          │  ← Pre-fetch filtering
├─────────────────────────────────┤
│ L4: Prompt Injection Detection  │  ← Injection detection
├─────────────────────────────────┤
│ L5: LLM Sandbox                 │  ← Execution isolation
├─────────────────────────────────┤
│ L6: Output Validation           │  ← Output verification
├─────────────────────────────────┤
│ L7: Response Sanitization       │  ← Neutralization
├─────────────────────────────────┤
│ L8: Audit Logging               │  ← Audit records
└─────────────────────────────────┘
   │
   ▼
[Output]
```

### Layer Responsibilities

#### L1: Input Validation
```python
def validate_input(request: MCPRequest) -> ValidationResult:
    # Schema validation
    validate_json_schema(request, TOOL_SCHEMAS[request.tool])
    # Length limits
    check_length_limits(request.params)
    # Character type validation
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
    # Apply user-configured allowlist if present
    return True
```

#### L3: Content Pre-filter
```python
def prefilter_content(html: str) -> str:
    # Remove dangerous tags
    html = remove_script_tags(html)
    html = remove_style_tags(html)
    # Reject extremely large content
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
# Limit LLM capabilities
SANDBOX_CONFIG = {
    "max_tokens": 1000,
    "allowed_tools": [],  # Tool invocation prohibited
    "system_prompt_locked": True,
}

async def sandboxed_generate(prompt: str) -> str:
    # Execute in isolated environment
    return await ollama.generate(
        prompt=prompt,
        **SANDBOX_CONFIG
    )
```

#### L6: Output Validation
```python
def validate_output(output: LLMOutput) -> ValidationResult:
    # Is NLI result a valid value?
    if output.relation not in ["SUPPORTS", "REFUTES", "NEUTRAL"]:
        return ValidationResult(valid=False, reason="Invalid relation")
    # Is confidence within range?
    if not 0 <= output.confidence <= 1:
        return ValidationResult(valid=False, reason="Invalid confidence")
    return ValidationResult(valid=True)
```

#### L7: Response Sanitization
```python
def sanitize_response(response: dict) -> dict:
    # Neutralize before returning to user
    sanitized = deep_copy(response)
    # Remove internal information
    remove_internal_fields(sanitized)
    # HTML escape
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
    # Append-only for tamper resistance
    append_to_audit_log(log_entry)
```

## Consequences

### Positive
- **Defense in Depth**: Remaining layers defend even if one is breached
- **Independence**: Each layer can be tested independently
- **Visibility**: Clear which layer detected the threat
- **Extensibility**: Easy to add new layers

### Negative
- **Performance**: Overhead of passing through all 8 layers
- **Complexity**: Inter-layer consistency maintenance required
- **False Positives**: Overly strict rules may block legitimate content

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Single Filter | Simple | Game over if breached | Rejected |
| External WAF | Specialized | Unsuitable for local execution | Rejected |
| LLM Self-defense Only | Easy | Insufficient reliability | Rejected |

## References
- `src/filter/llm_security.py` - L4/L5 implementation
- `src/mcp/response_sanitizer.py` - L7 implementation
- `src/filter/source_verification.py` - L2/L6 implementation
- OWASP LLM Top 10: https://owasp.org/www-project-top-10-for-large-language-model-applications/
