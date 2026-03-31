"""헤드리스 PNG 내보내기.
Playwright + Chromium + SwiftShader로 py3Dmol HTML → PNG 캡처.

선택적 의존성: pip install playwright && playwright install chromium
"""

import asyncio
from pathlib import Path


async def html_to_png(
    html_path: str,
    png_path: str | None = None,
    width: int = 800,
    height: int = 600,
    wait_ms: int = 3000,
    timeout_ms: int = 30000,
) -> dict:
    """HTML 파일을 PNG로 캡처.

    Args:
        html_path: py3Dmol HTML 파일 경로.
        png_path: 출력 PNG 경로. None이면 자동 생성.
        width: 뷰포트 너비 (px).
        height: 뷰포트 높이 (px).
        wait_ms: 3Dmol.js 렌더링 대기 (ms).
        timeout_ms: 전체 타임아웃 (ms).

    Returns:
        dict: {success, png_path, width, height, file_size_bytes, error}.

    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "error": (
                "Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
        }

    if png_path is None:
        png_path = str(Path(html_path).with_suffix(".png"))

    html_uri = Path(html_path).resolve().as_uri()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--enable-gpu",
                    "--use-angle=swiftshader-webgl",
                    "--enable-unsafe-swiftshader",
                    "--no-sandbox",
                ],
            )
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
            )
            page = await context.new_page()
            await page.goto(html_uri, timeout=timeout_ms)
            await page.wait_for_timeout(wait_ms)

            canvas_ok = await page.evaluate(
                "() => { const c = document.querySelector('canvas'); "
                "return c !== null && c.width > 0; }"
            )
            if not canvas_ok:
                await page.wait_for_timeout(wait_ms * 2)

            await page.screenshot(path=png_path, type="png")
            await browser.close()

        file_size = Path(png_path).stat().st_size
        return {
            "success": True,
            "png_path": png_path,
            "width": width * 2,
            "height": height * 2,
            "file_size_bytes": file_size,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def html_to_png_sync(html_path: str, **kwargs) -> dict:
    """동기 래퍼."""
    return asyncio.run(html_to_png(html_path, **kwargs))
