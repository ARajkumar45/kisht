"""Fake microphone: play caller WAV files into a Bolna agent exactly like voice_chat.py does,
and record what comes back and how fast.

    .venv312 python (Bolna's) tools/voice_probe.py --agent <id> line1.wav line2.wav ...

Each file is streamed as 16 kHz 16-bit mono PCM in 100 ms frames at real-time pace, then
silence frames are streamed until the agent has replied (speech-to-text needs the silence
to detect the end of the utterance). Per line it records:
  speech_end -> first reply audio  (what a caller feels as "reply time")
  reply audio length, bytes, and the WAV saved to --out-dir for listening.
The bridge log / audit file hold the text side (transcript as heard, reply, model time).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
import wave
from pathlib import Path

import websockets

FRAME_MS = 100
IN_RATE = 16000
OUT_RATE = 24000
FRAME_BYTES = IN_RATE * 2 * FRAME_MS // 1000      # 3200
SILENCE = b"\x00" * FRAME_BYTES


def pcm16_mono_16k(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (IN_RATE, 1, 2), \
            f"{path}: need 16 kHz mono 16-bit, got {w.getframerate()} Hz {w.getnchannels()} ch"
        return w.readframes(w.getnframes())


async def run(agent: str, files: list[Path], out_dir: Path, host: str,
              reply_wait: float, quiet_end: float) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    async with websockets.connect(f"ws://{host}/chat/v1/{agent}", max_size=None) as ws:
        await ws.send(json.dumps({"type": "init", "meta_data": {}}))
        reply = bytearray()
        state = {"first_audio": None, "last_audio": None, "cleared": 0, "marks": 0}

        async def listener():
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if msg.get("type") == "audio":
                    now = time.perf_counter()
                    if state["first_audio"] is None:
                        state["first_audio"] = now
                    state["last_audio"] = now
                    reply.extend(base64.b64decode(msg["data"]))
                elif msg.get("type") == "clear":
                    state["cleared"] += 1
                elif msg.get("type") == "mark":
                    # Bolna learns what the caller heard from these acknowledgements; the
                    # welcome message counts as "still playing" until its mark comes back.
                    await ws.send(json.dumps({"type": "mark", "name": msg.get("name")}))
                    state["marks"] += 1

        task = asyncio.create_task(listener())

        async def stream(pcm: bytes):
            t0 = time.perf_counter()
            for i, off in enumerate(range(0, len(pcm), FRAME_BYTES)):
                frame = pcm[off:off + FRAME_BYTES].ljust(FRAME_BYTES, b"\x00")
                await ws.send(json.dumps({"type": "audio", "data": base64.b64encode(frame).decode()}))
                await asyncio.sleep(max(0.0, t0 + (i + 1) * FRAME_MS / 1000 - time.perf_counter()))

        # Stay silent until the welcome message (if any) has finished: wait up to 12 s,
        # and once audio has started, until it has been quiet for `quiet_end` seconds.
        t_start = time.perf_counter()
        while time.perf_counter() - t_start < 12.0:
            await ws.send(json.dumps({"type": "audio", "data": base64.b64encode(SILENCE).decode()}))
            await asyncio.sleep(FRAME_MS / 1000)
            if state["first_audio"] and time.perf_counter() - state["last_audio"] > quiet_end:
                break
            if not state["first_audio"] and time.perf_counter() - t_start > 4.0:
                break                                   # no welcome configured
        if reply:
            save(out_dir / "welcome.wav", bytes(reply))
            print(f"welcome: {len(reply) / (OUT_RATE * 2):.1f} s of audio, "
                  f"first after {state['first_audio'] - t_start:.2f} s")
        for n, path in enumerate(files, start=1):
            reply.clear()
            state.update(first_audio=None, last_audio=None, cleared=0, marks=0)
            await stream(pcm16_mono_16k(path))
            speech_end = time.perf_counter()
            # keep sending silence until the reply has been quiet for `quiet_end` seconds
            deadline = speech_end + reply_wait
            while time.perf_counter() < deadline:
                await ws.send(json.dumps({"type": "audio", "data": base64.b64encode(SILENCE).decode()}))
                await asyncio.sleep(FRAME_MS / 1000)
                if state["first_audio"] and time.perf_counter() - state["last_audio"] > quiet_end:
                    break
            first = state["first_audio"]
            row = {"line": path.name,
                   "reply_after_s": round(first - speech_end, 2) if first else None,
                   "reply_audio_s": round(len(reply) / (OUT_RATE * 2), 1),
                   "interrupt_clears": state["cleared"], "marks_acked": state["marks"]}
            if reply:
                save(out_dir / f"reply{n}.wav", bytes(reply))
            results.append(row)
            print(row, flush=True)
        task.cancel()
    return results


def save(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(OUT_RATE)
        w.writeframes(pcm)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--agent", required=True)
    p.add_argument("--host", default="localhost:5001")
    p.add_argument("--out-dir", type=Path, default=Path("results/voice_probe"))
    p.add_argument("--reply-wait", type=float, default=40.0, help="max seconds to wait for a reply")
    p.add_argument("--quiet-end", type=float, default=2.0, help="silence that ends a reply")
    a = p.parse_args(argv)
    rows = asyncio.run(run(a.agent, a.files, a.out_dir, a.host, a.reply_wait, a.quiet_end))
    (a.out_dir / "probe.json").write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
