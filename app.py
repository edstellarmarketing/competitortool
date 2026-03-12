import streamlit as st
import requests
from bs4 import BeautifulSoup, Comment, NavigableString
from io import BytesIO
from urllib.parse import urlparse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import re
import time

st.set_page_config(page_title="L&D Page Body Extractor", page_icon="🔍", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f8f9fb; }
    .main-title { font-size: 2rem; font-weight: 700; color: #1a1a2e; margin-bottom: 0.2rem; }
    .sub-title { font-size: 1rem; color: #555; margin-bottom: 1.5rem; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🔍 L&D Competitor Page Body Extractor</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Paste competitor URLs → Extract main body content (no header/nav/footer) → Export to Excel</div>', unsafe_allow_html=True)

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

HEADERS_REQ = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REMOVE_TAG_NAMES = ["header", "nav", "footer", "noscript", "iframe", "script", "style", "svg"]

NOISE_PATTERNS = re.compile(
    r"nav|header|footer|menu|sidebar|cookie|consent|banner|popup|modal|"
    r"social-share|breadcrumb|skip|onetrust|recaptcha|grecaptcha|"
    r"top-bar|mega-menu|mobile-menu|site-footer|site-header",
    re.IGNORECASE
)


def is_noise_element(tag):
    if isinstance(tag, NavigableString):
        return False
    if not hasattr(tag, "get"):
        return False
    try:
        classes = tag.get("class", None)
        if classes:
            class_str = " ".join(classes) if isinstance(classes, list) else str(classes)
            if NOISE_PATTERNS.search(class_str):
                return True
        tag_id = tag.get("id", None)
        if tag_id and NOISE_PATTERNS.search(str(tag_id)):
            return True
        role = tag.get("role", None)
        if role and str(role).lower() in ("navigation", "banner", "contentinfo"):
            return True
    except Exception:
        pass
    return False


def extract_body_content(html_text, as_text=False):
    soup = BeautifulSoup(html_text, "html.parser")

    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    for tag_name in REMOVE_TAG_NAMES:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(["img", "picture"]):
        tag.decompose()

    to_remove = []
    for tag in soup.find_all(True):
        if is_noise_element(tag):
            to_remove.append(tag)
    for tag in to_remove:
        try:
            tag.decompose()
        except Exception:
            pass

    main_content = None
    main_content = soup.find("main")
    if not main_content:
        main_content = soup.find("article")
    if not main_content:
        main_content = soup.find("div", attrs={"role": "main"})
    if not main_content:
        for div in soup.find_all("div"):
            div_id = div.get("id", "") or ""
            if re.search(r"content|main", div_id, re.IGNORECASE):
                main_content = div
                break
    if not main_content:
        for div in soup.find_all("div"):
            classes = div.get("class", [])
            class_str = " ".join(classes) if isinstance(classes, list) else str(classes)
            if re.search(r"content|main|page-body|entry-content", class_str, re.IGNORECASE):
                main_content = div
                break
    if not main_content:
        main_content = soup.find("body")
    if not main_content:
        main_content = soup

    if as_text:
        text = main_content.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    else:
        html_out = str(main_content)
        html_out = re.sub(r"\n{3,}", "\n\n", html_out)
        return html_out.strip()


def fetch_and_extract(url, timeout_sec, as_text):
    try:
        resp = requests.get(url, headers=HEADERS_REQ, timeout=timeout_sec, allow_redirects=True)
        resp.raise_for_status()
        content = extract_body_content(resp.text, as_text)
        return {"url": url, "status": "success", "content": content, "code": resp.status_code}
    except requests.exceptions.Timeout:
        return {"url": url, "status": "error", "content": f"Timeout after {timeout_sec}s", "code": None}
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else None
        return {"url": url, "status": "error", "content": f"HTTP Error {code}", "code": code}
    except Exception as e:
        return {"url": url, "status": "error", "content": f"Error: {str(e)}", "code": None}


def get_domain(url):
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").replace("services.", "")
        parts = domain.split(".")
        return parts[0].capitalize() if parts else url
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
    center = Alignment(wrap_text=True, vertical="center", horizontal="center")
    border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )

    col_headers = ["S.No", "Company", "URL", "Body Content"]
    col_widths = {"A": 6, "B": 20, "C": 55, "D": 160}

    for i, h in enumerate(col_headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = center
        c.border = border

    for col_letter, w in col_widths.items():
        ws.column_dimensions[col_letter].width = w

    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"

    for idx, r in enumerate(results, 1):
        row = idx + 1
        domain = get_domain(r["url"])
        content = r["content"][:32000] if r["content"] else ""
        values = [idx, domain, r["url"], content]
        for col, val in enumerate(values, 1):
            c = ws.cell(row=row, column=col, value=val)
            c.font = body_font
            c.alignment = wrap
            c.border = border
        ws.row_dimensions[row].height = 400

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─── Sidebar ───
with st.sidebar:
    st.header("⚙️ Settings")
    timeout = st.slider("Request timeout (seconds)", 5, 30, 15)
    output_format = st.radio("Content output format", ["HTML (raw body)", "Plain Text"])
    st.markdown("---")
    st.markdown("**How it works:**")
    st.markdown(
        "1. Fetches each URL\n"
        "2. Parses HTML with BeautifulSoup\n"
        "3. Removes header, nav, footer, cookies, scripts, images\n"
        "4. Extracts the main/article/content div\n"
        "5. Exports to a 4-column Excel"
    )

# ─── Main UI ───
urls_input = st.text_area("📋 Paste URLs (one per line):", value=DEFAULT_URLS, height=280)

col1, col2, _ = st.columns([1, 1, 3])
with col1:
    run_btn = st.button("🚀 Extract All", type="primary", use_container_width=True)
with col2:
    if st.button("🗑️ Clear", use_container_width=True):
        st.session_state.pop("results", None)
        st.rerun()

if run_btn:
    urls = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]
    if not urls:
        st.error("Please enter at least one URL.")
    else:
        as_text = output_format == "Plain Text"
        results = []
        progress = st.progress(0, text="Starting...")
        for i, url in enumerate(urls):
            progress.progress(i / len(urls), text=f"Fetching {i+1}/{len(urls)}: {get_domain(url)}...")
            result = fetch_and_extract(url, timeout, as_text)
            results.append(result)
            time.sleep(0.5)
        progress.progress(1.0, text="✅ Done!")
        st.session_state["results"] = results

# ─── Results ───
if "results" in st.session_state:
    results = st.session_state["results"]
    success_count = sum(1 for r in results if r["status"] == "success")
    error_count = len(results) - success_count

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total URLs", len(results))
    c2.metric("✅ Success", success_count)
    c3.metric("❌ Failed", error_count)

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
        status_icon = "✅" if r["status"] == "success" else "❌"
        content_len = len(r["content"]) if r["content"] else 0

        with st.expander(f"{status_icon} {domain} — {content_len:,} chars", expanded=False):
            st.caption(r["url"])
            if r["status"] == "success":
                preview = r["content"][:5000]
                if len(r["content"]) > 5000:
                    preview += "\n\n... [truncated — full content in Excel]"
                if output_format == "Plain Text":
                    st.text(preview)
                else:
                    st.code(preview, language="html")
            else:
                st.error(r["content"])
