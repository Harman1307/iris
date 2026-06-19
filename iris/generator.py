import sys
import json
import os
import hashlib
import math
from PIL import Image
import numpy as np


def get_cache_key(path, dark, glass):
    try:
        st = os.stat(path)
        raw = f"{path}{st.st_mtime}{st.st_size}_{dark}_{glass}"
    except Exception:
        raw = f"{path}_{dark}_{glass}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def check_cache(key):
    f = os.path.expanduser(f"~/.cache/wallpaper-colors/{key}.json")
    try:
        with open(f) as fh:
            return fh.read().strip()
    except Exception:
        return None


def write_cache(key, data):
    d = os.path.expanduser("~/.cache/wallpaper-colors")
    os.makedirs(d, exist_ok=True)
    try:
        with open(f"{d}/{key}.json", "w") as fh:
            fh.write(data)
    except Exception:
        pass


def resolve_path(path):
    try:
        r = os.path.realpath(path)
        return r if os.path.exists(r) else path
    except Exception:
        return path


def find_thumb(resolved):
    base = os.path.expanduser("~/.cache/wallpaper-thumbs")
    t = os.path.join(base, os.path.basename(resolved) + ".thumb.jpg")
    return t if os.path.exists(t) else None


def srgb_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def srgb_delin(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055


def rgb_to_lab(r, g, b):
    rl, gl, bl = srgb_lin(r), srgb_lin(g), srgb_lin(b)
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    def f(t):
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0
    fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def rgb_to_hsl(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = ((g - b) / d + (6.0 if g < b else 0.0)) / 6.0
    elif mx == g:
        h = ((b - r) / d + 2.0) / 6.0
    else:
        h = ((r - g) / d + 4.0) / 6.0
    return h * 360.0, s, l


def hsl_to_rgb(h, s, l):
    h /= 360.0
    s, l = max(0.0, min(1.0, s)), max(0.0, min(1.0, l))
    if s == 0.0:
        v = int(round(l * 255))
        return v, v, v
    def hue2rgb(p, q, t):
        t %= 1.0
        if t < 1.0 / 6.0: return p + (q - p) * 6.0 * t
        if t < 0.5: return q
        if t < 2.0 / 3.0: return p + (q - p) * (2.0 / 3.0 - t) * 6.0
        return p
    q = l * (1.0 + s) if l < 0.5 else l + s - l * s
    p = 2.0 * l - q
    return (
        int(round(hue2rgb(p, q, h + 1.0 / 3.0) * 255)),
        int(round(hue2rgb(p, q, h) * 255)),
        int(round(hue2rgb(p, q, h - 1.0 / 3.0) * 255)),
    )


def to_hex(r, g, b):
    return f"#{max(0,min(255,int(round(r)))):02x}{max(0,min(255,int(round(g)))):02x}{max(0,min(255,int(round(b)))):02x}"


def lum(r, g, b):
    return 0.2126 * srgb_lin(r) + 0.7152 * srgb_lin(g) + 0.0722 * srgb_lin(b)


def contrast(r1, g1, b1, r2, g2, b2):
    l1, l2 = lum(r1, g1, b1), lum(r2, g2, b2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def nudge_l(h, s, l, target_cr, against_rgb, go_darker):
    step = -0.005 if go_darker else 0.005
    hard_limit = 0.18 if go_darker else 0.82
    for _ in range(130):
        r, g, b = hsl_to_rgb(h, s, l)
        if contrast(r, g, b, *against_rgb) >= target_cr:
            return h, s, l
        l = l + step
        if go_darker and l < hard_limit:
            l = hard_limit
            break
        if not go_darker and l > hard_limit:
            l = hard_limit
            break
    return h, s, l


def hue_dist(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def hue_toward(h, target, amount):
    d = target - h
    if d > 180: d -= 360
    if d < -180: d += 360
    return (h + d * amount) % 360


def load_image(path):
    resolved = resolve_path(path)
    source = find_thumb(resolved) or resolved
    img = Image.open(source).convert("RGB")
    img.thumbnail((150, 150), Image.LANCZOS)
    return img


def sample_palette(img, debug=False):
    w, h = img.size

    px = np.array(img, dtype=np.float32).reshape(-1, 3)
    r, g, b = px[:, 0], px[:, 1], px[:, 2]

    rc = np.where(r / 255.0 <= 0.04045, r / 255.0 / 12.92, ((r / 255.0 + 0.055) / 1.055) ** 2.4)
    gc = np.where(g / 255.0 <= 0.04045, g / 255.0 / 12.92, ((g / 255.0 + 0.055) / 1.055) ** 2.4)
    bc = np.where(b / 255.0 <= 0.04045, b / 255.0 / 12.92, ((b / 255.0 + 0.055) / 1.055) ** 2.4)

    X = rc * 0.4124564 + gc * 0.3575761 + bc * 0.1804375
    Y = rc * 0.2126729 + gc * 0.7151522 + bc * 0.0721750
    Z = rc * 0.0193339 + gc * 0.1191920 + bc * 0.9503041

    def f_lab(t):
        return np.where(t > 0.008856, t ** (1.0 / 3.0), 7.787 * t + 16.0 / 116.0)

    fx = f_lab(X / 0.95047)
    fy = f_lab(Y)
    fz = f_lab(Z / 1.08883)

    L_chan = 116.0 * fy - 16.0
    a_chan = 500.0 * (fx - fy)
    b_chan = 200.0 * (fy - fz)
    lab_c  = np.sqrt(a_chan ** 2 + b_chan ** 2)

    mx = px.max(axis=1) / 255.0
    mn = px.min(axis=1) / 255.0
    lv = (mx + mn) / 2.0

    denom_s = np.where(lv > 0.5, 2.0 - mx - mn, mx + mn)
    s_chan   = np.where(mx == mn, 0.0, (mx - mn) / np.maximum(denom_s, 1e-9))

    ri, gi, bi = r / 255.0, g / 255.0, b / 255.0
    d_chan = mx - mn
    h_raw  = np.zeros(len(px), dtype=np.float32)
    mask_r = (mx == ri) & (d_chan > 0)
    mask_g = (mx == gi) & (d_chan > 0)
    mask_b = (mx == bi) & (d_chan > 0)
    h_raw[mask_r] = ((gi[mask_r] - bi[mask_r]) / d_chan[mask_r]) % 6.0
    h_raw[mask_g] = (bi[mask_g] - ri[mask_g]) / d_chan[mask_g] + 2.0
    h_raw[mask_b] = (ri[mask_b] - gi[mask_b]) / d_chan[mask_b] + 4.0
    h_chan = h_raw * 60.0

    ys = np.repeat(np.arange(h, dtype=np.float32), w)
    xs = np.tile(np.arange(w, dtype=np.float32), h)
    cx = np.abs((xs + 0.5) / w - 0.5) * 2.0
    cy = np.abs((ys + 0.5) / h - 0.5) * 2.0
    pw = 1.0 - (np.sqrt(cx ** 2 + cy ** 2) / math.sqrt(2.0)) * 0.18

    pixels_lab = np.stack([L_chan, a_chan, b_chan], axis=1)

    k = 14
    iterations = 14
    rng = np.random.default_rng(42)
    idx = rng.choice(len(pixels_lab), k, replace=False)
    centers = pixels_lab[idx].copy()

    assignments = np.zeros(len(pixels_lab), dtype=np.int32)
    for _ in range(iterations):
        dists = np.sum((pixels_lab[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        assignments = np.argmin(dists, axis=1)

        new_centers = np.zeros_like(centers)
        for i in range(k):
            mask = assignments == i
            if mask.any():
                new_centers[i] = pixels_lab[mask].mean(axis=0)
            else:
                new_centers[i] = centers[i]
        centers = new_centers

    entries = []
    for i in range(k):
        mask = assignments == i
        if not mask.any():
            continue
        w_i = pw[mask]
        total_w = w_i.sum()
        if total_w < 1.0:
            continue

        def wavg(arr, _w=w_i, _tw=total_w):
            return float((arr[mask] * _w).sum() / _tw)

        entries.append({
            "L": wavg(L_chan),
            "a": wavg(a_chan),
            "b": wavg(b_chan),
            "h": wavg(h_chan),
            "s": wavg(s_chan),
            "l": wavg(lv),
            "c": wavg(lab_c),
            "mass": float(total_w),
        })

    total_mass = sum(e["mass"] for e in entries) or 1.0
    for e in entries:
        presence = e["mass"] / total_mass
        e["sig"] = e["c"] * 0.50 + e["s"] * 100 * 0.30 + presence * 100 * 0.20

    entries.sort(key=lambda x: x["sig"], reverse=True)

    if debug:
        print(f"kmeans palette: {len(entries)} colors", file=sys.stderr)
        for e in entries:
            print(
                f"  h={e['h']:5.1f} s={e['s']:.3f} l={e['l']:.3f} "
                f"c={e['c']:.1f} sig={e['sig']:.1f} mass={e['mass']:.0f}",
                file=sys.stderr,
            )

    return entries


def read_tone(img):
    px = np.array(img, dtype=np.float32).reshape(-1, 3)
    r, g, b = px[:, 0], px[:, 1], px[:, 2]

    mx = px.max(axis=1) / 255.0
    mn = px.min(axis=1) / 255.0
    lv = (mx + mn) / 2.0

    denom_s = np.where(lv > 0.5, 2.0 - mx - mn, mx + mn)
    s_chan   = np.where(mx == mn, 0.0, (mx - mn) / np.maximum(denom_s, 1e-9))

    ri, gi, bi = r / 255.0, g / 255.0, b / 255.0
    d_chan = mx - mn
    h_raw  = np.zeros(len(px), dtype=np.float32)
    mask_r = (mx == ri) & (d_chan > 0)
    mask_g = (mx == gi) & (d_chan > 0)
    mask_b = (mx == bi) & (d_chan > 0)
    h_raw[mask_r] = ((gi[mask_r] - bi[mask_r]) / d_chan[mask_r]) % 6.0
    h_raw[mask_g] = (bi[mask_g] - ri[mask_g]) / d_chan[mask_g] + 2.0
    h_raw[mask_b] = (ri[mask_b] - gi[mask_b]) / d_chan[mask_b] + 4.0
    h_chan = h_raw * 60.0

    total = float(len(px))

    avg_l            = float(lv.mean())
    avg_s            = float(s_chan.mean())
    dark_ratio       = float((lv < 0.40).sum()) / total
    light_ratio      = float((lv > 0.60).sum()) / total
    very_dark_ratio  = float((lv < 0.15).sum()) / total
    very_light_ratio = float((lv > 0.85).sum()) / total
    true_black_ratio = float((lv < 0.05).sum()) / total
    true_white_ratio = float((lv > 0.95).sum()) / total
    grey_ratio       = float((s_chan < 0.12).sum()) / total

    warm_mask  = (s_chan > 0.10) & ((h_chan < 65) | (h_chan > 295))
    cool_mask  = (s_chan > 0.10) & (h_chan > 140) & (h_chan < 285)
    warm_w     = float(warm_mask.sum())
    cool_w     = float(cool_mask.sum())
    warm_ratio = warm_w / (warm_w + cool_w + 1e-9)

    return (
        avg_l, avg_s,
        dark_ratio, light_ratio, grey_ratio,
        warm_ratio,
        very_dark_ratio, very_light_ratio,
        true_black_ratio, true_white_ratio,
    )


def decide_dark(avg_l, dark_ratio, light_ratio, forced):
    if forced == 1: return True
    if forced == 0: return False
    if dark_ratio > 0.52: return True
    if light_ratio > 0.52: return False
    return avg_l < 0.50


def assign_bg(palette, is_dark, glass, is_pure_black, is_pure_white, is_grayscale):
    if is_grayscale:
        if is_dark:
            if is_pure_black:
                return 0.0, 0.005, 0.015
            else:
                return 0.0, 0.02, 0.13
        else:
            if is_pure_white:
                return 0.0, 0.005, 0.985
            else:
                return 0.0, 0.02, 0.87

    by_mass = sorted(palette, key=lambda e: e["mass"], reverse=True)

    if is_dark:
        candidates = [e for e in by_mass if e["l"] < 0.52]
        if not candidates:
            candidates = sorted(palette, key=lambda e: e["l"])

        src = candidates[0]

        if is_pure_black:
            return 0.0, 0.005, 0.015

        target_l = max(0.12, min(src["l"], 0.28))
        target_s = src["s"]

        if glass:
            target_l = max(target_l - 0.02, 0.10)
    else:
        candidates = [e for e in by_mass if e["l"] > 0.48]
        if not candidates:
            candidates = sorted(palette, key=lambda e: e["l"], reverse=True)

        src = candidates[0]

        if is_pure_white:
            return 0.0, 0.005, 0.985

        target_l = max(0.72, min(src["l"], 0.92))
        target_s = src["s"]

        if glass:
            target_l = min(target_l + 0.02, 0.94)

    return src["h"], target_s, target_l


def assign_fg(palette, bg_h, bg_s, bg_l, bg_rgb, is_dark, is_grayscale):
    if is_grayscale:
        if is_dark:
            return 0.0, 0.01, 0.88
        else:
            return 0.0, 0.01, 0.12

    if is_dark:
        candidates = sorted(palette, key=lambda e: e["l"], reverse=True)
        src = candidates[0]
        target_l = max(0.75, min(src["l"] if src["l"] > 0.60 else 0.82, 0.91))
        h = src["h"]
        s = src["s"]
        l = target_l
        h, s, l = nudge_l(h, s, l, 4.5, bg_rgb, False)
        l = max(0.72, min(l, 0.91))
    else:
        candidates = sorted(palette, key=lambda e: e["l"])
        src = candidates[0]
        h = src["h"]
        s = min(src["s"] * 0.60, 0.25)
        l = 0.11
        h, s, l = nudge_l(h, s, l, 7.0, bg_rgb, True)
        l = max(0.08, min(l, 0.20))

    return h, s, l


def assign_surface(bg_h, bg_s, bg_l, is_dark):
    if is_dark:
        return bg_h, bg_s, max(0.10, min(bg_l + 0.07, 0.36))
    else:
        return bg_h, bg_s, max(0.60, min(bg_l - 0.07, 0.90))


def assign_dim(bg_h, bg_s, bg_l, fg_l, is_dark, is_grayscale):
    mid_l = bg_l + (fg_l - bg_l) * 0.38
    if is_grayscale:
        return 0.0, 0.01, mid_l
    dim_s = bg_s * 0.65
    dim_s = max(0.04, min(dim_s, 0.40))
    return bg_h, dim_s, mid_l


def assign_accent(palette, bg_h, bg_s, bg_l, bg_rgb, is_dark, is_grayscale):
    if is_grayscale:
        if is_dark:
            return 220.0, 0.22, 0.68
        else:
            return 220.0, 0.35, 0.38

    best = None
    best_score = -1.0
    for e in palette:
        hd = hue_dist(e["h"], bg_h)
        score = e["sig"] * 0.60 + min(hd / 90.0, 1.0) * 40 * 0.40
        if score > best_score:
            best_score = score
            best = e

    if best is None:
        best = palette[0]

    h = best["h"]
    s = best["s"]

    if is_dark:
        l = best["l"]
        if l < 0.45:
            l = 0.58 + (best["c"] / 60.0) * 0.14
        l = max(0.48, min(l, 0.80))
        cr = 3.0
        h, s, l = nudge_l(h, s, l, cr, bg_rgb, False)
        l = max(0.45, min(l, 0.82))
    else:
        l = best["l"]
        if l > 0.55:
            l = 0.36 - (best["c"] / 60.0) * 0.08
        l = max(0.22, min(l, 0.52))
        cr = 4.0
        h, s, l = nudge_l(h, s, l, cr, bg_rgb, True)
        l = max(0.18, min(l, 0.55))

    return h, s, l


def assign_semantic(target_h, palette, bg_h, avg_s, bg_rgb, is_dark, is_grayscale, tol=60):
    if is_grayscale:
        if is_dark:
            s = 0.40
            l = 0.68
        else:
            s = 0.62
            l = 0.38
        return hsl_to_rgb(target_h, s, l)

    found = None
    best_d = 999
    for e in palette:
        d = hue_dist(e["h"], target_h)
        if d < tol and d < best_d:
            best_d = d
            found = e

    if found is not None:
        h = found["h"]
        s = max(found["s"], 0.40 if is_dark else 0.75)
        l = found["l"]
    else:
        closest_d = 999
        closest = None
        for e in palette:
            d = hue_dist(e["h"], target_h)
            if d < closest_d:
                closest_d = d
                closest = e

        if closest is not None:
            rotate = min(closest_d, 35.0)
            h = hue_toward(closest["h"], target_h, rotate / closest_d if closest_d > 0 else 1.0)
            s = max(closest["s"], 0.40 if is_dark else 0.75)
            l = closest["l"]
        else:
            h = target_h
            s = 0.45 if is_dark else 0.80
            l = 0.55

    if is_dark:
        l = max(0.52, min(l, 0.78))
        cr = 3.0
        h, s, l = nudge_l(h, s, l, cr, bg_rgb, False)
        l = max(0.48, min(l, 0.82))
    else:
        s = max(s, 0.75)
        l = max(0.25, min(l, 0.42))
        cr = 6.0
        h, s, l = nudge_l(h, s, l, cr, bg_rgb, True)
        l = max(0.22, min(l, 0.45))

    return hsl_to_rgb(h, s, l)


def assign_syntax(palette, bg_h, avg_s, bg_rgb, is_dark, is_grayscale):
    role_names = [
        "syntax_keyword", "syntax_string", "syntax_func",
        "syntax_type", "syntax_const", "syntax_param", "syntax_operator",
    ]

    if is_grayscale:
        if is_dark:
            hues = [240, 200, 220, 260, 180, 210, 230]
            s_base = 0.28
            l_base = 0.70
        else:
            hues = [240, 200, 220, 260, 180, 210, 230]
            s_base = 0.45
            l_base = 0.36

        assigned = []
        for h in hues:
            assigned.append(to_hex(*hsl_to_rgb(h, s_base, l_base)))

        result = dict(zip(role_names, assigned))
        if is_dark:
            result["syntax_comment"] = to_hex(*hsl_to_rgb(0.0, 0.01, 0.48))
        else:
            result["syntax_comment"] = to_hex(*hsl_to_rgb(0.0, 0.01, 0.52))
        return result

    if is_dark:
        l_default = 0.70
        l_lo      = 0.58
        l_hi      = 0.84
        cr        = 4.0
        dim_cr    = 2.4
        s_floor   = 0.38

        palette_by_sig = sorted(palette, key=lambda e: e["sig"], reverse=True)
        hue_buckets = set()
        for e in palette_by_sig:
            hue_buckets.add(int(e["h"] / 90))
        palette_too_limited = len(hue_buckets) < 3 or len(palette) < 4

        assigned = []
        used_hues = []

        def hue_too_close(h, used, min_dist=45):
            return any(hue_dist(h, u) < min_dist for u in used)

        angles = [285, 30, 195, 168, 18, 182, 212]

        for angle in angles:
            target_h = (bg_h + angle) % 360
            chosen_h = None
            chosen_s = None

            if not palette_too_limited:
                best_d = 999
                for e in palette_by_sig:
                    d = hue_dist(e["h"], target_h)
                    if d < 65 and d < best_d:
                        if not hue_too_close(e["h"], used_hues):
                            best_d = d
                            chosen_h = e["h"]
                            chosen_s = max(e["s"], s_floor)
                            break

            if chosen_h is None:
                h = target_h
                attempts = 0
                while hue_too_close(h, used_hues, 40) and attempts < 20:
                    h = (h + 8) % 360
                    attempts += 1
                chosen_h = h
                chosen_s = s_floor

            used_hues.append(chosen_h)
            l = l_default
            h, s, l = nudge_l(chosen_h, chosen_s, l, cr, bg_rgb, False)
            l = max(l_lo, min(l, l_hi))
            assigned.append(to_hex(*hsl_to_rgb(h, s, l)))

        result = dict(zip(role_names, assigned))
        comm_l = 0.52
        ch, cs, cl = nudge_l(bg_h, max(avg_s * 0.50, 0.06), comm_l, dim_cr, bg_rgb, False)
        result["syntax_comment"] = to_hex(*hsl_to_rgb(ch, cs, cl))

    else:
        l_default = 0.36
        l_lo      = 0.28
        l_hi      = 0.46
        cr        = 5.0
        dim_cr    = 3.5
        s_floor   = 0.62

        palette_by_sig = sorted(palette, key=lambda e: e["sig"], reverse=True)

        assigned = []
        used_hues = []

        def hue_too_close(h, used, min_dist=38):
            return any(hue_dist(h, u) < min_dist for u in used)

        absolute_hues = [270, 12, 210, 155, 35, 195, 245]

        for target_h in absolute_hues:
            chosen_h = None
            chosen_s = None

            best_d = 999
            for e in palette_by_sig:
                d = hue_dist(e["h"], target_h)
                if d < 55 and d < best_d:
                    if not hue_too_close(e["h"], used_hues):
                        best_d = d
                        chosen_h = e["h"]
                        chosen_s = max(e["s"], s_floor)
                        break

            if chosen_h is None:
                h = target_h
                attempts = 0
                while hue_too_close(h, used_hues, 35) and attempts < 20:
                    h = (h + 10) % 360
                    attempts += 1
                chosen_h = h
                chosen_s = s_floor

            chosen_s = max(chosen_s, s_floor)
            used_hues.append(chosen_h)
            l = l_default
            h, s, l = nudge_l(chosen_h, chosen_s, l, cr, bg_rgb, True)
            l = max(l_lo, min(l, l_hi))
            assigned.append(to_hex(*hsl_to_rgb(h, s, l)))

        result = dict(zip(role_names, assigned))
        comm_l = 0.50
        comm_s = max(avg_s * 0.35, 0.08)
        ch, cs, cl = nudge_l(bg_h, comm_s, comm_l, dim_cr, bg_rgb, True)
        cl = max(0.44, min(cl, 0.56))
        result["syntax_comment"] = to_hex(*hsl_to_rgb(ch, cs, cl))

    return result


def build_theme(img, forced_dark, glass, debug):
    palette = sample_palette(img, debug)
    avg_l, avg_s, dark_ratio, light_ratio, grey_ratio, warm_ratio, very_dark_ratio, very_light_ratio, true_black_ratio, true_white_ratio = read_tone(img)

    is_pure_black = true_black_ratio > 0.45
    is_pure_white = true_white_ratio > 0.45
    is_grayscale  = grey_ratio > 0.70 and true_black_ratio < 0.30 and true_white_ratio < 0.30

    is_dark = decide_dark(avg_l, dark_ratio, light_ratio, forced_dark)

    if not palette:
        fh = 30.0 if warm_ratio > 0.52 else 218.0
        palette = [{"h": fh, "s": 0.22, "l": 0.50, "c": 18.0, "sig": 50.0, "mass": 1000,
                    "L": 50.0, "a": 0.0, "b": 0.0}]

    bg_h, bg_s, bg_l = assign_bg(palette, is_dark, glass, is_pure_black, is_pure_white, is_grayscale)
    bg_rgb = hsl_to_rgb(bg_h, bg_s, bg_l)

    sf_h, sf_s, sf_l = assign_surface(bg_h, bg_s, bg_l, is_dark)
    surf_rgb = hsl_to_rgb(sf_h, sf_s, sf_l)

    fg_h, fg_s, fg_l = assign_fg(palette, bg_h, bg_s, bg_l, bg_rgb, is_dark, is_grayscale)
    fg_rgb = hsl_to_rgb(fg_h, fg_s, fg_l)

    dim_h, dim_s, dim_l = assign_dim(bg_h, bg_s, bg_l, fg_l, is_dark, is_grayscale)
    dim_rgb = hsl_to_rgb(dim_h, dim_s, dim_l)

    acc_h, acc_s, acc_l = assign_accent(palette, bg_h, bg_s, bg_l, bg_rgb, is_dark, is_grayscale)
    acc_rgb = hsl_to_rgb(acc_h, acc_s, acc_l)

    red_rgb    = assign_semantic(5.0,   palette, bg_h, avg_s, bg_rgb, is_dark, is_grayscale, 60)
    green_rgb  = assign_semantic(138.0, palette, bg_h, avg_s, bg_rgb, is_dark, is_grayscale, 62)
    yellow_rgb = assign_semantic(48.0,  palette, bg_h, avg_s, bg_rgb, is_dark, is_grayscale, 52)

    syntax = assign_syntax(palette, bg_h, avg_s, bg_rgb, is_dark, is_grayscale)

    if debug:
        print(f"is_dark={is_dark} is_pure_black={is_pure_black} is_pure_white={is_pure_white} is_grayscale={is_grayscale}", file=sys.stderr)
        print(f"avg_l={avg_l:.3f} avg_s={avg_s:.3f} warm={warm_ratio:.3f}", file=sys.stderr)
        print(f"grey_ratio={grey_ratio:.3f} very_dark={very_dark_ratio:.3f} very_light={very_light_ratio:.3f}", file=sys.stderr)
        print(f"true_black={true_black_ratio:.3f} true_white={true_white_ratio:.3f}", file=sys.stderr)
        print(f"bg  h={bg_h:.1f} s={bg_s:.3f} l={bg_l:.3f}  {to_hex(*bg_rgb)}", file=sys.stderr)
        print(f"srf h={sf_h:.1f} s={sf_s:.3f} l={sf_l:.3f}  {to_hex(*surf_rgb)}", file=sys.stderr)
        print(f"fg  h={fg_h:.1f} s={fg_s:.3f} l={fg_l:.3f}  {to_hex(*fg_rgb)}", file=sys.stderr)
        print(f"dim h={dim_h:.1f} s={dim_s:.3f} l={dim_l:.3f}  {to_hex(*dim_rgb)}", file=sys.stderr)
        print(f"acc h={acc_h:.1f} s={acc_s:.3f} l={acc_l:.3f}  {to_hex(*acc_rgb)}", file=sys.stderr)
        print(f"red={to_hex(*red_rgb)} grn={to_hex(*green_rgb)} yel={to_hex(*yellow_rgb)}", file=sys.stderr)
        for k, v in syntax.items():
            print(f"  {k}={v}", file=sys.stderr)

    return {
        "bg":      to_hex(*bg_rgb),
        "surface": to_hex(*surf_rgb),
        "fg":      to_hex(*fg_rgb),
        "dim":     to_hex(*dim_rgb),
        "accent":  to_hex(*acc_rgb),
        "red":     to_hex(*red_rgb),
        "green":   to_hex(*green_rgb),
        "yellow":  to_hex(*yellow_rgb),
        "dark":    is_dark,
        "tone_l":  round(avg_l, 3),
        **syntax,
    }


def fallback(is_dark):
    if is_dark:
        return {
            "bg":              "#2d3a2e",
            "surface":         "#38483a",
            "fg":              "#c8d5b9",
            "dim":             "#7a9478",
            "accent":          "#e8b84a",
            "red":             "#c87878",
            "green":           "#78b898",
            "yellow":          "#c8b050",
            "syntax_keyword":  "#c888c8",
            "syntax_string":   "#c8a068",
            "syntax_func":     "#80b0d8",
            "syntax_type":     "#70c0b8",
            "syntax_const":    "#c89068",
            "syntax_comment":  "#6a8468",
            "syntax_param":    "#80b8c8",
            "syntax_operator": "#88b8d0",
            "dark":            True,
            "tone_l":          0.25,
        }
    return {
        "bg":              "#e8ede0",
        "surface":         "#d8e0cc",
        "fg":              "#2e3828",
        "dim":             "#6e7a62",
        "accent":          "#8b6914",
        "red":             "#9c3428",
        "green":           "#3a6e48",
        "yellow":          "#8c6020",
        "syntax_keyword":  "#7c2878",
        "syntax_string":   "#7c4010",
        "syntax_func":     "#204888",
        "syntax_type":     "#1a6060",
        "syntax_const":    "#803010",
        "syntax_comment":  "#6e7a62",
        "syntax_param":    "#1a5868",
        "syntax_operator": "#204870",
        "dark":            False,
        "tone_l":          0.82,
    }


def generate(wallpaper_path, dark_mode=-1, glass=False, debug=False):
    try:
        img = load_image(wallpaper_path)
    except Exception as e:
        if debug:
            print(f"load error: {e}", file=sys.stderr)
        return fallback(dark_mode == 1)

    try:
        theme = build_theme(img, dark_mode, glass, debug)
    except Exception as e:
        if debug:
            print(f"build error: {e}", file=sys.stderr)
        return fallback(dark_mode == 1)

    return theme