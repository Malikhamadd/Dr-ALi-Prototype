#!/usr/bin/env python3
"""Post-process a `wget --mirror` download of a Webflow site.

- Finds external asset URLs (CSS/JS/images/fonts) referenced by mirrored HTML/CSS.
- Downloads those assets into a local `assets/` directory.
- Rewrites mirrored HTML/CSS to reference local copies for offline editing.

Usage:
  python3 tools/mirror_webflow.py mirror/videa-saversion.webflow.io
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


SKIP_HOSTS = {
    "www.w3.org",
    "w3.org",
    "www.linkedin.com",
}


ASSET_EXTENSIONS = {
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp4",
    ".webm",
    ".pdf",
    ".json",
}


URL_RE = re.compile(r"https?://[^\"'<>\s)]+")
CSS_URL_RE = re.compile(r"url\((?P<q>['\"]?)(?P<u>.*?)(?P=q)\)")

# Seen in some Webflow mirrors: inline styles end up with
#   url(https://site.webflow.io/&quot;assets/foo.png&quot;)
# Normalize those to local `assets/foo.png`.
BROKEN_LOCAL_ASSET_RE = re.compile(
    r'https?://videa-saversion\.webflow\.io/(?:[^\s"\']*/)?(?:&quot;|"|%22)(assets/[^"&%<>\s)]+)(?:&quot;|"|%22)',
    re.IGNORECASE,
)


def _relative_assets_prefix(site_root: Path, html_path: Path) -> str:
    """Return a relative prefix from `html_path` to the root-level `assets/`.

    Example:
      - <root>/index.html -> "assets/"
      - <root>/news/foo.html -> "../assets/"
    """

    rel = html_path.resolve().relative_to(site_root)
    depth = max(0, len(rel.parts) - 1)
    return ("../" * depth) + "assets/"


def _rewrite_nested_local_asset_refs(site_root: Path, html_path: Path) -> bool:
    """Fix local `assets/...` refs inside nested HTML pages (e.g. `news/*.html`).

    `wget` mirrors commonly preserve HTML where pages under subfolders reference
    `assets/...`, which then incorrectly resolves to `subfolder/assets/...`.
    """

    prefix = _relative_assets_prefix(site_root, html_path)
    if prefix == "assets/":
        return False

    original = html_path.read_text(errors="ignore")
    updated = original

    # HTML attrs
    updated = updated.replace('src="assets/', f'src="{prefix}')
    updated = updated.replace("src='assets/", f"src='{prefix}")
    updated = updated.replace('href="assets/', f'href="{prefix}')
    updated = updated.replace("href='assets/", f"href='{prefix}")

    # srcset
    updated = updated.replace('srcset="assets/', f'srcset="{prefix}')
    updated = updated.replace("srcset='assets/", f"srcset='{prefix}")

    # inline CSS url()
    updated = updated.replace('url(assets/', f'url({prefix}')
    updated = updated.replace('url("assets/', f'url("{prefix}')
    updated = updated.replace("url('assets/", f"url('{prefix}")

    # Handle already-escaped variants (rare but seen in mirrors)
    updated = updated.replace('src=&quot;assets/', f'src=&quot;{prefix}')
    updated = updated.replace('href=&quot;assets/', f'href=&quot;{prefix}')
    updated = updated.replace('srcset=&quot;assets/', f'srcset=&quot;{prefix}')
    updated = updated.replace('url(&quot;assets/', f'url(&quot;{prefix}')

    if updated != original:
        html_path.write_text(updated)
        return True

    return False


def _iter_files(root: Path, suffixes: set[str]) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in suffixes:
            files.append(p)
    return sorted(files)


def _extract_urls_from_text(text: str) -> set[str]:
    decoded = html.unescape(text)
    urls = set(URL_RE.findall(decoded))
    return urls


def _is_asset_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    host = (parsed.hostname or "").lower()
    if not host or host in SKIP_HOSTS:
        return False

    # Ignore same-site page links; those should already be local after wget.
    if host.endswith("videa-saversion.webflow.io"):
        return False

    path = parsed.path or ""
    ext = Path(path).suffix.lower()
    if ext in ASSET_EXTENSIONS:
        return True

    # Webflow sometimes serves CSS/JS with no extension in rare cases; keep it strict.
    return False


def _safe_filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name
    if not name:
        # Fallback: hash the full URL.
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    # Strip anything weird (very conservative).
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)

    # If query string exists, disambiguate but keep readable filename.
    if parsed.query:
        qhash = hashlib.sha256(parsed.query.encode("utf-8")).hexdigest()[:8]
        stem, ext = os.path.splitext(name)
        name = f"{stem}.{qhash}{ext}" if ext else f"{stem}.{qhash}"

    if len(name) > 180:
        base, ext = os.path.splitext(name)
        name = base[:150] + ext

    return name


def _download(url: str, dest: Path, user_agent: str, retries: int = 2) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "*/*",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            dest.write_bytes(data)
            return True
        except urllib.error.HTTPError as e:
            # Permanent failure (404 etc) — don’t retry too much.
            if e.code in {400, 401, 403, 404}:
                return False
            if attempt >= retries:
                return False
        except Exception:
            if attempt >= retries:
                return False

        time.sleep(1.0 + attempt)

    return False


def _rewrite_in_file(path: Path, replacements: dict[str, str]) -> bool:
    original = path.read_text(errors="ignore")
    updated = original

    # Replace both decoded and HTML-escaped forms.
    for src, dst in replacements.items():
        updated = updated.replace(src, dst)
        updated = updated.replace(html.escape(src, quote=True), dst)

    # Fix broken local asset quoting artifacts.
    updated = BROKEN_LOCAL_ASSET_RE.sub(r"\1", updated)

    if updated != original:
        path.write_text(updated)
        return True

    return False


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 tools/mirror_webflow.py <mirror_site_root>")
        return 2

    site_root = Path(sys.argv[1]).resolve()
    if not site_root.exists() or not site_root.is_dir():
        print(f"Site root not found: {site_root}")
        return 2

    assets_dir = site_root / "assets"

    html_files = _iter_files(site_root, {".html"})
    if not html_files:
        print(f"No .html files found under {site_root}")
        return 2

    user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

    # 1) Gather asset URLs from mirrored HTML.
    urls: set[str] = set()
    for f in html_files:
        urls |= _extract_urls_from_text(f.read_text(errors="ignore"))

    asset_urls = sorted(u for u in urls if _is_asset_url(u))
    print(f"Found {len(asset_urls)} external asset URLs")

    # 2) Download assets and build replacement maps.
    #    - HTML should reference assets as: assets/<filename>
    #    - CSS/JS inside assets/ should reference sibling files as: <filename>
    filename_by_url: dict[str, str] = {}
    downloaded = 0
    failed = 0

    for url in asset_urls:
        filename = _safe_filename_from_url(url)
        dest = assets_dir / filename

        if dest.exists() and dest.stat().st_size > 0:
            filename_by_url[url] = filename
            continue

        ok = _download(url, dest, user_agent=user_agent)
        if ok:
            downloaded += 1
            filename_by_url[url] = filename
        else:
            failed += 1

    print(f"Downloaded {downloaded} assets ({failed} failed)")

    replacements_html: dict[str, str] = {u: f"assets/{fn}" for u, fn in filename_by_url.items()}
    replacements_assets: dict[str, str] = {u: fn for u, fn in filename_by_url.items()}

    # 3) Rewrite HTML to point at local assets.
    rewritten_html = 0
    for f in html_files:
        changed = _rewrite_in_file(f, replacements_html)
        changed = _rewrite_nested_local_asset_refs(site_root, f) or changed
        if changed:
            rewritten_html += 1

    print(f"Rewrote {rewritten_html}/{len(html_files)} HTML files")

    # 4) Scan downloaded text assets (CSS/JS) for additional external URLs, download + rewrite.
    css_files = _iter_files(assets_dir, {".css"})
    js_files = _iter_files(assets_dir, {".js"})

    discovered_urls: set[str] = set()

    # CSS: url(...) references
    for css in css_files:
        txt = css.read_text(errors="ignore")
        for m in CSS_URL_RE.finditer(txt):
            raw = m.group("u").strip()
            if raw.startswith("data:"):
                continue
            if raw.startswith("//"):
                raw = "https:" + raw
            if raw.startswith("http://") or raw.startswith("https://"):
                discovered_urls.add(raw)

    # JS: any embedded URLs
    for js in js_files:
        discovered_urls |= _extract_urls_from_text(js.read_text(errors="ignore"))

    discovered_asset_urls = sorted(u for u in discovered_urls if _is_asset_url(u))
    if discovered_asset_urls:
        print(f"Found {len(discovered_asset_urls)} additional asset URLs (CSS/JS)")

    for url in discovered_asset_urls:
        filename = _safe_filename_from_url(url)
        dest = assets_dir / filename

        if not dest.exists() or dest.stat().st_size == 0:
            ok = _download(url, dest, user_agent=user_agent)
            if not ok:
                continue
        filename_by_url[url] = filename

    # Refresh replacement maps after discovery.
    replacements_html = {u: f"assets/{fn}" for u, fn in filename_by_url.items()}
    replacements_assets = {u: fn for u, fn in filename_by_url.items()}

    rewritten_css = 0
    for css in css_files:
        changed = _rewrite_in_file(css, replacements_assets)

        # Webflow-exported CSS sometimes references sibling assets via `url("assets/<file>")`.
        # Since we store the CSS itself in `assets/`, that would incorrectly resolve to
        # `/assets/assets/<file>`. Normalize to `url("<file>")`.
        txt = css.read_text(errors="ignore")
        fixed = (
            txt.replace('url("assets/', 'url("')
            .replace("url('assets/", "url('")
            .replace('url(assets/', 'url(')
        )
        if fixed != txt:
            css.write_text(fixed)
            changed = True

        if changed:
            rewritten_css += 1

    rewritten_js = 0
    for js in js_files:
        if _rewrite_in_file(js, replacements_assets):
            rewritten_js += 1

    if css_files:
        print(f"Rewrote {rewritten_css}/{len(css_files)} CSS files")
    if js_files:
        print(f"Rewrote {rewritten_js}/{len(js_files)} JS files")

    print("Done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
