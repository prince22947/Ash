# DEPLOY TO RENDER.COM - Files Ready (118 KB)

These 7 files are ready to deploy to Render.com for the 0.1 CPU free tier.

## Files in this folder:

✅ denli.py (112 KB) - Main bot code
✅ requirements.txt (0.1 KB) - Python dependencies
✅ .env.example (0.1 KB) - Environment template
✅ .gitignore (0.8 KB) - Protection rules
✅ README.md (1.0 KB) - Quick setup guide
✅ DEPLOY.txt (0.9 KB) - Deployment instructions
✅ cmds.txt (3.8 KB) - Commands reference

Total: 118 KB (99.9% smaller than with ffmpeg.exe!)

## Git Push Commands:

cd DEPLOY_TO_RENDER

git init
git add .
git commit -m "Ash Music Bot by Raged solo"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main

## Render.com Setup:

1. Create New Web Service
2. Connect your GitHub repository
3. Build Command: pip install -r requirements.txt
4. Start Command: python denli.py
5. Add Environment Variables:
   - DISCORD_TOKEN
   - SPOTIFY_CLIENT_ID
   - SPOTIFY_CLIENT_SECRET

## What Happens at Runtime:

. Bot creates music/ folder automatically
. JSON files (bot_data, channel_settings, user_songs) auto-generated
. FFmpeg auto-detected (uses system FFmpeg on Render)
. Temp folders (temp_tts/) created as needed

Made by Raged solo
