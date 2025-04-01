import asyncio
import logging
import os
import re
import time
from datetime import timedelta
from typing import Any, Callable, Dict, Optional, Tuple

import m3u8
from curl_cffi import requests
from ua_generator import generate as generate_user_agent

from utils import format_duration, progress_func

logger = logging.getLogger("Delta")


class ProgressTracker:
    def __init__(
        self,
        total_segments: int = 0,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        msg=None,
        file_name: str = "video",
        update_interval: float = 5.0,
    ):
        self.total_segments = total_segments
        self.completed_segments = 0
        self.start_time = time.time()
        self.callback = callback
        self.status = "initializing"
        self.last_update_time = 0
        self.update_interval = update_interval
        self.msg = msg
        self.file_name = file_name
        self.estimated_bytes_per_segment = 1048576  # Default estimate
        self.last_update_time_list = [0]

    def update(self, segments_completed: int = 1, status: Optional[str] = None):
        self.completed_segments += segments_completed
        if status:
            self.status = status
        current_time = time.time()
        if (current_time - self.last_update_time) >= self.update_interval:
            self.last_update_time = current_time
            self._report_progress()

    def set_total_segments(self, total_segments: int):
        self.total_segments = total_segments
        self._report_progress()

    def set_bytes_per_segment(self, bytes_per_segment: int):
        self.estimated_bytes_per_segment = bytes_per_segment
        logger.debug(f"Updated bytes per segment: {bytes_per_segment}")

    def set_file_name(self, file_name: str):
        self.file_name = file_name
        self._report_progress()

    def _report_progress(self):
        elapsed_time = time.time() - self.start_time
        if self.total_segments == 0:
            percentage = 0
        else:
            percentage = (self.completed_segments / self.total_segments) * 100

        if percentage > 0:
            eta = (elapsed_time / percentage) * (100 - percentage)
        else:
            eta = 0

        speed = self.completed_segments / elapsed_time if elapsed_time > 0 else 0

        progress_data = {
            "status": self.status,
            "completed": self.completed_segments,
            "total": self.total_segments,
            "percentage": round(percentage, 2),
            "elapsed": round(elapsed_time, 2),
            "eta": round(eta, 2),
            "speed": round(speed, 2),
        }

        if self.callback:
            self.callback(progress_data)

        if self.msg:
            current_bytes = self.completed_segments * self.estimated_bytes_per_segment
            total_bytes = self.total_segments * self.estimated_bytes_per_segment
            mode = "upload" if "upload" in self.status.lower() else "download"
            asyncio.create_task(
                progress_func(
                    current=current_bytes,
                    total=total_bytes,
                    msg=self.msg,
                    start_time=self.start_time,
                    mode=mode,
                    file_name=self.file_name,
                    update_interval=self.update_interval,
                    last_update_time=self.last_update_time_list,
                )
            )


class VideoDownloader:
    def __init__(
        self,
        url: str,
        output_dir: str = "./downloads",
        quality: str = "medium",
        retries: int = 3,
        delay: int = 2,
        timeout: int = 10,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        msg=None,
        file_name: str = None,
        update_interval: float = 5.0,
    ):
        self.url = url
        self.output_dir = output_dir
        self.quality = quality
        self.retries = retries
        self.delay = delay
        self.timeout = timeout
        self.headers = {
            "User-Agent": str(generate_user_agent()),
            "Accept": "*/*",
            "Connection": "keep-alive",
        }
        self.logger = logging.getLogger("Delta.VideoDownloader")
        self.progress = ProgressTracker(
            callback=progress_callback,
            msg=msg,
            file_name="Initializing...",
            update_interval=update_interval,
        )
        self.custom_file_name = file_name
        os.makedirs(self.output_dir, exist_ok=True)

    async def download(self) -> Tuple[bool, Optional[str]]:
        try:
            self.progress.update(0, "Fetching video page")
            page_html = await self._fetch_page_content()
            if not page_html:
                self.progress.update(0, "Failed to fetch page content")
                return False, None

            self.progress.update(0, "Extracting video information")
            uuid = self._extract_uuid(page_html)
            if not uuid:
                self.progress.update(0, "Failed to extract video information")
                return False, None

            self._extract_title(page_html) or "video"
            file_name = self._get_url_based_filename()
            self.progress.set_file_name(file_name)

            self.progress.update(0, "Processing playlist")
            variant_data = await self._process_m3u8_playlist(uuid)
            if not variant_data:
                self.progress.update(0, "Failed to process playlist")
                return False, None

            variant_url, segment_count = variant_data
            self.progress.set_total_segments(segment_count)

            video_url = f"https://surrit.com/{uuid}/{variant_url}"
            output_file = os.path.join(self.output_dir, f"{file_name}.mp4")

            self.progress.update(0, "Starting download")
            success = await self._execute_ffmpeg_download(video_url, output_file)

            if success:
                self.progress.update(0, "Download completed")
            else:
                self.progress.update(0, "Download failed")

            return (success, output_file) if success else (False, None)

        except Exception as e:
            self.logger.error(f"Download process failed: {e}")
            self.progress.update(0, f"Error: {str(e)}")
            return False, None

    async def _fetch_page_content(self) -> Optional[str]:
        self.logger.debug(f"Fetching video page: {self.url}")
        content = await self._http_get(self.url)
        return content.decode("utf-8", errors="replace") if content else None

    async def _http_get(self, url: str) -> Optional[bytes]:
        for attempt in range(1, self.retries + 1):
            try:
                response = await asyncio.to_thread(
                    requests.get,
                    url=url,
                    headers=self.headers,
                    timeout=self.timeout,
                    verify=False,
                    impersonate="chrome",
                )
                if response.status_code >= 400:
                    self.logger.error(
                        f"HTTP error {response.status_code} on attempt {attempt}"
                    )
                    await asyncio.sleep(self.delay)
                    continue
                return response.content
            except Exception as e:
                self.logger.error(f"Request failed on attempt {attempt}: {e}")
                await asyncio.sleep(self.delay)
        return None

    async def _get_segment_size(self, segment_url: str) -> Optional[int]:
        for attempt in range(1, self.retries + 1):
            try:
                response = await asyncio.to_thread(
                    requests.head,
                    url=segment_url,
                    headers=self.headers,
                    timeout=self.timeout,
                    verify=False,
                    impersonate="chrome",
                )
                if response.status_code == 200:
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        return int(content_length)
            except Exception as e:
                self.logger.error(
                    f"Failed to get segment size on attempt {attempt}: {e}"
                )
                await asyncio.sleep(self.delay)
        return None

    def _extract_uuid(self, html: str) -> Optional[str]:
        match = re.search(r"m3u8\|([a-f0-9\|]+)\|com\|surrit\|https\|video", html)
        if not match:
            self.logger.error("Failed to extract UUID from page content")
            return None
        return "-".join(match.group(1).split("|")[::-1])

    def _extract_title(self, html: str) -> Optional[str]:
        title_match = re.search(r"<title>(.*?)</title>", html)
        if title_match:
            title = title_match.group(1).strip()
            title = re.sub(r"\s*[-|]\s*.*$", "", title)
            return title.strip()

        meta_title_match = re.search(
            r'<meta\s+(?:name|property)="(?:og:title|title)"\s+content="(.*?)"', html
        )
        if meta_title_match:
            return meta_title_match.group(1).strip()

        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html)
        if h1_match:
            return h1_match.group(1).strip()

        return None

    def _get_url_based_filename(self) -> str:
        try:
            clean_url = self.url.rstrip("/")
            parts = clean_url.split("/")

            if len(parts) >= 2:
                last_part = parts[-1]
                filename = last_part.split("?")[0].split("#")[0]

                if re.match(r"^[a-zA-Z]+-\d+-[a-zA-Z0-9-]+$", filename):
                    return filename

                if len(parts) >= 3 and parts[-2] in ["en", "ja", "zh"]:
                    filename = parts[-1]
                    if re.match(r"^[a-zA-Z]+-\d+-[a-zA-Z0-9-]+$", filename):
                        return filename

            match = re.search(r"/([a-zA-Z]+-\d+-[a-zA-Z0-9-]+)(?:/|$|\?|#)", self.url)
            if match:
                return match.group(1)

        except Exception as e:
            self.logger.error(f"Error extracting filename from URL: {e}")

        return f"video_{int(time.time())}"

    async def _process_m3u8_playlist(self, uuid: str) -> Optional[Tuple[str, int]]:
        m3u8_url = f"https://surrit.com/{uuid}/playlist.m3u8"
        self.logger.debug(f"Fetching m3u8 playlist: {m3u8_url}")

        content = await self._http_get(m3u8_url)
        if not content:
            return None

        variant_url = self._select_quality_variant(content.decode("utf-8"))
        if not variant_url:
            return None

        variant_full_url = f"https://surrit.com/{uuid}/{variant_url}"
        segment_content = await self._http_get(variant_full_url)
        if not segment_content:
            return None

        segment_count = self._count_segments(segment_content.decode("utf-8"))
        if segment_count == 0:
            return None

        # Estimate segment size using the first segment
        try:
            playlist = m3u8.loads(segment_content.decode("utf-8"))
            if playlist.segments:
                first_segment_uri = playlist.segments[0].uri
                variant_dir = os.path.dirname(variant_url)
                first_segment_url = (
                    f"https://surrit.com/{uuid}/{variant_dir}/{first_segment_uri}"
                )
                segment_size = await self._get_segment_size(first_segment_url)
                if segment_size:
                    self.progress.set_bytes_per_segment(segment_size)
                    self.logger.debug(f"Estimated bytes per segment: {segment_size}")
                else:
                    self.logger.warning(
                        "Failed to get segment size, using default estimate"
                    )
        except Exception as e:
            self.logger.error(f"Error estimating segment size: {e}")

        return variant_url, segment_count

    def _select_quality_variant(self, m3u8_content: str) -> Optional[str]:
        try:
            playlist = m3u8.loads(m3u8_content)
            if not playlist.is_variant:
                self.logger.error("Invalid variant playlist")
                return None

            variants = sorted(playlist.playlists, key=lambda p: p.stream_info.bandwidth)
            if not variants:
                return None

            quality_map = {"lowest": 0, "medium": len(variants) // 2, "high": -1}
            index = quality_map.get(self.quality.lower(), 0)
            return variants[index].uri
        except Exception as e:
            self.logger.error(f"Failed to process m3u8 content: {e}")
            return None

    def _count_segments(self, m3u8_content: str) -> int:
        try:
            playlist = m3u8.loads(m3u8_content)
            return len(playlist.segments)
        except Exception as e:
            self.logger.error(f"Failed to count segments: {e}")
            return 100

    async def _execute_ffmpeg_download(self, video_url: str, output_file: str) -> bool:
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-headers",
            f"User-Agent: {self.headers['User-Agent']}",
            "-i",
            video_url,
            "-c",
            "copy",
            "-loglevel",
            "info",
            output_file,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def read_stderr():
                segment_pattern = re.compile(r"Opening \'.*\' for reading")
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace")
                    if segment_pattern.search(line_str):
                        self.progress.update(1, "Downloading")

            monitor_task = asyncio.create_task(read_stderr())
            await process.wait()
            await monitor_task

            if process.returncode != 0:
                stderr_output = await process.stderr.read()
                self.logger.error(f"ffmpeg failed with error: {stderr_output.decode()}")
                return False

            if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                self.logger.error("Output file missing or empty")
                return False

            return True
        except Exception as e:
            self.logger.error(f"ffmpeg execution failed: {e}")
            return False


def print_progress(progress_data: Dict[str, Any]):
    status = progress_data["status"]
    percentage = progress_data["percentage"]
    eta = progress_data["eta"]

    bar_length = 30
    filled_length = int(bar_length * progress_data["percentage"] / 100)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)

    eta_str = format_duration(timedelta(seconds=eta))

    print(
        f"\r{status}: [{bar}] {percentage:.1f}% | ETA: {eta_str} | Segments: {progress_data['completed']}/{progress_data['total']}",
        end="",
        flush=True,
    )

    if status == "Download completed":
        print()


async def missav_dl(url: str, msg, quality: str = "lowest"):
    downloader = VideoDownloader(
        url=url,
        output_dir="./downloads",
        quality=quality,
        msg=msg,
        update_interval=3.0,
    )
    return await downloader.download()
