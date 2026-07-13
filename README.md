# Funding Fit Scorer (template)

A customizable, staff-only web app that scores funding opportunities against
*your* organization's strategy and returns a 0-100 fit score, a tier, and a
one-page go/no-go memo. It captures staff feedback and real outcomes and
recalibrates its scoring on a schedule with human sign-off.

This is a template. Fork it, brand it, define your strategy profile, and deploy
your own instance. Your organization runs its own copy with its own database and
its own Claude key, so your data is isolated by construction.

Stack: FastAPI (Python), SQLAlchemy (SQLite locally, Postgres/Neon in
production), the Claude API for parsing, scoring, memo, recalibration, and
profile bootstrap, and a zero-build single-page frontend (React via CDN).

## What makes it reusable

Everything specific to an organization is configuration, not code:

- **Branding** lives in `org_config.json` (name, tool name, tagline, brand color).
- **Your scoring strategy** lives in the Strategy Profile, stored in the database
  and edited in the app: the scoring dimensions, their weights, the hard and soft
  filters, thresholds, and tier cutoffs are all data you control.
- **A bootstrap agent** drafts your first profile from your strategic plan, so a
  new organization is not staring at a blank form.

The engine (parse, score, memo, learn) is generic. The judgment is yours, and it
lives entirely in the profile. Read **PROFILE_GUIDE.md** before you configure it:
the tool is only as good as the profile, and a vague profile is worse than none.

## Run it locally (no API key needed)

```bash
bash run_local.sh
```

Open http://localhost:8000. With no `ANTHROPIC_API_KEY` it runs in mock mode (a
keyword heuristic) so you can click through the whole flow. The first user to
sign in becomes admin. It boots with a placeholder starter profile and prompts
you to set up your real one.

For real scoring, put your key in `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Customize it for your organization

1. Copy `org_config.example.json` to `org_config.json` and set your name, tool
   name, tagline, brand color, and currency. (`org_config.json` is git-ignored.)
2. Copy `.env.example` to `.env`, set `ALLOWED_EMAIL_DOMAINS` to your email
   domain and `INITIAL_ADMIN_EMAILS` to your admins.
3. Start the app, sign in as admin, open **Setup**, paste your strategic plan,
   and let the bootstrap agent draft your profile. Edit every part of it (see
   PROFILE_GUIDE.md), then save it as your active profile.
4. Score away. Refine weights and filters over time in **Admin**, and let
   recalibration propose changes once you have logged real outcomes.

## Deploy to Render + Neon

1. **Neon**: create a project, copy the pooled connection string
   (`postgresql://...-pooler...`). That is your `DATABASE_URL`. The app creates
   its own tables on first boot.
2. **Render**: New > Blueprint pointed at your fork (uses `render.yaml`), or a
   Python web service with build `pip install -r requirements.txt` and start
   `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.
3. Set env vars: `SECRET_KEY`, `DATABASE_URL`, `ANTHROPIC_API_KEY`,
   `ALLOWED_EMAIL_DOMAINS`, `INITIAL_ADMIN_EMAILS`, `DEV_AUTH=false`, and the
   Google OAuth values below. `runtime.txt` pins Python 3.11.9.
4. **Google OAuth** (staff-only sign-in): create an OAuth web client, set the
   redirect URI to `https://YOUR-URL/api/auth/google/callback`, put the client id
   and secret in Render along with `BASE_URL`. When set, Google SSO replaces the
   dev login. Access is restricted to `ALLOWED_EMAIL_DOMAINS`.

Confirm current Claude model IDs at
https://platform.claude.com/docs/en/about-claude/models/overview and set
`STRONG_MODEL`, `FAST_MODEL`, `RECAL_MODEL` if they have changed.

## How scoring works

Parse the opportunity (paste text, URL, or upload a PDF/Word/text file) into
structured fields, run the hard and soft filters, score each dimension 0-100
with the strong model, compute the weighted total and tier in Python (auditable,
not model-invented), and write the memo. A **hard** filter disqualifies; a
**soft** filter (like org-type eligibility) caps the tier at Watch and flags a
resolvable blocker instead of zeroing the score. Staff override, decide, and log
outcomes; recalibration turns that history into proposed weight changes an admin
approves.

## Files

- `org_config.json` / `.example` - branding.
- `backend/starter_profile.py` - the neutral placeholder profile.
- `backend/claude_agents.py` - parser, scorer (dynamic schema), memo,
  recalibration, and the bootstrap agent.
- `backend/scoring.py` - weighted math, hard/soft filter logic, tiering.
- `backend/routes.py` - API including `/api/setup/bootstrap` and `/api/config`.
- `frontend/app.js` - single-page UI with dynamic dimensions and a Setup screen.
- `PROFILE_GUIDE.md` - how and why to define a sharp profile. Read it.
