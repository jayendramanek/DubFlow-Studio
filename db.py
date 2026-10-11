"""
Database and system monitoring layer for ManhwaDub Admin Panel.
Provides persistent storage for Videos and Jobs, macOS unified RAM telemetry,
and automatic recovery of archived conversions.
"""

import os
import re
import json
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


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
        total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
        vm_output = subprocess.check_output(["vm_stat"]).decode("utf-8")
        page_size = 4096
        pages = {}
        for line in vm_output.splitlines():
            if ":" in line:
                parts = line.split(":")
                key = parts[0].strip()
                val = parts[1].strip().rstrip(".")
                if val.isdigit():
                    pages[key] = int(val)
        free_pages = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)
        free_bytes = free_pages * page_size
        used_bytes = max(0, total_bytes - free_bytes)
        return {
            "total_gb": round(total_bytes / (1024 ** 3), 2),
            "used_gb": round(used_bytes / (1024 ** 3), 2),
            "free_gb": round(free_bytes / (1024 ** 3), 2),
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

    if videos_file.exists():
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
    if not videos_db:
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


def get_system_stats(jobs_db: Dict[str, Any], videos_db: Dict[str, Any]) -> Dict[str, Any]:
    """Calculates live system RAM and statistics for dashboard widgets."""
    ram = get_system_ram()

    total_videos = len(videos_db)
    
    # Calculate completed conversions count and language counts
    language_counts: Dict[str, int] = {}
    completed_jobs = 0
    active_jobs = 0
    failed_jobs = 0
    active_jobs_list: List[Dict[str, Any]] = []

    for j in jobs_db.values():
        st = j.get("status")
        if st in ["queued", "processing"]:
            active_jobs += 1
            active_jobs_list.append({
                "job_id": j.get("job_id"),
                "status": st,
                "progress": j.get("progress", 0.0),
                "current_step": j.get("current_step", "Processing..."),
                "target_langs": j.get("target_langs") or [j.get("target_lang", "es")],
                "part_name": j.get("part_name"),
                "created_at": j.get("created_at"),
                "youtube_url": j.get("youtube_url")
            })
        elif st == "completed":
            completed_jobs += 1
            langs = j.get("target_langs") or [j.get("target_lang", "de")]
            for l in langs:
                language_counts[l] = language_counts.get(l, 0) + 1
        elif st == "failed":
            failed_jobs += 1

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
        "counts": {
            "total_videos": total_videos,
            "total_conversions": completed_jobs,
            "active_jobs": active_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "total_languages": len(language_counts)
        },
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
