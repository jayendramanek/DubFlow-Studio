"""
DubFlow Studio - FastAPI Production Server for Universal Local Video Dubbing
============================================================================
High-performance REST API with background task execution,
Apple Silicon MPS monitoring, job tracking, and file streaming.
"""

import os
import sys
import json
import uuid
import time
import shutil
import asyncio
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
from concurrent.futures import ThreadPoolExecutor

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from pipeline import (
    ManhwaDubbingPipeline,
    HardwareAccelerationManager,
    AppleSiliconManager,
    YouTubeDownloader,
    find_cookies_file,
    sync_browser_cookies,
    AudioDemixer,
    TimedTranscriber,
    SegmentTranslator,
    TimestampAwareTTS,
    VideoRemuxer,
    ShortsGenerator,
    GermanMetadataGenerator,
    GermanThumbnailGenerator,
    MultilingualMetadataGenerator,
    MultilingualThumbnailGenerator,
    LANGUAGE_SEO_CONFIG,
    logger
)

# App directory configuration
BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_DIR = BASE_DIR / "workspace_api" / "uploads"
JOBS_DIR = BASE_DIR / "workspace_api" / "jobs"
STATIC_DIR = BASE_DIR / "static"
VIDEOS_CACHE_DIR = BASE_DIR / "workspace_api" / "videos_cache"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
VIDEOS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Restore or detect YouTube cookies from environment / disk (supports VM / Docker deployments)
try:
    find_cookies_file()
except Exception:
    pass


def extract_youtube_id(url: Optional[str]) -> Optional[str]:
    """Extracts standard 11-character YouTube video ID from various URL formats."""
    if not url:
        return None
    url = url.strip()
    patterns = [
        r"(?:v=|\/v\/|embed\/|shorts\/|youtu\.be\/|\/e\/|watch\?v=)([a-zA-Z0-9_-]{11})",
        r"^[a-zA-Z0-9_-]{11}$"
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1) if m.groups() else m.group(0)
    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1].split("?")[0].split("&")[0]
    if "v=" in url:
        return url.split("v=")[-1].split("&")[0].split("?")[0]
    return None


import db

# Sequential thread pool executor (1 worker active at a time to optimize Apple Silicon RAM/GPU; subsequent videos/parts wait in queue)
executor = ThreadPoolExecutor(max_workers=1)

class JobCancelledException(Exception):
    """Raised when a dubbing job is cancelled by the user."""
    pass

# Active cancelled job IDs to abort immediately
CANCELLED_JOBS: Set[str] = set()

# Persistent databases for jobs and videos
jobs_db, videos_db = db.load_databases(JOBS_DIR, BASE_DIR / "workspace_api")

# Active WebSocket connections per job
ws_connections: Dict[str, List[WebSocket]] = {}

# Supported voices database
SUPPORTED_VOICES = {
    "es": {
        "name": "Spanish",
        "voices": [
            {"id": "es-ES-AlvaroNeural", "gender": "Male", "region": "Spain", "description": "Dramatic recap narrator"},
            {"id": "es-MX-JorgeNeural", "gender": "Male", "region": "Mexico", "description": "Energetic anime narrator"},
            {"id": "es-ES-ElviraNeural", "gender": "Female", "region": "Spain", "description": "Expressive female voice"},
            {"id": "es-MX-DaliaNeural", "gender": "Female", "region": "Mexico", "description": "Smooth female voice"},
        ]
    },
    "ta": {
        "name": "Tamil (தமிழ்)",
        "voices": [
            {"id": "ta-IN-ValluvarNeural", "gender": "Male", "region": "India", "description": "Dramatic Tamil male narrator"},
            {"id": "ta-IN-PallaviNeural", "gender": "Female", "region": "India", "description": "Expressive Tamil female"},
        ]
    },
    "te": {
        "name": "Telugu (తెలుగు)",
        "voices": [
            {"id": "te-IN-MohanNeural", "gender": "Male", "region": "India", "description": "Energetic Telugu male narrator"},
            {"id": "te-IN-ShrutiNeural", "gender": "Female", "region": "India", "description": "Smooth Telugu female"},
        ]
    },
    "bn": {
        "name": "Bengali (বাংলা)",
        "voices": [
            {"id": "bn-IN-BashkarNeural", "gender": "Male", "region": "India", "description": "Indian Bengali male narrator"},
            {"id": "bn-IN-TanishaaNeural", "gender": "Female", "region": "India", "description": "Indian Bengali female"},
            {"id": "bn-BD-PradeepNeural", "gender": "Male", "region": "Bangladesh", "description": "Bangladeshi Bengali male"},
        ]
    },
    "hi": {
        "name": "Hindi (हिन्दी)",
        "voices": [
            {"id": "hi-IN-MadhurNeural", "gender": "Male", "region": "India", "description": "Deep Hindi male narrator"},
            {"id": "hi-IN-SwaraNeural", "gender": "Female", "region": "India", "description": "Smooth Hindi female"},
        ]
    },
    "kn": {
        "name": "Kannada (ಕನ್ನಡ)",
        "voices": [
            {"id": "kn-IN-GaganNeural", "gender": "Male", "region": "India", "description": "Kannada male narrator"},
            {"id": "kn-IN-SapnaNeural", "gender": "Female", "region": "India", "description": "Clear Kannada female storyteller"}
        ]
    },
    "ml": {
        "name": "Malayalam (മലയാളം)",
        "voices": [
            {"id": "ml-IN-MidhunNeural", "gender": "Male", "region": "India", "description": "Malayalam male narrator"},
            {"id": "ml-IN-SobhanaNeural", "gender": "Female", "region": "India", "description": "Smooth Malayalam female narrator"}
        ]
    },
    "mr": {
        "name": "Marathi (मराठी)",
        "voices": [
            {"id": "mr-IN-ManoharNeural", "gender": "Male", "region": "India", "description": "Marathi male narrator"},
            {"id": "mr-IN-AarohiNeural", "gender": "Female", "region": "India", "description": "Expressive Marathi female voice"}
        ]
    },
    "id": {
        "name": "Indonesian (Bahasa Indonesia)",
        "voices": [
            {"id": "id-ID-ArdiNeural", "gender": "Male", "region": "Indonesia", "description": "Alur Cerita Manhwa narrator"},
            {"id": "id-ID-GadisNeural", "gender": "Female", "region": "Indonesia", "description": "Smooth narrative voice"}
        ]
    },
    "pt": {
        "name": "Portuguese (Brasil)",
        "voices": [
            {"id": "pt-BR-AntonioNeural", "gender": "Male", "region": "Brazil", "description": "Resumo de Manhwa narrator"},
            {"id": "pt-BR-FranciscaNeural", "gender": "Female", "region": "Brazil", "description": "Expressive anime narrator"}
        ]
    },
    "fr": {
        "name": "French (Français)",
        "voices": [
            {"id": "fr-FR-HenriNeural", "gender": "Male", "region": "France", "description": "Cinematic French narrator"},
            {"id": "fr-FR-DeniseNeural", "gender": "Female", "region": "France", "description": "Expressive French voice"}
        ]
    },
    "vi": {
        "name": "Vietnamese (Tiếng Việt)",
        "voices": [
            {"id": "vi-VN-NamMinhNeural", "gender": "Male", "region": "Vietnam", "description": "Review Truyện Tranh narrator"},
            {"id": "vi-VN-HoaiMyNeural", "gender": "Female", "region": "Vietnam", "description": "Clear storytelling voice"}
        ]
    },
    "ar": {
        "name": "Arabic (العربية)",
        "voices": [
            {"id": "ar-SA-HamedNeural", "gender": "Male", "region": "Saudi Arabia", "description": "Dramatic Arabic narrator"},
            {"id": "ar-EG-SalmaNeural", "gender": "Female", "region": "Egypt", "description": "Expressive storytelling voice"}
        ]
    },
    "de": {
        "name": "German (Deutsch)",
        "voices": [
            {"id": "de-DE-ConradNeural", "gender": "Male", "region": "Germany", "description": "Deep German narrator"},
            {"id": "de-DE-KatjaNeural", "gender": "Female", "region": "Germany", "description": "Clear narration"}
        ]
    },
    "ru": {
        "name": "Russian (Русский)",
        "voices": [
            {"id": "ru-RU-DmitryNeural", "gender": "Male", "region": "Russia", "description": "Manhwa recap narrator"},
            {"id": "ru-RU-SvetlanaNeural", "gender": "Female", "region": "Russia", "description": "Dramatic female voice"}
        ]
    },
    "ja": {
        "name": "Japanese (日本語)",
        "voices": [
            {"id": "ja-JP-KeitaNeural", "gender": "Male", "region": "Japan", "description": "Anime narrator male"},
            {"id": "ja-JP-NanamiNeural", "gender": "Female", "region": "Japan", "description": "Expressive anime voice"}
        ]
    }
}

# Initialize FastAPI App
app = FastAPI(
    title="DubFlow Studio API",
    description="High-performance Local AI Video Dubbing REST API for Apple Silicon (M1 Pro/Max)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for external frontends / web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Schemas
# ============================================================================

class HealthResponse(BaseModel):
    status: str
    hardware_device: str
    engine_label: str
    os_name: str
    cpu_cores: int
    ffmpeg_available: bool
    python_version: str
    active_jobs: int


class DubbingJobResponse(BaseModel):
    job_id: str
    status: str
    message: str
    target_lang: str
    voice: str
    created_at: float
    target_langs: Optional[List[str]] = None
    is_multi_language: Optional[bool] = False


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: float
    current_step: str
    logs: List[str]
    created_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    output_video_url: Optional[str] = None
    duration: Optional[float] = None
    segment_count: Optional[int] = None
    target_langs: Optional[List[str]] = None
    is_multi_language: Optional[bool] = False
    languages: Optional[Dict[str, Any]] = None
    zip_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    thumbnail_url: Optional[str] = None
    metadata_by_lang: Optional[Dict[str, Any]] = None
    thumbnails_by_lang: Optional[Dict[str, Any]] = None
    shorts: Optional[List[Dict[str, Any]]] = None
    is_shorts_mode: Optional[bool] = False


# ============================================================================
# Background Worker Task
# ============================================================================

def notify_ws_clients(job_id: str, data: dict):
    """Sends real-time updates to connected WebSocket clients."""
    if job_id in ws_connections:
        dead_sockets = []
        for ws in ws_connections[job_id]:
            try:
                asyncio.run(ws.send_json(data))
            except Exception:
                dead_sockets.append(ws)
        for dead in dead_sockets:
            ws_connections[job_id].remove(dead)


def run_dubbing_job_sync(
    job_id: str,
    video_path: Optional[Path],
    target_lang: str,
    voice: str,
    whisper_model: str,
    translation_engine: str,
    tts_engine: str,
    voice_clone: bool,
    bg_volume: float,
    vocals_volume: float,
    start_seconds: Optional[float] = None,
    duration_seconds: Optional[float] = None,
    part_name: Optional[str] = None,
    target_langs: Optional[List[str]] = None,
    speed_cap: float = 1.15,
    enable_watermark: bool = False,
    watermark_text: Optional[str] = None,
    watermark_interval: float = 3.0,
    watermark_opacity: float = 0.40,
    gemini_api_key: Optional[str] = None,
    is_shorts_mode: bool = False,
    shorts_count: int = 3,
    short_duration: float = 45.0,
    shorts_aspect_ratio: str = "9:16",
    selected_moment_index: Optional[int] = None,
):
    """Worker function executed inside thread pool."""
    job = jobs_db.get(job_id)
    if not job:
        return

    if job_id in CANCELLED_JOBS or job.get("is_cancelled") or job.get("status") == "cancelled":
        logger.info(f"Job {job_id} was cancelled before starting. Exiting worker.")
        job["status"] = "cancelled"
        job["current_step"] = "Cancelled by user"
        db.update_video_on_job_progress(job_id, "cancelled", 0.0, videos_db, BASE_DIR / "workspace_api", jobs_db)
        return

    job["status"] = "processing"
    job["started_at"] = time.time()
    db.update_video_on_job_progress(job_id, "processing", job.get("progress", 0.01), videos_db, BASE_DIR / "workspace_api", jobs_db)
    notify_ws_clients(job_id, {
        "type": "status",
        "status": "processing",
        "progress": job.get("progress", 0.01),
        "step": "Starting video conversion..."
    })
    job_folder = JOBS_DIR / job_id
    job_folder.mkdir(parents=True, exist_ok=True)

    def progress_callback(progress_float: float, step_msg: str):
        if job_id in CANCELLED_JOBS or job.get("is_cancelled") or job.get("status") == "cancelled":
            raise JobCancelledException(f"Job {job_id} cancelled by user")
        job["progress"] = round(progress_float, 2)
        job["current_step"] = step_msg
        log_entry = f"[{time.strftime('%H:%M:%S')}] {step_msg}"
        job["logs"].append(log_entry)
        notify_ws_clients(job_id, {
            "type": "progress",
            "progress": job["progress"],
            "step": step_msg,
            "log": log_entry
        })

    try:
        # Download from YouTube if URL was provided (cached to avoid duplicate downloads across parts)
        if not video_path and job.get("youtube_url"):
            yt_url = job["youtube_url"].strip()
            yt_id = extract_youtube_id(yt_url)

            # Check if source video is already cached to avoid duplicate downloads across parts
            cached_source = None
            if yt_id:
                candidate = VIDEOS_CACHE_DIR / f"{yt_id}.mp4"
                if candidate.exists() and candidate.stat().st_size > 100000:
                    cached_source = candidate
                else:
                    ytd_candidate = BASE_DIR / "workspace_api" / "ytd_downloads" / f"{yt_id}.mp4"
                    if ytd_candidate.exists() and ytd_candidate.stat().st_size > 100000:
                        cached_source = ytd_candidate

            if cached_source:
                logger.info(f"Reusing cached source video for job {job_id}: {cached_source}")
                progress_callback(0.02, f"Reusing cached source video ({cached_source.name})...")
                target_video = job_folder / cached_source.name
                if not target_video.exists():
                    try:
                        shutil.copy2(cached_source, target_video)
                        video_path = target_video
                    except Exception:
                        video_path = cached_source
                else:
                    video_path = target_video
            else:
                progress_callback(0.02, "Step 0 of 5: Downloading video from YouTube via yt-dlp...")
                download_dest = VIDEOS_CACHE_DIR if yt_id else job_folder
                downloaded_file = YouTubeDownloader.download(
                    yt_url,
                    download_dest,
                    progress_callback=progress_callback
                )
                if yt_id and downloaded_file.exists():
                    target_video = job_folder / downloaded_file.name
                    if not target_video.exists():
                        try:
                            shutil.copy2(downloaded_file, target_video)
                            video_path = target_video
                        except Exception:
                            video_path = downloaded_file
                    else:
                        video_path = target_video
                else:
                    video_path = downloaded_file

            job["input_video"] = str(video_path)

        if not video_path or not video_path.exists():
            raise FileNotFoundError("Video source file could not be resolved.")

        output_video_path = job_folder / f"{video_path.stem}_{target_lang}_dubbed.mp4"

        pipeline = ManhwaDubbingPipeline(
            whisper_model=whisper_model,
            target_lang=target_lang,
            translation_engine=translation_engine,
            tts_engine=tts_engine,
            tts_voice=voice,
            voice_gender=job.get("voice_gender"),
            voice_clone=voice_clone,
            bg_volume=bg_volume,
            vocals_volume=vocals_volume,
            speed_cap=speed_cap,
            work_dir=job_folder,
            enable_watermark=enable_watermark,
            watermark_text=watermark_text,
            watermark_interval=watermark_interval,
            watermark_opacity=watermark_opacity,
            gemini_api_key=gemini_api_key,
        )

        result = pipeline.run(
            video_path=str(video_path),
            output_path=str(output_video_path),
            progress_callback=progress_callback,
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
            part_name=part_name,
            target_langs=target_langs,
            gemini_api_key=gemini_api_key,
            is_shorts_mode=is_shorts_mode,
            generate_shorts=is_shorts_mode,
            shorts_count=shorts_count,
            short_duration=short_duration,
            shorts_aspect_ratio=shorts_aspect_ratio,
            selected_moment_index=selected_moment_index,
        )

        job["status"] = "completed"
        job["progress"] = 1.0
        job["current_step"] = "Dubbing completed successfully."
        job["completed_at"] = time.time()
        job["result"] = result
        job["languages"] = result.get("languages")
        job["is_multi_language"] = result.get("is_multi_language", False)
        job["target_langs"] = result.get("target_langs", [target_lang])
        if result.get("zip_path"):
            job["zip_url"] = f"/api/jobs/{job_id}/download-all"
        job["output_video_path"] = result.get("final_video", str(output_video_path))
        job["duration"] = result.get("total_duration", 0.0)
        job["segment_count"] = len(result.get("segments", []))
        job["metadata"] = result.get("metadata")
        job["thumbnail"] = result.get("thumbnail")
        job["metadata_by_lang"] = result.get("metadata_by_lang", {})
        job["thumbnails_by_lang"] = result.get("thumbnails_by_lang", {})
        if result.get("thumbnail"):
            job["thumbnail_url"] = f"/api/jobs/{job_id}/thumbnail"

        raw_shorts = result.get("shorts", [])
        formatted_shorts = []
        for s in raw_shorts:
            fn = s.get("filename")
            formatted_shorts.append({
                **s,
                "video_url": f"/api/jobs/{job_id}/shorts/{fn}",
                "download_url": f"/api/jobs/{job_id}/shorts/{fn}",
            })
        job["shorts"] = formatted_shorts
        job["is_shorts_mode"] = is_shorts_mode

        notify_ws_clients(job_id, {
            "type": "completed",
            "progress": 1.0,
            "message": "Job finished successfully",
            "output_url": f"/api/jobs/{job_id}/video",
            "is_multi_language": job["is_multi_language"],
            "languages": job.get("languages"),
            "zip_url": job.get("zip_url"),
            "metadata": job.get("metadata"),
            "thumbnail_url": job.get("thumbnail_url"),
            "metadata_by_lang": job.get("metadata_by_lang"),
            "thumbnails_by_lang": job.get("thumbnails_by_lang"),
            "shorts": formatted_shorts,
            "is_shorts_mode": is_shorts_mode,
        })

        db.update_video_on_job_progress(
            job_id,
            "completed",
            1.0,
            videos_db,
            BASE_DIR / "workspace_api",
            jobs_db,
            extra_data={
                "output_video_url": f"/api/jobs/{job_id}/video",
                "thumbnail_url": job.get("thumbnail_url"),
                "zip_url": job.get("zip_url"),
                "duration": job.get("duration"),
                "languages": job.get("target_langs") or [target_lang]
            }
        )

    except JobCancelledException as e:
        logger.info(f"Job {job_id} was successfully cancelled: {e}")
        job["status"] = "cancelled"
        job["is_cancelled"] = True
        job["progress"] = 0.0
        job["current_step"] = "Cancelled by user"
        job["completed_at"] = time.time()
        notify_ws_clients(job_id, {
            "type": "cancelled",
            "message": "Job cancelled by user"
        })
        db.update_video_on_job_progress(
            job_id,
            "cancelled",
            0.0,
            videos_db,
            BASE_DIR / "workspace_api",
            jobs_db
        )

    except Exception as e:
        if job_id in CANCELLED_JOBS or job.get("is_cancelled") or job.get("status") == "cancelled":
            logger.info(f"Job {job_id} was cancelled during error: {e}")
            job["status"] = "cancelled"
            job["is_cancelled"] = True
            job["current_step"] = "Cancelled by user"
            db.update_video_on_job_progress(job_id, "cancelled", 0.0, videos_db, BASE_DIR / "workspace_api", jobs_db)
            return

        logger.exception(f"Job {job_id} encountered an error: {e}")
        job["status"] = "failed"
        job["error"] = str(e)
        job["current_step"] = f"Failed: {str(e)}"
        notify_ws_clients(job_id, {
            "type": "failed",
            "error": str(e)
        })
        db.update_video_on_job_progress(
            job_id,
            "failed",
            job.get("progress", 0.0),
            videos_db,
            BASE_DIR / "workspace_api",
            jobs_db
        )


# ============================================================================
# API Endpoints
# ============================================================================

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", tags=["Frontend"])
def root():
    """Serves the React Frontend app or API meta info."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "service": "DubFlow Studio API",
        "description": "Local AI Video Dubbing Backend for Apple Silicon (M1 Pro/Max)",
        "frontend": "/app",
        "docs": "/docs",
        "health": "/api/health",
        "languages": "/api/languages"
    }


@app.get("/app", tags=["Frontend"])
@app.get("/web", tags=["Frontend"])
def serve_app():
    """Serves the React Web Application."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="React frontend build not found at static/index.html")


@app.get("/api/health", response_model=HealthResponse, tags=["General"])
def health_check():
    """Returns dynamic hardware acceleration status and dependencies across Linux Cloud VMs, macOS, and Windows."""
    hw = HardwareAccelerationManager.get_device_info()
    ffmpeg_ok = HardwareAccelerationManager.verify_ffmpeg()
    return {
        "status": "healthy" if ffmpeg_ok else "degraded",
        "hardware_device": hw["device"],
        "engine_label": hw["engine_label"],
        "os_name": hw["os"],
        "cpu_cores": hw["cpu_cores"],
        "ffmpeg_available": ffmpeg_ok,
        "python_version": sys.version.split()[0],
        "active_jobs": sum(1 for j in jobs_db.values() if j["status"] in ["queued", "processing"])
    }


@app.get("/api/languages", tags=["Languages"])
def list_languages():
    """Lists all supported target languages and their neural voices."""
    return SUPPORTED_VOICES


@app.get("/api/auth/config", tags=["Auth"])
def get_auth_config():
    """Returns frontend authentication configuration from .env."""
    return {
        "admin_email": os.environ.get("VITE_ADMIN_EMAIL", "admin@admin.com"),
        "authenticated": True
    }


@app.get("/api/system/stats", tags=["System"])
def get_system_stats_endpoint():
    """Returns real-time Apple Silicon RAM usage and dubbing job metrics."""
    return db.get_system_stats(jobs_db, videos_db)


class CreateVideoRequest(BaseModel):
    title: Optional[str] = None
    youtube_url: Optional[str] = ""
    description: Optional[str] = None
    duration_seconds: Optional[float] = None
    source_type: Optional[str] = "youtube"


class UpdateVideoRequest(BaseModel):
    title: Optional[str] = None
    youtube_url: Optional[str] = None


@app.get("/api/videos", tags=["Videos"])
def list_videos():
    """Returns all video projects with aggregated languages and conversion parts."""
    vids = list(videos_db.values())
    vids.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return vids


@app.post("/api/videos", status_code=status.HTTP_201_CREATED, tags=["Videos"])
def create_video(req: CreateVideoRequest):
    """Creates a new video project entry. Always starts fresh with 0 conversions."""
    clean_url = req.youtube_url.strip() if req.youtube_url else ""
    yt_id = extract_youtube_id(clean_url)
    unique_suffix = uuid.uuid4().hex[:6]
    vid_id = f"vid_{yt_id}_{unique_suffix}" if yt_id else f"vid_{unique_suffix}"

    title = req.title.strip() if req.title else ""
    duration_sec = req.duration_seconds
    thumb_url = None

    if clean_url:
        try:
            info = YouTubeDownloader.get_video_info(clean_url)
            if not title and info.get("title"):
                title = info.get("title")
            if not duration_sec and info.get("duration_seconds"):
                duration_sec = float(info.get("duration_seconds"))
            thumb_url = info.get("thumbnail")
        except Exception:
            pass

    if not title:
        title = f"YouTube Video: {yt_id}" if yt_id else f"Video Project {unique_suffix}"
    if not thumb_url and yt_id:
        thumb_url = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"

    video_entry = {
        "id": vid_id,
        "title": title,
        "youtube_url": clean_url,
        "description": req.description.strip() if req.description else "",
        "thumbnail_url": thumb_url,
        "duration_seconds": duration_sec,
        "source_type": req.source_type or ("youtube" if clean_url else "upload"),
        "source_file": None,
        "source_file_name": None,
        "source_file_size": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "draft",
        "conversions": [],
        "languages": []
    }
    videos_db[vid_id] = video_entry
    db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    return video_entry


@app.post("/api/videos/upload", status_code=status.HTTP_201_CREATED, tags=["Videos"])
async def create_video_from_upload(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None)
):
    """Creates a new video project directly by uploading a local video file (skips YouTube)."""
    unique_suffix = uuid.uuid4().hex[:8]
    vid_id = f"vid_upload_{unique_suffix}"

    saved_path = UPLOAD_DIR / f"{vid_id}_{file.filename}"
    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    duration_sec = None
    try:
        from pipeline import VideoSegmenter
        duration_sec = VideoSegmenter.get_duration(saved_path)
    except Exception as e:
        logger.warning(f"Could not extract duration for {saved_path}: {e}")

    thumb_path = UPLOAD_DIR / f"{vid_id}_thumb.jpg"
    thumb_url = None
    try:
        cmd = ["ffmpeg", "-y", "-ss", "00:00:01", "-i", str(saved_path), "-vframes", "1", "-q:v", "2", str(thumb_path)]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if thumb_path.exists() and thumb_path.stat().st_size > 500:
            thumb_url = f"/api/videos/{vid_id}/thumbnail"
    except Exception as e:
        logger.warning(f"Could not generate thumbnail for {saved_path}: {e}")

    clean_title = title.strip() if title and title.strip() else Path(file.filename).stem
    video_entry = {
        "id": vid_id,
        "title": clean_title,
        "youtube_url": "",
        "description": description.strip() if description else "",
        "thumbnail_url": thumb_url,
        "duration_seconds": duration_sec,
        "source_file": str(saved_path),
        "source_file_name": file.filename,
        "source_file_size": saved_path.stat().st_size if saved_path.exists() else 0,
        "source_type": "upload",
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "draft",
        "conversions": [],
        "languages": []
    }
    videos_db[vid_id] = video_entry
    db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    return video_entry


@app.post("/api/videos/{video_id}/upload-source", tags=["Videos"])
async def upload_video_source(
    video_id: str,
    file: UploadFile = File(...)
):
    """Uploads or replaces the main source video file for a video project (skips YouTube)."""
    vid = videos_db.get(video_id)
    if not vid:
        raise HTTPException(status_code=404, detail="Video project not found")

    # Remove previous source file if it existed in uploads
    old_source = vid.get("source_file")
    if old_source:
        old_p = Path(old_source)
        if old_p.exists() and old_p.is_file() and UPLOAD_DIR in old_p.parents:
            try:
                old_p.unlink(missing_ok=True)
            except Exception:
                pass

    saved_path = UPLOAD_DIR / f"{video_id}_{file.filename}"
    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    duration_sec = None
    try:
        from pipeline import VideoSegmenter
        duration_sec = VideoSegmenter.get_duration(saved_path)
    except Exception as e:
        logger.warning(f"Could not extract duration for {saved_path}: {e}")

    thumb_path = UPLOAD_DIR / f"{video_id}_thumb.jpg"
    try:
        cmd = ["ffmpeg", "-y", "-ss", "00:00:01", "-i", str(saved_path), "-vframes", "1", "-q:v", "2", str(thumb_path)]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if thumb_path.exists() and thumb_path.stat().st_size > 500:
            vid["thumbnail_url"] = f"/api/videos/{video_id}/thumbnail"
    except Exception as e:
        logger.warning(f"Could not generate thumbnail for {saved_path}: {e}")

    vid["source_file"] = str(saved_path)
    vid["source_file_name"] = file.filename
    vid["source_file_size"] = saved_path.stat().st_size if saved_path.exists() else 0
    vid["source_type"] = "upload"
    if duration_sec and duration_sec > 0:
        vid["duration_seconds"] = duration_sec
    if not vid.get("title") or vid["title"].startswith("YouTube Video:") or vid["title"].startswith("Video Project"):
        vid["title"] = Path(file.filename).stem
    vid["updated_at"] = time.time()

    db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    return vid


@app.get("/api/videos/{video_id}/thumbnail", tags=["Videos"])
def get_video_thumbnail(video_id: str):
    """Returns thumbnail image for an uploaded video project."""
    thumb_path = UPLOAD_DIR / f"{video_id}_thumb.jpg"
    if thumb_path.exists():
        return FileResponse(path=thumb_path, media_type="image/jpeg", filename=f"{video_id}_thumb.jpg")
    raise HTTPException(status_code=404, detail="Thumbnail not found")


@app.get("/api/videos/{video_id}", tags=["Videos"])
def get_video(video_id: str):
    """Returns details and all conversions for a specific video project."""
    vid = videos_db.get(video_id)
    if not vid:
        raise HTTPException(status_code=404, detail="Video project not found")
    return vid


@app.put("/api/videos/{video_id}", tags=["Videos"])
def update_video(video_id: str, req: UpdateVideoRequest):
    """Updates video title or YouTube URL."""
    vid = videos_db.get(video_id)
    if not vid:
        raise HTTPException(status_code=404, detail="Video project not found")

    if req.title is not None and req.title.strip():
        vid["title"] = req.title.strip()
    if req.youtube_url is not None and req.youtube_url.strip():
        vid["youtube_url"] = req.youtube_url.strip()
    vid["updated_at"] = time.time()

    db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    return vid


@app.delete("/api/videos/{video_id}", tags=["Videos"])
def delete_video(video_id: str):
    """Deletes a video project along with its main video file, converted parts, and all media files from disk."""
    vid = videos_db.pop(video_id, None)
    if not vid:
        raise HTTPException(status_code=404, detail="Video project not found")

    deleted_count = 0

    # 1. Purge explicitly registered source video file
    source_file = vid.get("source_file")
    if source_file:
        p = Path(source_file)
        if p.exists() and p.is_file():
            try:
                p.unlink(missing_ok=True)
                deleted_count += 1
                logger.info(f"Deleted source video file: {p}")
            except Exception as e:
                logger.warning(f"Could not delete source file {p}: {e}")

    # 2. Purge local thumbnail file if present
    thumb_file = UPLOAD_DIR / f"{video_id}_thumb.jpg"
    if thumb_file.exists():
        try:
            thumb_file.unlink(missing_ok=True)
            deleted_count += 1
        except Exception:
            pass

    # 3. Collect associated jobs
    job_ids_to_remove = set()
    for conv in vid.get("conversions", []):
        j_id = conv.get("job_id")
        if j_id:
            job_ids_to_remove.add(j_id)

    vid_base = video_id.replace("vid_", "")
    for j_id, j_data in list(jobs_db.items()):
        if j_data.get("video_base_id") == vid_base or j_data.get("video_id") == video_id:
            job_ids_to_remove.add(j_id)

    # 4. Clean up input videos recorded in the jobs and job directories
    for j_id in job_ids_to_remove:
        j_data = jobs_db.get(j_id)
        if j_data:
            inp = j_data.get("input_video")
            if inp:
                inp_p = Path(inp)
                if inp_p.exists() and inp_p.is_file():
                    try:
                        inp_p.unlink(missing_ok=True)
                        deleted_count += 1
                    except Exception:
                        pass
        CANCELLED_JOBS.add(j_id)
        jobs_db.pop(j_id, None)
        job_dir = JOBS_DIR / j_id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
            deleted_count += 1

    # 5. Clean up any uploaded files matching video_id, vid_base, or j_id in UPLOAD_DIR
    for pattern in [f"{video_id}*", f"{vid_base}*"]:
        for f in UPLOAD_DIR.glob(pattern):
            if f.is_file():
                try:
                    f.unlink(missing_ok=True)
                    deleted_count += 1
                except Exception:
                    pass
    for j_id in job_ids_to_remove:
        for f in UPLOAD_DIR.glob(f"{j_id}*"):
            if f.is_file():
                try:
                    f.unlink(missing_ok=True)
                    deleted_count += 1
                except Exception:
                    pass

    # 6. Clean up any cached video files in VIDEOS_CACHE_DIR and ytd_downloads
    clean_yt = vid.get("youtube_url")
    yt_id = extract_youtube_id(clean_yt) if clean_yt else None
    for target_id in [yt_id, vid_base, video_id]:
        if target_id:
            for f in VIDEOS_CACHE_DIR.glob(f"{target_id}*"):
                if f.is_file():
                    try:
                        f.unlink(missing_ok=True)
                        deleted_count += 1
                    except Exception:
                        pass
            ytd_dir = BASE_DIR / "workspace_api" / "ytd_downloads"
            if ytd_dir.exists():
                for f in ytd_dir.glob(f"{target_id}*"):
                    if f.is_file():
                        try:
                            f.unlink(missing_ok=True)
                            deleted_count += 1
                        except Exception:
                            pass

    db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    return {"status": "deleted", "video_id": video_id, "deleted_items": deleted_count}


class VideoInfoRequest(BaseModel):
    url: str


@app.post("/api/video-info", tags=["Video Info"])
def get_video_info_post(req: VideoInfoRequest):
    """Fetches YouTube video metadata (title, duration, thumbnail) without downloading."""
    try:
        return YouTubeDownloader.get_video_info(req.url.strip())
    except Exception as e:
        logger.error(f"Failed to fetch video info: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/video-info", tags=["Video Info"])
def get_video_info_get(url: str):
    """Fetches YouTube video metadata via GET parameter."""
    try:
        return YouTubeDownloader.get_video_info(url.strip())
    except Exception as e:
        logger.error(f"Failed to fetch video info: {e}")
        raise HTTPException(status_code=400, detail=str(e))


class YouTubeCredentialsRequest(BaseModel):
    email: str
    password: str


class YouTubeSyncRequest(BaseModel):
    browser: Optional[str] = "chrome"


class YouTubePasteCookiesRequest(BaseModel):
    cookies_text: str


def _sync_cookies_to_env(cookies_text: str):
    """Saves base64-encoded cookies to .env so VM / Docker deployments retain authenticated sessions."""
    import base64
    try:
        b64 = base64.b64encode(cookies_text.encode("utf-8")).decode("utf-8")
        env_path = BASE_DIR / ".env"
        content = env_path.read_text() if env_path.exists() else ""
        lines = content.splitlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("YOUTUBE_COOKIES_B64="):
                new_lines.append(f"YOUTUBE_COOKIES_B64={b64}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"YOUTUBE_COOKIES_B64={b64}")
        env_path.write_text("\n".join(new_lines) + "\n")
        os.environ["YOUTUBE_COOKIES_B64"] = b64
    except Exception as e:
        logger.warning(f"Could not persist cookies to .env: {e}")


@app.get("/api/youtube/auth-status", tags=["YouTube Auth"])
def get_youtube_auth_status():
    """Returns current YouTube authentication, account credentials, and cookies status."""
    import platform
    email = os.getenv("YOUTUBE_EMAIL", "manhwadesistyle@gmail.com")
    cookie_file = find_cookies_file()
    has_cookies = cookie_file is not None and cookie_file.exists() and cookie_file.stat().st_size > 100
    cookie_count = 0
    if has_cookies and cookie_file:
        try:
            with open(cookie_file, "r") as f:
                cookie_count = sum(1 for line in f if not line.startswith("#") and line.strip())
        except Exception:
            pass

    system_name = platform.system()
    return {
        "email": email,
        "has_password": bool(os.getenv("YOUTUBE_PASSWORD", "G00gle@123")),
        "has_cookies": has_cookies,
        "cookie_count": cookie_count,
        "cookie_file": str(cookie_file) if cookie_file else None,
        "status": "ready" if has_cookies else "unauthenticated",
        "is_vm": system_name != "Darwin",
        "os_name": system_name,
        "has_env_backup": bool(os.getenv("YOUTUBE_COOKIES_B64")),
    }


@app.post("/api/youtube/sync-cookies", tags=["YouTube Auth"])
def post_sync_youtube_cookies(req: Optional[YouTubeSyncRequest] = None):
    """Syncs YouTube/Google cookies from local browser into cookies.txt and .env."""
    browser = req.browser if req and req.browser else "chrome"
    success, message = sync_browser_cookies(browser=browser)
    if success:
        cookie_file = find_cookies_file()
        if cookie_file and cookie_file.exists():
            _sync_cookies_to_env(cookie_file.read_text())
    return {
        "success": success,
        "message": message,
        "auth_status": get_youtube_auth_status()
    }


@app.post("/api/youtube/update-credentials", tags=["YouTube Auth"])
def post_update_youtube_credentials(req: YouTubeCredentialsRequest):
    """Updates YouTube login email and password in environment and .env file."""
    os.environ["YOUTUBE_EMAIL"] = req.email.strip()
    os.environ["YOUTUBE_PASSWORD"] = req.password.strip()

    env_path = BASE_DIR / ".env"
    try:
        content = env_path.read_text() if env_path.exists() else ""
        lines = content.splitlines()
        new_lines = []
        found_email = False
        found_pwd = False
        for line in lines:
            if line.startswith("YOUTUBE_EMAIL="):
                new_lines.append(f"YOUTUBE_EMAIL={req.email.strip()}")
                found_email = True
            elif line.startswith("YOUTUBE_PASSWORD="):
                new_lines.append(f"YOUTUBE_PASSWORD={req.password.strip()}")
                found_pwd = True
            else:
                new_lines.append(line)
        if not found_email:
            new_lines.append(f"YOUTUBE_EMAIL={req.email.strip()}")
        if not found_pwd:
            new_lines.append(f"YOUTUBE_PASSWORD={req.password.strip()}")
        env_path.write_text("\n".join(new_lines) + "\n")
    except Exception as e:
        logger.warning(f"Could not persist credentials to .env: {e}")

    return {
        "success": True,
        "message": f"Updated YouTube credentials for {req.email.strip()}",
        "auth_status": get_youtube_auth_status()
    }


@app.post("/api/youtube/paste-cookies", tags=["YouTube Auth"])
def post_paste_youtube_cookies(req: YouTubePasteCookiesRequest):
    """Saves pasted Netscape cookies.txt directly to project root, workspace, and .env."""
    raw = req.cookies_text.strip()
    if len(raw) < 50:
        raise HTTPException(status_code=400, detail="Cookies content is too short or invalid.")

    target_path = BASE_DIR / "cookies.txt"
    try:
        target_path.write_text(raw + "\n")
        # Mirror to workspace
        try:
            mirror = BASE_DIR / "workspace_api" / "cookies.txt"
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mirror.write_text(raw + "\n")
        except Exception:
            pass

        # Also persist to .env
        _sync_cookies_to_env(raw)

        return {
            "success": True,
            "message": f"Successfully installed cookies ({len(raw)} characters). Ready for VM downloads.",
            "auth_status": get_youtube_auth_status()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write cookies: {e}")


@app.post("/api/youtube/upload-cookies", tags=["YouTube Auth"])
async def post_upload_youtube_cookies(file: UploadFile = File(...)):
    """Uploads a cookies.txt file to authenticate YouTube downloads on this server/VM."""
    content = await file.read()
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        text_content = content.decode("latin-1", errors="ignore")

    raw = text_content.strip()
    if len(raw) < 50:
        raise HTTPException(status_code=400, detail="Uploaded cookie file is empty or invalid.")

    target_path = BASE_DIR / "cookies.txt"
    try:
        target_path.write_text(raw + "\n")
        # Mirror to workspace
        try:
            mirror = BASE_DIR / "workspace_api" / "cookies.txt"
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mirror.write_text(raw + "\n")
        except Exception:
            pass

        # Also persist to .env
        _sync_cookies_to_env(raw)

        return {
            "success": True,
            "message": f"Successfully uploaded cookies.txt ({len(content)} bytes). Active on this VM.",
            "auth_status": get_youtube_auth_status()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save cookies: {e}")


@app.get("/api/youtube/export-cookies", tags=["YouTube Auth"])
def get_export_youtube_cookies():
    """Downloads the active cookies.txt file as an attachment to easily transfer to a remote VM."""
    cookie_file = find_cookies_file()
    if not cookie_file or not cookie_file.exists():
        raise HTTPException(status_code=404, detail="No active cookies.txt file found to export.")
    return FileResponse(
        path=str(cookie_file),
        filename="cookies.txt",
        media_type="text/plain"
    )




@app.post("/api/dub", response_model=DubbingJobResponse, status_code=status.HTTP_202_ACCEPTED, tags=["Dubbing"])
async def create_dubbing_job(
    background_tasks: BackgroundTasks,
    youtube_url: Optional[str] = Form(None, description="YouTube video URL to download and dub"),
    video_file: Optional[UploadFile] = File(None),
    video_path: Optional[str] = Form(None),
    target_lang: str = Form("es", description="Language code: de, fr, id, es, ta, te, bn, hi, kn, ml, mr, pt, vi, ar, ru, ja"),
    target_langs: Optional[str] = Form(None, description="Comma-separated language codes for multi-dubbing: 'de,fr,id'"),
    voice: Optional[str] = Form(None, description="Neural voice ID (e.g. de-DE-ConradNeural, fr-FR-HenriNeural, id-ID-ArdiNeural)"),
    voice_gender: Optional[str] = Form(None, description="Voice gender preference: 'male' or 'female'"),
    whisper_model: str = Form("base", description="Whisper model size: tiny, base, small, medium"),
    translation_engine: str = Form("deep-translator", description="Translation engine: deep-translator or helsinki-nlp"),
    voice_clone: bool = Form(False, description="Enable Coqui XTTS-v2 voice cloning"),
    bg_volume: float = Form(0.80, description="Background music volume factor (0.0 to 1.5)"),
    vocals_volume: float = Form(1.00, description="Voiceover volume factor (0.0 to 1.5)"),
    speed_cap: float = Form(1.15, description="Maximum voiceover speed multiplier cap (1.0 to 1.4, default 1.15)"),
    start_seconds: Optional[float] = Form(None, description="Start timestamp in seconds to trim part"),
    duration_seconds: Optional[float] = Form(None, description="Duration in seconds of the part (e.g. 600 for 10 mins)"),
    part_name: Optional[str] = Form(None, description="Label for the part (e.g. Part 1)"),
    enable_watermark: bool = Form(False, description="Enable floating light white text watermark"),
    watermark_text: Optional[str] = Form(None, description="Watermark text (light white)"),
    watermark_interval: float = Form(3.0, description="Interval in seconds for watermark to jump (2-4 seconds)"),
    watermark_opacity: float = Form(0.40, description="Watermark opacity (0.1 to 1.0)"),
    gemini_api_key: Optional[str] = Form(None, description="Optional Google Gemini API key for German SEO Title/Description/Tags"),
    is_shorts_mode: bool = Form(False, description="Enable Instagram / YouTube Shorts mode"),
    shorts_count: int = Form(3, description="Number of top moments shorts to make (1-10)"),
    short_duration: float = Form(45.0, description="Duration in seconds per short (e.g. 30, 45, 60)"),
    shorts_aspect_ratio: str = Form("9:16", description="Aspect ratio: '9:16' (vertical) or '16:9'"),
    selected_moment_index: Optional[int] = Form(None, description="Index of specific top moment, or None for all"),
    video_id: Optional[str] = Form(None, description="Optional video project ID to link this conversion to")
):
    """
    Submits a video dubbing job to the asynchronous background queue.
    Supports single or multiple target languages, with each language exported to its own dedicated folder.
    Supports full video or splitting into timed parts (e.g. 10 mins each).
    """
    job_id = uuid.uuid4().hex[:12]

    # Resolve input video
    final_input_path = None
    clean_yt_url = youtube_url.strip() if youtube_url and youtube_url.strip() else None

    # Resolve video_id if not provided
    resolved_video_id = video_id
    if not resolved_video_id:
        if clean_yt_url:
            yt_id = clean_yt_url.split("v=")[-1].split("&")[0].split("youtu.be/")[-1]
            resolved_video_id = f"vid_{yt_id}"
        elif video_file and video_file.filename:
            resolved_video_id = f"vid_{Path(video_file.filename).stem}"
        else:
            resolved_video_id = f"vid_{job_id}"

    if clean_yt_url:
        pass
    elif video_file and video_file.filename:
        saved_video_path = UPLOAD_DIR / f"{resolved_video_id}_{video_file.filename}"
        with open(saved_video_path, "wb") as buffer:
            shutil.copyfileobj(video_file.file, buffer)
        final_input_path = saved_video_path
        if resolved_video_id and resolved_video_id in videos_db:
            videos_db[resolved_video_id]["source_file"] = str(saved_video_path)
            videos_db[resolved_video_id]["source_file_name"] = video_file.filename
            videos_db[resolved_video_id]["source_file_size"] = saved_video_path.stat().st_size
            videos_db[resolved_video_id]["source_type"] = "upload"
            try:
                from pipeline import VideoSegmenter
                d = VideoSegmenter.get_duration(saved_video_path)
                if d > 0:
                    videos_db[resolved_video_id]["duration_seconds"] = d
                    if not duration_seconds:
                        duration_seconds = d
            except Exception:
                pass
            db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    elif video_path:
        local_p = Path(video_path).resolve()
        if not local_p.exists():
            raise HTTPException(status_code=400, detail=f"Local video path does not exist: {video_path}")
        final_input_path = local_p
    elif resolved_video_id and resolved_video_id in videos_db and videos_db[resolved_video_id].get("source_file"):
        local_p = Path(videos_db[resolved_video_id]["source_file"]).resolve()
        if not local_p.exists():
            raise HTTPException(status_code=400, detail=f"Attached source video not found on disk: {local_p}")
        final_input_path = local_p
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either 'youtube_url', upload a 'video_file', or have an uploaded video attached to this project."
        )

    # Parse and validate target languages
    if target_langs and target_langs.strip():
        parsed_langs = [l.strip().lower() for l in target_langs.split(",") if l.strip()]
    else:
        parsed_langs = [target_lang.strip().lower()]
    if not parsed_langs:
        parsed_langs = [target_lang.strip().lower()]
    parsed_langs = list(dict.fromkeys(parsed_langs))
    primary_lang = parsed_langs[0]

    # Select default voice for primary target language and gender if not specified
    if not voice:
        lang_data = SUPPORTED_VOICES.get(primary_lang, SUPPORTED_VOICES.get("es", {}))
        voices_list = lang_data.get("voices", [])
        if voice_gender and voices_list:
            matched = [v["id"] for v in voices_list if v.get("gender", "").lower() == voice_gender.lower()]
            voice = matched[0] if matched else voices_list[0]["id"]
        elif voices_list:
            voice = voices_list[0]["id"]
        else:
            voice = "es-ES-AlvaroNeural"

    tts_engine = "xtts" if voice_clone else "edge-tts"

    clean_wm_text = watermark_text.strip() if watermark_text and watermark_text.strip() else None
    has_watermark = bool(enable_watermark and clean_wm_text)
    clean_gemini_key = gemini_api_key.strip() if gemini_api_key and gemini_api_key.strip() else None

    # Register Job
    jobs_db[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0.0,
        "current_step": "Queued for processing",
        "logs": [f"[{time.strftime('%H:%M:%S')}] Job created and queued" + (f" ({part_name})" if part_name else "")],
        "target_lang": primary_lang,
        "target_langs": parsed_langs,
        "is_multi_language": len(parsed_langs) > 1,
        "voice": voice,
        "created_at": time.time(),
        "completed_at": None,
        "error": None,
        "youtube_url": clean_yt_url,
        "input_video": str(final_input_path) if final_input_path else None,
        "output_video_path": None,
        "result": None,
        "languages": None,
        "zip_url": None,
        "duration": None,
        "segment_count": None,
        "part_name": part_name,
        "voice_gender": voice_gender,
        "speed_cap": float(speed_cap),
        "start_seconds": start_seconds,
        "duration_seconds": duration_seconds,
        "enable_watermark": has_watermark,
        "watermark_text": clean_wm_text,
        "watermark_interval": float(watermark_interval),
        "watermark_opacity": float(watermark_opacity),
        "gemini_api_key": clean_gemini_key,
        "is_shorts_mode": bool(is_shorts_mode),
        "shorts_count": int(shorts_count),
        "short_duration": float(short_duration),
        "shorts_aspect_ratio": str(shorts_aspect_ratio),
        "selected_moment_index": selected_moment_index,
        "shorts": None,
        "metadata": None,
        "thumbnail": None,
        "thumbnail_url": None,
        "video_id": resolved_video_id,
    }

    # Link job to video project
    db.link_job_to_video(
        resolved_video_id,
        job_id,
        jobs_db[job_id],
        videos_db,
        BASE_DIR / "workspace_api",
        jobs_db
    )

    # Dispatch to thread pool executor asynchronously
    executor.submit(
        run_dubbing_job_sync,
        job_id,
        final_input_path,
        primary_lang,
        voice,
        whisper_model,
        translation_engine,
        tts_engine,
        voice_clone,
        bg_volume,
        vocals_volume,
        start_seconds,
        duration_seconds,
        part_name,
        parsed_langs,
        float(speed_cap),
        has_watermark,
        clean_wm_text,
        float(watermark_interval),
        float(watermark_opacity),
        clean_gemini_key,
        bool(is_shorts_mode),
        int(shorts_count),
        float(short_duration),
        str(shorts_aspect_ratio),
        selected_moment_index,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "message": f"Job queued successfully. Poll status at /api/jobs/{job_id}",
        "target_lang": primary_lang,
        "target_langs": parsed_langs,
        "is_multi_language": len(parsed_langs) > 1,
        "voice": voice,
        "created_at": jobs_db[job_id]["created_at"]
    }


class BatchDubbingPart(BaseModel):
    part_name: str
    start_seconds: float
    duration_seconds: float
    time_range: Optional[str] = None


class BatchDubbingRequest(BaseModel):
    video_id: str
    youtube_url: Optional[str] = None
    video_path: Optional[str] = None
    target_lang: str = "es"
    target_langs: Optional[str] = None
    voice: Optional[str] = None
    voice_gender: Optional[str] = None
    whisper_model: str = "base"
    translation_engine: str = "deep-translator"
    voice_clone: bool = False
    bg_volume: float = 0.80
    vocals_volume: float = 1.00
    speed_cap: float = 1.15
    enable_watermark: bool = False
    watermark_text: Optional[str] = None
    watermark_interval: float = 3.0
    watermark_opacity: float = 0.40
    gemini_api_key: Optional[str] = None
    parts: List[BatchDubbingPart]


@app.post("/api/dub/batch", status_code=status.HTTP_202_ACCEPTED, tags=["Dubbing"])
async def create_batch_dubbing_jobs(req: BatchDubbingRequest):
    """
    Submits multiple split parts to the background queue at once for a video project.
    Allows dubbing all parts sequentially in queue without manual step-by-step submission.
    """
    if not req.parts:
        raise HTTPException(status_code=400, detail="No parts provided to queue.")

    resolved_video_id = req.video_id
    clean_yt_url = req.youtube_url.strip() if req.youtube_url and req.youtube_url.strip() else None

    # Resolve video source path
    resolved_video_path = None
    if req.video_path:
        local_p = Path(req.video_path).resolve()
        if local_p.exists():
            resolved_video_path = local_p
    elif resolved_video_id and resolved_video_id in videos_db and videos_db[resolved_video_id].get("source_file"):
        src_p = Path(videos_db[resolved_video_id]["source_file"]).resolve()
        if src_p.exists():
            resolved_video_path = src_p

    if not clean_yt_url and not resolved_video_path:
        raise HTTPException(
            status_code=400,
            detail="Must provide either YouTube URL or an uploaded video file to split into parts."
        )

    # Parse and validate target languages
    if req.target_langs and req.target_langs.strip():
        parsed_langs = [l.strip().lower() for l in req.target_langs.split(",") if l.strip()]
    else:
        parsed_langs = [req.target_lang.strip().lower()]
    if not parsed_langs:
        parsed_langs = [req.target_lang.strip().lower()]
    parsed_langs = list(dict.fromkeys(parsed_langs))
    primary_lang = parsed_langs[0]

    voice = req.voice
    if not voice:
        lang_data = SUPPORTED_VOICES.get(primary_lang, SUPPORTED_VOICES.get("es", {}))
        voices_list = lang_data.get("voices", [])
        if req.voice_gender and voices_list:
            matched = [v["id"] for v in voices_list if v.get("gender", "").lower() == req.voice_gender.lower()]
            voice = matched[0] if matched else voices_list[0]["id"]
        elif voices_list:
            voice = voices_list[0]["id"]
        else:
            voice = "es-ES-AlvaroNeural"

    tts_engine = "xtts" if req.voice_clone else "edge-tts"
    clean_wm_text = req.watermark_text.strip() if req.watermark_text and req.watermark_text.strip() else None
    has_watermark = bool(req.enable_watermark and clean_wm_text)
    clean_gemini_key = req.gemini_api_key.strip() if req.gemini_api_key and req.gemini_api_key.strip() else None

    def fmt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    queued_jobs = []

    for part in req.parts:
        job_id = uuid.uuid4().hex[:12]
        time_range = part.time_range or f"{fmt_time(part.start_seconds)} - {fmt_time(part.start_seconds + part.duration_seconds)}"

        jobs_db[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0.0,
            "current_step": f"Queued in batch pipeline for {part.part_name}",
            "logs": [f"[{time.strftime('%H:%M:%S')}] Job queued in batch: {part.part_name} ({time_range})"],
            "target_lang": primary_lang,
            "target_langs": parsed_langs,
            "is_multi_language": len(parsed_langs) > 1,
            "voice": voice,
            "created_at": time.time(),
            "completed_at": None,
            "error": None,
            "youtube_url": clean_yt_url,
            "input_video": str(resolved_video_path) if resolved_video_path else None,
            "output_video_path": None,
            "result": None,
            "languages": None,
            "zip_url": None,
            "duration": part.duration_seconds,
            "segment_count": None,
            "part_name": part.part_name,
            "voice_gender": req.voice_gender,
            "speed_cap": float(req.speed_cap),
            "start_seconds": part.start_seconds,
            "duration_seconds": part.duration_seconds,
            "enable_watermark": has_watermark,
            "watermark_text": clean_wm_text,
            "watermark_interval": float(req.watermark_interval),
            "watermark_opacity": float(req.watermark_opacity),
            "gemini_api_key": clean_gemini_key,
            "is_shorts_mode": False,
            "shorts_count": 3,
            "short_duration": 45.0,
            "shorts_aspect_ratio": "9:16",
            "selected_moment_index": None,
            "shorts": None,
            "metadata": None,
            "thumbnail": None,
            "thumbnail_url": None,
            "video_id": resolved_video_id,
        }

        # Link job to video project
        db.link_job_to_video(
            resolved_video_id,
            job_id,
            jobs_db[job_id],
            videos_db,
            BASE_DIR / "workspace_api",
            jobs_db
        )

        # Dispatch to thread pool executor asynchronously
        executor.submit(
            run_dubbing_job_sync,
            job_id,
            resolved_video_path,
            primary_lang,
            voice,
            req.whisper_model,
            req.translation_engine,
            tts_engine,
            req.voice_clone,
            req.bg_volume,
            req.vocals_volume,
            part.start_seconds,
            part.duration_seconds,
            part.part_name,
            parsed_langs,
            float(req.speed_cap),
            has_watermark,
            clean_wm_text,
            float(req.watermark_interval),
            float(req.watermark_opacity),
            clean_gemini_key,
            False,
            3,
            45.0,
            "9:16",
            None
        )

        queued_jobs.append({
            "job_id": job_id,
            "part_name": part.part_name,
            "time_range": time_range,
            "duration_seconds": part.duration_seconds
        })

    return {
        "status": "queued",
        "video_id": resolved_video_id,
        "count": len(queued_jobs),
        "message": f"Successfully queued {len(queued_jobs)} parts for background processing.",
        "jobs": queued_jobs
    }


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse, tags=["Dubbing"])
def get_job_status(job_id: str):
    """Checks progress, logs, and state of a dubbing job."""
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    output_url = f"/api/jobs/{job_id}/video" if job["status"] == "completed" else None

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
        "current_step": job["current_step"],
        "logs": job["logs"],
        "created_at": job["created_at"],
        "completed_at": job["completed_at"],
        "error": job["error"],
        "output_video_url": output_url,
        "duration": job["duration"],
        "segment_count": job["segment_count"],
        "target_langs": job.get("target_langs"),
        "is_multi_language": job.get("is_multi_language", False),
        "languages": job.get("languages"),
        "zip_url": job.get("zip_url"),
        "metadata": job.get("metadata"),
        "thumbnail_url": job.get("thumbnail_url"),
        "metadata_by_lang": job.get("metadata_by_lang"),
        "thumbnails_by_lang": job.get("thumbnails_by_lang"),
    }


class SEOPackRequest(BaseModel):
    lang: Optional[str] = None
    gemini_api_key: Optional[str] = None


class GermanPackRequest(BaseModel):
    gemini_api_key: Optional[str] = None


@app.post("/api/jobs/{job_id}/generate-seo-pack", tags=["Dubbing"])
def generate_seo_pack(job_id: str, request_data: Optional[SEOPackRequest] = None):
    """
    Generates or fetches the YouTube SEO Pack (Title, Description, Tags, Hook)
    and 1280x720 Thumbnail for one or all processed languages in the job.
    Uses Gemini API if key is provided, with fallback to local translation & template engine.
    """
    job = jobs_db.get(job_id)
    job_dir = JOBS_DIR / job_id

    if not job and not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    provided_key = None
    if request_data and request_data.gemini_api_key:
        provided_key = request_data.gemini_api_key.strip()
    elif job and job.get("gemini_api_key"):
        provided_key = job["gemini_api_key"]

    req_lang = request_data.lang.strip().lower() if (request_data and request_data.lang) else None

    # Determine languages to generate for
    if req_lang and req_lang != "all":
        langs_to_process = [req_lang]
    elif job and job.get("target_langs"):
        langs_to_process = list(job["target_langs"])
    elif job and job.get("target_lang"):
        langs_to_process = [job["target_lang"]]
    else:
        subdirs = [d.name for d in job_dir.iterdir() if d.is_dir() and d.name in LANGUAGE_SEO_CONFIG]
        langs_to_process = subdirs if subdirs else ["de"]

    metadata_by_lang = dict(job.get("metadata_by_lang", {})) if job else {}
    thumbnails_by_lang = dict(job.get("thumbnails_by_lang", {})) if job else {}

    # Locate video file for thumbnail generation
    video_candidate = None
    if job and job.get("output_video_path") and Path(job["output_video_path"]).exists():
        video_candidate = Path(job["output_video_path"])
    elif job and job.get("input_video") and Path(job["input_video"]).exists():
        video_candidate = Path(job["input_video"])
    else:
        mp4s = list(job_dir.glob("*.mp4")) or list(job_dir.glob("*/*.mp4"))
        if mp4s:
            video_candidate = mp4s[0]

    title_hint = video_candidate.stem.replace("_", " ") if video_candidate else "Manhwa Video Recap"

    for l_code in langs_to_process:
        l_dir = job_dir / l_code if (job_dir / l_code).is_dir() else job_dir
        l_meta_file = l_dir / f"metadata_{l_code}.json"
        l_thumb_file = l_dir / f"thumbnail_{l_code}.jpg"

        # Check German backward compatibility files
        if l_code == "de":
            if not l_meta_file.exists() and (l_dir / "metadata_german.json").exists():
                l_meta_file = l_dir / "metadata_german.json"
            if not l_thumb_file.exists() and (l_dir / "thumbnail_german.jpg").exists():
                l_thumb_file = l_dir / "thumbnail_german.jpg"

        existing_meta = None
        if l_meta_file.exists():
            try:
                with open(l_meta_file, "r", encoding="utf-8") as f:
                    existing_meta = json.load(f)
            except Exception:
                pass

        # If already exists and no new API key requested, reuse existing
        if existing_meta and l_thumb_file.exists() and not (request_data and request_data.gemini_api_key):
            metadata_by_lang[l_code] = existing_meta
            thumbnails_by_lang[l_code] = f"/api/jobs/{job_id}/languages/{l_code}/thumbnail"
            continue

        if not video_candidate or not video_candidate.exists():
            l_mp4s = list(l_dir.glob("*.mp4"))
            if l_mp4s:
                video_candidate = l_mp4s[0]
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"No video source found for job {job_id} to generate thumbnails."
                )

        # Context hint from transcript
        context_hint = ""
        candidates_ctx = [
            l_dir / f"transcript_{l_code}.json",
            job_dir / "segments_translated.json",
            job_dir / "english_transcript.json",
        ]
        for sc in candidates_ctx:
            if sc.exists():
                try:
                    with open(sc, "r", encoding="utf-8") as f:
                        segs = json.load(f)
                        context_hint = " ".join([s.get("translated_text", s.get("text", "")) for s in segs[:15]])
                        if context_hint:
                            break
                except Exception:
                    pass

        if not context_hint and job and job.get("result") and job["result"].get("segments"):
            context_hint = " ".join([s.get("translated_text", s.get("text", "")) for s in job["result"]["segments"][:15]])

        # Generate localized metadata
        meta = MultilingualMetadataGenerator.generate(
            english_title=title_hint,
            context_text=context_hint,
            target_lang=l_code,
            gemini_api_key=provided_key
        )

        l_dir.mkdir(parents=True, exist_ok=True)
        with open(l_dir / f"metadata_{l_code}.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        with open(l_dir / f"youtube_metadata_{l_code}.txt", "w", encoding="utf-8") as f:
            f.write(f"TITEL ({l_code.upper()}):\n{meta['title']}\n\n")
            f.write(f"BESCHREIBUNG:\n{meta['description']}\n\n")
            f.write(f"TAGS:\n{meta['tags']}\n")

        # For German, mirror to legacy files
        if l_code == "de":
            try:
                with open(l_dir / "metadata_german.json", "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # Generate localized thumbnail
        hook_text = meta.get("thumbnail_hook")
        MultilingualThumbnailGenerator.generate_thumbnail(
            video_path=video_candidate,
            hook_text=hook_text,
            output_path=l_thumb_file,
            lang_code=l_code
        )

        if l_code == "de" and l_thumb_file != (l_dir / "thumbnail_german.jpg"):
            try:
                import shutil
                shutil.copy2(l_thumb_file, l_dir / "thumbnail_german.jpg")
            except Exception:
                pass

        metadata_by_lang[l_code] = meta
        thumbnails_by_lang[l_code] = f"/api/jobs/{job_id}/languages/{l_code}/thumbnail"

    primary_code = langs_to_process[0] if langs_to_process else "de"
    primary_meta = metadata_by_lang.get(primary_code)
    primary_thumb_url = thumbnails_by_lang.get(primary_code, f"/api/jobs/{job_id}/thumbnail")

    if job:
        job["metadata_by_lang"] = metadata_by_lang
        job["thumbnails_by_lang"] = thumbnails_by_lang
        job["metadata"] = primary_meta
        job["thumbnail"] = str(job_dir / f"thumbnail_{primary_code}.jpg")
        job["thumbnail_url"] = primary_thumb_url

    return {
        "status": "success",
        "metadata_by_lang": metadata_by_lang,
        "thumbnails_by_lang": thumbnails_by_lang,
        "metadata": primary_meta,
        "thumbnail_url": primary_thumb_url,
    }


@app.post("/api/jobs/{job_id}/generate-german-pack", tags=["Dubbing"])
def generate_german_pack(job_id: str, request_data: Optional[GermanPackRequest] = None):
    """Backward compatibility endpoint for German SEO Pack."""
    seo_req = SEOPackRequest(
        lang="de",
        gemini_api_key=request_data.gemini_api_key if request_data else None
    )
    return generate_seo_pack(job_id=job_id, request_data=seo_req)


@app.get("/api/jobs/{job_id}/thumbnail", tags=["Outputs"])
def download_thumbnail(job_id: str, lang: Optional[str] = None):
    """Serves the generated 1280x720 YouTube thumbnail image for a specific or primary language."""
    job = jobs_db.get(job_id)
    job_dir = JOBS_DIR / job_id

    target_l = lang.lower().strip() if lang else None
    thumb_path = None

    if target_l:
        candidates = [
            job_dir / target_l / f"thumbnail_{target_l}.jpg",
            job_dir / f"thumbnail_{target_l}.jpg",
        ]
        if target_l == "de":
            candidates.extend([
                job_dir / "de" / "thumbnail_german.jpg",
                job_dir / "thumbnail_german.jpg",
            ])
        for c in candidates:
            if c.exists():
                thumb_path = c
                break

    if not thumb_path:
        if job and job.get("thumbnail") and Path(job["thumbnail"]).exists():
            thumb_path = Path(job["thumbnail"])
        elif (job_dir / "thumbnail_german.jpg").exists():
            thumb_path = job_dir / "thumbnail_german.jpg"
        elif (job_dir / "de" / "thumbnail_german.jpg").exists():
            thumb_path = job_dir / "de" / "thumbnail_german.jpg"
        else:
            thumbs = list(job_dir.glob("thumbnail_*.jpg")) or list(job_dir.glob("*/thumbnail_*.jpg"))
            if thumbs:
                thumb_path = thumbs[0]

    if not thumb_path or not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found or not generated yet")

    return FileResponse(
        path=thumb_path,
        media_type="image/jpeg",
        filename=thumb_path.name
    )


@app.get("/api/jobs/{job_id}/languages/{lang}/thumbnail", tags=["Outputs"])
def download_language_thumbnail(job_id: str, lang: str):
    """Serves the localized 1280x720 YouTube thumbnail image for the specified language."""
    return download_thumbnail(job_id=job_id, lang=lang)


@app.get("/api/jobs/{job_id}/download-all", tags=["Outputs"])
def download_all_languages_zip(job_id: str):
    """Downloads all dubbed languages packaged into a single ZIP archive organized in separate clean subfolders."""
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    zip_path = None
    if job.get("result") and job["result"].get("zip_path"):
        zip_path = Path(job["result"]["zip_path"])
    if not zip_path or not zip_path.exists():
        job_dir = JOBS_DIR / job_id
        zip_candidate = job_dir / "all_dubbed_languages.zip"
        if zip_candidate.exists():
            zip_path = zip_candidate

    if not zip_path or not zip_path.exists():
        raise HTTPException(status_code=404, detail="ZIP archive not found or dubbing job not finished yet")

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"all_dubbed_languages_{job_id}.zip"
    )


@app.get("/api/jobs/{job_id}/languages/{lang}/video", tags=["Outputs"])
def download_language_video(job_id: str, lang: str):
    """Streams or downloads the dubbed video for a specific language."""
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang_code = lang.lower()
    languages = job.get("languages") or (job.get("result") and job["result"].get("languages"))
    if not languages or lang_code not in languages:
        if job.get("target_lang") == lang_code and job.get("output_video_path"):
            v_p = Path(job["output_video_path"])
            if v_p.exists():
                return FileResponse(path=v_p, media_type="video/mp4", filename=v_p.name)
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found in completed job")

    video_path = Path(languages[lang_code]["final_video"])
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Dubbed video file for '{lang}' not found on disk")

    return FileResponse(path=video_path, media_type="video/mp4", filename=video_path.name)


@app.get("/api/jobs/{job_id}/languages/{lang}/audio", tags=["Outputs"])
def download_language_audio(job_id: str, lang: str):
    """Streams the synthesized dubbed vocals for a specific language."""
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang_code = lang.lower()
    languages = job.get("languages") or (job.get("result") and job["result"].get("languages"))
    if not languages or lang_code not in languages:
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found in completed job")

    audio_path = Path(languages[lang_code]["dub_vocals"])
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file for '{lang}' not found on disk")

    return FileResponse(path=audio_path, media_type="audio/wav", filename=audio_path.name)


@app.get("/api/jobs/{job_id}/languages/{lang}/segments", tags=["Outputs"])
def get_language_segments(job_id: str, lang: str):
    """Returns the timed transcription and translation segments JSON for a specific language."""
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    lang_code = lang.lower()
    languages = job.get("languages") or (job.get("result") and job["result"].get("languages"))
    if not languages or lang_code not in languages:
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found in completed job")

    return languages[lang_code].get("segments", [])


@app.get("/api/jobs/{job_id}/video", tags=["Outputs"])
def download_dubbed_video(job_id: str):
    """Streams or downloads the completed dubbed MP4 video."""
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed" or not job.get("output_video_path"):
        raise HTTPException(status_code=400, detail=f"Job not ready. Current status: {job['status']}")

    video_path = Path(job["output_video_path"])
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Exported video file missing on disk")

    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=video_path.name
    )


class TopMomentsRequest(BaseModel):
    url: Optional[str] = None
    duration_seconds: Optional[float] = None
    num_moments: int = 3
    moment_duration: float = 45.0


@app.post("/api/top-moments", tags=["Shorts"])
def get_top_moments_api(req: TopMomentsRequest):
    """
    Detects or pre-calculates top action/climax moments from a YouTube URL or video duration.
    """
    total_dur = req.duration_seconds or 0.0
    if req.url and total_dur <= 0:
        try:
            info = YouTubeDownloader.get_video_info(req.url.strip())
            total_dur = info.get("duration_seconds", 0.0)
        except Exception as e:
            logger.warning(f"Failed to fetch video info for top moments: {e}")

    moments = ShortsGenerator.detect_top_moments(
        duration_seconds=total_dur,
        num_moments=req.num_moments,
        moment_duration=req.moment_duration
    )
    return {
        "duration_seconds": total_dur,
        "num_moments": len(moments),
        "moment_duration": req.moment_duration,
        "moments": moments
    }


class GenerateShortsRequest(BaseModel):
    num_shorts: int = 3
    short_duration: float = 45.0
    aspect_ratio: str = "9:16"
    lang: Optional[str] = None


@app.post("/api/jobs/{job_id}/generate-shorts", tags=["Shorts"])
def generate_job_shorts_on_demand(job_id: str, req: GenerateShortsRequest):
    """
    Generates high-engagement 9:16 Instagram Reels / YouTube Shorts from an existing completed video job.
    """
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = JOBS_DIR / job_id
    target_video = None
    lang_code = (req.lang or job.get("target_lang") or "es").lower()

    if job.get("languages") and lang_code in job["languages"]:
        target_video = Path(job["languages"][lang_code]["final_video"])
    elif job.get("output_video_path") and Path(job["output_video_path"]).exists():
        target_video = Path(job["output_video_path"])
    else:
        candidates = list(job_dir.rglob("*_dubbed.mp4")) + list(job_dir.glob("*.mp4"))
        if candidates:
            target_video = candidates[0]

    if not target_video or not target_video.exists():
        raise HTTPException(status_code=404, detail="Source dubbed video file not found to create shorts from")

    total_dur = job.get("duration") or 0.0
    extracted_audio = job_dir / "original_audio.wav"
    audio_p = extracted_audio if extracted_audio.exists() else None

    top_moments = ShortsGenerator.detect_top_moments(
        video_path=target_video,
        audio_path=audio_p,
        duration_seconds=total_dur,
        num_moments=req.num_shorts,
        moment_duration=req.short_duration
    )

    shorts_dir = target_video.parent / "Shorts"
    shorts_dir.mkdir(parents=True, exist_ok=True)
    created_shorts = []

    for m in top_moments:
        short_clean_time = m["time_range"].replace(":", "-").replace(" ", "")
        short_fname = f"short_{m['index']}_{short_clean_time}.mp4"
        short_dest = shorts_dir / short_fname
        try:
            ShortsGenerator.create_vertical_short(
                input_video=target_video,
                output_path=short_dest,
                start_seconds=m["start_seconds"],
                duration_seconds=m["duration_seconds"],
                aspect_ratio=req.aspect_ratio
            )
            created_shorts.append({
                "index": m["index"],
                "title": m["title"],
                "category": m["category"],
                "time_range": m["time_range"],
                "start_seconds": m["start_seconds"],
                "duration_seconds": m["duration_seconds"],
                "filename": short_fname,
                "aspect_ratio": req.aspect_ratio,
                "video_url": f"/api/jobs/{job_id}/shorts/{short_fname}",
                "download_url": f"/api/jobs/{job_id}/shorts/{short_fname}",
            })
        except Exception as e:
            logger.error(f"Failed to generate short #{m['index']}: {e}")

    job["shorts"] = created_shorts
    job["is_shorts_mode"] = True

    return {
        "job_id": job_id,
        "total_shorts": len(created_shorts),
        "shorts": created_shorts
    }


@app.get("/api/jobs/{job_id}/shorts/{filename}", tags=["Shorts"])
def stream_job_short_video(job_id: str, filename: str):
    """
    Streams or downloads a 9:16 vertical Instagram Reel / YouTube Short.
    """
    job_dir = JOBS_DIR / job_id
    target_file = None
    candidates = list(job_dir.rglob(filename))
    if candidates and candidates[0].exists():
        target_file = candidates[0]
    else:
        matching = [f for f in job_dir.rglob("*.mp4") if f.name == filename or filename in f.name]
        if matching:
            target_file = matching[0]

    if not target_file or not target_file.exists():
        raise HTTPException(status_code=404, detail=f"Short video '{filename}' not found for job {job_id}")

    return FileResponse(
        path=target_file,
        media_type="video/mp4",
        filename=target_file.name
    )


@app.get("/api/jobs/{job_id}/segments", tags=["Outputs"])
def get_job_transcript_segments(job_id: str):
    """Returns the timed transcription and translation segments JSON."""
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed" or not job.get("result"):
        raise HTTPException(status_code=400, detail=f"Job not completed. Current status: {job['status']}")

    return job["result"].get("segments", [])


@app.get("/api/jobs/{job_id}/audio/{stem_name}", tags=["Outputs"])
def get_audio_stem(job_id: str, stem_name: str):
    """
    Streams an isolated audio stem.
    stem_name can be: 'vocals', 'background', 'spanish_vocals', or 'original_audio'
    """
    job = jobs_db.get(job_id)
    if not job or not job.get("result"):
        raise HTTPException(status_code=404, detail="Job or result not found")

    result = job["result"]
    target_path = None
    if stem_name in result:
        target_path = result[stem_name]
    elif stem_name in ["dub_vocals", "spanish_vocals", "target_vocals"]:
        target_path = result.get("dub_vocals") or result.get("spanish_vocals")

    if not target_path:
        raise HTTPException(
            status_code=400,
            detail="Invalid stem. Allowed stems: ['vocals', 'background', 'dub_vocals', 'spanish_vocals', 'original_audio']"
        )

    file_p = Path(target_path)
    if not file_p.exists():
        raise HTTPException(status_code=404, detail=f"Audio file {stem_name} not found on disk")

    return FileResponse(path=file_p, media_type="audio/wav", filename=file_p.name)


@app.post("/api/jobs/{job_id}/cancel", tags=["Dubbing"])
def cancel_job_endpoint(job_id: str):
    """Cancels an active or queued dubbing job, immediately aborting execution."""
    CANCELLED_JOBS.add(job_id)
    job = jobs_db.get(job_id)
    was_status = "unknown"
    if job:
        was_status = job.get("status", "unknown")
        job["status"] = "cancelled"
        job["is_cancelled"] = True
        job["current_step"] = "Cancelled by user"
        job["progress"] = 0.0
        job["completed_at"] = time.time()

    # Update conversion status in video project
    db.update_video_on_job_progress(
        job_id,
        "cancelled",
        0.0,
        videos_db,
        BASE_DIR / "workspace_api",
        jobs_db
    )

    notify_ws_clients(job_id, {
        "type": "cancelled",
        "message": "Job cancelled by user"
    })

    db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    return {"status": "cancelled", "job_id": job_id, "previous_status": was_status}


@app.post("/api/queue/cancel-all", tags=["Dubbing"])
def cancel_all_queue_endpoint():
    """Cancels all currently queued and processing dubbing jobs."""
    cancelled_ids = []
    for job_id, job in list(jobs_db.items()):
        st = job.get("status")
        if st in ["queued", "processing"]:
            CANCELLED_JOBS.add(job_id)
            job["status"] = "cancelled"
            job["is_cancelled"] = True
            job["current_step"] = "Cancelled by user"
            cancelled_ids.append(job_id)
            db.update_video_on_job_progress(
                job_id,
                "cancelled",
                0.0,
                videos_db,
                BASE_DIR / "workspace_api",
                jobs_db
            )
            notify_ws_clients(job_id, {
                "type": "cancelled",
                "message": "All jobs cancelled by user"
            })

    db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    return {"status": "cancelled", "cancelled_count": len(cancelled_ids), "job_ids": cancelled_ids}


@app.delete("/api/jobs/{job_id}", tags=["Dubbing"])
def delete_job(job_id: str):
    """Deletes temporary files, removes job from registry and video project conversions, and saves DB."""
    CANCELLED_JOBS.add(job_id)
    job = jobs_db.pop(job_id, None)

    # Remove conversion from any video's conversions in videos_db
    found_in_video = False
    for video in videos_db.values():
        conversions = video.get("conversions", [])
        updated_convs = [c for c in conversions if c.get("job_id") != job_id]
        if len(updated_convs) != len(conversions):
            found_in_video = True
            video["conversions"] = updated_convs
            all_langs = set()
            for c in updated_convs:
                for l in c.get("languages", []):
                    all_langs.add(l)
            video["languages"] = sorted(list(all_langs))
            video["updated_at"] = time.time()

    if not job and not found_in_video:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)

    db.save_databases(BASE_DIR / "workspace_api", jobs_db, videos_db)
    return {"status": "deleted", "job_id": job_id}


# ============================================================================
# WebSocket Live Streaming
# ============================================================================

@app.websocket("/api/jobs/{job_id}/ws")
async def websocket_job_progress(websocket: WebSocket, job_id: str):
    """
    Streams real-time progress, steps, and logs directly over WebSocket
    to any frontend (React, Vue, Flutter, iOS, Web).
    """
    await websocket.accept()
    if job_id not in ws_connections:
        ws_connections[job_id] = []
    ws_connections[job_id].append(websocket)

    # Send current state immediately on connect
    if job_id in jobs_db:
        current_job = jobs_db[job_id]
        await websocket.send_json({
            "type": "state",
            "status": current_job["status"],
            "progress": current_job["progress"],
            "step": current_job["current_step"],
            "logs": current_job["logs"]
        })

    try:
        while True:
            # Keep socket alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        if job_id in ws_connections and websocket in ws_connections[job_id]:
            ws_connections[job_id].remove(websocket)


# ============================================================================
# YouTube Downloader (YTD) Subsystem Endpoints
# ============================================================================

import ytd

class YtdAddChannelRequest(BaseModel):
    url: str
    title: Optional[str] = None

class YtdUpdateChannelRequest(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None

class YtdDownloadRequest(BaseModel):
    type: Optional[str] = None  # "full", "split", "splits", "shorts"
    download_type: Optional[str] = None
    split_minutes: Optional[int] = None  # 2, 5, 9
    part_duration_mins: Optional[int] = None
    shorts_count: Optional[int] = None
    num_shorts: Optional[int] = None


@app.get("/api/ytd/stats", tags=["YTD"])
def get_ytd_stats_endpoint():
    """Returns overall stats for the YouTube Downloader."""
    return ytd.get_ytd_stats()


@app.get("/api/ytd/channels", tags=["YTD"])
def list_ytd_channels():
    """Lists all connected YouTube channels."""
    return ytd.get_all_channels()


@app.post("/api/ytd/channels", status_code=status.HTTP_201_CREATED, tags=["YTD"])
def add_ytd_channel(req: YtdAddChannelRequest):
    """Adds a new YouTube channel and syncs its videos."""
    try:
        return ytd.add_channel(req.url, req.title)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ytd/channels/{channel_id}", tags=["YTD"])
def get_ytd_channel(channel_id: int):
    """Retrieves channel info by ID."""
    ch = ytd.get_channel_by_id(channel_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ch


@app.put("/api/ytd/channels/{channel_id}", tags=["YTD"])
def update_ytd_channel(channel_id: int, req: YtdUpdateChannelRequest):
    """Updates channel title or URL."""
    try:
        return ytd.update_channel(channel_id, req.title, req.url)
    except KeyError:
        raise HTTPException(status_code=404, detail="Channel not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/ytd/channels/{channel_id}", tags=["YTD"])
def delete_ytd_channel(channel_id: int):
    """Deletes channel and all its videos and downloaded files."""
    try:
        ytd.delete_channel(channel_id)
        return {"status": "deleted", "channel_id": channel_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ytd/channels/{channel_id}/sync", tags=["YTD"])
def sync_ytd_channel(channel_id: int):
    """Re-syncs all videos of a channel from YouTube."""
    try:
        return ytd.sync_channel_by_id(channel_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Channel not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ytd/channels/{channel_id}/videos", tags=["YTD"])
def list_ytd_channel_videos(
    channel_id: int,
    status: str = "all",
    search: str = "",
    limit: int = 150,
    offset: int = 0
):
    """Returns videos belonging to a channel."""
    return ytd.get_channel_videos(channel_id, status_filter=status, search=search, limit=limit, offset=offset)


@app.post("/api/ytd/videos/{video_id}/download", tags=["YTD"])
def start_ytd_video_download(video_id: int, req: YtdDownloadRequest):
    """Queues downloading a video in Full, Split (2, 5, 9 mins), or Shorts."""
    try:
        dl_type = (req.download_type or req.type or "full").lower()
        split_mins = req.part_duration_mins or req.split_minutes or 5
        shorts_cnt = req.num_shorts or req.shorts_count or 3
        return ytd.queue_video_download(
            video_id,
            download_type=dl_type,
            split_minutes=split_mins,
            shorts_count=shorts_cnt
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Video not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ytd/videos/{video_id}/status", tags=["YTD"])
def get_ytd_video_status(video_id: int):
    """Returns download status and progress for a video."""
    vid = ytd.get_video_by_id(video_id)
    if not vid:
        raise HTTPException(status_code=404, detail="Video not found")
    active = ytd.active_ytd_downloads.get(video_id, {})
    return {
        "id": vid["id"],
        "is_downloaded": bool(vid["is_downloaded"]),
        "status": active.get("status") or vid["download_status"],
        "progress": active.get("progress") if active.get("progress") is not None else vid["download_progress"],
        "step": active.get("step") or vid["download_status"],
        "error": active.get("error") or vid["download_error"],
        "download_file_name": vid["download_file_name"],
        "download_file_size": vid["download_file_size"],
        "download_type": vid["download_type"],
        "is_zip": bool(vid["is_zip"])
    }


@app.get("/api/ytd/videos/{video_id}/file", tags=["YTD"])
def download_ytd_video_file(video_id: int):
    """Serves the downloaded video or ZIP archive to the browser."""
    vid = ytd.get_video_by_id(video_id)
    if not vid or not vid["download_path"]:
        raise HTTPException(status_code=404, detail="Video file not found or not yet downloaded")

    file_p = Path(vid["download_path"])
    if not file_p.exists():
        raise HTTPException(status_code=404, detail="Downloaded file is missing from disk")

    media_type = "application/zip" if vid["is_zip"] else "video/mp4"
    filename = vid["download_file_name"] or file_p.name
    return FileResponse(path=file_p, media_type=media_type, filename=filename)


@app.delete("/api/ytd/videos/{video_id}", tags=["YTD"])
def delete_ytd_video(video_id: int):
    """
    Deletes video from database and disk, and adds its YouTube ID to
    the permanent delete blacklist so it can never be re-added on sync.
    """
    try:
        return ytd.delete_video(video_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Video not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Direct YouTube Video Downloader Endpoints
# ============================================================================

class DirectAddVideoRequest(BaseModel):
    url: str
    title: Optional[str] = None
    auto_download: Optional[bool] = True


class DirectCheckRequest(BaseModel):
    url: str


@app.get("/api/direct/stats", tags=["Direct Downloads"])
def get_direct_stats_endpoint():
    """Returns statistics for direct video downloads."""
    return ytd.get_direct_stats()


@app.get("/api/direct/videos", tags=["Direct Downloads"])
def list_direct_videos(
    search: str = "",
    status: str = "all",
    limit: int = 250,
    offset: int = 0
):
    """Lists direct videos with optional search query and status filtering."""
    return ytd.get_all_direct_videos(search=search, status_filter=status, limit=limit, offset=offset)


@app.post("/api/direct/videos", status_code=status.HTTP_201_CREATED, tags=["Direct Downloads"])
def add_direct_video_endpoint(req: DirectAddVideoRequest):
    """Adds a direct YouTube video link and optionally triggers download."""
    try:
        return ytd.add_direct_video(req.url, title=req.title, auto_download=bool(req.auto_download))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/direct/videos/check", tags=["Direct Downloads"])
def check_direct_video_endpoint(req: DirectCheckRequest):
    """Checks if a YouTube video URL or ID is already saved in direct downloads."""
    return ytd.check_direct_video_exists(req.url)


@app.post("/api/direct/videos/{video_id}/download", tags=["Direct Downloads"])
def start_direct_video_download(video_id: int):
    """Starts or restarts downloading a direct video."""
    try:
        return ytd.queue_direct_video_download(video_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Direct video record not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/direct/videos/{video_id}/status", tags=["Direct Downloads"])
def get_direct_video_status(video_id: int):
    """Returns the live download status of a direct video."""
    v = ytd.get_direct_video_by_id(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Direct video not found")
    return {
        "id": v["id"],
        "is_downloaded": bool(v["is_downloaded"]),
        "was_downloaded": bool(v.get("was_downloaded", 0)),
        "status": v["download_status"],
        "progress": v["download_progress"],
        "download_file_name": v.get("download_file_name"),
        "download_file_size": v.get("download_file_size"),
        "error": v.get("download_error")
    }


@app.get("/api/direct/videos/{video_id}/file", tags=["Direct Downloads"])
def download_direct_video_file(video_id: int):
    """Serves the downloaded video file to the user's browser for saving."""
    v = ytd.get_direct_video_by_id(video_id)
    if not v or not v.get("download_path"):
        raise HTTPException(status_code=404, detail="Video file not found or has been cleared to reduce storage")

    p = Path(v["download_path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="Video file is missing from disk")

    filename = v.get("download_file_name") or p.name
    return FileResponse(
        path=p,
        media_type="video/mp4",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.delete("/api/direct/videos/{video_id}/video", tags=["Direct Downloads"])
def delete_direct_video_file_only(video_id: int):
    """Deletes ONLY the video file from disk to save storage, keeping the record intact."""
    try:
        return ytd.delete_direct_video_file_only(video_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Direct video not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/direct/videos/{video_id}", tags=["Direct Downloads"])
def delete_direct_video_record(video_id: int):
    """Permanently deletes the video record and its file."""
    try:
        return ytd.delete_direct_video_permanent(video_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Direct video not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Server Runner
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "3333"))
    print("=" * 70)
    print("🚀 STARTING DUBFLOW STUDIO FASTAPI PRODUCTION SERVER")
    print("=" * 70)
    print(f"• Web UI & Admin Panel   : http://{host}:{port}/")
    print(f"• Interactive Swagger UI : http://{host}:{port}/docs")
    print(f"• Health Check Endpoint  : http://{host}:{port}/api/health")
    print("=" * 70)
    uvicorn.run("api:app", host=host, port=port, reload=False)
