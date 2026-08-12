import os
import sys
import math
import time
import random
import threading
import pygame

# --- Bangladesh Color Palette ---
BD_GREEN       = (0,   106, 78)
BD_GREEN_LIGHT = (0,   180, 120)
BD_GREEN_DIM   = (0,    55, 35)
BD_RED         = (212,  43, 58)
BD_RED_LIGHT   = (255,  85, 85)
BD_RED_DIM     = (110,  18, 28)
BD_GOLD        = (255, 200, 50)
BD_WHITE       = (245, 252, 248)
BD_BG          = (4,   16, 10)
BD_CARD        = (7,   26, 16)

# --- States ---
STATE_IDLE      = "IDLE"
STATE_LISTENING = "LISTENING"
STATE_THINKING  = "THINKING"
STATE_SPEAKING  = "SPEAKING"

# ─── Particle ──────────────────────────────────────────────────────────────────
class Particle:
    def __init__(self, sw, sh):
        self.sw = sw
        self.sh = sh
        self.reset(random.uniform(0, sw), random.uniform(0, sh))

    def reset(self, x=None, y=None):
        self.x     = x if x is not None else random.uniform(0, self.sw)
        self.y     = y if y is not None else self.sh + 5
        self.vx    = random.uniform(-0.25, 0.25)
        self.vy    = random.uniform(-0.55, -0.12)
        self.size  = random.uniform(1.2, 2.8)
        self.life  = random.uniform(0.4, 1.0)
        self.max_life = self.life
        self.color = random.choice([BD_GREEN_LIGHT, BD_RED_LIGHT, BD_GOLD, BD_WHITE])

    def update(self):
        self.x    += self.vx
        self.y    += self.vy
        self.life -= 0.0035
        if self.life <= 0 or self.y < -10:
            self.reset()

    def draw(self, surf):
        alpha = max(0.0, self.life / self.max_life)
        if alpha < 0.05:
            return
        r, g, b = self.color
        color = (int(r * alpha), int(g * alpha), int(b * alpha))
        pygame.draw.circle(surf, color, (int(self.x), int(self.y)), max(1, int(self.size * alpha)))

# ─── WaveBar ───────────────────────────────────────────────────────────────────
class WaveBar:
    def __init__(self, x, base_y, index):
        self.x      = x
        self.base_y = base_y
        self.index  = index
        self.phase  = random.uniform(0, math.pi * 2)
        self.speed  = random.uniform(3.0, 6.5)

    def height(self, t, state):
        if state == STATE_SPEAKING:
            return abs(math.sin(t * self.speed + self.phase)) * 52 + 6
        elif state == STATE_LISTENING:
            return abs(math.sin(t * self.speed * 0.45 + self.phase)) * 18 + 4
        elif state == STATE_THINKING:
            return abs(math.sin(t * 1.8 + self.phase * 0.4)) * 10 + 3
        else:
            return abs(math.sin(t * 0.4 + self.phase)) * 4 + 2

# ─── Main GUI ──────────────────────────────────────────────────────────────────
class DeskBuddyGUI:
    def __init__(self, fullscreen=True):
        pygame.init()
        pygame.font.init()

        self.fullscreen = fullscreen
        info = pygame.display.Info()
        self.sw = info.current_w if info.current_w > 0 else 1024
        self.sh = info.current_h if info.current_h > 0 else 600

        flags = (pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.HWSURFACE
                 if self.fullscreen else pygame.RESIZABLE)
        try:
            self.screen = pygame.display.set_mode((self.sw, self.sh), flags)
        except Exception:
            self.fullscreen = False
            self.sw, self.sh = 1024, 600
            self.screen = pygame.display.set_mode((self.sw, self.sh), pygame.RESIZABLE)

        pygame.display.set_caption("ShongiBot — Bangladesh Culture Assistant")
        self.clock = pygame.time.Clock()

        self.font_xl    = pygame.font.SysFont("Arial", max(20, int(self.sh * 0.044)), bold=True)
        self.font_lg    = pygame.font.SysFont("Arial", max(16, int(self.sh * 0.034)), bold=True)
        self.font_md    = pygame.font.SysFont("Arial", max(13, int(self.sh * 0.027)))
        self.font_sm    = pygame.font.SysFont("Arial", max(11, int(self.sh * 0.022)))
        self.font_badge = pygame.font.SysFont("Arial", max(12, int(self.sh * 0.025)), bold=True)

        self.state      = STATE_IDLE
        self.user_text  = ""
        self.robot_text = ""
        self.running    = True

        self.t             = 0.0
        self.orbit_angle   = 0.0
        self.speak_phase   = 0.0
        self.flag_pulse    = 0.0
        self.blink_timer   = time.time() + random.uniform(2, 5)
        self.is_blinking   = False
        self.blink_prog    = 0.0
        self.gaze_x        = 0.0
        self.gaze_y        = 0.0
        self.tgt_gaze_x    = 0.0
        self.tgt_gaze_y    = 0.0
        self.next_gaze_t   = time.time()
        self.sonar_rings   = []
        self.last_sonar    = 0.0
        self.orbit_trail   = []

        self.particles = [Particle(self.sw, self.sh) for _ in range(65)]

        BAR_COUNT   = 26
        bar_total_w = int(self.sw * 0.48)
        bar_gap     = bar_total_w // BAR_COUNT
        bar_start_x = (self.sw - bar_total_w) // 2
        wave_base_y = int(self.sh * 0.76)
        self.wave_bars = [WaveBar(bar_start_x + i * bar_gap, wave_base_y, i) for i in range(BAR_COUNT)]

    def set_state(self, state, user_text="", robot_text=""):
        self.state = state
        if user_text:
            self.user_text  = user_text
        if robot_text:
            self.robot_text = robot_text

    def _update(self, dt):
        self.t           += dt
        self.orbit_angle  = (self.orbit_angle + dt * 1.9) % (math.pi * 2)
        self.speak_phase  += dt * 5.0
        self.flag_pulse   += dt * 1.7

        if not self.is_blinking and time.time() > self.blink_timer:
            self.is_blinking = True
            self.blink_prog  = 0.0
            self.blink_timer = time.time() + random.uniform(3.0, 7.0)
        if self.is_blinking:
            self.blink_prog += dt * 8.0
            if self.blink_prog >= 1.0:
                self.is_blinking = False
                self.blink_prog  = 0.0

        if time.time() > self.next_gaze_t:
            self.tgt_gaze_x = random.uniform(-11, 11)
            self.tgt_gaze_y = random.uniform(-5, 5)
            self.next_gaze_t = time.time() + random.uniform(1.2, 3.5)
        self.gaze_x += (self.tgt_gaze_x - self.gaze_x) * 0.07
        self.gaze_y += (self.tgt_gaze_y - self.gaze_y) * 0.07

        for p in self.particles:
            p.update()

        if self.state == STATE_LISTENING:
            if self.t - self.last_sonar > 0.52:
                self.sonar_rings.append([0, 240])
                self.last_sonar = self.t
        self.sonar_rings = [[r + dt * 75, max(0, a - dt * 170)]
                            for r, a in self.sonar_rings if a > 0]

        self.orbit_trail.append((self.orbit_angle, 255))
        self.orbit_trail = [(a, max(0, al - 16)) for a, al in self.orbit_trail if al > 0][-28:]

    def _draw_bg(self):
        self.screen.fill(BD_BG)
        cx, cy = self.sw // 2, self.sh // 2
        for r in range(200, 0, -35):
            alpha = max(0, int(16 - r * 0.07))
            if alpha > 0:
                s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                pygame.draw.circle(s, (*BD_GREEN_DIM, alpha), (r, r), r)
                self.screen.blit(s, (cx - r, cy - r))
        for p in self.particles:
            p.draw(self.screen)

    def _draw_header(self):
        bar_h = int(self.sh * 0.072)
        pygame.draw.rect(self.screen, BD_GREEN, (0, 0, self.sw, bar_h))
        stripe = int(bar_h * 0.20)
        pygame.draw.rect(self.screen, BD_RED, (0, bar_h - stripe, self.sw, stripe))
        title = self.font_xl.render("ShongiBot  |  Bangladesh Culture Guide", True, BD_WHITE)
        self.screen.blit(title, (self.sw // 2 - title.get_width() // 2,
                                  bar_h // 2 - title.get_height() // 2))
        disc_r = int(bar_h * 0.36)
        pulse  = int(math.sin(self.flag_pulse) * 2)
        pygame.draw.circle(self.screen, BD_RED, (int(self.sw * 0.05), bar_h // 2), disc_r + pulse)
        pygame.draw.circle(self.screen, BD_RED, (int(self.sw * 0.95), bar_h // 2), disc_r + pulse)

        # Draw a clear red Exit [X] button on the top-right for touchscreen/mouse close
        self.exit_btn_rect = pygame.Rect(self.sw - int(self.sw * 0.08) - 10, int(bar_h * 0.15), int(self.sw * 0.08), int(bar_h * 0.7))
        pygame.draw.rect(self.screen, BD_RED_DIM, self.exit_btn_rect, border_radius=6)
        pygame.draw.rect(self.screen, BD_WHITE, self.exit_btn_rect, width=1, border_radius=6)
        exit_lbl = self.font_badge.render("EXIT [X]", True, BD_WHITE)
        self.screen.blit(exit_lbl, (self.exit_btn_rect.centerx - exit_lbl.get_width() // 2,
                                     self.exit_btn_rect.centery - exit_lbl.get_height() // 2))


    def _draw_badge(self):
        labels = {
            STATE_IDLE:      ("● IDLE",      BD_GREEN_LIGHT),
            STATE_LISTENING: ("◉ LISTENING", BD_GOLD),
            STATE_THINKING:  ("◎ THINKING",  BD_RED_LIGHT),
            STATE_SPEAKING:  ("◈ SPEAKING",  (100, 220, 255)),
        }
        label, color = labels.get(self.state, ("● IDLE", BD_GREEN_LIGHT))
        pulse = (math.sin(self.t * 4) + 1) * 0.5
        ac = tuple(min(255, int(c * (0.65 + 0.35 * pulse))) for c in color)
        surf = self.font_badge.render(label, True, ac)
        bx = self.sw - surf.get_width() - 24
        by = int(self.sh * 0.10)
        pw, ph = surf.get_width() + 22, surf.get_height() + 10
        pill = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(pill, (*BD_CARD, 200), (0, 0, pw, ph), border_radius=10)
        pygame.draw.rect(pill, (*color, 100), (0, 0, pw, ph), width=2, border_radius=10)
        self.screen.blit(pill, (bx - 10, by - 5))
        self.screen.blit(surf, (bx, by))

    def _draw_eye(self, cx, cy, ew, eh, color, glow_col):
        if self.is_blinking:
            scale = max(0.04, 1.0 - math.sin(self.blink_prog * math.pi))
            eh = max(2, int(eh * scale))
        if self.state == STATE_SPEAKING:
            squish = math.sin(self.speak_phase) * 0.20
            eh = max(6, int(eh * (1.0 + squish)))

        for gr in [24, 15, 7]:
            gw, gh = ew + gr * 2, max(4, eh + gr * 2)
            gs = pygame.Surface((gw, gh), pygame.SRCALPHA)
            alpha = max(0, 32 - gr * 1.1)
            pygame.draw.ellipse(gs, (*glow_col, int(alpha)), (0, 0, gw, gh))
            self.screen.blit(gs, (cx - ew // 2 - gr, cy - eh // 2 - gr))

        pygame.draw.ellipse(self.screen, color, (cx - ew // 2, cy - eh // 2, ew, max(2, eh)))

        pw = max(4, int(ew * 0.27))
        ph = max(3, int(eh * 0.27))
        pgx = int(cx + self.gaze_x * 0.38)
        pgy = int(cy + self.gaze_y * 0.38)
        if ph > 2:
            pygame.draw.ellipse(self.screen, BD_BG, (pgx - pw // 2, pgy - ph // 2, pw, ph))

        hx = int(cx - ew * 0.17 + self.gaze_x * 0.14)
        hy = int(cy - eh * 0.22 + self.gaze_y * 0.14)
        hw = max(3, int(ew * 0.13))
        hh = max(2, int(eh * 0.13))
        if hh > 1:
            pygame.draw.ellipse(self.screen, BD_WHITE, (hx, hy, hw, hh))

    def _draw_sonar(self, cx, cy):
        for ring_r, ring_a in self.sonar_rings:
            if ring_a > 5:
                ir = max(2, int(ring_r))
                s = pygame.Surface((ir * 2 + 4, ir * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(s, (*BD_GOLD, int(ring_a)), (ir + 2, ir + 2), ir, 2)
                self.screen.blit(s, (cx - ir - 2, cy - ir - 2))

    def _draw_orbit(self, cx, cy, radius):
        pygame.draw.circle(self.screen, BD_GREEN_DIM, (cx, cy), int(radius), 1)
        for angle, alpha in self.orbit_trail:
            if alpha > 8:
                ox = cx + math.cos(angle) * radius
                oy = cy + math.sin(angle) * radius
                frac = alpha / 255
                c = (int(BD_RED[0] * frac + BD_GOLD[0] * (1 - frac)),
                     int(BD_RED[1] * frac + BD_GOLD[1] * (1 - frac)),
                     int(BD_RED[2] * frac + BD_GOLD[2] * (1 - frac)))
                pygame.draw.circle(self.screen, c, (int(ox), int(oy)), max(2, int(4 * frac)))

        lx = int(cx + math.cos(self.orbit_angle) * radius)
        ly = int(cy + math.sin(self.orbit_angle) * radius)
        pygame.draw.circle(self.screen, BD_RED,  (lx, ly), 7)
        pygame.draw.circle(self.screen, BD_WHITE, (lx, ly), 3)

        a2 = (-self.orbit_angle * 1.6) % (math.pi * 2)
        ox2 = int(cx + math.cos(a2) * radius * 0.58)
        oy2 = int(cy + math.sin(a2) * radius * 0.58)
        pygame.draw.circle(self.screen, BD_GOLD,  (ox2, oy2), 5)
        pygame.draw.circle(self.screen, BD_WHITE, (ox2, oy2), 2)

    def _draw_waveform(self):
        bar_w = max(4, int(self.sw * 0.011))
        for bar in self.wave_bars:
            h  = bar.height(self.t, self.state)
            frac = abs(math.sin(self.t * 1.4 + bar.index * 0.28))
            r = int(BD_GREEN_LIGHT[0] + (BD_RED[0] - BD_GREEN_LIGHT[0]) * frac)
            g = int(BD_GREEN_LIGHT[1] + (BD_RED[1] - BD_GREEN_LIGHT[1]) * frac)
            b = int(BD_GREEN_LIGHT[2] + (BD_RED[2] - BD_GREEN_LIGHT[2]) * frac)
            color = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
            rect  = pygame.Rect(bar.x - bar_w // 2, int(bar.base_y - h), bar_w, max(2, int(h * 2)))
            pygame.draw.rect(self.screen, color, rect, border_radius=bar_w // 2)
            tip = pygame.Surface((bar_w + 4, 6), pygame.SRCALPHA)
            pygame.draw.rect(tip, (*color, 75), (0, 0, bar_w + 4, 6), border_radius=3)
            self.screen.blit(tip, (bar.x - bar_w // 2 - 2, int(bar.base_y - h) - 3))

    def _draw_face(self):
        cx = self.sw // 2
        cy = int(self.sh * 0.44)
        ew  = int(self.sw * 0.12)
        eh  = int(self.sh * 0.21)
        esp = int(self.sw * 0.20)

        state_glow = {
            STATE_IDLE:      BD_GREEN_DIM,
            STATE_LISTENING: (75, 65, 0),
            STATE_THINKING:  (75, 10, 14),
            STATE_SPEAKING:  (0,  45, 75),
        }
        gc = state_glow.get(self.state, BD_GREEN_DIM)
        for gr in [88, 58, 32]:
            gs = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
            alpha = max(0, 38 - gr * 0.3)
            pygame.draw.circle(gs, (*gc, int(alpha)), (gr, gr), gr)
            self.screen.blit(gs, (cx - gr, cy - gr))

        eye_col = {
            STATE_IDLE:      BD_GREEN_LIGHT,
            STATE_LISTENING: BD_GOLD,
            STATE_THINKING:  BD_RED_LIGHT,
            STATE_SPEAKING:  (75, 210, 255),
        }.get(self.state, BD_GREEN_LIGHT)

        glow_col = {
            STATE_IDLE:      BD_GREEN,
            STATE_LISTENING: (160, 130, 0),
            STATE_THINKING:  BD_RED_DIM,
            STATE_SPEAKING:  (0,   90, 160),
        }.get(self.state, BD_GREEN)

        if self.state == STATE_LISTENING:
            self._draw_sonar(cx - esp, cy)
            self._draw_sonar(cx + esp, cy)

        if self.state == STATE_THINKING:
            orbit_r = int(min(esp + ew // 2 + 28, self.sw * 0.27))
            self._draw_orbit(cx, cy, orbit_r)

        self._draw_eye(cx - esp, cy, ew, eh, eye_col, glow_col)
        self._draw_eye(cx + esp, cy, ew, eh, eye_col, glow_col)

        # Central red disc — Bangladesh flag motif
        third_cy = cy - int(self.sh * 0.19)
        disc_r   = int(self.sh * 0.052)
        pulse_r  = int(math.sin(self.t * 2.8) * 4) if self.state != STATE_IDLE else 0

        for gr in [20, 12, 5]:
            r_tot = disc_r + gr + pulse_r
            gs = pygame.Surface((r_tot * 2, r_tot * 2), pygame.SRCALPHA)
            alpha = max(0, 38 - gr * 1.6)
            pygame.draw.circle(gs, (*BD_RED, int(alpha)), (r_tot, r_tot), r_tot)
            self.screen.blit(gs, (cx - r_tot, third_cy - r_tot))

        pygame.draw.circle(self.screen, BD_RED_DIM, (cx, third_cy), disc_r + pulse_r + 4)
        pygame.draw.circle(self.screen, BD_RED,     (cx, third_cy), disc_r + pulse_r)
        pygame.draw.circle(self.screen, BD_RED_LIGHT, (cx - disc_r // 5, third_cy - disc_r // 5), disc_r // 4)

        self._draw_waveform()

    def _draw_card(self):
        cw = int(self.sw * 0.92)
        ch = int(self.sh * 0.19)
        cx = (self.sw - cw) // 2
        cy = self.sh - ch - int(self.sh * 0.025)

        card_surf = pygame.Surface((cw, ch), pygame.SRCALPHA)
        pygame.draw.rect(card_surf, (*BD_CARD, 215), (0, 0, cw, ch), border_radius=18)
        self.screen.blit(card_surf, (cx, cy))

        t_frac = (math.sin(self.t * 1.1) + 1) * 0.5
        bc = tuple(int(BD_GREEN[i] + (BD_RED[i] - BD_GREEN[i]) * t_frac) for i in range(3))
        pygame.draw.rect(self.screen, bc, pygame.Rect(cx, cy, cw, ch), width=2, border_radius=18)

        pad   = 18
        lh    = int(self.sh * 0.044)
        line1 = cy + 12
        line2 = cy + 12 + lh
        line3 = cy + 12 + lh * 2

        if self.user_text:
            u = self.font_md.render(f"You:         {self.user_text[:82]}", True, BD_WHITE)
            self.screen.blit(u, (cx + pad, line1))

        if self.robot_text:
            mc = 82
            la = self.robot_text[:mc]
            lb = self.robot_text[mc:mc * 2]
            r1 = self.font_md.render(f"ShongiBot:   {la}", True, BD_GREEN_LIGHT)
            self.screen.blit(r1, (cx + pad, line2))
            if lb:
                r2 = self.font_md.render(f"             {lb}", True, BD_GREEN_LIGHT)
                self.screen.blit(r2, (cx + pad, line3))
        elif not self.user_text:
            hint = self.font_sm.render(
                "ShongiBot ready  •  Speak in Bangla or English about Bangladesh  •  [F] Fullscreen  [Q] Quit",
                True, BD_GREEN_DIM
            )
            self.screen.blit(hint, (cx + pad, cy + ch // 2 - hint.get_height() // 2))

    def render(self, dt):
        self._update(dt)
        self._draw_bg()
        self._draw_header()
        self._draw_face()
        self._draw_badge()
        self._draw_card()
        pygame.display.flip()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click / touchscreen tap
                    pos = pygame.mouse.get_pos()
                    if hasattr(self, 'exit_btn_rect') and self.exit_btn_rect.collidepoint(pos):
                        print("[GUI] Exit button clicked. Exiting ShongiBot...")
                        self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    self.running = False
                elif event.key == pygame.K_f:
                    self.fullscreen = not self.fullscreen
                    flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
                    self.screen = pygame.display.set_mode((self.sw, self.sh), flags)

    def close(self):
        pygame.quit()


gui_instance = None

def start_gui_in_main_thread(voice_backend_func, fullscreen=True):
    global gui_instance
    gui_instance = DeskBuddyGUI(fullscreen=fullscreen)

    backend_thread = threading.Thread(target=voice_backend_func, daemon=True)
    backend_thread.start()

    prev_time = time.time()
    while gui_instance.running:
        now      = time.time()
        dt       = min(now - prev_time, 0.05)
        prev_time = now
        gui_instance.handle_events()
        gui_instance.render(dt)
        gui_instance.clock.tick(60)

    gui_instance.close()
    sys.exit(0)
