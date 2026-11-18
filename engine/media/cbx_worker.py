"""Runs INSIDE the separate Chatterbox environment (~/cbx), never imported by the main system.

Usage: python cbx_worker.py jobs.json
jobs.json = {"model_dir": "...", "ref": "...", "threads": 8,
             "lines": [{"text": "...", "out": "...wav", "exaggeration": 0.6, "cfg": 0.4}, ...]}
Writes one wav per line (24 kHz) and prints "DONE <n>" at the end. Lines already on disk are skipped, so a crashed
batch resumes where it stopped."""
import json
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
from chatterbox.models.s3gen import S3Gen
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

_orig = S3Gen.load_state_dict
S3Gen.load_state_dict = lambda self, sd, strict=True, **kw: _orig(self, sd, strict=False, **kw)   # v3 file omits buffers


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    torch.set_num_threads(int(job.get("threads", 8)))
    torch.manual_seed(int(job.get("seed", 7)))
    model = ChatterboxMultilingualTTS.from_local(Path(job["model_dir"]), "cpu")
    done = 0
    for k, ln in enumerate(job["lines"]):
        out = Path(ln["out"])
        if out.exists() and out.stat().st_size > 1000:
            done += 1
            continue
        t0 = time.time()
        wav = model.generate(ln["text"], language_id=job.get("language", "hi"), audio_prompt_path=job["ref"],
                             exaggeration=float(ln.get("exaggeration", 0.6)), cfg_weight=float(ln.get("cfg", 0.4)))
        tmp = out.with_suffix(".part.wav")
        sf.write(str(tmp), wav.squeeze().numpy(), model.sr)
        tmp.replace(out)
        done += 1
        print(f"LINE {k + 1}/{len(job['lines'])} {time.time() - t0:.0f}s", flush=True)
    print(f"DONE {done}", flush=True)


if __name__ == "__main__":
    main()
