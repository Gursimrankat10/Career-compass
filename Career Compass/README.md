# Career Compass

Career Compass is a Python/Flask career exploration website with individual accounts, a private progress database, a 25-question self-reflection assessment (10 answers minimum), a searchable career catalog, personalized roadmaps and daily tasks, XP and streak tracking, progress-aware scenario tests, cited career-market research, and an optional AI career mentor.

## Run locally

Python 3.10 or newer is recommended.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5050](http://127.0.0.1:5050) and create an account. Each account has its own assessments, chosen career, task completions, XP, streak, mentor chat, display name, theme, accent palette, and market region. Dark mode is the default; profile settings offer light mode and 12 accent palettes.

### Export a static HTML preview

To generate standalone HTML snapshots for static hosting, run `python static_export.py`. The command writes `static-site/` with an `index.html`, the other application pages, and their CSS/assets. Upload that output folder to a static host such as Cloudflare Pages by setting its build output directory to `static-site`.

The export uses temporary demonstration data and does not include or modify your account database. It is read-only: registration, sign-in, saving progress, test submissions, mentor responses, and live career research still require the Flask backend. For those features, run or deploy the Python application instead.

### Start automatically on Windows

The server normally stops when Windows shuts down. To have it start automatically each time you sign in to Windows, run `.\install_startup.ps1` once from PowerShell in this folder. This registers a per-user Task Scheduler job, starts the server in the background, and creates a `Career Compass.url` shortcut on your desktop. After restarting the PC and signing in, open the desktop shortcut (or visit [http://127.0.0.1:5050](http://127.0.0.1:5050)); no terminal command is needed. The supervisor restarts the server if it exits and writes diagnostic output to `logs\supervisor.log`, `logs\server-error.log`, and `logs\server.log`. To remove automatic startup, run `Unregister-ScheduledTask -TaskName 'Career Compass' -Confirm:$false` in PowerShell.

If `SECRET_KEY` is not set, the app creates a private `.career_compass_secret` file on first launch and reuses it so signed-in sessions survive server restarts. Keep this file private and do not delete it while you want existing sessions to remain valid. Successful registration and sign-in remember the browser on this device for up to one year; users can sign out from the profile or sidebar at any time. The SQLite database is created as `career_compass.db` beside `app.py`; set `DATABASE_PATH` to choose another location. Set `COOKIE_SECURE=1` when serving the site over HTTPS.

## Deploy to Cloudflare Workers and D1

The Cloudflare deployment runs this Flask app through Cloudflare's Python Workers WSGI adapter. Accounts and progress are stored in D1; the Worker's ephemeral filesystem is not used for persistent state. Python Workers are currently in open beta and require `uv` and Node.js for the `pywrangler` tooling.

1. Install `uv` and Node.js, then run `uv sync`.
2. Create a D1 database with `uv run pywrangler d1 create career-compass`. Copy its database ID into `wrangler.jsonc`, replacing `REPLACE_WITH_YOUR_D1_DATABASE_ID`.
3. Generate a strong secret locally (for example, `python -c "import secrets; print(secrets.token_hex(32))"`) and set it with `uv run pywrangler secret put SECRET_KEY`. Do not put the value in `wrangler.jsonc`, source control, or a command-line argument.
4. Apply the database schema remotely with `uv run pywrangler d1 migrations apply career-compass --remote`.
5. Deploy with `uv run pywrangler deploy` (or `npx wrangler deploy` if your Cloudflare build environment is configured for Python Workers).

For local Worker testing, use `uv run pywrangler d1 migrations apply career-compass --local`, then run `uv run pywrangler dev`. The Wrangler config binds D1 as `DB`, public assets as `ASSETS`, and secrets as `SECRET_KEY` and (optionally) `MODEL_API_KEY`. Both D1 migrations must be applied before the updated Worker can serve requests. Static assets are served directly from the tracked `static/` and `templates/` directories; the root `.assetsignore` allowlists only those two directories so application source, configuration, local databases, and secrets are not uploaded as public assets.

Cloudflare deployment starts with a new D1 database; it does not automatically copy users or progress from the local `career_compass.db`. Keep that local database backed up until you have deliberately handled any data you want to transfer. The `.career_compass_secret` file is only used by the local Flask server; the Worker reads its session key from the Cloudflare secret binding.

## Mentor AI and career-market research

The mentor automatically uses Chrome's on-device Prompt API when the browser supports it; its first use may download a model to the device. If browser AI is unavailable, the server uses Meta AI when `MODEL_API_KEY` is configured, then falls back to the built-in local career guide. Browser AI availability varies by browser and device. When Meta is used, the current question, chosen career, market region, related task details, and any cached career-market report may be sent to Meta; chat history, questionnaire answers, account details, and progress are not sent. Meta model and web-search usage may incur pay-as-you-go charges.

To enable Meta-backed mentor answers and career-market reports, configure a Meta Model API key as `MODEL_API_KEY` in the local server environment or as a Cloudflare Worker secret with `uv run pywrangler secret put MODEL_API_KEY`. Market research is requested only when the user presses the research button; opening the insights page does not trigger a paid API call. Reports request current sources and preserve HTTPS citations; unsupported or uncited statistics are not saved. Generated research can still be wrong or outdated, so verify important information at the linked primary source.

The insights page covers global context and one user-selected country (India, United States, United Kingdom, Canada, Australia, or Germany), with official starting points including ILOSTAT, OECD, the World Economic Forum, and national statistics. These links are references, not a substitute for a current report. When a report has been requested, a daily Cloudflare Cron Trigger refreshes up to three expired cached career/region reports; saved reports expire after seven days. The cron runs at 00:17 UTC, requires the D1 migration and `MODEL_API_KEY`, and only refreshes existing cached reports. Local Flask runs do not have a background scheduler; users can request an update from the insights page.

Without Meta configured, the mentor uses a small multinomial Naive Bayes intent classifier and curated guidance. It is an educational prototype, not a professionally validated model or a substitute for a qualified career adviser. Meta AI is optional and its answers are not professionally validated either.

Career information and assessment guidance are locally curated snapshots; this version does not scrape or synchronize with job platforms. Sports and athletics pathways are included, but professional competition can be highly selective and outcomes are not guaranteed. Before adding an external career source, use its permitted API or licensed dataset, review its terms, attribute content where required, and disclose any data shared. Career requirements and professional licensing vary by location. Assessment match percentages are rough interest-alignment estimates, not employment odds or a validated psychometric test.

Daily task plans are locally generated and personalized from the selected career, assessment interests, recent task history, and the server's local calendar date. A new plan is created on the first request after midnight; an open tasks page checks for the date rollover and refreshes itself. This does not require an external AI service or a separate scheduler, but the web app must be running and the browser will check when it is open. Progress tracking summarizes saved task activity across the last seven days. The six career-learning links are YouTube search suggestions by difficulty, not endorsements or individually vetted videos.

The learning-test area offers 10-question, 20-minute applied scenario tests. Question selection draws from the chosen career track, assessed weak dimensions, completed task types, and previous scores; subsequent difficulty increases with task completion and test performance. Reports retain the selected answers, corrections, citations when available, and mentor guidance. Progress combines completed task types with test performance, and the testing area stores attempt history.

On an original single-profile installation with no account records, the first registered account receives the saved progress and legacy tables are removed after the migration succeeds. If accounts already exist, their progress and retained legacy backup tables are left untouched; new accounts start with fresh progress instead. Back up `career_compass.db` before upgrading an installation with data.

Before sharing a public deployment broadly, add email verification, password reset and rate limiting, backups, privacy/retention controls, and an independent security review. Cloudflare Python Workers are in open beta.
