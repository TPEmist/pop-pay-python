# Agent-Oriented Installation Guide for pop-pay MCP Server

This document provides instructions for an AI agent to install and configure the pop-pay MCP server. 

## 1. Installation Environment
Always use a dedicated virtual environment to prevent dependency conflicts.
```bash
mkdir ~/pop-pay && cd ~/pop-pay
python3 -m venv .venv && source .venv/bin/activate
pip install "pop-pay[all]"
```
*Note: The quotes around "pop-pay[all]" are mandatory in zsh/bash.*

## 2. Configuration (.env)
Configuration is stored in `~/.config/pop-pay/.env`. Key fields include:
- `POP_ALLOWED_CATEGORIES`: JSON array of approved vendor categories (e.g., `["aws", "openai", "github"]`).
- `POP_MAX_PER_TX`: Float value for maximum spending per transaction (e.g., `100.0`).
- `POP_MAX_DAILY`: Float value for maximum cumulative daily spending (e.g., `500.0`).
- `POP_BLOCK_LOOPS`: Boolean (`true`/`false`) to prevent hallucination-driven retry loops.
- `POP_AUTO_INJECT`: Boolean to enable Chrome DevTools Protocol (CDP) DOM injection.
- `POP_GUARDRAIL_ENGINE`: Set to `keyword` (zero-cost) or `llm` (semantic analysis).
- `POP_BYOC_NUMBER`: Physical card number for BYOC mode (stored in encrypted vault).

## 3. Setup Flow
1. **Initialize Vault**: Run `pop-init-vault` to securely store card credentials. Credentials are encrypted with AES-256-GCM and never stored in plaintext.
2. **Launch Chrome**: Run `pop-launch --print-mcp` to start a CDP-enabled browser instance.
3. **Connect to Host**: Use the printed command (e.g., `claude mcp add ...`) to register the server with your MCP host.

## 4. Virtual Card & Security Mechanism
- **Credential Isolation**: When `request_virtual_card` is called, pop-pay returns only a masked card number (e.g., `****-4242`) to the agent context.
- **CDP Injection**: Real credentials are injected directly into the browser DOM via CDP. The raw PAN/CVV never enters the LLM's context window, providing 100% protection against prompt injection.
- **Guardrails**: Every request is evaluated by the Guardrail Engine. It checks spending limits and performs semantic analysis on the agent's `reasoning` to block suspicious or off-policy transactions.
