"""PlantDoc web UI (Gradio). Run with:  python app.py"""
from __future__ import annotations

import gradio as gr

from diagnose import BACKENDS, DiagnosisError, diagnose, to_markdown
from weather import WeatherError, fetch_weather, summarize, weather_tips

try:  # optional: load GEMINI_API_KEY from a local .env file
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

LANGUAGES = ["English", "Français", "العربية"]


def run(image, backend: str, language: str, plant_hint: str, city: str) -> str:
    if image is None:
        return "Upload or take a photo of a plant first."

    weather, note = None, ""
    if city and city.strip():
        try:
            weather = fetch_weather(city.strip())
        except WeatherError as exc:
            note = f"_Weather skipped: {exc}_\n\n"

    try:
        report = diagnose(
            image,
            backend=backend,
            language=language,
            plant_hint=plant_hint or "",
            weather_summary=summarize(weather) if weather else "",
        )
    except DiagnosisError as exc:
        return f"**Could not diagnose this photo:** {exc}"

    tips = weather_tips(report, weather) if weather else []
    return note + to_markdown(report, tips)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="PlantDoc") as demo:
        gr.Markdown(
            "# 🌿 PlantDoc\n"
            "Take or upload a photo of a plant. An open-weight AI model (Gemma 4) "
            "checks its health and suggests what to do."
        )
        with gr.Row():
            with gr.Column():
                image = gr.Image(
                    type="pil", sources=["upload", "webcam"], label="Plant photo", height=360
                )
                plant_hint = gr.Textbox(
                    label="Plant name (optional)", placeholder="e.g. tomato, olive tree, mint"
                )
                city = gr.Textbox(
                    label="City for weather-aware tips (optional)", placeholder="e.g. Rabat"
                )
                with gr.Row():
                    language = gr.Dropdown(LANGUAGES, value="English", label="Language")
                    backend = gr.Dropdown(
                        list(BACKENDS), value="gemini", label="Model backend"
                    )
                go = gr.Button("Diagnose", variant="primary")
            with gr.Column():
                out = gr.Markdown("The report will appear here.")
        go.click(run, [image, backend, language, plant_hint, city], out)
    return demo


if __name__ == "__main__":
    build_ui().launch()
