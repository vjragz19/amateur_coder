#!/usr/bin/env python3
"""Scrape Pipedream + Composio app names and list apps missing from Composio."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from playwright.async_api import async_playwright, Page


DEFAULT_PIPEDREAM_URL = "https://pipedream.com/explore"
DEFAULT_COMPOSIO_URL = "https://composio.dev/toolkits"

PIPEDREAM_SELECTORS = [
    "a[href^='/apps/']",
    "[data-testid*='app'] a",
    "[data-testid*='App'] a",
    "[class*='app'] a",
]

COMPOSIO_SELECTORS = [
    "a[href^='/toolkits/']",
    "[data-testid*='toolkit'] a",
    "[class*='toolkit'] a",
]

SKIP_PHRASES = {
    "explore",
    "apps",
    "workflows",
    "toolkits",
    "integration",
    "integrations",
    "browse",
    "learn more",
    "view all",
}


@dataclass
class ScrapeResult:
    source: str
    url: str
    raw_names: List[str]

    @property
    def normalized(self) -> List[str]:
        return sorted({normalize_name(name) for name in self.raw_names if name})


async def auto_scroll(page: Page, max_scrolls: int, pause_ms: int) -> None:
    last_height = await page.evaluate("() => document.body.scrollHeight")
    for _ in range(max_scrolls):
        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(pause_ms)
        new_height = await page.evaluate("() => document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name).strip()
    cleaned = re.sub(r"[^\w\s\-+&.]", "", cleaned)
    cleaned = cleaned.lower()
    cleaned = cleaned.replace("+", " plus ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned in SKIP_PHRASES:
        return ""
    return cleaned


def filter_names(names: Iterable[str]) -> List[str]:
    filtered = []
    for name in names:
        cleaned = normalize_name(name)
        if not cleaned:
            continue
        if len(cleaned) < 2:
            continue
        filtered.append(name.strip())
    return filtered


def find_names_in_json(data: object, key_hints: Sequence[str]) -> List[str]:
    hits: List[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in key_hints and isinstance(value, str):
                    hits.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return hits


async def extract_names(page: Page, selectors: Sequence[str], key_hints: Sequence[str]) -> List[str]:
    collected: List[str] = []
    for selector in selectors:
        names = await page.eval_on_selector_all(
            selector,
            """
            (elements) => elements
              .map((el) => el.textContent || el.getAttribute('aria-label') || '')
              .map((text) => text.trim())
              .filter(Boolean)
            """,
        )
        collected.extend(names)

    if collected:
        return filter_names(collected)

    for candidate in ("__NEXT_DATA__", "__NUXT__"):
        data = await page.evaluate("(key) => window[key] || null", candidate)
        if not data:
            continue
        collected.extend(find_names_in_json(data, key_hints))

    return filter_names(collected)


async def scrape_site(
    page: Page,
    url: str,
    source: str,
    selectors: Sequence[str],
    key_hints: Sequence[str],
    max_scrolls: int,
    pause_ms: int,
) -> ScrapeResult:
    await page.goto(url, wait_until="networkidle")
    await auto_scroll(page, max_scrolls=max_scrolls, pause_ms=pause_ms)
    names = await extract_names(page, selectors=selectors, key_hints=key_hints)
    return ScrapeResult(source=source, url=url, raw_names=sorted(set(names)))


def write_output(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

def write_html_report(path: Path, payload: dict) -> None:
    missing = payload.get("missing_in_composio", [])
    rows = "\n".join(
        f"<tr><td>{index + 1}</td><td>{name}</td></tr>" for index, name in enumerate(missing)
    )
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Apps missing from Composio</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 2rem; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; }}
      th {{ background: #f5f5f5; text-align: left; }}
      caption {{ caption-side: bottom; padding-top: 0.75rem; color: #555; }}
    </style>
  </head>
  <body>
    <h1>Apps missing from Composio</h1>
    <p>Count: {len(missing)}</p>
    <table>
      <thead>
        <tr><th>#</th><th>App name</th></tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
      <caption>Generated by scrape_apps.py</caption>
    </table>
  </body>
</html>
"""
    path.write_text(html, encoding="utf-8")


async def run(args: argparse.Namespace) -> int:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.show)
        page = await browser.new_page()

        pipedream_result = await scrape_site(
            page,
            url=args.pipedream_url,
            source="pipedream",
            selectors=PIPEDREAM_SELECTORS,
            key_hints=["name", "app", "appname"],
            max_scrolls=args.max_scrolls,
            pause_ms=args.pause_ms,
        )

        composio_result = await scrape_site(
            page,
            url=args.composio_url,
            source="composio",
            selectors=COMPOSIO_SELECTORS,
            key_hints=["name", "toolkit", "toolkitname"],
            max_scrolls=args.max_scrolls,
            pause_ms=args.pause_ms,
        )

        await browser.close()

    pipedream_normalized = set(pipedream_result.normalized)
    composio_normalized = set(composio_result.normalized)

    missing_in_composio = sorted(
        name for name in pipedream_normalized if name and name not in composio_normalized
    )

    output = {
        "pipedream": {
            "url": pipedream_result.url,
            "count": len(pipedream_result.raw_names),
            "normalized_count": len(pipedream_normalized),
            "names": pipedream_result.raw_names,
        },
        "composio": {
            "url": composio_result.url,
            "count": len(composio_result.raw_names),
            "normalized_count": len(composio_normalized),
            "names": composio_result.raw_names,
        },
        "missing_in_composio": missing_in_composio,
    }

    output_path = Path(args.output)
    write_output(output_path, output)
    if args.html_report:
        write_html_report(Path(args.html_report), output)

    print(f"Pipedream apps scraped: {len(pipedream_result.raw_names)}")
    print(f"Composio apps scraped: {len(composio_result.raw_names)}")
    print(f"Missing in Composio: {len(missing_in_composio)}")
    print(f"Output written to: {output_path}")
    if args.html_report:
        print(f"HTML report written to: {args.html_report}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape Pipedream + Composio app catalogs and list apps missing from Composio."
        )
    )
    parser.add_argument("--pipedream-url", default=DEFAULT_PIPEDREAM_URL)
    parser.add_argument("--composio-url", default=DEFAULT_COMPOSIO_URL)
    parser.add_argument("--max-scrolls", type=int, default=60)
    parser.add_argument("--pause-ms", type=int, default=750)
    parser.add_argument("--output", default="apps_missing_from_composio.json")
    parser.add_argument("--html-report", help="Write an HTML report to this path.")
    parser.add_argument("--show", action="store_true", help="Run with a visible browser.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
