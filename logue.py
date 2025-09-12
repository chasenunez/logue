#!/usr/bin/env python3
"""
logue.py – Terminal logbook with Git integration.

This is a patched version that fixes several issues found in the prior copy:
 - Fix incorrect indentation and stray `except` in the header/logo block.
 - Use the correct date variable when printing the header.
 - Make the entry box draw solidly (no right-side gap) where possible.
 - Make startup location prompt robust to ESC/cancel (don't call .strip() on None).
 - Fix typing for helper that returns both tasks and cleaned text.
 - General minor robustness: bounds-checked curses drawing, silent git calls,
   and safe handling of narrow terminals.
 - Keeps the user's current features: tags with '#', tasks for tomorrow using '*',
   tasks persisted under "tasks" keyed by YYYY_MM_DD, entries under "entries".
"""

import argparse
import curses
import datetime
import json
import sys
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# ------------ Config ------------
TASKS_GAP = 1  # blank lines between today's tasks and tomorrow's header

# ---------------- Paths ----------------
# Program can be anywhere
SCRIPT_DIR = Path(__file__).resolve().parent

# log_cold_storage directory
COLD_STORAGE_DIR = Path.home() / "Documents" / "log_cold_storage"
COLD_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = COLD_STORAGE_DIR / "logue.json"

# Repository URL (used only if git remote isn't set)
COLD_REPO_URL = "https://github.com/chasenunez/log_cold_storage.git"

# ------------ Data storage ------------
def load_data() -> dict:
    if not LOGFILE.exists():
        return {"entries": [], "tasks": {}}
    try:
        with LOGFILE.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            return {"entries": obj.get("entries", []), "tasks": obj.get("tasks", {})}
        return {"entries": [], "tasks": {}}
    except Exception as e:
        print(f"[ERROR] Failed to load log file: {e}", file=sys.stderr)
        return {"entries": [], "tasks": {}}

def save_data(data: dict) -> None:
    with LOGFILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    git_commit_and_push()



# ------------ Git (silent) ------------
def git_commit_and_push() -> None:
    """
    Commit and push logue.json to the cold storage repo.
    Assumes that the repo has been cloned and the remote origin set to COLD_REPO_URL.
    """
    import subprocess
    import sys

    try:
        # Ensure we are in the cold storage repo
        subprocess.run(["git", "init"], cwd=COLD_STORAGE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Ensure remote origin exists
        remotes = subprocess.run(["git", "remote"], cwd=COLD_STORAGE_DIR, capture_output=True, text=True)
        if "origin" not in remotes.stdout:
            subprocess.run(["git", "remote", "add", "origin", COLD_REPO_URL], cwd=COLD_STORAGE_DIR)

        # Add and commit the file
        subprocess.run(
            ["git", "add", str(LOGFILE.name)],
            check=True,
            cwd=COLD_STORAGE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "commit", "-m", "logue: update"],
            check=True,
            cwd=COLD_STORAGE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],  # or "master" depending on your repo default branch
            check=True,
            cwd=COLD_STORAGE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Git operation failed: {e}", file=sys.stderr)
        print(
            "If authentication fails, ensure the remote repo exists and credentials are set.\n"
            f"Remote URL: {COLD_REPO_URL}",
            file=sys.stderr,
        )



# ------------ Helpers ------------
def extract_tags(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"#(\w+)", text)]


def extract_tasks_and_clean_text(text: str) -> Tuple[List[str], str]:
    """
    Extract tasks denoted by leading '*' and return (tasks, cleaned_text).
    Cleans removed task lines and any now-empty lines.
    """
    tasks = re.findall(r"\*\s*([^\n\r]+)", text)
    cleaned = re.sub(r"\*\s*[^\n\r]+", "", text)
    # Remove empty lines and trailing spaces from cleaned text
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
    """
    Single-line editor:
      - Left/Right arrow navigation
      - Backspace/delete
      - Horizontal scrolling if text longer than visible width
      - Enter -> return the string
      - ESC -> return None (cancel)
    """
    buffer: List[str] = []
    cursor_pos = 0
    scroll = 0
    visible = max(1, max_width)

    while True:
        if cursor_pos < scroll:
            scroll = cursor_pos
        elif cursor_pos > scroll + visible - 1:
            scroll = cursor_pos - (visible - 1)

        view = "".join(buffer)[scroll : scroll + visible]

        try:
            stdscr.move(y, x)
            stdscr.clrtoeol()
            stdscr.addstr(y, x, view)
        except curses.error:
            # If we can't draw (very small terminal), just ignore draw errors
            pass

        cursor_col = x + max(0, cursor_pos - scroll)
        max_y, max_x = stdscr.getmaxyx()
        cursor_col = min(cursor_col, max_x - 1)
        try:
            stdscr.move(y, cursor_col)
        except curses.error:
            # fallback to nearest valid position
            try:
                stdscr.move(max(0, min(max_y - 1, y)), max(0, cursor_col))
            except curses.error:
                pass

        ch = stdscr.getch()

        if ch in (10, 13):  # Enter
            return "".join(buffer).strip()
        elif ch == 27:  # ESC
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


# ------------ Main UI ------------
def interactive_mode(stdscr) -> None:
    # Set terminal/tab title
    try:
        sys.stdout.write("\x1b]2;logue\x07")
        sys.stdout.flush()
    except Exception:
        pass

    curses.cbreak()
    curses.noecho()
    stdscr.keypad(True)

    # Colors and attributes:
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)    # tasks today
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # tasks tomorrow
        curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)   # entries
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)   # header/label/input

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
        tasks_today_attr = tasks_today_title_attr = curses.A_BOLD
        tasks_tomorrow_attr = tasks_tomorrow_title_attr = curses.A_BOLD
        entries_attr = entries_title_attr = curses.A_BOLD
        header_attr = label_attr = input_attr = curses.A_NORMAL

    # Load data
    data = load_data()
    entries: List[Dict[str, Any]] = data.get("entries", [])
    # tasks_map will be re-read each loop from data to reflect updates
    # Startup location prompt
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    logo_lines = [
        "╻  ┏━┓┏━╸╻ ╻┏━╸",
        "┃  ┃ ┃┃╺┓┃ ┃┣╸ ",
        "┗━╸┗━┛┗━┛┗━┛┗━╸",
    ]
    for i, line in enumerate(logo_lines):
        try:
            stdscr.addstr(i + 1, max(0, (width - len(line)) // 2), line, header_attr)
        except curses.error:
            # ignore if terminal too narrow
            pass

    prompt_loc = "enter location: "
    prompt_row = len(logo_lines) + 3
    prompt_col = max(2, (width - len(prompt_loc)) // 2)
    try:
        stdscr.addstr(prompt_row, prompt_col, prompt_loc, label_attr)
    except curses.error:
        pass
    stdscr.refresh()

    loc_in = get_singleline_input(stdscr, prompt_row, prompt_col + len(prompt_loc), max(8, width - (prompt_col + len(prompt_loc)) - 2))
    if loc_in is None:
        location = ""
    else:
        location = loc_in.strip()

    location_tags: List[str] = []
    if location:
        raw = location.lower()
        underscore = raw.replace(" ", "_")
        location_tags = [raw] if raw == underscore else [raw, underscore]

    # Date strings
    today_date = datetime.date.today()
    today_str = today_date.strftime("%Y_%m_%d")
    tomorrow_date = today_date + datetime.timedelta(days=1)
    tomorrow_str = tomorrow_date.strftime("%Y_%m_%d")
    date_str_pretty = f"{today_date.strftime('%B')} {ordinal(today_date.day)} {today_date.year}"

    # Main loop
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        left = 2
        right = 2

        # Header block: logo left, date+location right
        header_height = len(logo_lines)
        for i, line in enumerate(logo_lines):
            try:
                stdscr.addstr(i, left, line, header_attr)
            except curses.error:
                pass

        date_line = date_str_pretty
        if location:
            date_line += f"  {location}"
        try:
            # print date_line on the top-right, try first row then second if collision
            stdscr.addstr(0, max(0, width - len(date_line) - 2), date_line, header_attr)
        except curses.error:
            try:
                stdscr.addstr(1, max(0, width - len(date_line) - 2), date_line, header_attr)
            except curses.error:
                pass

        # Entry box (white)
        box_top = header_height + 1
        box_left = left
        box_width = max(30, width - left - right)
        box_height = 3
        try:
            stdscr.addch(box_top, box_left, curses.ACS_ULCORNER)
            stdscr.hline(box_top, box_left + 1, curses.ACS_HLINE, max(0, box_width - 2))
            stdscr.addch(box_top, box_left + box_width - 1, curses.ACS_URCORNER)
            stdscr.vline(box_top + 1, box_left, curses.ACS_VLINE, max(0, box_height - 2))
            stdscr.vline(box_top + 1, box_left + box_width - 1, curses.ACS_VLINE, max(0, box_height - 2))
            stdscr.addch(box_top + box_height - 1, box_left, curses.ACS_LLCORNER)
            stdscr.hline(box_top + box_height - 1, box_left + 1, curses.ACS_HLINE, max(0, box_width - 2))
            stdscr.addch(box_top + box_height - 1, box_left + box_width - 1, curses.ACS_LRCORNER)
        except curses.error:
            # If ACS_* drawing fails, ignore — terminal might not support it or be too small
            pass

        prompt_text = "Entry: "
        entry_y = box_top + 1
        prompt_x = box_left + 2
        entry_x = prompt_x + len(prompt_text)
        try:
            stdscr.addstr(box_top + 1, prompt_x, prompt_text, label_attr)
        except curses.error:
            pass
        entry_visible_width = max(10, box_left + box_width - entry_x - 2)

        # Tasks and entries sections
        tasks_top = box_top + box_height + 1
        current_line = tasks_top

        data = load_data()  # reload so any external edits are visible
        entries = data.get("entries", [])
        tasks_map = data.get("tasks", {})

        # Tasks for today
        if current_line < height - 1:
            try:
                stdscr.addstr(current_line, left, "  Tasks for today:", tasks_today_title_attr)
            except curses.error:
                pass
        current_line += 1
        todays_tasks = tasks_for_date(tasks_map, today_str)
        for t in todays_tasks:
            if current_line < height - 1:
                try:
                    stdscr.addstr(current_line, left + 4, f"- {t}", tasks_today_attr)
                except curses.error:
                    pass
                current_line += 1
            else:
                break

        # vertical gap
        for _ in range(TASKS_GAP):
            if current_line < height - 1:
                current_line += 1

        # Tasks for tomorrow
        if current_line < height - 1:
            try:
                stdscr.addstr(current_line, left, "  Tasks for tomorrow:", tasks_tomorrow_title_attr)
            except curses.error:
                pass
            current_line += 1

        tom_tasks = tasks_for_date(tasks_map, tomorrow_str)
        for t in tom_tasks:
            if current_line < height - 1:
                try:
                    stdscr.addstr(current_line, left + 4, f"- {t}", tasks_tomorrow_attr)
                except curses.error:
                    pass
                current_line += 1
            else:
                break

        # spacer before entries
        if current_line < height - 1:
            current_line += 1

        # Today's entries
        entries_start = current_line
        if entries_start < height - 1:
            try:
                stdscr.addstr(entries_start, left, "  Today's entries:", entries_title_attr)
            except curses.error:
                pass
        line = entries_start + 1
        box_height_logs = max(0, height - line - 1)

        session_entries = [
            e
            for e in entries
            if e.get("timestamp", "").startswith(today_str) and str(e.get("text", "")).strip() != ""
        ]

        for entry in reversed(session_entries[-(box_height_logs - 1) :]):
            if line >= height - 1:
                break
            try:
                ts = datetime.datetime.strptime(entry["timestamp"], "%Y_%m_%d_%H_%M_%S")
                time_str = ts.strftime("%H:%M")
            except Exception:
                time_str = entry.get("timestamp", "")[-8:-3]
            # time (bold + color)
            try:
                stdscr.addstr(line, left + 4, f"{time_str}", entries_attr | curses.A_BOLD)
            except curses.error:
                pass
            display = f" - {entry.get('text','')}"
            wrap_width = max(10, width - (left + 14))
            for wl in textwrap.wrap(display, wrap_width):
                if line < height - 1:
                    try:
                        stdscr.addstr(line, left + 12, wl, entries_attr)
                    except curses.error:
                        pass
                    line += 1
                else:
                    break
            if line < height - 1:
                line += 1

        # status/help line (dim)
        help_line = "Enter = submit entry | ESC = quit"
        try:
            stdscr.addstr(max(0, height - 1), 2, help_line[: max(0, width - 4)], curses.A_DIM)
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
            # ignore empty entries (do not save nor push)
            continue

        # Extract tasks and cleaned note
        tasks, cleaned_note = extract_tasks_and_clean_text(note)

        now_exact = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        tags = extract_tags(note)
        for lt in location_tags:
            if lt not in tags:
                tags.append(lt)

        new_entry = {"timestamp": now_exact, "text": cleaned_note, "tags": tags, "location": location}
        entries.append(new_entry)
        data["entries"] = entries

        # If tasks found, add them to tomorrow
        if tasks:
            tasks_map = data.get("tasks", {})
            for t in tasks:
                add_task_for_date(tasks_map, tomorrow_str, t)
            data["tasks"] = tasks_map

        save_data(data)
        # Try to commit & push; keep UI quiet by running it in background for responsiveness is an option,
        # but for now we run it synchronously but silent to stdout/stderr.
        git_commit_and_push()


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
