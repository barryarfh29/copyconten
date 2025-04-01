import asyncio
import logging
import os
import re
import time
from typing import Any, Callable, Dict, Optional, Tuple

import m3u8
from curl_cffi import requests
from ua_generator import generate as generate_user_agent

from utils import progress_func

logger = logging.getLogger("Delta")


class ProgressTracker:
    def __init__(
        self,
        total_bytes: int = 0,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        msg=None,
        file_name: str = "video",
        update_interval: float = 5.0,
    ):
        self.total_bytes = total_bytes
        self.completed_bytes = 0
        self.start_time = time.time()
        self.callback = callback
        self.status = "initializing"
        self.last_update_time = 0
        self.update_interval = update_interval
        self.msg = msg
        self.file_name = file_name
        self.last_update_time_list = [0]

    def update_bytes(self, bytes_completed: int, status: Optional[str] = None):
        self.completed_bytes += bytes_completed
        if status:
            self.status = status
        current_time = time.time()
        if (current_time - self.last_update_time) >= self.update_interval:
            self.last_update_time = current_time
            self._report_progress()

    def set_total_bytes(self, total_bytes: int):
        self.total_bytes = total_bytes
        self._report_progress()

    def set_file_name(self, file_name: str):
        self.file_name = file_name
        self._report_progress()

    def _report_progress(self):
        elapsed_time = time.time() - self.start_time
        if self.total_bytes == 0:
            percentage = 0
        else:
            percentage = (self.completed_bytes / self.total_bytes) * 100

        if percentage > 0:
            eta = (elapsed_time / percentage) * (100 - percentage)
        else:
            eta = 0

        speed = self.completed_bytes / elapsed_time if elapsed_time > 0 else 0

        progress_data = {
            "status": self.status,
            "completed_bytes": self.completed_bytes,
            "total_bytes": self.total_bytes,
            "percentage": round(percentage, 2),
            "elapsed": round(elapsed_time, 2),
            "eta": round(eta, 2),
            "speed": round(speed, 2),
        }

        if self.callback:
            self.callback(progress_data)

        if self.msg:
            mode = "upload" if "upload" in self.status.lower() else "download"
            asyncio.create_task(
                progress_func(
                    current=self.completed_bytes,
                    total=self.total_bytes,
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
            self.progress.update_bytes(0, "Fetching video page")
            page_html = await self._fetch_page_content()
            if not page_html:
                self.progress.update_bytes(0, "Failed to fetch page content")
                return False, None

            self.progress.update_bytes(0, "Extracting video information")
            uuid = self._extract_uuid(page_html)
            if not uuid:
                self.progress.update_bytes(0, "Failed to extract video information")
                return False, None

            self._extract_title(page_html) or "video"
            file_name = self._get_url_based_filename()
            self.progress.set_file_name(file_name)

            self.progress.update_bytes(0, "Processing playlist")
            variant_data = await self._process_m3u8_playlist(uuid)
            if not variant_data:
                self.progress.update_bytes(0, "Failed to process playlist")
                return False, None

            variant_url, total_bytes = variant_data
            self.progress.set_total_bytes(total_bytes)

            video_url = f"https://surrit.com/{uuid}/{variant_url}"
            output_file = os.path.join(self.output_dir, f"{file_name}.mp4")

            self.progress.update_bytes(0, "Starting download")
            success = await self._execute_ffmpeg_download(video_url, output_file)

            if success:
                self.progress.update_bytes(0, "Download completed")
            else:
                self.progress.update_bytes(0, "Download failed")

            return (success, output_file) if success else (False, None)

        except Exception as e:
            self.logger.error(f"Download process failed: {e}")
            self.progress.update_bytes(0, f"Error: {str(e)}")
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

        try:
            playlist = m3u8.loads(segment_content.decode("utf-8"))
            total_bytes = 0

            # First try to use byte ranges if available
            if all(seg.byterange for seg in playlist.segments):
                total_bytes = sum(seg.byterange.length for seg in playlist.segments)
                self.logger.info(f"Using byte range total: {total_bytes} bytes")
            else:
                # Fallback to sampling first 3 segments
                sample_segments = playlist.segments[:3]
                if not sample_segments:
                    return None

                total_size = 0
                successful_samples = 0
                variant_dir = os.path.dirname(variant_url)

                for seg in sample_segments:
                    segment_url = f"https://surrit.com/{uuid}/{variant_dir}/{seg.uri}"
                    size = await self._get_segment_size(segment_url)
                    if size:
                        total_size += size
                        successful_samples += 1

                if successful_samples > 0:
                    avg_size = total_size / successful_samples
                    total_bytes = int(avg_size * len(playlist.segments))
                    self.logger.info(
                        f"Estimated total size from {successful_samples} samples: {total_bytes} bytes"
                    )
                else:
                    # Final fallback: 1MB per segment
                    total_bytes = len(playlist.segments) * 1048576
                    self.logger.warning("Using fallback size estimation (1MB/segment)")

            return variant_url, total_bytes

        except Exception as e:
            self.logger.error(f"Error processing playlist: {e}")
            return None

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
                size_pattern = re.compile(r"size=\s*(\d+)(k|m)?B", re.IGNORECASE)
                byte_pattern = re.compile(r"bytes=\s*(\d+)", re.IGNORECASE)
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace")

                    # Parse size in format like "size=   1234kB" or "size=  1.23MB"
                    size_match = size_pattern.search(line_str)
                    if size_match:
                        value, unit = size_match.groups()
                        multiplier = 1
                        if unit:
                            multiplier = 1024 if unit.lower() == "k" else 1048576
                        bytes_value = int(float(value) * multiplier)
                        self.progress.update_bytes(bytes_value, "Downloading")
                        continue

                    # Parse raw byte count format
                    byte_match = byte_pattern.search(line_str)
                    if byte_match:
                        bytes_value = int(byte_match.group(1))
                        self.progress.update_bytes(bytes_value, "Downloading")

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


async def missav_dl(url: str, msg, quality: str = "lowest"):
    downloader = VideoDownloader(
        url=url,
        output_dir="./downloads",
        quality=quality,
        msg=msg,
        update_interval=1.0,
    )
    return await downloader.download()
