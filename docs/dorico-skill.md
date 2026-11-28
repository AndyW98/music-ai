# Dorico audio transcription skill

The [repository skill](https://github.com/AndyW98/music-ai/tree/main/.agents/skills/dorico-audio-transcription) guides an agent from a source recording to a new editable Dorico project. It estimates tempo, meter, and beat phase before notation, exports the actual Dorico audio, uses this repository's comparison report to review specific discrepancies, and revises the same project across versions. It keeps the original audio and any pre-existing Dorico project unchanged.

For the complete [ChatGPT desktop setup on Windows](https://github.com/AndyW98/music-ai#audio-to-dorico-skill-in-chatgpt-desktop-windows), including Dorico Maestro MCP configuration, see the README.

## Use it

1. Clone the repository and open it as a local project in **Codex** in the ChatGPT desktop app. The `.agents/skills` folder is discovered from the project. Alternatively, install this skill from the GitHub repository path with `$skill-installer` for use in another project; keep a checkout of this repository available for `compare.py`.
2. Supply the audio recording and ask to use `$dorico-audio-transcription`. Describe the intended instrument or parts if you know them and say whether published sheet music may be consulted. For an audio-only accuracy test, keep sheet music out of the drafting loop.
3. Review the score and reports after each phrase. The CLI tracks one dominant pitch at a time, so overlapping parts need independent listening and careful assignment. A high similarity score alone cannot establish a correct transcription.

The skill uses a configured Hindsight music bank when available and continues without it otherwise. Dorico Maestro supplies optional MCP controls for Dorico; this repository supplies the comparison CLI and skill instructions. Voice can start or steer a Codex task in the desktop app when available for your account, but the local skill and MCP connection must be usable by that Codex task.
