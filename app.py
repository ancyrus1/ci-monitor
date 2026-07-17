import streamlit as st
import pandas as pd
import io
import re
import hashlib
import base64
import requests
import matplotlib.pyplot as plt
from datetime import datetime

st.set_page_config(page_title='CI Monitor', page_icon='⚙️', layout='wide')

ACCENT = '#3b82f6'

st.markdown(f'''
<style>
.block-container {{padding-top: 3rem;}}

.brand {{display:flex; align-items:center; gap:10px; margin-bottom:18px;}}
.brand-icon {{
    width:34px; height:34px; border-radius:9px; background:{ACCENT};
    display:flex; align-items:center; justify-content:center; font-weight:800; color:white; font-size:1rem;
}}
.brand-title {{font-size:1.15rem; font-weight:800; color:#f3f4f6;}}
.sidebar-footer {{font-size:.78rem; opacity:.6; margin-top:4px;}}

.dash-title {{font-size:1.9rem; font-weight:800; margin:0;}}
.dash-subtitle {{opacity:.65; font-size:.9rem; margin-top:4px;}}

.kpi-card {{
    border:1px solid rgba(120,120,120,.18); border-radius:16px; padding:18px 18px 14px 18px;
    background:rgba(127,127,127,.05); min-height:150px; position:relative; overflow:hidden;
}}
.kpi-icon {{
    width:36px; height:36px; border-radius:10px; display:flex; align-items:center; justify-content:center;
    font-size:1.05rem; margin-bottom:10px;
}}
.kpi-label {{font-size:.72rem; opacity:.65; text-transform:uppercase; letter-spacing:.03em; margin-bottom:2px;}}
.kpi-value {{font-size:1.9rem; font-weight:800; margin-top:2px; line-height:1.15;}}
.kpi-note {{font-size:.76rem; opacity:.6; margin-top:5px;}}
.note {{border-left:4px solid {ACCENT}; padding:10px 12px; background:rgba(59,130,246,.08); border-radius:6px;}}

/* Multiselect tag pills — override Streamlit's default red to match the accent color */
span[data-baseweb="tag"] {{
    background-color:{ACCENT} !important;
    color:white !important;
}}
span[data-baseweb="tag"] svg {{
    fill:white !important;
}}
</style>
''', unsafe_allow_html=True)

# -----------------------------------------------------------------------
# DATA LAYER
# Expected columns (from the issue tracker export):
#   Issue ID, Status, Failure Category, Short Message, Error Description,
#   Recommended Fix, Workflow Name, Branch, Failed Stage, Build URL,
#   Created Time, Run
#
# Run        -> Success / Fail  (the CI run outcome)
# Status     -> Open / Resolve  (whether the failure has been fixed)
# -----------------------------------------------------------------------

REQUIRED_COLS = [
    'Issue ID', 'Status', 'Failure Category', 'Short Message',
    'Error Description', 'Recommended Fix', 'Workflow Name', 'Branch',
    'Failed Stage', 'Build URL', 'Created Time', 'Run'
]

# Set this once and the dashboard loads automatically on every run — no manual pasting needed.
DEFAULT_SHEET_URL = 'https://docs.google.com/spreadsheets/d/1xtWH0PqfvNa0xH-ECc2czkDruKJbQqmhs7NRdCvPnYg/edit?usp=sharing'


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        st.error(f"Missing expected column(s): {', '.join(missing)}. "
                 f"Found columns: {', '.join(df.columns)}")
        st.stop()

    df['Status'] = df['Status'].astype(str).str.strip().str.title()
    df['Status'] = df['Status'].replace({'Resolve': 'Resolved'})
    df['Run'] = df['Run'].astype(str).str.strip().str.title()
    df['Failure Category'] = df['Failure Category'].astype(str).str.strip().str.rstrip(',')
    df['Workflow Name'] = df['Workflow Name'].astype(str).str.strip()
    df['Branch'] = df['Branch'].astype(str).str.strip()

    return df


def _extract_sheet_id(share_url: str) -> str:
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', share_url)
    if not match:
        raise ValueError('That doesn\'t look like a Google Sheets link (expected .../spreadsheets/d/<id>/...).')
    return match.group(1)


@st.cache_data(ttl=300, show_spinner='Fetching latest data from Google Sheets...')
def load_sheet_from_url(share_url: str):
    sheet_id = _extract_sheet_id(share_url)
    csv_url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'
    resp = requests.get(csv_url, timeout=20)
    if resp.status_code != 200 or resp.text.strip().startswith('<'):
        raise RuntimeError(
            'Could not download the sheet as CSV. Make sure sharing is set to '
            '"Anyone with the link" → Viewer (File → Share → General access).'
        )
    df = pd.read_csv(io.StringIO(resp.text))
    return _clean_columns(df)


@st.cache_data
def load_excel(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    return _clean_columns(df)


def sparkline_svg(color, seed_text, width=140, height=28):
    # Deterministic decorative trend line (illustrative only — the sheet has no
    # per-day history to plot a real trend from). Seeded so it's stable per card.
    seed = int(hashlib.md5(seed_text.encode()).hexdigest(), 16)
    n = 10
    pts = []
    val = 0.5
    for i in range(n):
        seed = (seed * 1103515245 + 12345) & 0x7fffffff
        val += ((seed % 1000) / 1000 - 0.5) * 0.6
        val = max(0.05, min(0.95, val))
        x = i / (n - 1) * width
        y = height - (val * height)
        pts.append(f'{x:.1f},{y:.1f}')
    points = ' '.join(pts)
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'style="display:block;margin-top:10px;">'
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/></svg>')


def kpi(label, value, note, icon, icon_bg, icon_color, value_color='#f3f4f6'):
    spark = sparkline_svg(icon_color, label)
    st.markdown(f"""
    <div class='kpi-card'>
        <div class='kpi-icon' style='background:{icon_bg}; color:{icon_color};'>{icon}</div>
        <div class='kpi-label'>{label}</div>
        <div class='kpi-value' style='color:{value_color};'>{value}</div>
        <div class='kpi-note'>{note}</div>
        {spark}
    </div>
    """, unsafe_allow_html=True)


def _donut_image_b64(labels, values, colors, title_center):
    total = sum(values)
    fig, ax = plt.subplots(figsize=(2.3, 2.3), dpi=220)
    fig.patch.set_alpha(0)
    ax.set_facecolor('none')

    if total == 0:
        ax.pie([1], colors=['#374151'], wedgeprops={'width': 0.4, 'edgecolor': '#11182a', 'linewidth': 1.5})
    else:
        ax.pie(
            values, colors=colors, startangle=90, counterclock=False,
            wedgeprops={'width': 0.4, 'edgecolor': '#11182a', 'linewidth': 1.5}
        )
    ax.text(0, 0.10, f'{total:,}', ha='center', va='center', fontsize=18, fontweight='bold', color='white')
    ax.text(0, -0.16, title_center, ha='center', va='center', fontsize=8.5, color='#9ca3af')
    ax.axis('equal')
    plt.tight_layout(pad=0.15)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=220, transparent=True, bbox_inches='tight', pad_inches=0.03)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _legend_html(labels, values, colors):
    total = sum(values)
    html = ''
    for lab, val, col in zip(labels, values, colors):
        pct = (val / total * 100) if total else 0
        html += (
            f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:9px;font-size:.84rem;white-space:nowrap;'>"
            f"<span style='width:9px;height:9px;border-radius:50%;background:{col};display:inline-block;flex-shrink:0;'></span>"
            f"<span style='color:#e5e7eb;min-width:62px;'>{lab}</span>"
            f"<span style='color:#f3f4f6;font-weight:700;'>{val:,}</span>"
            f"<span style='color:#9ca3af;'>({pct:.0f}%)</span>"
            f"</div>"
        )
    return html


def donut_card_row(chart_a, chart_b, img_width=170):
    """Render two donut+legend cards side by side, responsive to window width.
    Cards flex-grow to share available space (min 340px each) and only wrap
    to stacked when the window is genuinely too narrow to fit both.
    IMPORTANT: every line must start with zero leading whitespace — Markdown
    treats 4+ leading spaces as a literal code block, which breaks HTML
    rendering (this bit us once already)."""
    card_parts = []
    for chart in (chart_a, chart_b):
        b64 = _donut_image_b64(chart['labels'], chart['values'], chart['colors'], chart['center'])
        legend = _legend_html(chart['labels'], chart['values'], chart['colors'])
        card = (
            f"<div style='flex:1 1 340px; max-width:520px; border:1px solid rgba(120,120,120,.18); border-radius:16px; "
            f"background:rgba(127,127,127,.05); padding:20px; box-sizing:border-box;'>"
            f"<div style='font-size:1.15rem; font-weight:800; color:#f3f4f6; margin-bottom:16px;'>{chart['title']}</div>"
            f"<div style='display:flex; align-items:center; justify-content:center; gap:22px; flex-wrap:wrap;'>"
            f"<img src='data:image/png;base64,{b64}' width='{img_width}' style='flex-shrink:0;'/>"
            f"<div>{legend}</div>"
            f"</div>"
            f"</div>"
        )
        card_parts.append(card)

    wrapper = (
        f"<div style='display:flex; gap:24px; flex-wrap:wrap;'>"
        f"{''.join(card_parts)}"
        f"</div>"
    )
    st.markdown(wrapper, unsafe_allow_html=True)


# -----------------------------------------------------------------------
# SIDEBAR — brand + nav + data source status
# Nav is plain HTML links (not st.button) so we have full control over
# styling — Streamlit's built-in button CSS is unreliable to override.
# -----------------------------------------------------------------------
NAV_ITEMS = [
    ('Overview', '▦'),
    ('Full logs', '▤'),
    ('Data source', '⚙'),
]

try:
    current_page = st.query_params.get('page', 'Overview')
except Exception:
    current_page = st.experimental_get_query_params().get('page', ['Overview'])[0]

if current_page not in [n for n, _ in NAV_ITEMS]:
    current_page = 'Overview'

nav_html = f"""
<div class='brand'>
    <div class='brand-icon'>C</div>
    <div class='brand-title'>CI Monitor</div>
</div>
<div style='margin-bottom:14px;'>
"""
for name, icon in NAV_ITEMS:
    is_active = (name == current_page)
    bg = 'rgba(59,130,246,.16)' if is_active else 'transparent'
    color = ACCENT if is_active else '#cbd5e1'
    weight = 700 if is_active else 500
    nav_html += (
        f"<a href='?page={name.replace(' ', '+')}' target='_self' "
        f"style='display:block; text-decoration:none; background:{bg}; color:{color}; "
        f"font-weight:{weight}; border-radius:10px; padding:9px 12px; margin-bottom:4px; "
        f"font-size:.95rem;'>{icon}&nbsp;&nbsp;&nbsp;{name}</a>"
    )
nav_html += "</div>"
st.sidebar.markdown(nav_html, unsafe_allow_html=True)

page = current_page

st.sidebar.markdown('<hr style="margin:1.2rem 0;opacity:.15;">', unsafe_allow_html=True)

# -----------------------------------------------------------------------
# DATA LOADING — runs regardless of which page is active, so Overview /
# Full logs always have data even if the user never visits Data source.
# -----------------------------------------------------------------------
if 'sheet_url' not in st.session_state:
    st.session_state['sheet_url'] = DEFAULT_SHEET_URL
if 'source_mode' not in st.session_state:
    st.session_state['source_mode'] = 'Google Sheet link'

df = None
load_error = None

if st.session_state['source_mode'] == 'Google Sheet link':
    try:
        df = load_sheet_from_url(st.session_state['sheet_url'])
        st.session_state['last_updated'] = datetime.now()
    except Exception as e:
        load_error = str(e)
else:
    uploaded_bytes = st.session_state.get('uploaded_bytes')
    if uploaded_bytes:
        df = load_excel(uploaded_bytes)
        st.session_state['last_updated'] = datetime.now()

last_updated = st.session_state.get('last_updated')
st.sidebar.markdown(f"""
<div class='sidebar-footer'>
    📅 Last updated<br>{last_updated.strftime('%b %d, %Y %I:%M %p') if last_updated else '—'}
</div>
""", unsafe_allow_html=True)

if df is None:
    st.title('CI Monitor')
    if load_error:
        st.error('Could not load data.')
        st.code(load_error)
    else:
        st.info('Go to the Data source page to connect a Google Sheet or upload an Excel file.')
    st.stop()

# -----------------------------------------------------------------------
# Shared lookups
# -----------------------------------------------------------------------
all_workflows = sorted(df['Workflow Name'].dropna().unique())
all_branches = sorted(df['Branch'].dropna().unique())

# -----------------------------------------------------------------------
# PAGE: DATA SOURCE
# -----------------------------------------------------------------------
if page == 'Data source':
    st.markdown("<div class='dash-title'>Data source</div>", unsafe_allow_html=True)
    st.markdown("<div class='dash-subtitle'>Connect and manage where CI Monitor reads its data from.</div>", unsafe_allow_html=True)
    st.write("")

    mode = st.radio('Load from', ['Google Sheet link', 'Manual upload'],
                     index=0 if st.session_state['source_mode'] == 'Google Sheet link' else 1)
    st.session_state['source_mode'] = mode

    if mode == 'Google Sheet link':
        url = st.text_input('Google Sheet share link (anyone with the link can view)',
                             value=st.session_state['sheet_url'])
        c1, c2 = st.columns([1, 4])
        with c1:
            if st.button('🔄 Refresh now'):
                st.session_state['sheet_url'] = url
                load_sheet_from_url.clear()
                st.rerun()
        if url != st.session_state['sheet_url']:
            st.session_state['sheet_url'] = url
            st.rerun()
        st.caption('Auto-refreshes every 5 minutes. Sharing must be set to "Anyone with the link → Viewer".')
    else:
        uploaded = st.file_uploader('Upload issue tracker Excel (.xlsx)', type=['xlsx', 'xls'])
        if uploaded is not None:
            st.session_state['uploaded_bytes'] = uploaded.getvalue()
            st.rerun()

    st.write("")
    if load_error:
        st.error('Could not load data.')
        st.code(load_error)
    else:
        st.markdown(f"<div class='note'>✅ Connected — {len(df):,} rows loaded, "
                    f"{len(all_workflows)} workflow(s), {len(all_branches)} branch(es).</div>",
                    unsafe_allow_html=True)

    st.caption('Expected columns: ' + ', '.join(REQUIRED_COLS))

# -----------------------------------------------------------------------
# PAGE: OVERVIEW
# -----------------------------------------------------------------------
elif page == 'Overview':
    fdf = df

    total_runs = len(fdf)
    success_runs = (fdf['Run'] == 'Success').sum()
    failed_runs = (fdf['Run'] == 'Fail').sum()
    success_rate = (success_runs / total_runs * 100) if total_runs else 0

    issues = fdf
    open_issues = issues[issues['Status'] == 'Open']
    resolved_issues = issues[issues['Status'] == 'Resolved']
    resolved_rate = (len(resolved_issues) / len(issues) * 100) if len(issues) else 0

    header_left, header_right = st.columns([3, 1])
    with header_left:
        st.markdown(f"""
        <div class='dash-title'>CI Pipeline Health</div>
        <div class='dash-subtitle'>Overview of your CI pipeline performance and issue resolution &middot; {total_runs:,} runs loaded</div>
        """, unsafe_allow_html=True)
    with header_right:
        st.write("")
        st.download_button('⬇️ Export Report', fdf.to_csv(index=False).encode(), 'ci_pipeline_report.csv', 'text/csv', width='stretch')

    c = st.columns(4)
    with c[0]:
        kpi('Total runs', f'{total_runs:,}', f'{len(all_workflows)} workflow(s)',
            '▶', 'rgba(96,165,250,.15)', '#60a5fa')
    with c[1]:
        kpi('Success rate', f'{success_rate:.1f}%', f'{success_runs:,} successful runs',
            '✓', 'rgba(52,211,153,.15)', '#34d399', value_color='#34d399')
    with c[2]:
        kpi('Issues detected', f'{len(open_issues):,}', f'{len(issues):,} total tracked',
            '⚠', 'rgba(251,191,36,.15)', '#fbbf24', value_color='#fbbf24')
    with c[3]:
        kpi('Resolved', f'{len(resolved_issues):,}', f'{resolved_rate:.0f}% resolution rate',
            '✓', 'rgba(167,139,250,.15)', '#a78bfa', value_color='#a78bfa')

    st.markdown("<div style='height:22px;'></div>", unsafe_allow_html=True)

    if total_runs or len(issues):
        chart_a = {
            'title': 'Successful vs failed runs',
            'center': 'runs',
            'labels': ['Success', 'Fail'],
            'values': [success_runs, failed_runs],
            'colors': ['#34d399', '#f87171'],
        }
        chart_b = {
            'title': 'Open vs resolved issues',
            'center': 'issues',
            'labels': ['Open', 'Resolved'],
            'values': [len(open_issues), len(resolved_issues)],
            'colors': ['#fbbf24', '#60a5fa'],
        }
        donut_card_row(chart_a, chart_b)
    else:
        st.info('No data in the current filter.')

    st.write("")
    st.subheader('Recent runs')
    recent = fdf.tail(3).iloc[::-1][['Issue ID', 'Status', 'Branch', 'Short Message']]
    st.dataframe(recent, hide_index=True, width='stretch')

# -----------------------------------------------------------------------
# PAGE: FULL LOGS
# -----------------------------------------------------------------------
else:
    st.markdown("<div class='dash-title'>Full logs</div>", unsafe_allow_html=True)
    st.write("")

    filter_cols = ['Status', 'Branch', 'Run']
    selected = {}

    with st.expander('🔍 Filters', expanded=False):
        cols = st.columns(len(filter_cols))
        for c, colname in zip(cols, filter_cols):
            with c:
                options = sorted(df[colname].dropna().astype(str).unique())
                selected[colname] = st.multiselect(colname, options, default=options, key=f'filt_{colname}')

    mask = pd.Series(True, index=df.index)
    for colname, chosen in selected.items():
        mask &= df[colname].astype(str).isin(chosen)
    log = df[mask]

    st.caption(f'{len(log):,} rows')
    st.dataframe(log, hide_index=True, width='stretch')
    st.download_button('⬇️ Download CSV', log.to_csv(index=False).encode(), 'ci_full_log.csv', 'text/csv')

st.divider()
st.caption('Data refreshes automatically from the configured source. Change it anytime from the Data source page.')