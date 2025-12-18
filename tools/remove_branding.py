#!/usr/bin/env python3

import argparse
import os
import re
from pathlib import Path


def iter_html_files(root: Path):
    for path in root.rglob("*.html"):
        if path.is_file():
            yield path


def safe_read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def safe_write_text(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def build_rename_map(site_root: Path) -> dict[Path, Path]:
    assets = site_root / "assets"
    news = site_root / "news"

    rename_map: dict[Path, Path] = {}

    # Core Webflow bundles (rename to remove brand from asset URLs)
    css_old = assets / "videa-saversion.9b1352011.css"
    js_old = assets / "videa-saversion.d9a4b8013.js"
    if css_old.exists():
        rename_map[css_old] = assets / "site.9b1352011.css"
    if js_old.exists():
        rename_map[js_old] = assets / "site.d9a4b8013.js"

    # Asset images with videa in filename
    for old_name in [
        "63b86b66011d4fd93a44a1a7_videa_insights.jpg",
        "63b86b66011d4fd27044a1c7_videa_detect.jpg",
        "63b86b66011d4fd27044a1c7_videa_detect-p-1080.jpeg",
    ]:
        old_path = assets / old_name
        if old_path.exists():
            new_name = old_name.replace("_videa_", "_").replace("videa_", "")
            rename_map[old_path] = assets / new_name

    # News pages containing videahealth in filename
    if news.exists():
        for old_path in news.glob("*videahealth*.html"):
            new_name = old_path.name
            new_name = new_name.replace("-with-videahealth-to-", "-to-")
            new_name = new_name.replace("-videahealth-", "-")
            new_name = new_name.replace("videahealth-", "")
            new_name = new_name.replace("-videahealth", "")
            new_name = re.sub(r"-{2,}", "-", new_name)
            rename_map[old_path] = old_path.with_name(new_name)

    return rename_map


def validate_rename_map(rename_map: dict[Path, Path]):
    targets = set()
    for src, dst in rename_map.items():
        if src == dst:
            raise SystemExit(f"Refusing noop rename: {src}")
        if dst in targets:
            raise SystemExit(f"Two renames target the same destination: {dst}")
        targets.add(dst)
        if dst.exists() and dst not in rename_map:
            raise SystemExit(f"Destination already exists: {dst}")


def apply_rewrites(text: str) -> str:
    # Links / contact details
    text = re.sub(
        r"mailto:contact@videa\.ai\?subject=Videa%20Health%20Contact%20Form",
        "mailto:contact@example.com?subject=Contact%20Form",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"contact\s*@videa\.ai", "contact@example.com", text, flags=re.IGNORECASE)

    # Remove brand-specific outbound links
    text = re.sub(r"https?://(www\.)?videa\.ai/?", "#", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://jobs\.lever\.co/videahealth[^\"']*", "#", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://www\.linkedin\.com/company/videahealth/?", "#", text, flags=re.IGNORECASE)

    # Titles / meta that include brand prefix
    text = re.sub(r"<title>\s*Videa\s*-\s*", "<title>", text)
    text = re.sub(r"(content=\")\s*Videa\s*-\s*", r"\1", text)
    text = re.sub(r"<title>\s*Videa\s+Press\s*-\s*", "<title>Press - ", text)
    text = re.sub(r"(content=\")\s*Videa\s+Press\s*-\s*", r"\1Press - ", text)

    # Remove brand name from common phrases (best-effort)
    text = re.sub(r"\bVideaHealth\b", "the company", text)
    text = re.sub(r"\bVidea\s+Health\b", "the company", text)
    text = re.sub(r"\bVidea\s+Healthcare\b", "Healthcare", text)

    text = re.sub(r"\bVidea\s+Team\b", "Our Team", text)
    text = re.sub(r"\bVidea\s+Detect\b", "Detect", text)
    text = re.sub(r"\bVidea\s+Insights\b", "Insights", text)

    # CamelCase product names
    text = text.replace("VideaDetect", "Detect")
    text = text.replace("VideaTeach", "Teach")

    # Possessive cases
    text = re.sub(r"\bVidea(?:Health)?[’']s\b", "our", text)

    # Any remaining standalone Videa word
    text = re.sub(r"\bVidea\b", "", text)

    # Remove webflow domain attribute if it still contains the brand
    text = text.replace('data-wf-domain="videa-saversion.webflow.io"', 'data-wf-domain=""')

    return text


def main():
    parser = argparse.ArgumentParser(description="Remove Videa branding from mirrored site")
    parser.add_argument("--root", default="mirror/videa-saversion.webflow.io", help="Site root")
    parser.add_argument("--apply", action="store_true", help="Write changes and rename files")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    site_root = (repo_root / args.root).resolve()

    if not site_root.exists():
        raise SystemExit(f"Site root not found: {site_root}")

    rename_map = build_rename_map(site_root)
    validate_rename_map(rename_map)

    # Replace references by basename (works for both root and /news pages)
    basename_map = {src.name: dst.name for src, dst in rename_map.items()}
    # Also update Webflow slugs which are file stems.
    stem_map = {src.stem: dst.stem for src, dst in rename_map.items() if src.suffix.lower() == ".html"}

    changed_files = 0
    for path in iter_html_files(site_root):
        original = safe_read_text(path)
        updated = original

        for old_base, new_base in basename_map.items():
            updated = updated.replace(old_base, new_base)
        for old_stem, new_stem in stem_map.items():
            updated = updated.replace(old_stem, new_stem)

        updated = apply_rewrites(updated)

        if updated != original:
            changed_files += 1
            if args.apply:
                safe_write_text(path, updated)

    # Update the main CSS bundle only if it exists (for renamed background images)
    css_src = site_root / "assets" / "videa-saversion.9b1352011.css"
    css_dst = rename_map.get(css_src)
    if css_src.exists():
        css_original = safe_read_text(css_src)
        css_updated = css_original
        for old_base, new_base in basename_map.items():
            css_updated = css_updated.replace(old_base, new_base)
        if css_updated != css_original:
            changed_files += 1
            if args.apply:
                safe_write_text(css_src, css_updated)

    if args.apply:
        # Rename files after content updates
        for src, dst in sorted(rename_map.items(), key=lambda kv: len(str(kv[0])), reverse=True):
            if src.exists():
                os.rename(src, dst)

    action = "Applied" if args.apply else "Dry-run"
    print(f"{action}: updated {changed_files} text files")
    if rename_map:
        print(f"{action}: planned {len(rename_map)} renames")
        for src, dst in rename_map.items():
            print(f" - {src.relative_to(site_root)} -> {dst.relative_to(site_root)}")


if __name__ == "__main__":
    main()
