"""Test: Task 10 first image with chinese_docu Steve McCurry style."""
import asyncio, base64, os, sys, time, sqlite3, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
import httpx
from services.llm_service import extract_visual_context
from services.image_service import *

async def main():
    conn = sqlite3.connect(str(Path(__file__).parent.parent / "data" / "app.db"))
    cur = conn.cursor()
    cur.execute('SELECT rewritten_transcript FROM tasks WHERE id=10')
    text = cur.fetchone()[0]
    conn.close()

    raw = re.split(r'(?<=[。！？；\n])', text)
    sentences = [s.strip() for s in raw if s.strip() and len(s.strip()) >= 5]
    first = sentences[0]
    print(f'Task 10: {len(sentences)} sentences')
    print(f'First: {first[:80]}...')

    style = 'chinese_docu'
    style_bible = STYLE_BIBLES.get(style, STYLE_BIBLES['default'])

    print('\n--- Pipeline ---')
    vc = await extract_visual_context(text)
    sp = await generate_screenplay(text, '', '', vc, style, len(sentences), sentences, 'auto')
    if sp and len(sp.get('character_cast', [])) == 0:
        fb = _parse_visual_context_fallback(vc)
        if fb: sp['character_cast'] = fb
    sb = await generate_storyboard(sp, sentences, vc, len(sentences))
    if sb:
        sb['face_policy'] = sp.get('face_policy', 'show')
        sb['character_cast'] = sp.get('character_cast', [])

    prompt = build_single_segment_prompt(
        text=first, book_title='', book_author='',
        segment_index=0, total_segments=len(sentences),
        style_bible=style_bible, style_key=style, aspect_ratio='9:16',
        visual_context=vc, visual_plan=None, storyboard=sb,
    )

    print(f'\n--- Prompt ({len(prompt)} chars) ---')
    print(prompt[:200])
    print('...')
    print(prompt[-200:])

    FAL_KEY = os.getenv('FAL_KEY', '')
    url = 'https://fal.run/openai/gpt-image-2'
    headers = {'Authorization': f'Key {FAL_KEY}', 'Content-Type': 'application/json'}
    payload = {
        'prompt': prompt,
        'image_size': {'width': 2160, 'height': 3840},
        'quality': 'low',
        'num_images': 1,
        'output_format': 'png',
        'sync_mode': True,
    }

    print('\n--- Generating (gpt-image-2 low) ---')
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)
    elapsed = time.time() - t0

    if resp.status_code != 200:
        print(f'FAIL HTTP {resp.status_code}: {resp.text[:300]}')
        return

    data = resp.json()
    img_url = data['images'][0]['url']
    if img_url.startswith('data:'):
        b64 = img_url.split(',', 1)[1]
        img_bytes = base64.b64decode(b64)
    else:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as dl:
            r2 = await dl.get(img_url)
            img_bytes = r2.content

    out = Path(__file__).parent.parent / 'data' / 'tasks' / '10' / 'images'
    out.mkdir(parents=True, exist_ok=True)
    fp = out / 'seg_000_chinese_docu_test.png'
    fp.write_bytes(img_bytes)
    print(f'OK ({elapsed:.0f}s, {len(img_bytes)/1024:.0f}KB) -> {fp}')

asyncio.run(main())
