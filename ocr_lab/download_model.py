"""Fetch a pinned HF snapshot; runtime inference is strictly local."""
import json
from pathlib import Path
import hashlib
import urllib.request
import ssl
from concurrent.futures import ThreadPoolExecutor
import certifi
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
REPO = 'SeerRay-Lab/Xiaomi-OCR-0'
manifest = ROOT / 'ocr_lab/model.json'


def main():
    revision = json.loads(manifest.read_text())['revision'] if manifest.exists() else HfApi().model_info(REPO).sha
    manifest.write_text(json.dumps({'repo': REPO, 'revision': revision}, indent=2) + '\n', encoding='utf-8')
    target = ROOT / 'models/xiaomi-ocr-0'
    print(f'Downloading {REPO} @ {revision}', flush=True)
    context = ssl.create_default_context(cafile=certifi.where())
    def fetch(url, headers=None):
        request = urllib.request.Request(url, headers={'User-Agent': 'XiaomiOCRLab/1.0', **(headers or {})})
        return urllib.request.urlopen(request, context=context, timeout=120)
    with fetch(f'https://huggingface.co/api/models/{REPO}/tree/{revision}?recursive=true') as response:
        files = json.load(response)
    for item in files:
        name = item['path']
        if item['type'] != 'file' or '/' in name or not name.endswith(('.json', '.safetensors', '.model', '.txt', '.jinja')):
            continue
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        expected = item.get('lfs', {}).get('oid')
        def valid():
            if not dest.exists() or dest.stat().st_size != item['size']:
                return False
            with dest.open('rb') as stream:
                return not expected or hashlib.file_digest(stream, 'sha256').hexdigest() == expected
        if valid():
            continue
        url = f'https://huggingface.co/{REPO}/resolve/{revision}/{name}'
        if item['size'] < 1024 * 1024:
            with fetch(url) as response:
                dest.write_bytes(response.read())
            if not valid():
                raise RuntimeError(f'Invalid download: {name}')
            continue
        # Standard HTTP ranges avoid a dependency on Xet transfer hosts and resume each chunk.
        chunk_dir = ROOT / 'models/downloads/xiaomi-ocr-0' / name
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_size = 4 * 1024 * 1024
        count = (item['size'] + chunk_size - 1) // chunk_size
        def piece(index):
            import time
            start = index * chunk_size
            end = min(item['size'] - 1, start + chunk_size - 1)
            part = chunk_dir / str(index)
            if part.exists() and part.stat().st_size == end - start + 1:
                return
            for attempt in range(4):
                try:
                    with fetch(url + f'?download=true&ocrPart={index}', {'Range': f'bytes={start}-{end}'}) as response:
                        data = response.read()
                        if response.status != 206 or len(data) != end - start + 1:
                            raise RuntimeError('Server returned an invalid range')
                    part.write_bytes(data)
                    return
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(attempt + 1)
        print(f'{name}: {item["size"] / 1048576:.1f} MB', flush=True)
        with ThreadPoolExecutor(max_workers=16) as executor:
            for n, _ in enumerate(executor.map(piece, range(count)), 1):
                if n % 16 == 0 or n == count:
                    print(f'  {n}/{count} chunks', flush=True)
        partial = dest.with_suffix(dest.suffix + '.part')
        with partial.open('wb') as out:
            for index in range(count):
                out.write((chunk_dir / str(index)).read_bytes())
        partial.replace(dest)
        if not valid():
            raise RuntimeError(f'SHA-256 mismatch: {name}. Remove chunk files in {chunk_dir} and retry.')
    print(f'Model ready: {target}', flush=True)


if __name__ == '__main__':
    main()
