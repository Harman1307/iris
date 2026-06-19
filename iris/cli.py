import argparse
import json
import sys
import re
from pathlib import Path
from . import generator


CACHE_DIR = Path.home() / ".cache" / "iris"
WAL_CACHE_DIR = Path.home() / ".cache" / "wal"


def build_terminal_palette(theme):
    return {
        "color0": theme["bg"],
        "color1": theme["red"],
        "color2": theme["green"],
        "color3": theme["yellow"],
        "color4": theme["accent"],
        "color5": theme.get("syntax_keyword", theme["accent"]),
        "color6": theme.get("syntax_func", theme["accent"]),
        "color7": theme["dim"],
        "color8": theme["surface"],
        "color9": theme["red"],
        "color10": theme["green"],
        "color11": theme["yellow"],
        "color12": theme["accent"],
        "color13": theme.get("syntax_keyword", theme["accent"]),
        "color14": theme.get("syntax_func", theme["accent"]),
        "color15": theme["fg"],
    }


def write_shell_file(path, theme, palette):
    lines = []
    for key in ["bg", "fg", "surface", "dim", "accent", "red", "green", "yellow"]:
        lines.append(f"{key}='{theme[key]}'\n")
    for i in range(16):
        lines.append(f"color{i}='{palette[f'color{i}']}'\n")
    path.write_text("".join(lines))


def write_sequences(path, palette):
    sequences = []
    for i in range(16):
        color = palette[f"color{i}"].lstrip("#")
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        sequences.append(f"\033]4;{i};rgb:{r:02x}/{g:02x}/{b:02x}\033\\")
    
    bg = palette["color0"].lstrip("#")
    r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
    sequences.append(f"\033]11;rgb:{r:02x}/{g:02x}/{b:02x}\033\\")
    
    fg = palette["color15"].lstrip("#")
    r, g, b = int(fg[0:2], 16), int(fg[2:4], 16), int(fg[4:6], 16)
    sequences.append(f"\033]10;rgb:{r:02x}/{g:02x}/{b:02x}\033\\")
    
    path.write_text("".join(sequences))


def write_css_file(path, theme):
    lines = [":root {\n"]
    for key, value in theme.items():
        if isinstance(value, str) and value.startswith("#"):
            lines.append(f"    --{key}: {value};\n")
    lines.append("}\n")
    path.write_text("".join(lines))


def hex_to_rgb_string(hex_color):
    hex_color = hex_color.lstrip("#")
    return f"{int(hex_color[0:2], 16)}, {int(hex_color[2:4], 16)}, {int(hex_color[4:6], 16)}"


def render_templates(theme, palette):
    template_dir = Path.home() / ".config" / "iris" / "templates"
    
    builtin_template_dir = Path(__file__).parent / "templates"
    
    variables = {**theme, **palette}
    
    def replace_vars(content):
        result = content
        for key, value in variables.items():
            if isinstance(value, str):
                result = result.replace(f"{{{key}}}", value)
                if value.startswith("#"):
                    result = result.replace(f"{{{key}.rgb}}", hex_to_rgb_string(value))
                    result = result.replace(f"{{{key}.strip}}", value.lstrip("#"))
        return result
    
    if builtin_template_dir.exists():
        for template in builtin_template_dir.iterdir():
            if template.is_file() and not template.name.startswith("."):
                rendered = replace_vars(template.read_text())
                (CACHE_DIR / template.name).write_text(rendered)
    
    if template_dir.exists():
        for template in template_dir.iterdir():
            if template.is_file() and not template.name.startswith("."):
                rendered = replace_vars(template.read_text())
                (CACHE_DIR / template.name).write_text(rendered)


def write_wal_compat(theme, palette, wallpaper):
    WAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    wal_json = {
        "wallpaper": str(Path(wallpaper).resolve()),
        "alpha": "100",
        "special": {
            "background": theme["bg"],
            "foreground": theme["fg"],
            "cursor": theme["fg"],
        },
        "colors": palette
    }
    
    (WAL_CACHE_DIR / "colors.json").write_text(json.dumps(wal_json, indent=4))
    write_shell_file(WAL_CACHE_DIR / "colors.sh", theme, palette)
    write_sequences(WAL_CACHE_DIR / "sequences", palette)


def write_outputs(theme, wallpaper, compat_mode=None):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    (CACHE_DIR / "colors.json").write_text(json.dumps(theme, indent=2))
    
    palette = build_terminal_palette(theme)
    
    write_shell_file(CACHE_DIR / "colors.sh", theme, palette)
    write_sequences(CACHE_DIR / "sequences", palette)
    write_css_file(CACHE_DIR / "colors.css", theme)
    
    render_templates(theme, palette)
    
    if compat_mode == "wal":
        write_wal_compat(theme, palette, wallpaper)


def main():
    parser = argparse.ArgumentParser(
        prog="iris",
        description="semantic color scheme generator"
    )
    
    parser.add_argument("wallpaper", nargs="?", help="path to wallpaper")
    parser.add_argument("-i", "--image", dest="wallpaper_flag", help="wallpaper path")
    parser.add_argument("--dark", type=int, default=-1, choices=[-1, 0, 1], help="-1=auto, 0=light, 1=dark")
    parser.add_argument("--glass", action="store_true", help="adjust bg for transparency")
    parser.add_argument("--debug", action="store_true", help="print debug info")
    parser.add_argument("--json-only", action="store_true", help="only print json, no files")
    parser.add_argument("--compat", choices=["wal"], help="write to pywal cache")
    
    args = parser.parse_args()
    
    wallpaper = args.wallpaper or args.wallpaper_flag
    if not wallpaper:
        parser.print_help()
        sys.exit(1)
    
    resolved = generator.resolve_path(wallpaper)
    cache_key = generator.get_cache_key(resolved, args.dark, 1 if args.glass else 0)
    cached = generator.check_cache(cache_key)
    
    if cached:
        theme = json.loads(cached)
    else:
        theme = generator.generate(
            wallpaper,
            dark_mode=args.dark,
            glass=args.glass,
            debug=args.debug
        )
        generator.write_cache(cache_key, json.dumps(theme))
    
    if args.json_only:
        print(json.dumps(theme))
        return
    
    write_outputs(theme, wallpaper, args.compat)
    
    if not args.debug:
        print(f"generated colors from {Path(wallpaper).name}")
        print(f"  {CACHE_DIR}")
        if args.compat:
            print(f"  {WAL_CACHE_DIR}")