"""Speaking while the model is still writing (voice). `Out` is what the borrower has heard
this turn; `Speaker` releases a reply sentence by sentence, each only after the reply so far
has passed the same checks a whole reply must pass."""
from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from kisht.confirm import is_plain_talk

if TYPE_CHECKING:
    from kisht.agent import Agent, TurnResult

_SENTENCE_END = re.compile(r"(?<!\bRs)(?<!\bMr)(?<!\bDr)(?<!\bNo)[.!?\u0964](?=\s)")
MIN_PIECE = 12            # characters; shorter bits wait for the next sentence


class CallerGone(Exception):
    """On a call: the caller spoke over the agent or hung up, so this turn is abandoned."""


class Out:
    """What the borrower has heard so far in this turn, in order."""

    def __init__(self, on_say: Any):
        self.on_say = on_say
        self.pieces: list[tuple[str, bool]] = []      # (text, is a filler line)
        self.committed = 0                            # pieces already saved in the transcript
        self.done = False                             # the model's own reply went out through here
        self.started = time.perf_counter()
        self.first_s: float | None = None

    def __call__(self, piece: str, filler: bool = False) -> None:
        piece = (piece or "").strip()
        if not piece:
            return
        if self.first_s is None:
            self.first_s = time.perf_counter() - self.started
        self.pieces.append((piece, filler))
        self.on_say(piece)

    def commit(self) -> None:
        self.committed = len(self.pieces)

    def still_listening(self) -> None:
        """Raises CallerGone if the voice layer says the caller has cut in. Asked before any
        tool runs: a link must not be sent, or a case opened, for a turn the caller already
        talked over (before, this was only noticed at the next spoken sentence)."""
        alive = getattr(self.on_say, "alive", None)
        if alive is not None and not alive():
            raise CallerGone

    def text(self) -> str:
        return " ".join(p for p, _ in self.pieces)

    def uncommitted(self) -> str:
        return " ".join(p for p, filler in self.pieces[self.committed:] if not filler)


class Speaker:
    """Releases the start of a model reply while the rest is still being written. A sentence
    goes out early only if the reply up to and including it is plain talk (no number, no word
    about an action) and passes every check a whole reply must pass. From the first sentence
    that is not, everything waits until the model has finished: if a tool call follows, that
    text is dropped, as it always was; if not, the whole reply is checked and said."""

    def __init__(self, agent: Agent, result: TurnResult, out: Out, check_retry: bool):
        self.agent, self.result, self.out, self.check_retry = agent, result, out, check_retry
        self.quiet = result.promise_saved    # after "your promise is saved", no "sorry" line
        self.text = ""
        self.said = 0             # characters of self.text already released
        self.stopped = False

    def feed(self, piece: str) -> None:
        if self.stopped:
            return
        self.text += piece
        if "<think" in self.text or "<tool_call" in self.text:
            self.stopped = True
            return
        end = None
        for m in _SENTENCE_END.finditer(self.text, self.said):
            end = m.end()
        if end is None or end - self.said < MIN_PIECE:
            return
        ready = self.text[:end]
        # The model is never cut off here, even when this reply will be asked again ("I am
        # recording it" with no tool yet): tried live, and the cut sometimes removed the very
        # tool call that was about to follow the words.
        if (not is_plain_talk(ready) or self.agent._violation(ready, self.result)
                or (self.check_retry and self.agent._retry_reason(ready, self.result))):
            self.stopped = True          # the rest waits for the whole reply and its checks
            return
        self.out(self.text[self.said:end])
        self.said = end

    def heard(self) -> str:
        return self.text[:self.said].strip()

    def finish(self, full: str) -> str:
        """The model has finished: check the whole reply, release what is left."""
        heard = self.heard()
        checked = self.agent._checked(full, self.result)
        if checked == full and full.startswith(heard):
            self.out(full[len(heard):])
            self.out.done = True
            return full
        if not heard:
            return checked        # nothing was heard: the caller says the safe line instead
        # The clean start was heard; the blocked rest is replaced by the safe line (seen
        # live without it: the borrower heard only "Okay, Sunita." and then silence).
        self.out.done = True
        if not self.quiet:
            self.out(checked)
            return f"{heard} {checked}"
        return heard
