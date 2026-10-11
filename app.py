"""
ManhwaDub - Gradio UI for Local AI Video Dubbing
================================================
Interactive web interface running natively on Apple Silicon (M1 Pro/Max).
Features:
- Video upload & live preview
- Step-by-step progress tracking
- Audio stem inspection (Vocals vs BGM/SFX vs Spanish Vocals)
- Interactive timed transcript & translation table
- Side-by-side dubbed video player
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

import gradio as gr
from pipeline import ManhwaDubbingPipeline, AppleSiliconManager

# Ensure Apple Silicon MPS fallback is active
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

# Supported Target Languages and Neural Voices
VOICE_MAP = {
    # Spanish Presets
    "🇪🇸 Spanish (Spain - Alvaro Dramatic Male)": ("es", "es-ES-AlvaroNeural"),
    "🇲🇽 Spanish (Mexico - Jorge Energetic Male)": ("es", "es-MX-JorgeNeural"),
    "🇪🇸 Spanish (Spain - Elvira Expressive Female)": ("es", "es-ES-ElviraNeural"),
    "🇲🇽 Spanish (Mexico - Dalia Smooth Female)": ("es", "es-MX-DaliaNeural"),
    
    # Tamil (தமிழ்)
    "🇮🇳 Tamil (India - Valluvar Male)": ("ta", "ta-IN-ValluvarNeural"),
    "🇮🇳 Tamil (India - Pallavi Female)": ("ta", "ta-IN-PallaviNeural"),

    # Telugu (తెలుగు)
    "🇮🇳 Telugu (India - Mohan Male)": ("te", "te-IN-MohanNeural"),
    "🇮🇳 Telugu (India - Shruti Female)": ("te", "te-IN-ShrutiNeural"),

    # Bengali (বাংলা)
    "🇮🇳 Bengali (India - Bashkar Male)": ("bn", "bn-IN-BashkarNeural"),
    "🇮🇳 Bengali (India - Tanishaa Female)": ("bn", "bn-IN-TanishaaNeural"),
    "🇧🇩 Bengali (Bangladesh - Pradeep Male)": ("bn", "bn-BD-PradeepNeural"),

    # Hindi (हिन्दी)
    "🇮🇳 Hindi (India - Madhur Male)": ("hi", "hi-IN-MadhurNeural"),
    "🇮🇳 Hindi (India - Swara Female)": ("hi", "hi-IN-SwaraNeural"),

    # Kannada, Malayalam, Marathi
    "🇮🇳 Kannada (India - Gagan Male)": ("kn", "kn-IN-GaganNeural"),
    "🇮🇳 Kannada (India - Sapna Female)": ("kn", "kn-IN-SapnaNeural"),
    "🇮🇳 Malayalam (India - Midhun Male)": ("ml", "ml-IN-MidhunNeural"),
    "🇮🇳 Malayalam (India - Sobhana Female)": ("ml", "ml-IN-SobhanaNeural"),
    "🇮🇳 Marathi (India - Manohar Male)": ("mr", "mr-IN-ManoharNeural"),
    "🇮🇳 Marathi (India - Aarohi Female)": ("mr", "mr-IN-AarohiNeural"),

    # Indonesian (Bahasa Indonesia)
    "🇮🇩 Indonesian (Indonesia - Ardi Male)": ("id", "id-ID-ArdiNeural"),
    "🇮🇩 Indonesian (Indonesia - Gadis Female)": ("id", "id-ID-GadisNeural"),

    # French (Français)
    "🇫🇷 French (France - Henri Male)": ("fr", "fr-FR-HenriNeural"),
    "🇫🇷 French (France - Denise Female)": ("fr", "fr-FR-DeniseNeural"),

    # German (Deutsch)
    "🇩🇪 German (Germany - Conrad Male)": ("de", "de-DE-ConradNeural"),
    "🇩🇪 German (Germany - Katja Female)": ("de", "de-DE-KatjaNeural"),

    # Portuguese, Vietnamese, Arabic, Russian, Japanese
    "🇧🇷 Portuguese (Brazil - Antonio Male)": ("pt", "pt-BR-AntonioNeural"),
    "🇧🇷 Portuguese (Brazil - Francisca Female)": ("pt", "pt-BR-FranciscaNeural"),
    "🇻🇳 Vietnamese (Vietnam - Nam Minh Male)": ("vi", "vi-VN-NamMinhNeural"),
    "🇻🇳 Vietnamese (Vietnam - Hoai My Female)": ("vi", "vi-VN-HoaiMyNeural"),
    "🇸🇦 Arabic (Saudi - Hamed Male)": ("ar", "ar-SA-HamedNeural"),
    "🇪🇬 Arabic (Egypt - Salma Female)": ("ar", "ar-EG-SalmaNeural"),
    "🇷🇺 Russian (Russia - Dmitry Male)": ("ru", "ru-RU-DmitryNeural"),
    "🇷🇺 Russian (Russia - Svetlana Female)": ("ru", "ru-RU-SvetlanaNeural"),
    "🇯🇵 Japanese (Japan - Keita Male)": ("ja", "ja-JP-KeitaNeural"),
    "🇯🇵 Japanese (Japan - Nanami Female)": ("ja", "ja-JP-NanamiNeural"),
}


def process_video_dubbing(
    video_path: str,
    whisper_model: str,
    translation_engine: str,
    voice_selection: str,
    voice_clone: bool,
    bg_volume: float,
    vocals_volume: float,
    auto_speed_adjust: bool,
    progress=gr.Progress(track_tqdm=True)
):
    """Callback function executing the 5-step dubbing pipeline."""
    if not video_path:
        raise gr.Error("Please upload an English .mp4 video first.")

    target_lang, selected_voice = VOICE_MAP.get(voice_selection, ("es", "es-ES-AlvaroNeural"))
    input_path = Path(video_path)
    output_path = input_path.parent / f"{input_path.stem}_{target_lang}_dubbed.mp4"

    progress(0.0, desc="Initializing Apple Silicon hardware...")
    device_info = AppleSiliconManager.get_torch_device()

    # Initialize Pipeline
    pipeline = ManhwaDubbingPipeline(
        whisper_model=whisper_model,
        target_lang=target_lang,
        translation_engine=translation_engine,
        tts_engine="xtts" if voice_clone else "edge-tts",
        tts_voice=selected_voice,
        voice_clone=voice_clone,
        bg_volume=bg_volume,
        vocals_volume=vocals_volume,
    )

    log_history = []

    def progress_hook(pct: float, message: str):
        log_history.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        progress(pct, desc=message)

    try:
        progress_hook(0.02, f"Target device: Apple Silicon ({device_info.upper()})")
        result = pipeline.run(
            video_path=str(input_path),
            output_path=str(output_path),
            progress_callback=progress_hook
        )

        # Prepare segment data for Gradio Dataframe
        segments_data = []
        for s in result.get("segments", []):
            duration = round(s["end"] - s["start"], 2)
            segments_data.append([
                f"{s['start']:.2f}s",
                f"{s['end']:.2f}s",
                f"{duration:.2f}s",
                s.get("original_text", ""),
                s.get("text", "")
            ])

        status_msg = (
            f"✅ Dubbing Complete!\n"
            f"• Output Video: {Path(result['final_video']).name}\n"
            f"• Total Segments Dubbed: {len(segments_data)}\n"
            f"• Video Duration: {result.get('total_duration', 0.0):.1f}s"
        )

        return (
            result["final_video"],          # final video player
            status_msg,                     # status text
            result["original_audio"],       # audio: original
            result["vocals"],               # audio: separated vocals
            result["background"],           # audio: separated BGM/SFX
            result["spanish_vocals"],       # audio: synthesized spanish vocals
            segments_data,                  # table: subtitles & translations
            "\n".join(log_history)          # execution logs
        )

    except Exception as e:
        err_msg = f"❌ Pipeline Failed: {str(e)}"
        log_history.append(f"[{time.strftime('%H:%M:%S')}] ERROR: {str(e)}")
        raise gr.Error(err_msg)


def build_ui():
    """Builds the Gradio application layout."""
    custom_css = """
    .gradio-container { max-width: 1280px !important; margin: auto; }
    .hero-banner { text-align: center; margin-bottom: 20px; }
    .badge { background: #3b82f6; color: white; padding: 4px 10px; border-radius: 9999px; font-size: 0.8rem; font-weight: 600; display: inline-block; }
    """

    with gr.Blocks(title="ManhwaDub - Local AI Video Dubbing", css=custom_css, theme=gr.themes.Soft()) as demo:
        with gr.Column(elem_classes=["hero-banner"]):
            gr.Markdown(
                """
                # 🎙️ ManhwaDub Studio
                ### Local AI Video Dubbing Pipeline for Apple Silicon (M1 Pro/Max)
                <span class="badge">Apple Silicon MPS Accelerated</span>
                <span class="badge">Zero Cloud API Costs</span>
                <span class="badge">Demucs BGM Preservation</span>
                <span class="badge">faster-whisper</span>
                """
            )

        with gr.Row():
            # Left Column: Inputs & Configuration
            with gr.Column(scale=5):
                gr.Markdown("### 1. Video Input & Preview")
                video_input = gr.Video(
                    label="English Manhwa Recap / Motion Comic (.mp4)",
                    sources=["upload"],
                    height=280
                )

                gr.Markdown("### 2. AI Pipeline Configuration")
                with gr.Accordion("⚙️ Model & Performance Settings", open=True):
                    with gr.Row():
                        whisper_model = gr.Dropdown(
                            label="Whisper Speech-to-Text Model",
                            choices=["tiny", "base", "small", "medium"],
                            value="base",
                            info="M1 Pro runs 'base' & 'small' in near real-time"
                        )
                        translation_engine = gr.Dropdown(
                            label="Translation Engine",
                            choices=[
                                ("deep-translator (Fast Online)", "deep-translator"),
                                ("Helsinki-NLP/opus-mt-en-es (100% Offline HuggingFace)", "helsinki-nlp")
                            ],
                            value="deep-translator",
                            info="Translates while retaining exact timestamps"
                        )

                    with gr.Row():
                        voice_selection = gr.Dropdown(
                            label="Target Language & Narrator Voice",
                            choices=list(VOICE_MAP.keys()),
                            value="🇪🇸 Spanish (Spain - Alvaro Dramatic Male)",
                            info="Select Spanish, Tamil, Telugu, Bengali, Hindi, etc."
                        )
                        voice_clone = gr.Checkbox(
                            label="Zero-Shot Voice Cloning (Coqui XTTS-v2)",
                            value=False,
                            info="Clones original English narrator's timbre"
                        )

                    with gr.Row():
                        bg_volume = gr.Slider(
                            minimum=0.0,
                            maximum=1.5,
                            value=0.80,
                            step=0.05,
                            label="Original BGM & SFX Volume",
                            info="Ducks background music under dialogue"
                        )
                        vocals_volume = gr.Slider(
                            minimum=0.0,
                            maximum=1.5,
                            value=1.00,
                            step=0.05,
                            label="Spanish Dialogue Volume",
                            info="Volume of generated Spanish vocals"
                        )

                    auto_speed_adjust = gr.Checkbox(
                        label="Dynamic Time-Stretching Synchronization",
                        value=True,
                        info="Dynamically speeds up speech (max 1.3x) to match panel timing"
                    )

                start_btn = gr.Button("🚀 Start Local Dubbing Pipeline", variant="primary", size="lg")

            # Right Column: Dubbed Output & Inspection
            with gr.Column(scale=6):
                gr.Markdown("### 3. Final Dubbed Video Output")
                output_video = gr.Video(
                    label="Dubbed Spanish Video (-c:v copy, BGM Preserved)",
                    height=360
                )
                status_box = gr.Textbox(label="Status & Summary", interactive=False)

        gr.Markdown("---")
        gr.Markdown("### 🔬 Intermediate Audio Stems & Transcript Inspection")

        with gr.Tabs():
            with gr.TabItem("🎧 Audio Stems"):
                gr.Markdown("Listen to the isolated tracks produced during Demucs separation and TTS alignment:")
                with gr.Row():
                    audio_orig = gr.Audio(label="1. Original Full Audio", interactive=False)
                    audio_vocals = gr.Audio(label="2. Isolated English Vocals (Demucs)", interactive=False)
                with gr.Row():
                    audio_bg = gr.Audio(label="3. Isolated BGM & SFX (Preserved)", interactive=False)
                    audio_es_vocals = gr.Audio(label="4. Synthesized Spanish Vocals", interactive=False)

            with gr.TabItem("📝 Timed Subtitles & Translations"):
                gr.Markdown("Exact timeline breakdown of transcribed English speech and Spanish translation:")
                segments_table = gr.Dataframe(
                    headers=["Start", "End", "Duration", "Original English Speech", "Spanish Translation"],
                    datatype=["str", "str", "str", "str", "str"],
                    interactive=False,
                    wrap=True
                )

            with gr.TabItem("📋 Execution Logs"):
                logs_display = gr.Textbox(
                    label="Real-time Pipeline Terminal Logs",
                    lines=10,
                    interactive=False
                )

        # Wire Up Event Listeners
        start_btn.click(
            fn=process_video_dubbing,
            inputs=[
                video_input,
                whisper_model,
                translation_engine,
                voice_selection,
                voice_clone,
                bg_volume,
                vocals_volume,
                auto_speed_adjust,
            ],
            outputs=[
                output_video,
                status_box,
                audio_orig,
                audio_vocals,
                audio_bg,
                audio_es_vocals,
                segments_table,
                logs_display,
            ]
        )

    return demo


if __name__ == "__main__":
    demo = build_ui()
    # Launch on localhost
    demo.queue().launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        show_error=True
    )
