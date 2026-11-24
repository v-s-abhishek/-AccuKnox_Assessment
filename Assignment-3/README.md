# Assignment 3 - RedLine

Project link: https://github.com/v-s-abhishek/RedLine
Live demo: https://redline-mw58.onrender.com/ (free hosting, so the first load can take up to a minute)

RedLine is an AI voice agent that calls you pretending to be a social engineer, so a team can practise
saying no. A hidden coach scores the call while it's happening. I built it for the AssemblyAI Voice Agent
Hackathon 2026.

Why it's hard:

1. It has to hold a real-time conversation. Speech-to-text, the LLM playing the attacker and its voice all run
   over one full-duplex WebSocket at 24 kHz with barge-in, and the attacker has to adapt and push harder within
   a normal pause when the trainee resists.
2. You can't just trust an LLM to do the grading. A second model tags tactics and defences as strict JSON, but
   leaked credentials are checked with plain code line by line, even when the digits are spoken, so a lenient or
   manipulated judge can't hide a failure.
3. It's an attack tool pointed at real people, so safety had to be built in. The server won't call anyone who
   hasn't opted in by SMS or email, drills only use fake practice values, and saying the safe word "red line"
   ends the call straight away.
