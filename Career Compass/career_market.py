import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request as URLRequest, urlopen


MODEL_API_URL = "https://api.meta.ai/v1/responses"
MODEL_NAME = "muse-spark-1.3"
INSIGHT_TTL = timedelta(days=7)
REFRESH_BATCH_SIZE = 3

COUNTRIES = {
    "IN": "India",
    "US": "United States",
    "GB": "United Kingdom",
    "CA": "Canada",
    "AU": "Australia",
    "DE": "Germany",
}

PALETTES = {
    "green": {
        "label": "Emerald green",
        "accent": "#37634d",
        "deep": "#294d3a",
        "soft": "#e1eee5",
        "glow": "#c6e0c9",
        "on_accent": "#ffffff",
        "on_accent_dark": "#ffffff",
    },
    "red": {
        "label": "Ruby red",
        "accent": "#c63a50",
        "deep": "#a2263b",
        "soft": "#fae5e9",
        "glow": "#f6c4ce",
        "on_accent": "#ffffff",
        "on_accent_dark": "#ffffff",
    },
    "blue": {
        "label": "Electric blue",
        "accent": "#3868d9",
        "deep": "#244eae",
        "soft": "#e5ecff",
        "glow": "#c6d5fc",
        "on_accent": "#ffffff",
        "on_accent_dark": "#ffffff",
    },
    "gold": {
        "label": "Golden",
        "accent": "#bd870b",
        "deep": "#926505",
        "soft": "#fbf1d7",
        "glow": "#eed89c",
        "on_accent": "#251b04",
        "on_accent_dark": "#251b04",
    },
    "magenta": {
        "label": "Magenta",
        "accent": "#c3238a",
        "deep": "#971869",
        "soft": "#f9e3f2",
        "glow": "#edb6da",
        "on_accent": "#ffffff",
        "on_accent_dark": "#ffffff",
    },
    "purple": {
        "label": "Purple",
        "accent": "#7548c8",
        "deep": "#56339a",
        "soft": "#eee7fb",
        "glow": "#d6c3f5",
        "on_accent": "#ffffff",
        "on_accent_dark": "#ffffff",
    },
    "violet": {
        "label": "Violet",
        "accent": "#7444e8",
        "deep": "#5931b4",
        "soft": "#eee8ff",
        "glow": "#d2c3ff",
        "on_accent": "#ffffff",
        "on_accent_dark": "#ffffff",
    },
    "orange": {
        "label": "Sunset orange",
        "accent": "#d66722",
        "deep": "#a84b17",
        "soft": "#fceedf",
        "glow": "#f5ceb0",
        "on_accent": "#3b1909",
        "on_accent_dark": "#3b1909",
    },
    "cyan": {
        "label": "Cyan",
        "accent": "#087e91",
        "deep": "#066372",
        "soft": "#def4f7",
        "glow": "#b2e3e9",
        "on_accent": "#ffffff",
        "on_accent_dark": "#ffffff",
    },
    "teal": {
        "label": "Teal",
        "accent": "#13836e",
        "deep": "#0c6252",
        "soft": "#e0f3ee",
        "glow": "#b9e1d6",
        "on_accent": "#ffffff",
        "on_accent_dark": "#ffffff",
    },
    "lime": {
        "label": "Lime",
        "accent": "#668c16",
        "deep": "#4d6c0f",
        "soft": "#eef5da",
        "glow": "#d9e8a9",
        "on_accent": "#17210a",
        "on_accent_dark": "#17210a",
    },
}

RESEARCH_SOURCES = [
    {
        "title": "International Labour Organization (ILOSTAT)",
        "url": "https://ilostat.ilo.org/",
        "description": "International labour, employment, and wage indicators.",
    },
    {
        "title": "World Economic Forum — Future of Jobs",
        "url": "https://www.weforum.org/publications/the-future-of-jobs-report-2025/",
        "description": "Employer expectations about job and skill change through 2030.",
    },
    {
        "title": "U.S. Bureau of Labor Statistics — Occupational Outlook Handbook",
        "url": "https://www.bls.gov/ooh/",
        "description": "U.S.-specific occupation pay, duties, and projected outlook.",
    },
    {
        "title": "OECD Data Explorer",
        "url": "https://data-explorer.oecd.org/",
        "description": "Comparable labour-market and earnings indicators for OECD members.",
    },
]

MARKET_RESEARCH_INSTRUCTIONS = (
    "You are a career-market research assistant. Search the web for current primary "
    "and authoritative sources. Distinguish worldwide context from country-specific "
    "evidence. Report only numbers you can verify from a source, and include the source "
    "year, geography, currency, and whether pay is median, average, annual, hourly, or "
    "a range. Never invent salary figures, growth rates, vacancies, rankings, or "
    "credentials. If a reliable current figure is unavailable, say so. Explain "
    "uncertainty and regional variation. Use concise headings and plain language. "
    "This is informational research, not a promise of employment or professional "
    "financial advice."
)
MENTOR_INSTRUCTIONS = (
    "You are a patient, practical career mentor. Answer the user's actual question, "
    "including hypotheticals, by stating assumptions and walking through the trade-offs. "
    "When discussing current pay, hiring, or requirements, use live web sources and cite "
    "them; otherwise do not invent facts. Use the supplied career-market report only "
    "within its stated date and region. Do not claim to be a licensed professional, "
    "diagnose, or give legal, medical, or financial advice. Be clear about uncertainty "
    "and suggest a qualified local professional when appropriate. Keep the answer "
    "specific, encouraging, and concise."
)


class MetaAPIError(RuntimeError):
    pass


def current_model_api_key(worker_environment=None):
    if worker_environment is not None:
        try:
            key = str(worker_environment.MODEL_API_KEY)
            return key if key not in ("undefined", "None", "") else None
        except AttributeError:
            return None
    return os.environ.get("MODEL_API_KEY")


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def cached_insight_is_stale(updated_at, now=None):
    if not updated_at:
        return True
    try:
        updated = datetime.fromisoformat(updated_at)
    except (TypeError, ValueError):
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (now or utc_now()) - updated >= INSIGHT_TTL


def _request_payload(
    prompt,
    api_key,
    worker_environment=None,
    instructions=MARKET_RESEARCH_INSTRUCTIONS,
    max_output_tokens=1100,
):
    payload = {
        "model": MODEL_NAME,
        "store": False,
        "instructions": instructions,
        "input": prompt,
        "tools": [{"type": "web_search", "search_context_size": "high"}],
        "include": ["web_search_call.results"],
        "max_output_tokens": max_output_tokens,
    }
    if worker_environment is None:
        return _request_local(payload, api_key)
    return _request_worker(payload, api_key)


def _request_local(payload, api_key):
    body = json.dumps(payload).encode("utf-8")
    request = URLRequest(
        MODEL_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            result = json.loads(response.read(1_000_001).decode("utf-8"))
    except HTTPError as error:
        raise MetaAPIError(f"Meta Model API returned HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise MetaAPIError("The Meta Model API could not be reached.") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MetaAPIError("The Meta Model API returned invalid JSON.") from error
    return _extract_answer(result)


def _request_worker(payload, api_key):
    from js import Object, fetch
    from pyodide.ffi import run_sync, to_js

    options = to_js(
        {
            "method": "POST",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            "body": json.dumps(payload),
        },
        dict_converter=Object.fromEntries,
    )
    try:
        response = run_sync(fetch(MODEL_API_URL, options))
        if not response.ok:
            raise MetaAPIError(
                f"Meta Model API returned HTTP {response.status}."
            )
        result = run_sync(response.json()).to_py()
    except MetaAPIError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise MetaAPIError("The Meta Model API request failed.") from error
    return _extract_answer(result)


def _extract_answer(result):
    if result.get("status") not in (None, "completed"):
        raise MetaAPIError("Meta Model API did not complete the research request.")
    text_parts = []
    sources = []
    for item in result.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") != "output_text":
                    continue
                if isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
                for annotation in block.get("annotations", []):
                    if annotation.get("type") == "url_citation":
                        source = _safe_source(
                            annotation.get("title"), annotation.get("url")
                        )
                        if source:
                            sources.append(source)
        if item.get("type") == "web_search_call":
            for source_result in item.get("results", []):
                source = _safe_source(
                    source_result.get("title"), source_result.get("url")
                )
                if source:
                    sources.append(source)
    answer = "\n\n".join(text_parts).strip()
    unique_sources = list(
        {source["url"]: source for source in sources}.values()
    )
    if not answer:
        raise MetaAPIError("Meta Model API returned an empty answer.")
    return answer[:12000], unique_sources[:12]


def _safe_source(title, url):
    if not isinstance(title, str) or not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return {"type": "url_citation", "title": title[:240], "url": url[:1500]}


def career_market_prompt(career, country_code):
    country_name = COUNTRIES[country_code]
    strengths = ", ".join(career.get("strengths", []))
    return (
        f"Research the current career outlook for {career['title']} "
        f"(category: {career['category']}). Career Compass describes this role as: "
        f"{career['description']} The related strengths are {strengths or 'not specified'}. "
        f"Prioritize {country_name}, then give a separately labeled worldwide view. "
        "Write a useful, specific report under these exact headings:\n"
        "CAREER SCOPE — Explain what the role covers, where people do this work, "
        "which industries and regions employ it, and any reliable global and "
        f"{country_name}-specific workforce or demand measures. Clearly separate "
        "current employment from forecasts and name each measure's year and geography.\n"
        "EARNINGS — Give current, sourced pay data for the selected country, including "
        "currency, year, pay period, and whether each figure is a median, average, or "
        "range. Include entry-level and experienced pay only when sources explicitly "
        "support the comparison. Add global comparisons only when measures are "
        "genuinely comparable. Explain major factors affecting income and say when "
        "reliable figures are unavailable; never estimate or convert unsupported pay.\n"
        "WHAT THE WORK IS LIKE — Describe typical duties, tools, common work settings, "
        "team interaction, schedule, travel, physical or emotional demands, and how "
        "these vary across specializations or employers. Distinguish sourced facts "
        "from general role descriptions.\n"
        "ENTRY ROUTES AND PROGRESSION — Explain typical education or training, "
        "beginner skills, entry roles, portfolio or experience expectations, and "
        "country-specific licenses or certifications. Include alternate routes and "
        "possible specializations or progression. Give durations or requirements "
        "only when an authoritative source supports them.\n"
        "OUTLOOK AND RISKS — Summarize recent and projected hiring or sector change, "
        "automation or technology effects, barriers, and uncertainties, with source "
        "years and geography.\n"
        "PRACTICAL NEXT STEPS — Give three realistic ways a beginner can investigate "
        "this role in the selected region without implying a job guarantee.\n"
        "Use 6-10 current, reputable sources, prioritizing national statistical and "
        "labor agencies, ILO, OECD, official education or licensing bodies, and "
        "relevant professional organizations. Attach citations to factual claims. "
        "Do not invent statistics, rankings, credentials, or requirements. If "
        "global data are not comparable or unavailable, say so plainly instead of "
        "presenting a local figure as worldwide. Keep the report detailed but readable."
    )


def mentor_prompt(message, career, country_code, market_report=None, task_context=None):
    if career:
        context = f"Career direction: {career['title']} ({career['category']}). "
    else:
        context = "No career has been selected yet; give general career exploration guidance. "
    context += f"User-selected market: {COUNTRIES[country_code]} plus global context."
    if market_report:
        context += (
            "\nRecently retrieved, cited career-market context (check its date and "
            "citations; do not extend its numeric claims):\n"
            + market_report[:6000]
        )
    if task_context:
        context += (
            "\nCurrent learning task:\n"
            f"Title: {task_context['title'][:240]}\n"
            f"Goal: {task_context['deliverable'][:1000]}"
        )
    return context + "\n\nUser's current question:\n" + message[:500]


def meta_mentor_reply(message, career, country_code, api_key, market_report=None,
                      worker_environment=None, task_context=None):
    return _request_payload(
        mentor_prompt(message, career, country_code, market_report, task_context),
        api_key,
        worker_environment,
        instructions=MENTOR_INSTRUCTIONS,
    )


def refresh_insights(database, career, country_code, api_key, worker_environment=None):
    prompt = career_market_prompt(career, country_code)
    report, sources = _request_payload(
        prompt,
        api_key,
        worker_environment,
        max_output_tokens=2600,
    )
    if not sources:
        raise MetaAPIError(
            "Meta's live-search response did not include source citations; no statistics were saved."
        )
    updated_at = utc_now().isoformat()
    database.execute(
        """INSERT OR REPLACE INTO career_insights
           (career_id, country_code, report, sources_json, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (career["id"], country_code, report, json.dumps(sources), updated_at),
    )
    database.commit()
    return {
        "career_id": career["id"],
        "country_code": country_code,
        "report": report,
        "sources": sources,
        "updated_at": updated_at,
    }


def refresh_stale_insights(database, api_key, career_lookup, worker_environment=None):
    if not api_key:
        return 0
    cutoff = (utc_now() - INSIGHT_TTL).isoformat()
    stale_rows = database.execute(
        """SELECT career_id, country_code FROM career_insights
           WHERE updated_at <= ? ORDER BY updated_at LIMIT ?""",
        (cutoff, REFRESH_BATCH_SIZE),
    ).fetchall()
    refreshed = 0
    for row in stale_rows:
        career = career_lookup(row["career_id"])
        if career is None or row["country_code"] not in COUNTRIES:
            continue
        refresh_insights(
            database, career, row["country_code"], api_key, worker_environment
        )
        refreshed += 1
    return refreshed


def read_cached_insight(database, career_id, country_code):
    row = database.execute(
        """SELECT report, sources_json, updated_at FROM career_insights
           WHERE career_id = ? AND country_code = ?""",
        (career_id, country_code),
    ).fetchone()
    if row is None:
        return None
    return {
        "report": row["report"],
        "sources": json.loads(row["sources_json"]),
        "updated_at": row["updated_at"],
        "stale": cached_insight_is_stale(row["updated_at"]),
    }
