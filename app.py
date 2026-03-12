import streamlit as st
import requests
import trafilatura
from trafilatura.settings import use_config
from bs4 import BeautifulSoup, Comment, NavigableString
from io import BytesIO
from urllib.parse import urlparse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import re
import time

# ───────────────────────────────────────────────
# Page Config
# ───────────────────────────────────────────────
st.set_page_config(page_title="L&D Page Body Extractor", page_icon="🔍", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f8f9fb; }
    h1 { font-size: 1.8rem !important; font-weight: 700; color: #1a1a2e; }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

st.title("🔍 L&D Competitor Page Body Extractor")
st.caption("Paste competitor URLs → Extract main body content (no header/nav/footer) → Export to Excel")

# ───────────────────────────────────────────────
# Default URLs
# ───────────────────────────────────────────────
DEFAULT_URLS = """https://cmoe.com/products-and-services/learning-and-development-advisory-services/
https://www.ey.com/en_gl/services/workforce/learning-development-advisory
https://www.optimuslearningservices.com/l-and-d-services/consult/
https://www.eidesign.net/ld-consulting/
https://wdhb.com/services/strategy-design-consulting/
https://www.futuristsspeakers.com/learning-development-consulting-services/
https://www.hemsleyfraser.com/en-us/consultancy-services
https://www.thinkdom.co/learning-and-development-consulting
https://www.wipro.com/consulting/learning-and-development-consulting-services/
https://services.elblearning.com/learning-and-development-consulting"""

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Trafilatura config: be generous with content extraction
TRAF_CONFIG = use_config()
TRAF_CONFIG.set("DEFAULT", "MIN_OUTPUT_SIZE", "100")
TRAF_CONFIG.set("DEFAULT", "MIN_EXTRACTED_SIZE", "100")


# ───────────────────────────────────────────────
# Extraction Methods
# ───────────────────────────────────────────────

def fetch_html(url, timeout_sec):
    """Fetch raw HTML from a URL with browser-like headers."""
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    resp = session.get(url, timeout=timeout_sec, allow_redirects=True)
    resp.raise_for_status()
    return resp.text, resp.status_code


def extract_with_trafilatura(html, output_fmt="txt"):
    """
    Primary extraction: trafilatura.
    Handles boilerplate removal (nav, footer, sidebar, ads) automatically.
    Returns clean text or XML/HTML.
    """
    result = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        include_links=True,
        include_images=False,
        include_formatting=True,
        favor_recall=True,       # extract more content rather than less
        output_format=output_fmt,
        config=TRAF_CONFIG,
    )
    return result


def extract_with_beautifulsoup(html):
    """
    Fallback extraction: BeautifulSoup.
    Strips known non-content elements and returns remaining text.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove comments
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    # Remove non-content tags
    for tag_name in ["script", "style", "header", "nav", "footer",
                     "noscript", "iframe", "svg", "img", "picture"]:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove elements with nav/footer/menu/cookie classes or ids
    noise_re = re.compile(
        r"nav|header|footer|menu|sidebar|cookie|consent|banner|popup|modal|"
        r"breadcrumb|skip|onetrust|social-share|mega-menu|site-footer|site-header",
        re.IGNORECASE
    )
    to_remove = []
    for tag in soup.find_all(True):
        if isinstance(tag, NavigableString) or not hasattr(tag, "get"):
            continue
        classes = tag.get("class", [])
        class_str = " ".join(classes) if isinstance(classes, list) else str(classes or "")
        tag_id = str(tag.get("id", "") or "")
        role = str(tag.get("role", "") or "").lower()
        if noise_re.search(class_str) or noise_re.search(tag_id) or role in ("navigation", "banner", "contentinfo"):
            to_remove.append(tag)
    for tag in to_remove:
        try:
            tag.decompose()
        except Exception:
            pass

    # Find main content container
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", attrs={"role": "main"})
        or soup.find("div", id=re.compile(r"content|main", re.I))
        or soup.find("div", class_=re.compile(r"content|main|page-body|entry", re.I))
        or soup.find("body")
        or soup
    )

    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_content(url, timeout_sec, output_mode):
    """
    Master extraction function.
    Strategy:
      1. Fetch raw HTML
      2. Try trafilatura (purpose-built for main content extraction)
      3. If trafilatura returns empty/too short, fallback to BeautifulSoup
    """
    try:
        html, status_code = fetch_html(url, timeout_sec)
    except requests.exceptions.Timeout:
        return {"url": url, "status": "error", "content": f"⏱ Timeout after {timeout_sec}s", "method": "none"}
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        return {"url": url, "status": "error", "content": f"HTTP {code} error", "method": "none"}
    except Exception as e:
        return {"url": url, "status": "error", "content": f"Fetch error: {str(e)[:200]}", "method": "none"}

    # Attempt 1: trafilatura
    fmt = "txt" if output_mode == "Plain Text" else "txt"
    content = extract_with_trafilatura(html, fmt)

    method = "trafilatura"

    # If trafilatura fails or returns too little, fallback
    if not content or len(content.strip()) < 150:
        content = extract_with_beautifulsoup(html)
        method = "beautifulsoup"

    # Final safety check
    if not content or len(content.strip()) < 50:
        content = f"[Extraction returned minimal content. Raw HTML was {len(html):,} chars. The site may require JavaScript rendering.]"
        method = "failed"

    return {
        "url": url,
        "status": "success" if method != "failed" else "warning",
        "content": content.strip(),
        "method": method,
    }


# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────

def get_domain(url):
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").replace("services.", "")
        return domain.split(".")[0].capitalize()
    except Exception:
        return url


def build_excel(results):
    wb = Workbook()
    ws = wb.active
    ws.title = "Page Body Content"

    hdr_font = Font(name="Arial", bold=True, color="FFFFFF", size=11)
    hdr_fill = PatternFill("solid", fgColor="1F4E79")
    body_font = Font(name="Arial", size=9)
    wrap = Alignment(wrap_text=True, vertical="top")
    center_wrap = Alignment(wrap_text=True, vertical="center", horizontal="center")
    border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )

    headers = ["S.No", "Company", "URL", "Extraction Method", "Body Content"]
    widths = {"A": 6, "B": 18, "C": 52, "D": 16, "E": 160}

    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = center_wrap
        c.border = border

    for letter, w in widths.items():
        ws.column_dimensions[letter].width = w

    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"

    for idx, r in enumerate(results, 1):
        row = idx + 1
        domain = get_domain(r["url"])
        content = r["content"][:32000] if r["content"] else ""
        method = r.get("method", "unknown")

        for col, val in enumerate([idx, domain, r["url"], method, content], 1):
            c = ws.cell(row=row, column=col, value=val)
            c.font = body_font
            c.alignment = wrap
            c.border = border

        ws.row_dimensions[row].height = 400

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ───────────────────────────────────────────────
# Sidebar
# ───────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    timeout = st.slider("Request timeout (sec)", 5, 30, 15)
    output_mode = st.radio("Output format", ["Plain Text", "HTML body"])
    st.markdown("---")
    st.subheader("How it works")
    st.markdown(
        "**Step 1:** Fetches each URL with browser-like headers\n\n"
        "**Step 2:** Extracts body content using **trafilatura** — "
        "a purpose-built library that automatically removes nav, header, "
        "footer, sidebars, ads, and boilerplate\n\n"
        "**Step 3:** If trafilatura returns too little, falls back to "
        "**BeautifulSoup** with pattern-based noise removal\n\n"
        "**Step 4:** Exports everything to a clean Excel file"
    )


# ───────────────────────────────────────────────
# Main UI
# ───────────────────────────────────────────────
urls_input = st.text_area("📋 Paste URLs (one per line):", value=DEFAULT_URLS, height=260)

col1, col2, _ = st.columns([1, 1, 3])
with col1:
    run_btn = st.button("🚀 Extract All", type="primary", use_container_width=True)
with col2:
    if st.button("🗑️ Clear Results", use_container_width=True):
        st.session_state.pop("results", None)
        st.rerun()

if run_btn:
    urls = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]
    if not urls:
        st.error("Please enter at least one URL.")
    else:
        results = []
        progress = st.progress(0, text="Starting extraction...")

        for i, url in enumerate(urls):
            domain = get_domain(url)
            progress.progress(i / len(urls), text=f"Fetching {i+1}/{len(urls)}: {domain}...")
            result = extract_page_content(url, timeout, output_mode)
            results.append(result)
            time.sleep(0.5)

        progress.progress(1.0, text="✅ All done!")
        st.session_state["results"] = results


# ───────────────────────────────────────────────
# Display Results
# ───────────────────────────────────────────────
if "results" in st.session_state:
    results = st.session_state["results"]

    success = sum(1 for r in results if r["status"] == "success")
    warnings = sum(1 for r in results if r["status"] == "warning")
    errors = sum(1 for r in results if r["status"] == "error")

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(results))
    c2.metric("✅ Extracted", success)
    c3.metric("⚠️ Partial", warnings)
    c4.metric("❌ Failed", errors)

    excel_buf = build_excel(results)
    st.download_button(
        label="📥 Download Excel",
        data=excel_buf,
        file_name="LD_Competitor_Body_Content.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

    st.markdown("---")
    st.subheader("📄 Extracted Content Preview")

    for r in results:
        domain = get_domain(r["url"])
        content_len = len(r["content"]) if r["content"] else 0
        method = r.get("method", "?")

        if r["status"] == "success":
            icon = "✅"
        elif r["status"] == "warning":
            icon = "⚠️"
        else:
            icon = "❌"

        label = f"{icon} {domain} — {content_len:,} chars (via {method})"

        with st.expander(label, expanded=False):
            st.caption(r["url"])
            if r["status"] == "error":
                st.error(r["content"])
            else:
                preview = r["content"][:8000]
                if content_len > 8000:
                    preview += "\n\n... [truncated — full content in Excel download]"
                st.text(preview)
