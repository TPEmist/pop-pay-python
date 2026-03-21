[English](./README.md) | [繁體中文](./README.zh-TW.md)

# Project Aegis (AgentPay)

Project Aegis 是專為 Agentic AI（如 Claude Code、OpenHands）設計的**支付護欄與一次性交易協議**。它能讓 AI Agent 安全地處理金融交易，同時避免人類信用卡被無限制地暴露於風險之中。

## 1. 問題背景
當 Agentic AI 在自動化工作流程中遭遇付費牆（如網域註冊、API 額度、運算資源擴展）時，通常被迫停下來等待人類介入。然而，直接將實體信用卡提供給 Agent 會引發「信任危機」：幻覺（hallucination）或無限迴圈可能導致信用卡被刷爆。

## 2. 安裝

```bash
# 僅核心功能（關鍵字護欄 + mock provider，零外部依賴）
pip install aegis-pay

# 加裝 LLM 語意護欄（支援 OpenAI、Ollama、vLLM、OpenRouter）
pip install aegis-pay[llm]

# 加裝 Stripe 虛擬卡發行
pip install aegis-pay[stripe]

# 加裝 LangChain 整合
pip install aegis-pay[langchain]

# 完整安裝（所有功能）
pip install aegis-pay[all]
```

## 3. 核心元件

### 🛡️ The Vault（金庫）
基於 **Streamlit** 與 **SQLite** (`aegis_state.db`) 的本地視覺化控制台。The Vault 讓人類可以：
- 即時監控所有已核發的 Seal 與 Agent 消費活動。
- 監控全域預算使用率。
- 審查來自語意護欄的拒絕紀錄。

### 📜 The Seal（封印）
內建執行機制的虛擬一次性支付憑證：
- **每日預算硬限制**：自動阻擋任何會超過預設每日消費上限的請求。
- **用後即焚攔截**：確保虛擬卡一旦被使用後立即失效，防止重播攻擊或未授權的重複扣款。

### 🧠 語意護欄（Semantic Guardrails）
Aegis 提供兩種意圖評估模式，防止 Agent 浪費資金：
1. **快速關鍵字攔截**（預設）：使用 `GuardrailEngine` 即時阻擋包含迴圈或幻覺相關關鍵字的請求（如「retry」、「failed again」、「ignore previous」）。零依賴、零成本。
2. **LLM 語意護欄引擎**：由 `LLMGuardrailEngine` 驅動，對 Agent 的推理進行深度語意分析，檢測無關購買或邏輯不一致。支援**任何 OpenAI 相容端點** — 包括透過 Ollama/vLLM 的本地模型，或 OpenAI、OpenRouter 等雲端服務。

## 4. 安全聲明
安全性是 Aegis 的第一優先。SDK **預設遮罩卡號**（如 `****-****-****-4242`），在回傳授權結果給 Agent 時不會暴露完整卡號。這能防止敏感支付資訊洩漏到 Agent 的對話紀錄、模型上下文視窗或持久化日誌中，確保只有執行環境能處理原始憑證。

## 5. 整合 Claude Code 與 OpenHands
Aegis 完整支援 **Model Context Protocol (MCP)**。你可以用一行指令將我們的護欄與發卡機制整合到你的 Agentic 工作流程中。

**啟動 MCP Server：**
```bash
# Claude Code
claude mcp add aegis -- uv run python -m aegis.mcp_server

# 或直接執行
uv run python -m aegis.mcp_server
```

**透過環境變數設定：**
```bash
export AEGIS_ALLOWED_CATEGORIES='["aws", "cloudflare", "openai"]'
export AEGIS_MAX_PER_TX=100.0
export AEGIS_MAX_DAILY=500.0
export AEGIS_BLOCK_LOOPS=true
# 可選：設定 AEGIS_STRIPE_KEY 以使用真實的 Stripe Issuing
```

**自動化購買範例：**
```
Claude：「我找到了所需的依賴，但該儲存庫需要一次性購買 $15 的 API 金鑰。」
使用者：「如有必要請繼續，你有 Aegis 授權。」
[Tool Call] request_virtual_card(amount=15.0, vendor="AWS", reasoning="Need API key for dependency installation")
[Aegis Vault] 請求已核准。卡片已核發：****4242，有效期：12/25...
Claude：「我已成功繞過付費牆，安裝已完成。」
```

## 6. Python SDK 快速入門
只需幾行程式碼即可將 Aegis 整合到你的 Python 或 LangChain 工作流程：

```python
from aegis.client import AegisClient
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.core.models import GuardrailPolicy

# 定義你的安全策略
policy = GuardrailPolicy(
    allowed_categories=["API", "Cloud", "SaaS"], 
    max_amount_per_tx=50.0, 
    max_daily_budget=200.0,
    block_hallucination_loops=True
)

# 使用僅關鍵字護欄初始化客戶端（預設）
client = AegisClient(
    provider=MockStripeProvider(), 
    policy=policy,
    db_path="aegis_state.db"
)

# 或使用本地模型的 LLM 護欄（例如 Ollama）
from aegis.engine.llm_guardrails import LLMGuardrailEngine

llm_engine = LLMGuardrailEngine(
    base_url="http://localhost:11434/v1",  # Ollama 端點
    model="llama3.2",
    use_json_mode=False
)
client = AegisClient(
    provider=MockStripeProvider(),
    policy=policy,
    engine=llm_engine
)

# 搭配 LangChain Tool 使用
from aegis.tools.langchain import AegisPaymentTool
tool = AegisPaymentTool(client=client, agent_id="agent-01")
```

### 支援的 LLM 供應商

| 供應商 | `base_url` | `model` |
|---|---|---|
| OpenAI（預設） | *（不需要）* | `gpt-4o-mini` |
| Ollama（本地） | `http://localhost:11434/v1` | `llama3.2` |
| vLLM / LM Studio | `http://localhost:8000/v1` | 你的模型名稱 |
| OpenRouter | `https://openrouter.ai/api/v1` | `anthropic/claude-3-haiku` |
| 任何 OpenAI 相容端點 | 你的端點 URL | 你的模型名稱 |
