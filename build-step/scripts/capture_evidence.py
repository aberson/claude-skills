"""Playwright evidence capture script for build-step.

Launches headless Chromium, navigates pages, captures screenshots/console/video/HAR,
optionally runs an exercise script, then saves all evidence to --output-dir.

Project-agnostic — exercise scripts provide project-specific interactions.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

try:
    from playwright.async_api import ConsoleMessage, Page, async_playwright
except ImportError:
    print("ERROR: Playwright not installed.")
    print("Run: pip install playwright && playwright install chromium")
    sys.exit(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Capture UI evidence via Playwright")
    p.add_argument("--url", required=True, help="Base URL of the app")
    p.add_argument(
        "--pages",
        default=None,
        help='JSON array of URLs to screenshot (default: ["<url>"])',
    )
    p.add_argument("--exercise", default=None, help="Absolute path to exercise script")
    p.add_argument("--output-dir", required=True, help="Where to save evidence")
    p.add_argument("--viewport", default="1920x1080", help="WxH viewport size")
    p.add_argument("--record-video", action="store_true", help="Enable video recording")
    p.add_argument("--record-har", action="store_true", help="Record HAR network archive")
    p.add_argument(
        "--page-wait",
        type=float,
        default=3,
        help="Seconds to wait after navigation for networkidle",
    )
    p.add_argument(
        "--exercise-timeout",
        type=float,
        default=30,
        help="Max seconds for exercise script",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="Max seconds for initial page load",
    )
    args = p.parse_args(argv)

    if args.pages is None:
        args.pages = [args.url]
    else:
        args.pages = json.loads(args.pages)

    width, height = args.viewport.split("x")
    args.viewport_width = int(width)
    args.viewport_height = int(height)

    return args


def _page_label(url: str) -> str:
    """Derive a short label from a URL for filenames.

    http://localhost:5173          -> 'root'
    http://localhost:5173/#/stats  -> 'stats'
    http://localhost:5173/#/build-orders -> 'build-orders'
    """
    fragment = url.split("#")[-1] if "#" in url else ""
    if fragment and fragment != "/":
        return fragment.strip("/").replace("/", "-")
    path = url.split("://", 1)[-1].split("/", 1)
    if len(path) > 1 and path[1].strip("/"):
        return path[1].strip("/").replace("/", "-")
    return "root"


class ConsoleCollector:
    """Collects browser console messages, tagged by page URL."""

    def __init__(self) -> None:
        self._entries: list[dict[str, str]] = []
        self._start = time.monotonic()

    def handle(self, msg: ConsoleMessage) -> None:
        elapsed = time.monotonic() - self._start
        self._entries.append(
            {
                "time": f"{elapsed:07.3f}",
                "type": msg.type,
                "url": msg.location.get("url", "unknown") if msg.location else "unknown",
                "text": msg.text,
            }
        )

    def entries_for_url(self, page_url: str) -> list[dict[str, str]]:
        """Return entries whose source URL starts with the given page URL."""
        return [e for e in self._entries if e["url"].startswith(page_url)]

    def format_entries(self, entries: list[dict[str, str]] | None = None) -> str:
        entries = entries if entries is not None else self._entries
        lines: list[str] = []
        for e in entries:
            lines.append(f"[{e['time']}] [{e['type']}] [{e['url']}] {e['text']}")
        return "\n".join(lines)


def _load_exercise(path: str) -> object:
    """Load an exercise module from an absolute file path."""
    spec = importlib.util.spec_from_file_location("exercise_module", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load exercise from {path}")
    mod = importlib.util.module_from_spec(spec)
    # Add the exercise's parent directory to sys.path so local imports work.
    parent = str(Path(path).parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec.loader.exec_module(mod)
    return mod


async def _screenshot_pages(
    page: Page,
    pages: list[str],
    output_dir: Path,
    suffix: str,
    page_wait: float,
    timeout: float,
) -> None:
    """Navigate to each URL and take a full-page screenshot."""
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    for idx, url in enumerate(pages):
        label = _page_label(url)
        await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
        # Additional wait for any late-arriving data
        await page.wait_for_timeout(page_wait * 1000)
        filename = f"page-{label}-{idx + 1:02d}-{suffix}.png"
        await page.screenshot(path=str(screenshots_dir / filename), full_page=True)


async def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    console = ConsoleCollector()

    async with async_playwright() as pw:
        browser_args: dict = {
            "headless": True,
        }

        # Video recording requires a persistent context with a video dir.
        # HAR recording also uses the context-level option.
        context_args: dict = {
            "viewport": {"width": args.viewport_width, "height": args.viewport_height},
        }

        if args.record_video:
            video_dir = output_dir / "video"
            video_dir.mkdir(parents=True, exist_ok=True)
            context_args["record_video_dir"] = str(video_dir)
            context_args["record_video_size"] = {
                "width": args.viewport_width,
                "height": args.viewport_height,
            }

        if args.record_har:
            context_args["record_har_path"] = str(output_dir / "network.har")

        browser = await pw.chromium.launch(**browser_args)
        context = await browser.new_context(**context_args)
        page = await context.new_page()

        # Attach console listener — persists across navigations.
        page.on("console", console.handle)

        # Step 5: Navigate to base URL, wait for networkidle.
        try:
            await page.goto(args.url, wait_until="networkidle", timeout=args.timeout * 1000)
        except Exception as exc:
            print(f"ERROR: Initial page load failed: {exc}", file=sys.stderr)
            await context.close()
            await browser.close()
            return 1

        # Step 6: Screenshot all pages — initial state.
        await _screenshot_pages(
            page, args.pages, output_dir, "initial", args.page_wait, args.timeout
        )

        # Step 7: Run exercise script if provided.
        exercise_timed_out = False
        if args.exercise:
            exercise_mod = _load_exercise(args.exercise)
            run_fn = getattr(exercise_mod, "run", None)
            if run_fn is None:
                print(
                    f"ERROR: Exercise script {args.exercise} has no run(page) function",
                    file=sys.stderr,
                )
                await context.close()
                await browser.close()
                return 1

            start_t = time.monotonic()
            try:
                await asyncio.wait_for(
                    run_fn(page), timeout=args.exercise_timeout
                )
            except TimeoutError:
                elapsed = time.monotonic() - start_t
                exercise_timed_out = True
                timeout_path = output_dir / "exercise-timeout.txt"
                timeout_path.write_text(
                    f"Exercise timed out after {elapsed:.1f}s "
                    f"(limit: {args.exercise_timeout}s)\n"
                    f"Script: {args.exercise}\n"
                )
                print(
                    f"WARNING: Exercise timed out after {elapsed:.1f}s",
                    file=sys.stderr,
                )
            except Exception as exc:
                error_path = output_dir / "exercise-error.txt"
                error_path.write_text(f"Exercise failed: {exc}\nScript: {args.exercise}\n")
                print(f"WARNING: Exercise failed: {exc}", file=sys.stderr)

        # Step 8: Screenshot all pages — after exercise.
        await _screenshot_pages(
            page, args.pages, output_dir, "after-exercise", args.page_wait, args.timeout
        )

        # Write per-page console logs.
        for url in args.pages:
            label = _page_label(url)
            entries = console.entries_for_url(url)
            if entries:
                log_path = output_dir / f"console-{label}.log"
                log_path.write_text(console.format_entries(entries), encoding="utf-8")

        # Write combined console log.
        combined = console.format_entries()
        (output_dir / "console.log").write_text(combined, encoding="utf-8")

        # Close context to finalize video/HAR recordings.
        await context.close()
        await browser.close()

    # Print summary.
    screenshots = list((output_dir / "screenshots").glob("*.png"))
    print(f"Evidence captured to {output_dir}")
    print(f"  Screenshots: {len(screenshots)}")
    print(f"  Console log: {len(console._entries)} entries")
    if args.record_video:
        videos = list((output_dir / "video").glob("*"))
        print(f"  Video: {len(videos)} file(s)")
    if args.record_har:
        har_path = output_dir / "network.har"
        print(f"  HAR: {'yes' if har_path.exists() else 'no'}")
    if exercise_timed_out:
        print("  Exercise: TIMED OUT (see exercise-timeout.txt)")

    return 0


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
