# logue
### A lightweight terminal logbook with Git integration.

`logue` is a minimal, curses-based terminal logbook that lets you quickly capture tasks.  
Each entry is timestamped, tagged automatically, and stored in JSON format.  
All logs are committed and pushed to your Git repository, so your journal is version-controlled and backed up.

## Features

- Tag extraction — write `#tags` directly in your entry, they will be saved separately in JSON.
- Task-fixing for the next day - write `*task you would like to show up tomorrow` in the entry box, and they will be saved separately int he JSON, and appear the following day under "Tasks for today".  
- Search support by date (`--search`) or by tag (`--search-tag`).  
- Git integration — entries are auto-committed and pushed.  
- Location tracking — when you start `logue`, it asks for your location and saves it alongside entries.  

## Installation

1. Clone this repository:

```bash
git clone https://gitlab.eawag.ch/chase.nunez/logue.git
cd logue
````

2. Make the script executable:

```bash
chmod +x logue.py
```

3. Create a shortcut so you can just type `logue` into the terminal (instead of invoking python3):

```bash
mkdir -p ~/bin
ln -s "$(pwd)/logue.py" ~/bin/logue
```

4. Add `~/bin` to your `PATH` if not already present. For zsh (the mac shell) that looks like:

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Now you can run to following from the terminal to begin logging:

```bash
logue
```

### Start logging


* Use arrow keys to navigate and edit your current entry.
* Press Enter to save the entry.
* Entries are timestamped and saved in `logue.json`.
* On save, your entry is committed and pushed to Git.

### Search by date

```bash
logue --search 2025_09_08
```

### Search by tag

```bash
logue --search-tag projectx
```

## Data format

All logs are stored in `logue.json` (Git-tracked). Example:

```json
[
  {
    "timestamp": "2025_09_08_11_04_23",
    "text": "example log entry text",
    "tags": ["projectx"],
    "location": "Zurich"
  }
]
```

## GitHub Integration


It is goof practice not to have your log file in the same directory as the program file (if the program file is visible on github). But you can save your log.json file in a separate repo with minimal fiddling in `logue.py`
```python3
# ---------------- Paths ----------------
# Program can be anywhere
SCRIPT_DIR = Path(__file__).resolve().parent

# log_cold_storage directory
COLD_STORAGE_DIR = Path.home() / "Documents" / "log_cold_storage"
COLD_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = COLD_STORAGE_DIR / "logue.json"

# Repository URL (used only if git remote isn't set)
COLD_REPO_URL = "<URL_FOR_YOUR_COLD_STORAGE_REPO>"

```
Make sure your repository’s remote URL includes a personal access token if you want seamless pushes:
```bash
git remote set-url origin https://<USERNAME>:<TOKEN>@github.com/<USERNAME>/<COLD_STORAGE_REPO>.git
```

## Dev ideas
- I would like to transition this to Rust, and also add a few features (access to past logs in window, more advanced text editing using nvim, editable content IRL)

## License

MIT License. See `LICENSE` for details.
