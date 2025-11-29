# Ash Music Bot 🎵

Minimal Discord bot for Render.com (0.1 CPU optimized)

Made by **Raged solo**

## Quick Deploy on Render.com

### 1. Fork this repo

### 2. Get tokens:
- Discord: [Developer Portal](https://discord.com/developers/applications)
- Spotify: [Dashboard](https://developer.spotify.com/dashboard)

### 3. Deploy on Render:
- Build: `pip install -r requirements.txt`
- Start: `python denli.py`
- Add env vars: `DISCORD_TOKEN`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`
- Note: FFmpeg auto-detected (uses system FFmpeg on Render, local ffmpeg.exe on Windows)

### 4. Enable Discord intents:
- MESSAGE CONTENT
- SERVER MEMBERS

## Local Setup

## Local Setup

```bash
git clone <repo>
cd "Ash Music"
pip install -r requirements.txt
cp .env.example .env
# Edit .env
python denli.py
```

## Commands

See `cmds.txt` (3 parts)

### Music:
`!play` `!skip` `!queue` `!stop`

### Moderation:
`/protection` `/setupjoin` `/autorole` `/lock`

### Fun:
`!<character>` `!fusion` `!run`

---

Made by Raged solo