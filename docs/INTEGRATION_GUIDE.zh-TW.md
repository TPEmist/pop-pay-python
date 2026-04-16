[English](./INTEGRATION_GUIDE.md) | [中文](./INTEGRATION_GUIDE.zh-TW.md)

# Point One Percent 整合指南

> **給 Agent 開發者**，想要將 Point One Percent 作為財務中間層嵌入 Agentic 工作流程的實戰參考。
> 本指南涵蓋四種整合模式：**Claude Code（BYOC + CDP 注入）**、**Python SDK / gemini-cli**、**瀏覽器 Agent 中間層（Playwright / browser-use / Skyvern）**，以及 **OpenClaw/NemoClaw System Prompt 設定**。

---

## 1. Claude Code — 使用 CDP 注入的完整設定

本節說明在 **Claude Code**（駭客版 / BYOC）中使用 Point One Percent 的完整三元件設定流程。兩個 MCP 共用同一個 Chrome 實例：Playwright MCP 負責導航，Point One Percent MCP 則透過 CDP 將卡片憑證直接注入 DOM。使用者可以在瀏覽器視窗中即時觀看整個注入流程 — 原始卡號絕不進入 Claude 的上下文。

### 架構說明

```
Chrome (--remote-debugging-port=9222)
├── Playwright MCP  ──→ Agent 用於瀏覽導航
└── POP MCP         ──→ 透過 CDP 注入真實卡片
         │
         └── Claude Code Agent（只看到 ****-****-****-4242）
```

### 步驟 0 — 以 CDP 模式啟動 Chrome（每次工作階段開始前必須先執行）

**推薦 — 使用 `pop-launch`：**

```bash
pop-launch
```

`pop-launch` 已包含於 `pop-pay`。它會自動偵測你系統上的 Chrome，以正確的 CDP 旗標啟動，等待 port 就緒，並印出適合你機器的 `claude mcp add` 指令。執行 `pop-launch --help` 查看選項（`--port`、`--url`、`--print-mcp`）。

<details>
<summary>手動替代方案（若偏好自行啟動 Chrome）</summary>

```bash
# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-pop-profile

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-pop-profile
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
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-pop-profile'

# Linux
alias chrome-cdp='google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-pop-profile'
```

</details>

### 步驟 1a — 初始化加密金庫

卡片憑證儲存於 **AES-256-GCM 加密金庫**，不放在明文檔案中。執行一次完成設定：

```bash
pop-init-vault
```

程式會提示輸入卡號、CVV、到期日與帳單資料（輸入內容隱藏）。憑證加密存入 `~/.config/pop-pay/vault.enc`，MCP 伺服器啟動時自動解密 — 每次會話無需額外操作。

**通行碼模式**（更強 — 可防禦具備 shell 執行能力的 Agent）：

```bash
pop-init-vault --passphrase   # 一次性設定：從通行碼衍生加密金鑰
pop-unlock                     # 每次 MCP 伺服器會話前執行一次
```

`pop-unlock` 將衍生金鑰存入 OS 鑰匙圈，MCP 伺服器啟動時自動讀取 — 下次會話前才需再次輸入通行碼。

> **安全等級（由低至高）：**
> 明文 `.env` < 金庫，機器金鑰，原始碼安裝 < 金庫，機器金鑰，`pip install pop-pay` < 金庫＋通行碼 < Stripe Issuing（商業版，無本地憑證儲存）

### 步驟 1b — 設定策略（`.env`）

建立 `~/.config/pop-pay/.env`，**只放策略與非敏感設定** — 卡片憑證不在這裡：

```bash
# ── 消費策略 ──
POP_ALLOWED_CATEGORIES='["aws", "cloudflare", "openai", "github", "wikipedia", "donation"]'
POP_MAX_PER_TX=100.0
POP_MAX_DAILY=500.0
POP_BLOCK_LOOPS=true

# ── CDP 注入 ──
POP_AUTO_INJECT=true
POP_CDP_URL=http://localhost:9222

# ── 護欄模式："keyword"（預設）或 "llm" ──
# POP_GUARDRAIL_ENGINE=keyword

# ── 帳單資料（自動填入結帳頁的姓名、地址、電話欄位）──
# POP_BILLING_FIRST_NAME=Bob
# POP_BILLING_LAST_NAME=Smith
# POP_BILLING_EMAIL=bob@example.com
# POP_BILLING_PHONE_COUNTRY_CODE=US     # 選填：填入國碼下拉選單；本地號碼自動推算
# POP_BILLING_PHONE=+14155551234        # E.164 格式
# POP_BILLING_STREET="123 Main St"
# POP_BILLING_CITY="Redwood City"
# POP_BILLING_STATE=CA                  # 全名或縮寫，模糊比對
# POP_BILLING_COUNTRY=US                # ISO 碼或全名，模糊比對
# POP_BILLING_ZIP=94043

# ── 額外信任的支付處理商（內建清單已含 Stripe、Zoho、Square 等）──
# POP_ALLOWED_PAYMENT_PROCESSORS='["checkout.myprocessor.com"]'

# ── 自訂封鎖關鍵字（延伸內建清單）──
# POP_EXTRA_BLOCK_KEYWORDS=
```

> **修改 `.env` 後，請重新啟動 Agent 會話**（例如關閉並重新開啟 Claude Code）以使更改生效。MCP 伺服器在啟動時僅加載一次配置，不支援熱重載。

### 護欄模式設定

Point One Percent 預設使用 `keyword` 引擎 — 這是一個零成本、零相依性的檢查機制，可攔截明顯的幻覺迴圈與提示注入語句。對於正式環境或高價值工作流程，可切換至 `llm` 雙層模式：先跑 Layer 1 keyword 引擎（快速、無 API 費用），通過後才進入 Layer 2 LLM 語意評估。僅在需要超越關鍵字比對的語意推理檢查時使用。

| | `keyword`（預設） | `llm` |
|---|---|---|
| **運作方式** | 攔截 `reasoning` 字串中含有可疑關鍵字的請求（如 "retry"、"failed again"、"ignore previous instructions"） | 雙層模式：先跑 Layer 1 keyword 引擎（快速、無 API 費用），通過後才進入 Layer 2 LLM 語意評估 |
| **攔截範圍** | 明顯的迴圈、幻覺語句、提示注入嘗試 | 細微的偏題採購、邏輯矛盾、關鍵字比對無法捕捉的違規行為 |
| **成本** | 零 — 無 API 呼叫，即時完成 | Layer 1 免費；僅在通過 Layer 1 後才消耗一次 LLM 呼叫 |
| **相依性** | 無 | 任何相容 OpenAI 的端點 |
| **適用場景** | 開發階段、低風險工作流程、重視成本的環境 | 正式環境、高價值交易、不受信任的 Agent 管線 |

**LLM 模式：**

```bash
export POP_GUARDRAIL_ENGINE=llm

# 選項 A：OpenAI
export POP_LLM_API_KEY=sk-...
export POP_LLM_MODEL=gpt-4o-mini          # 預設

# 選項 B：透過 Ollama 使用本地模型（免費、私密）
export POP_LLM_BASE_URL=http://localhost:11434/v1
export POP_LLM_MODEL=llama3.2
# Ollama 的 POP_LLM_API_KEY 可設為任意非空字串

# 選項 C：任何相容 OpenAI 的端點（OpenRouter、vLLM、LM Studio...）
export POP_LLM_BASE_URL=https://openrouter.ai/api/v1
export POP_LLM_API_KEY=sk-or-...
export POP_LLM_MODEL=anthropic/claude-3-haiku
```

> **建議：** 開發期間先使用 `keyword`。進入正式環境、或 Agent 管線開始處理真實金額或不受信任的輸入時，再切換至 `llm`。

### 步驟 2 — 將 Point One Percent MCP 加入 Claude Code

```bash
pop-launch --print-mcp
```

複製印出的 `claude mcp add pop-pay -- ...` 指令並執行。該指令使用你 venv 中的 `sys.executable`，無論你如何安裝 pop-pay，都能正確運作。

```bash
claude mcp add pop-pay ... #複製 pop-launch 的輸出
```

> `--scope user`（選填）將設定存入 `~/.claude.json`——在所有 Claude Code session 中都能使用。若省略，則僅套用於目前專案。

### 步驟 3 — 將 Playwright MCP 加入 Claude Code

```bash
claude mcp add --scope user playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> **`--cdp-endpoint` 是必要的。** 它讓 Playwright MCP 連接到 Point One Percent 用來注入卡片的**同一個 Chrome**。若省略，Playwright 會啟動自己的獨立瀏覽器，Point One Percent 看不到你導航的頁面，注入會失敗並出現「找不到卡片欄位」的錯誤。**執行一次即永久生效。**

### `request_virtual_card` 參數

| 參數 | 必填 | 說明 |
|---|---|---|
| `requested_amount` | 是 | 交易金額，單位為美元。 |
| `target_vendor` | 是 | 購買的供應商或服務（例如 `"openai"`、`"Wikipedia"`）。必須符合 `POP_ALLOWED_CATEGORIES` 中的一個項目。 |
| `reasoning` | 是 | Agent 對於為何需要此次購買的說明。由護欄引擎評估。 |
| `page_url` | 否 | 目前結帳頁的 URL。用於交叉驗證供應商網域，偵測釣魚攻擊。使用 Playwright MCP 時，傳入 `page.url`。 |

> **網域驗證：** 提供 `page_url` 且 `target_vendor` 符合已知供應商（AWS、GitHub、Cloudflare、OpenAI、Stripe、Anthropic、Wikipedia 等）時，pop-pay 會比對頁面 URL 的網域與該供應商的預期網域。網域不符（可能是釣魚頁面）時，請求將自動被拒絕。

### 建議加入的 System Prompt

將以下區塊加入你的 Claude Code system prompt（或專案的 `CLAUDE.md`）。這會讓 Agent 在需要時自動啟動 Chrome，並正確傳遞 `page_url`：

```
pop-pay payment rules:
- Billing info and card credentials: NEVER ask the user — pop-pay auto-fills everything.
- Billing/contact page (no card fields visible): call request_purchaser_info(target_vendor, page_url)
- Payment page (card fields visible): call request_virtual_card(amount, vendor, reasoning, page_url)
- Always pass page_url. Never type card numbers or personal info manually. Never read .env files.
- Rejection → stop and report to user. pop-pay MCP unavailable → stop and tell user.
- CDP check: curl http://localhost:9222/json/version — if down, run pop-launch first.
```

### 完整工作流程

**一次性設定**（clone 後由人工執行一次）：

1. 建立 `~/.config/pop-pay/.env` → 填入卡片資訊與政策設定
2. `pop-launch --print-mcp` → 執行它印出的兩條 `claude mcp add` 指令

**每次工作階段**（若加入上方 System Prompt，Agent 會自動處理）：

1. Agent 確認 Chrome 是否在跑（`curl http://localhost:9222/json/version`）— 若未啟動，執行 `pop-launch`
2. 開啟 Claude Code → 兩個 MCP 自動連線
3. Agent 透過 Playwright MCP 導航到結帳頁，帶 `page_url` 呼叫 `request_virtual_card`
4. Point One Percent 將真實卡片注入表單 — Agent 只看到遮罩後的卡號
5. Agent 點擊送出；卡片用後即焚

### 第一次實測

兩個 MCP 連線後，在新的 Claude Code 對話中貼上以下 prompt：

> 請捐款 10 美元給 Wikipedia，網址 https://donate.wikimedia.org。選擇**信用卡**作為付款方式。使用 pop MCP 工具申請虛擬卡。填妥支付資料，但**請勿送出** — 我會確認後再決定是否提交。

> **注意：**「請勿送出」的指令僅供初次測試使用。一旦確認注入流程正常運作，請從 prompt 中移除，即可達到全自動支付模式——在你設定的 policy 範圍內，agent 無需人工介入即可完成完整的付款流程。

**預期流程：** Agent 導航 → 選擇 $10 → 點擊「Donate by credit/debit card」→ 呼叫 `request_virtual_card` → Point One Percent 透過 CDP 注入卡號與帳單資訊 → Agent 等待你確認。

> **如果請求被拒絕，顯示「Vendor not in allowed categories」：** 在 `.env` 的 `POP_ALLOWED_CATEGORIES` 中加入 `donation`，然後開啟新的 Claude Code session 即可（不需重新註冊 MCP — 新 session 會自動重啟 server 並重新讀取 `.env`）。

---

## 2. gemini-cli / Python 腳本整合

對於使用 `gemini-cli` 或直接 Python Agent 迴圈的自動化腳本，可以將 `PopClient` 直接作為支付中間層嵌入。

### 模式一：PopClient 作為腳本中間層

```python
import asyncio
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import GuardrailPolicy, PaymentIntent

async def run_automated_workflow():
    # 1. 在腳本開頭初始化 Point One Percent
    policy = GuardrailPolicy(
        allowed_categories=["SaaS", "API", "Cloud"],
        max_amount_per_tx=50.0,
        max_daily_budget=200.0,
        block_hallucination_loops=True
    )
    client = PopClient(
        provider=MockStripeProvider(),  # 正式環境換成 StripeIssuingProvider
        policy=policy,
        db_path="pop_state.db"
    )

    # 2. 需要付款時，透過 Point One Percent 進行申請
    intent = PaymentIntent(
        agent_id="gemini-script-001",
        requested_amount=15.0,
        target_vendor="openai",
        reasoning="補充 API 額度以繼續資料管線的執行。"
    )

    seal = await client.process_payment(intent)

    if seal.status == "Rejected":
        print(f"支付被阻擋：{seal.rejection_reason}")
        return  # 停止腳本 — 不要嘗試繞道

    print(f"已核准。Seal: {seal.seal_id} | 卡號：****-****-****-{seal.card_number[-4:]}")

    # 3. 使用 seal_id 執行交易（用後即焚機制啟動）
    result = await client.execute_payment(seal.seal_id, 15.0)
    print(f"執行結果：{result['status']}")

asyncio.run(run_automated_workflow())
```

### 模式二：LangChain Tool Call（適用於 gemini-cli 工具整合）

如果你的 `gemini-cli` 提示使用工具呼叫，可以將 Point One Percent 封裝為 LangChain `BaseTool`：

```python
from pop_pay.tools.langchain import PopPaymentTool
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import GuardrailPolicy

policy = GuardrailPolicy(
    allowed_categories=["SaaS", "API"],
    max_amount_per_tx=50.0,
    max_daily_budget=200.0,
    block_hallucination_loops=True
)
client = PopClient(MockStripeProvider(), policy)

# 在 Agent 工具清單中註冊
pop_tool = PopPaymentTool(client=client, agent_id="gemini-agent")

# 工具接受：requested_amount、target_vendor、reasoning
result = await pop_tool._arun(
    requested_amount=15.0,
    target_vendor="openai",
    reasoning="需要 API 額度以繼續處理使用者請求。"
)
print(result)
# → "Payment approved. Card Issued: ****-****-****-4242, Expiry: 03/27, ..."
```

### 模式三：LLM 護欄引擎

若要在 Python 腳本中直接使用 LLM 護欄引擎（例如搭配本地 Ollama 推理），可在建構 `PopClient` 時傳入 `LLMGuardrailEngine` 實例：

```python
from pop_pay.engine.llm_guardrails import LLMGuardrailEngine

llm_engine = LLMGuardrailEngine(
    base_url="http://localhost:11434/v1",  # Ollama 端點
    model="llama3.2",
    use_json_mode=False
)
client = PopClient(
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

### 第一次實測

執行內附的 SDK Demo，確認一切設定正確：

```bash
uv run python examples/e2e_demo.py
```

你應該會看到三個情境執行：核准的付款、超出預算的拒絕，以及幻覺迴圈的攔截 — 不需要瀏覽器或 API Key。若要同步驗證 LLM 護欄模式，執行：

```bash
uv run --extra llm python scripts/test_llm_guardrails.py
```

> **注意：**「請勿送出」的指令僅供初次測試使用。一旦確認注入流程正常運作，請從 prompt 中移除，即可達到全自動支付模式——在你設定的 policy 範圍內，agent 無需人工介入即可完成完整的付款流程。

---

## 3. 瀏覽器 Agent 中間層（Playwright / browser-use / Skyvern）

操作真實網站的瀏覽器 Agent 需要在填入支付表單之前，先攔截結帳流程並向 Point One Percent 申請虛擬卡。

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
                        │  request_virtual_card(amount, vendor, reasoning, page_url=page.url)
                        ▼
┌──────────────────────────────────────────────────────┐
│          Point One Percent（本函式庫）                 │
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
│  4. PopBrowserInjector 透過 CDP 連線至 Chrome       │
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
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import PaymentIntent, GuardrailPolicy

async def browser_agent_with_pop():
    # 1. 初始化 Point One Percent
    policy = GuardrailPolicy(
        allowed_categories=["Donation", "SaaS", "Wikipedia"],
        max_amount_per_tx=30.0,
        max_daily_budget=50.0
    )
    client = PopClient(MockStripeProvider(), policy, db_path="pop_state.db")

    # 2. 瀏覽器 Agent 偵測到結帳頁面，申請授權
    intent = PaymentIntent(
        agent_id="playwright-agent-001",
        requested_amount=25.0,
        target_vendor="Wikipedia",
        reasoning="我需要透過 $25 捐款支持開放知識。"
    )
    seal = await client.process_payment(intent)

    if seal.status.lower() == "rejected":
        print(f"支付被阻擋：{seal.rejection_reason}")
        return  # 瀏覽器 Agent 停止 — 不嘗試填入表單

    print(f"已核准。Seal: {seal.seal_id}")
    # Agent 的上下文只看到遮罩後的卡號 — 絕不是真實 PAN
    print(f"   Agent 日誌中的卡號：****-****-****-{seal.card_number[-4:]}")

    # 3. 可信任的本地程式將真實憑證填入瀏覽器
    #    （此程式碼跑在本地執行環境，不在 LLM 上下文中）
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://donate.wikimedia.org/")

        # 關鍵：使用 PopBrowserInjector — 真實卡片資訊從記憶體中的 VirtualSeal 注入，
        # 絕不從 DB 取得（DB 只儲存遮罩後的卡號）。
        from pop_pay.injector import PopBrowserInjector
        browser_injector = PopBrowserInjector(client.state_tracker)
        await browser_injector.inject_payment_info(
            seal_id=seal.seal_id,
            cdp_url="http://localhost:9222",
            card_number=seal.card_number or "",
            cvv=seal.cvv or "",
            expiration_date=seal.expiration_date or "",
        )
        await page.click("#submit-donation")

    # 4. 標記 Seal 為已使用（用後即焚機制）
    await client.execute_payment(seal.seal_id, 25.0)
    print("虛擬卡已銷毀。交易完成。")

asyncio.run(browser_agent_with_pop())
```

### 第一次實測

執行內附的 Playwright 範例，對真實 Wikipedia 捐款頁面進行完整流程測試：

```bash
uv run python examples/agent_vault_flow.py
```

腳本會導航至結帳頁、向 Point One Percent 申請虛擬卡、透過 CDP 注入卡片資訊，並印出遮罩後的卡號 — 原始 PAN 不會出現在任何輸出中。

> **注意：**「請勿送出」的指令僅供初次測試使用。一旦確認注入流程正常運作，請從 prompt 中移除，即可達到全自動支付模式——在你設定的 policy 範圍內，agent 無需人工介入即可完成完整的付款流程。

### 適用於 browser-use / Skyvern 的調整

如果你使用 `browser-use` 或 Skyvern（以更高層次的視覺推理運作），模式完全相同 — 在送出表單前攔截：

```python
# browser-use 整合的偽代碼
class POPCheckoutInterceptor:
    def __init__(self, pop_client: PopClient):
        self.client = pop_client

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
            raise PaymentBlockedError(f"Point One Percent 拒絕了：{seal.rejection_reason}")

        return seal  # 將 seal 傳回給 browser-use 完成結帳

    async def on_checkout_complete(self, seal_id: str, amount: float):
        """browser-use 成功送出表單後呼叫。"""
        await self.client.execute_payment(seal_id, amount)
```

---

## 4. OpenClaw / NemoClaw — 完整設定

pop-pay 是一個獨立運行在本機的 MCP 伺服器，負責守衛 Agent 的支付行為。對於 OpenClaw 用戶，ClawHub 上的「skill」是發現層與設定層，負責告訴你的 Agent 如何與本機的 pop-pay 伺服器溝通。你必須先安裝 `pop-pay` Python 套件，再透過 `openclaw` 加入 skill，Agent 才能取用支付工具。這樣的架構確保支付邏輯安全地在你的機器上執行，同時讓 Agent 能透過標準的工具呼叫介面發起付款請求。

### ClawHub Skill（最快設定方式）

pop-pay 已在 **ClawHub**（OpenClaw / NemoClaw 的 skill 市集）上架，可一鍵安裝。搜尋 Point One Percent 發布的 **"pop-pay"** skill。該 skill 內含 MCP 註冊、預設消費 policy，以及下方的 system prompt 片段——單次點擊即完成設定。

若偏好完全手動控制，請繼續閱讀下方的手動設定說明。

---

### 推薦的 System Prompt 片段

將以下區塊加入你的 OpenClaw 或 NemoClaw 身份設定檔（如 `IDENTITY.md` 或 Agent 設定中的 system prompt 欄位）：

```markdown
## 財務安全協議（必須遵守）

你正在「Point One Percent 支付護欄協議」下運行。以下規則**不可協商**：

1. **在嘗試任何購買、訂閱、捐款、API 額度加值或任何金融交易之前，
   你必須呼叫 `request_virtual_card` MCP 工具**以取得授權。

2. **絕對不可使用**儲存在你的上下文、記憶或檔案中的信用卡號碼、
   PAN 卡號或任何真實支付憑證。這些資訊從不提供給你。

3. **如果 `request_virtual_card` 回傳拒絕，立即停止支付流程。**
   不可以用不同的理由重試。請向使用者回報拒絕原因。

4. **如果你發現自己陷入迴圈**（對同一筆失敗交易重試超過一次），
   你必須停下來並請求人類介入，而非繼續嘗試。
```

---

### OpenClaw 設定

OpenClaw 原生支援 MCP，並以與 Claude Code 相同的方式讀取 `.env` 檔案。設定流程與 §1 幾乎完全一致。

**步驟 0 — 啟動帶有 CDP 的 Chrome**

與 §1 相同，使用 `pop-launch`：

```bash
pop-launch --print-mcp
```

**步驟 1 — 設定 `.env`**

與 §1 相同。OpenClaw 會從專案目錄、`~/.openclaw/.env` 或 `~/.openclaw/openclaw.json` 的 `env` 區塊讀取設定。建立 `~/.config/pop-pay/.env` 並填入你的憑證。

**步驟 2 — 註冊 Point One Percent MCP**

```bash
openclaw mcp add pop-pay -- /path/to/venv/bin/python -m pop_pay.mcp_server
```

> 執行 `pop-launch --print-mcp` 可取得包含正確 Python 路徑的完整指令。

或直接加入 `~/.openclaw/mcp_servers.json`：

```json
{
  "pop": {
    "command": "uv",
    "args": ["run", "--project", "/path/to/Point-One-Percent", "python", "-m", "pop_pay.mcp_server"]
  }
}
```

**步驟 3 — 註冊帶有 CDP endpoint 的 Playwright MCP**

OpenClaw 透過 ClawHub 支援 Playwright MCP。加上 `--cdp-endpoint` 旗標，確保兩個 MCP 共用同一個 Chrome 實例：

```bash
openclaw mcp add playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> 更新 `.env` 後，重啟 OpenClaw session 即可重新載入設定——不需要重新註冊 MCP。

---

### 支付流程

```
+------------------+     +----------------------+     +---------------------------+
| Agent 導航至     | --> | 顯示帳單表單          |     | 顯示支付表單              |
| 結帳頁面         |     | （姓名、地址欄位）     |     | （信用卡欄位）             |
+------------------+     +----------------------+     +---------------------------+
                                   |                              |
                       呼叫 request_purchaser_info()   呼叫 request_virtual_card()
                       （填入姓名、地址、Email）        - 自動掃描頁面，內建於請求中
                                   |                     - 透過 CDP 注入卡片
                                   v                              |
                            點擊「繼續 / 下一步」                  v
                                                         點擊「送出 / 確認訂單」
```

### 第一次實測

使用 Wikipedia 捐款頁面——流程簡單，無需登入帳號。

```bash
> Donate $10 to Wikipedia, with credit card, pay with pop-pay. Fill in the payment details, but **do not submit** — I will review and confirm before proceeding.
```

1. Agent 導航至 `https://donate.wikimedia.org`，選擇 $10，選擇「信用卡」，進入填寫付款資訊的頁面。

2. 在帳單資料頁，Agent 呼叫：
   ```
   request_purchaser_info(target_vendor="Wikipedia", page_url="...", reasoning="...")
   ```
   然後點擊「繼續」。

3. 在支付頁面，Agent 呼叫：
   ```
   request_virtual_card(requested_amount=10.0, target_vendor="Wikipedia", reasoning="...", page_url="...")
   ```
   pop-pay 自動掃描頁面是否有提示注入，確認後透過 CDP 注入卡片資料。

4. Agent 點擊送出。初次測試時，在 prompt 中加入 `「請勿送出表單」`，方便你在任何款項被扣款前先檢查已填入的欄位。

**預期流程：** Agent 導航 → 選擇 $10 → 進入卡片表單 → 呼叫 `request_virtual_card` → pop-pay 掃描頁面並透過 CDP 注入卡片 → Agent 等待確認。

---

### NemoClaw（NVIDIA OpenShell）設定

NemoClaw 將 OpenClaw 包裝在 **OpenShell** 安全沙箱中。與 Claude Code / OpenClaw 的主要差異：

1. **不使用 `.env` 檔案** — 憑證以「Providers」形式宣告在 YAML policy 檔中，並在執行時注入為環境變數。
2. **預設零出口（zero-egress）** — POP MCP server 的端點必須明確加入網路白名單。
3. **早期預覽** — 介面可能異動；請參閱 [NemoClaw 文件](https://docs.nvidia.com/nemoclaw/latest/) 取得最新資訊。

**步驟 0 — 在沙箱外啟動帶有 CDP 的 Chrome**

在連接沙箱前，先在 host 端執行 `pop-launch`：

```bash
pop-launch
```

**步驟 1 — 在沙箱內 clone 並安裝**

```bash
nemoclaw my-assistant connect
cd /sandbox
git clone https://github.com/100xPercent/pop-pay-python.git
cd pop-pay-python && uv sync --all-extras
```

**步驟 2 — 在 policy YAML 中以 Providers 宣告 POP 憑證**

在 `nemoclaw-blueprint/policies/openclaw-sandbox.yaml` 的 `providers` 區塊中加入：

```yaml
providers:
  - name: POP_BYOC_NUMBER
    value: "4111111111111111"
  - name: POP_BYOC_CVV
    value: "123"
  - name: POP_BYOC_EXP_MONTH
    value: "12"
  - name: POP_BYOC_EXP_YEAR
    value: "27"
  - name: POP_ALLOWED_CATEGORIES
    value: '["aws", "openai", "donation"]'
  - name: POP_MAX_PER_TX
    value: "100.0"
  - name: POP_MAX_DAILY
    value: "500.0"
  - name: POP_BLOCK_LOOPS
    value: "true"
```

**步驟 3 — 在網路 policy 中將 POP MCP server 加入白名單**

```yaml
network:
  egress:
    allow:
      - host: localhost
        port: 9222   # Chrome CDP
      - host: localhost
        port: 8000   # POP MCP server（如有調整請修改）
```

**步驟 4 — 在沙箱內註冊 MCP**

```bash
openclaw mcp add pop-pay -- /path/to/venv/bin/python -m pop_pay.mcp_server
openclaw mcp add playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> **NemoClaw 提示：** Point One Percent 的護欄在 NemoClaw 中特別有價值——零出口沙箱可防止大多數意外消費，而 POP 更在此之上提供語意 policy 執行與完整審計紀錄，這是 OpenShell 本身無法做到的。

### 第一次實測

Agent 設定完上方的 System Prompt 後，試著交派這個任務：

> 請捐款 10 美元給 Wikipedia，網址 https://donate.wikimedia.org。選擇**信用卡**作為付款方式。使用 pop MCP 工具申請虛擬卡。填妥支付資料，但**請勿送出** — 我會確認後再決定是否提交。

> **注意：**「請勿送出」的指令僅供初次測試使用。一旦確認注入流程正常運作，請從 prompt 中移除，即可達到全自動支付模式——在你設定的 policy 範圍內，agent 無需人工介入即可完成完整的付款流程。

如果護欄核准請求並且卡片資訊被注入表單，代表 Point One Percent 的端對端流程運作正常。

> **如果請求被拒絕，顯示「Vendor not in allowed categories」：** 在環境變數或 `mcp_servers.json` 的 `POP_ALLOWED_CATEGORIES` 中加入 `donation`，然後重啟 agent session。

---

## 延伸閱讀

- [README.zh-TW.md](../README.zh-TW.md) — 主要概述與快速上手（中文版）
- [§1 Claude Code](#1-claude-code--使用-cdp-注入的完整設定) — 完整 BYOC + CDP 注入設定（最常見）
- [§2 Python SDK / gemini-cli](#2-gemini-cli--python-腳本整合) — 直接嵌入 SDK 與 LangChain 工具模式
- [§3 瀏覽器 Agent](#3-瀏覽器-agent-中間層playwright--browser-use--skyvern) — Playwright / browser-use / Skyvern 整合
- [§4 OpenClaw / NemoClaw](#4-openclaw--nemoclaw--完整設定) — OpenClaw 與 NemoClaw 的完整 MCP + CDP 設定
- [examples/agent_vault_flow.py](../examples/agent_vault_flow.py) — 完整 Playwright 瀏覽器注入範例
- [examples/e2e_demo.py](../examples/e2e_demo.py) — 純 SDK 端對端展示（無瀏覽器）
- [CONTRIBUTING.md](../CONTRIBUTING.md) — 如何新增支付供應商或護欄引擎
