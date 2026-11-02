"""Lazy local Transformers adapter; no PDF text-layer extraction or OCR fallback."""
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = os.getenv('XIAOMI_MODEL', str(ROOT / 'models/xiaomi-ocr-0'))
PROMPT = ('Extract all information from the main body of the document image and represent it '
          'in markdown format, ignoring headers and footers. Tables should be expressed in OTSL '
          'format, formulas in the document should be represented using LATEX format, and the '
          'parsing should be organized according to the reading order.')


class Engine:
    def __init__(self):
        self.model = None
        self.device = None
        self.load_seconds = None

    def load(self):
        if self.model is not None:
            return
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        started = time.perf_counter()
        self.device = os.getenv('XIAOMI_DEVICE', 'auto')
        if self.device == 'auto':
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.processor = AutoProcessor.from_pretrained(MODEL, local_files_only=True)
        self.model = AutoModelForImageTextToText.from_pretrained(
            MODEL, local_files_only=True,
            dtype=torch.float32 if self.device == 'cpu' else torch.float16,
            attn_implementation='sdpa',
        ).to(self.device).eval()
        self.load_seconds = round(time.perf_counter() - started, 3)

    def recognize(self, image, max_tokens, cancelled):
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        class Cancel(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return cancelled()

        messages = [{'role': 'user', 'content': [
            {'type': 'image', 'image': image}, {'type': 'text', 'text': PROMPT}]}]
        inputs = self.processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors='pt', enable_thinking=False,
        ).to(self.device)
        with torch.inference_mode():
            output = self.model.generate(
                **inputs, max_new_tokens=max_tokens, do_sample=False,
                stopping_criteria=StoppingCriteriaList([Cancel()]),
            )
        tokens = output[:, inputs['input_ids'].shape[1]:]
        raw = self.processor.batch_decode(tokens, skip_special_tokens=True)[0]
        return raw, tokens.shape[1], tokens.shape[1] >= max_tokens
