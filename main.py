#!/usr/bin/env python3
"""
================================================================================
ManhwaDub: Local AI Video Dubbing Automation Script (Apple Silicon M1 Pro/Max)
================================================================================

OBJECTIVE:
Takes an English 'Manhwa recap / motion comic' video (.mp4) and completely dubs
it into Spanish locally, preserving original background music (BGM) and sound effects (SFX).

--------------------------------------------------------------------------------
MACOS & APPLE SILICON SETUP INSTRUCTIONS (One-Time Setup):
--------------------------------------------------------------------------------
1. Install Homebrew (if not already installed) & System Dependencies:
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install ffmpeg python@3.11

2. Create and Activate Virtual Environment (Recommended: Python 3.11):
   python3.11 -m venv venv
   source venv/bin/activate

3. Install Core Python Dependencies:
   pip install --upgrade pip setuptools wheel
   pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
   pip install demucs
   pip install faster-whisper
   pip install deep-translator
   pip install transformers sentencepiece
   pip install edge-tts
   pip install soundfile numpy scipy
   pip install gradio rich

4. Optional Voice Cloning (XTTS-v2):
   pip install TTS

--------------------------------------------------------------------------------
USAGE:
--------------------------------------------------------------------------------
Launch Web UI:
   python app.py

Run CLI Headless:
   python main.py --input /path/to/recap.mp4 --output /path/to/dubbed_spanish.mp4
================================================================================
"""

import os
import sys
import argparse
from pathlib import Path
from pipeline import ManhwaDubbingPipeline, AppleSiliconManager, DEFAULT_LANGUAGE_VOICES, resolve_voice, logger

def parse_args():
    parser = argparse.ArgumentParser(
        description="Local AI Video Dubbing Pipeline for Apple Silicon (M1 Pro/Max)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        required=True,
        help="Path to input English video file (.mp4)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Path to finalized dubbed video file (.mp4)"
    )
    parser.add_argument(
        "--whisper-model",
        type=str,
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size for speech-to-text"
    )
    parser.add_argument(
        "--translator",
        type=str,
        default="deep-translator",
        choices=["deep-translator", "helsinki-nlp"],
        help="Translation backend: fast online (deep-translator) or 100%% offline (helsinki-nlp)"
    )
    parser.add_argument(
        "--tts-engine",
        type=str,
        default="edge-tts",
        choices=["edge-tts", "xtts"],
        help="TTS engine: neural narration (edge-tts) or zero-shot voice cloning (xtts)"
    )
    parser.add_argument(
        "--voice",
        type=str,
        default=None,
        help="Voice identifier for neural TTS (auto-selected for target language if omitted, e.g. de-DE-ConradNeural, fr-FR-HenriNeural, id-ID-ArdiNeural)"
    )
    parser.add_argument(
        "--gender",
        type=str,
        default=None,
        choices=["male", "female"],
        help="Voice gender preference: 'male' or 'female'"
    )
    parser.add_argument(
        "--voice-clone",
        action="store_true",
        help="Enable zero-shot voice cloning using original English vocals as reference"
    )
    parser.add_argument(
        "--bg-volume",
        type=float,
        default=0.80,
        help="Background music and SFX volume ducking level (0.0 to 1.5)"
    )
    parser.add_argument(
        "--target-lang",
        type=str,
        default="es",
        help="Target language ISO code (e.g. es for Spanish, ta for Tamil, te for Telugu, bn for Bengali, hi for Hindi)"
    )
    parser.add_argument(
        "--langs",
        type=str,
        default=None,
        help="Comma-separated target languages for multi-language batch (e.g. 'de,fr,id,es,hi')"
    )
    parser.add_argument(
        "--vocals-volume",
        type=float,
        default=1.00,
        help="Voiceover volume level (0.0 to 1.5)"
    )
    parser.add_argument(
        "--start-seconds",
        type=float,
        default=None,
        help="Start timestamp in seconds to trim a part (e.g. 0, 1800 for 30m, 3600 for 1h)"
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Duration in seconds of the part (e.g. 1800 for 30 mins, 3600 for 1 hr)"
    )
    parser.add_argument(
        "--watermark-text",
        type=str,
        default=None,
        help="Optional floating light-white watermark text jumping randomly every 2-4 seconds (e.g. '@MyChannel')"
    )
    parser.add_argument(
        "--watermark-interval",
        type=float,
        default=3.0,
        help="Interval in seconds for watermark to jump (default: 3.0s, range 2-4s)"
    )
    parser.add_argument(
        "--shorts",
        action="store_true",
        help="Generate top climax moments 9:16 vertical shorts for Instagram Reels / YouTube Shorts"
    )
    parser.add_argument(
        "--num-shorts",
        type=int,
        default=3,
        help="Number of shorts to create from top moments (default: 3)"
    )
    parser.add_argument(
        "--short-duration",
        type=float,
        default=45.0,
        help="Duration in seconds per short (default: 45.0s, recommended 30-60s)"
    )
    parser.add_argument(
        "--aspect-ratio",
        type=str,
        default="9:16",
        choices=["9:16", "16:9"],
        help="Aspect ratio for shorts (default: '9:16' vertical with blurred wings)"
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch the interactive Gradio web UI instead of CLI execution"
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Launch the FastAPI production REST server"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Launch FastAPI Server if requested
    if args.api:
        port = int(os.environ.get("PORT", "3333"))
        print(f"Starting FastAPI REST API server on http://127.0.0.1:{port} ...")
        uvicorn.run("api:app", host="127.0.0.1", port=port, reload=True)
        return

    # Launch UI if requested
    if args.ui:
        print("Starting Gradio Web Studio...")
        from app import build_ui
        demo = build_ui()
        demo.queue().launch(server_name="127.0.0.1", server_port=7860)
        return


    # Validate environment
    print("\n" + "=" * 70)
    print("🎬 MANHWADUB: LOCAL AI VIDEO DUBBING PIPELINE")
    print("=" * 70)
    
    device = AppleSiliconManager.get_torch_device()
    target_langs_list = [l.strip().lower() for l in args.langs.split(",") if l.strip()] if args.langs else [args.target_lang.lower()]
    primary_lang = target_langs_list[0]
    selected_voice = args.voice or resolve_voice(primary_lang, args.gender)

    print(f"• Hardware Target  : Apple Silicon (device='{device}')")
    print(f"• Input Video      : {args.input}")
    print(f"• Target Languages : {', '.join([l.upper() for l in target_langs_list])}")
    print(f"• Voice Gender     : {args.gender.capitalize() if args.gender else 'Auto/Default'}")
    print(f"• Primary Voice    : {selected_voice}")
    print(f"• Whisper Model    : {args.whisper_model}")
    print(f"• Translator Engine: {args.translator}")
    print(f"• TTS Mode         : {'Voice Cloning (XTTS-v2)' if args.voice_clone else f'Neural TTS ({selected_voice})'}")
    if args.watermark_text:
        print(f"• Watermark Text   : '{args.watermark_text}' (light-white, jumping every {args.watermark_interval}s)")
    print("=" * 70 + "\n")

    pipeline = ManhwaDubbingPipeline(
        whisper_model=args.whisper_model,
        target_lang=primary_lang,
        translation_engine=args.translator,
        tts_engine=args.tts_engine,
        tts_voice=selected_voice,
        voice_gender=args.gender,
        voice_clone=args.voice_clone,
        bg_volume=args.bg_volume,
        vocals_volume=args.vocals_volume,
        enable_watermark=bool(args.watermark_text),
        watermark_text=args.watermark_text,
        watermark_interval=args.watermark_interval,
    )

    try:
        result = pipeline.run(
            video_path=args.input,
            output_path=args.output,
            target_langs=target_langs_list,
            start_seconds=args.start_seconds,
            duration_seconds=args.duration_seconds,
            generate_shorts=args.shorts,
            shorts_count=args.num_shorts,
            short_duration=args.short_duration,
            shorts_aspect_ratio=args.aspect_ratio,
        )
        print("\n" + "=" * 70)
        print("🎉 SUCCESS! DUBBING PIPELINE COMPLETED")
        print("=" * 70)
        if result.get("languages"):
            print("📁 Created Language Folders:")
            for l_code, l_info in result["languages"].items():
                print(f"  • {l_info['lang_name']}: {l_info['folder']}")
                print(f"    - Video: {l_info['final_video']}")
                if l_info.get("shorts"):
                    print(f"    - 📱 Instagram Shorts ({len(l_info['shorts'])} created in {l_info['lang_name']}/Shorts/):")
                    for s in l_info["shorts"]:
                        print(f"      • {s['title']} ({s['time_range']}): {s['filename']}")
        print(f"• Primary Video  : {result['final_video']}")
        if result.get("zip_path"):
            print(f"• ZIP Package    : {result['zip_path']}")
        print(f"• Segments Dubbed: {len(result['segments'])}")
        print("=" * 70 + "\n")
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
