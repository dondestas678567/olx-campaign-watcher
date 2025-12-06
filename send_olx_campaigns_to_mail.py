import os
import json
import re
from datetime import datetime
from collections import defaultdict

import requests


# =========================================
# CONFIG
# =========================================

DEBUG = True

AURA_URL = "https://ajutor.olx.ro/olxhelpro/s/sfsites/aura"
AURA_PARAMS = {
    "r": "6",
    "aura.ApexAction.execute": "1",
}

AURA_BODY = (
    "message=%7B%22actions%22%3A%5B%7B%22id%22%3A%22246%3Ba%22%2C%22descriptor%22%3A%22aura%3A%2F%2F"
    "ApexActionController%2FACTION%24execute%22%2C%22callingDescriptor%22%3A%22UNKNOWN%22%2C%22params%22"
    "%3A%7B%22namespace%22%3A%22%22%2C%22classname%22%3A%22c_listTopicDetail%22%2C%22method%22%3A%22get"
    "Articles%22%2C%22params%22%3A%7B%22language%22%3A%22ro%22%2C%22overrideCategory%22%3Afalse%2C%22topic"
    "Id%22%3A%220TO09000000khDAGAY%22%7D%2C%22cacheable%22%3Atrue%2C%22isContinuation%22%3Afalse%7D%7D%5D"
    "%7D"
    "&aura.context=%7B%22mode%22%3A%22PROD%22%2C%22fwuid%22%3A%22MXg4UmtXaFlzZ0JoYTJBejdMZEtWdzFLcUUxeUY3"
    "ZVB6dE9hR0VheDVpb2cxMy4zMzU1NDQzMi41MDMzMTY0OA%22%2C%22app%22%3A%22siteforce%3AcommunityApp%22%2C%22"
    "loaded%22%3A%7B%22APPLICATION%40markup%3A%2F%2Fsiteforce%3AcommunityApp%22%3A%221414_JnVqyfJtnxwn08WU"
    "8yKzPg%22%7D%2C%22dn%22%3A%5B%5D%2C%22globals%22%3A%7B%7D%2C%22uad%22%3Atrue%7D"
    "&aura.pageURI=%2Folxhelpro%2Fs%2Ftopic%2F0TO09000000khDAGAY%2Fcampanii-si-noutati-olx"
    "&aura.token=null"
)

AURA_COOKIE = ""

# Default recipient (can be overridden by env var TO_EMAIL)
TO_EMAIL = os.getenv("TO_EMAIL", "az.e1.3.19.8.9@gmail.com")

# ===== Resend (for GitHub Actions) =====
# Set in GitHub Secrets and passed by the workflow:
#   RESEND_API_KEY
#   RESEND_FROM  (ex: "OLX Alerts <alerts@yourdomain.com>")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM", "").strip()
RESEND_URL = "https://api.resend.com/emails"

# Fallback sender. May be rejected unless your Resend account allows it.
RESEND_FROM_FALLBACK = "OLX Alerts <onboarding@resend.dev>"

FORCE_BASELINE_DATE = datetime(2025, 11, 30)


# =========================================
# UTILS
# =========================================

def debug(msg: str) -> None:
    if DEBUG:
        print(f"[DEBUG] {msg}")


def get_script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def load_static_baselinks(path: str):
    if not os.path.exists(path):
        debug(f"No static baseline file at {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    debug(f"Loaded {len(data)} baselinks from read-only file")
    return data


def load_all_aura_ever(path: str):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_all_aura_ever(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_new_campaigns(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_stored_datetime(date_str: str) -> tuple[str, str]:
    if not date_str or not date_str.strip():
        return "", ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M")
    except:
        return "", ""


def get_week_of_month(date_obj: datetime) -> int:
    first_day = date_obj.replace(day=1)
    adjusted_dom = date_obj.day + first_day.weekday()
    return (adjusted_dom - 1) // 7 + 1


def parse_date_from_title(title: str, original_date_obj: datetime) -> datetime:
    ro_months = {
        "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5, "iunie": 6,
        "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12
    }
    pattern = r"(?i)\b(" + "|".join(ro_months.keys()) + r")\s+(\d{4})\b"
    match = re.search(pattern, title)
    if match:
        month_str = match.group(1).lower()
        year_str = match.group(2)
        new_month = ro_months[month_str]
        new_year = int(year_str)
        try:
            return original_date_obj.replace(year=new_year, month=new_month)
        except ValueError:
            return original_date_obj.replace(year=new_year, month=new_month, day=1)
    return original_date_obj


# =========================================
# PLACEMENT DATE
# =========================================

def compute_placement_date(url: str, title: str, date_str: str, static_baselinks: dict) -> datetime:
    if url in static_baselinks:
        return FORCE_BASELINE_DATE

    date_obj = datetime(1900, 1, 1)
    if date_str and date_str.strip():
        try:
            date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except:
            pass

    date_obj = parse_date_from_title(title, date_obj)
    return date_obj


# =========================================
# FETCH & PARSE
# =========================================

def parse_aura_json(text: str):
    raw = text.lstrip()
    if raw.startswith("while(1);"):
        raw = raw[len("while(1);"):].lstrip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    actions = data.get("actions") or []
    all_campaigns = {}

    for action in actions:
        if action.get("state") != "SUCCESS":
            continue
        rv_inner = ((action.get("returnValue") or {}).get("returnValue") or {})
        articles_by_topic = rv_inner.get("articles") or {}

        for article_list in articles_by_topic.values():
            for art in article_list:
                ka_id = art.get("KnowledgeArticleId") or art.get("Id")
                title = (art.get("Title") or "").strip()
                date_str = art.get("LastPublishedDate") or art.get("CreatedDate") or art.get("LastModifiedDate") or ""
                if not ka_id:
                    continue
                url = f"https://ajutor.olx.ro/olxhelpro/s/article/{ka_id}"
                all_campaigns[url] = {"title": title, "date": date_str}

    return all_campaigns


def fetch_campaign_links_from_aura():
    headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "referer": "https://ajutor.olx.ro/olxhelpro/s/topic/0TO09000000khDAGAY/campanii-si-noutati-olx",
    }
    if AURA_COOKIE:
        headers["cookie"] = AURA_COOKIE

    try:
        resp = requests.post(AURA_URL, params=AURA_PARAMS, headers=headers, data=AURA_BODY, timeout=30)
    except Exception as e:
        debug(f"Request error: {e!r}")
        return {}

    if resp.status_code != 200:
        debug(f"Aura HTTP status: {resp.status_code}")
        return {}

    return parse_aura_json(resp.text)


# =========================================
# ORGANIZE & EMAIL BODY
# =========================================

def organize_by_month_week(campaigns, static_baselinks):
    organized = defaultdict(lambda: defaultdict(list))

    for url, info in campaigns.items():
        title = info.get("title", "")
        # Pentru baselinks folosim întotdeauna data din fișierul read-only
        date_str = static_baselinks.get(url, {}).get("date", info.get("date", ""))
        d_part, t_part = parse_stored_datetime(date_str)

        placement_date = compute_placement_date(url, title, date_str, static_baselinks)

        year_month = (placement_date.year, placement_date.month)
        week_num = get_week_of_month(placement_date)

        organized[year_month][week_num].append((url, title, d_part, t_part))

    return organized


def format_email_body(campaigns_to_display, static_baselinks, has_new: bool):
    plain_lines = []
    html_lines = []

    if not has_new:
        plain_lines.append("Nicio campanie noua")
        html_lines.append("<p>Nicio campanie noua</p>")
        plain_text = "\n".join(plain_lines)
        html_text = "<html><body>" + "".join(html_lines) + "</body></html>"
        return plain_text, html_text

    organized = organize_by_month_week(campaigns_to_display, static_baselinks)

    now = datetime.now()
    current_ym = (now.year, now.month)
    prev_ym = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)

    month_names = ["", "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
                   "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"]

    def print_month_block(ym_tuple, label):
        year, month = ym_tuple
        month_name = month_names[month]

        plain_lines.append(f"{label}:")
        plain_lines.append("")
        html_lines.append(f"<p><strong>{label}:</strong></p>")

        if ym_tuple not in organized:
            plain_lines.append("N/A")
            plain_lines.append("")
            html_lines.append("<p>N/A</p>")
            return

        plain_lines.append(f"{month_name.capitalize()}, {year}")
        plain_lines.append("")
        html_lines.append(f"<p><strong>{month_name.capitalize()}, {year}</strong></p>")

        weeks = sorted(organized[ym_tuple].keys(), reverse=True)

        for week_num in weeks:
            plain_lines.append(f"Week {week_num}, {month_name.capitalize()}, {year}")
            html_lines.append(f"<p><strong>Week {week_num}, {month_name.capitalize()}, {year}</strong></p>")

            for url, title, d_part, t_part in organized[ym_tuple][week_num]:
                suffix = f" [ {d_part} -> {t_part} ]" if d_part and t_part else ""
                plain_lines.append(title + suffix)
                html_lines.append(f'<p><a href="{url}">{title}</a>{suffix}</p>')

            plain_lines.append("")
            html_lines.append("<p>&nbsp;</p>")

    print_month_block(current_ym, "Current month")
    plain_lines.append("")
    html_lines.append("<br/>")
    print_month_block(prev_ym, "Previous month")

    plain_text = "\n".join(plain_lines)
    html_text = "<html><body>" + "".join(html_lines) + "</body></html>"
    return plain_text, html_text


# =========================================
# EMAIL (RESEND)
# =========================================

def send_email(subject: str, body_plain: str, body_html: str):
    if not RESEND_API_KEY:
        debug("RESEND_API_KEY missing. Skipping email send.")
        return

    from_addr = RESEND_FROM or RESEND_FROM_FALLBACK

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": from_addr,
        "to": [TO_EMAIL],
        "subject": subject,
        "text": body_plain,
        "html": body_html,
    }

    try:
        r = requests.post(RESEND_URL, headers=headers, json=payload, timeout=30)
        if r.status_code >= 400:
            debug(f"Resend error {r.status_code}: {r.text[:300]}")
            return
        debug("Email sent successfully via Resend.")
    except Exception as e:
        debug(f"Resend request error: {e!r}")


# =========================================
# MAIN
# =========================================

def main():
    debug("=== OLX Campanii monitor start ===")
    script_dir = get_script_dir()

    static_file = os.path.join(script_dir, "olx_baseline_links_read_only.json")
    aura_ever_file = os.path.join(script_dir, "aura_links_updating_every_run.json")
    new_campaigns_file = os.path.join(script_dir, "new_olx_campaigns.json")

    static_baselinks = load_static_baselinks(static_file)
    all_aura_ever = load_all_aura_ever(aura_ever_file)

    current_aura = fetch_campaign_links_from_aura()

    live_new_urls = [url for url in current_aura if url not in all_aura_ever]
    has_new = bool(live_new_urls)

    now_iso = datetime.now().isoformat(timespec='seconds') + "Z"
    for url, info in current_aura.items():
        current_date = info.get("date", "").strip()
        if url not in all_aura_ever:
            new_info = info.copy()
            if not current_date:
                new_info["date"] = now_iso
            all_aura_ever[url] = new_info
        else:
            all_aura_ever[url]["title"] = info["title"]
            if current_date:
                all_aura_ever[url]["date"] = current_date

    save_all_aura_ever(aura_ever_file, all_aura_ever)

    new_campaigns = {url: all_aura_ever[url] for url in all_aura_ever if url not in static_baselinks}
    save_new_campaigns(new_campaigns_file, new_campaigns)

    # Display source - baselinks au prioritate absolută pentru date
    display_sources = static_baselinks.copy()
    aura_only = {url: info for url, info in all_aura_ever.items() if url not in static_baselinks}
    display_sources.update(aura_only)

    display_campaigns = {}

    # Campanii noi - cu datele lor reale
    for url in live_new_urls:
        display_campaigns[url] = all_aura_ever[url]

    # Restul din current/prev - pentru baselinks folosim întotdeauna datele din fișierul read-only
    now = datetime.now()
    current_ym = (now.year, now.month)
    prev_ym = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)

    for url, info in display_sources.items():
        if url in display_campaigns:
            continue
        title = info.get("title", "")
        date_str = static_baselinks.get(url, info).get("date", info.get("date", ""))
        placement_date = compute_placement_date(url, title, date_str, static_baselinks)
        ym = (placement_date.year, placement_date.month)

        if ym in (current_ym, prev_ym):
            baseline_info = static_baselinks.get(url, info)
            display_campaigns[url] = baseline_info

    now_str = now.strftime("%d-%m-%Y %H:%M")
    subject = f"Campanii noi OLX <> {now_str}" if has_new else f"Nu există campanii noi OLX <> {now_str}"

    body_plain, body_html = format_email_body(display_campaigns, static_baselinks, has_new)
    send_email(subject, body_plain, body_html)

    debug("=== OLX Campanii monitor end ===")


if __name__ == "__main__":
    main()
