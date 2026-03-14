"""
Optional Gemini AI image enhancement for static heatmap exports.

Sends the full rendered heatmap to Gemini for cartoonification.
"""

import io
import os
import logging
from typing import Optional

from PIL import Image
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

ENHANCE_PROMPT = (
    "Edit this running heatmap image to make it fun and visually stunning "
    "for social media sharing.\n\n"
    "PRESERVE EXACTLY — DO NOT CHANGE:\n"
    "- The glowing heatmap route lines — their exact shapes, positions, colors, "
    "and density. These are real GPS data and are sacred.\n"
    "- The overall layout — same number of panels, same positions\n"
    "- All text content must remain readable (location names, run counts, distances)\n\n"
    "CARTOONIFY THE BASEMAP:\n"
    "- Transform the topographic map underneath the routes into a fun, illustrated, "
    "cartoon-style map — think hand-drawn style with bold outlines and bright colors\n"
    "- Simplify roads into thick cartoon lines, make water bright blue, "
    "add illustrated hills/trees/buildings where terrain features exist\n"
    "- The geography must stay accurate — same roads, rivers, coastlines, "
    "same positions — just restyled as a playful cartoon illustration\n"
    "- The heatmap route lines sit ON TOP of this cartoonified map unchanged\n\n"
    "LABEL PLACES:\n"
    "- Read the place names visible on the underlying map and add subtle, "
    "small labels for the major cities and towns in each panel\n"
    "- Place each label at the correct geographic position on the map\n"
    "- Labels should blend naturally into the map like normal map text — "
    "small, understated, NOT banners or ribbons. Think standard cartography.\n\n"
    "DECORATE:\n"
    "- RESTYLE the text — use playful hand-drawn fonts, banners, or ribbons "
    "for titles, location names, and stats\n"
    "- ADD running-themed decorations in the margins and corners — cartoon runners, "
    "shoes, medals, finish flags, or other playful elements\n"
    "- ADD decorative borders or frames around the map panels\n\n"
    "The route lines must look identical to the input — they are the star of the image. "
    "Everything else (map, text, margins) should be cartoonified and fun."
)

_MIME_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}


def enhance_image_with_gemini(
    input_path: str,
    output_path: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Enhance a heatmap image using Gemini's image generation.

    Sends the full rendered image to Gemini for cartoonification.
    """
    if output_path is None:
        output_path = input_path

    resolved_key = api_key or os.environ.get('GEMINI_API_KEY')
    if not resolved_key:
        raise ValueError(
            "No Gemini API key provided. Set GEMINI_API_KEY env var or pass api_key."
        )

    img = Image.open(input_path)
    logger.info(f"Sending image at full resolution: {img.size[0]}x{img.size[1]}")

    ext = os.path.splitext(input_path)[1].lower()
    mime_type = _MIME_TYPES.get(ext, 'image/png')

    buf = io.BytesIO()
    save_format = 'JPEG' if mime_type == 'image/jpeg' else 'PNG'
    img.save(buf, format=save_format)
    image_bytes = buf.getvalue()

    client = genai.Client(api_key=resolved_key)

    logger.info("Sending image to Gemini for enhancement...")
    response = client.models.generate_content(
        model="gemini-3-pro-image-preview",
        contents=[
            types.Content(
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    types.Part.from_text(text=ENHANCE_PROMPT),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.text:
            logger.info(f"Gemini response text: {part.text[:200]}")

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            enhanced_bytes = part.inline_data.data
            out_ext = os.path.splitext(output_path)[1].lower()
            out_mime = _MIME_TYPES.get(out_ext, 'image/png')

            enhanced_img = Image.open(io.BytesIO(enhanced_bytes))
            logger.info(
                f"Enhanced image: {enhanced_img.size[0]}x{enhanced_img.size[1]}, "
                f"{len(enhanced_bytes):,} bytes"
            )
            out_format = 'JPEG' if out_mime == 'image/jpeg' else 'PNG'
            enhanced_img.save(output_path, format=out_format)
            logger.info(f"Saved Gemini-enhanced image to {output_path}")
            return output_path

    raise ValueError("Gemini response contained no image data")
