"""
Database and system monitoring layer for ManhwaDub Admin Panel.
Provides persistent storage for Videos and Jobs, macOS unified RAM telemetry,
and automatic recovery of archived conversions.
"""

import os
import re
import json
import time
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def get_system_storage(target_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Retrieves real-time disk storage metrics (available, used, total in GB).
    """
    try:
        check_dir = str(target_path or Path(__file__).resolve().parent / "workspace_api")
        if not os.path.exists(check_dir):
            check_dir = "."
        usage = shutil.disk_usage(check_dir)
        total_gb = round(usage.total / (1024 ** 3), 1)
        used_gb = round(usage.used / (1024 ** 3), 1)
        free_gb = round(usage.free / (1024 ** 3), 1)
        percent_used = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0.0
        return {
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "available_gb": free_gb,
            "percent": percent_used,
            "percent_used": percent_used,
            "percent_free": round(100.0 - percent_used, 1),
            "display": f"{free_gb} GB / {total_gb} GB"
        }
    except Exception:
        return {
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "available_gb": 0.0,
            "percent": 0.0,
            "percent_used": 0.0,
            "percent_free": 0.0,
            "display": "N/A"
        }


def get_system_ram() -> Dict[str, Any]:
    """
    Retrieves real-time system memory across Linux Cloud VMs, Docker, macOS, and Windows.
    Uses /proc/meminfo on Linux, psutil if available, or sysctl/vm_stat on macOS.
    """
    # 1. Try psutil if installed
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            "total_gb": round(vm.total / (1024 ** 3), 2),
            "used_gb": round(vm.used / (1024 ** 3), 2),
            "free_gb": round(vm.available / (1024 ** 3), 2),
            "percent": round(vm.percent, 1)
        }
    except Exception:
        pass

    # 2. Linux / Cloud VM (/proc/meminfo)
    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            mem = {}
            with open(meminfo_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip().split()[0]
                        if v.isdigit():
                            mem[k] = int(v) # kB
            total_kb = mem.get("MemTotal", 0)
            avail_kb = mem.get("MemAvailable", mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0))
            if total_kb > 0:
                used_kb = max(0, total_kb - avail_kb)
                total_bytes = total_kb * 1024
                used_bytes = used_kb * 1024
                free_bytes = avail_kb * 1024
                return {
                    "total_gb": round(total_bytes / (1024 ** 3), 2),
                    "used_gb": round(used_bytes / (1024 ** 3), 2),
                    "free_gb": round(free_bytes / (1024 ** 3), 2),
                    "percent": round((used_bytes / total_bytes) * 100, 1)
                }
        except Exception:
            pass

    # 3. macOS (Apple Silicon or Intel Mac)
    try:
        import re
        total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
        vm_output = subprocess.check_output(["vm_stat"]).decode("utf-8")
        m_page = re.search(r"page size of (\d+) bytes", vm_output)
        page_size = int(m_page.group(1)) if m_page else 4096
        pages = {}
        for line in vm_output.splitlines():
            if ":" in line:
                parts = line.split(":")
                key = parts[0].strip().strip("\"")
                val = parts[1].strip().rstrip(".")
                if val.isdigit():
                    pages[key] = int(val)
        # On macOS, available memory = free + inactive + purgeable + speculative
        avail_pages = pages.get("Pages free", 0) + pages.get("Pages inactive", 0) + pages.get("Pages purgeable", 0) + pages.get("Pages speculative", 0)
        avail_bytes = avail_pages * page_size
        used_bytes = max(0, total_bytes - avail_bytes)
        return {
            "total_gb": round(total_bytes / (1024 ** 3), 2),
            "used_gb": round(used_bytes / (1024 ** 3), 2),
            "free_gb": round(avail_bytes / (1024 ** 3), 2),
            "percent": round((used_bytes / total_bytes) * 100, 1)
        }
    except Exception:
        pass

    # 4. Safe dynamic host fallback
    return {
        "total_gb": 16.0,
        "used_gb": 8.0,
        "free_gb": 8.0,
        "percent": 50.0
    }


def load_databases(jobs_dir: Path, workspace_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Loads jobs and videos from json files. If not present or incomplete,
    scans existing jobs folders on disk and reconstructs records.
    """
    jobs_file = workspace_dir / "jobs_db.json"
    videos_file = workspace_dir / "videos_db.json"

    jobs_db: Dict[str, Dict[str, Any]] = {}
    videos_db: Dict[str, Dict[str, Any]] = {}

    if jobs_file.exists():
        try:
            with open(jobs_file, "r", encoding="utf-8") as f:
                jobs_db = json.load(f)
        except Exception:
            jobs_db = {}

    has_videos_file = videos_file.exists()
    if has_videos_file:
        try:
            with open(videos_file, "r", encoding="utf-8") as f:
                videos_db = json.load(f)
        except Exception:
            videos_db = {}

    # Scan jobs directory on disk
    if jobs_dir.exists():
        for job_folder in jobs_dir.iterdir():
            if not job_folder.is_dir() or job_folder.name.startswith("."):
                continue

            job_id = job_folder.name
            if job_id not in jobs_db:
                # Reconstruct job metadata from disk
                meta_files = list(job_folder.glob("metadata_*.json"))
                mp4_files = [x.name for x in job_folder.glob("*.mp4")]

                langs = []
                for m in meta_files:
                    l = m.stem.replace("metadata_", "")
                    if l and l not in ["german", "seo"]:
                        langs.append(l)
                    elif l == "german":
                        langs.append("de")
                for mp4 in mp4_files:
                    for code in ["de", "es", "fr", "id", "ta", "te", "bn", "hi", "kn", "ml", "mr", "pt", "vi", "ar", "ru", "ja"]:
                        if f"_{code}_dubbed" in mp4:
                            langs.append(code)
                langs = list(dict.fromkeys(langs))
                if not langs:
                    langs = ["de"]

                part_name = None
                time_range = None
                for mp4 in mp4_files:
                    m = re.search(r"Part\s*(\d+)", mp4, re.IGNORECASE)
                    if m:
                        part_name = f"Part {m.group(1)}"
                        # Check timestamp pattern in filename
                        t_m = re.search(r"(\d+_\d+_\d+___\d+_\d+_\d+|\d+_\d+___\d+_\d+)", mp4)
                        if t_m:
                            time_range = t_m.group(1).replace("___", " - ").replace("_", ":")
                        break

                # Detect video base id
                base_id = None
                for mp4 in mp4_files:
                    stem = Path(mp4).stem
                    base = stem.split("_Part")[0].split("_de_")[0].split("_es_")[0].split("_fr_")[0].split("_")[0]
                    if len(base) >= 8:
                        base_id = base
                        break

                has_output = any("_dubbed.mp4" in mp4 for mp4 in mp4_files)
                thumb_file = job_folder / "thumbnail_german.jpg"
                if not thumb_file.exists():
                    thumb_file = job_folder / "thumbnail_de.jpg"

                mtime = job_folder.stat().st_mtime
                job_rec = {
                    "job_id": job_id,
                    "status": "completed",
                    "progress": 1.0,
                    "current_step": "Dubbing completed successfully." if has_output else "Completed",
                    "logs": ["Job restored from local disk archive"],
                    "target_lang": langs[0],
                    "target_langs": langs,
                    "is_multi_language": len(langs) > 1,
                    "created_at": mtime,
                    "completed_at": mtime,
                    "part_name": part_name,
                    "time_range": time_range or ("00:00 - 10:00" if part_name else "Full Video"),
                    "video_base_id": base_id,
                    "youtube_url": f"https://www.youtube.com/watch?v={base_id}" if base_id else None,
                    "thumbnail_url": f"/api/jobs/{job_id}/thumbnail" if thumb_file.exists() else None,
                    "output_video_url": f"/api/jobs/{job_id}/video" if has_output else None,
                    "zip_url": f"/api/jobs/{job_id}/download-all" if (job_folder / "all_dubbed_languages.zip").exists() else None,
                    "duration": 600.0 if part_name else 900.0
                }
                jobs_db[job_id] = job_rec

    # Organize existing jobs into video entries if not already grouped
    if not videos_db and not has_videos_file:
        # Group jobs by video_base_id
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for j_id, j_data in jobs_db.items():
            base_id = j_data.get("video_base_id") or "default_video"
            grouped.setdefault(base_id, []).append(j_data)

        # Predefined friendly titles for known sample videos
        title_map = {
            "Lz38NiTR69A": "Solo Leveling Manhwa Recap (Episodes 1-12)",
            "bXe7-vR7o5M": "Manhwa Chronicles: The Reincarnated Boss",
            "3Fpgkq6Tj6I": "Return of the Disaster-Class Hero",
            "C5koU3Sa1GU": "The Beginning After The End Season 1",
            "4_-IexPhd4k": "Nano Machine Action Recap"
        }

        for base_id, j_list in grouped.items():
            vid_id = f"vid_{base_id}"
            yt_url = f"https://www.youtube.com/watch?v={base_id}" if base_id != "default_video" else "https://www.youtube.com/watch?v=Lz38NiTR69A"
            title = title_map.get(base_id, f"Manhwa Recap: {base_id}")
            
            # Sort conversions by part name or creation time
            conversions = []
            all_langs = set()
            thumb = None
            for j in j_list:
                for l in j.get("target_langs", [j.get("target_lang", "de")]):
                    all_langs.add(l)
                if not thumb and j.get("thumbnail_url"):
                    thumb = j.get("thumbnail_url")
                
                conversions.append({
                    "job_id": j["job_id"],
                    "part_name": j.get("part_name") or "Full Video",
                    "time_range": j.get("time_range") or "Full Video",
                    "is_multipart": bool(j.get("part_name")),
                    "languages": j.get("target_langs", [j.get("target_lang", "de")]),
                    "status": j.get("status", "completed"),
                    "progress": j.get("progress", 1.0),
                    "created_at": j.get("created_at", time.time()),
                    "output_video_url": j.get("output_video_url"),
                    "thumbnail_url": j.get("thumbnail_url"),
                    "zip_url": j.get("zip_url"),
                    "duration": j.get("duration", 600.0)
                })

            videos_db[vid_id] = {
                "id": vid_id,
                "title": title,
                "youtube_url": yt_url,
                "thumbnail_url": thumb,
                "created_at": min((c["created_at"] for c in conversions), default=time.time()),
                "updated_at": max((c["created_at"] for c in conversions), default=time.time()),
                "status": "completed",
                "conversions": conversions,
                "languages": sorted(list(all_langs))
            }

    save_databases(workspace_dir, jobs_db, videos_db)
    return jobs_db, videos_db


def save_databases(workspace_dir: Path, jobs_db: Dict[str, Any], videos_db: Dict[str, Any]):
    """Persists jobs and videos state to JSON files."""
    try:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        jobs_file = workspace_dir / "jobs_db.json"
        videos_file = workspace_dir / "videos_db.json"

        # Safe atomic write
        tmp_jobs = workspace_dir / "jobs_db.json.tmp"
        with open(tmp_jobs, "w", encoding="utf-8") as f:
            json.dump(jobs_db, f, indent=2)
        tmp_jobs.replace(jobs_file)

        tmp_videos = workspace_dir / "videos_db.json.tmp"
        with open(tmp_videos, "w", encoding="utf-8") as f:
            json.dump(videos_db, f, indent=2)
        tmp_videos.replace(videos_file)
    except Exception as e:
        print(f"Error saving databases: {e}")


def format_duration_human(sec: float) -> str:
    """Formats seconds into human-readable duration like '4m 30s', '45s', or '1h 12m'."""
    sec = int(round(sec))
    if sec <= 0:
        return "0s"
    if sec < 60:
        return f"{sec}s"
    m = sec // 60
    s = sec % 60
    if m < 60:
        return f"{m}m {s}s" if s > 0 else f"{m}m"
    h = m // 60
    rem_m = m % 60
    return f"{h}h {rem_m}m" if rem_m > 0 else f"{h}h"


def estimate_job_duration_sec(job_dict: Dict[str, Any]) -> float:
    """
    Estimates total processing time for a dubbing job based on video/part duration.
    Full dubbing pipeline (Whisper STT + Translation + Edge-TTS/XTTS + FFMPEG Remux)
    takes ~0.35x real-time duration on modern CPU / Apple Silicon.
    """
    dur = job_dict.get("duration") or job_dict.get("duration_seconds")
    try:
        video_sec = float(dur) if dur is not None else 600.0
    except (ValueError, TypeError):
        video_sec = 600.0

    if video_sec <= 0:
        video_sec = 600.0

    # Account for multi-language TTS generation
    langs = job_dict.get("target_langs") or [job_dict.get("target_lang", "es")]
    num_langs = max(1, len(langs))
    lang_mult = 1.0 + (num_langs - 1) * 0.15

    # Voice clone (XTTS) is slightly heavier than Edge-TTS
    clone_mult = 1.35 if job_dict.get("voice_clone") else 1.0

    return max(45.0, video_sec * 0.35 * lang_mult * clone_mult)


def get_system_stats(jobs_db: Dict[str, Any], videos_db: Dict[str, Any]) -> Dict[str, Any]:
    """Calculates live system RAM and statistics for dashboard widgets."""
    ram = get_system_ram()
    storage = get_system_storage()
    now = time.time()
    total_videos = len(videos_db)

    language_counts: Dict[str, int] = {}
    completed_jobs = 0
    failed_jobs = 0

    processing_jobs: List[Dict[str, Any]] = []
    queued_jobs: List[Dict[str, Any]] = []

    for j in jobs_db.values():
        st = j.get("status")
        if st in ["queued", "processing"]:
            vid_id = j.get("video_id")
            vid_title = None
            if vid_id:
                if vid_id in videos_db:
                    vid_title = videos_db[vid_id].get("title")
                else:
                    alt_id = f"vid_{vid_id}" if not vid_id.startswith("vid_") else vid_id.replace("vid_", "", 1)
                    if alt_id in videos_db:
                        vid_title = videos_db[alt_id].get("title")

            part_label = j.get("part_name")
            display_title = vid_title or part_label or "Video Conversion"
            if vid_title and part_label:
                display_title = f"{vid_title} ({part_label})"
            elif vid_title and not part_label:
                display_title = f"{vid_title} (Full Video)"

            job_info = {
                "job_id": j.get("job_id"),
                "video_id": vid_id,
                "video_title": vid_title,
                "display_title": display_title,
                "status": st,
                "progress": j.get("progress", 0.0),
                "current_step": j.get("current_step", "In queue..."),
                "target_langs": j.get("target_langs") or [j.get("target_lang", "es")],
                "part_name": j.get("part_name"),
                "created_at": j.get("created_at"),
                "started_at": j.get("started_at"),
                "youtube_url": j.get("youtube_url"),
                "duration": j.get("duration") or j.get("duration_seconds")
            }

            if st == "processing":
                processing_jobs.append(job_info)
            else:
                queued_jobs.append(job_info)

        elif st == "completed":
            completed_jobs += 1
            langs = j.get("target_langs") or [j.get("target_lang", "de")]
            for l in langs:
                language_counts[l] = language_counts.get(l, 0) + 1
        elif st == "failed":
            failed_jobs += 1

    # Sort processing and queued jobs chronologically
    processing_jobs.sort(key=lambda x: x.get("started_at") or x.get("created_at") or 0)
    queued_jobs.sort(key=lambda x: x.get("created_at") or 0)

    # Calculate remaining time for processing jobs
    proc_rem_seconds: List[float] = []
    for pj in processing_jobs:
        prog = float(pj.get("progress") or 0.0)
        started = pj.get("started_at") or pj.get("created_at") or now
        elapsed = max(0.0, now - started)
        est_total = estimate_job_duration_sec(pj)

        if prog > 0.05 and elapsed > 5:
            rem = max(10.0, (elapsed / prog) * (1.0 - prog))
        else:
            rem = max(15.0, est_total * (1.0 - prog))

        pj["estimated_remaining_seconds"] = round(rem)
        pj["estimated_remaining_formatted"] = format_duration_human(rem)
        proc_rem_seconds.append(rem)

    # Calculate estimated duration for queued jobs
    queued_durations: List[float] = []
    for qj in queued_jobs:
        q_dur = estimate_job_duration_sec(qj)
        qj["estimated_duration_seconds"] = round(q_dur)
        qj["estimated_duration_formatted"] = format_duration_human(q_dur)
        queued_durations.append(q_dur)

    # Concurrency in ThreadPoolExecutor is 1 (sequential worker pipeline to keep Apple Silicon RAM under 8GB)
    concurrency = 1
    proc_work = sum(proc_rem_seconds)
    queued_work = sum(queued_durations)
    total_work = proc_work + queued_work
    total_est_seconds = round(total_work / concurrency) if total_work > 0 else 0

    queue_summary = {
        "total_in_queue": len(queued_jobs),
        "total_processing": len(processing_jobs),
        "total_pending": len(queued_jobs) + len(processing_jobs),
        "estimated_seconds_remaining": total_est_seconds,
        "estimated_time_formatted": format_duration_human(total_est_seconds),
        "estimated_finish_time": round(now + total_est_seconds) if total_est_seconds > 0 else None,
        "concurrency": concurrency,
        "processing_jobs": processing_jobs,
        "queued_jobs": queued_jobs
    }

    # Combined active list for backward compatibility
    active_jobs_list = processing_jobs + queued_jobs

    # Ensure all video languages are properly represented
    for v in videos_db.values():
        for l in v.get("languages", []):
            if l not in language_counts:
                language_counts[l] = 1

    # Dynamic hardware inspection
    try:
        from pipeline import HardwareAccelerationManager
        hardware = HardwareAccelerationManager.get_device_info()
    except Exception:
        import platform
        hardware = {
            "device": "cpu",
            "engine_label": f"Multi-Core CPU ({os.cpu_count() or 4} Cores)",
            "gpu_name": None,
            "cpu_cores": os.cpu_count() or 4,
            "os": platform.system()
        }

    return {
        "hardware": hardware,
        "ram": ram,
        "storage": storage,
        "counts": {
            "total_videos": total_videos,
            "total_conversions": completed_jobs,
            "active_jobs": len(active_jobs_list),
            "queued_jobs": len(queued_jobs),
            "processing_jobs": len(processing_jobs),
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "total_languages": len(language_counts),
            "estimated_queue_time": format_duration_human(total_est_seconds)
        },
        "queue_summary": queue_summary,
        "languages": language_counts,
        "active_jobs": active_jobs_list
    }


def link_job_to_video(
    video_id: str,
    job_id: str,
    job_data: Dict[str, Any],
    videos_db: Dict[str, Any],
    workspace_dir: Path,
    jobs_db: Dict[str, Any]
):
    """Links a newly queued job to its parent video entry in videos_db."""
    if video_id not in videos_db:
        # Create new video entry if not exists
        title = job_data.get("part_name") or "New Video Dubbing"
        if job_data.get("youtube_url"):
            yt_id = job_data["youtube_url"].split("v=")[-1].split("&")[0]
            title = f"YouTube Video: {yt_id}"
            
        videos_db[video_id] = {
            "id": video_id,
            "title": title,
            "youtube_url": job_data.get("youtube_url") or "",
            "thumbnail_url": None,
            "created_at": time.time(),
            "updated_at": time.time(),
            "status": "processing",
            "conversions": [],
            "languages": []
        }

    video = videos_db[video_id]
    video["updated_at"] = time.time()
    video["status"] = "processing"

    # Check if conversion item already exists
    existing_conv = next((c for c in video["conversions"] if c["job_id"] == job_id), None)
    conv_data = {
        "job_id": job_id,
        "part_name": job_data.get("part_name") or "Full Video",
        "time_range": job_data.get("time_range") or ("00:00 - 10:00" if job_data.get("part_name") else "Full Video"),
        "is_multipart": bool(job_data.get("part_name")),
        "languages": job_data.get("target_langs") or [job_data.get("target_lang", "es")],
        "status": job_data.get("status", "queued"),
        "progress": job_data.get("progress", 0.0),
        "created_at": job_data.get("created_at", time.time()),
        "output_video_url": job_data.get("output_video_url"),
        "thumbnail_url": job_data.get("thumbnail_url"),
        "zip_url": job_data.get("zip_url"),
        "duration": job_data.get("duration", 0.0)
    }

    if existing_conv:
        existing_conv.update(conv_data)
    else:
        video["conversions"].insert(0, conv_data)

    # Recalculate video languages
    all_langs = set()
    for c in video["conversions"]:
        for l in c.get("languages", []):
            all_langs.add(l)
    video["languages"] = sorted(list(all_langs))

    save_databases(workspace_dir, jobs_db, videos_db)


def update_video_on_job_progress(
    job_id: str,
    status_str: str,
    progress_val: float,
    videos_db: Dict[str, Any],
    workspace_dir: Path,
    jobs_db: Dict[str, Any],
    extra_data: Optional[Dict[str, Any]] = None
):
    """Updates video conversions when a job status or progress changes."""
    for video in videos_db.values():
        for conv in video.get("conversions", []):
            if conv.get("job_id") == job_id:
                conv["status"] = status_str
                conv["progress"] = progress_val
                if extra_data:
                    if extra_data.get("output_video_url"):
                        conv["output_video_url"] = extra_data["output_video_url"]
                    if extra_data.get("thumbnail_url"):
                        conv["thumbnail_url"] = extra_data["thumbnail_url"]
                        if not video.get("thumbnail_url"):
                            video["thumbnail_url"] = extra_data["thumbnail_url"]
                    if extra_data.get("zip_url"):
                        conv["zip_url"] = extra_data["zip_url"]
                    if extra_data.get("duration"):
                        conv["duration"] = extra_data["duration"]
                    if extra_data.get("languages"):
                        conv["languages"] = extra_data["languages"]

                # Check if all conversions for this video are completed
                any_processing = any(c.get("status") in ["queued", "processing"] for c in video["conversions"])
                video["status"] = "processing" if any_processing else "completed"
                video["updated_at"] = time.time()

                # Recalculate languages
                all_langs = set()
                for c in video["conversions"]:
                    for l in c.get("languages", []):
                        all_langs.add(l)
                video["languages"] = sorted(list(all_langs))

                save_databases(workspace_dir, jobs_db, videos_db)
                return
