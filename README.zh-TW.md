[English](./README.md) | [繁體中文](./README.zh-TW.md)

# Project Aegis (AgentPay)

Project Aegis 是專為 Agentic AI（如 OpenClaw、NemoClaw、Claude Code、OpenHands）設計的**支付護欄與一次性交易協議**。它能讓 AI Agent 安全地處理金融交易，同時避免人類信用卡被無限制地暴露於風險之中。

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

## 3. 快速上手 — OpenClaw / NemoClaw / Claude Code / OpenHands

如果你使用 OpenClaw、NemoClaw、Claude Code、OpenHands 或任何支援 MCP 的 Agentic 框架，你可以在 2 分鐘內啟動 Aegis：

### 步驟一：安裝並啟動 MCP Server

```bash
# 複製儲存庫
git clone https://github.com/TPEmist/Project-Aegis.git
cd Project-Aegis

# 安裝依賴
uv sync --all-extras

# 啟動 MCP server
uv run python -m aegis.mcp_server
```

### 步驟二：連接你的 Agent

**OpenClaw：**
```bash
# 在 OpenClaw 中註冊 Aegis 為 MCP 工具
openclaw mcp add aegis -- uv run python -m aegis.mcp_server

# 或手動加入 OpenClaw MCP 設定檔（~/.openclaw/mcp_servers.json）
```
```json
{
  "aegis": {
    "command": "uv",
    "args": ["run", "python", "-m", "aegis.mcp_server"],
    "cwd": "/path/to/Project-Aegis",
    "env": {
      "AEGIS_ALLOWED_CATEGORIES": "[\"aws\", \"cloudflare\", \"openai\"]",
      "AEGIS_MAX_PER_TX": "100.0",
      "AEGIS_MAX_DAILY": "500.0"
    }
  }
}
```

**NemoClaw（NVIDIA 安全沙箱）：**

NemoClaw 將 OpenClaw agent 包裝在安全沙箱中。在你的 NemoClaw 沙箱內設定 Aegis：

```bash
# 連接到你的 NemoClaw 沙箱
nemoclaw my-assistant connect

# 在沙箱內註冊 Aegis MCP server
openclaw mcp add aegis -- uv run python -m aegis.mcp_server
```

> **注意：** NemoClaw 限制檔案存取權限。請確保 Project-Aegis 複製到 `/sandbox/` 內，以便 agent 能存取。`aegis_state.db` 會建立在沙箱的可寫入目錄中。

**Claude Code：**
```bash
claude mcp add aegis -- uv run python -m aegis.mcp_server
```

**OpenHands：** 加入你的 MCP 設定：
```json
{
  "mcpServers": {
    "aegis": {
      "command": "uv",
      "args": ["run", "python", "-m", "aegis.mcp_server"],
      "cwd": "/path/to/Project-Aegis"
    }
  }
}
```

### 步驟三：設定你的安全策略（環境變數）

```bash
export AEGIS_ALLOWED_CATEGORIES='["aws", "cloudflare", "openai", "github"]'
export AEGIS_MAX_PER_TX=100.0        # 單筆交易上限 $100
export AEGIS_MAX_DAILY=500.0         # 每日總預算上限 $500
export AEGIS_BLOCK_LOOPS=true        # 阻擋幻覺 / 重試迴圈
# 可選：export AEGIS_STRIPE_KEY=sk_live_...（Stripe 設定請見 §8）
```

### 步驟四：開始使用

你的 Agent 現在可以使用 `request_virtual_card` 工具。當它遇到付費牆時：

```
Agent：「我需要從 AWS 購買 $15 的 API 金鑰才能繼續。」
[Tool Call] request_virtual_card(amount=15.0, vendor="AWS", reasoning="Need API key for deployment")
[Aegis] ✅ 請求已核准。卡片已核發：****4242，有效期：12/25，金額：15.0
Agent：「購買成功，繼續工作流程。」
```

如果 Agent 產生幻覺或試圖超支：
```
Agent：「讓我再試一次購買運算資源……上次又失敗了。」
[Tool Call] request_virtual_card(amount=50.0, vendor="AWS", reasoning="failed again, retry loop")
[Aegis] ❌ 請求被拒絕。原因：偵測到幻覺或無限迴圈
```

---

## 4. 核心元件

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

## 5. 安全聲明
安全性是 Aegis 的第一優先。SDK **預設遮罩卡號**（如 `****-****-****-4242`），在回傳授權結果給 Agent 時不會暴露完整卡號。這能防止敏感支付資訊洩漏到 Agent 的對話紀錄、模型上下文視窗或持久化日誌中，確保只有執行環境能處理原始憑證。

## 6. The Vault Dashboard（監控面板）

The Vault 是你即時監控所有 Agent 支付活動的控制台。

### 啟動 Dashboard

```bash
cd Project-Aegis
uv run streamlit run dashboard/app.py
# Dashboard 會開啟在 http://localhost:8501
```

### Dashboard 版面配置

| 區域 | 說明 |
|---|---|
| **側邊欄：Max Daily Budget 滑桿** | 調整顯示用的預算上限（不影響後端策略 — 後端策略透過環境變數或 SDK 設定） |
| **Today's Spending** | 今日 Agent 累計消費金額 |
| **Remaining Budget** | 今日剩餘預算 |
| **Budget Utilization** | 預算使用率進度條 |
| **💳 Issued Seals & Activity** | 所有支付嘗試（核准 + 拒絕）的完整表格，含 seal ID、金額、供應商、狀態與時間戳 |
| **🚫 Rejected Summary** | 僅顯示被拒絕/阻擋的嘗試，方便快速審查 |

### 使用提示
- 點擊側邊欄的 **Refresh Data** 以獲取最新活動資料。
- Dashboard 讀取的是 `aegis_state.db` — 與 SDK 寫入的是同一個資料庫。同時運行兩者即可即時監控。
- 表格中的每一列對應 Agent 的一次 `request_virtual_card` 呼叫。

---

## 7. Python SDK 快速入門

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

---

## 8. 支付供應商：Stripe vs Mock

### 不使用 Stripe（預設 — Mock Provider）

預設情況下，Aegis 使用 `MockStripeProvider` 來模擬虛擬卡發行。適用於：
- **開發與測試** — 不涉及真實金錢
- **展示與評估** — 無需任何 API 金鑰即可體驗完整流程
- **黑客松** — 幾分鐘內就能跑出可運作的原型

Mock 卡在 Aegis 系統內完全可用（預算追蹤、用後即焚、護欄全部正常運作），但它們不是真實的支付工具。

```python
from aegis.providers.stripe_mock import MockStripeProvider

client = AegisClient(
    provider=MockStripeProvider(),  # 不需要 API 金鑰
    policy=policy
)
```

### 使用真實的 Stripe Issuing

若要透過 [Stripe Issuing](https://stripe.com/issuing) 核發**真實的虛擬信用卡**：

**前置條件：**
1. 具備已啟用 [Issuing](https://stripe.com/issuing) 的 Stripe 帳號（需申請審核通過）
2. 你的 Stripe 密鑰（`sk_live_...` 或 `sk_test_...`）

**方法 A：透過環境變數（適用 MCP Server）**
```bash
export AEGIS_STRIPE_KEY=sk_live_your_stripe_key_here
uv run python -m aegis.mcp_server
# MCP server 會自動使用 StripeIssuingProvider
```

**方法 B：透過 Python SDK**
```python
from aegis.providers.stripe_real import StripeIssuingProvider

client = AegisClient(
    provider=StripeIssuingProvider(api_key="sk_live_your_stripe_key_here"),
    policy=policy
)
```

**Stripe Issuing 的運作方式：**
- 建立真實的 Stripe 持卡人（`Aegis Agent`）
- 核發虛擬卡，消費限額與核准金額相符
- 僅回傳遮罩後的卡片資訊（末 4 碼）給 Agent
- 所有 Stripe 錯誤都會被捕獲並以拒絕原因回傳

> **備註：** Stripe Issuing 是 Stripe 的進階產品，需要申請通過。對於大多數開發與展示場景，Mock provider 已經足夠。
