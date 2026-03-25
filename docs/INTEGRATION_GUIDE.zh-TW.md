[English](./INTEGRATION_GUIDE.md) | [中文](./INTEGRATION_GUIDE.zh-TW.md)

# Aegis 整合指南

> **給 Agent 開發者**，想要將 Aegis 作為財務中間層嵌入 Agentic 工作流程的實戰參考。
> 本指南涵蓋四種整合模式：**Claude Code（BYOC + CDP 注入）**、**Python SDK / gemini-cli**、**瀏覽器 Agent 中間層（Playwright / browser-use / Skyvern）**，以及 **OpenClaw/NemoClaw System Prompt 設定**。

---

## 1. Claude Code — 使用 CDP 注入的完整設定

本節說明在 **Claude Code**（駭客版 / BYOC）中使用 Aegis 的完整三元件設定流程。兩個 MCP 共用同一個 Chrome 實例：Playwright MCP 負責導航，Aegis MCP 則透過 CDP 將卡片憑證直接注入 DOM。使用者可以在瀏覽器視窗中即時觀看整個注入流程 — 原始卡號絕不進入 Claude 的上下文。

### 架構說明

```
Chrome (--remote-debugging-port=9222)
├── Playwright MCP  ──→ Agent 用於瀏覽導航
└── Aegis MCP       ──→ 透過 CDP 注入真實卡片
         │
         └── Claude Code Agent（只看到 ****-****-****-4242）
```

### 步驟 0 — 以 CDP 模式啟動 Chrome（每次工作階段開始前必須先執行）

**推薦 — 使用 `aegis-launch`：**

```bash
aegis-launch
```

`aegis-launch` 已包含於 `aegis-pay`。它會自動偵測你系統上的 Chrome，以正確的 CDP 旗標啟動，等待 port 就緒，並印出適合你機器的 `claude mcp add` 指令。執行 `aegis-launch --help` 查看選項（`--port`、`--url`、`--print-mcp`）。

<details>
<summary>手動替代方案（若偏好自行啟動 Chrome）</summary>

```bash
# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-aegis-profile

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-aegis-profile
```

> **為什麼需要 `--user-data-dir`？** 若 Chrome 已在執行中，必須使用獨立的 Profile 目錄才能開啟一個新實例並啟用 CDP。若省略此參數，Chrome 會靜默地重用現有實例，CDP 將無法使用。

驗證 CDP 是否已啟動：

```bash
curl http://localhost:9222/json/version
# 應回傳含 "Browser"、"webSocketDebuggerUrl" 等欄位的 JSON 物件
```

**Shell alias**（加入 `~/.zshrc` 或 `~/.bashrc`）：

```bash
# macOS
alias chrome-cdp='"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-aegis-profile'

# Linux
alias chrome-cdp='google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-aegis-profile'
```

</details>

### 步驟 1 — 設定 `.env`

從範例檔複製並填入你的憑證：

```bash
cp .env.example .env
```

編輯 `.env`，至少設定以下項目：

```bash
AEGIS_BYOC_NUMBER=4111111111111111   # 你的真實卡號
AEGIS_BYOC_CVV=123
AEGIS_BYOC_EXPIRY=12/27
AEGIS_BYOC_NAME=Your Name

# 策略設定
AEGIS_ALLOWED_CATEGORIES=["aws", "cloudflare", "openai"]
AEGIS_MAX_PER_TX=100.0
AEGIS_MAX_DAILY=500.0
AEGIS_BLOCK_LOOPS=true

# 選填：帳單欄位（自動填入姓名、地址、電子郵件）
# AEGIS_BILLING_FIRST_NAME=John
# AEGIS_BILLING_LAST_NAME=Doe
# AEGIS_BILLING_STREET=123 Main St
# AEGIS_BILLING_ZIP=10001
# AEGIS_BILLING_EMAIL=john@example.com

# 護欄模式："keyword"（預設，零成本）或 "llm"（深度語意分析）
# 完整比較表與 LLM 設定選項請見下方「護欄模式設定」小節。
# AEGIS_GUARDRAIL_ENGINE=keyword
```

> **⚠️  修改 `.env` 後，請重新啟動 Agent 會話**（例如關閉並重新開啟 Claude Code）以使更改生效。MCP 伺服器在啟動時僅加載一次配置，不支援熱重載。

### 護欄模式設定

Aegis 預設使用 `keyword` 引擎 — 這是一個零成本、零相依性的檢查機制，可攔截明顯的幻覺迴圈與提示注入語句。對於正式環境或高價值工作流程，可切換至 `llm` 模式，對每筆支付的理由進行深度語意分析。

| | `keyword`（預設） | `llm` |
|---|---|---|
| **運作方式** | 攔截 `reasoning` 字串中含有可疑關鍵字的請求（如 "retry"、"failed again"、"ignore previous instructions"） | 將 Agent 的 `reasoning` 傳送給 LLM 進行深度語意分析 |
| **攔截範圍** | 明顯的迴圈、幻覺語句、提示注入嘗試 | 細微的偏題採購、邏輯矛盾、關鍵字比對無法捕捉的違規行為 |
| **成本** | 零 — 無 API 呼叫，即時完成 | 每次 `request_virtual_card` 呼叫消耗一次 LLM 呼叫 |
| **相依性** | 無 | 任何相容 OpenAI 的端點 |
| **適用場景** | 開發階段、低風險工作流程、重視成本的環境 | 正式環境、高價值交易、不受信任的 Agent 管線 |

**LLM 模式：**

```bash
export AEGIS_GUARDRAIL_ENGINE=llm

# 選項 A：OpenAI
export AEGIS_LLM_API_KEY=sk-...
export AEGIS_LLM_MODEL=gpt-4o-mini          # 預設

# 選項 B：透過 Ollama 使用本地模型（免費、私密）
export AEGIS_LLM_BASE_URL=http://localhost:11434/v1
export AEGIS_LLM_MODEL=llama3.2
# Ollama 的 AEGIS_LLM_API_KEY 可設為任意非空字串

# 選項 C：任何相容 OpenAI 的端點（OpenRouter、vLLM、LM Studio...）
export AEGIS_LLM_BASE_URL=https://openrouter.ai/api/v1
export AEGIS_LLM_API_KEY=sk-or-...
export AEGIS_LLM_MODEL=anthropic/claude-3-haiku
```

> **建議：** 開發期間先使用 `keyword`。進入正式環境、或 Agent 管線開始處理真實金額或不受信任的輸入時，再切換至 `llm`。

### 步驟 2 — 將 Aegis MCP 加入 Claude Code

**選項 A — 全域（推薦）：** 在任何工作目錄啟動 Claude Code 都能使用。

```bash
claude mcp add --scope global aegis -- uv run --project /path/to/Project-Aegis python -m aegis.mcp_server
```

**選項 B — 專案層級：** 僅在從 Project-Aegis 目錄啟動 Claude Code 時有效。

```bash
cd /path/to/Project-Aegis
claude mcp add aegis -- uv run --project . python -m aegis.mcp_server
```

> `--project` 旗標指定 `uv` 使用的目錄，確保 `.env` 與 `aegis_state.db` 正確解析。若希望 `request_virtual_card` 在所有 Claude Code 專案中都能使用，請選擇全域選項。

### 步驟 3 — 將 Playwright MCP 加入 Claude Code

```bash
claude mcp add --scope global playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> 這會將 Playwright MCP 連接到你在步驟 0 啟動的**同一個 Chrome 實例**。兩個 MCP 現在共用同一個瀏覽器視窗。使用 `--scope global` 確保 Playwright 與 Aegis 在任何 session 中都能一起使用。

### 建議加入的 System Prompt

將以下區塊加入你的 Claude Code system prompt（或專案的 `CLAUDE.md`）：

```
Payment rules:
- Only call request_virtual_card when you can see credit card input fields on the current page
- After approval, the system auto-fills the card — just click submit
- Never manually type any card number or CVV
- If request_virtual_card is rejected, do not retry — report to user
```

### 完整工作階段核查清單

1. `aegis-launch` — 啟動 Chrome CDP 並印出 `claude mcp add` 指令
2. 啟動 Claude Code — 兩個 MCP 會自動連線
   - 如果自上次會話以來修改了 `.env`，則必須重啟以使新配置生效
4. 給 Agent 指派一個涉及結帳頁面的任務
5. Agent 透過 Playwright MCP 導航，透過 Aegis MCP 呼叫 `request_virtual_card`
6. `AegisBrowserInjector` 透過 CDP 注入真實卡片 — Agent 只看到遮罩後的卡號
7. Agent 點擊送出；卡片在使用後立即銷毀

---

## 2. gemini-cli / Python 腳本整合

對於使用 `gemini-cli` 或直接 Python Agent 迴圈的自動化腳本，可以將 `AegisClient` 直接作為支付中間層嵌入。

### 模式一：AegisClient 作為腳本中間層

```python
import asyncio
from aegis.client import AegisClient
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.core.models import GuardrailPolicy, PaymentIntent

async def run_automated_workflow():
    # 1. 在腳本開頭初始化 Aegis
    policy = GuardrailPolicy(
        allowed_categories=["SaaS", "API", "Cloud"],
        max_amount_per_tx=50.0,
        max_daily_budget=200.0,
        block_hallucination_loops=True
    )
    client = AegisClient(
        provider=MockStripeProvider(),  # 正式環境換成 StripeIssuingProvider
        policy=policy,
        db_path="aegis_state.db"
    )

    # 2. 需要付款時，透過 Aegis 進行申請
    intent = PaymentIntent(
        agent_id="gemini-script-001",
        requested_amount=15.0,
        target_vendor="openai",
        reasoning="補充 API 額度以繼續資料管線的執行。"
    )

    seal = await client.process_payment(intent)

    if seal.status == "Rejected":
        print(f"🛑 支付被阻擋：{seal.rejection_reason}")
        return  # 停止腳本 — 不要嘗試繞道

    print(f"✅ 已核准。Seal: {seal.seal_id} | 卡號：****-****-****-{seal.card_number[-4:]}")

    # 3. 使用 seal_id 執行交易（用後即焚機制啟動）
    result = await client.execute_payment(seal.seal_id, 15.0)
    print(f"執行結果：{result['status']}")

asyncio.run(run_automated_workflow())
```

### 模式二：LangChain Tool Call（適用於 gemini-cli 工具整合）

如果你的 `gemini-cli` 提示使用工具呼叫，可以將 Aegis 封裝為 LangChain `BaseTool`：

```python
from aegis.tools.langchain import AegisPaymentTool
from aegis.client import AegisClient
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.core.models import GuardrailPolicy

policy = GuardrailPolicy(
    allowed_categories=["SaaS", "API"],
    max_amount_per_tx=50.0,
    max_daily_budget=200.0,
    block_hallucination_loops=True
)
client = AegisClient(MockStripeProvider(), policy)

# 在 Agent 工具清單中註冊
aegis_tool = AegisPaymentTool(client=client, agent_id="gemini-agent")

# 工具接受：requested_amount、target_vendor、reasoning
result = await aegis_tool._arun(
    requested_amount=15.0,
    target_vendor="openai",
    reasoning="需要 API 額度以繼續處理使用者請求。"
)
print(result)
# → "Payment approved. Card Issued: ****-****-****-4242, Expiry: 03/27, ..."
```

### 模式三：LLM 護欄引擎

若要在 Python 腳本中直接使用 LLM 護欄引擎（例如搭配本地 Ollama 推理），可在建構 `AegisClient` 時傳入 `LLMGuardrailEngine` 實例：

```python
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
```

支援的 LLM 供應商：

| 供應商 | `base_url` | `model` |
|---|---|---|
| OpenAI（預設） | *（不需填寫）* | `gpt-4o-mini` |
| Ollama（本地） | `http://localhost:11434/v1` | `llama3.2` |
| vLLM / LM Studio | `http://localhost:8000/v1` | 你的模型名稱 |
| OpenRouter | `https://openrouter.ai/api/v1` | `anthropic/claude-3-haiku` |
| 任何相容 OpenAI 的端點 | 你的端點 URL | 你的模型名稱 |

---

## 3. 瀏覽器 Agent 中間層（Playwright / browser-use / Skyvern）

操作真實網站的瀏覽器 Agent 需要在填入支付表單之前，先攔截結帳流程並向 Aegis 申請虛擬卡。

### 架構說明

```
┌──────────────────────────────────────────────────────┐
│                  Agent 協調器                         │
│  (OpenClaw / NemoClaw / 自訂 asyncio 迴圈)           │
└───────────────────────┬──────────────────────────────┘
                        │
          導航、找到結帳頁面
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│              瀏覽器 Agent 層                           │
│  (Playwright, browser-use, Skyvern)                  │
│                                                       │
│  1. 偵測到支付表單 / 付費牆                            │
│  2. 擷取：金額、供應商、上下文                          │
│  3. ─── 暫停導航 ────────────────────────────────────►│
└───────────────────────┬──────────────────────────────┘
                        │  request_virtual_card(amount, vendor, reasoning)
                        ▼
┌──────────────────────────────────────────────────────┐
│                 Aegis（本函式庫）                      │
│                                                       │
│  • GuardrailEngine：關鍵字 + 可選 LLM 語意審核         │
│  • 預算執行：每日上限 + 單筆上限                        │
│  • 核發 VirtualSeal：一次性虛擬卡，用後即焚             │
│  • 回傳：遮罩後的卡號 + seal_id                        │
└───────────────────────┬──────────────────────────────┘
                        │  Seal 核准
                        ▼
┌──────────────────────────────────────────────────────┐
│              瀏覽器 Agent 層（繼續）                   │
│                                                       │
│  4. AegisBrowserInjector 透過 CDP 連線至 Chrome       │
│     (--remote-debugging-port=9222)                   │
│  5. 穿透跨網域 Iframe（如 Stripe Elements）            │
│  6. 將真實卡片注入 DOM — 非透過 page.fill()            │
│     （原始卡號僅由可信任的本地程序處理）                 │
│  7. Agent 點擊送出（只看到遮罩後的卡號）                 │
│  8. execute_payment(seal_id) → 虛擬卡銷毀              │
└──────────────────────────────────────────────────────┘
```

### 真實實作範例（Playwright）

以下是基於 [`examples/agent_vault_flow.py`](../examples/agent_vault_flow.py) 的可運行實作：

```python
import asyncio
from playwright.async_api import async_playwright
from aegis.client import AegisClient
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.core.models import PaymentIntent, GuardrailPolicy

async def browser_agent_with_aegis():
    # 1. 初始化 Aegis
    policy = GuardrailPolicy(
        allowed_categories=["Donation", "SaaS", "Wikipedia"],
        max_amount_per_tx=30.0,
        max_daily_budget=50.0
    )
    client = AegisClient(MockStripeProvider(), policy, db_path="aegis_state.db")

    # 2. 瀏覽器 Agent 偵測到結帳頁面，申請授權
    intent = PaymentIntent(
        agent_id="playwright-agent-001",
        requested_amount=25.0,
        target_vendor="Wikipedia",
        reasoning="我需要透過 $25 捐款支持開放知識。"
    )
    seal = await client.process_payment(intent)

    if seal.status.lower() == "rejected":
        print(f"🛑 Aegis 阻擋了支付：{seal.rejection_reason}")
        return  # 瀏覽器 Agent 停止 — 不嘗試填入表單

    print(f"✅ Aegis 已核准。Seal: {seal.seal_id}")
    # Agent 的上下文只看到遮罩後的卡號 — 絕不是真實 PAN
    print(f"   Agent 日誌中的卡號：****-****-****-{seal.card_number[-4:]}")

    # 3. 可信任的本地程式將真實憑證填入瀏覽器
    #    （此程式碼跑在本地執行環境，不在 LLM 上下文中）
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://donate.wikimedia.org/")

        # 關鍵：真實卡片資訊從 DB 取得，絕不從 LLM 輸出讀取
        details = client.state_tracker.get_seal_details(seal.seal_id)

        await page.fill("#card_number", details["card_number"])
        await page.fill("#cvv", details["cvv"])
        await page.fill("#expiry", details["expiration_date"])
        await page.click("#submit-donation")

    # 4. 標記 Seal 為已使用（用後即焚機制）
    await client.execute_payment(seal.seal_id, 25.0)
    print("🔥 虛擬卡已銷毀。交易完成。")

asyncio.run(browser_agent_with_aegis())
```

### 適用於 browser-use / Skyvern 的調整

如果你使用 `browser-use` 或 Skyvern（以更高層次的視覺推理運作），模式完全相同 — 在送出表單前攔截：

```python
# browser-use 整合的偽代碼
class AegisCheckoutInterceptor:
    def __init__(self, aegis_client: AegisClient):
        self.client = aegis_client

    async def on_checkout_detected(self, amount: float, vendor: str, context: str):
        """當 browser-use 偵測到支付表單時呼叫。"""
        intent = PaymentIntent(
            agent_id="browser-use-agent",
            requested_amount=amount,
            target_vendor=vendor,
            reasoning=context  # browser-use 對於為何付款的視覺描述
        )
        seal = await self.client.process_payment(intent)

        if seal.status == "Rejected":
            raise PaymentBlockedError(f"Aegis 拒絕了：{seal.rejection_reason}")

        return seal  # 將 seal 傳回給 browser-use 完成結帳

    async def on_checkout_complete(self, seal_id: str, amount: float):
        """browser-use 成功送出表單後呼叫。"""
        await self.client.execute_payment(seal_id, amount)
```

---

## 4. OpenClaw / NemoClaw — System Prompt 設定

最重要的防護層在於 **System Prompt 層級**：明確指示 Agent 在執行任何支付動作之前，*必須*先呼叫 Aegis，而不是直接嘗試填入真實憑證。

### 推薦的 System Prompt 片段

將以下區塊加入你的 OpenClaw 或 NemoClaw 身份設定檔（如 `IDENTITY.md` 或 Agent 設定中的 system prompt 欄位）：

```markdown
## 財務安全協議（必須遵守）

你正在「Aegis 支付護欄協議」下運行。以下規則**不可協商**：

1. **在嘗試任何購買、訂閱、捐款、API 額度加值或任何金融交易之前，
   你必須呼叫 `request_virtual_card` MCP 工具**以取得授權。

2. **絕對不可使用**儲存在你的上下文、記憶或檔案中的信用卡號碼、
   PAN 卡號或任何真實支付憑證。這些資訊從不提供給你。

3. **如果 `request_virtual_card` 回傳拒絕，立即停止支付流程。**
   不可以用不同的理由重試。請向使用者回報拒絕原因。

4. **如果你發現自己陷入迴圈**（對同一筆失敗交易重試超過一次），
   你必須停下來並請求人類介入，而非繼續嘗試。

5. Aegis 回傳的卡號將是遮罩格式（如 `****-****-****-4242`）。
   **不可嘗試查找或還原完整卡號。**
```

### OpenClaw：註冊 Aegis 為 MCP 工具

```bash
openclaw mcp add aegis -- uv run python -m aegis.mcp_server
```

或加入 `~/.openclaw/mcp_servers.json`：

```json
{
  "aegis": {
    "command": "uv",
    "args": ["run", "python", "-m", "aegis.mcp_server"],
    "cwd": "/path/to/Project-Aegis",
    "env": {
      "AEGIS_ALLOWED_CATEGORIES": "[\"aws\", \"cloudflare\", \"openai\", \"github\"]",
      "AEGIS_MAX_PER_TX": "100.0",
      "AEGIS_MAX_DAILY": "500.0",
      "AEGIS_BLOCK_LOOPS": "true",
      "AEGIS_GUARDRAIL_ENGINE": "llm",
      "AEGIS_LLM_API_KEY": "sk-your-openai-api-key"
    }
  }
}
```

### NemoClaw（NVIDIA 安全沙箱）：特別注意事項

NemoClaw 的 `OpenShell` 運行時限制寫入存取範圍，僅允許 `/sandbox/` 與 `/tmp/`。

```bash
# 步驟一：在沙箱內複製 Aegis
nemoclaw my-assistant connect
cd /sandbox
git clone https://github.com/TPEmist/Project-Aegis.git
cd Project-Aegis && uv sync --all-extras

# 步驟二：連接沙箱後，在內部註冊 MCP server
openclaw mcp add aegis -- uv run python -m aegis.mcp_server

# 步驟三：設定環境變數（aegis_state.db 將寫入 /sandbox/Project-Aegis/）
export AEGIS_ALLOWED_CATEGORIES='["aws", "openai"]'
export AEGIS_MAX_PER_TX=50.0
export AEGIS_MAX_DAILY=200.0
# 護欄模式："keyword"（預設）或 "llm" — 設定選項請見 §1「護欄模式設定」
export AEGIS_GUARDRAIL_ENGINE=llm
export AEGIS_LLM_API_KEY=sk-your-openai-api-key
```

> **NemoClaw 提示：** 上方的 System Prompt 片段在 NemoClaw 情境中尤為關鍵，因為沙箱內的 Agent 擁有更廣泛的系統層級權限。Aegis 成為沙箱內的最後一道財務防線。

---

## 延伸閱讀

- [README.zh-TW.md](../README.zh-TW.md) — 主要概述與快速上手（繁體中文版）
- [§1 Claude Code](#1-claude-code--使用-cdp-注入的完整設定) — 完整 BYOC + CDP 注入設定（最常見）
- [§2 Python SDK / gemini-cli](#2-gemini-cli--python-腳本整合) — 直接嵌入 SDK 與 LangChain 工具模式
- [§3 瀏覽器 Agent](#3-瀏覽器-agent-中間層playwright--browser-use--skyvern) — Playwright / browser-use / Skyvern 整合
- [§4 OpenClaw / NemoClaw](#4-openclaw--nemoclaw--system-prompt-設定) — OpenClaw 與 NemoClaw 的 System Prompt 設定
- [examples/agent_vault_flow.py](../examples/agent_vault_flow.py) — 完整 Playwright 瀏覽器注入範例
- [examples/e2e_demo.py](../examples/e2e_demo.py) — 純 SDK 端對端展示（無瀏覽器）
- [CONTRIBUTING.md](../CONTRIBUTING.md) — 如何新增支付供應商或護欄引擎
