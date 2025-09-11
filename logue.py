#!/usr/bin/env python3
"""
logue.py – Terminal logbook with Git integration.

Aesthetic and spacing changes:
 - Adds configurable vertical gap between "Tasks for today" list and "Tasks for tomorrow" header.
 - Color-codes each section:
     * Tasks for today — cyan
     * Tasks for tomorrow — yellow
     * Today's entries — green
 - Main header and entry box (labels & input) use white.
 - No functional changes beyond styling and spacing.
"""

import argparse
import curses
import datetime
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List, Dict, Any, Optional

# ------------ Config ------------
TASKS_GAP = 1  # number of blank lines between today's tasks and tomorrow's header

# ------------ Paths ------------
SCRIPT_DIR = Path(__file__).resolve().parent
LOGFILE = SCRIPT_DIR / "logue.json"


# ------------ Data storage ------------
def load_data() -> Dict[str, Any]:
    if not LOGFILE.exists():
        return {"entries": [], "tasks": {}}
    try:
        with LOGFILE.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading log file: {e}", file=sys.stderr)
        return {"entries": [], "tasks": {}}

    if isinstance(obj, list):
        return {"entries": obj, "tasks": {}}
    if isinstance(obj, dict):
        entries = obj.get("entries", [])
        tasks = obj.get("tasks", {})
        if not isinstance(entries, list):
            entries = []
        if not isinstance(tasks, dict):
            tasks = {}
        return {"entries": entries, "tasks": tasks}
    return {"entries": [], "tasks": {}}


def save_data(data: Dict[str, Any]) -> None:
    out = {"entries": data.get("entries", []), "tasks": data.get("tasks", {})}
    with LOGFILE.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


# ------------ Git (silent) ------------
def git_commit_and_push() -> None:
    try:
        subprocess.run(
            ["git", "add", str(LOGFILE.name)], check=True, cwd=SCRIPT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ["git", "commit", "-m", "logue: update"], check=True, cwd=SCRIPT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(["git", "push"], check=True, cwd=SCRIPT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Git operation failed: {e}", file=sys.stderr)
        print(
            "If authentication fails after reboot, set a GitHub token:\n"
            "  git remote set-url origin https://<USERNAME>:<TOKEN>@github.com/<USERNAME>/<REPO>.git",
            file=sys.stderr,
        )


# ------------ Helpers ------------
def extract_tags(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"#(\w+)", text)]


def extract_tasks_and_clean_text(text: str) -> (List[str], str):
    tasks = re.findall(r'\*\s*([^\n\r]+)', text)
    cleaned = re.sub(r'\*\s*[^\n\r]+', '', text)
    cleaned = "\n".join([ln.rstrip() for ln in cleaned.splitlines() if ln.strip() != ""]).strip()
    tasks = [t.strip() for t in tasks if t.strip()]
    return tasks, cleaned


def ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    elif n % 10 == 1:
        return f"{n}st"
    elif n % 10 == 2:
        return f"{n}nd"
    elif n % 10 == 3:
        return f"{n}rd"
    else:
        return f"{n}th"


# ------------ Input (single-line editor) ------------
def get_singleline_input(stdscr, y: int, x: int, max_width: int) -> Optional[str]:
    buffer: List[str] = []
    cursor_pos = 0
    scroll = 0
    visible = max(1, max_width)

    while True:
        if cursor_pos < scroll:
            scroll = cursor_pos
        elif cursor_pos > scroll + visible - 1:
            scroll = cursor_pos - (visible - 1)

        view = "".join(buffer)[scroll:scroll + visible]

        stdscr.move(y, x)
        stdscr.clrtoeol()
        try:
            stdscr.addstr(y, x, view)
        except curses.error:
            pass

        cursor_col = x + max(0, cursor_pos - scroll)
        max_y, max_x = stdscr.getmaxyx()
        cursor_col = min(cursor_col, max_x - 1)
        try:
            stdscr.move(y, cursor_col)
        except curses.error:
            stdscr.move(max(0, min(max_y - 1, y)), max(0, cursor_col))

        ch = stdscr.getch()

        if ch in (10, 13):
            return "".join(buffer).strip()
        elif ch == 27:
            return None
        elif ch in (8, 127, curses.KEY_BACKSPACE):
            if cursor_pos > 0:
                buffer.pop(cursor_pos - 1)
                cursor_pos -= 1
        elif ch == curses.KEY_LEFT and cursor_pos > 0:
            cursor_pos -= 1
        elif ch == curses.KEY_RIGHT and cursor_pos < len(buffer):
            cursor_pos += 1
        elif 32 <= ch <= 126:
            buffer.insert(cursor_pos, chr(ch))
            cursor_pos += 1
        # ignore other keys


# ------------ Main UI ------------
def interactive_mode(stdscr) -> None:
    sys.stdout.write("\x1b]2;logue\x07")
    sys.stdout.flush()

    curses.cbreak()
    curses.noecho()
    stdscr.keypad(True)

    # Colors and attributes:
    if curses.has_colors():
        curses.start_color()
        # pair 1: tasks for today (cyan)
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
        # pair 2: tasks for tomorrow (yellow)
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        # pair 3: today's entries (green)
        curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)
        # pair 4: header / entry box (white)
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)

        tasks_today_attr = curses.color_pair(1)
        tasks_today_title_attr = curses.color_pair(1) | curses.A_BOLD

        tasks_tomorrow_attr = curses.color_pair(2)
        tasks_tomorrow_title_attr = curses.color_pair(2) | curses.A_BOLD

        entries_attr = curses.color_pair(3)
        entries_title_attr = curses.color_pair(3) | curses.A_BOLD

        header_attr = curses.color_pair(4) | curses.A_BOLD
        label_attr = curses.color_pair(4)
        input_attr = curses.color_pair(4)
    else:
        # fallback attributes
        tasks_today_attr = tasks_today_title_attr = curses.A_BOLD
        tasks_tomorrow_attr = tasks_tomorrow_title_attr = curses.A_BOLD
        entries_attr = entries_title_attr = curses.A_BOLD
        header_attr = label_attr = input_attr = curses.A_NORMAL

    # load data
    data = load_data()
    entries: List[Dict[str, Any]] = data.get("entries", [])
    tasks_map: Dict[str, List[str]] = data.get("tasks", {})

    # startup location prompt
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    prompt_loc = "Enter location (optional, press Enter to skip): "
    stdscr.addstr(0, 2, prompt_loc, label_attr)
    stdscr.refresh()
    loc = get_singleline_input(stdscr, 0, 2 + len(prompt_loc), max(10, width - len(prompt_loc) - 6))
    if loc is None:
        return
    location = loc.strip()

    location_tags: List[str] = []
    if location:
        raw = location.lower()
        underscore = raw.replace(" ", "_")
        location_tags = [raw] if raw == underscore else [raw, underscore]

    # dates
    today_date = datetime.date.today()
    today_str = today_date.strftime("%Y_%m_%d")
    tomorrow_date = today_date + datetime.timedelta(days=1)
    tomorrow_str = tomorrow_date.strftime("%Y_%m_%d")
    date_str_pretty = f"{today_date.strftime('%B')} {ordinal(today_date.day)} {today_date.year}"

    # main loop
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        left = 2
        right = 2

        # header (white)
        header_text = f"logue: {date_str_pretty}"
        if location:
            header_text += f"; {location}"
        try:
            stdscr.addstr(0, left, header_text, header_attr)
        except curses.error:
            pass

        # Entry box (white)
        box_top, box_left = 2, left
        box_width = max(30, width - left - right)
        box_height = 3
        try:
            stdscr.addch(box_top, box_left, curses.ACS_ULCORNER)
            stdscr.hline(box_top, box_left + 1, curses.ACS_HLINE, box_width - 2)
            stdscr.addch(box_top, box_left + box_width - 1, curses.ACS_URCORNER)
            stdscr.vline(box_top + 1, box_left, curses.ACS_VLINE, box_height - 2)
            stdscr.vline(box_top + 1, box_left + box_width - 1, curses.ACS_VLINE, box_height - 2)
            stdscr.addch(box_top + box_height - 1, box_left, curses.ACS_LLCORNER)
            stdscr.hline(box_top + box_height - 1, box_left + 1, curses.ACS_HLINE, box_width - 2)
            stdscr.addch(box_top + box_height - 1, box_left + box_width - 1, curses.ACS_LRCORNER)
        except curses.error:
            pass

        prompt_text = "Entry: "
        entry_y = box_top + 1
        entry_x = box_left + 2 + len(prompt_text)
        stdscr.addstr(box_top + 1, box_left + 2, prompt_text, label_attr)
        entry_visible_width = max(10, box_left + box_width - entry_x - 2)

        # Tasks for today (title uses same look as header but colored cyan)
        tasks_top = box_top + box_height + 1
        if tasks_top < height - 1:
            stdscr.addstr(tasks_top, left + 0, "  Tasks for today:", tasks_today_title_attr)
        current_line = tasks_top + 1

        tasks_map = data.get("tasks", {})
        todays_tasks = tasks_for_date(tasks_map, today_str)
        for t in todays_tasks:
            if current_line < height - 1:
                stdscr.addstr(current_line, left + 4, f"- {t}", tasks_today_attr)
                current_line += 1
            else:
                break

        # Add vertical gap
        for _ in range(TASKS_GAP):
            if current_line < height - 1:
                current_line += 1

        # Tasks for tomorrow (title/color: yellow)
        if current_line < height - 1:
            stdscr.addstr(current_line, left + 0, "  Tasks for tomorrow:", tasks_tomorrow_title_attr)
            current_line += 1

        tom_tasks = tasks_for_date(tasks_map, tomorrow_str)
        for t in tom_tasks:
            if current_line < height - 1:
                stdscr.addstr(current_line, left + 4, f"- {t}", tasks_tomorrow_attr)
                current_line += 1
            else:
                break

        # Add a small spacer before entries
        if current_line < height - 1:
            current_line += 1

        # Today's Entries (title/color: green)
        entries_start = current_line
        if entries_start < height - 1:
            stdscr.addstr(entries_start, left + 0, "  Today's entries:", entries_title_attr)
        line = entries_start + 1
        box_height_logs = max(0, height - line - 1)

        session_entries = [
            e for e in entries
            if e.get("timestamp", "").startswith(today_str) and str(e.get("text", "")).strip() != ""
        ]

        for entry in reversed(session_entries[-(box_height_logs - 1):]):
            if line >= height - 1:
                break
            try:
                ts = datetime.datetime.strptime(entry["timestamp"], "%Y_%m_%d_%H_%M_%S")
                time_str = ts.strftime("%H:%M")
            except Exception:
                time_str = entry.get("timestamp", "")[-8:-3]
            stdscr.addstr(line, left + 2, f"{time_str}", entries_attr)
            display = f" - {entry.get('text','')}"
            wrap_width = max(10, width - (left + 14))
            for wl in textwrap.wrap(display, wrap_width):
                if line < height - 1:
                    stdscr.addstr(line, left + 12, wl, entries_attr)
                    line += 1
                else:
                    break
            if line < height - 1:
                line += 1

        # status/help
        help_line = "Enter = submit entry | ESC = quit"
        try:
            stdscr.addstr(height - 1, 2, help_line[: max(0, width - 4)], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

        # Input
        stdscr.attron(input_attr)
        note = get_singleline_input(stdscr, entry_y, entry_x, entry_visible_width)
        stdscr.attroff(input_attr)

        if note is None:
            break

        if note == "":
            continue

        tasks, cleaned_note = extract_tasks_and_clean_text(note)

        now_exact = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        tags = extract_tags(note)
        for lt in location_tags if 'location_tags' in locals() else []:
            if lt not in tags:
                tags.append(lt)
        new_entry = {"timestamp": now_exact, "text": cleaned_note, "tags": tags, "location": location}
        entries.append(new_entry)
        data["entries"] = entries

        if tasks:
            tasks_map = data.get("tasks", {})
            for t in tasks:
                add_task_for_date(tasks_map, tomorrow_str, t)
            data["tasks"] = tasks_map

        save_data(data)
        git_commit_and_push()


# ------------ Task utilities ------------
def tasks_for_date(tasks_map: Dict[str, List[str]], date_str: str) -> List[str]:
    return tasks_map.get(date_str, [])


def add_task_for_date(tasks_map: Dict[str, List[str]], date_str: str, task: str) -> None:
    if not task:
        return
    tasks_map.setdefault(date_str, []).append(task)


# ------------ CLI search helpers ------------
def search_by_date(date_prefix: str) -> None:
    data = load_data()
    entries = data.get("entries", [])
    matches = [e for e in entries if e.get("timestamp", "").startswith(date_prefix)]
    if matches:
        for e in matches:
            tags = f" [tags: {', '.join(e.get('tags', []))}]" if e.get("tags") else ""
            location = f" [location: {e.get('location','')}]"
            print(f"{e['timestamp']}: {e['text']}{tags}{location}")
    else:
        print(f"No entries found for {date_prefix}")


def search_by_tag(tag: str) -> None:
    data = load_data()
    entries = data.get("entries", [])
    tag = tag.lower()
    matches = [e for e in entries if tag in [t.lower() for t in e.get("tags", [])]]
    if matches:
        for e in matches:
            print(f"{e['timestamp']}: {e['text']} [tags: {', '.join(e.get('tags', []))}] [location: {e.get('location','')}]")
    else:
        print(f"No entries found for tag #{tag}")


# ------------ Main ------------
def main():
    parser = argparse.ArgumentParser(description="logue: simple terminal logbook with git")
    parser.add_argument("--search", metavar="YYYY_MM_DD", help="Search entries by date")
    parser.add_argument("--search-tag", metavar="TAG", help="Search entries by tag (without #)")
    args = parser.parse_args()

    if args.search:
        search_by_date(args.search)
        return
    if args.search_tag:
        search_by_tag(args.search_tag)
        return

    curses.wrapper(interactive_mode)


if __name__ == "__main__":
    main()
