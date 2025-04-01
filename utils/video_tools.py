#!/usr/bin/env python3
import asyncio
import json
import math
import os
from pathlib import Path


async def get_video_info(input_file):
    """Get video information using ffprobe asynchronously."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        input_file,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"Error analyzing video: {stderr.decode()}")

    return json.loads(stdout.decode())


async def split_segment(input_file, output_file, start_time, duration=None):
    """Split a single segment of the video asynchronously."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", input_file, "-ss", str(start_time)]

    # For all segments except the last one, specify duration
    if duration is not None:
        cmd.extend(["-t", str(duration)])

    cmd.extend(["-c", "copy", output_file])

    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()}")

    return output_file


async def split_video_by_size(input_file, output_prefix, max_size_bytes=2_097_152_000):
    """
    Split a video file into multiple parts, ensuring each part doesn't exceed the maximum size.

    Args:
        input_file (str): Path to the input video file
        output_prefix (str): Prefix for output file names
        max_size_bytes (int): Maximum size in bytes (default: 2GB)

    Returns:
        list: List of output file paths

    Raises:
        FileNotFoundError: If input file doesn't exist
        RuntimeError: If there's an error during video processing
        ValueError: If input parameters are invalid
    """
    # Check if input file exists
    if not os.path.isfile(input_file):
        raise FileNotFoundError(f"Input file '{input_file}' does not exist")

    # Get file size
    file_size = os.path.getsize(input_file)

    # Ensure output directory exists
    output_dir = os.path.dirname(output_prefix)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # If file is already smaller than max size, just copy it
    if file_size <= max_size_bytes:
        output_file = f"{output_prefix}001{Path(input_file).suffix}"

        # Use asyncio to copy the file
        process = await asyncio.create_subprocess_exec(
            "cp",
            input_file,
            output_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"Failed to copy file: {stderr.decode()}")

        return [output_file]

    # Get video information
    video_info = await get_video_info(input_file)

    # Get video duration
    duration = float(video_info["format"]["duration"])

    # Calculate number of segments needed (round up)
    num_segments = math.ceil(file_size / max_size_bytes)

    # Add an extra segment if segments would be close to max size
    if (file_size / num_segments) > 0.9 * max_size_bytes:
        num_segments += 1

    segment_duration = duration / num_segments

    output_files = []
    tasks = []

    # Create tasks for splitting each segment
    for i in range(num_segments):
        start_time = i * segment_duration
        segment_num = f"{i + 1:03d}"
        output_file = f"{output_prefix}{segment_num}{Path(input_file).suffix}"
        output_files.append(output_file)

        # Create split task
        task = split_segment(
            input_file,
            output_file,
            start_time,
            segment_duration if i < num_segments - 1 else None,
        )
        tasks.append(task)

    # Execute all splits concurrently
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        # Clean up any created files
        for file in output_files:
            if os.path.exists(file):
                os.remove(file)
        raise RuntimeError(f"Error during video splitting: {str(e)}")

    # Check file sizes
    for i, output_file in enumerate(output_files):
        if os.path.exists(output_file):
            seg_size = os.path.getsize(output_file)
            if seg_size > max_size_bytes:
                # If we still have a segment exceeding max size, try with more segments
                for file in output_files:
                    if os.path.exists(file):
                        os.remove(file)

                # Recursive call with more segments
                return await split_video_by_size(
                    input_file, output_prefix, max_size_bytes
                )

    return output_files
