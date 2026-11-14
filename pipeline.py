"""
ManhwaDub - Local AI Video Dubbing Pipeline for Apple Silicon (M1 Pro/Max)
===========================================================================
A clean, modular local AI automation pipeline that dubs English videos
(e.g., Manhwa recaps / motion comics) into Spanish, preserving background
music and sound effects.

Hardware Acceleration:
- PyTorch Metal Performance Shaders (device = 'mps')
- Optimized CPU execution via Apple Accelerate & NEON SIMD for Whisper & CTranslate2
"""

import os
import sys
import json
import shutil
import logging
import subprocess
import asyncio
import zipfile
import platform
import math
import uuid
import gc
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Callable
import threading
import concurrent.futures

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Ensure PyTorch MPS Fallback is active before importing torch if on macOS
if platform.system() == "Darwin":
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

# Compatibility patch: PyAV 14+ removed 'metadata_errors' which causes faster-whisper to raise:
# TypeError: open() got an unexpected keyword argument 'metadata_errors'
try:
    import av
    if hasattr(av, "open"):
        _orig_av_open = av.open
        def _safe_av_open(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return _orig_av_open(*args, **kwargs)
        av.open = _safe_av_open
except Exception:
    pass

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("DubFlow")


# ============================================================================
# Device & Hardware Optimization Manager (Dynamic for Cloud VMs & Local OS)
# ============================================================================

class HardwareAccelerationManager:
    """Detects and dynamically configures hardware acceleration for Linux Cloud VMs (NVIDIA CUDA / CPU), macOS (Apple Silicon MPS), and Windows."""

    @staticmethod
    def get_torch_device() -> str:
        """
        Determines the optimal PyTorch device dynamically.
        Prefers NVIDIA CUDA on Cloud VMs / Linux servers,
        followed by Apple Silicon Metal Performance Shaders ('mps') on macOS,
        with robust multi-core CPU optimization fallback.
        """
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                logger.info(f"NVIDIA CUDA GPU detected: {gpu_name}. Hardware acceleration active.")
                return "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available() and torch.backends.mps.is_built():
                logger.info("Apple Silicon GPU detected. Metal Performance Shaders (MPS) active.")
                return "mps"
            else:
                logger.info("GPU acceleration not present. Using high-performance multi-core CPU optimization.")
                return "cpu"
        except Exception as e:
            logger.warning(f"PyTorch device check encountered: {e}. Defaulting to CPU.")
            return "cpu"

    @staticmethod
    def get_device_info() -> Dict[str, Any]:
        """Returns structured hardware information for telemetry and UI badges."""
        device = HardwareAccelerationManager.get_torch_device()
        cpu_cores = os.cpu_count() or 4
        os_name = platform.system()
        gpu_name = None
        engine_label = f"Multi-Core CPU ({cpu_cores} Cores)"

        try:
            import torch
            if device == "cuda":
                gpu_name = torch.cuda.get_device_name(0)
                engine_label = f"NVIDIA CUDA ({gpu_name})"
            elif device == "mps":
                engine_label = "Apple Silicon MPS (Metal)"
            else:
                engine_label = f"Multi-Core CPU ({cpu_cores} Cores)"
        except Exception:
            pass

        workers = HardwareAccelerationManager.get_optimal_worker_count()
        return {
            "device": device,
            "engine_label": engine_label,
            "gpu_name": gpu_name,
            "cpu_cores": cpu_cores,
            "os": os_name,
            "parallel_workers": workers
        }

    @staticmethod
    def get_effective_ram_gb() -> float:
        """
        Determines the true effective RAM in GB available to this process,
        properly accounting for Docker container cgroup memory limits if running in a container.
        """
        cgroup_bytes = None
        for p in ["/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"]:
            path = Path(p)
            if path.exists():
                try:
                    val = path.read_text().strip()
                    if val != "max" and val.isdigit():
                        cgroup_bytes = int(val)
                        break
                except Exception:
                    pass

        host_bytes = None
        try:
            import psutil
            host_bytes = psutil.virtual_memory().total
        except Exception:
            try:
                meminfo_p = Path("/proc/meminfo")
                if meminfo_p.exists():
                    with open(meminfo_p, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("MemTotal:"):
                                total_kb = int(line.split(":")[1].strip().split()[0])
                                host_bytes = total_kb * 1024
                                break
            except Exception:
                pass

        if cgroup_bytes and host_bytes:
            effective_bytes = min(cgroup_bytes, host_bytes)
        elif cgroup_bytes:
            effective_bytes = cgroup_bytes
        elif host_bytes:
            effective_bytes = host_bytes
        else:
            effective_bytes = 8 * (1024 ** 3)

        return effective_bytes / (1024 ** 3)

    @staticmethod
    def get_optimal_worker_count(reserved_gb: float = 3.0, gb_per_worker: float = 4.0, max_cap: int = 4) -> int:
        """
        Dynamically calculates how many conversion parts can safely run in parallel based on system RAM:
        - < 8GB RAM: 1 part (strictly sequential to avoid OOM crash)
        - 8GB - 14GB RAM: 2 parts in parallel
        - 15GB - 22GB RAM: 3 parts in parallel
        - >= 23GB RAM: 4 parts in parallel
        Can be manually overridden at any time via MAX_PARALLEL_WORKERS environment variable.
        """
        env_override = os.getenv("MAX_PARALLEL_WORKERS") or os.getenv("DUBFLOW_MAX_WORKERS") or os.getenv("PARALLEL_PARTS")
        if env_override:
            try:
                val = int(env_override.strip())
                if val >= 1:
                    logger.info(f"Using manual MAX_PARALLEL_WORKERS override: {val}")
                    return val
            except ValueError:
                pass

        effective_gb = HardwareAccelerationManager.get_effective_ram_gb()
        cpu_cores = os.cpu_count() or 4

        avail_ram = max(0.0, effective_gb - reserved_gb)
        workers_by_ram = int(avail_ram // gb_per_worker)
        workers_by_cpu = max(1, cpu_cores // 2)

        optimal = max(1, min(workers_by_ram, workers_by_cpu, max_cap))
        return optimal

    @staticmethod
    def get_whisper_config() -> Dict[str, Any]:
        """Configures faster-whisper (CTranslate2) dynamically for CUDA or CPU."""
        device = HardwareAccelerationManager.get_torch_device()
        cpu_cores = os.cpu_count() or 4
        optimal_threads = min(max(cpu_cores - 2, 2), 8)

        if device == "cuda":
            return {
                "device": "cuda",
                "compute_type": "float16",
                "cpu_threads": optimal_threads,
            }
        else:
            return {
                "device": "cpu",
                "compute_type": "int8",
                "cpu_threads": optimal_threads,
            }

    @staticmethod
    def verify_ffmpeg() -> bool:
        """Verifies if ffmpeg is accessible in system PATH."""
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            logger.info(f"FFmpeg found at: {ffmpeg_path}")
            return True
        logger.error("FFmpeg not found! Please ensure ffmpeg is installed (e.g. `apt-get install ffmpeg` on Linux VM).")
        return False


# Compatibility alias for existing code
AppleSiliconManager = HardwareAccelerationManager


# ============================================================================
# YouTube Downloader
# ============================================================================

# ============================================================================

def find_cookies_file() -> Optional[Path]:
    """Finds a valid Netscape cookies.txt file across environment variables and project paths."""
    # 1. Check base64 encoded cookies in environment (ideal for Docker / headless VM deployments)
    b64_env = os.getenv("YOUTUBE_COOKIES_B64")
    if b64_env:
        try:
            import base64
            decoded = base64.b64decode(b64_env).decode("utf-8", errors="ignore")
            if len(decoded) > 100:
                target = Path(__file__).resolve().parent / "cookies.txt"
                target.write_text(decoded)
                try:
                    ws_target = Path(__file__).resolve().parent / "workspace_api" / "cookies.txt"
                    ws_target.parent.mkdir(parents=True, exist_ok=True)
                    ws_target.write_text(decoded)
                except Exception:
                    pass
                return target
        except Exception as e:
            logger.warning(f"Could not load cookies from YOUTUBE_COOKIES_B64: {e}")

    raw_env = os.getenv("YOUTUBE_COOKIES")
    if raw_env and len(raw_env) > 100:
        try:
            target = Path(__file__).resolve().parent / "cookies.txt"
            target.write_text(raw_env)
            try:
                ws_target = Path(__file__).resolve().parent / "workspace_api" / "cookies.txt"
                ws_target.parent.mkdir(parents=True, exist_ok=True)
                ws_target.write_text(raw_env)
            except Exception:
                pass
            return target
        except Exception as e:
            logger.warning(f"Could not load cookies from YOUTUBE_COOKIES: {e}")

    # 2. Check candidate filesystem paths on Mac or Linux VM
    base_dir = Path(__file__).resolve().parent
    candidates = [
        base_dir / "cookies.txt",
        Path("cookies.txt"),
        base_dir / "workspace_api" / "cookies.txt",
        Path("workspace_api/cookies.txt"),
        Path.home() / ".dubflow" / "cookies.txt",
        Path("/etc/dubflow/cookies.txt"),
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 100:
            return p
    return None


def sync_browser_cookies(browser: Optional[str] = "chrome", target_path: Optional[Path] = None) -> Tuple[bool, str]:
    """
    Extracts YouTube/Google cookies from browser into cookies.txt.
    Supports macOS, Linux desktop, and headless VM fallback.
    """
    if target_path is None:
        target_path = Path(__file__).resolve().parent / "cookies.txt"

    import yt_dlp

    browsers_to_try = [browser] if browser and browser != "auto" else ["chrome", "chromium", "firefox", "brave", "edge"]
    last_err = ""

    for b in browsers_to_try:
        try:
            ydl_opts = {
                "cookiesfrombrowser": (b, None, None, None),
                "cookiefile": str(target_path),
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                pass
            if target_path.exists() and target_path.stat().st_size > 100:
                # Also mirror to workspace_api/cookies.txt for persistent volume storage on VM
                try:
                    mirror_path = Path(__file__).resolve().parent / "workspace_api" / "cookies.txt"
                    mirror_path.parent.mkdir(parents=True, exist_ok=True)
                    mirror_path.write_bytes(target_path.read_bytes())
                except Exception:
                    pass
                return True, f"Successfully synced cookies from {b} ({target_path.stat().st_size} bytes)"
        except Exception as e:
            last_err = str(e)
            continue

    return False, (
        f"Could not extract browser cookies ({last_err}). "
        f"If running on a headless VM without a desktop browser, please upload/paste cookies.txt via the Web UI "
        f"or set YOUTUBE_COOKIES_B64 in your .env file."
    )


class YouTubeDownloader:
    """Downloads YouTube videos locally using yt-dlp with authentication, bot-bypass and session cookies."""

    @staticmethod
    def _build_ydl_opts(
        extra_opts: Optional[Dict[str, Any]] = None,
        use_cookies: bool = True,
        clients: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        if clients is None:
            clients = ["visionos", "android", "ios", "mweb", "web"]

        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        )

        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "remote_components": ["ejs:github"],
            "js_runtimes": {"node": {}, "deno": {}, "quickjs": {}},
            "user_agent": user_agent,
            "http_headers": {
                "User-Agent": user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
            "extractor_args": {
                "youtube": {
                    "player_client": clients
                }
            },
        }

        # NOTE: Google/YouTube requires session cookies for authenticated requests.
        # Basic auth username/password is not supported by YouTube.
        if use_cookies:
            cookie_file = find_cookies_file()
            if cookie_file:
                opts["cookiefile"] = str(cookie_file)

        if extra_opts:
            opts.update(extra_opts)
        return opts

    @staticmethod
    def download(
        url: str,
        output_dir: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """Downloads the best MP4 video stream from a YouTube URL with authentication fallback."""
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError("`yt-dlp` is required for YouTube downloading. Run `pip install yt-dlp`.")

        logger.info(f"Downloading YouTube video from: {url}")
        output_dir.mkdir(parents=True, exist_ok=True)
        outtmpl = str(output_dir / "%(id)s.%(ext)s")

        def ydl_hook(d):
            if d.get("status") == "downloading" and progress_callback:
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                pct = min(downloaded / total, 1.0)
                progress_callback(pct * 0.1, f"Downloading YouTube: {int(pct * 100)}%")

        base_opts = {
            "format": "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "progress_hooks": [ydl_hook],
            "noplaylist": True,
        }

        # Attempt 1: Standard download with available cookies and multi-client fallback
        ydl_opts = YouTubeDownloader._build_ydl_opts(base_opts, use_cookies=True)
        last_error = None

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info.get("id", "youtube_video")
                expected_mp4 = output_dir / f"{video_id}.mp4"
                if expected_mp4.exists() and expected_mp4.stat().st_size > 0:
                    logger.info(f"YouTube video downloaded successfully: {expected_mp4}")
                    return expected_mp4

                candidates = list(output_dir.glob(f"{video_id}*.mp4"))
                if candidates:
                    return candidates[0]
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            logger.warning(f"Initial YouTube download attempt failed: {e}. Checking authentication fallback...")

            # If blocked by signin, bot verification, format error, or reload requirement:
            if any(k in err_str for k in ["sign in", "bot", "reload", "confirm", "format", "private"]):
                # Attempt to refresh cookies from Chrome browser
                sync_ok, sync_msg = sync_browser_cookies("chrome")
                if sync_ok:
                    logger.info(f"Refreshed Chrome cookies: {sync_msg}. Retrying download...")
                
                # Retry with authenticated web client and challenge solver
                retry_opts = YouTubeDownloader._build_ydl_opts(
                    base_opts,
                    use_cookies=True,
                    clients=["web", "mweb", "visionos"]
                )
                try:
                    with yt_dlp.YoutubeDL(retry_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        video_id = info.get("id", "youtube_video")
                        expected_mp4 = output_dir / f"{video_id}.mp4"
                        if expected_mp4.exists() and expected_mp4.stat().st_size > 0:
                            logger.info(f"YouTube video downloaded on auth retry: {expected_mp4}")
                            return expected_mp4
                        candidates = list(output_dir.glob(f"{video_id}*.mp4"))
                        if candidates:
                            return candidates[0]
                except Exception as retry_e:
                    last_error = retry_e

        # If both attempts failed, provide clear user-friendly explanation
        err_msg = str(last_error) if last_error else "Unknown download error"
        email = os.getenv("YOUTUBE_EMAIL", "manhwadesistyle@gmail.com")
        if "unavailable" in err_msg.lower():
            raise RuntimeError(
                f"YouTube video is unavailable ({url}). The video may have been deleted, made private, or the link has a typo."
            ) from last_error
        elif "sign in" in err_msg.lower() or "bot" in err_msg.lower():
            raise RuntimeError(
                f"YouTube requires sign-in verification for this video ({url}). "
                f"Because this server runs on a cloud VM, YouTube requires active session cookies for account '{email}'. "
                f"Please update cookies via 'VM & Cookie Transfer Tools' or upload the MP4 file directly via the 'Upload File' tab."
            ) from last_error
        raise RuntimeError(f"YouTube download failed: {err_msg}") from last_error

    @staticmethod
    def get_video_info(url: str) -> Dict[str, Any]:
        """Fetches YouTube video metadata (title, duration, thumbnail) with authentication fallback."""
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError("`yt-dlp` is required. Run `pip install yt-dlp`.")

        last_error = None
        for attempt, clients in enumerate([
            ["visionos", "android", "ios", "mweb", "web"],
            ["web", "mweb", "visionos"]
        ]):
            ydl_opts = YouTubeDownloader._build_ydl_opts(
                {"skip_download": True},
                use_cookies=True,
                clients=clients
            )
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    duration_sec = info.get("duration", 0) or 0
                    
                    hours = int(duration_sec // 3600)
                    mins = int((duration_sec % 3600) // 60)
                    secs = int(duration_sec % 60)
                    duration_str = f"{hours:02d}:{mins:02d}:{secs:02d}" if hours > 0 else f"{mins:02d}:{secs:02d}"

                    return {
                        "id": info.get("id", ""),
                        "title": info.get("title", "Untitled Video"),
                        "duration_seconds": duration_sec,
                        "duration_formatted": duration_str,
                        "duration_minutes": round(duration_sec / 60.0, 1),
                        "thumbnail": info.get("thumbnail") or (info.get("thumbnails")[-1]["url"] if info.get("thumbnails") else ""),
                        "channel": info.get("uploader") or info.get("channel", "Unknown Channel"),
                        "view_count": info.get("view_count", 0),
                    }
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if attempt == 0 and any(k in err_str for k in ["sign in", "bot", "reload", "confirm", "format"]):
                    sync_browser_cookies("chrome")
                    continue
                break

        err_msg = str(last_error) if last_error else "Unknown error"
        email = os.getenv("YOUTUBE_EMAIL", "manhwadesistyle@gmail.com")
        if "unavailable" in err_msg.lower():
            raise ValueError("YouTube video is unavailable. It may have been deleted, made private, or the URL contains a typo.") from last_error
        elif "sign in" in err_msg.lower() or "bot" in err_msg.lower():
            raise ValueError(
                f"YouTube requires sign-in verification for this video. "
                f"Because this server runs on a cloud VM, YouTube requires active session cookies for '{email}'. "
                f"Please update cookies via 'VM & Cookie Transfer Tools' or upload the file directly."
            ) from last_error
        raise ValueError(f"Unable to access video: {err_msg}") from last_error



# ============================================================================
# Video Segmenter & Trimmer
# ============================================================================

class VideoSegmenter:
    """Trims, splits, and concatenates videos into timed parts using FFmpeg fast stream copy."""

    @staticmethod
    def get_duration(video_path: Path) -> float:
        """Retrieves exact duration in seconds of a video file using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        try:
            res = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True).strip()
            val = float(res)
            if val > 0:
                return val
        except Exception as e:
            logger.warning(f"ffprobe duration probe failed on {video_path}: {e}")

        try:
            cmd_stream = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ]
            res = subprocess.check_output(cmd_stream, stderr=subprocess.PIPE, text=True).strip()
            val = float(res)
            if val > 0:
                return val
        except Exception:
            pass

        return 0.0

    @staticmethod
    def trim(
        input_video: Path,
        output_video: Path,
        start_seconds: float = 0.0,
        duration_seconds: Optional[float] = None
    ) -> Path:
        """
        Extracts a segment from input_video starting at start_seconds.
        Uses keyframe-accurate fast stream copying (-c copy) with clean timestamp resets.
        """
        output_video.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_seconds),
            "-i", str(input_video),
        ]
        if duration_seconds is not None and duration_seconds > 0:
            cmd.extend(["-t", str(duration_seconds)])
        
        cmd.extend(["-c", "copy", "-avoid_negative_ts", "make_zero", str(output_video)])

        try:
            logger.info(f"Trimming video segment: start={start_seconds}s, duration={duration_seconds}s -> {output_video.name}")
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return output_video
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg trim failed: {e.stderr.decode('utf-8', errors='ignore')}")
            # If fast stream copy fails due to container keyframe quirks, fallback to transcode trim
            logger.warning("Retrying trim with fast re-encode...")
            cmd_fallback = [
                "ffmpeg", "-y",
                "-ss", str(start_seconds),
                "-i", str(input_video),
            ]
            if duration_seconds is not None and duration_seconds > 0:
                cmd_fallback.extend(["-t", str(duration_seconds)])
            cmd_fallback.extend(["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", "-avoid_negative_ts", "make_zero", str(output_video)])
            subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return output_video

    @staticmethod
    def merge_video_chunks(chunk_paths: List[Path], output_video: Path) -> Path:
        """
        Concatenates multiple video parts sequentially using FFmpeg concat demuxer.
        Falls back to fast stream re-encode concat if fast copy encounters container issues.
        """
        if not chunk_paths:
            raise ValueError("No video chunks provided to merge.")
        if len(chunk_paths) == 1:
            if Path(chunk_paths[0]).resolve() != output_video.resolve():
                shutil.copyfile(str(chunk_paths[0]), str(output_video))
            return output_video

        output_video.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_video.parent / f"concat_list_{uuid.uuid4().hex[:6]}.txt"
        try:
            with open(list_file, "w", encoding="utf-8") as f:
                for p in chunk_paths:
                    escaped = str(Path(p).resolve()).replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            # Fast stream copy concat
            cmd_copy = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-map", "0:v",
                "-map", "0:a?",
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_video)
            ]
            try:
                subprocess.run(cmd_copy, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                logger.info(f"Successfully merged {len(chunk_paths)} video chunks into {output_video.name} via stream copy.")
                return output_video
            except subprocess.CalledProcessError as e:
                logger.warning(f"Fast stream copy concat failed ({e.stderr.decode('utf-8', errors='ignore')[:200]}), falling back to safe re-encode concat...")
                cmd_reencode = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(list_file),
                    "-map", "0:v",
                    "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                    "-movflags", "+faststart",
                    str(output_video)
                ]
                subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                logger.info(f"Successfully merged {len(chunk_paths)} video chunks into {output_video.name} via re-encode concat.")
                return output_video
        finally:
            if list_file.exists():
                try:
                    list_file.unlink()
                except Exception:
                    pass

    @staticmethod
    def merge_audio_chunks(chunk_paths: List[Path], output_audio: Path) -> Path:
        """Concatenates multiple audio files sequentially."""
        valid_paths = [p for p in chunk_paths if p and Path(p).exists()]
        if not valid_paths:
            return output_audio
        if len(valid_paths) == 1:
            if Path(valid_paths[0]).resolve() != output_audio.resolve():
                shutil.copyfile(str(valid_paths[0]), str(output_audio))
            return output_audio

        output_audio.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_audio.parent / f"concat_audio_{uuid.uuid4().hex[:6]}.txt"
        try:
            with open(list_file, "w", encoding="utf-8") as f:
                for p in valid_paths:
                    escaped = str(Path(p).resolve()).replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            cmd_copy = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                str(output_audio)
            ]
            try:
                subprocess.run(cmd_copy, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                return output_audio
            except Exception:
                cmd_reencode = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(list_file),
                    "-c:a", "pcm_s16le",
                    str(output_audio)
                ]
                subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                return output_audio
        finally:
            if list_file.exists():
                try:
                    list_file.unlink()
                except Exception:
                    pass


class ShortsGenerator:
    """
    Creates high-engagement Instagram Reels / YouTube Shorts (9:16 vertical video)
    from top action and climax moments in manhwa and recap videos.
    """

    MOMENT_CATEGORIES = [
        "🔥 Peak Action & Climax",
        "⚡ Epic Confrontation",
        "🎬 Plot Twist & Dramatic Reveal",
        "💥 Unstoppable Power Awakening",
        "🗡️ Decisive Battle Turn",
        "🛡️ Legendary Stand",
        "✨ Final Climax Clashing",
        "🔥 High-Voltage Climax",
        "⚡ Secret Revealed",
        "💥 Supreme Counterattack",
    ]

    @staticmethod
    def format_timestamp(s: float) -> str:
        s = max(0.0, float(s))
        hrs = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        if hrs > 0:
            return f"{hrs}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"

    @staticmethod
    def detect_top_moments(
        video_path: Optional[Path] = None,
        audio_path: Optional[Path] = None,
        duration_seconds: float = 0.0,
        num_moments: int = 3,
        moment_duration: float = 45.0,
    ) -> List[Dict[str, Any]]:
        """
        Detects top climax moments in the video.
        Uses audio RMS energy peak detection if audio/video is on disk,
        or narrative climax distribution curve if only duration is known.
        """
        num_moments = max(1, min(10, int(num_moments)))
        moment_duration = max(15.0, min(90.0, float(moment_duration)))

        # 1. Try audio energy detection if audio_path exists
        if audio_path and Path(audio_path).exists():
            moments = ShortsGenerator._detect_via_audio(Path(audio_path), duration_seconds, num_moments, moment_duration)
            if moments:
                return moments

        # 2. Try fast audio extraction & energy detection if video_path exists
        if video_path and Path(video_path).exists():
            try:
                temp_wav = Path(video_path).parent / f"energy_probe_{Path(video_path).stem}.wav"
                cmd = [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-vn", "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(temp_wav)
                ]
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                moments = ShortsGenerator._detect_via_audio(temp_wav, duration_seconds, num_moments, moment_duration)
                if temp_wav.exists():
                    temp_wav.unlink(missing_ok=True)
                if moments:
                    return moments
            except Exception as e:
                logger.warning(f"Audio energy detection fallback to narrative curve: {e}")

        # 3. Fallback to narrative climax curve
        return ShortsGenerator._calculate_narrative_moments(duration_seconds, num_moments, moment_duration)

    @staticmethod
    def _detect_via_audio(
        wav_path: Path,
        duration_seconds: float,
        num_moments: int,
        moment_duration: float
    ) -> List[Dict[str, Any]]:
        try:
            import numpy as np
            import soundfile as sf
            data, sr = sf.read(str(wav_path))
            if len(data.shape) > 1:
                data = np.mean(data, axis=1)
            total_dur = len(data) / sr if sr > 0 else duration_seconds
            if total_dur < moment_duration:
                return [{
                    "index": 1,
                    "title": "Top Moment #1",
                    "category": ShortsGenerator.MOMENT_CATEGORIES[0],
                    "start_seconds": 0.0,
                    "duration_seconds": round(total_dur, 1),
                    "end_seconds": round(total_dur, 1),
                    "time_range": f"00:00 - {ShortsGenerator.format_timestamp(total_dur)}",
                    "score": 1.0
                }]

            win_size = int(moment_duration * sr)
            step_size = int(5.0 * sr)
            windows = []
            min_sample = int(total_dur * 0.05 * sr)
            max_sample = max(min_sample + win_size, int((total_dur * 0.96 - moment_duration) * sr))

            for s_idx in range(min_sample, max_sample, step_size):
                chunk = data[s_idx:s_idx + win_size]
                if len(chunk) < win_size:
                    break
                rms = float(np.sqrt(np.mean(chunk**2)))
                windows.append((s_idx / sr, (s_idx + win_size) / sr, rms))

            if not windows:
                return ShortsGenerator._calculate_narrative_moments(total_dur, num_moments, moment_duration)

            windows.sort(key=lambda x: x[2], reverse=True)
            chosen = []
            for start, end, score in windows:
                if not any(abs(start - c[0]) < (moment_duration * 0.8) for c in chosen):
                    chosen.append((start, end, score))
                if len(chosen) >= num_moments:
                    break

            chosen.sort(key=lambda x: x[0])
            results = []
            for idx, (st, en, sc) in enumerate(chosen):
                cat = ShortsGenerator.MOMENT_CATEGORIES[idx % len(ShortsGenerator.MOMENT_CATEGORIES)]
                results.append({
                    "index": idx + 1,
                    "title": f"Top Moment #{idx + 1}",
                    "category": cat,
                    "start_seconds": round(st, 1),
                    "duration_seconds": round(en - st, 1),
                    "end_seconds": round(en, 1),
                    "time_range": f"{ShortsGenerator.format_timestamp(st)} - {ShortsGenerator.format_timestamp(en)}",
                    "score": round(sc, 3)
                })
            return results
        except Exception as e:
            logger.warning(f"Error in _detect_via_audio: {e}")
            return []

    @staticmethod
    def _calculate_narrative_moments(
        duration_seconds: float,
        num_moments: int,
        moment_duration: float
    ) -> List[Dict[str, Any]]:
        dur = max(duration_seconds, moment_duration)
        if dur <= moment_duration:
            return [{
                "index": 1,
                "title": "Top Moment #1",
                "category": ShortsGenerator.MOMENT_CATEGORIES[0],
                "start_seconds": 0.0,
                "duration_seconds": round(dur, 1),
                "end_seconds": round(dur, 1),
                "time_range": f"00:00 - {ShortsGenerator.format_timestamp(dur)}",
                "score": 1.0
            }]

        results = []
        usable = dur - moment_duration
        step = usable / (num_moments + 1)
        for i in range(num_moments):
            start = round(step * (i + 1), 1)
            end = round(start + moment_duration, 1)
            cat = ShortsGenerator.MOMENT_CATEGORIES[i % len(ShortsGenerator.MOMENT_CATEGORIES)]
            results.append({
                "index": i + 1,
                "title": f"Top Moment #{i + 1}",
                "category": cat,
                "start_seconds": start,
                "duration_seconds": moment_duration,
                "end_seconds": end,
                "time_range": f"{ShortsGenerator.format_timestamp(start)} - {ShortsGenerator.format_timestamp(end)}",
                "score": round(0.95 - (i * 0.05), 2)
            })
        return results

    @staticmethod
    def create_vertical_short(
        input_video: Path,
        output_path: Path,
        start_seconds: float = 0.0,
        duration_seconds: float = 45.0,
        aspect_ratio: str = "9:16",
    ) -> Path:
        """
        Renders a 9:16 vertical Instagram Reel / YouTube Short (1080x1920)
        with blurred aesthetic ambient wings and centered crisp 16:9 video.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if aspect_ratio == "9:16":
            filter_complex = (
                "[0:v]split=2[bg][fg];"
                "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[blurred];"
                "[fg]scale=1080:-2:force_original_aspect_ratio=decrease[scaled];"
                "[blurred][scaled]overlay=(W-w)/2:(H-h)/2"
            )
        else:
            filter_complex = "scale=1920:1080:force_original_aspect_ratio=decrease"

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_seconds),
            "-t", str(duration_seconds),
            "-i", str(input_video),
            "-filter_complex", filter_complex,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path)
        ]
        try:
            logger.info(f"Generating 9:16 vertical short: start={start_seconds}s, dur={duration_seconds}s -> {output_path.name}")
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg vertical short failed: {e.stderr.decode('utf-8', errors='ignore')}")
            cmd_fallback = [
                "ffmpeg", "-y",
                "-ss", str(start_seconds),
                "-t", str(duration_seconds),
                "-i", str(input_video),
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac",
                str(output_path)
            ]
            subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return output_path


# ============================================================================
# Step 1: Audio Extraction & Demixing (Vocal/Music Separation)
# ============================================================================

class AudioDemixer:
    """
    Extracts audio from video and separates it into vocals (English narration)
    and background accompaniment (BGM + sound effects) using Demucs.
    Uses a semaphore to throttle concurrent Demucs instances, preventing OOM spikes
    while allowing Whisper, TTS, and FFmpeg remuxing to run concurrently across parts.
    """
    _demux_semaphore: Optional[threading.Semaphore] = None

    @classmethod
    def get_demux_semaphore(cls) -> threading.Semaphore:
        if cls._demux_semaphore is None:
            ram_gb = HardwareAccelerationManager.get_effective_ram_gb()
            # Demucs uses ~2.8-3.5GB per process. Allow 2 concurrent separations only if RAM >= 16GB, else 1 to guarantee zero OOM.
            max_concurrent = 2 if ram_gb >= 16.0 else 1
            cls._demux_semaphore = threading.Semaphore(max_concurrent)
            logger.info(f"Demucs audio separation concurrency gate initialized: max {max_concurrent} concurrent process(es) (RAM: {ram_gb:.1f} GB)")
        return cls._demux_semaphore

    def __init__(self, device: Optional[str] = None):
        self.device = device or AppleSiliconManager.get_torch_device()

    def extract_audio(self, video_path: Path, output_audio_path: Path) -> Path:
        """Extracts 44.1kHz stereo WAV from the input video via FFmpeg."""
        logger.info(f"Extracting source audio from {video_path.name}...")
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            str(output_audio_path)
        ]
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info(f"Source audio extracted to: {output_audio_path}")
            return output_audio_path
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg extraction failed: {e.stderr.decode('utf-8', errors='ignore')}")
            raise RuntimeError(f"Failed to extract audio from video: {e}")

    def separate_audio(
        self,
        audio_path: Path,
        output_dir: Path,
        model_name: str = "htdemucs"
    ) -> Tuple[Path, Path]:
        """
        Separates audio into vocals and background (accompaniment) using Demucs.
        
        Returns:
            Tuple[Path, Path]: (vocals_path, background_path)
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        device_flag = self.device if self.device in ["mps", "cpu", "cuda"] else "cpu"
        cmd = [
            sys.executable, "-m", "demucs.separate",
            "-n", model_name,
            "--two-stems", "vocals",
            "-o", str(output_dir),
            "-d", device_flag,
            str(audio_path)
        ]

        sem = self.get_demux_semaphore()
        logger.info(f"Pipelining Demucs separation for {audio_path.name} (waiting for separation slot)...")
        try:
            with sem:
                logger.info(f"Acquired Demucs slot. Separating audio with Demucs (model='{model_name}', device='{device_flag}')...")
                result = None
                for attempt in range(2):
                    try:
                        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        if result.returncode == 0:
                            break
                        if device_flag == "mps" and attempt == 0:
                            logger.warning("MPS demixing encountered an issue. Retrying with high-performance CPU mode...")
                            cmd[cmd.index("-d") + 1] = "cpu"
                            device_flag = "cpu"
                            continue
                        logger.warning(f"Demucs attempt {attempt + 1} exited with code {result.returncode}. Retrying after memory purge...")
                        gc.collect()
                        time.sleep(2)
                    except Exception as ex:
                        if attempt == 1:
                            raise
                        time.sleep(2)

                if result is None or result.returncode != 0:
                    err_tail = result.stderr[-400:] if result and result.stderr else "Unknown error"
                    raise RuntimeError(f"Demucs separation failed: {err_tail}")

                # Demucs organizes files as: output_dir / model_name / audio_stem / vocals.wav & no_vocals.wav
                stem_name = audio_path.stem
                demucs_track_dir = output_dir / model_name / stem_name
                
                raw_vocals = demucs_track_dir / "vocals.wav"
                raw_no_vocals = demucs_track_dir / "no_vocals.wav"

                if not raw_vocals.exists() or not raw_no_vocals.exists():
                    # Check for alternative stem names
                    possible_vocals = list(demucs_track_dir.glob("*vocals*.wav"))
                    if not possible_vocals:
                        raise FileNotFoundError(f"Demucs outputs not found in {demucs_track_dir}")
                    raw_vocals = possible_vocals[0]
                    raw_no_vocals = [f for f in demucs_track_dir.glob("*.wav") if f != raw_vocals][0]

                # Standardize destination paths
                final_vocals = output_dir / "vocals.wav"
                final_background = output_dir / "background.wav"

                shutil.copyfile(raw_vocals, final_vocals)
                shutil.copyfile(raw_no_vocals, final_background)

                logger.info(f"Audio demixing successful:\n - Vocals: {final_vocals}\n - Background: {final_background}")
                return final_vocals, final_background
        except Exception as e:
            logger.error(f"Error during audio separation: {e}")
            raise


# ============================================================================
# Step 2: Timed Transcription (English)
# ============================================================================

class TimedTranscriber:
    """
    Transcribes English vocals into timed segments using faster-whisper.
    Returns: List[Dict] with 'start', 'end', and 'text'.
    """

    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self.config = AppleSiliconManager.get_whisper_config()
        self.model = None
        self._lock = threading.Lock()

    @staticmethod
    def _preload_cuda_libraries():
        """Preloads nvidia-cublas and nvidia-cudnn shared libraries into the process so CTranslate2 can resolve them."""
        try:
            import ctypes
            import site
            sp_list = site.getsitepackages() if hasattr(site, "getsitepackages") else []
            lib_dirs = []
            for sp in sp_list:
                for sub in ["nvidia/cublas/lib", "nvidia/cudnn/lib"]:
                    target = os.path.join(sp, sub)
                    if os.path.isdir(target):
                        lib_dirs.append(target)
            
            if lib_dirs:
                current_ld = os.environ.get("LD_LIBRARY_PATH", "")
                added = ":".join(lib_dirs)
                os.environ["LD_LIBRARY_PATH"] = f"{added}:{current_ld}".strip(":")
            
            for ldir in lib_dirs:
                for fname in os.listdir(ldir):
                    if fname.endswith(".so") or ".so." in fname:
                        try:
                            ctypes.CDLL(os.path.join(ldir, fname), mode=ctypes.RTLD_GLOBAL)
                        except Exception:
                            pass
        except Exception:
            pass

    def load_model(self):
        """Lazy load faster-whisper model in a thread-safe manner."""
        if self.model is None:
            with self._lock:
                if self.model is None:
                    if self.config.get("device") == "cuda":
                        self._preload_cuda_libraries()
                    try:
                        from faster_whisper import WhisperModel
                        logger.info(f"Loading faster-whisper model '{self.model_size}' (device={self.config['device']}, compute_type={self.config['compute_type']})...")
                        self.model = WhisperModel(
                            self.model_size,
                            device=self.config["device"],
                            compute_type=self.config["compute_type"],
                            cpu_threads=self.config["cpu_threads"]
                        )
                    except Exception as e:
                        if self.config.get("device") == "cuda" and ("cublas" in str(e).lower() or "cuda" in str(e).lower()):
                            logger.warning(f"CUDA initialization for Whisper failed ({e}). Falling back to CPU mode...")
                            self.config["device"] = "cpu"
                            self.config["compute_type"] = "int8"
                            from faster_whisper import WhisperModel
                            self.model = WhisperModel(
                                self.model_size,
                                device="cpu",
                                compute_type="int8",
                                cpu_threads=self.config.get("cpu_threads", 4)
                            )
                        else:
                            logger.error(f"Failed to load faster-whisper: {e}")
                            raise

    def transcribe(self, vocals_path: Path) -> List[Dict[str, Any]]:
        """
        Transcribes the isolated vocals file.
        
        Returns:
            List[Dict[str, Any]]: List of segment dicts with 'start', 'end', and 'text'.
        """
        self.load_model()
        logger.info(f"Transcribing vocals from: {vocals_path}...")
        
        try:
            segments_generator, info = self.model.transcribe(
                str(vocals_path),
                beam_size=5,
                language="en",
                vad_filter=True,  # Voice activity detection trims silence
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")

            results = []
            for seg in segments_generator:
                text = seg.text.strip()
                if not text:
                    continue
                segment_dict = {
                    "start": round(float(seg.start), 3),
                    "end": round(float(seg.end), 3),
                    "text": text,
                }
                results.append(segment_dict)
                logger.debug(f"[{segment_dict['start']}s -> {segment_dict['end']}s]: {segment_dict['text']}")

            logger.info(f"Transcription complete: extracted {len(results)} timed speech segments.")
            return results

        except Exception as e:
            err_str = str(e).lower()
            if self.config.get("device") == "cuda" and ("cublas" in err_str or "cuda" in err_str or "library" in err_str):
                logger.warning(f"Whisper CUDA transcription failed ({e}). Retrying with CPU fallback...")
                try:
                    from faster_whisper import WhisperModel
                    self.config["device"] = "cpu"
                    self.config["compute_type"] = "int8"
                    self.model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=self.config.get("cpu_threads", 4)
                    )
                    segments_generator, info = self.model.transcribe(
                        str(vocals_path),
                        beam_size=5,
                        language="en",
                        vad_filter=True,
                        vad_parameters=dict(min_silence_duration_ms=500),
                    )
                    results = []
                    for seg in segments_generator:
                        text = seg.text.strip()
                        if not text:
                            continue
                        segment_dict = {
                            "start": round(float(seg.start), 3),
                            "end": round(float(seg.end), 3),
                            "text": text,
                        }
                        results.append(segment_dict)
                    logger.info(f"CPU Fallback transcription complete: extracted {len(results)} speech segments.")
                    return results
                except Exception as cpu_e:
                    logger.error(f"CPU Fallback transcription also failed: {cpu_e}")
                    raise
            logger.error(f"Transcription failed: {e}")
            raise


# ============================================================================
# Step 3: Text Translation (English to Spanish)
# ============================================================================

class SegmentTranslator:
    """
    Translates transcript segments from source to target language while preserving
    exact start and end timing.
    Supports:
    - 'deep-translator' (Fast, lightweight Google Translate engine - 100+ languages including Tamil, Telugu, Bengali)
    - 'helsinki-nlp' (Offline HuggingFace MarianMT model)
    """

    MYMEMORY_LANG_MAP = {
        "es": "es-ES", "de": "de-DE", "fr": "fr-FR", "id": "id-ID",
        "ta": "ta-IN", "te": "te-IN", "bn": "bn-IN", "hi": "hi-IN",
        "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN", "pt": "pt-BR",
        "vi": "vi-VN", "ar": "ar-SA", "ru": "ru-RU", "ja": "ja-JP"
    }

    def __init__(self, engine: str = "deep-translator", target_lang: str = "es", device: Optional[str] = None):
        self.engine = engine.lower()
        self.target_lang = target_lang.lower()
        self.device = device or AppleSiliconManager.get_torch_device()
        self._hf_model = None
        self._hf_tokenizer = None

    def _init_hf_model(self):
        if self._hf_model is None or self._hf_tokenizer is None:
            from transformers import MarianMTModel, MarianTokenizer
            model_name = f"Helsinki-NLP/opus-mt-en-{self.target_lang}"
            logger.info(f"Loading local HuggingFace translation model: {model_name}...")
            self._hf_tokenizer = MarianTokenizer.from_pretrained(model_name)
            model = MarianMTModel.from_pretrained(model_name)
            if self.device in ["cuda", "mps"]:
                try:
                    model = model.to(self.device)
                    logger.info(f"MarianMT model accelerated on {self.device.upper()} GPU.")
                except Exception as e:
                    logger.warning(f"Could not move MarianMT to {self.device}: {e}")
            self._hf_model = model

    def _translate_hf(self, text: str) -> str:
        self._init_hf_model()
        inputs = self._hf_tokenizer(text, return_tensors="pt")
        if self.device in ["cuda", "mps"]:
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
        outputs = self._hf_model.generate(**inputs)
        return self._hf_tokenizer.decode(outputs[0], skip_special_tokens=True)

    def _translate_hf_batch(self, texts: List[str]) -> List[str]:
        if not texts:
            return []
        self._init_hf_model()
        try:
            inputs = self._hf_tokenizer(texts, return_tensors="pt", padding=True, truncation=True)
            if self.device in ["cuda", "mps"]:
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
            outputs = self._hf_model.generate(**inputs)
            return [self._hf_tokenizer.decode(t, skip_special_tokens=True) for t in outputs]
        except Exception as e:
            logger.warning(f"Batch MarianMT error ({e}), falling back to single translation...")
            return [self._translate_hf(t) for t in texts]

    def _translate_single(self, en_text: str, translator) -> str:
        """Translates a single string with multi-tier fallback."""
        if not en_text:
            return ""

        # 1. If explicit helsinki-nlp requested
        if self.engine == "helsinki-nlp":
            try:
                return self._translate_hf(en_text)
            except Exception as e:
                logger.warning(f"MarianMT translation failed for '{en_text[:30]}...': {e}")

        # 2. Try GoogleTranslator
        if translator:
            try:
                res = translator.translate(en_text)
                if res and res.strip() and res.strip().lower() != en_text.strip().lower():
                    return res.strip()
            except Exception as e:
                logger.debug(f"GoogleTranslator error: {e}. Trying fallback...")

        # 3. Fallback to local HuggingFace MarianMT (fast, offline)
        try:
            res = self._translate_hf(en_text)
            if res and res.strip() and res.strip().lower() != en_text.strip().lower():
                return res.strip()
        except Exception:
            pass

        # 4. Fallback to MyMemoryTranslator
        try:
            from deep_translator import MyMemoryTranslator
            tag = self.MYMEMORY_LANG_MAP.get(self.target_lang, self.target_lang)
            res = MyMemoryTranslator(source="en-US", target=tag).translate(en_text)
            if res and res.strip() and res.strip().lower() != en_text.strip().lower():
                return res.strip()
        except Exception:
            pass

        # Return original text if all translation methods fail
        return en_text

    def translate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Translates a list of segment dictionaries.
        Each returned segment contains: 'start', 'end', 'original_text', and 'text' (translated).
        Accelerated via batch processing on GPU when MarianMT is used.
        """
        logger.info(f"Translating {len(segments)} segments to '{self.target_lang}' using engine: '{self.engine}'...")
        if not segments:
            return []

        # If helsinki-nlp or local model preferred, run super-fast GPU batch translation
        if self.engine == "helsinki-nlp":
            texts = [s["text"].strip() for s in segments]
            batch_size = 32
            translated_all = []
            for b_start in range(0, len(texts), batch_size):
                b_texts = texts[b_start:b_start + batch_size]
                translated_all.extend(self._translate_hf_batch(b_texts))

            translated_segments = []
            translated_count = 0
            for s, orig, trans in zip(segments, texts, translated_all):
                t_clean = trans.strip() if trans else orig
                if t_clean and t_clean.lower() != orig.lower():
                    translated_count += 1
                translated_segments.append({
                    "start": s["start"],
                    "end": s["end"],
                    "original_text": orig,
                    "text": t_clean,
                })
            success_rate = (translated_count / len(segments) * 100) if segments else 0
            logger.info(f"GPU Translation complete: {translated_count}/{len(segments)} ({success_rate:.1f}%) segments translated to '{self.target_lang}'.")
            return translated_segments

        translated_segments = []
        translator = None
        if self.engine == "deep-translator":
            try:
                from deep_translator import GoogleTranslator
                translator = GoogleTranslator(source="en", target=self.target_lang)
            except ImportError:
                logger.warning("deep-translator not found. Falling back to local MarianMT model.")
                self.engine = "helsinki-nlp"

        consecutive_errors = 0
        translated_count = 0
        for idx, seg in enumerate(segments, 1):
            en_text = seg["text"].strip()
            if not en_text:
                translated_segments.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "original_text": "",
                    "text": "",
                })
                continue

            # If GoogleTranslator had multiple failures (e.g. rate limit), switch remaining to fast batch MarianMT
            if consecutive_errors >= 3:
                logger.info("GoogleTranslator rate limited. Switching remaining segments to fast GPU MarianMT...")
                remaining_segments = segments[idx - 1:]
                remaining_texts = [s["text"].strip() for s in remaining_segments]
                batch_size = 32
                trans_rem = []
                for b in range(0, len(remaining_texts), batch_size):
                    trans_rem.extend(self._translate_hf_batch(remaining_texts[b:b + batch_size]))
                for s, orig, trans in zip(remaining_segments, remaining_texts, trans_rem):
                    t_clean = trans.strip() if trans else orig
                    if t_clean and t_clean.lower() != orig.lower():
                        translated_count += 1
                    translated_segments.append({
                        "start": s["start"],
                        "end": s["end"],
                        "original_text": orig,
                        "text": t_clean,
                    })
                break

            translated_text = self._translate_single(en_text, translator)
            if translated_text and translated_text.lower() != en_text.lower():
                translated_count += 1
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                logger.warning(f"Segment {idx} could not be translated. Kept original: '{en_text}'")

            new_seg = {
                "start": seg["start"],
                "end": seg["end"],
                "original_text": en_text,
                "text": translated_text,
            }
            translated_segments.append(new_seg)

        success_rate = (translated_count / len(segments) * 100) if segments else 0
        logger.info(f"Translation complete: {translated_count}/{len(segments)} ({success_rate:.1f}%) segments translated to '{self.target_lang}'.")
        return translated_segments


# ============================================================================
# Step 4: Timestamp-Aware Text-to-Speech (Spanish) & Timeline Alignment
# ============================================================================

DEFAULT_LANGUAGE_VOICES: Dict[str, str] = {
    "es": "es-ES-AlvaroNeural",
    "de": "de-DE-ConradNeural",
    "fr": "fr-FR-HenriNeural",
    "id": "id-ID-ArdiNeural",
    "ta": "ta-IN-ValluvarNeural",
    "te": "te-IN-MohanNeural",
    "bn": "bn-IN-BashkarNeural",
    "hi": "hi-IN-MadhurNeural",
    "kn": "kn-IN-GaganNeural",
    "ml": "ml-IN-MidhunNeural",
    "mr": "mr-IN-ManoharNeural",
    "pt": "pt-BR-AntonioNeural",
    "vi": "vi-VN-NamMinhNeural",
    "ar": "ar-SA-HamedNeural",
    "ru": "ru-RU-DmitryNeural",
    "ja": "ja-JP-KeitaNeural",
}

LANGUAGE_NAMES: Dict[str, str] = {
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "id": "Indonesian",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "hi": "Hindi",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "pt": "Portuguese",
    "vi": "Vietnamese",
    "ar": "Arabic",
    "ru": "Russian",
    "ja": "Japanese",
}

DEFAULT_LANGUAGE_FEMALE_VOICES: Dict[str, str] = {
    "es": "es-ES-ElviraNeural",
    "de": "de-DE-KatjaNeural",
    "fr": "fr-FR-DeniseNeural",
    "id": "id-ID-GadisNeural",
    "ta": "ta-IN-PallaviNeural",
    "te": "te-IN-ShrutiNeural",
    "bn": "bn-IN-TanishaaNeural",
    "hi": "hi-IN-SwaraNeural",
    "kn": "kn-IN-SapnaNeural",
    "ml": "ml-IN-SobhanaNeural",
    "mr": "mr-IN-AarohiNeural",
    "pt": "pt-BR-FranciscaNeural",
    "vi": "vi-VN-HoaiMyNeural",
    "ar": "ar-EG-SalmaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ja": "ja-JP-NanamiNeural",
}

def resolve_voice(target_lang: str, gender: Optional[str] = None) -> str:
    lang = target_lang.lower()
    if gender and gender.lower() == "female":
        return DEFAULT_LANGUAGE_FEMALE_VOICES.get(lang, DEFAULT_LANGUAGE_VOICES.get(lang, "es-ES-ElviraNeural"))
    return DEFAULT_LANGUAGE_VOICES.get(lang, "es-ES-AlvaroNeural")


class TimestampAwareTTS:
    """
    Generates voiceover chunks for each translated segment and aligns
    them along a master audio timeline matching original video pacing.
    
    Engines:
    - 'edge-tts': High-performance neural narration (e.g., 'de-DE-ConradNeural', 'fr-FR-HenriNeural', 'id-ID-ArdiNeural')
    - 'xtts': Coqui XTTS-v2 for zero-shot voice cloning using 'vocals.wav'
    """

    def __init__(
        self,
        engine: str = "edge-tts",
        target_lang: str = "es",
        voice_clone: bool = False,
        voice_name: Optional[str] = None,
        voice_gender: Optional[str] = None,
        device: Optional[str] = None,
        speed_cap: float = 1.15
    ):
        self.engine = engine.lower()
        self.target_lang = target_lang.lower()
        self.voice_clone = voice_clone
        self.voice_gender = voice_gender
        self.voice_name = voice_name or resolve_voice(self.target_lang, voice_gender)
        self.device = device or AppleSiliconManager.get_torch_device()
        self.speed_cap = max(1.0, min(float(speed_cap), 1.5))
        self._xtts_model = None

    def _init_xtts(self):
        if self._xtts_model is None:
            try:
                from TTS.api import TTS
                logger.info(f"Loading Coqui XTTS-v2 for voice cloning on {self.device}...")
                self._xtts_model = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=(self.device in ["mps", "cuda"]))
            except Exception as e:
                logger.warning(f"Failed to load Coqui XTTS ({e}). Falling back to neural edge-tts.")
                self.voice_clone = False
                self.engine = "edge-tts"

    def _generate_chunk_edge_tts(self, text: str, output_path: Path):
        """Asynchronously synthesizes speech via edge-tts."""
        import edge_tts
        communicate = edge_tts.Communicate(text=text, voice=self.voice_name)
        asyncio.run(communicate.save(str(output_path)))

    def _generate_chunk_xtts(self, text: str, ref_wav: Path, output_path: Path):
        """Generates cloned voice using Coqui XTTS-v2."""
        xtts_lang = self.target_lang if self.target_lang in [
            "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi"
        ] else "en"
        self._xtts_model.tts_to_file(
            text=text,
            speaker_wav=str(ref_wav),
            language=xtts_lang,
            file_path=str(output_path)
        )

    @staticmethod
    def get_audio_duration(file_path: Path) -> float:
        """Retrieves exact duration in seconds of an audio file using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
            return float(res.stdout.strip())
        except Exception:
            return 0.0

    @staticmethod
    def time_stretch_audio(input_wav: Path, output_wav: Path, speed_factor: float, max_speed: float = 1.15):
        """
        Adjusts playback speed of an audio chunk using FFmpeg 'atempo' filter
        without changing pitch, capped at max_speed to prevent rushed or unnatural speech.
        """
        speed_factor = max(0.65, min(speed_factor, max_speed))
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_wav),
            "-filter:a", f"atempo={speed_factor:.3f}",
            "-vn",
            str(output_wav)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    def generate_and_align(
        self,
        segments: List[Dict[str, Any]],
        reference_vocals_path: Optional[Path],
        output_spanish_vocals: Path,
        total_duration: float,
        temp_dir: Path,
        auto_speed_adjust: bool = True,
        speed_cap: Optional[float] = None
    ) -> Path:
        """
        Synthesizes Spanish audio for each segment, places each chunk at its exact
        start timestamp on a silent timeline buffer, and saves 'spanish_vocals.wav'.
        """
        cap = float(speed_cap) if speed_cap is not None else self.speed_cap
        logger.info(f"Generating TTS chunks for {len(segments)} segments (speed_cap={cap:.2f}x)...")
        temp_dir.mkdir(parents=True, exist_ok=True)
        chunks_dir = temp_dir / "tts_chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        if self.voice_clone and reference_vocals_path and reference_vocals_path.exists():
            self._init_xtts()

        def _process_single_tts_task(task_args) -> Optional[Tuple[int, float, Path]]:
            i, seg = task_args
            start = seg["start"]
            end = seg["end"]
            target_duration = max(end - start, 0.2)
            es_text = seg["text"].strip()
            if not es_text:
                return None

            raw_chunk_path = chunks_dir / f"chunk_{i:04d}_raw.wav"
            aligned_chunk_path = chunks_dir / f"chunk_{i:04d}_aligned.wav"

            try:
                if self.voice_clone and self._xtts_model is not None and reference_vocals_path:
                    self._generate_chunk_xtts(es_text, reference_vocals_path, raw_chunk_path)
                else:
                    self._generate_chunk_edge_tts(es_text, raw_chunk_path)

                # Measure generated audio duration
                chunk_duration = self.get_audio_duration(raw_chunk_path)

                # Time stretch if translated sentence is longer than original English duration
                if auto_speed_adjust and chunk_duration > target_duration and target_duration > 0.5:
                    speed_factor = chunk_duration / target_duration
                    if speed_factor > 1.05:
                        clamped_speed = min(speed_factor, cap)
                        self.time_stretch_audio(raw_chunk_path, aligned_chunk_path, clamped_speed, max_speed=cap)
                    else:
                        shutil.copyfile(raw_chunk_path, aligned_chunk_path)
                else:
                    shutil.copyfile(raw_chunk_path, aligned_chunk_path)

                return (i, start, aligned_chunk_path)

            except Exception as e:
                logger.error(f"Error synthesizing segment {i} ('{es_text}'): {e}")
                return None

        tts_tasks = [(i, seg) for i, seg in enumerate(segments)]
        concurrency = 1 if (self.voice_clone and self._xtts_model is not None) else 8
        results_map: Dict[int, Tuple[float, Path]] = {}

        if concurrency > 1 and len(tts_tasks) > 1:
            logger.info(f"Synthesizing {len(tts_tasks)} audio segments in parallel ({concurrency} concurrent streams)...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(_process_single_tts_task, t) for t in tts_tasks]
                for fut in concurrent.futures.as_completed(futures):
                    res = fut.result()
                    if res:
                        idx, start, path = res
                        results_map[idx] = (start, path)
        else:
            for t in tts_tasks:
                res = _process_single_tts_task(t)
                if res:
                    idx, start, path = res
                    results_map[idx] = (start, path)

        processed_chunks: List[Tuple[float, Path]] = [results_map[i] for i in range(len(segments)) if i in results_map]

        # Build timeline using FFmpeg amix / adelay or high-precision Python WAV stitching
        logger.info("Assembling chunks onto high-precision master timeline...")
        self._stitch_timeline(processed_chunks, total_duration, output_spanish_vocals)
        
        logger.info(f"Vocals generated and aligned: {output_spanish_vocals}")
        return output_spanish_vocals

    def _stitch_timeline(
        self,
        chunks: List[Tuple[float, Path]],
        total_duration: float,
        output_file: Path
    ):
        """
        Places each WAV chunk onto a master timeline array initialized with silence.
        Handles sample-level accuracy (44.1kHz, 16-bit, stereo) and ensures sequential chunks
        do not overlap or talk over each other if a previous chunk runs slightly long.
        """
        import numpy as np
        import soundfile as sf

        sample_rate = 44100
        target_total_samples = int(total_duration * sample_rate) if total_duration and total_duration > 0 else 0
        allocated_samples = max(target_total_samples, int((total_duration + 5.0) * sample_rate) if total_duration else int(30 * sample_rate))
        # 2-channel stereo timeline
        master_timeline = np.zeros((allocated_samples, 2), dtype=np.float32)

        last_end_sample = 0
        min_gap_samples = int(0.06 * sample_rate)  # 60ms natural separation gap between phrases

        for start_sec, chunk_path in chunks:
            if not chunk_path.exists():
                continue
            data, sr = sf.read(str(chunk_path))
            
            # Resample if sample rate differs
            if sr != sample_rate:
                import scipy.signal
                num_samples = int(len(data) * float(sample_rate) / sr)
                data = scipy.signal.resample(data, num_samples)

            # Convert mono to stereo if necessary
            if data.ndim == 1:
                data = np.column_stack((data, data))

            target_start_sample = int(start_sec * sample_rate)
            # Ensure chunk doesn't overlap previous chunk if previous chunk ran slightly over
            start_sample = max(target_start_sample, last_end_sample + min_gap_samples)
            end_sample = start_sample + len(data)
            last_end_sample = end_sample

            if end_sample > master_timeline.shape[0]:
                # Expand master timeline if needed
                pad_size = end_sample - master_timeline.shape[0]
                master_timeline = np.pad(master_timeline, ((0, pad_size), (0, 0)), mode="constant")

            # Overlay chunk onto master timeline
            master_timeline[start_sample:end_sample] += data

        # If total_duration was provided, clamp or pad exact duration so chunk audio matches video part duration perfectly
        if target_total_samples > 0:
            if master_timeline.shape[0] > target_total_samples:
                master_timeline = master_timeline[:target_total_samples]
            elif master_timeline.shape[0] < target_total_samples:
                pad_size = target_total_samples - master_timeline.shape[0]
                master_timeline = np.pad(master_timeline, ((0, pad_size), (0, 0)), mode="constant")

        # Normalize audio to prevent clipping (-1.0 to 1.0)
        max_val = np.max(np.abs(master_timeline))
        if max_val > 1.0:
            master_timeline /= max_val

        output_file.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_file), master_timeline, sample_rate, subtype="PCM_16")


# ============================================================================
# Step 5: Audio Re-muxing and Video Export via FFmpeg
# ============================================================================

class VideoRemuxer:
    """
    Mixes vocals with isolated background audio (BGM/SFX) and
    stitches the mixed audio back into the video stream with universal web and player compatibility.
    """

    @staticmethod
    def get_video_codec(video_path: Path) -> str:
        """Probes video codec name (e.g. 'h264', 'vp9', 'av1') using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
            return res.stdout.strip().lower()
        except Exception as e:
            logger.warning(f"Failed to probe video codec for {video_path}: {e}")
            return ""

    @staticmethod
    def generate_watermark_image(
        text: str,
        output_path: Path,
        font_size: int = 28,
        opacity: float = 0.40,
    ) -> Path:
        """
        Generates a semi-transparent light white PNG watermark with subtle drop shadow.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            logger.warning("Pillow not installed; skipping watermark generation.")
            return output_path

        font_candidates = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNS.ttf",
        ]
        font = None
        for candidate in font_candidates:
            if os.path.exists(candidate):
                try:
                    font = ImageFont.truetype(candidate, font_size)
                    break
                except Exception:
                    pass
        if font is None:
            font = ImageFont.load_default()

        try:
            bbox = font.getbbox(text)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except Exception:
            text_w, text_h = len(text) * int(font_size * 0.6), font_size

        pad_x, pad_y = 16, 10
        img_w = text_w + pad_x * 2
        img_h = text_h + pad_y * 2

        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        alpha = int(255 * max(0.1, min(1.0, opacity)))
        shadow_alpha = int(alpha * 0.6)

        # Soft drop shadow for legibility over white manga bubbles
        draw.text((pad_x + 1, pad_y + 1), text, font=font, fill=(0, 0, 0, shadow_alpha))
        # Light white watermark text
        draw.text((pad_x, pad_y), text, font=font, fill=(255, 255, 255, alpha))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "PNG")
        return output_path

    @staticmethod
    def remux_and_export(
        original_video: Path,
        spanish_vocals: Path,
        background_audio: Path,
        output_video: Path,
        bg_volume: float = 0.8,
        vocals_volume: float = 1.0,
        watermark_text: Optional[str] = None,
        watermark_interval: float = 3.0,
        watermark_opacity: float = 0.40,
        watermark_font_size: int = 28,
    ) -> Path:
        """
        Mixes audio tracks and exports final MP4.
        Ensures 100% universal browser and media player compatibility with H.264/AAC,
        moves MOOV atom to the front via '+faststart', and avoids amix volume halving.
        """
        logger.info(f"Mixing vocals with background audio (BGM volume={bg_volume}, Vocals volume={vocals_volume})...")
        output_video.parent.mkdir(parents=True, exist_ok=True)

        temp_mixed_audio = output_video.parent / "temp_mixed_audio.wav"
        temp_watermark_png: Optional[Path] = None

        # 1. Mix vocals and background audio with custom volume balances
        has_vocals = spanish_vocals and Path(spanish_vocals).exists() and Path(spanish_vocals).stat().st_size > 100
        has_bg = background_audio and Path(background_audio).exists() and Path(background_audio).stat().st_size > 100

        if has_vocals and has_bg:
            mix_cmd = [
                "ffmpeg", "-y",
                "-i", str(spanish_vocals),
                "-i", str(background_audio),
                "-filter_complex",
                f"[0:a]volume={vocals_volume:.2f}[v];[1:a]volume={bg_volume:.2f}[b];[v][b]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]",
                "-map", "[aout]",
                "-c:a", "pcm_s16le",
                "-ar", "44100",
                "-ac", "2",
                str(temp_mixed_audio)
            ]
        elif has_vocals:
            mix_cmd = [
                "ffmpeg", "-y",
                "-i", str(spanish_vocals),
                "-filter:a", f"volume={vocals_volume:.2f}",
                "-c:a", "pcm_s16le",
                "-ar", "44100",
                "-ac", "2",
                str(temp_mixed_audio)
            ]
        elif has_bg:
            mix_cmd = [
                "ffmpeg", "-y",
                "-i", str(background_audio),
                "-filter:a", f"volume={bg_volume:.2f}",
                "-c:a", "pcm_s16le",
                "-ar", "44100",
                "-ac", "2",
                str(temp_mixed_audio)
            ]
        else:
            mix_cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "10",
                "-c:a", "pcm_s16le",
                str(temp_mixed_audio)
            ]

        try:
            subprocess.run(mix_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            logger.info("Audio mixing completed.")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg audio mixing failed: {e.stderr.decode('utf-8', errors='ignore')}")
            raise RuntimeError(f"Audio mixing failed: {e}")

        # 2. Check source video codec to ensure 100% universal MP4 playback compatibility
        raw_codec = VideoRemuxer.get_video_codec(original_video)
        is_universal_h264 = raw_codec in ["h264", "avc1"]

        # 3. Check if watermark is requested
        if watermark_text and watermark_text.strip():
            temp_watermark_png = output_video.parent / "temp_watermark.png"
            VideoRemuxer.generate_watermark_image(
                text=watermark_text.strip(),
                output_path=temp_watermark_png,
                font_size=watermark_font_size,
                opacity=watermark_opacity
            )

            interval = max(1.0, float(watermark_interval))
            k_expr = f"floor(t/{interval})"
            x_expr = f"'30+(W-w-60)*mod(abs(sin(({k_expr}+1)*12.9898)*43758.5453),1)'"
            y_expr = f"'30+(H-h-60)*mod(abs(sin(({k_expr}+1)*78.233)*43758.5453),1)'"

            vcodec = "h264_videotoolbox" if AppleSiliconManager.get_torch_device() == "mps" else "libx264"
            logger.info(f"Applying animated light-white watermark ('{watermark_text}') jumping every {interval}s with {vcodec}...")

            remux_cmd = [
                "ffmpeg", "-y",
                "-i", str(original_video),
                "-i", str(temp_mixed_audio),
                "-loop", "1", "-i", str(temp_watermark_png),
                "-filter_complex",
                f"[0:v][2:v]overlay=x={x_expr}:y={y_expr}:shortest=1[vout]",
                "-map", "[vout]",
                "-map", "1:a:0",
                "-c:v", vcodec,
                "-preset", "veryfast",
                "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
                "-movflags", "+faststart",
                "-shortest",
                str(output_video)
            ]
        elif not is_universal_h264:
            # Video codec is VP9, AV1, HEVC, etc.
            # Blindly copying into MP4 causes missing audio/black screen in web browsers and Windows players!
            # Transcode to universally compatible H.264 (yuv420p)
            vcodec = "h264_videotoolbox" if AppleSiliconManager.get_torch_device() == "mps" else "libx264"
            logger.info(f"Source video has codec '{raw_codec or 'unknown'}'. Transcoding to standard H.264 ({vcodec}) for universal web & audio playback compatibility...")

            remux_cmd = [
                "ffmpeg", "-y",
                "-i", str(original_video),
                "-i", str(temp_mixed_audio),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", vcodec,
                "-preset", "veryfast",
                "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
                "-movflags", "+faststart",
                "-shortest",
                str(output_video)
            ]
        else:
            logger.info(f"Source video is H.264 ({raw_codec}). Stitching mixed audio into {original_video.name} using '-c:v copy'...")
            remux_cmd = [
                "ffmpeg", "-y",
                "-i", str(original_video),
                "-i", str(temp_mixed_audio),
                "-map", "0:v:0",          # Copy original video stream
                "-map", "1:a:0",          # Inject new mixed audio
                "-c:v", "copy",           # Zero quality loss, near-instant copy
                "-c:a", "aac",            # Standard high-compatibility audio codec
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
                "-movflags", "+faststart",
                "-shortest",              # Match duration
                str(output_video)
            ]

        try:
            subprocess.run(remux_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            logger.info(f"Video export complete! Dubbed video saved at: {output_video}")
            return output_video
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg remuxing failed: {e.stderr.decode('utf-8', errors='ignore')}")
            raise RuntimeError(f"Video remuxing failed: {e}")
        finally:
            # Clean up temp files
            if temp_mixed_audio.exists():
                try:
                    temp_mixed_audio.unlink()
                except Exception:
                    pass
            if temp_watermark_png and temp_watermark_png.exists():
                try:
                    temp_watermark_png.unlink()
                except Exception:
                    pass


# ============================================================================
# ============================================================================
# Multilingual YouTube SEO Metadata & Thumbnail Generator
# ============================================================================

LANGUAGE_SEO_CONFIG: Dict[str, Dict[str, str]] = {
    "de": {
        "name": "German",
        "native": "Deutsch",
        "badge": "AUF DEUTSCH",
        "suffix": "| Manhwa Recap Deutsch",
        "hook": "ICH BIN JETZT DER BOSS!",
        "hashtags": "#ManhwaRecapDeutsch #ManhwaDeutsch #ManhwaZusammenfassung #MangaDeutsch #Wiedergeburt",
        "cta": "🔔 Abonniere den Kanal für tägliche Manhwa-Recaps auf Deutsch! 👍 Lass ein Like da!",
        "tags": "manhwa recap deutsch, manhwa zusammenfassung deutsch, manhwa auf deutsch, manhwa recap, manhwa deutsch erklärt, wiedergeburt manhwa, isekai manhwa deutsch, manga recap deutsch, anime recap deutsch",
    },
    "es": {
        "name": "Spanish",
        "native": "Español",
        "badge": "EN ESPAÑOL",
        "suffix": "| Manhwa Recap Español",
        "hook": "¡AHORA SOY EL JEFE!",
        "hashtags": "#ManhwaRecapEspañol #ResumenManhwa #ManhwaEspañol #MangaEspañol #Reencarnacion",
        "cta": "🔔 ¡Suscríbete al canal para ver resúmenes diarios de manhwa en español! 👍 ¡Deja tu like!",
        "tags": "manhwa recap español, resumen manhwa español, manhwa en español, resumen de manhwa, manhwa español latino, reencarnacion manhwa, manga recap español, anime resumen español",
    },
    "fr": {
        "name": "French",
        "native": "Français",
        "badge": "EN FRANÇAIS",
        "suffix": "| Manhwa Recap Français",
        "hook": "JE SUIS LE BOSS MAINTENANT!",
        "hashtags": "#ManhwaRecapFR #ManhwaFrancais #ResumeManhwa #MangaFR #Reincarnation",
        "cta": "🔔 Abonne-toi pour des résumés quotidiens de manhwa en français ! 👍 Laisse un like !",
        "tags": "manhwa recap francais, resume manhwa francais, manhwa en francais, manga recap fr, anime resume fr, webtoon fr, reincarnation manhwa francais",
    },
    "id": {
        "name": "Indonesian",
        "native": "Bahasa Indonesia",
        "badge": "BAHASA INDONESIA",
        "suffix": "| Alur Cerita Manhwa",
        "hook": "SEKARANG AKU BOSNYA!",
        "hashtags": "#AlurCeritaManhwa #ManhwaIndonesia #ReviewManhwa #KomikManhwa #Reinkarnasi",
        "cta": "🔔 Subscribe untuk alur cerita manhwa terbaru setiap hari! 👍 Jangan lupa like!",
        "tags": "alur cerita manhwa, manhwa sub indo, alur cerita komik, review manhwa indonesia, reinkarnasi manhwa, manhwa over power, pembahasan manhwa, alur cerita manga",
    },
    "pt": {
        "name": "Portuguese",
        "native": "Português",
        "badge": "EM PORTUGUÊS",
        "suffix": "| Manhwa Recap Português",
        "hook": "AGORA EU SOU O CHEFE!",
        "hashtags": "#ManhwaRecapPT #ResumoManhwa #ManhwaBrasil #MangaRecapPT #Reencarnacao",
        "cta": "🔔 Inscreva-se no canal para resumos diários de manhwa em português! 👍 Deixe seu like!",
        "tags": "manhwa recap portugues, resumo manhwa brasil, manhwa em portugues, recap manhwa pt br, resumo de manhwa, reencarnacao manhwa, manga recap brasil",
    },
    "hi": {
        "name": "Hindi",
        "native": "हिन्दी",
        "badge": "HINDI RECAP",
        "suffix": "| Manhwa Recap Hindi",
        "hook": "AB MAIN BOSS HOON!",
        "hashtags": "#ManhwaRecapHindi #ManhwaHindi #AnimeRecapHindi #MangaHindi #Reincarnation",
        "cta": "🔔 रोज़ाना हिंदी में manhwa recap देखने के लिए चैनल को सब्सक्राइब करें! 👍 Like ज़रूर करें!",
        "tags": "manhwa recap in hindi, manhwa explained in hindi, anime recap hindi, manga recap in hindi, reincarnation manhwa hindi, manhwa in hindi",
    },
    "ta": {
        "name": "Tamil",
        "native": "தமிழ்",
        "badge": "TAMIL RECAP",
        "suffix": "| Manhwa Recap Tamil",
        "hook": "INI NAAN THAAN BOSS!",
        "hashtags": "#ManhwaRecapTamil #ManhwaTamil #AnimeRecapTamil #MangaTamil",
        "cta": "🔔 தினமும் தமிழ் manhwa recap-க்கு Subscribe பண்ணுங்க! 👍 Like பண்ண மறக்காதீங்க!",
        "tags": "manhwa recap tamil, manhwa explained in tamil, anime recap tamil, manga recap tamil, webtoon tamil",
    },
    "te": {
        "name": "Telugu",
        "native": "తెలుగు",
        "badge": "TELUGU RECAP",
        "suffix": "| Manhwa Recap Telugu",
        "hook": "IKA NENE BOSS!",
        "hashtags": "#ManhwaRecapTelugu #ManhwaTelugu #AnimeRecapTelugu #MangaTelugu",
        "cta": "🔔 రోజూ తెలుగులో manhwa recap కోసం Subscribe చేయండి! 👍 Like చేయండి!",
        "tags": "manhwa recap in telugu, manhwa explained in telugu, anime recap telugu, manga recap telugu",
    },
    "bn": {
        "name": "Bengali",
        "native": "বাংলা",
        "badge": "BENGALI RECAP",
        "suffix": "| Manhwa Recap Bangla",
        "hook": "EKHON AMI-I BOSS!",
        "hashtags": "#ManhwaRecapBangla #ManhwaBengali #AnimeRecapBangla #MangaBangla",
        "cta": "🔔 প্রতিদিন বাংলায় manhwa recap দেখতে চ্যানেলটি সাবস্ক্রাইব করুন! 👍 Like দিতে ভুলবেন না!",
        "tags": "manhwa recap bangla, manhwa explained in bengali, anime recap bangla, manga recap bangla",
    },
    "ru": {
        "name": "Russian",
        "native": "Русский",
        "badge": "НА РУССКОМ",
        "suffix": "| Манхва Краткий Пересказ",
        "hook": "ТЕПЕРЬ Я ЗДЕСЬ БОСС!",
        "hashtags": "#МанхваПересказ #МанхваНаРусском #КраткийПересказ #Перерождение #Манга",
        "cta": "🔔 Подписывайся на канал для ежедневных пересказов манхв на русском! 👍 Ставь лайк!",
        "tags": "краткий пересказ манхвы, манхва пересказ, манхва на русском, манхва рекап, перерождение манхва, манга пересказ",
    },
    "vi": {
        "name": "Vietnamese",
        "native": "Tiếng Việt",
        "badge": "TIẾNG VIỆT",
        "suffix": "| Review Truyện Tranh",
        "hook": "GIỜ TAO LÀ TRÙM!",
        "hashtags": "#ReviewTruyenTranh #TómTắtManhwa #ManhwaTiengViet #TrọngSinh",
        "cta": "🔔 Đăng ký kênh để xem review truyện tranh manhwa mỗi ngày! 👍 Nhớ bấm Like nhé!",
        "tags": "review truyen tranh, tom tat manhwa, truyen tranh manhwa, review manhwa tieng viet, trong sinh manhwa",
    },
    "ar": {
        "name": "Arabic",
        "native": "العربية",
        "badge": "بالعربية",
        "suffix": "| ملخص مانهوا بالعربية",
        "hook": "أنا الزعيم الآن!",
        "hashtags": "#ملخص_مانهوا #مانهوا_مترجمة #مانهوا_بالعربي #انمي_ملخص",
        "cta": "🔔 اشترك في القناة لمشاهدة ملخصات مانهوا يومياً بالعربية! 👍 لا تنسى اللايك!",
        "tags": "ملخص مانهوا, ملخصات مانهوا بالعربية, مانهوا مترجمة, حكاية مانهوا, تلخيص مانهوا",
    },
    "ja": {
        "name": "Japanese",
        "native": "日本語",
        "badge": "日本語",
        "suffix": "| マンガ解説・要約",
        "hook": "俺が新しいボスだ！",
        "hashtags": "#マンガ解説 #マンガ要約 #マンガ紹介 #転生マンガ #Webtoon",
        "cta": "🔔 毎日のマンガ要約・解説動画をお見逃しなく！チャンネル登録＆高評価をお願いします！",
        "tags": "マンガ解説, マンガ要約, マンガ紹介, 転生マンガ, webtoon 日本語, アニメ要約",
    },
    "kn": {
        "name": "Kannada",
        "native": "ಕನ್ನಡ",
        "badge": "KANNADA RECAP",
        "suffix": "| Manhwa Recap Kannada",
        "hook": "EEGA NANE BOSS!",
        "hashtags": "#ManhwaRecapKannada #ManhwaKannada #AnimeRecapKannada",
        "cta": "🔔 ಪ್ರತಿದಿನ ಕನ್ನಡ manhwa recap ಗಾಗಿ Subscribe ಮಾಡಿ! 👍 Like ಮಾಡಿ!",
        "tags": "manhwa recap in kannada, manhwa explained in kannada, anime recap kannada",
    },
    "ml": {
        "name": "Malayalam",
        "native": "മലയാളം",
        "badge": "MALAYALAM RECAP",
        "suffix": "| Manhwa Recap Malayalam",
        "hook": "INI NJAN BOSS!",
        "hashtags": "#ManhwaRecapMalayalam #ManhwaMalayalam #AnimeRecapMalayalam",
        "cta": "🔔 ദിവസവും മലയാളത്തിൽ manhwa recap കാണാൻ Subscribe ചെയ്യുക! 👍 Like ചെയ്യുക!",
        "tags": "manhwa recap in malayalam, manhwa explained in malayalam, anime recap malayalam",
    },
    "mr": {
        "name": "Marathi",
        "native": "मराठी",
        "badge": "MARATHI RECAP",
        "suffix": "| Manhwa Recap Marathi",
        "hook": "AATA MECH BOSS!",
        "hashtags": "#ManhwaRecapMarathi #ManhwaMarathi #AnimeRecapMarathi",
        "cta": "🔔 दररोज मराठीत manhwa recap पाहण्यासाठी Subscribe करा! 👍 Like करा!",
        "tags": "manhwa recap in marathi, manhwa explained in marathi, anime recap marathi",
    },
}


class MultilingualMetadataGenerator:
    """
    Generates high-CTR YouTube metadata (Title, Description, Tags, Hook)
    dynamically tailored for any target language.
    Supports Google Gemini API (free tier) with automated fallback to local translation & localized templates.
    """

    @staticmethod
    def generate(
        target_lang: str = "de",
        english_title: str = "",
        context_text: str = "",
        gemini_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        lang_code = (target_lang or "de").lower().strip()
        config = LANGUAGE_SEO_CONFIG.get(lang_code, {
            "name": lang_code.upper(),
            "native": lang_code.upper(),
            "badge": f"IN {lang_code.upper()}",
            "suffix": f"| Manhwa Recap {lang_code.upper()}",
            "hook": "THE BOSS IS BACK!",
            "hashtags": f"#ManhwaRecap #{lang_code.upper()}Recap #Manhwa #Anime",
            "cta": "🔔 Subscribe for daily manhwa recaps! 👍 Leave a like!",
            "tags": f"manhwa recap, manhwa recap {lang_code}, manhwa explained, manga recap",
        })
        lang_name = config["name"]
        suffix = config["suffix"]

        # 1. Try Gemini API if key is provided (or in environment)
        api_key = (gemini_api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        if api_key:
            logger.info(f"Generating {lang_name} ({lang_code}) YouTube metadata via Google Gemini API...")
            try:
                import requests
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
                prompt = f"""You are an expert YouTube automation manager specialized in Anime and Manhwa Recaps for {lang_name} audiences.
Original English Video Title: {english_title}
Story Context / Transcript Summary: {context_text[:2500]}
Target Language: {lang_name} ({lang_code})

Generate a complete high-CTR YouTube metadata package strictly in {lang_name} ({config['native']}) formatted in JSON with the following exact keys:
{{
  "title": "A high-CTR, click-worthy title in {lang_name} ending with '{suffix}' (max 95 chars)",
  "thumbnail_hook": "A short, punchy 2-4 word hook in ALL CAPS in {lang_name} for the thumbnail overlay (e.g. {config['hook']})",
  "description": "A full, engaging description in {lang_name} with synopsis, call to action (Like & Subscribe), chapter placeholders, and {lang_name} hashtags ({config['hashtags']})",
  "tags": "Comma-separated list of 15 high-ranking YouTube tags in {lang_name}"
}}
Respond ONLY with valid JSON.
"""
                resp = requests.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"response_mime_type": "application/json"}
                }, timeout=15)

                if resp.status_code == 200:
                    data = resp.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    result = json.loads(raw_text)
                    result["badge_text"] = config.get("badge", f"IN {lang_code.upper()}")
                    result["lang"] = lang_code
                    result["lang_name"] = lang_name
                    logger.info(f"Successfully generated {lang_name} metadata via Gemini API.")
                    return result
                else:
                    logger.warning(f"Gemini API returned status {resp.status_code}. Falling back to local template generator.")
            except Exception as e:
                logger.warning(f"Gemini API call failed: {e}. Falling back to local template generator.")

        # 2. Local Fallback Generator
        logger.info(f"Generating {lang_name} ({lang_code}) YouTube metadata via local translation & template engine...")
        try:
            from deep_translator import GoogleTranslator
            tr = GoogleTranslator(source="auto", target=lang_code)
            clean_en_title = english_title.replace(" | Manhwa Recap", "").replace("Manhwa Recap", "").strip()
            translated_title = tr.translate(clean_en_title)
        except Exception:
            translated_title = english_title.replace(" | Manhwa Recap", "").strip()

        t_title = translated_title.strip()
        full_title = f"{t_title} {suffix}"
        if len(full_title) > 95:
            full_title = f"{t_title[:65]}... {suffix}"

        desc = f"""{full_title}

{config['cta']}

---
📌 Chapters / Timestamps:
00:00 - Prologue
05:30 - The Reincarnation
12:45 - The Revenge Begins
20:00 - Climax & Ending

---
⚠️ Disclaimer:
This video is for entertainment and educational recap purposes under fair use. All rights belong to respective authors and artists.

{config['hashtags']}
"""
        return {
            "title": full_title,
            "thumbnail_hook": config["hook"],
            "description": desc.strip(),
            "tags": config["tags"],
            "badge_text": config.get("badge", f"IN {lang_code.upper()}"),
            "lang": lang_code,
            "lang_name": lang_name,
        }


class MultilingualThumbnailGenerator:
    """
    Renders YouTube standard 1280x720 thumbnails with localized hook text on top-left
    and a dynamic localized badge in bottom-right corner based on the selected language.
    """

    @staticmethod
    def generate_thumbnail(
        video_path: Path,
        hook_text: str,
        output_path: Path,
        lang_code: str = "de",
        base_image: Optional[Path] = None
    ) -> Path:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

        output_path.parent.mkdir(parents=True, exist_ok=True)
        bg = None

        if base_image and Path(base_image).exists():
            try:
                bg = Image.open(base_image).convert("RGBA").resize((1280, 720), Image.Resampling.LANCZOS)
            except Exception:
                bg = None

        if bg is None and video_path.exists():
            temp_frame = output_path.parent / f"temp_thumb_{lang_code}.jpg"
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-ss", "00:00:15", "-i", str(video_path),
                    "-vframes", "1", "-q:v", "2", str(temp_frame)
                ], check=True, stderr=subprocess.DEVNULL)
                if temp_frame.exists():
                    bg = Image.open(temp_frame).convert("RGBA").resize((1280, 720), Image.Resampling.LANCZOS)
                    temp_frame.unlink()
            except Exception:
                bg = None

        if bg is None:
            bg = Image.new("RGBA", (1280, 720), (14, 16, 28, 255))

        enhancer = ImageEnhance.Color(bg)
        bg = enhancer.enhance(1.22)
        enhancer = ImageEnhance.Contrast(bg)
        bg = enhancer.enhance(1.15)

        overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)
        for r in range(560, 0, -25):
            a = int(195 * (1 - r / 560))
            draw_ov.ellipse([-120 - r, -120 - r, -120 + r, -120 + r], fill=(0, 0, 0, a))
        bg = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(bg)

        # Hook Font
        font_candidates = [
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Black.ttf",
            "/System/Library/Fonts/Supplemental/Impact.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        impact_font = None
        for fc in font_candidates:
            if os.path.exists(fc):
                try:
                    impact_font = ImageFont.truetype(fc, 74)
                    break
                except Exception:
                    pass
        if impact_font is None:
            impact_font = ImageFont.load_default()

        cfg = LANGUAGE_SEO_CONFIG.get(lang_code.lower(), {})
        clean_hook = (hook_text or cfg.get("hook", "THE BOSS IS BACK!")).strip().upper()
        if "\n" in clean_hook:
            lines = [l.strip() for l in clean_hook.split("\n") if l.strip()]
        else:
            words = clean_hook.split(" ")
            if len(words) > 3 or len(clean_hook) > 18:
                mid = len(words) // 2
                lines = [" ".join(words[:mid]), " ".join(words[mid:])]
            else:
                lines = [clean_hook]

        ty = 50
        for line in lines[:2]:
            tx = 55
            for ox in range(-5, 6):
                for oy in range(-5, 6):
                    if ox*ox + oy*oy <= 30:
                        draw.text((tx + ox, ty + oy), line, font=impact_font, fill=(0, 0, 0, 255))
            for offset in range(6, 12):
                draw.text((tx + offset, ty + offset), line, font=impact_font, fill=(0, 0, 0, 210))
            draw.text((tx, ty), line, font=impact_font, fill=(255, 215, 0))
            draw.text((tx, ty - 2), line, font=impact_font, fill=(255, 245, 170))
            ty += 88

        # Dynamic Bottom-Right Badge for this language!
        badge_text = cfg.get("badge", f"IN {lang_code.upper()}").upper()
        badge_font = None
        badge_candidates = [
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Black.ttf",
            "/System/Library/Fonts/Supplemental/Impact.ttf",
        ]
        for bc in badge_candidates:
            if os.path.exists(bc):
                try:
                    badge_font = ImageFont.truetype(bc, 32)
                    break
                except Exception:
                    pass
        if badge_font is None:
            badge_font = impact_font

        bbox = badge_font.getbbox(badge_text)
        bw = (bbox[2] - bbox[0]) + 48
        bh = (bbox[3] - bbox[1]) + 26
        bx = 1280 - bw - 40
        by = 720 - bh - 35

        # Shadow
        draw.rounded_rectangle([bx + 4, by + 4, bx + bw + 4, by + bh + 4], radius=16, fill=(0, 0, 0, 180))
        # Vivid red badge
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=16, fill=(225, 29, 72, 255), outline=(255, 255, 255, 255), width=3)
        # White bold text
        draw.text((bx + 24, by + 10), badge_text, font=badge_font, fill=(255, 255, 255))

        bg.convert("RGB").save(str(output_path), quality=96)
        logger.info(f"Generated {lang_code.upper()} YouTube thumbnail (badge='{badge_text}'): {output_path}")
        return output_path


# Backward compatibility aliases
class GermanMetadataGenerator:
    @staticmethod
    def generate(english_title: str, context_text: str = "", gemini_api_key: Optional[str] = None) -> Dict[str, Any]:
        return MultilingualMetadataGenerator.generate(target_lang="de", english_title=english_title, context_text=context_text, gemini_api_key=gemini_api_key)


class GermanThumbnailGenerator:
    @staticmethod
    def generate_thumbnail(video_path: Path, hook_text: str, output_path: Path, base_image: Optional[Path] = None) -> Path:
        return MultilingualThumbnailGenerator.generate_thumbnail(video_path=video_path, hook_text=hook_text, output_path=output_path, lang_code="de", base_image=base_image)


# ============================================================================
# Master Orchestrator Pipeline
# ============================================================================

class ManhwaDubbingPipeline:
    """
    Complete end-to-end local dubbing pipeline coordinating all 5 steps.
    """

    def __init__(
        self,
        whisper_model: str = "base",
        target_lang: str = "es",
        translation_engine: str = "deep-translator",
        tts_engine: str = "edge-tts",
        tts_voice: Optional[str] = None,
        voice_gender: Optional[str] = None,
        voice_clone: bool = False,
        bg_volume: float = 0.8,
        vocals_volume: float = 1.0,
        speed_cap: float = 1.15,
        work_dir: Optional[Path] = None,
        enable_watermark: bool = False,
        watermark_text: Optional[str] = None,
        watermark_interval: float = 3.0,
        watermark_opacity: float = 0.40,
        gemini_api_key: Optional[str] = None,
    ):
        self.whisper_model = whisper_model
        self.target_lang = target_lang.lower()
        self.translation_engine = translation_engine
        self.tts_engine = tts_engine
        self.voice_gender = voice_gender
        self.tts_voice = tts_voice or resolve_voice(self.target_lang, voice_gender)
        self.voice_clone = voice_clone
        self.bg_volume = bg_volume
        self.vocals_volume = vocals_volume
        self.speed_cap = float(speed_cap)
        self.work_dir = work_dir or Path("./workspace_dubbing")
        self.enable_watermark = enable_watermark
        self.watermark_text = watermark_text
        self.watermark_interval = float(watermark_interval)
        self.watermark_opacity = float(watermark_opacity)
        self.gemini_api_key = (gemini_api_key or os.environ.get("GEMINI_API_KEY", "")).strip()

        # Initialize components
        self.device = AppleSiliconManager.get_torch_device()
        self.demixer = AudioDemixer(device=self.device)
        self.transcriber = TimedTranscriber(model_size=self.whisper_model)
        self.translator = SegmentTranslator(
            engine=self.translation_engine,
            target_lang=self.target_lang,
            device=self.device
        )
        self.tts = TimestampAwareTTS(
            engine=self.tts_engine,
            target_lang=self.target_lang,
            voice_clone=self.voice_clone,
            voice_name=self.tts_voice,
            voice_gender=self.voice_gender,
            device=self.device,
            speed_cap=self.speed_cap
        )
        self.remuxer = VideoRemuxer()
        self.CHUNK_DURATION_SECONDS: float = 600.0  # 10 minutes (600 seconds)

    @staticmethod
    def _generate_silent_audio(output_path: Path, duration_seconds: float) -> Path:
        """Generates a silent stereo WAV of duration_seconds via ffmpeg."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dur = max(0.5, float(duration_seconds))
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(dur),
            str(output_path)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return output_path

    def _process_single_chunk(
        self,
        chunk_video: Path,
        chunk_work_dir: Path,
        langs: List[str],
        report_fn: Callable[[float, str], None],
        enable_watermark: Optional[bool] = None,
        watermark_text: Optional[str] = None,
        watermark_interval: Optional[float] = None,
        watermark_opacity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Executes Steps 1 to 5 for a single 10-minute (or shorter) chunk:
        Demix audio -> Whisper transcribe -> Translate -> TTS -> Remux.
        """
        chunk_work_dir.mkdir(parents=True, exist_ok=True)
        is_multi = len(langs) > 1

        # Step 1: Audio Extraction & Demixing (Vocals vs BGM/SFX)
        report_fn(0.05, "Step 1 of 5: Extracting audio and demixing vocals from BGM/SFX...")
        extracted_audio = chunk_work_dir / "original_audio.wav"
        self.demixer.extract_audio(chunk_video, extracted_audio)

        vocals_path, bg_path = self.demixer.separate_audio(extracted_audio, chunk_work_dir)
        total_duration = self.tts.get_audio_duration(extracted_audio)
        report_fn(0.25, "Step 1 of 5 complete: Vocals and background audio separated.")

        # Step 2: Timed Transcription (Whisper)
        report_fn(0.30, "Step 2 of 5: Transcribing English vocals into timed segments...")
        segments = self.transcriber.transcribe(vocals_path)
        if not segments:
            logger.warning(f"No speech segments detected in vocals track for {chunk_video.name}.")
            segments = []

        english_transcript_file = chunk_work_dir / "english_transcript.json"
        with open(english_transcript_file, "w", encoding="utf-8") as f:
            json.dump(segments, f, indent=2, ensure_ascii=False)
        report_fn(0.50, f"Step 2 of 5 complete: {len(segments)} segments transcribed.")

        # Steps 3 to 5: Translate, Synthesize TTS, and Remux per language
        languages_result: Dict[str, Any] = {}
        total_langs = len(langs)
        lang_progress_budget = 0.48 / total_langs

        for idx, lang in enumerate(langs):
            lang_name = LANGUAGE_NAMES.get(lang, lang.capitalize())
            lang_dir = chunk_work_dir / lang_name
            lang_dir.mkdir(parents=True, exist_ok=True)

            lang_base_pct = 0.50 + idx * lang_progress_budget
            lang_label = f"[{lang_name} ({idx + 1}/{total_langs})]" if is_multi else f"[{lang_name}]"

            # Step 3: Text Translation
            report_fn(
                lang_base_pct + 0.10 * lang_progress_budget,
                f"{lang_label} Translating dialogue segments into {lang_name}..."
            )
            if segments:
                translator = SegmentTranslator(
                    engine=self.translation_engine,
                    target_lang=lang,
                    device=self.device
                )
                translated_segments = translator.translate_segments(segments)
            else:
                translated_segments = []

            lang_transcript_json = lang_dir / f"segments_{lang}.json"
            with open(lang_transcript_json, "w", encoding="utf-8") as f:
                json.dump(translated_segments, f, indent=2, ensure_ascii=False)

            # Step 4: Timestamp-Aware TTS
            if not is_multi and self.tts_voice and self.target_lang == lang:
                lang_voice = self.tts_voice
            else:
                lang_voice = resolve_voice(lang, self.voice_gender)

            report_fn(
                lang_base_pct + 0.40 * lang_progress_budget,
                f"{lang_label} Synthesizing speech timeline with native voice ({lang_voice})..."
            )
            lang_dubbed_vocals = lang_dir / f"{lang}_vocals.wav"
            if translated_segments:
                tts_inst = TimestampAwareTTS(
                    engine=self.tts_engine,
                    target_lang=lang,
                    voice_clone=self.voice_clone,
                    voice_name=lang_voice,
                    voice_gender=self.voice_gender,
                    device=self.device,
                    speed_cap=self.speed_cap
                )
                tts_inst.generate_and_align(
                    segments=translated_segments,
                    reference_vocals_path=vocals_path if self.voice_clone else None,
                    output_spanish_vocals=lang_dubbed_vocals,
                    total_duration=total_duration,
                    temp_dir=lang_dir,
                    auto_speed_adjust=True,
                    speed_cap=self.speed_cap
                )
            else:
                self._generate_silent_audio(lang_dubbed_vocals, total_duration)

            # Step 5: Remuxing
            report_fn(
                lang_base_pct + 0.85 * lang_progress_budget,
                f"{lang_label} Mixing {lang_name} audio & remuxing video stream..."
            )
            lang_output_video = lang_dir / f"{chunk_video.stem}_{lang_name}_dubbed.mp4"
            effective_enable_wm = self.enable_watermark if enable_watermark is None else enable_watermark
            effective_wm_text = watermark_text if watermark_text is not None else self.watermark_text
            effective_wm_interval = watermark_interval if watermark_interval is not None else self.watermark_interval
            effective_wm_opacity = watermark_opacity if watermark_opacity is not None else self.watermark_opacity

            self.remuxer.remux_and_export(
                original_video=chunk_video,
                spanish_vocals=lang_dubbed_vocals,
                background_audio=bg_path,
                output_video=lang_output_video,
                bg_volume=self.bg_volume,
                vocals_volume=self.vocals_volume,
                watermark_text=effective_wm_text if effective_enable_wm else None,
                watermark_interval=effective_wm_interval,
                watermark_opacity=effective_wm_opacity,
            )

            languages_result[lang] = {
                "lang": lang,
                "lang_name": lang_name,
                "folder": str(lang_dir),
                "final_video": str(lang_output_video),
                "dub_vocals": str(lang_dubbed_vocals),
                "segments_json": str(lang_transcript_json),
                "segments": translated_segments,
                "voice": lang_voice,
            }

        return {
            "chunk_video": str(chunk_video),
            "chunk_work_dir": str(chunk_work_dir),
            "english_segments": segments,
            "extracted_audio": str(extracted_audio),
            "vocals": str(vocals_path),
            "background": str(bg_path),
            "total_duration": total_duration,
            "languages": languages_result
        }

    def _run_chunked(
        self,
        input_video: Path,
        job_dir: Path,
        langs: List[str],
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        effective_start: float = 0.0,
        effective_duration: float = 600.0,
        enable_watermark: Optional[bool] = None,
        watermark_text: Optional[str] = None,
        watermark_interval: Optional[float] = None,
        watermark_opacity: Optional[float] = None,
        gemini_api_key: Optional[str] = None,
        is_shorts_mode: bool = False,
        generate_shorts: bool = False,
        shorts_count: int = 3,
        short_duration: float = 45.0,
        shorts_aspect_ratio: str = "9:16",
        selected_moment_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Processes long videos (>10 mins) safely by splitting into 10-minute parts,
        converting each part individually, and merging all parts into the final video.
        """
        def report(progress: float, message: str):
            logger.info(f"[{int(progress * 100)}%] {message}")
            if progress_callback:
                progress_callback(progress, message)

        is_multi = len(langs) > 1
        num_chunks = int(math.ceil(effective_duration / self.CHUNK_DURATION_SECONDS))
        chunks_dir = job_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        def fmt_time(sec: float) -> str:
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s = int(sec % 60)
            return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        report(
            0.02,
            f"Video length is {effective_duration / 60:.1f} mins (> 10 mins). Processing in {num_chunks} x 10-minute parts for memory stability, then merging all parts..."
        )

        parallel_workers = HardwareAccelerationManager.get_optimal_worker_count()
        parallel_workers = max(1, min(parallel_workers, num_chunks))

        chunk_progress: Dict[int, float] = {i: 0.0 for i in range(num_chunks)}
        progress_lock = threading.Lock()

        def process_chunk_task(idx: int) -> Tuple[int, Dict[str, Any]]:
            c_start = effective_start + idx * self.CHUNK_DURATION_SECONDS
            c_dur = min(self.CHUNK_DURATION_SECONDS, effective_duration - (idx * self.CHUNK_DURATION_SECONDS))
            c_label = f"Part {idx + 1}/{num_chunks}"
            c_time_range = f"{fmt_time(c_start)} - {fmt_time(c_start + c_dur)}"

            chunk_dir = chunks_dir / f"part_{idx + 1}"
            chunk_dir.mkdir(parents=True, exist_ok=True)

            chunk_source = chunk_dir / f"source_part_{idx + 1}.mp4"
            with progress_lock:
                chunk_progress[idx] = 0.02
                avg_p = sum(chunk_progress.values()) / num_chunks
                report(
                    min(0.88, 0.02 + avg_p * 0.85),
                    f"[{c_label} ({c_time_range})] Extracting video part..."
                )

            VideoSegmenter.trim(
                input_video=input_video,
                output_video=chunk_source,
                start_seconds=c_start,
                duration_seconds=c_dur
            )

            def chunk_report(p: float, msg: str):
                with progress_lock:
                    chunk_progress[idx] = max(chunk_progress[idx], p)
                    avg_p = sum(chunk_progress.values()) / num_chunks
                    report(
                        min(0.88, 0.02 + avg_p * 0.85),
                        f"[{c_label} ({c_time_range})] {msg}"
                    )

            chunk_res = self._process_single_chunk(
                chunk_video=chunk_source,
                chunk_work_dir=chunk_dir,
                langs=langs,
                report_fn=chunk_report,
                enable_watermark=enable_watermark,
                watermark_text=watermark_text,
                watermark_interval=watermark_interval,
                watermark_opacity=watermark_opacity,
            )

            with progress_lock:
                chunk_progress[idx] = 1.0
                avg_p = sum(chunk_progress.values()) / num_chunks
                report(
                    min(0.88, 0.02 + avg_p * 0.85),
                    f"[{c_label} ({c_time_range})] Part {idx + 1} complete."
                )

            # Free memory between chunks
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                elif hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
                    torch.mps.empty_cache()
            except Exception:
                pass

            return idx, chunk_res

        if parallel_workers > 1:
            report(
                0.02,
                f"Video length is {effective_duration / 60:.1f} mins ({num_chunks} parts). "
                f"RAM permits parallel processing: Dubbing {parallel_workers} parts concurrently..."
            )
            chunk_results_dict: Dict[int, Dict[str, Any]] = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as chunk_pool:
                futures = [chunk_pool.submit(process_chunk_task, idx) for idx in range(num_chunks)]
                for fut in concurrent.futures.as_completed(futures):
                    idx, res = fut.result()
                    chunk_results_dict[idx] = res

            chunk_results = [chunk_results_dict[i] for i in range(num_chunks)]
        else:
            report(
                0.02,
                f"Video length is {effective_duration / 60:.1f} mins (> 10 mins). "
                f"Processing {num_chunks} parts sequentially (1 at a time for memory stability)..."
            )
            chunk_results = []
            for idx in range(num_chunks):
                _, res = process_chunk_task(idx)
                chunk_results.append(res)

        # Step: Merge all chunk results into final video and language assets
        report(0.88, f"All {num_chunks} parts converted successfully! Merging into complete final video...")

        # Calculate accurate cumulative start timestamp offsets for segment transcripts
        offsets = [0.0]
        for i in range(num_chunks - 1):
            offsets.append(offsets[-1] + chunk_results[i]["total_duration"])

        languages_result: Dict[str, Any] = {}
        for lang_idx, lang in enumerate(langs):
            lang_name = LANGUAGE_NAMES.get(lang, lang.capitalize())
            lang_dir = job_dir / lang_name
            lang_dir.mkdir(parents=True, exist_ok=True)

            report(
                0.88 + 0.04 * (lang_idx / len(langs)),
                f"[{lang_name}] Merging {num_chunks} parts into final {lang_name} dubbed video..."
            )

            chunk_videos = [Path(chunk_results[i]["languages"][lang]["final_video"]) for i in range(num_chunks)]
            final_lang_video = lang_dir / f"{input_video.stem}_{lang_name}_dubbed.mp4"
            VideoSegmenter.merge_video_chunks(chunk_videos, final_lang_video)

            # Merge translated segments with cumulative timeline offset
            merged_segments = []
            for i in range(num_chunks):
                offset = offsets[i]
                chunk_segs = chunk_results[i]["languages"][lang]["segments"]
                for seg in chunk_segs:
                    s = dict(seg)
                    s["start"] = round(float(seg.get("start", 0.0)) + offset, 2)
                    s["end"] = round(float(seg.get("end", 0.0)) + offset, 2)
                    merged_segments.append(s)

            lang_transcript_json = lang_dir / f"segments_{lang}.json"
            with open(lang_transcript_json, "w", encoding="utf-8") as f:
                json.dump(merged_segments, f, indent=2, ensure_ascii=False)

            # Merge dubbed vocals audio
            chunk_dub_vocals = [Path(chunk_results[i]["languages"][lang]["dub_vocals"]) for i in range(num_chunks)]
            final_lang_dub_vocals = lang_dir / f"{lang}_vocals.wav"
            VideoSegmenter.merge_audio_chunks(chunk_dub_vocals, final_lang_dub_vocals)

            # Generate YouTube SEO pack and thumbnail for full merged video
            report(0.92, f"[{lang_name}] Generating YouTube SEO Pack & Thumbnail for full video...")
            meta_result = None
            thumb_result = None
            try:
                active_key = gemini_api_key or self.gemini_api_key
                video_title_hint = input_video.stem.replace("_", " ")
                summary_hint = " ".join([s.get("translated_text", "") for s in merged_segments[:15]])
                seo_meta = MultilingualMetadataGenerator.generate(
                    target_lang=lang,
                    english_title=video_title_hint,
                    context_text=summary_hint,
                    gemini_api_key=active_key
                )
                meta_json_path = lang_dir / f"metadata_{lang}.json"
                with open(meta_json_path, "w", encoding="utf-8") as f:
                    json.dump(seo_meta, f, indent=2, ensure_ascii=False)

                meta_txt_path = lang_dir / f"youtube_metadata_{lang}.txt"
                with open(meta_txt_path, "w", encoding="utf-8") as f:
                    f.write(f"TITEL / TITLE:\n{seo_meta['title']}\n\n")
                    f.write(f"BESCHREIBUNG / DESCRIPTION:\n{seo_meta['description']}\n\n")
                    f.write(f"TAGS:\n{seo_meta['tags']}\n")

                if lang == "de":
                    with open(lang_dir / "metadata_german.json", "w", encoding="utf-8") as f:
                        json.dump(seo_meta, f, indent=2, ensure_ascii=False)

                thumb_out_path = lang_dir / f"thumbnail_{lang}.jpg"
                MultilingualThumbnailGenerator.generate_thumbnail(
                    video_path=final_lang_video,
                    hook_text=seo_meta.get("thumbnail_hook", ""),
                    output_path=thumb_out_path,
                    lang_code=lang
                )
                if lang == "de":
                    shutil.copyfile(str(thumb_out_path), str(lang_dir / "thumbnail_german.jpg"))

                meta_result = seo_meta
                thumb_result = str(thumb_out_path)
            except Exception as meta_err:
                logger.warning(f"{lang_name} SEO pack generation failed: {meta_err}")

            languages_result[lang] = {
                "lang": lang,
                "lang_name": lang_name,
                "folder": str(lang_dir),
                "final_video": str(final_lang_video),
                "dub_vocals": str(final_lang_dub_vocals),
                "segments_json": str(lang_transcript_json),
                "segments": merged_segments,
                "voice": chunk_results[0]["languages"][lang]["voice"],
                "metadata": meta_result,
                "thumbnail": thumb_result,
            }

        # Merge Master English transcript
        merged_english_segments = []
        for i in range(num_chunks):
            offset = offsets[i]
            for seg in chunk_results[i]["english_segments"]:
                s = dict(seg)
                s["start"] = round(float(seg.get("start", 0.0)) + offset, 2)
                s["end"] = round(float(seg.get("end", 0.0)) + offset, 2)
                merged_english_segments.append(s)

        english_transcript_file = job_dir / "english_transcript.json"
        with open(english_transcript_file, "w", encoding="utf-8") as f:
            json.dump(merged_english_segments, f, indent=2, ensure_ascii=False)

        # Backward compatibility segments_translated.json in job root
        primary_lang = langs[0]
        primary_info = languages_result[primary_lang]
        primary_video_path = Path(primary_info["final_video"])
        with open(job_dir / "segments_translated.json", "w", encoding="utf-8") as f:
            json.dump(primary_info["segments"], f, indent=2, ensure_ascii=False)

        # Merge shared audio stems in job root
        final_bg_path = job_dir / "background_music_sfx.wav"
        VideoSegmenter.merge_audio_chunks([Path(c["background"]) for c in chunk_results], final_bg_path)

        final_vocals_path = job_dir / "vocals.wav"
        VideoSegmenter.merge_audio_chunks([Path(c["vocals"]) for c in chunk_results], final_vocals_path)

        final_orig_audio = job_dir / "original_audio.wav"
        VideoSegmenter.merge_audio_chunks([Path(c["extracted_audio"]) for c in chunk_results], final_orig_audio)

        total_merged_duration = VideoSegmenter.get_duration(primary_video_path)
        if total_merged_duration <= 0.0:
            total_merged_duration = sum(c.get("total_duration", 0.0) for c in chunk_results)

        # Clean up chunk directories to save disk space
        try:
            shutil.rmtree(chunks_dir, ignore_errors=True)
        except Exception:
            pass

        # Generate Shorts if requested
        should_gen_shorts = generate_shorts or is_shorts_mode
        if should_gen_shorts:
            report(0.95, f"Generating Top {shorts_count} Instagram Reels / YouTube Shorts (9:16 vertical)...")
            try:
                top_moments = ShortsGenerator.detect_top_moments(
                    video_path=primary_video_path,
                    audio_path=final_orig_audio,
                    duration_seconds=total_merged_duration,
                    num_moments=shorts_count,
                    moment_duration=short_duration,
                )
                for l_code, l_info in languages_result.items():
                    lang_video_file = Path(l_info["final_video"])
                    lang_folder_p = Path(l_info["folder"])
                    shorts_dir = lang_folder_p / "Shorts"
                    shorts_dir.mkdir(parents=True, exist_ok=True)
                    lang_shorts = []
                    for m in top_moments:
                        short_clean_time = m["time_range"].replace(":", "-").replace(" ", "")
                        short_fname = f"short_{m['index']}_{short_clean_time}.mp4"
                        short_dest = shorts_dir / short_fname
                        try:
                            ShortsGenerator.create_vertical_short(
                                input_video=lang_video_file,
                                output_path=short_dest,
                                start_seconds=m["start_seconds"],
                                duration_seconds=m["duration_seconds"],
                                aspect_ratio=shorts_aspect_ratio,
                            )
                            lang_shorts.append({
                                "index": m["index"],
                                "title": m["title"],
                                "category": m["category"],
                                "time_range": m["time_range"],
                                "start_seconds": m["start_seconds"],
                                "duration_seconds": m["duration_seconds"],
                                "filename": short_fname,
                                "file_path": str(short_dest),
                                "aspect_ratio": shorts_aspect_ratio,
                            })
                        except Exception as s_err:
                            logger.warning(f"Could not generate short #{m['index']} for {l_code}: {s_err}")
                    l_info["shorts"] = lang_shorts
            except Exception as e:
                logger.warning(f"Shorts generation failed: {e}")

        # If user provided a specific single output path, copy the primary result there
        if output_path and not is_multi:
            custom_out = Path(output_path).resolve()
            if custom_out != primary_video_path:
                custom_out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(primary_video_path), str(custom_out))
                primary_video_path = custom_out

        # Create clean ZIP archive bundling all language folders and shorts
        zip_path = job_dir / "all_dubbed_languages.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for l_code, l_info in languages_result.items():
                    l_folder = Path(l_info["folder"])
                    if l_folder.exists():
                        for f in l_folder.rglob("*"):
                            if f.is_file() and not f.name.startswith("chunk_"):
                                rel = f.relative_to(l_folder)
                                zipf.write(f, arcname=f"{l_info['lang_name']}/{rel}")
                if english_transcript_file.exists():
                    zipf.write(english_transcript_file, arcname="shared/english_transcript.json")
                if final_bg_path.exists():
                    zipf.write(final_bg_path, arcname="shared/background_music_sfx.wav")
        except Exception as e:
            logger.warning(f"Could not build ZIP archive: {e}")

        report(
            1.0,
            f"Dubbing complete for {len(langs)} language(s)! ({num_chunks} x 10-minute parts merged into {job_dir.name}/)"
        )

        metadata_by_lang = {
            l: info.get("metadata")
            for l, info in languages_result.items()
            if info.get("metadata")
        }
        thumbnails_by_lang = {
            l: info.get("thumbnail")
            for l, info in languages_result.items()
            if info.get("thumbnail")
        }

        return {
            "is_multi_language": is_multi,
            "target_langs": langs,
            "languages": languages_result,
            "final_video": str(primary_video_path),
            "original_audio": str(final_orig_audio),
            "vocals": str(final_vocals_path),
            "background": str(final_bg_path),
            "dub_vocals": primary_info["dub_vocals"],
            "spanish_vocals": primary_info["dub_vocals"],
            "segments": primary_info["segments"],
            "total_duration": total_merged_duration,
            "zip_path": str(zip_path) if zip_path.exists() else None,
            "metadata": primary_info.get("metadata"),
            "thumbnail": primary_info.get("thumbnail"),
            "metadata_by_lang": metadata_by_lang,
            "thumbnails_by_lang": thumbnails_by_lang,
            "shorts": primary_info.get("shorts", []),
            "is_shorts_mode": is_shorts_mode,
        }

    def run(
        self,
        video_path: str,
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        start_seconds: Optional[float] = None,
        duration_seconds: Optional[float] = None,
        part_name: Optional[str] = None,
        target_langs: Optional[List[str]] = None,
        enable_watermark: Optional[bool] = None,
        watermark_text: Optional[str] = None,
        watermark_interval: Optional[float] = None,
        watermark_opacity: Optional[float] = None,
        gemini_api_key: Optional[str] = None,
        is_shorts_mode: bool = False,
        generate_shorts: bool = False,
        shorts_count: int = 3,
        short_duration: float = 45.0,
        shorts_aspect_ratio: str = "9:16",
        selected_moment_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Executes the local AI dubbing pipeline. If the video duration exceeds 10 minutes,
        it automatically processes the video by splitting into 10-minute parts, dubbing each part,
        and merging all parts into the final complete video.
        """
        input_video = Path(video_path).resolve()
        if not input_video.exists():
            raise FileNotFoundError(f"Input video not found: {input_video}")

        if not AppleSiliconManager.verify_ffmpeg():
            raise RuntimeError("FFmpeg is missing from PATH. Install with `brew install ffmpeg`.")

        job_dir = self.work_dir if ("job" in str(self.work_dir).lower() or self.work_dir.name == input_video.stem) else (self.work_dir / input_video.stem)
        job_dir.mkdir(parents=True, exist_ok=True)

        def report(progress: float, message: str):
            logger.info(f"[{int(progress * 100)}%] {message}")
            if progress_callback:
                progress_callback(progress, message)

        # Parse & normalize list of target languages
        langs = [l.strip().lower() for l in target_langs if l.strip()] if target_langs else [self.target_lang]
        if not langs:
            langs = [self.target_lang]
        langs = list(dict.fromkeys(langs))
        is_multi = len(langs) > 1

        # Check total duration to determine if 10-minute auto-chunking is needed
        video_dur = VideoSegmenter.get_duration(input_video)
        if video_dur <= 0.0:
            try:
                video_dur = self.tts.get_audio_duration(input_video)
            except Exception:
                video_dur = 600.0

        effective_start = float(start_seconds or 0.0)
        if duration_seconds is not None and duration_seconds > 0:
            effective_duration = float(duration_seconds)
        else:
            effective_duration = max(0.0, video_dur - effective_start)
        if effective_duration <= 0.0:
            effective_duration = video_dur

        # If length exceeds 10 minutes (600s), process via 10-min splitting + conversion + merge
        if effective_duration > self.CHUNK_DURATION_SECONDS:
            logger.info(
                f"Video duration ({effective_duration:.1f}s) exceeds 10 minutes ({self.CHUNK_DURATION_SECONDS}s). "
                f"Processing via auto-split 10-minute parts and merging all parts..."
            )
            return self._run_chunked(
                input_video=input_video,
                job_dir=job_dir,
                langs=langs,
                output_path=output_path,
                progress_callback=progress_callback,
                effective_start=effective_start,
                effective_duration=effective_duration,
                enable_watermark=enable_watermark,
                watermark_text=watermark_text,
                watermark_interval=watermark_interval,
                watermark_opacity=watermark_opacity,
                gemini_api_key=gemini_api_key,
                is_shorts_mode=is_shorts_mode,
                generate_shorts=generate_shorts,
                shorts_count=shorts_count,
                short_duration=short_duration,
                shorts_aspect_ratio=shorts_aspect_ratio,
                selected_moment_index=selected_moment_index,
            )

        # Single-pass execution for <= 10 minute videos / parts
        # Handle splitting / trimming if specific part start/duration requested
        if (start_seconds is not None and start_seconds > 0) or (duration_seconds is not None and duration_seconds > 0):
            part_tag = part_name or f"part_{int(start_seconds or 0)}_{int(duration_seconds or 0)}"
            trimmed_source = job_dir / f"{input_video.stem}_{part_tag}.mp4"
            report(0.03, f"Extracting video part ({int(start_seconds or 0)}s - {int((start_seconds or 0) + (duration_seconds or 0))}s)...")
            input_video = VideoSegmenter.trim(
                input_video=input_video,
                output_video=trimmed_source,
                start_seconds=start_seconds or 0.0,
                duration_seconds=duration_seconds
            )

        try:
            chunk_res = self._process_single_chunk(
                chunk_video=input_video,
                chunk_work_dir=job_dir,
                langs=langs,
                report_fn=report,
                enable_watermark=enable_watermark,
                watermark_text=watermark_text,
                watermark_interval=watermark_interval,
                watermark_opacity=watermark_opacity,
            )

            languages_result = chunk_res["languages"]
            total_duration = chunk_res["total_duration"]
            extracted_audio = Path(chunk_res["extracted_audio"])
            vocals_path = Path(chunk_res["vocals"])
            bg_path = Path(chunk_res["background"])
            english_transcript_file = job_dir / "english_transcript.json"

            # Step 5b: Generate YouTube SEO Pack and Thumbnail (Only for Full video or First Part)
            is_first_part_or_full = (
                (start_seconds is None or start_seconds == 0.0) or
                (part_name and any(p in part_name.lower() for p in ["part_1", "part 1", "part_0", "part 0"]))
            )

            for idx, lang in enumerate(langs):
                lang_name = LANGUAGE_NAMES.get(lang, lang.capitalize())
                lang_dir = Path(languages_result[lang]["folder"])
                lang_output_video = Path(languages_result[lang]["final_video"])
                translated_segments = languages_result[lang]["segments"]

                meta_result = None
                thumb_result = None
                if is_first_part_or_full:
                    report(
                        0.92 + 0.04 * (idx / len(langs)),
                        f"[{lang_name}] Generating YouTube SEO Pack & Thumbnail ({lang_name})..."
                    )
                    try:
                        active_key = gemini_api_key or self.gemini_api_key
                        video_title_hint = input_video.stem.replace("_", " ")
                        summary_hint = " ".join([s.get("translated_text", "") for s in translated_segments[:15]])
                        seo_meta = MultilingualMetadataGenerator.generate(
                            target_lang=lang,
                            english_title=video_title_hint,
                            context_text=summary_hint,
                            gemini_api_key=active_key
                        )

                        meta_json_path = lang_dir / f"metadata_{lang}.json"
                        with open(meta_json_path, "w", encoding="utf-8") as f:
                            json.dump(seo_meta, f, indent=2, ensure_ascii=False)

                        meta_txt_path = lang_dir / f"youtube_metadata_{lang}.txt"
                        with open(meta_txt_path, "w", encoding="utf-8") as f:
                            f.write(f"TITEL / TITLE:\n{seo_meta['title']}\n\n")
                            f.write(f"BESCHREIBUNG / DESCRIPTION:\n{seo_meta['description']}\n\n")
                            f.write(f"TAGS:\n{seo_meta['tags']}\n")

                        if lang == "de":
                            with open(lang_dir / "metadata_german.json", "w", encoding="utf-8") as f:
                                json.dump(seo_meta, f, indent=2, ensure_ascii=False)

                        thumb_out_path = lang_dir / f"thumbnail_{lang}.jpg"
                        MultilingualThumbnailGenerator.generate_thumbnail(
                            video_path=lang_output_video,
                            hook_text=seo_meta.get("thumbnail_hook", ""),
                            output_path=thumb_out_path,
                            lang_code=lang
                        )

                        if lang == "de":
                            shutil.copyfile(str(thumb_out_path), str(lang_dir / "thumbnail_german.jpg"))

                        meta_result = seo_meta
                        thumb_result = str(thumb_out_path)
                    except Exception as meta_err:
                        logger.warning(f"{lang_name} SEO pack generation failed: {meta_err}")

                languages_result[lang]["metadata"] = meta_result
                languages_result[lang]["thumbnail"] = thumb_result

            # Generate Shorts if requested
            should_gen_shorts = generate_shorts or is_shorts_mode
            if should_gen_shorts:
                report(0.96, f"Generating Top {shorts_count} Instagram Reels / YouTube Shorts (9:16 vertical)...")
                top_moments = ShortsGenerator.detect_top_moments(
                    video_path=input_video,
                    audio_path=extracted_audio,
                    duration_seconds=total_duration,
                    num_moments=shorts_count,
                    moment_duration=short_duration,
                )
                for l_code, l_info in languages_result.items():
                    lang_video_file = Path(l_info["final_video"])
                    lang_folder_p = Path(l_info["folder"])
                    shorts_dir = lang_folder_p / "Shorts"
                    shorts_dir.mkdir(parents=True, exist_ok=True)
                    lang_shorts = []
                    for m in top_moments:
                        short_clean_time = m["time_range"].replace(":", "-").replace(" ", "")
                        short_fname = f"short_{m['index']}_{short_clean_time}.mp4"
                        short_dest = shorts_dir / short_fname
                        try:
                            ShortsGenerator.create_vertical_short(
                                input_video=lang_video_file,
                                output_path=short_dest,
                                start_seconds=m["start_seconds"],
                                duration_seconds=m["duration_seconds"],
                                aspect_ratio=shorts_aspect_ratio,
                            )
                            lang_shorts.append({
                                "index": m["index"],
                                "title": m["title"],
                                "category": m["category"],
                                "time_range": m["time_range"],
                                "start_seconds": m["start_seconds"],
                                "duration_seconds": m["duration_seconds"],
                                "filename": short_fname,
                                "file_path": str(short_dest),
                                "aspect_ratio": shorts_aspect_ratio,
                            })
                        except Exception as s_err:
                            logger.warning(f"Could not generate short #{m['index']} for {l_code}: {s_err}")
                    l_info["shorts"] = lang_shorts

            primary_lang = langs[0]
            primary_info = languages_result[primary_lang]
            primary_video_path = Path(primary_info["final_video"])

            if output_path and not is_multi:
                custom_out = Path(output_path).resolve()
                if custom_out != primary_video_path:
                    custom_out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(primary_video_path), str(custom_out))
                    primary_video_path = custom_out

            with open(job_dir / "segments_translated.json", "w", encoding="utf-8") as f:
                json.dump(primary_info["segments"], f, indent=2, ensure_ascii=False)

            zip_path = job_dir / "all_dubbed_languages.zip"
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for l_code, l_info in languages_result.items():
                        l_folder = Path(l_info["folder"])
                        if l_folder.exists():
                            for f in l_folder.rglob("*"):
                                if f.is_file() and not f.name.startswith("chunk_"):
                                    rel = f.relative_to(l_folder)
                                    zipf.write(f, arcname=f"{l_info['lang_name']}/{rel}")
                    if english_transcript_file.exists():
                        zipf.write(english_transcript_file, arcname="shared/english_transcript.json")
                    if bg_path.exists():
                        zipf.write(bg_path, arcname="shared/background_music_sfx.wav")
            except Exception as e:
                logger.warning(f"Could not build ZIP archive: {e}")

            report(
                1.0,
                f"Dubbing complete for {len(langs)} language(s)! Stored in separate folders under {job_dir.name}/"
            )

            metadata_by_lang = {
                l: info.get("metadata")
                for l, info in languages_result.items()
                if info.get("metadata")
            }
            thumbnails_by_lang = {
                l: info.get("thumbnail")
                for l, info in languages_result.items()
                if info.get("thumbnail")
            }

            return {
                "is_multi_language": is_multi,
                "target_langs": langs,
                "languages": languages_result,
                "final_video": str(primary_video_path),
                "original_audio": str(extracted_audio),
                "vocals": str(vocals_path),
                "background": str(bg_path),
                "dub_vocals": primary_info["dub_vocals"],
                "spanish_vocals": primary_info["dub_vocals"],
                "segments": primary_info["segments"],
                "total_duration": total_duration,
                "zip_path": str(zip_path) if zip_path.exists() else None,
                "metadata": primary_info.get("metadata"),
                "thumbnail": primary_info.get("thumbnail"),
                "metadata_by_lang": metadata_by_lang,
                "thumbnails_by_lang": thumbnails_by_lang,
                "shorts": primary_info.get("shorts", []),
                "is_shorts_mode": is_shorts_mode,
            }

        except Exception as e:
            logger.exception(f"Pipeline failed during execution: {e}")
            raise
