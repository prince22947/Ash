import asyncio, datetime, json, logging, os, shutil, tempfile, time, typing, random
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
import edge_tts
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from discord import app_commands
import aiohttp

# -------------------------------------------------
# 0.  CONFIG - IMPROVED FOR AUDIO STABILITY
# -------------------------------------------------
load_dotenv()  # Load environment variables early

CFG = {
    "PREFIX": "!",
    "FFMPEG_PATH": "ffmpeg" if shutil.which("ffmpeg") else str(Path(__file__).parent / "ffmpeg.exe"),  # Auto-detect
    "TEMP_FOLDER": "temp_tts",
    "MAX_TEXT": 300,
    "QUEUE_LIMIT": 100,
    "DEF_VOL": 1.15,  # Slight boost for music
    "TTS_VOL": 1.5,   # Higher boost for TTS clarity
}

# Initialize Spotify client
try:
    spotify_client = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET")
    ))
    log = logging.getLogger("DS-Bot")
    log.info("Spotify client initialized successfully")
except Exception as e:
    spotify_client = None
    log = logging.getLogger("DS-Bot")
    log.warning(f"Spotify client failed to initialize: {e}")

# Voice mapping - Enhanced with rate control for better character authenticity
DS_VOICES = {
    "tanji": {"voice": "en-US-BrandonNeural", "pitch": "+4Hz", "rate": "+6%"},
    "nezuko": {"voice": "ja-JP-NanamiNeural", "pitch": "+20Hz", "rate": "-12%"},  # Japanese voice!
    "zenitsu": {"voice": "en-US-GuyNeural", "pitch": "+15Hz", "rate": "+10%"},
    "inosuke": {"voice": "en-US-ChristopherNeural", "pitch": "-14Hz", "rate": "-6%"},
    "muzan": {"voice": "en-US-ChristopherNeural", "pitch": "-24Hz", "rate": "-8%"},
    "giyu": {"voice": "en-US-GuyNeural", "pitch": "-10Hz", "rate": "-8%"},
    "girl": {"voice": "en-US-JennyNeural", "pitch": "+12Hz", "rate": "+4%"},
    "boy": {"voice": "en-US-BrandonNeural", "pitch": "-4Hz", "rate": "0%"},
    "child": {"voice": "en-US-AriaNeural", "pitch": "+22Hz", "rate": "+10%"},
    # Indian Languages
    "hindi": {"voice": "hi-IN-SwaraNeural", "pitch": "+0Hz", "rate": "+0%"},  # Hindi Female
    "hindim": {"voice": "hi-IN-MadhurNeural", "pitch": "+0Hz", "rate": "+0%"},  # Hindi Male
    "telugu": {"voice": "te-IN-ShrutiNeural", "pitch": "+0Hz", "rate": "+0%"},  # Telugu Female
    "telugum": {"voice": "te-IN-MohanNeural", "pitch": "+0Hz", "rate": "+0%"},  # Telugu Male
}

# -------------------------------------------------
# 1.  LOGGER
# -------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DS-Bot")

# -------------------------------------------------
# 2.  BOT INTENTS
# -------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=CFG["PREFIX"], intents=intents, help_command=None)

# Music queue system - one queue per guild
music_queues = {}
# Per-guild playback numbering and history
play_indices = {}
current_track = {}
played_history = {}
# Slash command sync flag
tree_synced = False

# Channel locking system
music_channels = {}  # guild_id: channel_id for music/TTS commands
fun_channels = {}    # guild_id: channel_id for anime/fun commands

# Music control panel messages
control_panels = {}  # guild_id: message_id

# Cooldown for control panel updates (prevent spam)
last_panel_update = {}  # guild_id: timestamp
PANEL_UPDATE_COOLDOWN = 2.0  # seconds

# Persistent storage file
CHANNEL_SETTINGS_FILE = Path("music/channel_settings.json")
USER_SONGS_FILE = Path("music/user_songs.json")

def load_channel_settings():
    """Load channel settings from JSON file"""
    global music_channels, fun_channels
    try:
        if CHANNEL_SETTINGS_FILE.exists():
            with open(CHANNEL_SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                # Convert string keys back to integers
                music_channels = {int(k): v for k, v in data.get('music_channels', {}).items()}
                fun_channels = {int(k): v for k, v in data.get('fun_channels', {}).items()}
                log.info(f"Loaded channel settings: {len(music_channels)} music, {len(fun_channels)} fun")
    except Exception as e:
        log.error(f"Failed to load channel settings: {e}")
        music_channels = {}
        fun_channels = {}

def save_channel_settings():
    """Save channel settings to JSON file"""
    try:
        CHANNEL_SETTINGS_FILE.parent.mkdir(exist_ok=True)
        data = {
            'music_channels': music_channels,
            'fun_channels': fun_channels
        }
        with open(CHANNEL_SETTINGS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        log.info("Channel settings saved")
    except Exception as e:
        log.error(f"Failed to save channel settings: {e}")

def load_user_songs():
    """Load user song history from JSON file"""
    try:
        if USER_SONGS_FILE.exists():
            with open(USER_SONGS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        log.error(f"Failed to load user songs: {e}")
    return {}

def save_user_songs(data):
    """Save user song history to JSON file"""
    try:
        USER_SONGS_FILE.parent.mkdir(exist_ok=True)
        with open(USER_SONGS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save user songs: {e}")

def track_user_song(user_id, username, song_title):
    """Track a song played by a user"""
    user_songs = load_user_songs()
    user_key = str(user_id)
    
    # Initialize user data if not exists
    if user_key not in user_songs:
        user_songs[user_key] = {
            "username": username,
            "songs": {}
        }
    
    # Update username if changed
    user_songs[user_key]["username"] = username
    
    # Track song
    songs = user_songs[user_key]["songs"]
    if song_title in songs:
        songs[song_title]["play_count"] += 1
        songs[song_title]["last_played"] = int(time.time())
    else:
        songs[song_title] = {
            "play_count": 1,
            "first_played": int(time.time()),
            "last_played": int(time.time())
        }
    
    save_user_songs(user_songs)
    return songs[song_title]["play_count"]

# Anime GIF and reaction data
ANIME_GIFS = {
    "hug": ["anime hug", "demon slayer hug", "naruto hug", "one piece hug"],
    "slap": ["anime slap", "demon slayer slap", "naruto slap"],
    "kiss": ["anime kiss", "demon slayer kiss", "anime couple kiss"],
    "pat": ["anime head pat", "demon slayer pat", "anime pat head"],
    "dance": ["anime dance", "demon slayer dance", "naruto dance"],
    "cry": ["anime cry", "demon slayer cry", "sad anime"],
    "laugh": ["anime laugh", "demon slayer laugh"],
    "cuddle": ["anime cuddle", "couple cuddle anime"],
    "hold": ["anime hold hand", "anime hold"],
    "bite": ["anime bite", "vampire bite anime"],
    "lick": ["anime lick", "anime tongue"],
    "poke": ["anime poke", "anime finger poke"],
    "boop": ["anime boop nose", "anime nose boop"],
    "bonk": ["anime bonk", "anime hit"],
    "punch": ["anime punch", "one piece punch"],
    "kick": ["anime kick", "naruto kick"],
    "stab": ["anime sword", "demon slayer sword"],
    "throw": ["anime throw", "anime toss"],
    "feed": ["anime feed", "anime eating"],
    "offer": ["anime offer", "anime give"],
    "protect": ["anime protect", "anime shield"],
    "carry": ["anime carry", "anime princess carry"],
    "snuggle": ["anime snuggle", "anime cuddle close"],
    "scare": ["anime scare", "anime scared"],
    "tickle": ["anime tickle", "anime laugh tickle"],
    "blush": ["anime blush", "anime shy blush"],
    "angry": ["anime angry", "anime mad"],
    "mad": ["anime rage", "anime fury"],
    "happy": ["anime happy", "anime smile"],
    "sleepy": ["anime sleepy", "anime tired"],
    "confused": ["anime confused", "anime question mark"],
    "wow": ["anime shocked", "anime amazed"],
    "shy": ["anime shy", "anime nervous"],
    "sip": ["anime sip tea", "anime drink"],
    "stare": ["anime stare", "anime intense look"],
    "panic": ["anime panic", "anime scared run"],
    "facepalm": ["anime facepalm", "anime disappointed"],
    "boom": ["anime explosion", "anime blast"],
    "bankai": ["bleach bankai", "ichigo bankai"],
    "rasengan": ["naruto rasengan", "rasengan attack"],
    "chidori": ["sasuke chidori", "chidori lightning"],
    "gumgum": ["luffy gear", "one piece luffy attack"],
    "breathing": ["demon slayer breathing", "tanjiro water breathing"],
    "gear5": ["luffy gear 5", "one piece gear 5"],
    "ultra": ["ultra instinct", "goku ultra instinct"],
    "plusultra": ["my hero academia", "all might plus ultra"],
    "titan": ["attack on titan", "eren titan"],
    "summon": ["anime summon", "naruto summon"],
    "isekai": ["isekai anime", "truck kun"],
    "transform": ["anime transformation", "power up transformation"],
    "powerup": ["anime power up", "super saiyan"],
}

ANIME_QUOTES = [
    "'If you don't take risks, you can't create a future!' - Monkey D. Luffy",
    "'Hard work is worthless for those that don't believe in themselves.' - Naruto",
    "'Keep moving forward.' - Eren Yeager",
    "'I'll destroy that wall!' - Tanjiro Kamado",
    "'The only one who can beat me is me.' - Saitama",
    "'Believe in the me that believes in you!' - Kamina",
    "'A person can change, at the moment when the person wishes to change.' - Haruhi",
    "'If you don't like your destiny, don't accept it.' - Naruto",
    "'I'm not gonna run away, I never go back on my word!' - Naruto",
    "'The world isn't perfect, but it's there for us trying the best it can.' - Roy Mustang",
]

BREATHING_STYLES = [
    "Water Breathing", "Thunder Breathing", "Flame Breathing", "Wind Breathing",
    "Stone Breathing", "Mist Breathing", "Serpent Breathing", "Love Breathing",
    "Insect Breathing", "Flower Breathing", "Beast Breathing", "Sound Breathing"
]

QUIRKS = [
    "One For All", "Explosion", "Half-Cold Half-Hot", "Hardening",
    "Zero Gravity", "Engine", "Electrification", "Frog", "Creation",
    "Dark Shadow", "Erasure", "Permeation", "Manifest", "Copy"
]

STANDS = [
    "Star Platinum", "The World", "Crazy Diamond", "Gold Experience",
    "King Crimson", "Made in Heaven", "Killer Queen", "Silver Chariot",
    "Hierophant Green", "Sticky Fingers", "Stone Free", "Tusk"
]

DEMON_RANKS = [
    "Lower Moon Six", "Lower Moon Five", "Lower Moon Four", "Lower Moon Three",
    "Lower Moon Two", "Lower Moon One", "Upper Moon Six", "Upper Moon Five",
    "Upper Moon Four", "Upper Moon Three", "Upper Moon Two", "Upper Moon One", "Demon King"
]

# Override VoiceClient to fix 4006 errors
class FixedVoiceClient(discord.VoiceClient):
    async def connect(self, *, timeout=60.0, reconnect=True, self_deaf=False, self_mute=False):
        """Override connect to handle 4006 errors better"""
        log.info(f"Connecting with custom voice client (timeout={timeout}s)")
        return await super().connect(timeout=timeout, reconnect=reconnect, self_deaf=self_deaf, self_mute=self_mute)

# -------------------------------------------------
# 2.5 MUSIC CONTROL PANEL
# -------------------------------------------------
class ReplayModal(discord.ui.Modal, title="Replay Song"):
    song_number = discord.ui.TextInput(
        label="Song Number",
        placeholder="Enter song number to replay (leave empty for current)",
        required=False,
        max_length=5
    )
    
    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        vc = interaction.guild.voice_client
        
        if not vc:
            await interaction.response.send_message("❌ Not in voice channel", ephemeral=True)
            return
        
        try:
            # Defer response to avoid timeout
            await interaction.response.defer(ephemeral=True)
            
            # Determine which song to replay
            number = None
            if self.song_number.value.strip():
                try:
                    number = int(self.song_number.value.strip())
                except:
                    await interaction.followup.send("❌ Invalid song number", ephemeral=True)
                    return
            
            # Stop current playback
            if vc.is_playing() or vc.is_paused():
                vc.stop()
                await asyncio.sleep(0.3)
            
            # Get the track to replay
            if number is None:
                # Replay current
                info = current_track.get(guild_id)
                if not info:
                    await interaction.followup.send('❌ No track to replay', ephemeral=True)
                    return
                query = info['url']
                idx = info['index']
            else:
                # Replay by number
                history = played_history.get(guild_id, [])
                match = next((t for t in history if t['index'] == number), None)
                if not match:
                    await interaction.followup.send(f'❌ No track numbered #{number} found', ephemeral=True)
                    return
                query = match['url']
                idx = number
            
            # Play the track
            player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
            vc.play(player, after=lambda e: bot.loop.create_task(play_next(interaction.guild)) if not e else log.error(f"Player error: {e}"))
            
            await interaction.followup.send(f"🔁 Replaying [#{idx}]: **{player.title}**", ephemeral=True)
        except Exception as e:
            log.error(f"Replay error: {e}")
            try:
                await interaction.followup.send("❌ Replay failed", ephemeral=True)
            except:
                pass

class MusicControlPanel(discord.ui.View):
    def __init__(self, user_id: int, is_playing: bool = True, is_paused: bool = False):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.is_playing = is_playing
        self.is_paused = is_paused
        
        # Row 1: Main controls
        if is_paused:
            self.add_item(discord.ui.Button(
                emoji="▶️",
                style=discord.ButtonStyle.green,
                custom_id="music_resume"
            ))
        elif is_playing:
            self.add_item(discord.ui.Button(
                emoji="⏸️",
                style=discord.ButtonStyle.green,
                custom_id="music_pause"
            ))
        
        self.add_item(discord.ui.Button(
            emoji="⏭️",
            style=discord.ButtonStyle.blurple,
            custom_id="music_skip"
        ))
        self.add_item(discord.ui.Button(
            emoji="⏹️",
            style=discord.ButtonStyle.red,
            custom_id="music_stop"
        ))
        self.add_item(discord.ui.Button(
            emoji="🔀",
            style=discord.ButtonStyle.grey,
            custom_id="music_shuffle"
        ))
        
        # Row 2: Volume and utility
        self.add_item(discord.ui.Button(
            emoji="🔉",
            style=discord.ButtonStyle.grey,
            custom_id="music_volume_down",
            row=1
        ))
        self.add_item(discord.ui.Button(
            emoji="🔊",
            style=discord.ButtonStyle.grey,
            custom_id="music_volume_up",
            row=1
        ))
        self.add_item(discord.ui.Button(
            emoji="🔁",
            style=discord.ButtonStyle.grey,
            custom_id="music_replay",
            row=1
        ))
        self.add_item(discord.ui.Button(
            emoji="📋",
            style=discord.ButtonStyle.grey,
            custom_id="music_queue",
            row=1
        ))
        self.add_item(discord.ui.Button(
            emoji="🚪",
            style=discord.ButtonStyle.danger,
            custom_id="music_leave",
            row=1
        ))
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Handle button clicks"""
        try:
            custom_id = interaction.data.get('custom_id')
            vc = interaction.guild.voice_client
            guild_id = interaction.guild.id
            
            if custom_id == "music_pause":
                if vc and vc.is_playing():
                    vc.pause()
                    await interaction.response.send_message("⏸️ Paused", ephemeral=True, delete_after=3)
                    # Update panel to show Resume button
                    if guild_id in current_track:
                        await update_control_panel(interaction.guild, current_track[guild_id], is_paused=True)
                else:
                    await interaction.response.send_message("❌ Nothing playing", ephemeral=True, delete_after=3)
            
            elif custom_id == "music_resume":
                if vc and vc.is_paused():
                    vc.resume()
                    await interaction.response.send_message("▶️ Resumed", ephemeral=True, delete_after=3)
                    # Update panel to show Pause button
                    if guild_id in current_track:
                        await update_control_panel(interaction.guild, current_track[guild_id], is_paused=False)
                else:
                    await interaction.response.send_message("❌ Not paused", ephemeral=True, delete_after=3)
            
            elif custom_id == "music_skip":
                if vc and (vc.is_playing() or vc.is_paused()):
                    vc.stop()
                    await interaction.response.send_message("⏭️ Skipped", ephemeral=True, delete_after=3)
                else:
                    await interaction.response.send_message("❌ Nothing to skip", ephemeral=True, delete_after=3)
            
            elif custom_id == "music_stop":
                if vc:
                    if guild_id in music_queues:
                        music_queues[guild_id].clear()
                    vc.stop()
                    await interaction.response.send_message("⏹️ Stopped & cleared queue", ephemeral=True, delete_after=3)
                else:
                    await interaction.response.send_message("❌ Not connected", ephemeral=True, delete_after=3)
            
            elif custom_id == "music_leave":
                if vc:
                    if guild_id in music_queues:
                        music_queues[guild_id].clear()
                    await vc.disconnect()
                    await interaction.response.send_message("🚪 Left voice channel", ephemeral=True, delete_after=3)
                else:
                    await interaction.response.send_message("❌ Not in voice channel", ephemeral=True, delete_after=3)
            
            elif custom_id == "music_replay":
                # Only the original user can use replay
                if interaction.user.id != self.user_id:
                    await interaction.response.send_message("❌ Only the song requester can replay", ephemeral=True, delete_after=3)
                    return True
                
                # Show modal for song number selection
                modal = ReplayModal(user_id=self.user_id)
                await interaction.response.send_modal(modal)
            
            elif custom_id == "music_shuffle":
                if guild_id in music_queues and len(music_queues[guild_id]) > 0:
                    import random
                    random.shuffle(music_queues[guild_id])
                    await interaction.response.send_message("🔀 Queue shuffled", ephemeral=True, delete_after=3)
                else:
                    await interaction.response.send_message("❌ Queue is empty", ephemeral=True, delete_after=3)
            
            elif custom_id == "music_volume_up":
                if vc and hasattr(vc.source, 'volume'):
                    new_vol = min(2.0, vc.source.volume + 0.1)
                    vc.source.volume = new_vol
                    await interaction.response.send_message(f"🔊 Volume: {int(new_vol * 100)}%", ephemeral=True, delete_after=3)
                else:
                    await interaction.response.send_message("❌ No audio playing", ephemeral=True, delete_after=3)
            
            elif custom_id == "music_volume_down":
                if vc and hasattr(vc.source, 'volume'):
                    new_vol = max(0.1, vc.source.volume - 0.1)
                    vc.source.volume = new_vol
                    await interaction.response.send_message(f"🔉 Volume: {int(new_vol * 100)}%", ephemeral=True, delete_after=3)
                else:
                    await interaction.response.send_message("❌ No audio playing", ephemeral=True, delete_after=3)
            
            elif custom_id == "music_queue":
                if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
                    await interaction.response.send_message("🎵 Queue is empty", ephemeral=True, delete_after=5)
                else:
                    queue_list = music_queues[guild_id][:10]
                    total = len(music_queues[guild_id])
                    queue_text = "\n".join([f"`{i+1}.` {song[:50]}" for i, song in enumerate(queue_list)])
                    if total > 10:
                        queue_text += f"\n\n... and {total - 10} more tracks"
                    
                    embed = discord.Embed(
                        title="📋 Music Queue",
                        description=queue_text,
                        color=0x1DB954
                    )
                    embed.set_footer(text=f"Total: {total} tracks")
                    await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=15)
            
            return True
        except discord.errors.NotFound:
            # Interaction expired, ignore
            log.debug("Interaction expired (button click took too long)")
            return False
        except Exception as e:
            log.error(f"Button interaction error: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Error processing button", ephemeral=True, delete_after=3)
            except:
                pass
            return False

async def update_control_panel(guild, track_info, is_paused=False):
    """Update or create the music control panel at the bottom of the channel"""
    guild_id = guild.id
    
    # Check if music channel is set
    if guild_id not in music_channels:
        return  # No channel lock, skip panel
    
    channel_id = music_channels[guild_id]
    channel = guild.get_channel(channel_id)
    
    if not channel:
        return
    
    # Determine playback state
    vc = guild.voice_client
    if vc:
        is_playing = vc.is_playing()
        is_paused = vc.is_paused()
    else:
        is_playing = False
        is_paused = False
    
    # Futuristic neon colors
    if is_paused:
        color = discord.Color.from_rgb(255, 0, 128)  # Neon pink for paused
    else:
        color = discord.Color.from_rgb(0, 255, 255)  # Neon cyan for playing
    
    # Create futuristic embed
    status_text = "⏸ PAUSED" if is_paused else "🎵 NOW PLAYING"
    
    embed = discord.Embed(
        title=f"🎧 {status_text}",
        description=f"**{track_info['title']}**",
        color=color
    )
    
    # Thumbnail
    if 'thumbnail' in track_info and track_info['thumbnail']:
        embed.set_thumbnail(url=track_info['thumbnail'])
    
    # Track info fields
    track_number = track_info.get('index', '?')
    embed.add_field(
        name="Track",
        value=f"`#{track_number}`",
        inline=True
    )
    
    # Requester info
    requester_id = track_info.get('requester_id', 0)
    play_count = track_info.get('play_count', 1)
    if requester_id:
        try:
            user = await guild.fetch_member(requester_id)
            play_text = f"**{user.display_name}**"
            if play_count > 1:
                play_text += f"\n`Played {play_count}x`"
            embed.add_field(
                name="Requested By",
                value=play_text,
                inline=True
            )
        except:
            embed.add_field(
                name="Requested By",
                value="**Unknown**",
                inline=True
            )
    
    # Queue length
    queue_length = len(music_queues.get(guild_id, []))
    if queue_length > 0:
        embed.add_field(
            name="Queue",
            value=f"`{queue_length} songs`",
            inline=True
        )
    
    # Footer with futuristic branding
    embed.set_footer(
        text="🔊 Ash Music Audio System"
    )
    
    # Futuristic banner image (optional - using a gradient bar)
    embed.set_image(
        url="https://dummyimage.com/600x100/0d1117/00ffff&text=▶+AUDIO+WAVE"
    )
    
    view = MusicControlPanel(user_id=requester_id, is_playing=is_playing, is_paused=is_paused)
    
    # Fast deletion: delete old panel without waiting
    old_msg_task = None
    if guild_id in control_panels:
        try:
            # Start deletion in background without awaiting
            old_msg_id = control_panels[guild_id]
            old_msg_task = asyncio.create_task(
                channel.get_partial_message(old_msg_id).delete()
            )
        except:
            pass
    
    # Send new panel immediately (don't wait for old one to delete)
    try:
        msg = await channel.send(embed=embed, view=view)
        control_panels[guild_id] = msg.id
        
        # Clean up old deletion task if it exists
        if old_msg_task:
            try:
                await old_msg_task
            except:
                pass
            
    except Exception as e:
        log.error(f"Failed to send control panel: {e}")

# -------------------------------------------------
# 3.  TTS ENGINE (IMPROVED)
# -------------------------------------------------
class TTSEngine:
    def __init__(self, temp_dir: Path):
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(exist_ok=True)

    async def create(self, text: str, character: str) -> Path:
        if len(text) > CFG["MAX_TEXT"]:
            text = text[:CFG["MAX_TEXT"]] + "…"

        ts = int(time.time() * 1000)
        out = self.temp_dir / f"tts_{character}_{ts}.mp3"

        cfg = DS_VOICES.get(character, DS_VOICES["girl"])

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=cfg["voice"],
                pitch=cfg["pitch"],
                rate=cfg.get("rate", "0%")  # Support rate parameter
            )
            await communicate.save(str(out))
            
            # Verify file was created and has content
            if not out.exists() or out.stat().st_size < 10:
                raise Exception("TTS file creation failed")
                
            return out
        except Exception as e:
            log.error("TTS creation error: %s", e)
            raise

    async def cleanup_old(self, older_than: int = 2700):  # 45 minutes
        now = time.time()
        for fp in self.temp_dir.glob("*.mp3"):
            if now - fp.stat().st_mtime > older_than:
                try:
                    fp.unlink()
                except:
                    pass

# -------------------------------------------------
# 4.  MUSIC SYSTEM - IMPROVED FFMPEG CONFIG
# -------------------------------------------------
ytdl_options = {
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
    'extractaudio': True,
    'audioformat': 'opus',
    'audioquality': 0,  # Best quality (0-9, 0 is best)
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'prefer_ffmpeg': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '320',
    }],
}

# HIGHEST QUALITY FFMPEG OPTIONS
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -b:a 320k -ar 48000 -ac 2 -filter:a "volume=1.0"'  # 320kbps, 48kHz, stereo, full volume
}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=1.15):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        
        def extract_info():
            try:
                with yt_dlp.YoutubeDL(ytdl_options) as ydl:
                    info = ydl.extract_info(url, download=not stream)
                    if not info:
                        return None
                    return info
            except Exception as e:
                log.error("YT-DLP extraction error: %s", e)
                return None
        
        data = await loop.run_in_executor(None, extract_info)
        
        if not data:
            raise Exception("Could not extract audio info")
            
        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else yt_dlp.YoutubeDL(ytdl_options).prepare_filename(data)
        
        # IMPROVED: Better error handling for audio source creation
        try:
            source = discord.FFmpegPCMAudio(
                filename, 
                **ffmpeg_options, 
                executable=CFG["FFMPEG_PATH"]
            )
            return cls(source, data=data, volume=CFG["DEF_VOL"])
        except Exception as e:
            log.error("FFmpeg audio source creation failed: %s", e)
            # Fallback: try without specific options
            try:
                source = discord.FFmpegPCMAudio(
                    filename, 
                    executable=CFG["FFMPEG_PATH"]
                )
                return cls(source, data=data, volume=CFG["DEF_VOL"])
            except Exception as e2:
                log.error("Fallback FFmpeg also failed: %s", e2)
                raise Exception(f"Audio source creation failed: {str(e)}")

# -------------------------------------------------
# 5.  EVENTS
# -------------------------------------------------
@bot.event
async def on_ready():
    log.info("Logged in as %s", bot.user)
    
    # Load channel settings from file
    load_channel_settings()
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="Spotify & YouTube | !help"
        )
    )
    # Sync slash commands once
    global tree_synced
    if not tree_synced:
        try:
            await bot.tree.sync()
            tree_synced = True
            log.info("Slash commands synced")
        except Exception as e:
            log.warning(f"Failed to sync slash commands: {e}")
    # Only start cleanup task if not already running
    if not cleanup_task.is_running():
        cleanup_task.start()

@bot.event
async def on_voice_state_update(member, before, after):
    """Handle voice state changes - bot stays in channel permanently"""
    # Bot no longer auto-disconnects when alone
    pass

@bot.event
async def on_disconnect():
    """Clean up voice connections on disconnect"""
    for vc in bot.voice_clients:
        try:
            await vc.disconnect(force=True)
        except:
            pass

@bot.event
async def on_message(message):
    """Auto-move control panel to bottom when messages are sent in music channel"""
    # Ignore bot's own messages
    if message.author.bot:
        await bot.process_commands(message)
        return
    
    guild_id = message.guild.id if message.guild else None
    
    # Check if this is the music channel and there's an active control panel
    if guild_id and guild_id in music_channels and guild_id in control_panels:
        if message.channel.id == music_channels[guild_id]:
            # Check cooldown to prevent spam
            current_time = time.time()
            last_update = last_panel_update.get(guild_id, 0)
            
            log.info(f"Message detected in music channel. Cooldown: {current_time - last_update:.2f}s")
            
            # Only update if cooldown has passed
            if current_time - last_update >= PANEL_UPDATE_COOLDOWN:
                # There's a control panel in this channel, move it to bottom
                if guild_id in current_track and current_track[guild_id]:
                    log.info("Moving control panel to bottom...")
                    # Check pause state
                    vc = message.guild.voice_client
                    is_paused = vc.is_paused() if vc else False
                    # Resend the control panel
                    await update_control_panel(message.guild, current_track[guild_id], is_paused=is_paused)
                    # Update timestamp
                    last_panel_update[guild_id] = current_time
                else:
                    log.info("No current track to display")
            else:
                log.info(f"Cooldown active, skipping update")
    
    # Process commands
    await bot.process_commands(message)

# -------------------------------------------------
# 6.  LOOPS
# -------------------------------------------------
@tasks.loop(minutes=45)  # Cleanup every 45 minutes
async def cleanup_task():
    await tts.cleanup_old()

@cleanup_task.before_loop
async def before_cleanup():
    await bot.wait_until_ready()

# -------------------------------------------------
# 7.  TTS COMMANDS (IMPROVED)
# -------------------------------------------------
tts = TTSEngine(Path(CFG["TEMP_FOLDER"]))

async def ensure_voice_client(ctx):
    """Ensure bot is connected to voice channel with better error handling"""
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You need to join a voice channel first!")
        return None

    vc = ctx.voice_client
    target_channel = ctx.author.voice.channel
    
    # If already connected to the same channel, return it
    if vc and vc.channel == target_channel:
        return vc
    
    # If connected to different channel in same server, move or create new connection
    if vc and vc.channel != target_channel:
        # Check if we can have multiple connections (one bot = one voice connection per guild)
        # Discord limitation: One bot can only be in ONE voice channel per server
        try:
            await vc.move_to(target_channel)
            await asyncio.sleep(0.5)
            return vc
        except:
            try:
                await vc.disconnect(force=True)
                await asyncio.sleep(0.5)
            except:
                pass
    
    # Connect to voice channel with retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            vc = await target_channel.connect(
                timeout=60.0,  # Increased from 30 to 60 seconds
                reconnect=True,
                cls=FixedVoiceClient,
                self_deaf=False
            )
            await asyncio.sleep(2.0)  # Increased wait time
            
            if vc.is_connected():
                log.info(f"Successfully connected to voice channel on attempt {attempt + 1}")
                return vc
            else:
                raise Exception("Connection established but not connected")
                
        except discord.errors.ClientException as e:
            if "already connected" in str(e).lower():
                if ctx.guild.voice_client:
                    return ctx.guild.voice_client
            log.error(f"Voice connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(3)  # Longer delay between retries
            else:
                await ctx.send(f"❌ Failed to join voice channel after {max_retries} attempts. Check bot permissions and try again.")
                return None
        except Exception as e:
            log.error(f"Voice connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(3)  # Longer delay between retries
            else:
                await ctx.send(f"❌ Failed to join voice channel. Error: {type(e).__name__}")
                return None
    
    return None

async def play_tts(ctx, character, *, text):
    vc = await ensure_voice_client(ctx)
    if not vc:
        return

    try:
        async with ctx.typing():
            mp3_path = await tts.create(text, character)

        def after_playing(error):
            """Callback after audio finishes playing"""
            try:
                # Clean up the temporary file
                if mp3_path and mp3_path.exists():
                    mp3_path.unlink()
            except Exception as e:
                log.error("Cleanup error: %s", e)
                
            if error:
                log.error("TTS playback error: %s", error)

        # HIGHEST QUALITY FFmpeg configuration for TTS
        source = discord.FFmpegPCMAudio(
            source=str(mp3_path),
            executable=CFG["FFMPEG_PATH"],
            before_options='-nostdin',
            options=f'-b:a 256k -ar 48000 -ac 2 -filter:a "volume={CFG["TTS_VOL"]}"'  # Use TTS_VOL config
        )
        
        # Stop any current playback
        if vc.is_playing():
            vc.stop()
            
        vc.play(source, after=after_playing)
        await ctx.send(f"🔊 {character.upper()} » {text}")
        
    except Exception as e:
        log.error("TTS error: %s", e)  # Only log, don't send error to chat
        # Clean up on error
        try:
            if 'mp3_path' in locals() and mp3_path.exists():
                mp3_path.unlink()
        except:
            pass

# TTS Commands
@bot.command(name="tanji")
async def tanji(ctx, *, text): 
    await play_tts(ctx, "tanji", text=text)

@bot.command(name="nezuko")
async def nezuko(ctx, *, text): 
    await play_tts(ctx, "nezuko", text=text)

@bot.command(name="zenitsu")
async def zenitsu(ctx, *, text): 
    await play_tts(ctx, "zenitsu", text=text)

@bot.command(name="inosuke")
async def inosuke(ctx, *, text): 
    await play_tts(ctx, "inosuke", text=text)

@bot.command(name="muzan")
async def muzan(ctx, *, text): 
    await play_tts(ctx, "muzan", text=text)

@bot.command(name="giyu")
async def giyu(ctx, *, text): 
    await play_tts(ctx, "giyu", text=text)

@bot.command(name="girl")
async def girl(ctx, *, text): 
    await play_tts(ctx, "girl", text=text)

@bot.command(name="boy")
async def boy(ctx, *, text): 
    await play_tts(ctx, "boy", text=text)

@bot.command(name="child")
async def child(ctx, *, text): 
    await play_tts(ctx, "child", text=text)

# Indian Language Commands
@bot.command(name="hindi")
async def hindi(ctx, *, text): 
    await play_tts(ctx, "hindi", text=text)

@bot.command(name="hindim")
async def hindim(ctx, *, text): 
    await play_tts(ctx, "hindim", text=text)

@bot.command(name="telugu")
async def telugu(ctx, *, text): 
    await play_tts(ctx, "telugu", text=text)

@bot.command(name="telugum")
async def telugum(ctx, *, text): 
    await play_tts(ctx, "telugum", text=text)

# -------------------------------------------------
# 8.  MUSIC COMMANDS - IMPROVED
# -------------------------------------------------

# Spotify helper functions
def extract_spotify_info(url):
    """Extract Spotify playlist or track info"""
    if not spotify_client:
        return None
    
    try:
        if "playlist" in url:
            playlist_id = url.split("/playlist/")[1].split("?")[0]
            results = spotify_client.playlist_tracks(playlist_id)
            tracks = []
            for item in results['items']:
                track = item['track']
                if track:
                    query = f"{track['name']} {track['artists'][0]['name']}"
                    tracks.append(query)
            return tracks
        elif "track" in url:
            track_id = url.split("/track/")[1].split("?")[0]
            track = spotify_client.track(track_id)
            query = f"{track['name']} {track['artists'][0]['name']}"
            return [query]
        elif "album" in url:
            album_id = url.split("/album/")[1].split("?")[0]
            results = spotify_client.album_tracks(album_id)
            tracks = []
            for track in results['items']:
                query = f"{track['name']} {track['artists'][0]['name']}"
                tracks.append(query)
            return tracks
    except Exception as e:
        log.error(f"Spotify extraction error: {e}")
        return None
    
    return None

@bot.command(name='play')
async def play(ctx, *, query):
    """Play music from YouTube or Spotify"""
    vc = await ensure_voice_client(ctx)
    if not vc:
        return

    guild_id = ctx.guild.id
    
    # Initialize queue for this guild if not exists
    if guild_id not in music_queues:
        music_queues[guild_id] = []

    # Check if it's a Spotify link
    if "spotify.com" in query:
        tracks = extract_spotify_info(query)
        if not tracks:
            log.error("Failed to extract Spotify info")
            return
        
        if len(tracks) == 1:
            # Single track
            await ctx.send(f'🎵 Adding Spotify track to queue...')
            music_queues[guild_id].append(tracks[0])
        else:
            # Playlist or album
            await ctx.send(f'🎵 Adding {len(tracks)} tracks from Spotify to queue...')
            music_queues[guild_id].extend(tracks)
    else:
        # YouTube or search query
        music_queues[guild_id].append(query)
    
    # If nothing is playing, start playing
    if not vc.is_playing():
        await play_next(ctx, vc)

async def play_next(ctx_or_guild, vc=None):
    """Play the next song in queue"""
    # Handle both ctx and guild objects
    if hasattr(ctx_or_guild, 'guild'):
        guild = ctx_or_guild.guild
        ctx = ctx_or_guild
    else:
        guild = ctx_or_guild
        ctx = None
    
    guild_id = guild.id
    
    if not vc:
        vc = guild.voice_client
    
    if not vc:
        log.info("No voice client available")
        return
    
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        log.info("Queue is empty")
        return
    
    query = music_queues[guild_id].pop(0)
    
    try:
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        
        def after_playing(error):
            if error:
                log.error("Music playback error: %s", error)
            # Play next song in queue
            asyncio.run_coroutine_threadsafe(play_next(guild, vc), bot.loop)
        
        # Track numbering and history
        idx = play_indices.get(guild_id, 0) + 1
        play_indices[guild_id] = idx
        
        # Get requester ID if available
        requester_id = 0
        requester_name = "Unknown"
        if ctx and hasattr(ctx, 'author'):
            requester_id = ctx.author.id
            requester_name = ctx.author.display_name
        
        # Track user song
        play_count = track_user_song(requester_id, requester_name, player.title)
        
        current_track[guild_id] = {
            "index": idx, 
            "query": query, 
            "title": player.title,
            "url": query,
            "thumbnail": player.data.get('thumbnail'),
            "requester_id": requester_id,
            "play_count": play_count
        }
        played_history.setdefault(guild_id, []).append(current_track[guild_id])
        
        vc.play(player, after=after_playing)
        
        # Update control panel if music channel is set
        await update_control_panel(guild, current_track[guild_id])
        
        # Only send text message if music channel is NOT set (control panel shows everything)
        if guild_id not in music_channels:
            # Send message in appropriate channel
            remaining = len(music_queues[guild_id])
            msg = f'🎵 Now playing: [#{idx}] **{player.title}**'
            if remaining > 0:
                msg += f' ({remaining} in queue)'
            
            if ctx:
                await ctx.send(msg)
            
    except Exception as e:
        log.error("Play command error: %s", e)
        # Try next song if this one fails
        await play_next(guild, vc)

async def check_and_disconnect(voice_client, guild_id):
    """Check if should disconnect after playback"""
    await asyncio.sleep(2)  # Wait a bit
    
    # Check if voice client still exists and is not playing
    guild = bot.get_guild(guild_id)
    if not guild or not guild.voice_client:
        return
        
    vc = guild.voice_client
    
    if vc and not vc.is_playing() and not vc.is_paused():
        await asyncio.sleep(60)  # Wait 1 minute before disconnecting
        if vc and not vc.is_playing() and not vc.is_paused():
            try:
                await vc.disconnect()
            except Exception as e:
                log.error("Disconnect error: %s", e)

@bot.command(name='stop')
async def stop(ctx):
    """Stop the music and clear queue"""
    if ctx.voice_client:
        # Clear the queue
        guild_id = ctx.guild.id
        if guild_id in music_queues:
            music_queues[guild_id].clear()
        
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send('⏹️ Stopped and cleared queue')
        else:
            await ctx.send('❌ Not playing anything')
    else:
        await ctx.send('❌ Not in a voice channel')

@bot.command(name='skip')
async def skip(ctx):
    """Skip to the next song in queue"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()  # This will trigger after_playing callback to play next
        await ctx.send('⏭️ Skipped')
    else:
        await ctx.send('❌ Not playing anything')

@bot.command(name='queue', aliases=['q'])
async def queue(ctx):
    """Show the current music queue"""
    guild_id = ctx.guild.id
    
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        await ctx.send('🎵 Queue is empty')
        return
    
    queue_list = music_queues[guild_id][:10]  # Show first 10
    total = len(music_queues[guild_id])
    
    embed = discord.Embed(
        title="🎶 Music Queue",
        description=f"**{total} songs in queue**",
        color=0x1DB954  # Spotify green
    )
    
    for i, song in enumerate(queue_list, 1):
        embed.add_field(name=f"{i}.", value=song[:50], inline=False)
    
    if total > 10:
        embed.set_footer(text=f"... and {total - 10} more songs")
    
    await ctx.send(embed=embed)

@bot.command(name='replay', aliases=['rp'])
async def replay(ctx, number: typing.Optional[int] = None):
    """Replay current song or a previously played song by number"""
    guild_id = ctx.guild.id
    vc = await ensure_voice_client(ctx)
    if not vc:
        return
    try:
        # Stop current playback if needed
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
        # Determine target track
        if number is None:
            info = current_track.get(guild_id)
            if not info:
                await ctx.send('❌ No track to replay')
                return
            query = info['query']
            idx = info['index']
        else:
            history = played_history.get(guild_id, [])
            match = next((t for t in history if t['index'] == number), None)
            if not match:
                await ctx.send(f'❌ No track numbered #{number} found')
                return
            query = match['query']
            idx = number
        # Play immediately
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        def after_playing(error):
            if error:
                log.error("Music playback error: %s", error)
            asyncio.run_coroutine_threadsafe(play_next(ctx, vc), bot.loop)
        vc.play(player, after=after_playing)
        await ctx.send(f'🔁 Replaying [#{idx}] **{player.title}**')
    except Exception as e:
        log.error(f"Replay error: {e}")

@bot.command(name='pause')
async def pause(ctx):
    """Pause the music"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send('⏸️ Paused')
    else:
        await ctx.send('❌ Not playing anything')

@bot.command(name='resume')
async def resume(ctx):
    """Resume the music"""
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send('▶️ Resumed')
    else:
        await ctx.send('❌ Not paused')

@bot.command(name='leave', aliases=['l'])
async def leave(ctx):
    """Leave the voice channel"""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send('👋 Left voice channel')
    else:
        await ctx.send('❌ Not in a voice channel')

@bot.command(name='mystats', aliases=['ms'])
async def my_stats(ctx, member: discord.Member = None):
    """View song statistics for yourself or another user"""
    target_user = member if member else ctx.author
    user_songs = load_user_songs()
    user_key = str(target_user.id)
    
    if user_key not in user_songs or not user_songs[user_key].get('songs'):
        await ctx.send(f"📊 **{target_user.display_name}** hasn't played any songs yet!")
        return
    
    user_data = user_songs[user_key]
    songs = user_data['songs']
    
    # Sort songs by play count
    sorted_songs = sorted(songs.items(), key=lambda x: x[1]['play_count'], reverse=True)
    
    # Total stats
    total_songs = len(songs)
    total_plays = sum(song['play_count'] for song in songs.values())
    
    # Create embed
    embed = discord.Embed(
        title=f"📊 {target_user.display_name}'s Music Stats",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="Total Songs",
        value=f"`{total_songs}`",
        inline=True
    )
    
    embed.add_field(
        name="Total Plays",
        value=f"`{total_plays}`",
        inline=True
    )
    
    # Top 10 most played songs
    top_songs_text = ""
    for i, (song_title, song_data) in enumerate(sorted_songs[:10], 1):
        count = song_data['play_count']
        # Truncate long song titles
        display_title = song_title[:40] + "..." if len(song_title) > 40 else song_title
        top_songs_text += f"`{i}.` **{display_title}** - {count}x\n"
    
    if top_songs_text:
        embed.add_field(
            name="🎵 Top Songs",
            value=top_songs_text,
            inline=False
        )
    
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.set_footer(text="Track your music journey! 🎶")
    
    await ctx.send(embed=embed)

# -------------------------------------------------
# 9.  UTILITY COMMANDS
# -------------------------------------------------
@bot.command(name='ping')
async def ping(ctx):
    """Check bot latency"""
    await ctx.send(f'🏓 Pong! {round(bot.latency * 1000)}ms')

@bot.command(name='help')
async def help_command(ctx):
    """Show help"""
    embed = discord.Embed(
        title="🎯 Demon-Slayer Bot Help",
        description="Voice commands, music player with Spotify support",
        color=0xEB459E
    )
    
    embed.add_field(
        name="🔊 TTS Commands",
        value="• `!tanji <text>`\n• `!nezuko <text>`\n• `!zenitsu <text>`\n• `!inosuke <text>`\n• `!muzan <text>`\n• `!giyu <text>`\n• `!girl <text>`\n• `!boy <text>`\n• `!child <text>`\n\n**Indian Languages:**\n• `!hindi <text>` (Female)\n• `!hindim <text>` (Male)\n• `!telugu <text>` (Female)\n• `!telugum <text>` (Male)",
        inline=False
    )
    
    embed.add_field(
        name="🎵 Music Commands", 
        value="• `!play <song/url>`\n  → YouTube, Spotify tracks/playlists\n• `!skip` - skip to next song\n• `!queue` or `!q` - show queue\n• `!stop` - stop & clear queue\n• `!pause` / `!resume`\n• `!leave` or `!l`\n• `/clearqueue` - restart from song #1",
        inline=False
    )
    
    embed.add_field(
        name="🔧 Channel Settings (Admin)",
        value="• `!setmusicchannel [#channel]`\n  → Lock music/TTS to channel with control panel\n• `!removemusicchannel`\n• `!setfunchannel [#channel]`\n  → Lock anime/fun commands to channel\n• `!removefunchannel`",
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Utility Commands",
        value="• `!ping`\n• `!help`",
        inline=False
    )
    
    embed.add_field(
        name="🎭 Anime Reactions & Fun",
        value="• `!hug [@user]` - Hug someone\n• `!slap [@user]` - Slap someone\n• `!kiss [@user]` - Kiss someone\n• `!pat [@user]` - Pat someone's head\n• `!dance` - Dance!\n• `!cry` - Cry\n• `!laugh` - Laugh\n• `!meme` - Random anime meme\n• `!animequote` - Inspirational quote",
        inline=False
    )
    
    embed.set_footer(text="🎮 Use control panel buttons when music channel is set!")
    
    await ctx.send(embed=embed)

# -------------------------------------------------
# 9.5.  ADMIN SLASH COMMANDS
# -------------------------------------------------
@bot.tree.command(name="cleanbot", description="Delete the bot's messages in a channel")
@app_commands.describe(channel="Target text channel", limit="Max messages to scan (up to 1000)")
async def cleanbot(interaction: discord.Interaction, channel: discord.TextChannel = None, limit: int = 100):
    # Default to current channel
    channel = channel or interaction.channel
    # Clamp limit
    limit = max(1, min(limit, 1000))
    try:
        def is_bot(m: discord.Message):
            return m.author.id == bot.user.id
        deleted = await channel.purge(limit=limit, check=is_bot, bulk=True)
        await interaction.response.send_message(f"🧹 Deleted {len(deleted)} bot messages in {channel.mention}", ephemeral=True)
    except Exception as e:
        log.error(f"cleanbot error: {e}")
        # Keep silent for users; confirm ephemeral
        try:
            await interaction.response.send_message("✅ Cleanup attempted.", ephemeral=True)
        except:
            pass

@bot.tree.command(name="clearqueue", description="Clear the queue and restart music playback from song #1")
async def clearqueue(interaction: discord.Interaction):
    """Clear the queue and restart from the first song"""
    guild_id = interaction.guild.id
    
    # Check if there's a voice client
    if guild_id not in music_queues or not music_queues[guild_id]:
        await interaction.response.send_message("❌ No songs in queue to clear!", ephemeral=True)
        return
    
    try:
        # Get first song before clearing
        first_song = music_queues[guild_id][0] if music_queues[guild_id] else None
        
        # Clear the queue
        music_queues[guild_id].clear()
        queue_positions[guild_id] = 0
        
        # Stop current playback if any
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        
        # If there was a first song, add it back and play
        if first_song:
            music_queues[guild_id].append(first_song)
            await interaction.response.send_message("🔄 Queue cleared! Restarting from song #1...", ephemeral=False)
            
            # Play the first song
            if vc and vc.is_connected():
                await play_next(interaction.guild)
            else:
                await interaction.followup.send("⚠️ Bot not in voice channel. Use `!play` to start.", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Queue cleared!", ephemeral=False)
            
    except Exception as e:
        log.error(f"Error clearing queue: {e}")  
        try:
            await interaction.response.send_message("✅ Queue cleared!", ephemeral=True)
        except:
            pass

@bot.command(name='setmusicchannel')
@commands.has_permissions(administrator=True)
async def set_music_channel(ctx, channel: discord.TextChannel = None):
    """Set the channel for music/TTS commands with auto-updating control panel"""
    guild_id = ctx.guild.id
    
    if channel is None:
        channel = ctx.channel
    
    music_channels[guild_id] = channel.id
    save_channel_settings()  # Save to file
    await ctx.send(f"🎵 Music channel set to {channel.mention}\nAll music/TTS commands will be sent here with an auto-updating control panel at the bottom!")

@bot.command(name='removemusicchannel')
@commands.has_permissions(administrator=True)
async def remove_music_channel(ctx):
    """Remove the music channel lock"""
    guild_id = ctx.guild.id
    
    if guild_id in music_channels:
        del music_channels[guild_id]
        save_channel_settings()  # Save to file
        await ctx.send("✅ Music channel lock removed! Commands can be used anywhere now.")
    else:
        await ctx.send("❌ No music channel is set.")

@bot.command(name='setfunchannel')
@commands.has_permissions(administrator=True)
async def set_fun_channel(ctx, channel: discord.TextChannel = None):
    """Set the channel for anime/fun commands"""
    guild_id = ctx.guild.id
    
    if channel is None:
        channel = ctx.channel
    
    fun_channels[guild_id] = channel.id
    save_channel_settings()  # Save to file
    await ctx.send(f"🎭 Fun channel set to {channel.mention}\nAll anime/fun commands will be sent here!")

@bot.command(name='removefunchannel')
@commands.has_permissions(administrator=True)
async def remove_fun_channel(ctx):
    """Remove the fun channel lock"""
    guild_id = ctx.guild.id
    
    if guild_id in fun_channels:
        del fun_channels[guild_id]
        save_channel_settings()  # Save to file
        await ctx.send("✅ Fun channel lock removed! Commands can be used anywhere now.")
    else:
        await ctx.send("❌ No fun channel is set.")

# -------------------------------------------------
# 9.6.  ANIME REACTIONS & FUN COMMANDS
# -------------------------------------------------

async def get_tenor_gif(query: str) -> str:
    """Get a random GIF from Tenor API"""
    # Using Tenor API (no key required for basic usage)
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://tenor.googleapis.com/v2/search?q={query}&key=AIzaSyAyimkuYQYF_FXVALexPuGQctUWRURdCYQ&limit=20&media_filter=gif"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('results'):
                        gif = random.choice(data['results'])
                        return gif['media_formats']['gif']['url']
    except Exception as e:
        log.error(f"Tenor API error: {e}")
    return None

@bot.command(name='hug')
async def hug(ctx, member: discord.Member = None):
    """Hug someone or yourself"""
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['hug']))
    
    if member:
        if member.id == ctx.author.id:
            message = f"**{ctx.author.name}** hugs themselves! 🤗"
        else:
            message = f"**{ctx.author.name}** hugs **{member.name}**! 🤗💕"
    else:
        message = f"**{ctx.author.name}** wants a hug! 🤗"
    
    embed = discord.Embed(description=message, color=0xFF69B4)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='slap')
async def slap(ctx, member: discord.Member = None):
    """Slap someone"""
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['slap']))
    
    if member:
        if member.id == ctx.author.id:
            message = f"**{ctx.author.name}** slaps themselves... why? 🤦"
        else:
            message = f"**{ctx.author.name}** slaps **{member.name}**! 👋💥"
    else:
        message = f"**{ctx.author.name}** slaps the air! 👋"
    
    embed = discord.Embed(description=message, color=0xFF4500)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='kiss')
async def kiss(ctx, member: discord.Member = None):
    """Kiss someone"""
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['kiss']))
    
    if member:
        if member.id == ctx.author.id:
            message = f"**{ctx.author.name}** kisses themselves in the mirror! 💋😘"
        else:
            message = f"**{ctx.author.name}** kisses **{member.name}**! 💋💕✨"
    else:
        message = f"**{ctx.author.name}** blows a kiss! 😘💋"
    
    embed = discord.Embed(description=message, color=0xFF1493)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='pat')
async def pat(ctx, member: discord.Member = None):
    """Pat someone's head"""
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['pat']))
    
    if member:
        if member.id == ctx.author.id:
            message = f"**{ctx.author.name}** pats their own head! Good job! 👋😊"
        else:
            message = f"**{ctx.author.name}** pats **{member.name}**'s head! 👋💕"
    else:
        message = f"**{ctx.author.name}** wants head pats! 🥺"
    
    embed = discord.Embed(description=message, color=0xFFB6C1)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='dance')
async def dance(ctx):
    """Dance!"""
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['dance']))
    message = f"**{ctx.author.name}** is dancing! 💃🕺✨"
    
    embed = discord.Embed(description=message, color=0x9370DB)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='cry')
async def cry(ctx):
    """Cry"""
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['cry']))
    message = f"**{ctx.author.name}** is crying! 😢💔"
    
    embed = discord.Embed(description=message, color=0x4682B4)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='laugh')
async def laugh(ctx):
    """Laugh"""
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['laugh']))
    message = f"**{ctx.author.name}** is laughing! 😂🤣"
    
    embed = discord.Embed(description=message, color=0xFFD700)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='animequote')
async def animequote(ctx):
    """Get a random anime quote"""
    quote = random.choice(ANIME_QUOTES)
    embed = discord.Embed(
        title="✨ Anime Quote ✨",
        description=quote,
        color=0xFF6347
    )
    embed.set_footer(text="Stay motivated!")
    await ctx.send(embed=embed)

@bot.command(name='meme')
async def meme(ctx):
    """Get a random anime meme"""
    meme_queries = [
        "anime meme",
        "demon slayer meme",
        "naruto meme",
        "one piece meme",
        "attack on titan meme",
        "jojo meme"
    ]
    gif_url = await get_tenor_gif(random.choice(meme_queries))
    
    embed = discord.Embed(
        title="🎭 Anime Meme 🎭",
        color=0x00FF00
    )
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

# Helper function for user-to-user interactions
async def user_interaction(ctx, member, action_key, emoji, color):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS[action_key]))
    if member:
        if member.id == ctx.author.id:
            message = f"**{ctx.author.name}** {action_key}s themselves! {emoji}"
        else:
            message = f"**{ctx.author.name}** {action_key}s **{member.name}**! {emoji}"
    else:
        message = f"**{ctx.author.name}** {action_key}s the air! {emoji}"
    embed = discord.Embed(description=message, color=color)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

# Additional interaction commands
@bot.command(name='cuddle')
async def cuddle(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'cuddle', '🤗💕', 0xFFC0CB)

@bot.command(name='hold')
async def hold(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'hold', '🤝💖', 0xFFB6C1)

@bot.command(name='bite')
async def bite(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'bite', '🧛‍♂️👸', 0x8B0000)

@bot.command(name='lick')
async def lick(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'lick', '👅😛', 0xFF69B4)

@bot.command(name='poke')
async def poke(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'poke', '👉😄', 0x87CEEB)

@bot.command(name='boop')
async def boop(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'boop', '👉👃', 0xFFDAB9)

@bot.command(name='bonk')
async def bonk(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'bonk', '🔨💥', 0xFF4500)

@bot.command(name='punch')
async def punch(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'punch', '👊💥', 0xDC143C)

@bot.command(name='kick')
async def kick(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'kick', '🦵💨', 0xFF6347)

@bot.command(name='stab')
async def stab(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'stab', '🗡️⚔️', 0x8B0000)

@bot.command(name='throw')
async def throw(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'throw', '🤾💨', 0xFF8C00)

@bot.command(name='feed')
async def feed(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'feed', '🍚🥄', 0xFFA500)

@bot.command(name='offer')
async def offer(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'offer', '🎁✨', 0xFFD700)

@bot.command(name='protect')
async def protect(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'protect', '🛡️⚔️', 0x4169E1)

@bot.command(name='carry')
async def carry(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'carry', '👑💕', 0xFF1493)

@bot.command(name='snuggle')
async def snuggle(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'snuggle', '🥰💕', 0xFFB6D9)

@bot.command(name='scare')
async def scare(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'scare', '👻😱', 0x800080)

@bot.command(name='tickle')
async def tickle(ctx, member: discord.Member = None):
    await user_interaction(ctx, member, 'tickle', '🤣😂', 0xFFD700)

# Solo reaction commands
@bot.command(name='blush')
async def blush(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['blush']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is blushing! 😳💕", color=0xFFB6C1)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='angry')
async def angry(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['angry']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is angry! 😡💢", color=0xFF0000)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='mad')
async def mad(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['mad']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is mad! 👿🔥", color=0x8B0000)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='happy')
async def happy(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['happy']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is happy! 😊✨", color=0xFFD700)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='sleepy')
async def sleepy(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['sleepy']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is sleepy! 😴💤", color=0x4682B4)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='confused')
async def confused(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['confused']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is confused! 🤔❓", color=0x9370DB)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='wow')
async def wow(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['wow']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is amazed! 😮✨", color=0xFF69B4)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='shy')
async def shy(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['shy']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is feeling shy! 😳💉💈", color=0xFFB6C1)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='sip')
async def sip(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['sip']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is sipping tea! ☕🍵", color=0x8B4513)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='stare')
async def stare(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['stare']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is staring intensely! 👀🔥", color=0x4B0082)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='panic')
async def panic(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['panic']))
    embed = discord.Embed(description=f"**{ctx.author.name}** is panicking! 😨🏃💨", color=0xFF6347)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='facepalm')
async def facepalm(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['facepalm']))
    embed = discord.Embed(description=f"**{ctx.author.name}** facepalms! 🤦😒", color=0x808080)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

# Anime power/attack commands
@bot.command(name='boom')
async def boom(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['boom']))
    embed = discord.Embed(description=f"**{ctx.author.name}** creates a huge explosion! 💥🔥💣", color=0xFF4500)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='bankai')
async def bankai(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['bankai']))
    embed = discord.Embed(description=f"**{ctx.author.name}** activates BANKAI! ⚔️🌊⚡", color=0x4169E1)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='rasengan')
async def rasengan(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['rasengan']))
    embed = discord.Embed(description=f"**{ctx.author.name}** uses RASENGAN! 🌀💥", color=0x0000FF)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='chidori')
async def chidori(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['chidori']))
    embed = discord.Embed(description=f"**{ctx.author.name}** uses CHIDORI! ⚡👊", color=0x00CED1)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='gumgum')
async def gumgum(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['gumgum']))
    embed = discord.Embed(description=f"**{ctx.author.name}** uses GUM-GUM ATTACK! 🥊💥", color=0xDC143C)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='breathing')
async def breathing(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['breathing']))
    embed = discord.Embed(description=f"**{ctx.author.name}** uses BREATHING TECHNIQUE! 🌊⚔️🔥", color=0x1E90FF)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='gear5')
async def gear5(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['gear5']))
    embed = discord.Embed(description=f"**{ctx.author.name}** activates GEAR 5! ☀️🔥🤣", color=0xFFD700)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='ultra')
async def ultra(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['ultra']))
    embed = discord.Embed(description=f"**{ctx.author.name}** enters ULTRA INSTINCT! ✨👁️🔥", color=0xC0C0C0)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='plusultra')
async def plusultra(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['plusultra']))
    embed = discord.Embed(description=f"**{ctx.author.name}** shouts PLUS ULTRA! 💪🔥⭐", color=0xFF0000)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='titan')
async def titan(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['titan']))
    embed = discord.Embed(description=f"**{ctx.author.name}** transforms into a TITAN! 🟥👺💥", color=0x8B0000)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='summon')
async def summon(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['summon']))
    embed = discord.Embed(description=f"**{ctx.author.name}** summons a powerful creature! 🐉✨🔮", color=0x9400D3)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='isekai')
async def isekai(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['isekai']))
    embed = discord.Embed(description=f"**{ctx.author.name}** got hit by Truck-kun and isekai'd! 🚚✨🌎", color=0xFF1493)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='transform')
async def transform(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['transform']))
    embed = discord.Embed(description=f"**{ctx.author.name}** transforms! ✨💥🔥", color=0xFF69B4)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='powerup')
async def powerup(ctx):
    gif_url = await get_tenor_gif(random.choice(ANIME_GIFS['powerup']))
    embed = discord.Embed(description=f"**{ctx.author.name}** powers up! 💥⚡🔥✨", color=0xFFD700)
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

# Rating and fun commands
@bot.command(name='rate')
async def rate(ctx, *, thing: str):
    rating = random.randint(1, 100)
    embed = discord.Embed(
        title="🎯 Rating System",
        description=f"**{thing}** is rated **{rating}/100**!",
        color=0xFF1493
    )
    await ctx.send(embed=embed)

@bot.command(name='simprate')
async def simprate(ctx, member: discord.Member = None):
    target = member or ctx.author
    rate = random.randint(1, 100)
    embed = discord.Embed(
        title="💖 Simp Meter",
        description=f"**{target.name}** is **{rate}% simp**!",
        color=0xFF69B4
    )
    await ctx.send(embed=embed)

@bot.command(name='driprate')
async def driprate(ctx, member: discord.Member = None):
    target = member or ctx.author
    rate = random.randint(1, 100)
    embed = discord.Embed(
        title="👗 Drip Meter",
        description=f"**{target.name}** has **{rate}% drip**! 🔥",
        color=0x1E90FF
    )
    await ctx.send(embed=embed)

@bot.command(name='hotrate')
async def hotrate(ctx, member: discord.Member = None):
    target = member or ctx.author
    rate = random.randint(1, 100)
    embed = discord.Embed(
        title="🔥 Hot Meter",
        description=f"**{target.name}** is **{rate}% hot**!",
        color=0xFF4500
    )
    await ctx.send(embed=embed)

@bot.command(name='iq')
async def iq(ctx, member: discord.Member = None):
    target = member or ctx.author
    iq_value = random.randint(50, 200)
    embed = discord.Embed(
        title="🧠 IQ Test",
        description=f"**{target.name}**'s IQ is **{iq_value}**!",
        color=0x9370DB
    )
    await ctx.send(embed=embed)

@bot.command(name='ship')
async def ship(ctx, user1: discord.Member, user2: discord.Member = None):
    if not user2:
        user2 = ctx.author
    compatibility = random.randint(1, 100)
    hearts = '❤️' * (compatibility // 20)
    embed = discord.Embed(
        title="💕 Ship Compatibility",
        description=f"**{user1.name}** ❤️ **{user2.name}**\n{hearts}\n**{compatibility}% compatible!**",
        color=0xFF1493
    )
    await ctx.send(embed=embed)

# Anime-specific commands
@bot.command(name='breathingstyle')
async def breathingstyle(ctx):
    style = random.choice(BREATHING_STYLES)
    embed = discord.Embed(
        title="⚔️ Demon Slayer Breathing Style",
        description=f"**{ctx.author.name}** has mastered **{style}**!",
        color=0x1E90FF
    )
    await ctx.send(embed=embed)

@bot.command(name='quirk')
async def quirk(ctx):
    quirk = random.choice(QUIRKS)
    embed = discord.Embed(
        title="✨ My Hero Academia Quirk",
        description=f"**{ctx.author.name}**'s quirk is **{quirk}**!",
        color=0xFF0000
    )
    await ctx.send(embed=embed)

@bot.command(name='stand')
async def stand(ctx):
    stand = random.choice(STANDS)
    embed = discord.Embed(
        title="👊 JoJo Stand",
        description=f"**{ctx.author.name}**'s Stand is **{stand}**!",
        color=0xFFD700
    )
    await ctx.send(embed=embed)

@bot.command(name='demonrank')
async def demonrank(ctx):
    rank = random.choice(DEMON_RANKS)
    embed = discord.Embed(
        title="🌙 Demon Rank",
        description=f"**{ctx.author.name}** is **{rank}**!",
        color=0x800080
    )
    await ctx.send(embed=embed)

@bot.command(name='battle')
async def battle(ctx, member: discord.Member):
    winner = random.choice([ctx.author, member])
    gif_url = await get_tenor_gif("anime battle epic")
    embed = discord.Embed(
        title="⚔️ Epic Anime Battle!",
        description=f"**{ctx.author.name}** vs **{member.name}**\n\n**Winner: {winner.name}!** 🏆",
        color=0xFF4500
    )
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='villain')
async def villain(ctx, member: discord.Member):
    """Turn someone into an anime villain"""
    villain_names = [
        "Dark Shadow Master", "The Crimson Phantom", "Lord of Destruction",
        "The Black Emperor", "Demon King", "Shadow Overlord",
        "The Cursed One", "Master of Chaos", "The Dark Flame"
    ]
    villain_powers = [
        "controls darkness", "manipulates time", "summons demons",
        "has infinite power", "can destroy worlds", "controls minds",
        "wields cursed weapons", "summons shadow armies", "bends reality"
    ]
    
    name = random.choice(villain_names)
    power = random.choice(villain_powers)
    
    gif_url = await get_tenor_gif("anime villain")
    embed = discord.Embed(
        title="😈 Villain Transformation! 😈",
        description=(
            f"**{member.name}** has transformed into a villain!\n\n"
            f"**Villain Name:** {name}\n"
            f"**Power:** {power.capitalize()}\n\n"
            "💀 Evil aura intensifies... 💀"
        ),
        color=0x8B0000
    )
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='theme')
async def theme(ctx, member: discord.Member):
    """Give someone an anime theme song"""
    themes = [
        {"song": "Unravel", "anime": "Tokyo Ghoul", "vibe": "Dark & Mysterious"},
        {"song": "Gurenge", "anime": "Demon Slayer", "vibe": "Powerful & Determined"},
        {"song": "Cruel Angel's Thesis", "anime": "Evangelion", "vibe": "Epic & Legendary"},
        {"song": "Blue Bird", "anime": "Naruto", "vibe": "Hopeful & Free"},
        {"song": "The World", "anime": "Death Note", "vibe": "Intense & Strategic"},
        {"song": "Guren no Yumiya", "anime": "Attack on Titan", "vibe": "Heroic & Bold"},
        {"song": "Silhouette", "anime": "Naruto", "vibe": "Emotional & Strong"},
        {"song": "COLORS", "anime": "Code Geass", "vibe": "Revolutionary & Bold"},
        {"song": "My War", "anime": "Attack on Titan", "vibe": "Dark & Intense"},
        {"song": "Inferno", "anime": "Fire Force", "vibe": "Fiery & Energetic"}
    ]
    
    theme = random.choice(themes)
    
    gif_url = await get_tenor_gif(f"{theme['anime']} opening")
    embed = discord.Embed(
        title="🎵 Your Anime Theme Song! 🎵",
        description=(
            f"**{member.name}**'s theme song is:\n\n"
            f"🎶 **{theme['song']}**\n"
            f"📺 From: {theme['anime']}\n"
            f"✨ Vibe: {theme['vibe']}\n\n"
            "*This song plays whenever they enter!*"
        ),
        color=0xFF1493
    )
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='story')
async def story(ctx, *, start: str):
    """Auto-generate an anime story"""
    # Story elements
    characters = [
        "a brave hero", "a mysterious stranger", "a cursed warrior",
        "a demon slayer", "a ninja", "a powerful mage"
    ]
    locations = [
        "a hidden village", "a dark forest", "a floating castle",
        "the underworld", "a cyberpunk city", "a mystical realm"
    ]
    conflicts = [
        "an ancient evil awakens", "a portal to another dimension opens",
        "a powerful artifact is stolen", "the world begins to crumble",
        "a deadly tournament begins", "a curse spreads across the land"
    ]
    twists = [
        "but they discover they have hidden powers",
        "when suddenly, their ally betrays them",
        "and realizes they're the chosen one",
        "until a mysterious figure appears",
        "when they unlock their true form",
        "but nothing is as it seems"
    ]
    endings = [
        "To be continued...", "The adventure has just begun!",
        "Their destiny awaits...", "The real battle starts now!",
        "A new saga begins...", "The legend continues..."
    ]
    
    character = random.choice(characters)
    location = random.choice(locations)
    conflict = random.choice(conflicts)
    twist = random.choice(twists)
    ending = random.choice(endings)
    
    story = (
        f"{start}... {character} finds themselves in {location}. "
        f"Suddenly, {conflict}! They must face this challenge, "
        f"{twist}. {ending}"
    )
    
    gif_url = await get_tenor_gif("anime story epic")
    embed = discord.Embed(
        title="📖 Auto-Generated Anime Story 📖",
        description=story,
        color=0x9370DB
    )
    embed.set_footer(text=f"Story by: {ctx.author.name}")
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

@bot.command(name='confess')
async def confess(ctx, member: discord.Member):
    gif_url = await get_tenor_gif("anime confession love")
    embed = discord.Embed(
        description=f"**{ctx.author.name}** confesses to **{member.name}**! 💖💌✨",
        color=0xFF69B4
    )
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

# Audio/Sound effect commands
@bot.command(name='moan')
async def moan(ctx):
    """Play anime moan sound effect"""
    await play_tts(ctx, "girl", text="Ahhhh... *moans*")

@bot.command(name='scream')
async def scream(ctx):
    """Play anime scream sound effect"""
    await play_tts(ctx, "girl", text="KYAAAAAAAAA! AHHHHHHHH!")

@bot.command(name='laughaudio')
async def laughaudio(ctx):
    """Play anime laugh sound effect"""
    await play_tts(ctx, "girl", text="Hahahahaha! Hehehehe! Fufufufu~")

@bot.command(name='bassboost')
async def bassboost(ctx):
    """Bass boost the current audio"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        # Increase volume for bass boost effect
        if hasattr(ctx.voice_client.source, 'volume'):
            ctx.voice_client.source.volume = min(2.0, ctx.voice_client.source.volume + 0.5)
            await ctx.send("🔊💥 BASS BOOSTED! 🔊💥")
    else:
        await ctx.send("❌ No audio playing to bass boost!")

@bot.command(name='nekoaudio')
async def nekoaudio(ctx):
    """Play neko/cat girl sound"""
    await play_tts(ctx, "child", text="Nya nya~ Meow meow~ Nyan nyan~")

@bot.command(name='animegirl')
async def animegirl(ctx):
    """Get a random anime girl GIF"""
    anime_girl_queries = [
        "anime girl cute",
        "anime waifu",
        "anime girl kawaii",
        "demon slayer nezuko",
        "anime girl smile"
    ]
    gif_url = await get_tenor_gif(random.choice(anime_girl_queries))
    embed = discord.Embed(
        title="✨ Anime Girl ✨",
        color=0xFF69B4
    )
    if gif_url:
        embed.set_image(url=gif_url)
    await ctx.send(embed=embed)

# -------------------------------------------------
# 9.7.  ADVANCED FEATURES - FUSION & GAMES
# -------------------------------------------------

# Temple Run Game Storage
temple_run_sessions = {}  # user_id: {score, active, last_event}
temple_run_leaderboard = {}  # guild_id: {user_id: best_score}
temple_run_global = {}  # user_id: best_score

@bot.command(name='fusion')
async def fusion(ctx, user1: discord.Member, user2: discord.Member = None):
    """Fuse two users into an anime fusion form"""
    # If only one user mentioned, fuse with command author
    if user2 is None:
        user2 = ctx.author
    
    # Prevent self-fusion if both are same
    if user1.id == user2.id:
        await ctx.send("❌ You can't fuse with yourself!")
        return
    
    # Generate fusion name
    name1 = user1.display_name
    name2 = user2.display_name
    
    # Simple fusion: take first half of name1 + second half of name2
    mid1 = len(name1) // 2
    mid2 = len(name2) // 2
    fused_name = name1[:mid1] + name2[mid2:]
    
    # Fusion titles
    titles = [
        "the Thunder Hashira", "the Flame Pillar", "the Water Guardian",
        "the Shadow Master", "the Lightning Sage", "the Storm Bringer",
        "the Eternal Warrior", "the Crimson Knight", "the Azure Dragon",
        "the Mystic Phoenix", "the Void Walker", "the Star Breaker"
    ]
    
    # Breathing styles/Powers
    powers = [
        "Thunder x Rage Fusion", "Flame x Water Fusion", "Wind x Lightning Fusion",
        "Shadow x Light Fusion", "Ice x Fire Fusion", "Cosmic x Void Fusion",
        "Divine x Demon Fusion", "Dragon x Phoenix Fusion", "Storm x Earth Fusion"
    ]
    
    # Personality traits
    trait_list = [
        ["Brave", "Hot-headed", "Loyal"],
        ["Calm", "Strategic", "Mysterious"],
        ["Energetic", "Chaotic", "Friendly"],
        ["Wise", "Patient", "Powerful"],
        ["Reckless", "Funny", "Strong"],
        ["Cold", "Calculating", "Intense"]
    ]
    
    # Theme music
    themes = [
        "Epic Battle Symphony", "Thunderous Awakening", "Crimson Destiny",
        "Shadow Dance", "Phoenix Rising", "Storm of Legends",
        "Eternal Flames", "Celestial Warrior", "Dark Hero's March"
    ]
    
    # Generate power level (random but consistent for same pair)
    seed = user1.id + user2.id
    random.seed(seed)
    power_level = random.randint(75000, 99999)
    title = random.choice(titles)
    power = random.choice(powers)
    traits = random.choice(trait_list)
    theme = random.choice(themes)
    random.seed()  # Reset seed
    
    # Get fusion GIF
    gif_url = await get_tenor_gif("anime fusion transformation power")
    
    # Create embed
    embed = discord.Embed(
        title=f"🌟 FUSION COMPLETE! 🌟",
        description=f"**{user1.display_name}** + **{user2.display_name}** = **{fused_name} {title}**",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="⚡ Power Level",
        value=f"`{power_level:,}`",
        inline=True
    )
    
    embed.add_field(
        name="🔥 Breathing Style",
        value=f"`{power}`",
        inline=True
    )
    
    embed.add_field(
        name="🎵 Theme Music",
        value=f"*{theme}*",
        inline=False
    )
    
    embed.add_field(
        name="✨ Personality",
        value=" • ".join(traits),
        inline=False
    )
    
    if gif_url:
        embed.set_image(url=gif_url)
    
    embed.set_footer(text="Fusion will last forever in our hearts! 💫")
    
    await ctx.send(embed=embed)

@bot.command(name='run')
async def temple_run(ctx, option: str = None):
    """Start Temple Run game or view leaderboards"""
    user_id = ctx.author.id
    guild_id = ctx.guild.id if ctx.guild else 0
    
    # Check for leaderboard options
    if option == "-s" or option == "--server":
        # Server leaderboard
        if guild_id not in temple_run_leaderboard or not temple_run_leaderboard[guild_id]:
            await ctx.send("📊 **Server Leaderboard**\n\nNo scores yet! Be the first to play `/run`")
            return
        
        # Sort by score
        scores = temple_run_leaderboard[guild_id]
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
        
        leaderboard_text = "📊 **Server Leaderboard - Top 10**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        
        for idx, (uid, score) in enumerate(sorted_scores, 1):
            try:
                user = await bot.fetch_user(uid)
                name = user.display_name
            except:
                name = "Unknown"
            
            medal = medals[idx-1] if idx <= 3 else f"`{idx}.`"
            leaderboard_text += f"{medal} **{name}** - {score} points\n"
        
        await ctx.send(leaderboard_text)
        return
    
    elif option == "-l" or option == "--leaderboard":
        # Global leaderboard
        if not temple_run_global:
            await ctx.send("🌍 **Global Leaderboard**\n\nNo scores yet! Be the first to play `/run`")
            return
        
        sorted_scores = sorted(temple_run_global.items(), key=lambda x: x[1], reverse=True)[:10]
        
        leaderboard_text = "🌍 **Global Leaderboard - Top 10**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        
        for idx, (uid, score) in enumerate(sorted_scores, 1):
            try:
                user = await bot.fetch_user(uid)
                name = user.display_name
            except:
                name = "Unknown"
            
            medal = medals[idx-1] if idx <= 3 else f"`{idx}.`"
            leaderboard_text += f"{medal} **{name}** - {score} points\n"
        
        await ctx.send(leaderboard_text)
        return
    
    # Start game
    if user_id in temple_run_sessions and temple_run_sessions[user_id].get('active'):
        await ctx.send("❌ You already have an active game! Finish it first.")
        return
    
    # Initialize session
    temple_run_sessions[user_id] = {
        'active': True,
        'score': 0,
        'channel_id': ctx.channel.id,
        'last_event': None
    }
    
    await ctx.send(f"🏃 **{ctx.author.display_name} started Temple Run!**\n\n🎮 Respond quickly with:\n`!jump` or `!j`\n`!slide` or `!sd`\n`!goleft` or `!gl`\n`!goright` or `!gr`\n`!fight` or `!ft`\n\n⚡ You have **1.5 seconds** to respond!\n\n🎯 Starting in 3...")
    
    await asyncio.sleep(1)
    await ctx.send("2...")
    await asyncio.sleep(1)
    await ctx.send("1... GO! 🏃💨")
    await asyncio.sleep(0.5)
    
    # Start game loop
    await temple_run_game_loop(ctx, user_id)

async def temple_run_game_loop(ctx, user_id):
    """Main game loop for Temple Run"""
    session = temple_run_sessions.get(user_id)
    if not session or not session['active']:
        return
    
    events = [
        ("Jump!", "jump", "j", "⬆️"),
        ("Slide!", "slide", "sd", "⬇️"),
        ("Left!", "goleft", "gl", "⬅️"),
        ("Right!", "goright", "gr", "➡️"),
        ("Fight monkey!", "fight", "ft", "🐒"),
        ("Treasure chest!", "fight", "ft", "💎")
    ]
    
    for round_num in range(15):  # 15 rounds
        if not session['active']:
            break
        
        # Pick random event
        event = random.choice(events)
        event_name, cmd1, cmd2, emoji = event
        
        # Store expected response
        session['last_event'] = (cmd1, cmd2)
        session['waiting'] = True
        session['round'] = round_num + 1
        
        # Send event
        await ctx.send(f"{emoji} **{event_name}** {emoji}\n⏱️ Quick!")
        
        # Wait for response (1.5 seconds)
        await asyncio.sleep(1.5)
        
        # Check if still waiting (user didn't respond)
        if session.get('waiting'):
            # Failed to respond in time
            await ctx.send(f"💥 **GAME OVER!** You didn't respond in time!\n\n🏆 Final Score: **{session['score']} points**")
            await update_leaderboards(ctx, user_id, session['score'])
            session['active'] = False
            return
    
    # Completed all rounds!
    await ctx.send(f"🎉 **INCREDIBLE!** You completed all rounds!\n\n🏆 Final Score: **{session['score']} points**\n⭐ +50 BONUS for completion!")
    session['score'] += 50
    await update_leaderboards(ctx, user_id, session['score'])
    session['active'] = False

async def update_leaderboards(ctx, user_id, score):
    """Update server and global leaderboards"""
    guild_id = ctx.guild.id if ctx.guild else 0
    
    # Update global leaderboard
    if user_id not in temple_run_global or score > temple_run_global[user_id]:
        temple_run_global[user_id] = score
    
    # Update server leaderboard
    if guild_id:
        if guild_id not in temple_run_leaderboard:
            temple_run_leaderboard[guild_id] = {}
        
        if user_id not in temple_run_leaderboard[guild_id] or score > temple_run_leaderboard[guild_id][user_id]:
            temple_run_leaderboard[guild_id][user_id] = score

# Temple Run response commands
@bot.command(name='jump', aliases=['j'])
async def temple_jump(ctx):
    """Jump command for Temple Run"""
    await process_temple_run_action(ctx, "jump", "j")

@bot.command(name='slide', aliases=['sd'])
async def temple_slide(ctx):
    """Slide command for Temple Run"""
    await process_temple_run_action(ctx, "slide", "sd")

@bot.command(name='goleft', aliases=['gl'])
async def temple_left(ctx):
    """Left command for Temple Run"""
    await process_temple_run_action(ctx, "goleft", "gl")

@bot.command(name='goright', aliases=['gr'])
async def temple_right(ctx):
    """Right command for Temple Run"""
    await process_temple_run_action(ctx, "goright", "gr")

@bot.command(name='fight', aliases=['ft'])
async def temple_fight(ctx):
    """Fight command for Temple Run"""
    await process_temple_run_action(ctx, "fight", "ft")

async def process_temple_run_action(ctx, action1, action2):
    """Process Temple Run player action"""
    user_id = ctx.author.id
    
    # Check if user has active session
    if user_id not in temple_run_sessions or not temple_run_sessions[user_id].get('active'):
        return
    
    session = temple_run_sessions[user_id]
    
    # Check if in correct channel
    if session['channel_id'] != ctx.channel.id:
        return
    
    # Check if waiting for response
    if not session.get('waiting'):
        return
    
    # Check if correct action
    expected = session.get('last_event')
    if not expected:
        return
    
    expected_cmd1, expected_cmd2 = expected
    
    if action1 == expected_cmd1 or action2 == expected_cmd2:
        # Correct!
        session['waiting'] = False
        session['score'] += 10
        
        reactions = ["✅", "🔥", "💯", "⚡", "🎯"]
        await ctx.send(f"{random.choice(reactions)} **Nice!** +10 points | Score: {session['score']}")
    else:
        # Wrong action
        await ctx.send(f"❌ **WRONG ACTION!** Game Over!\n\n🏆 Final Score: **{session['score']} points**")
        await update_leaderboards(ctx, user_id, session['score'])
        session['active'] = False

# -------------------------------------------------
# 9.8. ANIME CHARACTER COMMANDS (OP / Naruto / Bleach)
# -------------------------------------------------
CHARACTER_UNIVERSE = {
    'luffy': 'one piece', 'zoro': 'one piece', 'nami': 'one piece', 'sanji': 'one piece',
    'usopp': 'one piece', 'chopper': 'one piece', 'robin': 'one piece', 'franky': 'one piece',
    'brook': 'one piece', 'jinbe': 'one piece', 'ace': 'one piece', 'sabo': 'one piece',
    'law': 'one piece', 'boa': 'one piece', 'mihawk': 'one piece', 'shanks': 'one piece',
    'naruto': 'naruto', 'sasuke': 'naruto', 'sakura': 'naruto', 'kakashi': 'naruto',
    'hinata': 'naruto', 'gaara': 'naruto', 'itachi': 'naruto', 'madara': 'naruto',
    'orochimaru': 'naruto', 'tsunade': 'naruto', 'jiraiya': 'naruto',
    'ichigo': 'bleach', 'rukia': 'bleach', 'byakuya': 'bleach', 'aizen': 'bleach',
    'kenpachi': 'bleach', 'hitsugaya': 'bleach', 'ulquiorra': 'bleach', 'grimmjow': 'bleach', 'renji': 'bleach'
}

async def character_action(ctx, character: str, member: discord.Member = None, action: str = None):
    char = character.lower()
    anime = CHARACTER_UNIVERSE.get(char, 'anime')
    base_action = (action or '').strip()
    
    queries = []
    if base_action:
        queries = [
            f"{anime} {char} {base_action}",
            f"{char} {base_action} {anime}",
            f"{char} {base_action} gif"
        ]
    else:
        queries = [
            f"{anime} {char} gif",
            f"{char} {anime} scene",
            f"{char} anime"
        ]
    
    gif_url = None
    for q in queries:
        gif_url = await get_tenor_gif(q)
        if gif_url:
            break
    
    display_char = char.title()
    author = ctx.author.display_name
    target = member.display_name if member else author
    
    if base_action:
        verb = base_action if base_action.endswith('e') else base_action
        if member:
            desc = f"**{display_char}** {verb}s **{target}**! Requested by **{author}**"
        else:
            desc = f"**{display_char}** {verb}s **{target}**!"
    else:
        desc = f"**{display_char}** sends regards to **{target}**!"
    
    embed = discord.Embed(description=desc, color=0xEB459E)
    if gif_url:
        embed.set_image(url=gif_url)
    embed.set_footer(text=f"{display_char} • {anime.title()}")
    await ctx.send(embed=embed)

# Register many short commands
for _name in [
    # One Piece
    'luffy','zoro','nami','sanji','usopp','chopper','robin','franky','brook','jinbe','ace','sabo','law','boa','mihawk','shanks',
    # Naruto
    'naruto','sasuke','sakura','kakashi','hinata','gaara','itachi','madara','orochimaru','tsunade','jiraiya',
    # Bleach
    'ichigo','rukia','byakuya','aizen','kenpachi','hitsugaya','ulquiorra','grimmjow','renji'
]:
    @bot.command(name=_name)
    async def _(ctx, member: discord.Member = None, *, action: str = None, __name=_name):
        await character_action(ctx, __name, member, action)











# -------------------------------------------------
# 9.10. MODERATION & ONBOARDING
# -------------------------------------------------
BOT_DATA_FILE = Path("music/bot_data.json")

def load_bot_data():
    try:
        if BOT_DATA_FILE.exists():
            with open(BOT_DATA_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        log.error(f"Failed to load bot data: {e}")
    return {}

def save_bot_data(data):
    try:
        BOT_DATA_FILE.parent.mkdir(exist_ok=True)
        with open(BOT_DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save bot data: {e}")

def get_guild_settings(guild_id: int):
    data = load_bot_data()
    g = str(guild_id)
    if g not in data:
        data[g] = {
            "protection_enabled": False,
            "log_channel_id": None,
            "welcome_channel_id": None,
            "member_role_id": None,
            "bot_role_id": None
        }
        save_bot_data(data)
    return data[g]

def set_guild_settings(guild_id: int, **updates):
    data = load_bot_data()
    g = str(guild_id)
    if g not in data:
        data[g] = {}
    data[g].update(updates)
    save_bot_data(data)

async def ensure_log_channel(guild: discord.Guild) -> discord.TextChannel:
    settings = get_guild_settings(guild.id)
    ch = None
    if settings.get("log_channel_id"):
        ch = guild.get_channel(settings["log_channel_id"])
    if not ch:
        try:
            ch = await guild.create_text_channel(name="ash-logs")
        except:
            # Fallback: use system channel or first text channel
            ch = guild.system_channel or discord.utils.get(guild.text_channels)
    if ch:
        set_guild_settings(guild.id, log_channel_id=ch.id)
    return ch

# Profanity lists by severity
BAD_WORDS = {
    1: {"dumb","idiot","stupid"},
    2: {"hell","damn","bastard"},
    3: {"f***","motherf***","c***","s***","b****"}
}

def check_severity(text: str):
    t = text.lower()
    for level in (3,2,1):
        for w in BAD_WORDS[level]:
            if w in t:
                return level, w
    return 0, None

@bot.tree.command(name="protection", description="Enable or disable bad-word protection")
@app_commands.describe(mode="Choose enable or disable")
@app_commands.choices(mode=[app_commands.Choice(name="enable", value="enable"), app_commands.Choice(name="disable", value="disable")])
async def protection_cmd(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ Run in a server.", ephemeral=True)
        return
    enabled = (mode.value == "enable")
    set_guild_settings(guild.id, protection_enabled=enabled)
    if enabled:
        await ensure_log_channel(guild)
    await interaction.response.send_message(
        f"🛡️ Protection {'enabled' if enabled else 'disabled'}.", ephemeral=True
    )

@bot.tree.command(name="setupjoin", description="Set welcome channel and roles for auto-assign")
@app_commands.describe(channel="Welcome channel", member_role="Member role", bot_role="Bot role")
async def setupjoin(interaction: discord.Interaction, channel: discord.TextChannel, member_role: discord.Role = None, bot_role: discord.Role = None):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ Run in a server.", ephemeral=True)
        return
    # Create roles if missing and not provided
    if not member_role:
        member_role = discord.utils.get(guild.roles, name="Member")
        if not member_role:
            try:
                member_role = await guild.create_role(name="Member")
            except:
                pass
    if not bot_role:
        bot_role = discord.utils.get(guild.roles, name="Bot")
        if not bot_role:
            try:
                bot_role = await guild.create_role(name="Bot")
            except:
                pass
    set_guild_settings(
        guild.id,
        welcome_channel_id=channel.id,
        member_role_id=member_role.id if member_role else None,
        bot_role_id=bot_role.id if bot_role else None
    )
    await interaction.response.send_message(
        f"✅ Setup saved. Welcome: {channel.mention}\nMember role: {member_role.mention if member_role else 'None'}\nBot role: {bot_role.mention if bot_role else 'None'}",
        ephemeral=True
    )

@bot.tree.command(name="autorole", description="Set roles for auto assignment")
@app_commands.describe(member_role="Member role", bot_role="Bot role")
async def autorole(interaction: discord.Interaction, member_role: discord.Role = None, bot_role: discord.Role = None):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ Run in a server.", ephemeral=True)
        return
    # Resolve or create roles
    if not member_role:
        member_role = discord.utils.get(guild.roles, name="Member")
        if not member_role:
            try:
                member_role = await guild.create_role(name="Member")
            except:
                pass
    if not bot_role:
        bot_role = discord.utils.get(guild.roles, name="Bot")
        if not bot_role:
            try:
                bot_role = await guild.create_role(name="Bot")
            except:
                pass
    set_guild_settings(
        guild.id,
        member_role_id=member_role.id if member_role else None,
        bot_role_id=bot_role.id if bot_role else None
    )
    await interaction.response.send_message(
        f"✅ Auto-role updated.\nMember role: {member_role.mention if member_role else 'None'}\nBot role: {bot_role.mention if bot_role else 'None'}",
        ephemeral=True
    )

@bot.tree.command(name="lock", description="Lock a channel (prevent @everyone from sending)")
@app_commands.describe(channel="Target text channel (defaults to current)")
async def lock_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ Run in a server.", ephemeral=True)
        return
    ch = channel or interaction.channel
    if not ch:
        await interaction.response.send_message("❌ No channel context.", ephemeral=True)
        return
    # Permission check
    perms = ch.permissions_for(interaction.user)
    if not perms.manage_channels:
        await interaction.response.send_message("❌ You need Manage Channels permission.", ephemeral=True)
        return
    overwrites = ch.overwrites_for(guild.default_role)
    overwrites.send_messages = False
    try:
        await ch.set_permissions(guild.default_role, overwrite=overwrites)
        await interaction.response.send_message(f"🔒 Channel locked: {ch.mention}")
    except Exception as e:
        log.error(f"Lock error: {e}")
        await interaction.response.send_message("❌ Failed to lock channel.", ephemeral=True)

@bot.listen('on_message')
async def moderation_listener(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    settings = get_guild_settings(message.guild.id)
    if not settings.get("protection_enabled"):
        return
    level, word = check_severity(message.content)
    if level > 0:
        # Delete message
        try:
            await message.delete()
        except:
            pass
        # Log
        log_ch = message.guild.get_channel(settings.get("log_channel_id") or 0) or await ensure_log_channel(message.guild)
        if log_ch:
            embed = discord.Embed(
                title="🚨 Bad Word Detected",
                description=f"User: **{message.author.display_name}**\nLevel: `{level}`\nWord: `{word}`\nChannel: {message.channel.mention}",
                color=discord.Color.red() if level==3 else discord.Color.orange()
            )
            embed.set_footer(text=f"User ID: {message.author.id}")
            await log_ch.send(embed=embed)
        # DM warning for level 3
        if level == 3:
            try:
                await message.author.send("⚠️ Your message contained prohibited language (level 3). Please keep it respectful.")
            except:
                pass

@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    settings = get_guild_settings(guild.id)
    # Roles
    role_id = settings.get("bot_role_id") if member.bot else settings.get("member_role_id")
    role = guild.get_role(role_id) if role_id else None
    if not role:
        # Try find by name
        role = discord.utils.get(guild.roles, name=("Bot" if member.bot else "Member"))
        if not role:
            try:
                role = await guild.create_role(name=("Bot" if member.bot else "Member"))
                # Save back
                if member.bot:
                    set_guild_settings(guild.id, bot_role_id=role.id)
                else:
                    set_guild_settings(guild.id, member_role_id=role.id)
            except:
                pass
    if role:
        try:
            await member.add_roles(role, reason="Auto role assignment")
        except:
            pass
    # Welcome message
    ch = guild.get_channel(settings.get("welcome_channel_id") or 0)
    if ch:
        try:
            await ch.send(f"🎉 Welcome **{member.display_name}** to the server!")
        except:
            pass










# -------------------------------------------------
# 10.  ERROR HANDLING
# -------------------------------------------------
@bot.event
async def on_command_error(ctx, error):
    # Silently log errors without sending messages to chat
    if isinstance(error, commands.CommandNotFound):
        log.debug("Command not found: %s", ctx.message.content)
    elif isinstance(error, commands.MissingRequiredArgument):
        log.debug("Missing required argument for command: %s", ctx.command)
    else:
        log.error("Command error: %s", error)

# -------------------------------------------------
# 11.  RUN BOT
# -------------------------------------------------
if __name__ == "__main__":
    load_dotenv()
    TOKEN = os.getenv("DISCORD_TOKEN")
    
    if not TOKEN:
        log.error("❌ No Discord token found!")
        exit(1)
    
    async def cleanup():
        """Cleanup function to properly close connections"""
        log.info("Cleaning up...")
        for vc in bot.voice_clients:
            try:
                await vc.disconnect(force=True)
            except:
                pass
        await bot.close()
    
    try:
        bot.run(TOKEN, log_handler=None)  # Disable default handler to prevent duplicate logs
    except KeyboardInterrupt:
        log.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        log.error("Failed to start bot: %s", e)
    finally:
        # Run cleanup
        try:
            asyncio.run(cleanup())
        except:
            pass