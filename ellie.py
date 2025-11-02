#!/usr/bin/env python3
"""
Ellie's Frog Jump Game (flexible skins + rules)

Expected folder structure (example):
assets/skins/
  autumn/
    bg.png
    levels.json
    music.mp3             (any audio name containing 'music' also works)
    lily pad.bmp          (or pad.png, platform.png, lilypad.png, etc.)
    frog_bigeye.bmp       (or frog.png, ball.png)
    frog_wave.bmp         (optional life icon)
  spring/
  winter/
  night/

This script is forgiving about filenames:
- background: names containing "bg" or "background"
- pad: names containing "lily"+"pad", "lilypad", "pad", or "platform"
- frog/ball: names containing "frog_bigeye", "frog", "ball", "character", "player"
- life icon (optional): names containing "frog"+"wave", "life", "heart"
- music: any audio file whose name contains "music" or "bgm"

levels.json accepted formats:
- {"levels": [ {...}, {...} ]}  (recommended)
- {"rules":  [ {...}, {...} ]}
- [ {...}, {...} ]

Each rule can use synonyms:
  score|threshold, frogs|num_frogs, speed|speed_range, currents|current,
  wind|wind_gust, pad_scale|pad_size|pad_factor
"""

import pygame, sys, os, json, random, time, math
from typing import List, Dict, Optional

pygame.init()
# Mixer may fail on headless machines; we try once here, and again lazily in apply_music_for_skin.
try:
    pygame.mixer.init()
except Exception:
    pass

SCREEN_W, SCREEN_H = 640, 480
FPS = 60

DATA_DIR = "Data"
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SCORES_FILE   = os.path.join(DATA_DIR, "scores.json")
SKINS_ROOT    = os.path.join("assets", "skins")

os.makedirs(DATA_DIR, exist_ok=True)

GLOBAL_MUSIC_FALLBACK = "music.mp3"
LIFE_FILE  = "life.bmp"

# ------- flexible asset discovery helpers ------- #
AUDIO_EXTS = (".mp3", ".ogg", ".wav", ".flac", ".m4a")
IMAGE_EXTS = (".png", ".bmp", ".jpg", ".jpeg")

def list_files(folder):
    try:
        return [f for f in os.listdir(folder)]
    except Exception:
        return []

def stem_lower(name: str):
    return os.path.splitext(name)[0].lower()

def find_file_by_keywords(folder, keywords, allowed_exts):
    """
    Look in `folder` and return the first file whose stem contains *all* keywords (case-insensitive).
    `keywords` may be a string or list/tuple of strings.
    """
    if isinstance(keywords, str):
        kw = [keywords]
    else:
        kw = list(keywords)
    files = list_files(folder)
    # Sort for deterministic choice
    for fname in sorted(files):
        low = fname.lower()
        if not low.endswith(allowed_exts):
            continue
        stem = stem_lower(fname)
        stem_nospace = stem.replace(" ", "").replace("_", "")
        # match if every keyword appears in either raw stem or nospace version
        if all((k.lower() in stem) or (k.lower().replace(" ", "") in stem_nospace) for k in kw):
            return os.path.join(folder, fname)
    return None

def find_image_any(folder, candidates):
    """Try many candidate keyword combos to locate an image in folder."""
    # candidates is a list of tuples/list (each is one set of required keywords)
    for cand in candidates:
        p = find_file_by_keywords(folder, cand, IMAGE_EXTS)
        if p and os.path.exists(p):
            try:
                img = pygame.image.load(p)
                return img.convert_alpha() if img.get_alpha() else img.convert()
            except Exception:
                pass
    return None

def find_audio_any(folder, candidates):
    for cand in candidates:
        p = find_file_by_keywords(folder, cand, AUDIO_EXTS)
        if p and os.path.exists(p):
            return p
    return None


# -------- utilities -------- #
def safe_load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def draw_text(surface, txt, size, x, y, color=(30,30,30), center=False):
    font = pygame.font.Font(None, size)
    img = font.render(txt, True, color)
    rect = img.get_rect()
    if center:
        rect.center = (x, y)
    else:
        rect.topleft = (x, y)
    surface.blit(img, rect)

def load_any(path_noext: str) -> Optional[pygame.Surface]:
    for ext in (".png",".bmp",".jpg",".jpeg"):
        p = path_noext+ext
        if os.path.exists(p):
            img = pygame.image.load(p)
            return img.convert_alpha() if img.get_alpha() else img.convert()
    return None

def best_score():
    scores = safe_load_json(SCORES_FILE, [])
    return max([r["score"] for r in scores], default=0)

def add_score(name, score):
    scores = safe_load_json(SCORES_FILE, [])
    scores.append({"name": (name or "Anon")[:12], "score": int(score), "ts": int(time.time())})
    scores.sort(key=lambda s: (-s["score"], s["ts"]))
    save_json(SCORES_FILE, scores[:10])
    return scores[:10]

# -------- skins -------- #
class SkinManager:
    """
    Loads skins from assets/skins/<name>/ with:
      - frog.(png|bmp|jpg)
      - pad.(png|bmp|jpg)
      - bg.(png|bmp|jpg)
      - (optional) music.(mp3|ogg|wav)
      - (optional) levels.json  -> per-level rules
    Remembers last chosen skin + auto-cycle setting in Data/settings.json
    """
    def __init__(self, root=SKINS_ROOT, settings_file=SETTINGS_FILE):
        self.root = root
        self.settings_file = settings_file
        self.skins: List[Dict] = []
        self.index = 0
        self.auto_cycle = True
        self.load()

    def load(self):
        settings = safe_load_json(self.settings_file, {})
        self.auto_cycle = settings.get("auto_cycle", True)

        if not os.path.isdir(self.root):
            self.skins = []
            return

        names = sorted([d for d in os.listdir(self.root) if os.path.isdir(os.path.join(self.root, d))])
        for name in names:
            base = os.path.join(self.root, name)
            # Try to discover required art with flexible names:
            # frog image (ball/character)
            frog = find_image_any(base, [
                ("frog_bigeye",),
                ("frog", "bigeye"),
                ("frog",),
                ("ball",),
                ("character",),
                ("player",),
            ])
            # pad image (lily pad / platform)
            pad  = find_image_any(base, [
                ("lily", "pad"),
                ("lilypad",),
                ("pad",),
                ("platform",),
            ])
            # background image
            bg   = find_image_any(base, [
                ("bg",),
                ("background",),
            ])

            # optional per-skin life icon (frog_wave)
            life_icon = find_image_any(base, [
                ("frog", "wave"),
                ("life",),
                ("heart",),
            ])

            # If strict names exist, prefer them
            frog = frog or load_any(os.path.join(base, "frog"))
            pad  = pad  or load_any(os.path.join(base, "pad"))
            bg   = bg   or load_any(os.path.join(base, "bg"))

            if frog and pad and bg:
                bg = pygame.transform.smoothscale(bg, (SCREEN_W, SCREEN_H))

                # Flexible music discovery: handle odd filenames like "music. mp3"
                music = find_audio_any(base, [
                    ("music",),
                    ("bgm",),
                    ("background", "music"),
                ])
                if not music:
                    # Backwards-compat
                    for ext in (".mp3",".ogg",".wav"):
                        candidate = os.path.join(base, "music"+ext)
                        if os.path.exists(candidate):
                            music = candidate
                            break

                # Load levels.json if present
                levels_path = os.path.join(base, "levels.json")
                levels = safe_load_json(levels_path, None) if os.path.exists(levels_path) else None
                self.skins.append({
                    "name": name, "frog": frog, "pad": pad, "bg": bg,
                    "music": music, "levels": levels, "life_icon": life_icon
                })

        chosen = settings.get("skin_name")
        if chosen:
            for i, s in enumerate(self.skins):
                if s["name"] == chosen:
                    self.index = i
                    break

    def current(self):
        return self.skins[self.index] if self.skins else None

    def next(self):
        if not self.skins: return
        self.index = (self.index + 1) % len(self.skins)

    def prev(self):
        if not self.skins: return
        self.index = (self.index - 1) % len(self.skins)

    def save_choice(self):
        s = safe_load_json(self.settings_file, {})
        cur = self.current()
        if cur:
            s["skin_name"] = cur["name"]
        s["auto_cycle"] = self.auto_cycle
        save_json(self.settings_file, s)

# -------- sprites -------- #
class Bat(pygame.sprite.Sprite):
    def __init__(self, image):
        super().__init__()
        self.base_image = image
        self.image = image
        self.rect = self.image.get_rect(midbottom=(SCREEN_W//2, SCREEN_H-40))
        self.speed = 12

    def set_image(self, image):
        self.base_image = image
        self.image = image
        self.rect = self.image.get_rect(midbottom=self.rect.midbottom)

    def set_scale(self, scale: float):
        w,h = self.base_image.get_size()
        new = pygame.transform.smoothscale(self.base_image, (max(20,int(w*scale)), max(8,int(h*scale))))
        self.image = new
        self.rect = self.image.get_rect(midbottom=self.rect.midbottom)

    def update(self, pressed, wind_drift=0.0):
        if pressed[pygame.K_RIGHT] or pressed[pygame.K_d]:
            self.rect.x += self.speed
        if pressed[pygame.K_LEFT] or pressed[pygame.K_a]:
            self.rect.x -= self.speed
        # wind softly pushes the pad (simulate gusts)
        self.rect.x += wind_drift
        self.rect.x = max(0, min(self.rect.x, SCREEN_W - self.rect.width))

class Ball(pygame.sprite.Sprite):
    def __init__(self, image, speed_range):
        super().__init__()
        self.image = image
        self.rect = self.image.get_rect()
        self.speed_range = speed_range
        self.vx = 0
        self.vy = 0
        self.reset()

    def set_image(self, image):
        self.image = image
        self.rect = self.image.get_rect(center=self.rect.center)

    def reset(self):
        self.rect.centerx = random.randint(20, SCREEN_W - 20)
        self.rect.y = 10
        lo, hi = self.speed_range
        self.vx = random.choice([-1,1]) * random.randint(lo, hi)
        self.vy = random.randint(lo, hi)

    def update(self, bat_rect, current_force_x=0.0):
        # apply current (horizontal acceleration)
        self.vx += current_force_x
        # clamp VX slightly to avoid runaway
        self.vx = max(-12, min(12, self.vx))

        self.rect.x += self.vx
        self.rect.y += self.vy

        # walls
        if self.rect.left <= 0 or self.rect.right >= SCREEN_W:
            self.vx *= -1
        if self.rect.top <= 0:
            self.vy = abs(self.vy)

        # bat collision (AABB + downward check)
        if self.rect.colliderect(bat_rect) and self.vy > 0:
            lo, hi = self.speed_range
            self.vy = -random.randint(max(lo,3), hi+1)

    def fell_in_water(self):
        return self.rect.bottom > SCREEN_H - 10

# -------- game -------- #
class Game:
    def __init__(self):
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Ellie's Game — Skins + Rules")

        self.clock = pygame.time.Clock()
        self.skinman = SkinManager()
        self.ensure_at_least_one_skin()

        self.balls = pygame.sprite.Group()
        self.lives = 5
        self.score = 0
        self.state = "TITLE"  # TITLE, PLAYING, PAUSED, NAME, LEADER, SKINS
        self.name_input = ""
        self.muted = False

        # world forces / visuals from rules
        self.current_force_x = 0.0   # "currents" pushing frogs
        self.wind_base = 0.0         # constant wind on pad
        self.wind_amp  = 0.0         # amplitude for gusty sin modulation
        self.pad_scale = 1.0

        self.level_idx = 0
        self.last_frame = None
        self.current_music_path = None

        # skin-dependent art
        cur = self.skinman.current()
        self.background = cur["bg"]
        self.bat = Bat(cur["pad"])
        self.frog_img = cur["frog"]
        # life icon: prefer per-skin, else LIFE_FILE, else generate
        self.life_img = cur.get("life_icon")
        if self.life_img is None:
            try:
                # prefer a global frog_wave.bmp if present
                if os.path.exists("frog_wave.bmp"):
                    self.life_img = pygame.image.load("frog_wave.bmp").convert_alpha()
                elif os.path.exists(LIFE_FILE):
                    self.life_img = pygame.image.load(LIFE_FILE).convert_alpha()
                else:
                    raise FileNotFoundError
            except Exception:
                self.life_img = pygame.Surface((24,24), pygame.SRCALPHA)
                pygame.draw.circle(self.life_img, (0,180,0), (12,12), 10)

        self.apply_music_for_skin(cur)

    def ensure_at_least_one_skin(self):
        if not self.skinman.skins:
            # Fallback visuals if assets missing
            fb_bg = pygame.Surface((SCREEN_W, SCREEN_H)); fb_bg.fill((140,180,220))
            fb_frog = pygame.Surface((40,40), pygame.SRCALPHA); pygame.draw.circle(fb_frog, (0,200,0), (20,20), 18)
            fb_pad  = pygame.Surface((120,24), pygame.SRCALPHA); pygame.draw.ellipse(fb_pad, (40,140,60), fb_pad.get_rect())
            self.skinman.skins = [{"name":"fallback","frog":fb_frog,"pad":fb_pad,"bg":fb_bg,"music":None,"levels":None, "life_icon":None}]
            self.skinman.index = 0

    # ----- rules / levels ----- #
    def rules_from_skin(self, skin) -> List[Dict]:
        """
        Returns a list of level-rule dicts. Accepts several formats, e.g.:
        - {"levels":[ {...}, {...} ]}
        - {"rules":[ {...}, {...} ]}
        - [ {...}, {...} ]
        Where each level dict may use synonyms:
          score|threshold, frogs|num_frogs, speed|speed_range, currents|current,
          wind|wind_gust, pad_scale|pad_size|pad_factor
        """
        default = [
            {"score":0,    "frogs":1, "speed":[3,6],  "currents":0.0,  "wind":0.0,  "pad_scale":1.00},
            {"score":1500, "frogs":2, "speed":[3,7],  "currents":0.05, "wind":0.00, "pad_scale":0.95},
            {"score":3000, "frogs":3, "speed":[4,8],  "currents":0.08, "wind":0.03, "pad_scale":0.92},
            {"score":5000, "frogs":4, "speed":[5,9],  "currents":0.12, "wind":0.04, "pad_scale":0.88},
            {"score":7500, "frogs":5, "speed":[6,10], "currents":0.15, "wind":0.05, "pad_scale":0.84},
        ]

        raw = skin.get("levels")

        # Allow list directly
        if isinstance(raw, list) and raw:
            levels_raw = raw
        elif isinstance(raw, dict):
            # Try common keys
            for key in ("levels", "rules", "stages"):
                if isinstance(raw.get(key), list) and raw.get(key):
                    levels_raw = raw.get(key)
                    break
            else:
                levels_raw = []
        else:
            levels_raw = []

        if not levels_raw:
            return default

        def norm_level(d):
            # Normalize synonyms
            score = d.get("score", d.get("threshold", 0))
            frogs = d.get("frogs", d.get("num_frogs", 1))
            speed = d.get("speed", d.get("speed_range", [3,6]))
            currents = d.get("currents", d.get("current", 0.0))
            wind = d.get("wind", d.get("wind_gust", 0.0))
            pad_scale = d.get("pad_scale", d.get("pad_size", d.get("pad_factor", 1.0)))

            # Clamp/cast types
            try:
                frogs = int(frogs)
            except Exception:
                frogs = 1

            # speed can be [lo,hi] or a single number
            if isinstance(speed, (list, tuple)) and len(speed) >= 2:
                lo, hi = speed[0], speed[1]
            else:
                try:
                    lo = int(speed)
                except Exception:
                    lo = 3
                hi = max(lo+2, lo+3)
            lo = max(1, int(lo)); hi = max(lo+1, int(hi))

            try: currents = float(currents)
            except Exception: currents = 0.0
            try: wind = float(wind)
            except Exception: wind = 0.0
            try: pad_scale = float(pad_scale)
            except Exception: pad_scale = 1.0

            # score to int, tolerant of strings
            try:
                score_i = int(float(score))
            except Exception:
                score_i = 0

            return {
                "score": score_i,
                "frogs": frogs,
                "speed": [lo, hi],
                "currents": currents,
                "wind": wind,
                "pad_scale": pad_scale
            }

        levels = [norm_level(d) for d in levels_raw if isinstance(d, dict)]
        if not levels:
            return default

        # sort by score ascending to be safe
        levels.sort(key=lambda x: x.get("score", 0))
        return levels

    def level_for_score(self, rules: List[Dict], score: int):
        """
        Given a list of rules sorted by score threshold, return:
        (level_index, frogs, speed_range, currents, wind, pad_scale)
        """
        if not rules:
            return 0, 1, (3,6), 0.0, 0.0, 1.0
        idx, cfg = 0, rules[0]
        for i, r in enumerate(rules):
            if score >= int(r.get("score", 0)):
                idx, cfg = i, r
            else:
                break
        frogs     = int(cfg.get("frogs", 1))
        speed     = tuple(cfg.get("speed", [3,6]))
        currents  = float(cfg.get("currents", 0.0))
        wind      = float(cfg.get("wind", 0.0))
        pad_scale = float(cfg.get("pad_scale", 1.0))
        return idx, frogs, speed, currents, wind, pad_scale

    def apply_rules(self, speed_range, currents, wind, pad_scale):
        # store world forces
        self.current_force_x = currents
        # make wind a smooth gust: base + small sinusoidal wobble
        self.wind_base = wind
        self.wind_amp = wind * 0.5
        # apply pad scaling
        self.pad_scale = pad_scale
        self.bat.set_scale(self.pad_scale)
        # propagate new speed range to balls
        for b in self.balls:
            b.speed_range = speed_range

    def apply_music_for_skin(self, skin):
        """Start/loop the skin's background music (if present)."""
        # Ensure mixer is ready
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
                pygame.mixer.init()
        except Exception:
            return

        # Choose target track: skin music or global fallback
        target = skin.get("music") if skin.get("music") else (
            GLOBAL_MUSIC_FALLBACK if os.path.exists(GLOBAL_MUSIC_FALLBACK) else None
        )

        if not target:
            # No music available -> stop anything that might be playing
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.current_music_path = None
            return

        try:
            # Only reload if we're switching tracks
            if target != self.current_music_path:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                pygame.mixer.music.load(target)
                self.current_music_path = target

            # Ensure it's playing (e.g., after a previous stop)
            if not pygame.mixer.music.get_busy():
                pygame.mixer.music.play(-1)

            # Respect mute state
            pygame.mixer.music.set_volume(0.0 if getattr(self, "muted", False) else 0.5)

        except Exception as e:
            print("Music load issue:", e)

    def start_game(self):
        self.score = 0
        self.lives = 5
        self.balls.empty()
        cur = self.skinman.current()
        self.apply_music_for_skin(cur)
        self.background = cur["bg"]
        self.bat.set_image(cur["pad"])
        self.frog_img = cur["frog"]
        # refresh life icon from skin (if available)
        self.life_img = cur.get("life_icon", self.life_img)
        rules = self.rules_from_skin(cur)
        self.level_idx, frogs, spd, currents, wind, pad_scale = self.level_for_score(rules, self.score)
        self.apply_rules(spd, currents, wind, pad_scale)
        while len(self.balls) < frogs:
            self.balls.add(Ball(self.frog_img, spd))
        self.state = "PLAYING"

    # ----- state loop ----- #
    def run(self):
        while True:
            if self.state == "TITLE": self.handle_title()
            elif self.state == "PLAYING": self.handle_play()
            elif self.state == "PAUSED": self.handle_pause()
            elif self.state == "NAME": self.handle_name()
            elif self.state == "LEADER": self.handle_leader()
            elif self.state == "SKINS": self.handle_skins()
            else: break
        pygame.quit(); sys.exit()

    def handle_title(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT: return self.quit()
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_SPACE: self.start_game()
                if e.key == pygame.K_s: self.state = "SKINS"
                if e.key == pygame.K_m: self.toggle_mute()
        self.draw_title()
        pygame.display.flip()
        self.clock.tick(FPS)

    def draw_title(self):
        self.screen.blit(self.background, (0,0))
        draw_text(self.screen, "Ellie's Game", 74, SCREEN_W//2, 120, center=True)
        draw_text(self.screen, "SPACE: Start   S: Skins   P: Pause   M: Mute", 28, SCREEN_W//2, 200, center=True)
        draw_text(self.screen, f"Best: {best_score()}", 30, SCREEN_W//2, 240, center=True)
        ac = "ON" if self.skinman.auto_cycle else "OFF"
        draw_text(self.screen, f"Auto-cycle skin on level-up: {ac}", 26, SCREEN_W//2, 275, center=True)
        preview = pygame.transform.smoothscale(self.skinman.current()["frog"], (64,64))
        self.screen.blit(preview, (SCREEN_W//2-32, 310))
        draw_text(self.screen, f"Skin: {self.skinman.current()['name']}", 26, SCREEN_W//2, 390, center=True)

    def handle_play(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT: return self.quit()
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_p:
                    self.last_frame = self.screen.copy()   # freeze frame
                    self.state = "PAUSED"
                if e.key == pygame.K_m: self.toggle_mute()

        pressed = pygame.key.get_pressed()
        # wind drift is base + a soft sinusoidal gust
        t = pygame.time.get_ticks() / 1000.0
        wind_now = self.wind_base + self.wind_amp * math.sin(t * 1.2)
        self.bat.update(pressed, wind_drift=wind_now)

        # level check based on current skin rules
        cur_skin = self.skinman.current()
        rules = self.rules_from_skin(cur_skin)
        new_level_idx, frogs, spd, currents, wind, pad_scale = self.level_for_score(rules, self.score)
        if new_level_idx != self.level_idx:
            self.level_idx = new_level_idx
            # optional: auto-cycle skin on level-up
            if self.skinman.auto_cycle:
                self.skinman.next()
                self.skinman.save_choice()
                cur_skin = self.skinman.current()
                self.apply_music_for_skin(cur_skin)
                self.background = cur_skin["bg"]
                self.bat.set_image(cur_skin["pad"])
                self.frog_img = cur_skin["frog"]
            self.apply_rules(spd, currents, wind, pad_scale)
        # ensure balls count & sprites use current frog image
        while len(self.balls) < frogs:
            self.balls.add(Ball(self.frog_img, spd))
        for b in self.balls:
            b.set_image(self.frog_img)

        # update balls & check
        for b in self.balls:
            b.update(self.bat.rect, current_force_x=self.current_force_x)
        if any(b.fell_in_water() for b in self.balls):
            self.lives -= 1
            for b in self.balls: b.reset()
            if self.lives <= 0:
                self.state = "NAME"
        else:
            self.score += 1

        # draw
        self.screen.blit(self.background, (0,0))
        self.balls.draw(self.screen)
        self.screen.blit(self.bat.image, self.bat.rect)
        self.draw_hud()
        pygame.display.flip()
        self.clock.tick(FPS)

    def handle_pause(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT: return self.quit()
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_p: self.state = "PLAYING"
                if e.key == pygame.K_m: self.toggle_mute()
        # frozen frame + translucent overlay
        if self.last_frame: self.screen.blit(self.last_frame, (0,0))
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0,0,0,120))
        self.screen.blit(overlay, (0,0))
        draw_text(self.screen, "Paused", 64, SCREEN_W//2, SCREEN_H//2 - 20, (240,240,240), center=True)
        draw_text(self.screen, "Press P to resume", 28, SCREEN_W//2, SCREEN_H//2 + 30, (230,230,230), center=True)
        pygame.display.flip()
        self.clock.tick(30)

    def handle_name(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT: return self.quit()
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_RETURN:
                    add_score(self.name_input, self.score)
                    self.name_input = ""
                    self.state = "LEADER"
                elif e.key == pygame.K_BACKSPACE:
                    self.name_input = self.name_input[:-1]
                elif e.key == pygame.K_ESCAPE:
                    self.state = "LEADER"
                else:
                    if len(self.name_input) < 12 and e.unicode.isprintable():
                        self.name_input += e.unicode
        self.screen.blit(self.background, (0,0))
        draw_text(self.screen, "Game Over!", 64, SCREEN_W//2, 120, center=True)
        draw_text(self.screen, f"Score: {self.score}", 36, SCREEN_W//2, 180, center=True)
        pygame.draw.rect(self.screen, (30,30,30), pygame.Rect(140, 280, 360, 40), 2)
        draw_text(self.screen, self.name_input or "_", 32, 150, 287)
        pygame.display.flip()
        self.clock.tick(30)

    def handle_leader(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT: return self.quit()
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_SPACE: self.start_game()
                if e.key == pygame.K_ESCAPE: return self.quit()
                if e.key == pygame.K_s: self.state = "SKINS"
                if e.key == pygame.K_m: self.toggle_mute()

        self.screen.blit(self.background, (0,0))
        draw_text(self.screen, "Top Scores", 56, SCREEN_W//2, 90, center=True)
        rows = safe_load_json(SCORES_FILE, [])
        y = 150
        for i, row in enumerate(rows[:10], start=1):
            draw_text(self.screen, f"{i:>2}. {row['name']:<12}  {row['score']}", 30, SCREEN_W//2, y, center=True)
            y += 34
        draw_text(self.screen, "SPACE: Play again  S: Skins  Esc: Quit", 24, SCREEN_W//2, SCREEN_H-60, center=True)
        pygame.display.flip()
        self.clock.tick(30)

    def handle_skins(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT: return self.quit()
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_LEFT, pygame.K_a): self.skinman.prev()
                if e.key in (pygame.K_RIGHT, pygame.K_d): self.skinman.next()
                if e.key == pygame.K_RETURN:
                    self.skinman.save_choice()
                    cur = self.skinman.current()
                    self.background = cur["bg"]
                    self.bat.set_image(cur["pad"])
                    self.frog_img = cur["frog"]
                    self.life_img = cur.get("life_icon", self.life_img)
                    self.apply_music_for_skin(cur)
                if e.key == pygame.K_c:
                    self.skinman.auto_cycle = not self.skinman.auto_cycle
                    self.skinman.save_choice()
                if e.key == pygame.K_ESCAPE:
                    self.state = "TITLE"

        cur = self.skinman.current()
        self.screen.blit(cur["bg"], (0,0))
        draw_text(self.screen, "Skin Selector", 58, SCREEN_W//2, 90, center=True)
        draw_text(self.screen, f"Skin: {cur['name']}", 34, SCREEN_W//2, 150, center=True)
        frog = pygame.transform.smoothscale(cur["frog"], (90,90))
        pad  = pygame.transform.smoothscale(cur["pad"], (200,40))
        self.screen.blit(frog, (SCREEN_W//2-45, 190))
        self.screen.blit(pad,  (SCREEN_W//2-100, 290))
        music_label = "has music" if cur.get("music") else "uses global music"
        draw_text(self.screen, f"←/→ browse, Enter select, C toggle auto-cycle ({'ON' if self.skinman.auto_cycle else 'OFF'})", 22, SCREEN_W//2, 360, center=True)
        draw_text(self.screen, f"Music: {music_label}", 22, SCREEN_W//2, 388, center=True)
        draw_text(self.screen, "Esc to return", 22, SCREEN_W//2, 414, center=True)
        pygame.display.flip()
        self.clock.tick(30)

    def draw_hud(self):
        draw_text(self.screen, f"Score: {self.score}", 28, 10, 10)
        draw_text(self.screen, f"Best:  {best_score()}", 28, SCREEN_W-180, 10)
        for i in range(self.lives):
            x = 180 + i * (self.life_img.get_width() + 8)
            self.screen.blit(self.life_img, (x, 6))

    def toggle_mute(self):
        self.muted = not self.muted
        try:
            pygame.mixer.music.set_volume(0.0 if self.muted else 0.5)
        except Exception:
            pass

    def quit(self):
        pygame.quit(); sys.exit()

if __name__ == "__main__":
    Game().run()
