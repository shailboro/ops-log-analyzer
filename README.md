# Ops Log Analyzer

Multi-agent operations log analysis demo powered by **LangGraph**. Upload ops logs for live classification, remediation plans, Slack notifications, JIRA tickets, and actionable runbook checklists.

## Features

- **Log Reader / Classifier** — parses and categorizes log entries, detects issues
- **Remediation Agent** — maps each issue to fix steps with rationale
- **Cookbook Synthesizer** — produces markdown runbook checklists
- **Notification Agent** — posts summaries to Slack (mock or live)
- **JIRA Ticket Agent** — creates tickets for critical/high issues (mock or live)
- **LangGraph Orchestrator** — manages agent flow with live trace events

## Quick Start

### 1. Install dependencies

```bash
cd Projects/ops-log-analyzer
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e .
```

### 2. Configure environment

```bash
copy .env.example .env
```

Edit `.env` and set at minimum:

```
OPENROUTER_API_KEY=sk-or-your-key
LLM_PROVIDER=openrouter
```

Slack and JIRA are **mock by default** — outputs are written to `runs/{run_id}/`.

### 3. Run the app (two terminals)

**Terminal 1 — API:**

```bash
uvicorn app.api.main:app --reload --port 8000
```

**Terminal 2 — Streamlit UI:**

```bash
streamlit run app/streamlit_app.py
```

Open http://localhost:8501

## 5-Minute Demo Script

1. **Intro (30s)** — "We ingest ops logs and orchestrate five specialist agents via LangGraph."
2. **Upload (30s)** — Sidebar → **Load k8s_crashloop.log** → click **Analyze**.
3. **Live Trace (60s)** — Switch to **Live Trace** tab; narrate each agent step as it completes.
4. **Findings (60s)** — Show CrashLoopBackOff, OOM, and ImagePull errors with severity badges.
5. **Fixes (45s)** — Walk through remediation cards (memory limits, image tags, probe tuning).
6. **Cookbook (45s)** — Show synthesized checklist; download as `.md`.
7. **Outputs (30s)** — Reveal Slack Block Kit preview and JIRA tickets (mock mode).
8. **All-clear contrast (30s)** — Load `healthy_with_warnings.log`; show no JIRA tickets, all-clear Slack.

## Sample Logs

| File | Expected behavior |
|------|-------------------|
| `samples/k8s_crashloop.log` | Critical K8s failures → JIRA + Slack alert |
| `samples/db_connection.log` | DB pool exhaustion → high severity remediations |
| `samples/healthy_with_warnings.log` | Mostly INFO/WARN → all-clear, no JIRA |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health + integration mode |
| POST | `/analyze` | Start analysis `{logs, filename?}` → `{run_id}` |
| GET | `/runs/{run_id}` | Full run state + trace |
| GET | `/runs/{run_id}/events` | SSE stream of trace events |

## Live Integrations

Set these in `.env` to enable live mode:

**Slack (webhook):**

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

**Slack (bot):**

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C0123456789
```

**JIRA:**

```
JIRA_BASE_URL=https://your-org.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=your-api-token
JIRA_PROJECT_KEY=OPS
```

**Email:**

```
EMAIL_SMTP_HOST=smtp.example.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=your-smtp-user
EMAIL_SMTP_PASSWORD=your-smtp-password
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
EMAIL_FROM=ops-alerts@example.com
EMAIL_TO=team@example.com
```

## Architecture

```
Streamlit UI → FastAPI → LangGraph Orchestrator
                              ├── LogReaderClassifier
                              ├── RemediationAgent
                              ├── CookbookSynthesizer
                              ├── NotificationAgent → Slack
                              └── JiraTicketAgent → JIRA
```

Run artifacts are persisted to `runs/{run_id}/state.json` for post-demo inspection.

## Deploy to Vercel

The FastAPI backend and a static web UI deploy to [Vercel](https://vercel.com). Streamlit remains for local development only.

1. Install the Vercel CLI: `npm i -g vercel`
2. Link the project to your Vercel team:
   ```bash
   vercel link --scope shailborocloud-9996s-projects
   ```
3. Set environment variables in the Vercel dashboard (or via CLI):
   ```bash
   vercel env add OPENROUTER_API_KEY
   vercel env add LLM_PROVIDER production
   ```
   Use `openrouter` for `LLM_PROVIDER`.
4. Deploy:
   ```bash
   vercel deploy --prod
   ```

On Vercel, analysis runs synchronously in the `/analyze` request (up to 300s). Run state is stored under `/tmp/runs` for the duration of the function instance.

## License

MIT — hackathon demo project.
