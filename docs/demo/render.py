"""Render docs/demo/demo.html frame by frame (deterministic) and encode an MP4 + GIF.

    uv run --with playwright python docs/demo/render.py            # full video
    uv run --with playwright python docs/demo/render.py --stills 1.5 5 11 15 17.8 19.5
Uses the installed Google Chrome (no browser download).
"""

import argparse
import pathlib
import shutil
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FPS = 30
FFMPEG = shutil.which("ffmpeg") or "/opt/anaconda3/bin/ffmpeg"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", nargs="*", type=float)
    ap.add_argument("--out", default=str(HERE / "notetaker-demo.mp4"))
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.goto((HERE / "demo.html").as_uri() + "?capture")
        page.wait_for_load_state("networkidle")
        duration = page.evaluate("window.DURATION")

        if args.stills is not None:
            for t in args.stills:
                page.evaluate(f"render({t})")
                path = HERE / f"still-{t:05.1f}.png"
                page.screenshot(path=str(path))
                print(path)
            browser.close()
            return

        frames = pathlib.Path(tempfile.mkdtemp())
        total = int(duration * FPS)
        for i in range(total):
            page.evaluate(f"render({i / FPS})")
            page.screenshot(path=str(frames / f"f{i:04d}.png"))
            if i % 60 == 0:
                print(f"frame {i}/{total}", flush=True)
        browser.close()

    out = pathlib.Path(args.out)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow",
                    "-movflags", "+faststart", str(out)], check=True)
    gif = out.with_suffix(".gif")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(out), "-vf",
                    "fps=15,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                    str(gif)], check=True)
    shutil.rmtree(frames)
    print(out, gif)


if __name__ == "__main__":
    main()
