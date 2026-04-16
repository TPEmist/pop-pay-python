# pop-pay Payment Skill for OpenClaw

**Version**: 0.6.18  
**Author**: Point One Percent  
**License**: MIT  
**Install**: `pip install pop-pay` → `pop-pay setup` → add MCP server to your agent

---

## What This Skill Does

Gives your OpenClaw agent the ability to pay at any online store—using **your own credit card**, with no crypto, no proxy wallet, and no funds to pre-load.

The card number is **never placed in the agent's context window**. It is injected directly into the browser's payment form via Chrome DevTools Protocol (CDP) in a separate process. If your agent is compromised by a prompt injection attack, the attacker cannot steal your card—they cannot see it.

---

## Setup (One Time)

```bash
pip install pop-pay
pop-pay setup          # securely stores your card in the system keychain
pop-pay setup --profile   # stores billing info (name, address, email)
```

Then add to your OpenClaw config:

```json
{
  "mcpServers": {
    "pop-pay": {
      "command": "pop-pay",
      "args": ["serve"]
    }
  }
}
```

Set your spend policy in `~/.config/pop-pay/.env`:

```
POP_ALLOWED_CATEGORIES='["amazon","shopify","aws"]'
POP_MAX_AMOUNT_PER_TX=100
POP_MAX_DAILY_BUDGET=300
POP_AUTO_INJECT=true
# Optional: get Slack/webhook notifications on every transaction
POP_WEBHOOK_URL=https://hooks.slack.com/your-hook-here
```

---

## Tools

### `request_purchaser_info`

**When to call**: You are on a contact/billing info page with fields for name, email, phone, or address—but no credit card fields are visible yet.

```
request_purchaser_info(
    target_vendor: str,   # e.g. "Amazon", "Shopify", "Maker Faire" — NOT a URL
    page_url: str,        # current browser page URL
    reasoning: str        # why you are filling this form
)
```

- Injects name, email, phone, and address from the user's stored profile
- Does NOT issue a card, does NOT charge anything, does NOT affect the budget
- After this completes, navigate to the payment page and call `request_virtual_card`

---

### `request_virtual_card`

**When to call**: You are on the checkout/payment page and credit card input fields are visible.

```
request_virtual_card(
    requested_amount: float,  # exact amount shown on screen
    target_vendor: str,       # e.g. "Amazon" — NOT a URL
    reasoning: str,           # explain why this purchase should happen
    page_url: str             # current checkout page URL
)
```

- Evaluates the purchase against the user's spend policy (amount limits, category allowlist)
- Runs a semantic guardrail: the LLM evaluates whether this purchase **should** happen given your agent's current task context—not just whether it **can** (within budget)
- If approved, the card number, CVV, and expiry are injected directly into the browser form via CDP—never passed to the agent
- Returns: `approved` (with last 4 digits) or `rejected` (with reason)

**After approval**: Click the submit/pay button. The card has been filled automatically.

---

## Usage Flow

```
Agent navigates to product page
  ↓
Agent clicks "Checkout" / "Proceed to payment"
  ↓
[If billing page appears first]
  → call request_purchaser_info(vendor, page_url, reasoning)
  → click Continue/Next
  ↓
[When payment/card fields are visible]
  → call request_virtual_card(amount, vendor, reasoning, page_url)
  ↓
[If approved]
  → click Submit / Place Order
```

---

## Security Model

| Property | pop-pay | Proxy wallet (e.g. Lobster.cash) |
|---|---|---|
| Card number in agent context | Never | Never |
| Requires crypto / stable coin | No | Yes (USDC) |
| Works with existing credit card | Yes | No (requires funded wallet) |
| Works with any merchant | Yes (any form) | Only Visa TAP merchants |
| Semantic guardrail (SHOULD vs CAN) | Yes | No |
| Open source / auditable | MIT | Varies |

**Prompt injection resistance**: Because the card is injected by a separate process (CDP injector) that only activates after guardrail approval, a malicious merchant cannot steal the card via hidden DOM instructions—the agent never had the card to give away.

---

## Spend Policy Reference

| Env var | Description | Example |
|---|---|---|
| `POP_ALLOWED_CATEGORIES` | JSON array of allowed vendor keywords | `["amazon","cloudflare","aws"]` |
| `POP_MAX_AMOUNT_PER_TX` | Max per transaction (USD) | `100` |
| `POP_MAX_DAILY_BUDGET` | Max total spend per day (USD) | `300` |
| `POP_REQUIRE_HUMAN_APPROVAL` | Always require human confirmation | `false` |
| `POP_AUTO_INJECT` | Enable CDP auto-injection | `true` |
| `POP_WEBHOOK_URL` | POST notification URL (Slack/Teams/PagerDuty) | `https://hooks.slack.com/...` |

---

## Example: Agent Buys Office Supplies on Amazon

```python
# Agent has been asked: "Order a USB-C hub from Amazon, around $40"

# Step 1: Navigate to Amazon, find the product, add to cart, proceed to checkout
# [agent uses browser tools to navigate]

# Step 2: On billing info page
result = request_purchaser_info(
    target_vendor="Amazon",
    page_url="https://www.amazon.com/checkout/address",
    reasoning="Filling billing address for USB-C hub purchase as instructed by user"
)
# → Billing info injected. Click Continue.

# Step 3: On payment page  
result = request_virtual_card(
    requested_amount=43.99,
    target_vendor="Amazon",
    reasoning="Purchasing USB-C hub for home office setup as instructed by user",
    page_url="https://www.amazon.com/checkout/payment"
)
# → Approved. Card injected. Click "Place your order".
```

---

## GitHub

[github.com/100xPercent/pop-pay-python](https://github.com/100xPercent/pop-pay-python)
