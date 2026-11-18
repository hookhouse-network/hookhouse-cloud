"""Weekly GPU batch — runs inside a PRIVATE Kaggle notebook (free GPU).

Input : gpu_jobs.json  -> {"images": [{"key", "prompt"}], "motion": [{"key", "prompt"}]}
Output: out/<key>.png (FLUX.1-schnell, Apache 2.0)  and  out/<key>.mp4 (Wan 2.1 T2V 1.3B, Apache 2.0)
The files are copied into data/gpu_batch/ on the worker, where visuals.ai_image() finds them by key.

Status: written in Week 2, NOT yet tested (needs the Kaggle account + rules check in Week 3).
Kaggle setup: GPU accelerator on, Internet on (phone-verified account), add gpu_jobs.json as a dataset.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import torch

JOBS = Path(sys.argv[1] if len(sys.argv) > 1 else "/kaggle/input/gpu-jobs/gpu_jobs.json")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "/kaggle/working/out")
OUT.mkdir(parents=True, exist_ok=True)

IMG_W, IMG_H = 768, 1344           # 9:16, upscaled later by the renderer
MOTION_W, MOTION_H, MOTION_FRAMES = 480, 832, 81   # ~5 s at 16 fps


def run_images(jobs: list[dict]) -> None:
    todo = [j for j in jobs if not (OUT / f"{j['key']}.png").exists()]
    if not todo:
        return
    from diffusers import FluxPipeline
    pipe = FluxPipeline.from_pretrained("black-forest-labs/FLUX.1-schnell", torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()   # fits a 16 GB T4
    for j in todo:
        image = pipe(j["prompt"], width=IMG_W, height=IMG_H, num_inference_steps=4, guidance_scale=0.0,
                     max_sequence_length=256, generator=torch.Generator("cpu").manual_seed(0)).images[0]
        image.save(OUT / f"{j['key']}.png")
        print("image", j["key"], flush=True)
    del pipe
    torch.cuda.empty_cache()


def run_motion(jobs: list[dict]) -> None:
    todo = [j for j in jobs if not (OUT / f"{j['key']}.mp4").exists()]
    if not todo:
        return
    from diffusers import AutoencoderKLWan, WanPipeline
    from diffusers.utils import export_to_video
    model = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
    vae = AutoencoderKLWan.from_pretrained(model, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanPipeline.from_pretrained(model, vae=vae, torch_dtype=torch.float16)
    pipe.enable_model_cpu_offload()
    for j in todo:
        frames = pipe(prompt=j["prompt"], negative_prompt="blurry, low quality, text, watermark, distorted",
                      height=MOTION_H, width=MOTION_W, num_frames=MOTION_FRAMES, guidance_scale=5.0).frames[0]
        export_to_video(frames, str(OUT / f"{j['key']}.mp4"), fps=16)
        print("motion", j["key"], flush=True)


if __name__ == "__main__":
    jobs = json.loads(JOBS.read_text(encoding="utf-8"))
    run_images(jobs.get("images", []))
    run_motion(jobs.get("motion", []))
    print("done", flush=True)
