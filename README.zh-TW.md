[English](./README.md) | [中文](./README.zh-TW.md)

<p align="center">
    <picture>
        <img src="https://raw.githubusercontent.com/TPEmist/Point-One-Percent/main/project_banner.png" alt="Point One Percent (AgentPay)" width="800">
    </picture>
</p>

# Point One Percent - Agent Pay

> it only takes 0.1% of Hallucination to drain 100% of your wallet.

Point One Percent 是專為 Agentic AI（如 OpenClaw、NemoClaw、Claude Code、OpenHands）設計的**支付護欄與一次性交易協議**。它能讓 AI Agent 安全地處理金融交易，同時避免人類信用卡被無限制地暴露於風險之中。

## 1. 問題背景
當 Agentic AI 在自動化工作流程中遭遇付費牆（如網域註冊、API 額度、運算資源擴展）時，通常被迫停下來等待人類介入。然而，直接將實體信用卡提供給 Agent 會引發「信任危機」：幻覺（hallucination）或無限迴圈可能導致信用卡被刷爆。

## 2. 雙軌架構 (Dual Architecture)

Point One Percent 基於「雙軌架構」的願景設計，能從開源的本地實驗，輕易擴展至企業級的 AI 生產管線。

### 1. 駭客版 (BYOC + DOM Injection)
專為 OpenClaw、NemoClaw 等開源框架設計。Agent **永遠不會**拿到真實的信用卡號，只會看到經過遮罩的版本（如 `****-4242`）。當 Agent 成功導航到最後結帳頁面時，`PopBrowserInjector` 會透過 Chrome DevTools Protocol (CDP) 直接連線至活躍的 Chromium 瀏覽器，穿透並遍歷所有跨網域 Iframe（如 Stripe Elements），精準將真實的信用卡憑證注入底層的 DOM 表單元素。此機制能提供 **100% 免疫 Prompt Injection** 與幻覺提取的防護。讓你安心在本地環境使用自己的信用卡 (Bring Your Own Card, BYOC)。

### 2. 企業版 (Stripe Issuing)
更廣泛 Agentic SaaS 生態系的「北極星」。Point One Percent 證明了它具備真實世界所需的企業級擴展能力，能完美介接合規的金融基礎設施。這非常適合想要建立「Agentic Visa」服務的平台，能透過 Stripe API 替雲端的 AI 艦隊動態發行真實、拋棄式的虛擬信用卡 (VCC)。

---

## 3. 生態系定位：Point One Percent + 瀏覽器 Agent = 所向無敵

現代 Agentic 工作流程需要兩種互補的能力。Point One Percent 負責其中之一，並把它做到極致。

### Point One Percent 是什麼 — 以及不是什麼

**Point One Percent 是 Agent 的財務大腦與保險箱。** 它負責：
- 評估某筆購買是否*應該*發生（語意護欄審核）
- 執行硬性預算限制（每日上限、單筆上限）
- 核發一次性虛擬卡，確保真實信用卡資訊絕不外洩
- 完整保存每一筆支付嘗試的稽核紀錄

**Point One Percent 不做以下事情：**
- 瀏覽網站或操作 DOM 元素
- 破解 CAPTCHA 或繞過反機器人機制

那些是瀏覽器 Agent 的工作。

### 協作交接：Point One Percent 如何與瀏覽器 Agent 協同運作

真正的威力來自 Point One Percent 與瀏覽器自動化 Agent（如 OpenHands、browser-use、Skyvern）的配合。這是一種清晰的職責分工：

```
1. [瀏覽器 Agent]  導航至網站，抓取商品資訊，到達結帳頁面。
        │
        │  （遇到付費牆 / 支付表單）
        ▼
2. [瀏覽器 Agent → POP MCP]  呼叫 request_virtual_card(amount, vendor, reasoning)
        │
        │  （Point One Percent 評估：預算OK？供應商已核准？沒有幻覺？）
        ▼
3. [POP]  核發一次性虛擬卡（Stripe 模式）或模擬卡（開發模式）
            向 Agent 回傳遮罩後的卡號。完整卡號僅透過
            可信任的本地執行環境注入 — 絕不進入 LLM 的上下文。
        │
        ▼
4. [POP]  透過 CDP 將真實憑證注入結帳表單。
            Agent 僅收到交易確認通知 — 不含任何卡片資訊。
        │
        ▼
5. [瀏覽器 Agent]  點擊送出按鈕完成交易。
        │
        ▼
6. [The Vault]  Dashboard 記錄交易。虛擬卡立即銷毀。
```

### 支援的整合方式

| 整合路徑 | 適用框架 |
|---|---|
| **MCP Tool** | Claude Code、OpenClaw、NemoClaw、OpenHands，以及任何 MCP 相容的 Host |
| **Python SDK** | 自訂 Playwright、browser-use、Skyvern、Selenium、gemini-cli |

> **Claude Code** 支援完整的 CDP 注入 — 卡片自動填入瀏覽器表單，Agent 永遠看不到原始卡號。詳細設定請參閱 **[整合指南](./docs/INTEGRATION_GUIDE.zh-TW.md)**。

---

## 4. 安裝

```bash
# 僅核心功能（關鍵字護欄 + mock provider，零外部依賴）
pip install pop-pay

# 加裝 LLM 語意護欄（支援 OpenAI、Ollama、vLLM、OpenRouter）
pip install pop-pay[llm]

# 加裝 Stripe 虛擬卡發行
pip install pop-pay[stripe]

# 加裝 LangChain 整合
pip install pop-pay[langchain]

# 完整安裝（所有功能）
pip install pop-pay[all]
```

## 5. 快速上手 — OpenClaw / NemoClaw / Claude Code / OpenHands

如果你使用 OpenClaw、NemoClaw、Claude Code、OpenHands 或任何支援 MCP 的 Agentic 框架，你可以在 2 分鐘內啟動 Point One Percent：

### 步驟一：安裝並啟動 MCP Server

```bash
pip install pop-pay[mcp]
python -m pop_pay.mcp_server
```

> **貢獻者 / 本地開發？** 請參閱 [CONTRIBUTING.md](./CONTRIBUTING.md) 的 `git clone` + `uv sync` 流程。

### 步驟二：連接你的 Agent

依你使用的平台，前往對應的完整設定指南：

| 平台 | 設定指南 |
|---|---|
| **Claude Code**（BYOC + CDP 注入，推薦） | [整合指南 §1](./docs/INTEGRATION_GUIDE.zh-TW.md#1-claude-code--使用-cdp-注入的完整設定) |
| **Python 腳本 / gemini-cli** | [整合指南 §2](./docs/INTEGRATION_GUIDE.zh-TW.md#2-gemini-cli--python-腳本整合) |
| **Playwright / browser-use / Skyvern** | [整合指南 §3](./docs/INTEGRATION_GUIDE.zh-TW.md#3-瀏覽器-agent-中間層playwright--browser-use--skyvern) |
| **OpenClaw / NemoClaw** | [整合指南 §4](./docs/INTEGRATION_GUIDE.zh-TW.md#4-openclaw--nemoclaw--system-prompt-設定) |
| **OpenHands** | 將 `python -m pop_pay.mcp_server` 加入你的 `mcpServers` 設定 |

### 步驟三：設定你的安全策略（環境變數）

```bash
export POP_ALLOWED_CATEGORIES='["aws", "cloudflare", "openai", "github"]'
export POP_MAX_PER_TX=100.0        # 單筆交易上限 $100
export POP_MAX_DAILY=500.0         # 每日總預算上限 $500
export POP_BLOCK_LOOPS=true        # 阻擋幻覺 / 重試迴圈
# 可選：export POP_STRIPE_KEY=sk_live_...（Stripe 設定請見 §8）
```

> **修改 `.env` 後，請重新啟動 Agent 會話**（例如關閉並重新開啟 Claude Code）以使更改生效。MCP 伺服器在啟動時僅加載一次配置，不支援熱重載。

#### 護欄模式：關鍵字 vs LLM

Point One Percent 提供兩種護欄引擎，透過一個環境變數切換：

| | `keyword`（預設） | `llm` |
|---|---|---|
| **運作方式** | 掃描 Agent 的 `reasoning` 字串，比對可疑關鍵字（如「retry」、「failed again」、「ignore previous instructions」） | 將 Agent 的 `reasoning` 送給 LLM 進行深度語意分析 |
| **能攔截的威脅** | 明顯的迴圈、幻覺語句、Prompt Injection 嘗試 | 關鍵字比對會漏掉的細微誤用：不相關的購買、邏輯矛盾、政策違反 |
| **成本** | 零 — 無 API 呼叫，即時回應 | 每次 `request_virtual_card` 一次 LLM 呼叫 |
| **依賴** | 無 | 任何 OpenAI 相容端點 |
| **適合場景** | 開發測試、低風險工作流、成本敏感的設定 | 正式上線、高價值交易、不完全信任的 Agent 管線 |

> **提示**：關鍵字模式無需額外設定即可使用。若要啟用 LLM 模式，請參閱[整合指南 §1 護欄模式設定](./docs/INTEGRATION_GUIDE.zh-TW.md#護欄模式設定)的完整設定說明。

### 步驟四：開始使用

你的 Agent 現在可以使用 `request_virtual_card` 工具。當它遇到付費牆時：

```
Agent：「我需要從 AWS 購買 $15 的 API 金鑰才能繼續。」
[Tool Call] request_virtual_card(amount=15.0, vendor="AWS", reasoning="Need API key for deployment")
[POP] 請求已核准。卡片已核發：****4242，有效期：12/25，金額：15.0
Agent：「購買成功，繼續工作流程。」
```

如果 Agent 產生幻覺或試圖超支：
```
Agent：「讓我再試一次購買運算資源……上次又失敗了。」
[Tool Call] request_virtual_card(amount=50.0, vendor="AWS", reasoning="failed again, retry loop")
[POP] 請求被拒絕。原因：偵測到幻覺或無限迴圈
```

---

## 6. 核心元件

### The Vault（金庫）
基於 **Streamlit** 與 **SQLite** (`pop_state.db`) 的本地視覺化控制台。The Vault 讓人類可以：
- 即時監控所有已核發的 Seal 與 Agent 消費活動。
- 監控全域預算使用率。
- 審查來自語意護欄的拒絕紀錄。

### The Seal（封印）
內建執行機制的虛擬一次性支付憑證：
- **每日預算硬限制**：自動阻擋任何會超過預設每日消費上限的請求。
- **用後即焚攔截**：確保虛擬卡一旦被使用後立即失效，防止重播攻擊或未授權的重複扣款。

### 語意護欄（Semantic Guardrails）
Point One Percent 提供兩種意圖評估模式，皆透過 `.env` 中的 `POP_GUARDRAIL_ENGINE` 控制（完整設定請見 [§5 步驟三](#步驟三設定你的安全策略環境變數)）。

1. **關鍵字模式**（`POP_GUARDRAIL_ENGINE=keyword`，**預設**）：`GuardrailEngine` 掃描 Agent 的 `reasoning` 字串，攔截與迴圈或幻覺相關的可疑詞彙（如 `"retry"`、`"failed again"`、`"ignore previous"`）。零依賴、零延遲、零成本。建議所有部署從此模式開始。

2. **LLM 模式**（`POP_GUARDRAIL_ENGINE=llm`）：`LLMGuardrailEngine` 將 Agent 的 `reasoning` 送往 LLM 進行深度語意分析，能捕捉關鍵字比對無法識別的細微濫用行為 — 例如離題購買或邏輯前後矛盾的理由。支援**任何 OpenAI 相容端點**：OpenAI、Ollama（本地）、vLLM、OpenRouter 等。

## 7. 安全聲明
安全性是 Point One Percent 的第一優先。SDK **預設遮罩卡號**（如 `****-****-****-4242`），在回傳授權結果給 Agent 時不會暴露完整卡號。這能防止敏感支付資訊洩漏到 Agent 的對話紀錄、模型上下文視窗或持久化日誌中，確保只有執行環境能處理原始憑證。

## 8. The Vault Dashboard（監控面板）

The Vault 是你即時監控所有 Agent 支付活動的控制台。

### 啟動 Dashboard

```bash
cd Point-One-Percent
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
| **Issued Seals & Activity** | 所有支付嘗試（核准 + 拒絕）的完整表格，含 seal ID、金額、供應商、狀態與時間戳 |
| **Rejected Summary** | 僅顯示被拒絕/阻擋的嘗試，方便快速審查 |

### 使用提示
- 點擊側邊欄的 **Refresh Data** 以獲取最新活動資料。
- Dashboard 讀取的是 `pop_state.db` — 與 SDK 寫入的是同一個資料庫。同時運行兩者即可即時監控。
- 表格中的每一列對應 Agent 的一次 `request_virtual_card` 呼叫。

---

## 9. Python SDK 快速入門

只需幾行程式碼即可將 Point One Percent 整合到你的 Python 或 LangChain 工作流程：

```python
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import GuardrailPolicy

# 定義你的安全策略
policy = GuardrailPolicy(
    allowed_categories=["API", "Cloud", "SaaS"],
    max_amount_per_tx=50.0,
    max_daily_budget=200.0,
    block_hallucination_loops=True
)

# 使用僅關鍵字護欄初始化客戶端（預設）
client = PopClient(
    provider=MockStripeProvider(),
    policy=policy,
    db_path="pop_state.db"
)

# 搭配 LangChain Tool 使用
from pop_pay.tools.langchain import PopPaymentTool
tool = PopPaymentTool(client=client, agent_id="agent-01")
```

> LLM 護欄引擎設定與完整供應商參考，請見[整合指南 §2](./docs/INTEGRATION_GUIDE.zh-TW.md#2-gemini-cli--python-腳本整合)。

---

## 10. 支付供應商：Stripe vs Mock

### 不使用 Stripe（預設 — Mock Provider）

預設情況下，Point One Percent 使用 `MockStripeProvider` 來模擬虛擬卡發行。適用於：
- **開發與測試** — 不涉及真實金錢
- **展示與評估** — 無需任何 API 金鑰即可體驗完整流程
- **黑客松** — 幾分鐘內就能跑出可運作的原型

Mock 卡在系統內完全可用（預算追蹤、用後即焚、護欄全部正常運作），但它們不是真實的支付工具。

### BYOC — 使用自己的信用卡（駭客版）

適合想使用**自己的實體信用卡**而無需 Stripe 帳號的開發者。`LocalVaultProvider` 從環境變數讀取卡片憑證，並透過 CDP 將其注入瀏覽器支付表單 — 原始卡號絕不暴露給 Agent。

**新增至 `~/pop-pay/.env`：**
```bash
POP_BYOC_NUMBER=4111111111111111   # 你的真實卡號
POP_BYOC_CVV=123
POP_BYOC_EXP_MONTH=12             # 到期月份，例如 04
POP_BYOC_EXP_YEAR=27              # 到期年份，例如 31
POP_AUTO_INJECT=true
```
重新啟動 Claude Code 後，MCP server 會自動使用 `LocalVaultProvider`。

**Provider 優先序（高→低）：** Stripe Issuing → BYOC Local → Mock。

若設定了 `POP_STRIPE_KEY`，Stripe 優先。若設定了 `POP_BYOC_NUMBER`（但無 Stripe Key），則使用 `LocalVaultProvider`。若兩者皆未設定，則使用 `MockStripeProvider` 供開發使用。

> **安全提示：** 切勿將真實卡號提交至版本控制。請使用 `.env`（已在 `.gitignore` 中排除）或密鑰管理服務。CDP 注入確保完整卡號僅由本地可信任程序處理，絕不經過 LLM。

> 各供應商的 Python SDK 用法，請見[整合指南 §2](./docs/INTEGRATION_GUIDE.zh-TW.md#2-gemini-cli--python-腳本整合)。

### 使用真實的 Stripe Issuing

若要透過 [Stripe Issuing](https://stripe.com/issuing) 核發**真實的虛擬信用卡**：

**前置條件：**
1. 具備已啟用 [Issuing](https://stripe.com/issuing) 的 Stripe 帳號（需申請審核通過）
2. 你的 Stripe 密鑰（`sk_live_...` 或 `sk_test_...`）

**方法 A：透過環境變數（適用 MCP Server）**
```bash
export POP_STRIPE_KEY=sk_live_your_stripe_key_here
python -m pop_pay.mcp_server
# MCP server 會自動使用 StripeIssuingProvider
```

**Stripe Issuing 的運作方式：**
- 建立真實的 Stripe 持卡人（`POP Agent`）
- 核發虛擬卡，消費限額與核准金額相符
- 僅回傳遮罩後的卡片資訊（末 4 碼）給 Agent
- 所有 Stripe 錯誤都會被捕獲並以拒絕原因回傳

> **備註：** Stripe Issuing 是 Stripe 的進階產品，需要申請通過。對於大多數開發與展示場景，Mock provider 已經足夠。
