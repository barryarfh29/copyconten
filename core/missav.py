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
    """Tracks and reports download progress."""

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
        self.update_interval = update_interval  # Update UI every 5 seconds by default
        self.msg = msg
        self.file_name = file_name
        self.estimated_bytes_per_segment = (
            1048576  # Estimate 1MB per segment as default
        )
        self.last_update_time_list = [
            0
        ]  # For compatibility with Pyrogram progress function

    def update(self, segments_completed: int = 1, status: Optional[str] = None):
        """Update progress and trigger callback if enough time has passed."""
        self.completed_segments += segments_completed

        if status:
            self.status = status

        current_time = time.time()
        if (current_time - self.last_update_time) >= self.update_interval:
            self.last_update_time = current_time
            self._report_progress()

    def set_total_segments(self, total_segments: int):
        """Set or update the total number of segments."""
        self.total_segments = total_segments
        self._report_progress()

    def set_bytes_per_segment(self, bytes_per_segment: int):
        """Set the estimated bytes per segment for more accurate progress reporting."""
        self.estimated_bytes_per_segment = bytes_per_segment

    def set_file_name(self, file_name: str):
        """Update the file name used for progress reporting."""
        self.file_name = file_name
        self._report_progress()

    def _report_progress(self):
        """Calculate progress metrics and report via callback."""
        # First calculate standard progress metrics
        elapsed_time = time.time() - self.start_time

        # Avoid division by zero
        if self.total_segments == 0:
            percentage = 0
        else:
            percentage = (self.completed_segments / self.total_segments) * 100

        # Calculate estimated time remaining
        if percentage > 0:
            eta = (elapsed_time / percentage) * (100 - percentage)
        else:
            eta = 0

        # Calculate speed (segments per second)
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

        # If we have a standard callback, use it
        if self.callback:
            self.callback(progress_data)

        # If we have a Pyrogram message, use the Pyrogram progress function
        if self.msg:
            # Convert segment counts to bytes for the Pyrogram progress function
            current_bytes = self.completed_segments * self.estimated_bytes_per_segment
            total_bytes = self.total_segments * self.estimated_bytes_per_segment

            # Determine mode based on status
            mode = "upload" if "upload" in self.status.lower() else "download"

            # Call Pyrogram progress function
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

        # Initialize progress tracker with a temporary filename
        self.progress = ProgressTracker(
            callback=progress_callback,
            msg=msg,
            file_name="Initializing...",
            update_interval=update_interval,
        )

        # Store the provided filename (if any) for later use
        self.custom_file_name = file_name

        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)

    async def download(self) -> Tuple[bool, Optional[str]]:
        """Main method to execute the download process."""
        try:
            self.progress.update(0, "Fetching video page")

            # Fetch initial page content
            page_html = await self._fetch_page_content()
            if not page_html:
                self.progress.update(0, "Failed to fetch page content")
                return False, None

            # Extract UUID from page content
            self.progress.update(0, "Extracting video information")
            uuid = self._extract_uuid(page_html)
            if not uuid:
                self.progress.update(0, "Failed to extract video information")
                return False, None

            # Extract title from page content for better automatic naming
            title = self._extract_title(page_html) or "video"

            # Get clean filename (either from custom file_name, title, or url)
            file_name = self._get_clean_filename(title)

            # Update progress tracker with the actual filename
            self.progress.set_file_name(file_name)

            # Fetch and process m3u8 playlist
            self.progress.update(0, "Processing playlist")
            variant_data = await self._process_m3u8_playlist(uuid)
            if not variant_data:
                self.progress.update(0, "Failed to process playlist")
                return False, None

            variant_url, segment_count = variant_data

            # Update total segments for progress tracking
            self.progress.set_total_segments(segment_count)

            # Build final video URL and output path
            video_url = f"https://surrit.com/{uuid}/{variant_url}"
            output_file = os.path.join(self.output_dir, f"{file_name}.mp4")

            # Execute ffmpeg download
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
        """Fetch and decode the initial video page content."""
        self.logger.info(f"Fetching video page: {self.url}")
        content = await self._http_get(self.url)
        return content.decode("utf-8", errors="replace") if content else None

    async def _http_get(self, url: str) -> Optional[bytes]:
        """Perform HTTP GET request with retries and error handling."""
        for attempt in range(1, self.retries + 1):
            try:
                response = await asyncio.to_thread(
                    requests.get,
                    url=url,
                    headers=self.headers,
                    timeout=self.timeout,
                    verify=False,
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

    def _extract_uuid(self, html: str) -> Optional[str]:
        """Extract UUID from page HTML using regex."""
        match = re.search(r"m3u8\|([a-f0-9\|]+)\|com\|surrit\|https\|video", html)
        if not match:
            self.logger.error("Failed to extract UUID from page content")
            return None
        return "-".join(match.group(1).split("|")[::-1])

    def _extract_title(self, html: str) -> Optional[str]:
        """Extract video title from the page content."""
        # Try to find <title> tag content
        title_match = re.search(r"<title>(.*?)</title>", html)
        if title_match:
            # Clean up the title text
            title = title_match.group(1).strip()
            # Remove site name and other common suffixes
            title = re.sub(r"\s*[-|]\s*.*$", "", title)
            return title.strip()

        # Try to find meta title tag
        meta_title_match = re.search(
            r'<meta\s+(?:name|property)="(?:og:title|title)"\s+content="(.*?)"', html
        )
        if meta_title_match:
            title = meta_title_match.group(1).strip()
            return title

        # Try to find h1 heading as a last resort
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html)
        if h1_match:
            return h1_match.group(1).strip()

        return None

    def _get_clean_filename(self, title: str) -> str:
        """Generate a clean filename from the title or URL."""
        # If a custom filename was provided, use that
        if self.custom_file_name:
            return self.custom_file_name

        # Clean the title to make it suitable for a filename
        # Replace problematic characters with underscores
        clean_name = re.sub(r'[\\/*?:"<>|]', "_", title)
        # Replace multiple spaces with a single underscore
        clean_name = re.sub(r"\s+", "_", clean_name)
        # Limit length to avoid overly long filenames
        clean_name = clean_name[:100]

        # If we ended up with an empty string, fallback to URL-based name
        if not clean_name or clean_name.isspace():
            return self._get_url_based_filename()

        return clean_name

    def _get_url_based_filename(self) -> str:
        """Extract a filename from the URL as a fallback method."""
        try:
            # Extract the last part of the URL path
            base = self.url.rstrip("/").split("/")[-1]
            # Remove query parameters and fragments
            clean_base = base.split("#")[0].split("?")[0]

            # If we have something usable, return it
            if clean_base and not clean_base.isspace():
                return clean_base
        except Exception as e:
            self.logger.error(f"Error extracting filename from URL: {e}")

        # Final fallback: timestamp-based name
        return f"video_{int(time.time())}"

    async def _process_m3u8_playlist(self, uuid: str) -> Optional[Tuple[str, int]]:
        """Fetch and process m3u8 playlist to select quality variant and count segments."""
        m3u8_url = f"https://surrit.com/{uuid}/playlist.m3u8"
        self.logger.info(f"Fetching m3u8 playlist: {m3u8_url}")

        content = await self._http_get(m3u8_url)
        if not content:
            return None

        variant_url = self._select_quality_variant(content.decode("utf-8"))
        if not variant_url:
            return None

        # Now fetch the selected variant to count segments
        variant_full_url = f"https://surrit.com/{uuid}/{variant_url}"
        segment_content = await self._http_get(variant_full_url)
        if not segment_content:
            return None

        segment_count = self._count_segments(segment_content.decode("utf-8"))
        return variant_url, segment_count

    def _select_quality_variant(self, m3u8_content: str) -> Optional[str]:
        """Select appropriate quality variant from m3u8 content."""
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
        """Count number of segments in an m3u8 playlist."""
        try:
            playlist = m3u8.loads(m3u8_content)
            return len(playlist.segments)
        except Exception as e:
            self.logger.error(f"Failed to count segments: {e}")
            return 100  # Fallback to a reasonable default

    async def _execute_ffmpeg_download(self, video_url: str, output_file: str) -> bool:
        """Execute ffmpeg command to download and save the video with progress monitoring."""
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
            "info",  # Changed from warning to info to capture progress
            output_file,
        ]

        self.logger.info(f"Starting ffmpeg process: {' '.join(ffmpeg_cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Process ffmpeg output to track progress
            async def read_stderr():
                segment_pattern = re.compile(r"Opening \'.*\' for reading")
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace")

                    # Check if this line indicates a new segment is being processed
                    if segment_pattern.search(line_str):
                        self.progress.update(1, "Downloading")

            # Start monitoring in the background
            monitor_task = asyncio.create_task(read_stderr())

            # Wait for process to complete
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
    """Simple callback to print progress in console."""
    status = progress_data["status"]
    percentage = progress_data["percentage"]
    eta = progress_data["eta"]

    # Create a progress bar
    bar_length = 30
    filled_length = int(bar_length * progress_data["percentage"] / 100)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)

    # Format ETA
    eta_str = format_duration(timedelta(seconds=eta))

    # Print progress with carriage return to update in place
    print(
        f"\r{status}: [{bar}] {percentage:.1f}% | ETA: {eta_str} | Segments: {progress_data['completed']}/{progress_data['total']}",
        end="",
        flush=True,
    )

    # Add a new line when complete
    if status == "Download completed":
        print()


async def missav_dl(url: str, msg, quality: str = "lowest"):
    """
    Download a video with progress updates sent to a Pyrogram message.

    Args:
        url (str): Video URL to download
        msg: Pyrogram Message object to update with progress
        file_name (str, optional): Custom filename, or auto-generated if None

    Returns:
        Tuple[bool, Optional[str]]: Success status and output file path
    """
    downloader = VideoDownloader(
        url=url,
        output_dir="./downloads",
        quality=quality,
        msg=msg,
        update_interval=3.0,
    )

    return await downloader.download()
