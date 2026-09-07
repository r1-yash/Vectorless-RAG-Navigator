"""YouTube transcript fetching and chunk stitching services."""

import re
from typing import List, Tuple
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

from src.models import TranscriptChunk


class YouTubeServiceError(Exception):
    """Raised when YouTube URL parsing or transcript fetching fails."""
    pass


import json
import urllib.request
from typing import List, Tuple, Dict


def extract_video_id(url_or_id: str) -> str:
    """Extract 11-character YouTube video ID from various URL formats, Shorts, live links, or raw ID."""
    url_or_id = url_or_id.strip()
    if len(url_or_id) == 11 and re.match(r"^[a-zA-Z0-9_-]{11}$", url_or_id):
        return url_or_id

    patterns = [
        r"(?:v=|\/|shorts\/|live\/|embed\/)([a-zA-Z0-9_-]{11})(?:[\?&/#]|$)",
        r"youtu\.be\/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    raise YouTubeServiceError(f"Could not extract a valid YouTube video ID from input: '{url_or_id}'")


def fetch_video_metadata(video_id: str) -> Dict[str, str]:
    """Fetch video title, author, and thumbnail via YouTube oEmbed API."""
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    default_meta = {
        "title": f"YouTube Lecture ({video_id})",
        "channel": "YouTube Channel",
        "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
    }
    try:
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return {
                    "title": data.get("title") or default_meta["title"],
                    "channel": data.get("author_name") or default_meta["channel"],
                    "thumbnail_url": data.get("thumbnail_url") or default_meta["thumbnail_url"],
                }
    except Exception:
        pass
    return default_meta


def fetch_raw_transcript(video_id: str) -> List[TranscriptChunk]:
    """
    Fetch raw timestamped transcript chunks for a video.
    Supports list_transcripts for manual/auto-generated English captions with translation fallback.
    """
    raw_items = []
    try:
        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                # Try finding manual english first, then auto-generated english, then translate
                try:
                    transcript = transcript_list.find_transcript(["en", "en-US", "en-GB"])
                except Exception:
                    try:
                        transcript = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
                    except Exception:
                        # Fallback to translating any available transcript to English
                        first_transcript = next(iter(transcript_list))
                        transcript = first_transcript.translate("en")
                raw_items = transcript.fetch()
            except Exception:
                if hasattr(YouTubeTranscriptApi, "get_transcript"):
                    raw_items = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
                else:
                    raise
        elif hasattr(YouTubeTranscriptApi, "get_transcript"):
            raw_items = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        else:
            api_instance = YouTubeTranscriptApi()
            raw_items = api_instance.fetch(video_id, languages=["en", "en-US", "en-GB"])
    except TranscriptsDisabled:
        raise YouTubeServiceError(f"Subtitles/captions are disabled for video '{video_id}'.")
    except NoTranscriptFound:
        raise YouTubeServiceError(f"No English transcript found for video '{video_id}'.")
    except VideoUnavailable:
        raise YouTubeServiceError(f"Video '{video_id}' is unavailable or private.")
    except Exception as e:
        err_msg = str(e)
        if "TranscriptsDisabled" in err_msg:
            raise YouTubeServiceError(f"Subtitles/captions are disabled for video '{video_id}'.")
        if "NoTranscriptFound" in err_msg:
            raise YouTubeServiceError(f"No English transcript found for video '{video_id}'.")
        raise YouTubeServiceError(f"Failed to retrieve transcript for '{video_id}': {err_msg}")

    chunks: List[TranscriptChunk] = []
    for item in raw_items:
        text_val = getattr(item, "text", item["text"] if isinstance(item, dict) else "")
        start_val = float(getattr(item, "start", item["start"] if isinstance(item, dict) else 0.0))
        duration_val = float(getattr(item, "duration", item["duration"] if isinstance(item, dict) else 2.0))

        clean_text = " ".join(text_val.replace("\n", " ").split())
        if not clean_text:
            continue

        chunks.append(
            TranscriptChunk(
                text=clean_text,
                start_ts=start_val,
                duration=duration_val,
                end_ts=round(start_val + duration_val, 2),
            )
        )

    if not chunks:
        raise YouTubeServiceError(f"Transcript fetched for '{video_id}' contained no readable text lines.")

    return chunks


def stitch_chunks_into_blocks(
    chunks: List[TranscriptChunk], target_words_per_block: int = 500
) -> List[TranscriptChunk]:
    """
    Stitch raw 2-5 second micro-chunks into continuous ~500 word blocks.
    Preserves exact start timestamp of the first chunk and end timestamp of the last chunk in each block.
    """
    blocks: List[TranscriptChunk] = []
    current_texts: List[str] = []
    current_start: float = chunks[0].start_ts
    current_end: float = chunks[0].end_ts
    current_word_count: int = 0

    for chunk in chunks:
        words = chunk.text.split()
        current_texts.append(chunk.text)
        current_word_count += len(words)
        current_end = chunk.end_ts

        if current_word_count >= target_words_per_block:
            blocks.append(
                TranscriptChunk(
                    text=" ".join(current_texts),
                    start_ts=current_start,
                    duration=round(current_end - current_start, 2),
                    end_ts=current_end,
                )
            )
            current_texts = []
            current_word_count = 0
            current_start = chunk.end_ts

    if current_texts:
        blocks.append(
            TranscriptChunk(
                text=" ".join(current_texts),
                start_ts=current_start,
                duration=round(current_end - current_start, 2),
                end_ts=current_end,
            )
        )

    return blocks
