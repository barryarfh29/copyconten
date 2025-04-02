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
        percentage = (
            (self.completed_bytes / self.total_bytes * 100) if self.total_bytes else 0
        )
        eta = (elapsed_time / percentage) * (100 - percentage) if percentage > 0 else 0
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

        # Only schedule further progress updates if not complete
        if self.msg and self.completed_bytes < self.total_bytes:
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

        # Add quality-specific size estimation multiplier
        self.quality_multipliers = {
            "lowest": 1.0,
            "medium": 1.2,  # 20% buffer for medium quality
            "high": 1.5,  # 50% buffer for high quality
        }

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

            # Extract title if available; fallback to "video"
            self._extract_title(page_html) or "video"
            file_name = self.custom_file_name or self._get_url_based_filename()
            self.progress.set_file_name(file_name)

            self.progress.update_bytes(0, "Processing playlist")
            variant_data = await self._process_m3u8_playlist(uuid)
            if not variant_data:
                self.progress.update_bytes(0, "Failed to process playlist")
                return False, None

            variant_url, total_bytes = variant_data
            multiplier = self.quality_multipliers.get(self.quality.lower(), 1.0)
            adjusted_total_bytes = int(total_bytes * multiplier)
            self.logger.info(
                f"Estimated size: {total_bytes} bytes, adjusted: {adjusted_total_bytes} bytes"
            )
            self.progress.set_total_bytes(adjusted_total_bytes)

            video_url = f"https://surrit.com/{uuid}/{variant_url}"
            output_file = os.path.join(self.output_dir, f"{file_name}.mp4")

            self.progress.update_bytes(0, "Starting download")
            success = await self._execute_ffmpeg_download(video_url, output_file)

            if success:
                # Update progress to actual file size after completion
                if os.path.exists(output_file):
                    actual_size = os.path.getsize(output_file)
                    self.progress.set_total_bytes(actual_size)
                    self.progress.completed_bytes = actual_size
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

            # If byte ranges are available, sum them up
            if all(seg.byterange for seg in playlist.segments):
                total_bytes = sum(seg.byterange.length for seg in playlist.segments)
                self.logger.info(f"Using byte range total: {total_bytes} bytes")
            else:
                sample_count = {"lowest": 3, "medium": 5, "high": 8}.get(
                    self.quality.lower(), 3
                )
                total_segments = len(playlist.segments)
                if total_segments <= sample_count:
                    sample_indices = list(range(total_segments))
                else:
                    step = total_segments / sample_count
                    sample_indices = [
                        min(int(i * step), total_segments - 1)
                        for i in range(sample_count)
                    ]

                sample_segments = [playlist.segments[i] for i in sample_indices]
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
                    fallback_sizes = {
                        "lowest": 524288,  # 512KB per segment
                        "medium": 1048576,  # 1MB per segment
                        "high": 2097152,  # 2MB per segment
                    }
                    segment_size = fallback_sizes.get(self.quality.lower(), 1048576)
                    total_bytes = len(playlist.segments) * segment_size
                    self.logger.warning(
                        f"Using fallback size estimation ({segment_size/1048576}MB/segment)"
                    )

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

            quality_lower = self.quality.lower()

            if quality_lower == "lowest":
                return variants[0].uri
            elif quality_lower == "high":
                return variants[-1].uri
            elif quality_lower == "medium":
                if len(variants) >= 3:
                    return variants[len(variants) // 2].uri
                else:
                    return variants[-1].uri
            else:
                return variants[min(len(variants) // 2, len(variants) - 1)].uri

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
                size_pattern = re.compile(
                    r"size=\s*(\d+)(\.\d+)?(k|m|g)?B", re.IGNORECASE
                )
                previous_size = 0
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace")
                    size_match = size_pattern.search(line_str)
                    if size_match:
                        try:
                            value = size_match.group(1)
                            decimal = size_match.group(2) or ""
                            unit = size_match.group(3)
                            num_value = float(value + decimal)
                            multiplier = 1
                            if unit:
                                if unit.lower() == "k":
                                    multiplier = 1024
                                elif unit.lower() == "m":
                                    multiplier = 1024 * 1024
                                elif unit.lower() == "g":
                                    multiplier = 1024 * 1024 * 1024
                            cumulative_size = int(num_value * multiplier)
                            delta = cumulative_size - previous_size
                            if delta > 0:
                                self.progress.update_bytes(delta, "Downloading")
                                previous_size = cumulative_size
                        except Exception as e:
                            self.logger.error(f"Error parsing size: {e}")

            # Await both the stderr reader and process completion
            await asyncio.gather(read_stderr(), process.wait())
            return process.returncode == 0

        except Exception as e:
            self.logger.error(f"ffmpeg download failed: {e}")
            return False


async def missav_dl(url: str, msg, quality: str = "lowest"):
    downloader = VideoDownloader(
        url=url,
        output_dir="./downloads",
        quality=quality,
        msg=msg,
        update_interval=5.0,
    )
    return await downloader.download()
