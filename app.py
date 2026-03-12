import streamlit as st
import requests
from bs4 import BeautifulSoup, Comment
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import re
import time

# ─── Page Config ───
st.set_page_config(page_title="L&D Page Body Extractor", page_icon="🔍", layout="wide")

# ─── Custom CSS ───
st.markdown("""
<style>
    .stApp { background-color: #f8f9fb; }
    .main-title { font-size: 2rem; font-weight: 700; color: #1a1a2e; margin-bottom: 0.2rem; }
    .sub-title { font-size: 1rem; color: #555; margin-bottom: 1.5rem; }
    .status-box { padding: 0.6rem 1rem; border-radius: 8px; margin-bottom: 0.5rem; font-size: 0.9rem; }
    .success-box { background: #e8f5e9; color: #2e7d32; border-left: 4px solid #43a047; }
    .error-box { background: #fce4ec; color: #c62828; border-left: 4px solid #e53935; }
    .info-box { background: #e3f2fd; color: #1565c0; border-left: 4px solid #1e88e5; }
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 0.5rem; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🔍 L&D Competitor Page Body Extractor</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Paste competitor URLs → Extract main body content (no header/nav/footer) → Export to Excel</div>', unsafe_allow_html=True)

# ─── Default URLs ───
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

# ─── Sidebar Settings ───
with st.sidebar:
    st.header("⚙️ Settings")
    timeout = st.slider("Request timeout (seconds)", 5, 30, 15)
    strip_images = st.checkbox("Strip image tags", value=True)
    strip_scripts = st.checkbox("Strip script/style tags", value=True)
    output_format = st.radio("Content output format", ["HTML (raw body)", "Plain Text"])
    st.markdown("---")
    st.markdown("**How it works:**")
    st.markdown("""
    1. Fetches each URL
    2. Parses the HTML with BeautifulSoup
    3. Removes `<header>`, `<nav>`, `<footer>`, cookie banners, script/style tags
    4. Extracts the remaining `<main>` or primary body content
    5. Exports to a 3-column Excel
    """)


# ─── Core extraction logic ───
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Tags to remove entirely
REMOVE_TAGS = ["header", "nav", "footer", "noscript", "iframe"]
REMOVE_CLASSES_PATTERNS = [
    r"nav", r"header", r"footer", r"menu", r"sidebar",
    r"cookie", r"consent", r"banner", r"popup", r"modal",
    r"social", r"share", r"breadcrumb", r"skip-link",
    r"onetrust", r"recaptcha", r"grecaptcha",
]
REMOVE_IDS_PATTERNS = [
    r"nav", r"header", r"footer", r"menu", r"sidebar",
    r"cookie", r"consent", r"onetrust",
]


def should_remove_element(tag):
    """Check if an element should be removed based on class/id patterns."""
    classes = " ".join(tag.get("class", []))
    tag_id = tag.get("id", "") or ""
    combined = f"{classes} {tag_id}".lower()
    for pattern in REMOVE_CLASSES_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return True
    return False


def extract_body_content(html_text, url, strip_imgs=True, strip_js=True, as_text=False):
    """Extract main body content, stripping header/nav/footer/menus."""
    soup = BeautifulSoup(html_text, "lxml")

    # Remove comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Remove script and style tags
    if strip_js:
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()

    # Remove standard structural tags
    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove elements by class/id patterns
    for tag in soup.find_all(True):
        if should_remove_element(tag):
            tag.decompose()

    # Remove image tags if requested
    if strip_imgs:
        for img in soup.find_all("img"):
            img.decompose()
        for svg in soup.find_all("svg"):
            svg.decompose()
        for picture in soup.find_all("picture"):
            picture.decompose()

    # Try to find main content container
    main_content = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", {"role": "main"})
        or soup.find("div", id=re.compile(r"content|main", re.I))
        or soup.find("div", class_=re.compile(r"content|main|page-body|entry", re.I))
    )

    if main_content is None:
        # Fallback: use body
        main_content = soup.find("body") or soup

    # Clean up excessive whitespace in the result
    if as_text:
        text = main_content.get_text(separator="\n", strip=True)
        # Collapse multiple blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    else:
        # Return cleaned HTML
        html_out = str(main_content)
        # Remove excessive blank lines
        html_out = re.sub(r"\n{3,}", "\n\n", html_out)
        return html_out.strip()


def fetch_and_extract(url, timeout_sec, strip_imgs, strip_js, as_text):
    """Fetch a URL and extract body content."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout_sec, allow_redirects=True)
        resp.raise_for_status()
        content = extract_body_content(resp.text, url, strip_imgs, strip_js, as_text)
        return {"url": url, "status": "success", "content": content, "status_code": resp.status_code}
    except requests.exceptions.Timeout:
        return {"url": url, "status": "error", "content": f"Timeout after {timeout_sec}s", "status_code": None}
    except requests.exceptions.HTTPError as e:
        return {"url": url, "status": "error", "content": f"HTTP Error: {e}", "status_code": getattr(e.response, 'status_code', None)}
    except Exception as e:
        return {"url": url, "status": "error", "content": f"Error: {str(e)}", "status_code": None}


def get_domain(url):
    """Extract domain name from URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "").replace("services.", "")
    return domain.split(".")[0].capitalize() if domain else url


def build_excel(results):
    """Build Excel workbook from results."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Page Body Content"

    # Styles
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

    headers = ["S.No", "Company", "URL", "Body Content"]
    widths = [6, 20, 55, 160]

    for i, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = center
        c.border = border
        ws.column_dimensions[chr(64 + i) if i <= 4 else "D"].width = w

    # Correct column widths for D
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 55
    ws.column_dimensions["D"].width = 160

    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"

    for idx, r in enumerate(results, 1):
        row = idx + 1
        domain = get_domain(r["url"])
        # Truncate content to ~32000 chars (Excel cell limit is 32767)
        content = r["content"][:32000] if r["content"] else ""

        for col, val in enumerate([idx, domain, r["url"], content], 1):
            c = ws.cell(row=row, column=col, value=val)
            c.font = body_font
            c.alignment = wrap
            c.border = border

        ws.row_dimensions[row].height = 400

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─── Main UI ───
urls_input = st.text_area(
    "📋 Paste URLs (one per line):",
    value=DEFAULT_URLS,
    height=280,
    help="Enter one URL per line. The app will fetch each page and extract only the main body content."
)

col1, col2, col3 = st.columns([1, 1, 3])
with col1:
    run_btn = st.button("🚀 Extract All", type="primary", use_container_width=True)
with col2:
    clear_btn = st.button("🗑️ Clear Results", use_container_width=True)

if clear_btn:
    st.session_state.pop("results", None)
    st.rerun()

if run_btn:
    urls = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]
    if not urls:
        st.error("Please enter at least one URL.")
    else:
        as_text = output_format == "Plain Text"
        results = []
        progress = st.progress(0, text="Starting extraction...")

        for i, url in enumerate(urls):
            progress.progress((i) / len(urls), text=f"Fetching {i+1}/{len(urls)}: {get_domain(url)}...")
            result = fetch_and_extract(url, timeout, strip_images, strip_scripts, as_text)
            results.append(result)
            time.sleep(0.3)  # polite delay

        progress.progress(1.0, text="✅ Done!")
        st.session_state["results"] = results

# ─── Display Results ───
if "results" in st.session_state:
    results = st.session_state["results"]

    # Summary
    success_count = sum(1 for r in results if r["status"] == "success")
    error_count = len(results) - success_count

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total URLs", len(results))
    c2.metric("✅ Success", success_count)
    c3.metric("❌ Failed", error_count)

    # Download button
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

    for i, r in enumerate(results):
        domain = get_domain(r["url"])
        status_icon = "✅" if r["status"] == "success" else "❌"
        content_len = len(r["content"]) if r["content"] else 0

        with st.expander(f"{status_icon} {domain} — {content_len:,} chars", expanded=False):
            st.caption(r["url"])
            if r["status"] == "success":
                # Show preview (first 3000 chars)
                preview = r["content"][:3000]
                if len(r["content"]) > 3000:
                    preview += "\n\n... [truncated in preview, full content in Excel]"
                if output_format == "Plain Text":
                    st.text(preview)
                else:
                    st.code(preview, language="html")
            else:
                st.markdown(f'<div class="status-box error-box">{r["content"]}</div>', unsafe_allow_html=True)
