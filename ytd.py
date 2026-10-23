"""
YouTube Downloader (YTD) Subsystem for DubFlow Studio
======================================================
Manages connected YouTube channels, video catalogs, channel syncing,
and downloading options (Full MP4, Split Parts, Vertical Shorts).
Features a permanent blacklist for deleted videos so they are never re-added on sync.
"""

import os
import re
import sys
import json
import time
import shutil
import zipfile
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pipeline import ShortsGenerator

# Base paths
BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace_api"
YTD_DB_PATH = WORKSPACE_DIR / "ytd.db"
YTD_DOWNLOADS_DIR = WORKSPACE_DIR / "ytd_downloads"
DIRECT_DOWNLOADS_DIR = WORKSPACE_DIR / "direct_downloads"

# Ensure directories exist
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
YTD_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
DIRECT_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Thread pool for background downloading and splitting tasks
ytd_executor = ThreadPoolExecutor(max_workers=3)

# Active download progress tracking: video_id -> { status, progress, message, error }
active_ytd_downloads: Dict[int, Dict[str, Any]] = {}
active_direct_downloads: Dict[int, Dict[str, Any]] = {}


def get_db_connection() -> sqlite3.Connection:
    """Creates a thread-safe connection to the YTD SQLite database."""
    conn = sqlite3.connect(str(YTD_DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Initializes tables and indexes for the YTD subsystem."""
    with get_db_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                handle TEXT,
                title TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                thumbnail TEXT,
                description TEXT DEFAULT '',
                created_at REAL NOT NULL,
                last_synced_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
                youtube_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                url TEXT NOT NULL,
                thumbnail TEXT,
                duration INTEGER DEFAULT 0,
                view_count INTEGER DEFAULT 0,
                is_downloaded INTEGER DEFAULT 0,
                download_status TEXT DEFAULT 'undownloaded',
                download_progress INTEGER DEFAULT 0,
                download_path TEXT,
                download_file_name TEXT,
                download_file_size INTEGER DEFAULT 0,
                download_type TEXT DEFAULT 'full',
                split_duration INTEGER DEFAULT 0,
                parts_count INTEGER DEFAULT 1,
                shorts_count INTEGER DEFAULT 0,
                is_zip INTEGER DEFAULT 0,
                download_error TEXT,
                downloaded_at REAL,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ytd_videos_channel_id ON videos(channel_id);
            CREATE INDEX IF NOT EXISTS idx_ytd_videos_is_downloaded ON videos(is_downloaded);
            CREATE INDEX IF NOT EXISTS idx_ytd_videos_youtube_id ON videos(youtube_id);

            CREATE TABLE IF NOT EXISTS deleted_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_id TEXT UNIQUE NOT NULL,
                channel_id INTEGER,
                title TEXT,
                deleted_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ytd_deleted_youtube_id ON deleted_videos(youtube_id);

            CREATE TABLE IF NOT EXISTS direct_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_id TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                thumbnail TEXT DEFAULT '',
                duration INTEGER DEFAULT 0,
                view_count INTEGER DEFAULT 0,
                channel_name TEXT DEFAULT '',
                download_status TEXT DEFAULT 'pending',
                download_progress INTEGER DEFAULT 0,
                download_path TEXT,
                download_file_name TEXT,
                download_file_size INTEGER DEFAULT 0,
                is_downloaded INTEGER DEFAULT 0,
                was_downloaded INTEGER DEFAULT 0,
                download_error TEXT,
                downloaded_at REAL,
                file_deleted_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_direct_videos_youtube_id ON direct_videos(youtube_id);
            CREATE INDEX IF NOT EXISTS idx_direct_videos_url ON direct_videos(url);
            CREATE INDEX IF NOT EXISTS idx_direct_videos_download_status ON direct_videos(download_status);
        """)
        conn.commit()


# Initialize database on module load
init_db()


def normalize_channel_url(input_url: str) -> str:
    """
    Normalizes arbitrary user channel links (@handle, full URL, etc.)
    into a canonical https://www.youtube.com/.../videos endpoint.
    """
    val = str(input_url or "").strip()
    if not val:
        raise ValueError("Please enter a valid YouTube channel URL.")

    if val.startswith("@"):
        val = f"https://www.youtube.com/{val}"
    elif not re.match(r"^https?://", val, re.IGNORECASE):
        val = f"https://{val}"

    # Verify hostname
    from urllib.parse import urlparse
    parsed = urlparse(val)
    valid_hosts = ["youtube.com", "www.youtube.com", "m.youtube.com"]
    if parsed.netloc.lower() not in valid_hosts:
        raise ValueError("Please enter a valid YouTube URL (e.g. https://www.youtube.com/@ChannelName).")

    # Reject single video links
    if parsed.path.startswith("/watch") or "/shorts/" in parsed.path:
        raise ValueError("This is a single video URL. Please provide a YouTube channel link.")

    pathname = parsed.path.rstrip("/")
    for tab in ["/featured", "/community", "/playlists", "/about", "/streams", "/podcasts"]:
        if pathname.endswith(tab):
            pathname = pathname[:-len(tab)]
            break

    if not pathname.endswith("/videos"):
        pathname = f"{pathname}/videos"

    return f"https://www.youtube.com{pathname}"


def get_ytdlp_auth_args() -> List[str]:
    """Builds authentication, cookie, and challenge-solver CLI arguments for yt-dlp."""
    args = []
    try:
        from pipeline import find_cookies_file
        cookie_path = find_cookies_file()
        if cookie_path:
            args.extend(["--cookies", str(cookie_path)])
    except Exception:
        pass

    args.extend(["--remote-components", "ejs:github"])
    args.extend(["--js-runtimes", "node", "--js-runtimes", "deno", "--js-runtimes", "quickjs"])
    args.extend(["--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"])
    args.extend(["--extractor-args", "youtube:player_client=visionos,android,ios,mweb,web"])
    return args


def fetch_channel_data_from_yt(normalized_url: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Uses yt-dlp flat-playlist mode to fetch channel metadata and video list.
    """
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "-J",
        "--ignore-config",
        "--socket-timeout", "40",
    ] + get_ytdlp_auth_args() + [
        "--",
        normalized_url
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180, check=True)
        data = json.loads(res.stdout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Channel metadata extraction timed out. YouTube may be throttling or URL is unreachable.")
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip() or f"yt-dlp failed with return code {e.returncode}"
        raise RuntimeError(f"Failed to fetch channel data: {err_msg}")
    except Exception as e:
        raise RuntimeError(f"Error reading channel data: {e}")

    # Extract avatar thumbnail
    avatar_url = ""
    thumbnails = data.get("thumbnails") or []
    if isinstance(thumbnails, list) and len(thumbnails) > 0:
        for t in thumbnails:
            if t.get("id") == "avatar_uncropped" or (t.get("width") and t.get("width") == t.get("height")):
                avatar_url = t.get("url") or avatar_url
        if not avatar_url:
            avatar_url = thumbnails[-1].get("url") or ""

    channel_id = data.get("channel_id") or data.get("id") or ""
    raw_title = data.get("channel") or data.get("title") or "YouTube Channel"
    clean_title = re.sub(r"\s*-\s*Videos$", "", raw_title, flags=re.IGNORECASE).strip()
    uploader_id = data.get("uploader_id") or ""
    handle = uploader_id if uploader_id.startswith("@") else ""
    channel_url = data.get("channel_url") or data.get("uploader_url") or data.get("webpage_url") or normalized_url
    description = data.get("description") or ""
    entries = data.get("entries") or []

    channel_info = {
        "channel_id": channel_id,
        "handle": handle,
        "title": clean_title,
        "url": channel_url,
        "thumbnail": avatar_url,
        "description": description
    }

    return channel_info, entries


def get_ytd_stats() -> Dict[str, Any]:
    """Returns aggregated metrics for YTD dashboard pill counters."""
    with get_db_connection() as conn:
        channels_count = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        video_row = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_downloaded = 1 THEN 1 ELSE 0 END) as downloaded,
                SUM(CASE WHEN is_downloaded = 0 THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN download_type = 'shorts' THEN 1 ELSE 0 END) as shorts,
                SUM(COALESCE(download_file_size, 0)) as total_bytes
            FROM videos
        """).fetchone()

        deleted_count = conn.execute("SELECT COUNT(*) FROM deleted_videos").fetchone()[0]

    total_bytes = int(video_row["total_bytes"] or 0)
    total_mb = round(total_bytes / (1024 * 1024), 1)

    return {
        "channels": int(channels_count or 0),
        "total_channels": int(channels_count or 0),
        "videos": int(video_row["total"] or 0),
        "total_videos": int(video_row["total"] or 0),
        "downloaded": int(video_row["downloaded"] or 0),
        "downloaded_videos": int(video_row["downloaded"] or 0),
        "pending": int(video_row["pending"] or 0),
        "shorts_count": int(video_row["shorts"] or 0),
        "deleted_blacklisted": int(deleted_count or 0),
        "total_downloaded_bytes": total_bytes,
        "total_storage_mb": total_mb
    }


def get_all_channels() -> List[Dict[str, Any]]:
    """Retrieves all channels with aggregated video counts."""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT 
                c.*,
                COUNT(v.id) as video_count,
                SUM(CASE WHEN v.is_downloaded = 1 THEN 1 ELSE 0 END) as downloaded_count
            FROM channels c
            LEFT JOIN videos v ON v.channel_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
        """).fetchall()

    return [
        {
            "id": r["id"],
            "channel_id": r["channel_id"],
            "handle": r["handle"],
            "title": r["title"],
            "url": r["url"],
            "thumbnail": r["thumbnail"],
            "description": r["description"],
            "created_at": r["created_at"],
            "last_synced_at": r["last_synced_at"],
            "video_count": int(r["video_count"] or 0),
            "downloaded_count": int(r["downloaded_count"] or 0)
        }
        for r in rows
    ]


def get_channel_by_id(channel_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single channel by database ID."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if not row:
            return None

        counts = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_downloaded = 1 THEN 1 ELSE 0 END) as downloaded
            FROM videos WHERE channel_id = ?
        """, (channel_id,)).fetchone()

    return {
        "id": row["id"],
        "channel_id": row["channel_id"],
        "handle": row["handle"],
        "title": row["title"],
        "url": row["url"],
        "thumbnail": row["thumbnail"],
        "description": row["description"],
        "created_at": row["created_at"],
        "last_synced_at": row["last_synced_at"],
        "video_count": int(counts["total"] or 0),
        "downloaded_count": int(counts["downloaded"] or 0)
    }


def add_channel(url: str, title: Optional[str] = None) -> Dict[str, Any]:
    """Adds a new channel, fetches metadata, and performs initial video sync."""
    normalized_url = normalize_channel_url(url)
    entries = []
    try:
        channel_info, entries = fetch_channel_data_from_yt(normalized_url)
    except Exception as yt_err:
        # Fallback if network/offline or yt-dlp warning: create basic channel record with user URL & title
        handle_match = re.search(r"@([a-zA-Z0-9_\-\.]+)", normalized_url)
        channel_info = {
            "channel_id": handle_match.group(1) if handle_match else f"ch_{int(time.time())}",
            "handle": f"@{handle_match.group(1)}" if handle_match else "",
            "title": title.strip() if title and title.strip() else (handle_match.group(1) if handle_match else "YouTube Channel"),
            "url": normalized_url,
            "thumbnail": "",
            "description": ""
        }

    final_title = title.strip() if title and title.strip() else channel_info["title"]
    now = time.time()

    with get_db_connection() as conn:
        # Check if already exists
        existing = conn.execute(
            "SELECT id FROM channels WHERE channel_id = ? OR url = ?",
            (channel_info["channel_id"], channel_info["url"])
        ).fetchone()

        if existing:
            channel_db_id = existing["id"]
            conn.execute("""
                UPDATE channels 
                SET title = ?, thumbnail = COALESCE(?, thumbnail), last_synced_at = ?
                WHERE id = ?
            """, (final_title, channel_info["thumbnail"], now, channel_db_id))
        else:
            cur = conn.execute("""
                INSERT INTO channels (channel_id, handle, title, url, thumbnail, description, created_at, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                channel_info["channel_id"],
                channel_info["handle"],
                final_title,
                channel_info["url"],
                channel_info["thumbnail"],
                channel_info["description"],
                now,
                now
            ))
            channel_db_id = cur.lastrowid

        conn.commit()

    # Sync videos for this channel
    sync_res = sync_channel_videos(channel_db_id, entries) if entries else {"synced": 0, "skipped_blacklisted": 0, "total": 0}
    saved = get_channel_by_id(channel_db_id) or {}
    return {
        **saved,
        "channel": saved,
        "sync_result": sync_res
    }


def update_channel(channel_id: int, title: Optional[str] = None, url: Optional[str] = None) -> Dict[str, Any]:
    """Updates a channel title or URL."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if not row:
            raise KeyError("Channel not found.")

        new_title = title.strip() if title and title.strip() else row["title"]
        new_url = normalize_channel_url(url) if url and url.strip() else row["url"]

        conn.execute("""
            UPDATE channels SET title = ?, url = ? WHERE id = ?
        """, (new_title, new_url, channel_id))
        conn.commit()

    return get_channel_by_id(channel_id)


def delete_channel(channel_id: int) -> bool:
    """Deletes a channel, its videos, and downloaded files."""
    with get_db_connection() as conn:
        video_rows = conn.execute(
            "SELECT download_path, youtube_id FROM videos WHERE channel_id = ?",
            (channel_id,)
        ).fetchall()

        # Delete physical files
        for vr in video_rows:
            p = vr["download_path"]
            if p and Path(p).exists():
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass

        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        conn.commit()

    return True


def sync_channel_by_id(channel_id: int) -> Dict[str, Any]:
    """Re-syncs videos for an existing channel using yt-dlp."""
    ch = get_channel_by_id(channel_id)
    if not ch:
        raise KeyError("Channel not found.")

    normalized_url = normalize_channel_url(ch["url"])
    channel_info, entries = fetch_channel_data_from_yt(normalized_url)

    now = time.time()
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE channels 
            SET thumbnail = COALESCE(?, thumbnail), last_synced_at = ?
            WHERE id = ?
        """, (channel_info.get("thumbnail"), now, channel_id))
        conn.commit()

    sync_res = sync_channel_videos(channel_id, entries)
    return {
        "channel": get_channel_by_id(channel_id),
        "sync": sync_res
    }


def sync_channel_videos(channel_id: int, entries: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Saves or updates channel videos in the database.
    CRITICAL: Any video in `deleted_videos` table is SKIPPED and NOT added back!
    """
    now = time.time()
    added = 0
    updated = 0
    skipped_deleted = 0

    with get_db_connection() as conn:
        # Load deleted blacklist for this channel or globally
        deleted_set = {
            r[0] for r in conn.execute("SELECT youtube_id FROM deleted_videos").fetchall()
        }

        # Existing videos in DB
        existing_map = {
            r["youtube_id"]: r["id"]
            for r in conn.execute("SELECT id, youtube_id FROM videos WHERE channel_id = ?", (channel_id,)).fetchall()
        }

        for item in entries:
            yt_id = item.get("id") or item.get("url")
            if not yt_id:
                continue

            # Strip full URL to ID if needed
            if "watch?v=" in yt_id:
                yt_id = yt_id.split("watch?v=")[-1].split("&")[0]

            # 1. Check blacklist: if previously deleted by user, do NOT add back!
            if yt_id in deleted_set:
                skipped_deleted += 1
                continue

            item_title = item.get("title") or "Untitled Video"
            item_url = item.get("url") or f"https://www.youtube.com/watch?v={yt_id}"
            if not item_url.startswith("http"):
                item_url = f"https://www.youtube.com/watch?v={yt_id}"

            # Thumbnail
            thumb = item.get("thumbnail") or ""
            if not thumb and item.get("thumbnails"):
                thumb = item["thumbnails"][-1].get("url") or ""

            dur = int(item.get("duration") or 0)
            view_cnt = int(item.get("view_count") or 0)
            desc = item.get("description") or ""

            if yt_id in existing_map:
                # Update metadata only (preserve is_downloaded, download_path, etc.)
                conn.execute("""
                    UPDATE videos 
                    SET title = ?, thumbnail = COALESCE(?, thumbnail), duration = CASE WHEN duration <= 0 THEN ? ELSE duration END, view_count = ?
                    WHERE id = ?
                """, (item_title, thumb, dur, view_cnt, existing_map[yt_id]))
                updated += 1
            else:
                conn.execute("""
                    INSERT INTO videos (
                        channel_id, youtube_id, title, description, url, thumbnail,
                        duration, view_count, is_downloaded, download_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'undownloaded', ?)
                """, (channel_id, yt_id, item_title, desc, item_url, thumb, dur, view_cnt, now))
                added += 1

        conn.commit()

    return {
        "total_entries": len(entries),
        "added": added,
        "updated": updated,
        "skipped_deleted": skipped_deleted
    }


def get_channel_videos(
    channel_id: int,
    status_filter: str = "all",
    search: str = "",
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """Retrieves videos for a specific channel with optional filtering."""
    with get_db_connection() as conn:
        conditions = ["channel_id = ?"]
        params: List[Any] = [channel_id]

        if status_filter == "downloaded":
            conditions.append("is_downloaded = 1")
        elif status_filter == "undownloaded":
            conditions.append("is_downloaded = 0")

        if search and search.strip():
            conditions.append("title LIKE ?")
            params.append(f"%{search.strip()}%")

        where_clause = " AND ".join(conditions)

        total_row = conn.execute(f"SELECT COUNT(*) FROM videos WHERE {where_clause}", params).fetchone()
        total = int(total_row[0] or 0)

        query = f"""
            SELECT * FROM videos 
            WHERE {where_clause}
            ORDER BY is_downloaded DESC, id DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

    videos_list = []
    for r in rows:
        vid_id = r["id"]
        # Merge active download progress if running
        active = active_ytd_downloads.get(vid_id)
        v_dict = dict(r)
        v_dict["duration_seconds"] = v_dict.get("duration", 0)
        if v_dict.get("download_file_size"):
            v_dict["file_size_mb"] = round(v_dict["download_file_size"] / (1024 * 1024), 1)
        if active:
            v_dict["download_status"] = active.get("status", v_dict["download_status"])
            v_dict["download_progress"] = active.get("progress", v_dict["download_progress"])
            v_dict["download_step"] = active.get("step")
            if active.get("error"):
                v_dict["download_error"] = active.get("error")

        videos_list.append(v_dict)

    return {
        "videos": videos_list,
        "total": total
    }


def get_video_by_id(video_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single video by database ID."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        if not row:
            return None
        v_dict = dict(row)
        v_dict["duration_seconds"] = v_dict.get("duration", 0)
        if v_dict.get("download_file_size"):
            v_dict["file_size_mb"] = round(v_dict["download_file_size"] / (1024 * 1024), 1)
        active = active_ytd_downloads.get(video_id)
        if active:
            v_dict["download_status"] = active.get("status", v_dict["download_status"])
            v_dict["download_progress"] = active.get("progress", v_dict["download_progress"])
            v_dict["download_step"] = active.get("step")
            if active.get("error"):
                v_dict["download_error"] = active.get("error")
        return v_dict


def delete_video(video_id: int) -> Dict[str, Any]:
    """
    Deletes a video from the database, removes its files from disk,
    and adds its YouTube ID to the `deleted_videos` blacklist
    so it can NEVER be re-added on subsequent channel syncs.
    """
    video = get_video_by_id(video_id)
    if not video:
        raise KeyError("Video not found.")

    yt_id = video["youtube_id"]
    ch_id = video["channel_id"]
    v_title = video["title"]

    # 1. Clean up downloaded files from disk
    if video.get("download_path"):
        try:
            Path(video["download_path"]).unlink(missing_ok=True)
        except Exception:
            pass

    # Also clean up possible associated zip or part folders
    for ext in [".mp4", ".zip"]:
        f_p = YTD_DOWNLOADS_DIR / f"{yt_id}{ext}"
        if f_p.exists():
            f_p.unlink(missing_ok=True)

    parts_dir = YTD_DOWNLOADS_DIR / f"{yt_id}_parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir, ignore_errors=True)

    shorts_dir = YTD_DOWNLOADS_DIR / f"{yt_id}_shorts"
    if shorts_dir.exists():
        shutil.rmtree(shorts_dir, ignore_errors=True)

    # 2. Add to deleted blacklist table and delete from videos table
    now = time.time()
    with get_db_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO deleted_videos (youtube_id, channel_id, title, deleted_at)
            VALUES (?, ?, ?, ?)
        """, (yt_id, ch_id, v_title, now))

        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        conn.commit()

    active_ytd_downloads.pop(video_id, None)

    return {
        "status": "deleted",
        "video_id": video_id,
        "youtube_id": yt_id,
        "title": v_title,
        "blacklisted": True
    }


def split_video_into_parts(
    input_file: Path,
    youtube_id: str,
    safe_title: str,
    split_seconds: int
) -> Tuple[Path, str, int, int]:
    """
    Splits video into parts of `split_seconds` (e.g. 2, 5, or 9 mins)
    and packages them into a ZIP archive.
    Returns (zip_path, zip_name, file_size, parts_count).
    """
    parts_dir = YTD_DOWNLOADS_DIR / f"{youtube_id}_parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir, ignore_errors=True)
    parts_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(parts_dir / f"{safe_title} - Part %02d.mp4")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_file),
        "-c", "copy",
        "-map", "0",
        "-segment_time", str(split_seconds),
        "-segment_start_number", "1",
        "-f", "segment",
        "-reset_timestamps", "1",
        pattern
    ]

    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    part_files = sorted(list(parts_dir.glob("*.mp4")))
    if not part_files:
        raise RuntimeError("Splitting completed but no MP4 parts were created.")

    zip_file_name = f"{safe_title} (Parts).zip"
    zip_path = YTD_DOWNLOADS_DIR / f"{youtube_id}_parts.zip"
    zip_path.unlink(missing_ok=True)

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_STORED) as zf:
        for p in part_files:
            zf.write(str(p), arcname=p.name)

    # Clean up parts directory
    shutil.rmtree(parts_dir, ignore_errors=True)

    return zip_path, zip_file_name, zip_path.stat().st_size, len(part_files)


def generate_shorts_from_video(
    input_file: Path,
    youtube_id: str,
    safe_title: str,
    shorts_count: int,
    total_duration: float
) -> Tuple[Path, str, int, int]:
    """
    Detects top climax moments and renders vertical 9:16 shorts (1080x1920)
    with ambient wings and packages into a ZIP archive.
    Returns (zip_path, zip_name, file_size, shorts_count).
    """
    shorts_dir = YTD_DOWNLOADS_DIR / f"{youtube_id}_shorts"
    if shorts_dir.exists():
        shutil.rmtree(shorts_dir, ignore_errors=True)
    shorts_dir.mkdir(parents=True, exist_ok=True)

    moments = ShortsGenerator.detect_top_moments(
        video_path=input_file,
        duration_seconds=total_duration,
        num_moments=shorts_count,
        moment_duration=45.0
    )

    rendered_shorts = []
    for m in moments:
        idx = m["index"]
        out_short = shorts_dir / f"{safe_title} - Short {idx}.mp4"
        ShortsGenerator.create_vertical_short(
            input_video=input_file,
            output_path=out_short,
            start_seconds=m["start_seconds"],
            duration_seconds=m["duration_seconds"],
            aspect_ratio="9:16"
        )
        if out_short.exists():
            rendered_shorts.append(out_short)

    if not rendered_shorts:
        raise RuntimeError("No vertical shorts were generated.")

    zip_file_name = f"{safe_title} (Shorts).zip"
    zip_path = YTD_DOWNLOADS_DIR / f"{youtube_id}_shorts.zip"
    zip_path.unlink(missing_ok=True)

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_STORED) as zf:
        for s in rendered_shorts:
            zf.write(str(s), arcname=s.name)

    # Clean up temporary folder
    shutil.rmtree(shorts_dir, ignore_errors=True)

    return zip_path, zip_file_name, zip_path.stat().st_size, len(rendered_shorts)


def process_video_download_task(
    video_id: int,
    download_type: str = "full",
    split_minutes: int = 5,
    shorts_count: int = 3
):
    """
    Worker task that downloads the video and optionally splits or creates shorts.
    """
    video = get_video_by_id(video_id)
    if not video:
        return

    yt_id = video["youtube_id"]
    yt_url = video["url"]
    raw_title = video["title"] or f"video_{yt_id}"
    safe_title = re.sub(r'[\r\n\t]+', ' ', raw_title)
    safe_title = re.sub(r'[/\\?%*:|"<>]+', '_', safe_title)[:80].strip() or "video"

    active_ytd_downloads[video_id] = {
        "status": "downloading",
        "progress": 5,
        "step": "Downloading video from YouTube...",
        "error": None
    }

    with get_db_connection() as conn:
        conn.execute("""
            UPDATE videos SET download_status = 'downloading', download_progress = 5, download_error = NULL
            WHERE id = ?
        """, (video_id,))
        conn.commit()

    raw_mp4_path = YTD_DOWNLOADS_DIR / f"{yt_id}.mp4"

    try:
        # Check if source MP4 is already downloaded and valid on disk
        reuse_existing = (
            download_type in ["split", "splits", "shorts"] and
            raw_mp4_path.exists() and
            raw_mp4_path.stat().st_size > 1024
        )

        if not reuse_existing:
            # Step 1: Download highest quality 720p/1080p MP4
            cmd = [
                "yt-dlp",
                "--ignore-config",
                "--no-playlist",
                "--no-progress",
                "--newline",
                "--progress",
                "--socket-timeout", "35",
                "--force-overwrites",
                "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
                "--merge-output-format", "mp4",
            ] + get_ytdlp_auth_args() + [
                "-o", str(raw_mp4_path),
                "--",
                yt_url
            ]

            last_error_msg = None
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            if proc.stdout:
                for line in proc.stdout:
                    if "ERROR:" in line:
                        last_error_msg = line.replace("ERROR:", "").strip()
                    elif "Sign in to confirm" in line:
                        last_error_msg = "YouTube sign-in required. Please sync or upload cookies.txt."
                    elif "HTTP Error 403" in line:
                        last_error_msg = "HTTP 403 Forbidden. Session cookies may be expired. Please re-sync cookies."

                    m = re.search(r"\[download\]\s+([\d.]+)%", line)
                    if m:
                        pct = min(85, max(5, int(float(m.group(1)) * 0.85)))
                        active_ytd_downloads[video_id] = {
                            "status": "downloading",
                            "progress": pct,
                            "step": f"Downloading from YouTube ({m.group(1)}%)...",
                            "error": None
                        }

            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(last_error_msg or f"yt-dlp exited with error code {proc.returncode}")

            if not raw_mp4_path.exists() or raw_mp4_path.stat().st_size == 0:
                raise RuntimeError("Video download finished but MP4 file was not found on disk.")

        total_dur = float(video.get("duration") or 0)
        if total_dur <= 0:
            # Probe duration with ffprobe
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(raw_mp4_path)]
                dur_res = subprocess.check_output(probe_cmd, text=True).strip()
                total_dur = float(dur_res)
            except Exception:
                total_dur = 300.0

        # Step 2: Handle download type
        if download_type in ["split", "splits"]:
            active_ytd_downloads[video_id] = {
                "status": "processing",
                "progress": 90,
                "step": f"Splitting into {split_minutes}-minute parts and packaging ZIP...",
                "error": None
            }
            split_secs = int(split_minutes) * 60
            zip_path, zip_name, fsize, parts_cnt = split_video_into_parts(
                raw_mp4_path, yt_id, safe_title, split_secs
            )

            # Update DB with Split Zip
            with get_db_connection() as conn:
                conn.execute("""
                    UPDATE videos 
                    SET is_downloaded = 1,
                        download_status = 'downloaded',
                        download_progress = 100,
                        download_path = ?,
                        download_file_name = ?,
                        download_file_size = ?,
                        download_type = 'split',
                        split_duration = ?,
                        parts_count = ?,
                        is_zip = 1,
                        downloaded_at = ?,
                        download_error = NULL
                    WHERE id = ?
                """, (str(zip_path), zip_name, fsize, split_secs, parts_cnt, time.time(), video_id))
                conn.commit()

        elif download_type == "shorts":
            active_ytd_downloads[video_id] = {
                "status": "processing",
                "progress": 90,
                "step": f"Generating {shorts_count} vertical 9:16 shorts from climax moments...",
                "error": None
            }
            zip_path, zip_name, fsize, sc_cnt = generate_shorts_from_video(
                raw_mp4_path, yt_id, safe_title, shorts_count, total_dur
            )

            # Update DB with Shorts Zip
            with get_db_connection() as conn:
                conn.execute("""
                    UPDATE videos 
                    SET is_downloaded = 1,
                        download_status = 'downloaded',
                        download_progress = 100,
                        download_path = ?,
                        download_file_name = ?,
                        download_file_size = ?,
                        download_type = 'shorts',
                        shorts_count = ?,
                        is_zip = 1,
                        downloaded_at = ?,
                        download_error = NULL
                    WHERE id = ?
                """, (str(zip_path), zip_name, fsize, sc_cnt, time.time(), video_id))
                conn.commit()

        else:
            # Full Video
            file_size = raw_mp4_path.stat().st_size
            full_file_name = f"{safe_title}.mp4"

            with get_db_connection() as conn:
                conn.execute("""
                    UPDATE videos 
                    SET is_downloaded = 1,
                        download_status = 'downloaded',
                        download_progress = 100,
                        download_path = ?,
                        download_file_name = ?,
                        download_file_size = ?,
                        download_type = 'full',
                        is_zip = 0,
                        downloaded_at = ?,
                        download_error = NULL
                    WHERE id = ?
                """, (str(raw_mp4_path), full_file_name, file_size, time.time(), video_id))
                conn.commit()

        active_ytd_downloads[video_id] = {
            "status": "downloaded",
            "progress": 100,
            "step": "Completed",
            "error": None
        }

    except Exception as e:
        err_msg = str(e)
        active_ytd_downloads[video_id] = {
            "status": "error",
            "progress": 0,
            "step": "Failed",
            "error": err_msg
        }
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE videos 
                SET download_status = 'error', download_progress = 0, download_error = ?
                WHERE id = ?
            """, (err_msg, video_id))
            conn.commit()


def queue_video_download(
    video_id: int,
    download_type: str = "full",
    split_minutes: int = 5,
    shorts_count: int = 3
) -> Dict[str, Any]:
    """Queues asynchronous video download."""
    video = get_video_by_id(video_id)
    if not video:
        raise KeyError("Video not found.")

    if active_ytd_downloads.get(video_id, {}).get("status") in ["downloading", "processing", "queued"]:
        return {
            "status": "already_running",
            "video_id": video_id
        }

    active_ytd_downloads[video_id] = {
        "status": "downloading",
        "progress": 1,
        "step": "Starting download task...",
        "error": None
    }

    with get_db_connection() as conn:
        conn.execute("""
            UPDATE videos 
            SET download_status = 'downloading', download_progress = 1, download_error = NULL
            WHERE id = ?
        """, (video_id,))
        conn.commit()

    ytd_executor.submit(
        process_video_download_task,
        video_id,
        download_type,
        split_minutes,
        shorts_count
    )

    return {
        "status": "started",
        "video_id": video_id,
        "download_type": download_type,
        "split_minutes": split_minutes,
        "shorts_count": shorts_count
    }


# =========================================================================
# Direct YouTube Video Downloader Subsystem
# =========================================================================

def extract_youtube_id(url_or_id: str) -> Optional[str]:
    """
    Extracts an 11-character YouTube video ID from various URL formats or raw ID.
    Supports:
      - Raw 11-char ID
      - https://www.youtube.com/watch?v=ID
      - https://youtu.be/ID
      - https://www.youtube.com/shorts/ID
      - https://www.youtube.com/embed/ID
      - https://www.youtube.com/live/ID
      - Mobile & query param variations
    """
    val = str(url_or_id or "").strip()
    if not val:
        return None

    # Check for direct 11-char alphanumeric ID
    if re.match(r"^[a-zA-Z0-9_-]{11}$", val):
        return val

    # Match common YouTube URL patterns
    patterns = [
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/|\/live\/)([a-zA-Z0-9_-]{11})",
        r"[?&]v=([a-zA-Z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, val)
        if m:
            return m.group(1)

    return None


def fetch_direct_video_metadata(youtube_id: str) -> Dict[str, Any]:
    """
    Fetches video metadata (title, thumbnail, duration, uploader) using yt-dlp.
    Falls back gracefully to standard metadata if yt-dlp is slow or blocked.
    """
    url = f"https://www.youtube.com/watch?v={youtube_id}"
    default_meta = {
        "youtube_id": youtube_id,
        "url": url,
        "title": f"YouTube Video ({youtube_id})",
        "thumbnail": f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg",
        "duration": 0,
        "view_count": 0,
        "channel_name": "YouTube",
        "description": ""
    }

    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        "--ignore-config",
        "--socket-timeout", "25",
    ] + get_ytdlp_auth_args() + [
        "--",
        url
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=40, check=True)
        data = json.loads(res.stdout)

        thumb = data.get("thumbnail") or default_meta["thumbnail"]
        thumbs = data.get("thumbnails") or []
        if isinstance(thumbs, list) and len(thumbs) > 0:
            for t in reversed(thumbs):
                if t.get("url"):
                    thumb = t.get("url")
                    break

        return {
            "youtube_id": youtube_id,
            "url": url,
            "title": data.get("title") or default_meta["title"],
            "thumbnail": thumb,
            "duration": int(data.get("duration") or 0),
            "view_count": int(data.get("view_count") or 0),
            "channel_name": data.get("uploader") or data.get("channel") or "YouTube",
            "description": str(data.get("description") or "")[:500]
        }
    except Exception as e:
        print(f"[DirectYTD] Warning: Failed to fetch metadata for {youtube_id}: {e}")
        return default_meta


def get_direct_video_by_id(video_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single direct video record by database ID."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM direct_videos WHERE id = ?", (video_id,)).fetchone()
        if not row:
            return None
        v = dict(row)
        if v.get("download_file_size"):
            v["file_size_mb"] = round(v["download_file_size"] / (1024 * 1024), 1)
        else:
            v["file_size_mb"] = 0

        active = active_direct_downloads.get(video_id)
        if active:
            v["download_status"] = active.get("status", v["download_status"])
            v["download_progress"] = active.get("progress", v["download_progress"])
            if active.get("error"):
                v["download_error"] = active.get("error")
        return v


def get_direct_video_by_youtube_id(youtube_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a direct video record by YouTube ID."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM direct_videos WHERE youtube_id = ?", (youtube_id,)).fetchone()
        if not row:
            return None
        v = dict(row)
        if v.get("download_file_size"):
            v["file_size_mb"] = round(v["download_file_size"] / (1024 * 1024), 1)
        else:
            v["file_size_mb"] = 0

        active = active_direct_downloads.get(v["id"])
        if active:
            v["download_status"] = active.get("status", v["download_status"])
            v["download_progress"] = active.get("progress", v["download_progress"])
            if active.get("error"):
                v["download_error"] = active.get("error")
        return v


def check_direct_video_exists(url_or_id: str) -> Dict[str, Any]:
    """
    Checks if a YouTube video URL or ID is already saved in direct downloads.
    Used for instant duplicate verification in the UI.
    """
    yt_id = extract_youtube_id(url_or_id)
    if not yt_id:
        return {
            "valid": False,
            "error": "Invalid YouTube URL or ID"
        }

    existing = get_direct_video_by_youtube_id(yt_id)
    if existing:
        return {
            "valid": True,
            "youtube_id": yt_id,
            "exists": True,
            "video": existing
        }

    return {
        "valid": True,
        "youtube_id": yt_id,
        "exists": False,
        "video": None
    }


def add_direct_video(url: str, title: Optional[str] = None, auto_download: bool = True) -> Dict[str, Any]:
    """
    Adds a direct YouTube video link. If it already exists, returns the existing record.
    If auto_download is True, queues the video download immediately.
    """
    yt_id = extract_youtube_id(url)
    if not yt_id:
        raise ValueError("Invalid YouTube URL. Please provide a valid YouTube video link or ID.")

    existing = get_direct_video_by_youtube_id(yt_id)
    if existing:
        # If user explicitly requested auto_download and file is not present on disk
        if auto_download and not existing["is_downloaded"] and existing["download_status"] not in ["downloading", "queued"]:
            queue_direct_video_download(existing["id"])
            existing = get_direct_video_by_id(existing["id"])
        return {
            "already_exists": True,
            "video": existing
        }

    # Fetch metadata
    meta = fetch_direct_video_metadata(yt_id)
    final_title = title.strip() if title and title.strip() else meta["title"]
    now = time.time()

    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO direct_videos (
                youtube_id, url, title, description, thumbnail, duration,
                view_count, channel_name, download_status, download_progress,
                is_downloaded, was_downloaded, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, 0, ?, ?)
        """, (
            yt_id,
            meta["url"],
            final_title,
            meta.get("description", ""),
            meta.get("thumbnail", ""),
            meta.get("duration", 0),
            meta.get("view_count", 0),
            meta.get("channel_name", ""),
            now,
            now
        ))
        video_id = cursor.lastrowid
        conn.commit()

    if auto_download:
        queue_direct_video_download(video_id)

    return {
        "already_exists": False,
        "video": get_direct_video_by_id(video_id)
    }


def queue_direct_video_download(video_id: int) -> Dict[str, Any]:
    """Queues a direct video for background downloading via yt-dlp."""
    video = get_direct_video_by_id(video_id)
    if not video:
        raise KeyError("Direct video not found.")

    if active_direct_downloads.get(video_id, {}).get("status") in ["downloading", "queued"]:
        return {
            "status": "already_running",
            "video_id": video_id
        }

    active_direct_downloads[video_id] = {
        "status": "queued",
        "progress": 2,
        "step": "Queued for download...",
        "error": None
    }

    with get_db_connection() as conn:
        conn.execute("""
            UPDATE direct_videos
            SET download_status = 'queued', download_progress = 2, download_error = NULL, updated_at = ?
            WHERE id = ?
        """, (time.time(), video_id))
        conn.commit()

    ytd_executor.submit(_execute_direct_download_task, video_id)

    return {
        "status": "started",
        "video_id": video_id
    }


def _execute_direct_download_task(video_id: int):
    """Worker task that uses yt-dlp to download the direct video."""
    video = get_direct_video_by_id(video_id)
    if not video:
        return

    yt_id = video["youtube_id"]
    safe_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', video.get("title") or yt_id).strip()[:40] or yt_id
    filename = f"{yt_id}_{safe_title}.mp4"
    mp4_path = DIRECT_DOWNLOADS_DIR / filename

    active_direct_downloads[video_id] = {
        "status": "downloading",
        "progress": 5,
        "step": "Downloading direct video...",
        "error": None
    }

    with get_db_connection() as conn:
        conn.execute("""
            UPDATE direct_videos
            SET download_status = 'downloading', download_progress = 5, download_error = NULL, updated_at = ?
            WHERE id = ?
        """, (time.time(), video_id))
        conn.commit()

    cmd = [
        "yt-dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-progress",
        "--newline",
        "--progress",
        "--socket-timeout", "35",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "--merge-output-format", "mp4",
    ] + get_ytdlp_auth_args() + [
        "-o", str(mp4_path),
        "--",
        f"https://www.youtube.com/watch?v={yt_id}"
    ]

    try:
        last_error_msg = None
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in proc.stdout:
            if "ERROR:" in line:
                last_error_msg = line.replace("ERROR:", "").strip()
            elif "Sign in to confirm" in line:
                last_error_msg = "YouTube sign-in required (bot check). Please sync or upload cookies.txt."
            elif "HTTP Error 403" in line:
                last_error_msg = "HTTP 403 Forbidden. Session cookies may be expired. Please re-sync cookies."

            m = re.search(r"\[download\]\s+([\d\.]+)%", line)
            if m:
                try:
                    pct = int(float(m.group(1)))
                    active_direct_downloads[video_id] = {
                        "status": "downloading",
                        "progress": pct,
                        "step": f"Downloading ({pct}%)...",
                        "error": None
                    }
                    if pct % 10 == 0:
                        with get_db_connection() as conn:
                            conn.execute("UPDATE direct_videos SET download_progress = ? WHERE id = ?", (pct, video_id))
                            conn.commit()
                except Exception:
                    pass

        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(last_error_msg or f"yt-dlp exited with code {proc.returncode}")

        if not mp4_path.exists() or mp4_path.stat().st_size == 0:
            raise RuntimeError("Downloaded video file is missing or empty.")

        file_size = mp4_path.stat().st_size
        now = time.time()

        # Probe duration if missing
        total_dur = int(video.get("duration") or 0)
        if total_dur <= 0:
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(mp4_path)]
                dur_res = subprocess.check_output(probe_cmd, text=True).strip()
                total_dur = int(float(dur_res))
            except Exception:
                pass

        with get_db_connection() as conn:
            conn.execute("""
                UPDATE direct_videos
                SET is_downloaded = 1,
                    was_downloaded = 1,
                    download_status = 'downloaded',
                    download_progress = 100,
                    download_path = ?,
                    download_file_name = ?,
                    download_file_size = ?,
                    duration = CASE WHEN duration <= 0 THEN ? ELSE duration END,
                    downloaded_at = ?,
                    updated_at = ?,
                    download_error = NULL
                WHERE id = ?
            """, (str(mp4_path), filename, file_size, total_dur, now, now, video_id))
            conn.commit()

        active_direct_downloads[video_id] = {
            "status": "downloaded",
            "progress": 100,
            "step": "Completed",
            "error": None
        }

    except Exception as e:
        err_msg = str(e)
        active_direct_downloads[video_id] = {
            "status": "error",
            "progress": 0,
            "step": "Failed",
            "error": err_msg
        }
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE direct_videos
                SET download_status = 'error', download_progress = 0, download_error = ?, updated_at = ?
                WHERE id = ?
            """, (err_msg, time.time(), video_id))
            conn.commit()


def delete_direct_video_file_only(video_id: int) -> Dict[str, Any]:
    """
    Deletes ONLY the downloaded video file from disk to reduce storage.
    The video record is preserved in the database to verify in the future that it was already downloaded.
    """
    video = get_direct_video_by_id(video_id)
    if not video:
        raise KeyError("Direct video record not found.")

    if video.get("download_path"):
        try:
            Path(video["download_path"]).unlink(missing_ok=True)
        except Exception:
            pass

    yt_id = video["youtube_id"]
    for p in DIRECT_DOWNLOADS_DIR.glob(f"{yt_id}*"):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    now = time.time()
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE direct_videos
            SET is_downloaded = 0,
                was_downloaded = 1,
                download_status = 'file_deleted',
                download_path = NULL,
                download_file_name = NULL,
                download_file_size = 0,
                download_progress = 0,
                file_deleted_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (now, now, video_id))
        conn.commit()

    active_direct_downloads.pop(video_id, None)
    return get_direct_video_by_id(video_id)


def delete_direct_video_permanent(video_id: int) -> Dict[str, Any]:
    """
    Permanently deletes the direct video file from disk AND removes its record from the database.
    """
    video = get_direct_video_by_id(video_id)
    if not video:
        raise KeyError("Direct video record not found.")

    if video.get("download_path"):
        try:
            Path(video["download_path"]).unlink(missing_ok=True)
        except Exception:
            pass

    yt_id = video["youtube_id"]
    for p in DIRECT_DOWNLOADS_DIR.glob(f"{yt_id}*"):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    with get_db_connection() as conn:
        conn.execute("DELETE FROM direct_videos WHERE id = ?", (video_id,))
        conn.commit()

    active_direct_downloads.pop(video_id, None)
    return {"status": "deleted", "id": video_id}


def get_all_direct_videos(
    search: str = "",
    status_filter: str = "all",
    limit: int = 250,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Returns direct video records with optional search and status filtering."""
    query = "SELECT * FROM direct_videos WHERE 1=1"
    params = []

    if search and search.strip():
        s = f"%{search.strip().lower()}%"
        query += " AND (LOWER(title) LIKE ? OR LOWER(url) LIKE ? OR LOWER(youtube_id) LIKE ? OR LOWER(channel_name) LIKE ?)"
        params.extend([s, s, s, s])

    if status_filter == "downloaded":
        query += " AND is_downloaded = 1"
    elif status_filter == "file_deleted":
        query += " AND (download_status = 'file_deleted' OR (was_downloaded = 1 AND is_downloaded = 0))"
    elif status_filter == "active":
        query += " AND download_status IN ('downloading', 'queued')"
    elif status_filter == "pending":
        query += " AND download_status = 'pending'"

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    results = []
    for r in rows:
        v = dict(r)
        if v.get("download_file_size"):
            v["file_size_mb"] = round(v["download_file_size"] / (1024 * 1024), 1)
        else:
            v["file_size_mb"] = 0

        active = active_direct_downloads.get(v["id"])
        if active:
            v["download_status"] = active.get("status", v["download_status"])
            v["download_progress"] = active.get("progress", v["download_progress"])
            if active.get("error"):
                v["download_error"] = active.get("error")
        results.append(v)

    return results


def get_direct_stats() -> Dict[str, Any]:
    """Returns statistics for direct video downloads."""
    with get_db_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM direct_videos").fetchone()[0]
        on_disk = conn.execute("SELECT COUNT(*) FROM direct_videos WHERE is_downloaded = 1").fetchone()[0]
        storage_saved = conn.execute("SELECT COUNT(*) FROM direct_videos WHERE download_status = 'file_deleted' OR (was_downloaded = 1 AND is_downloaded = 0)").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM direct_videos WHERE download_status IN ('downloading', 'queued')").fetchone()[0]
        disk_bytes = conn.execute("SELECT COALESCE(SUM(download_file_size), 0) FROM direct_videos WHERE is_downloaded = 1").fetchone()[0]

    return {
        "total_records": total,
        "on_disk_count": on_disk,
        "storage_saved_count": storage_saved,
        "active_downloads": active,
        "disk_bytes": disk_bytes,
        "disk_mb": round(disk_bytes / (1024 * 1024), 1)
    }
