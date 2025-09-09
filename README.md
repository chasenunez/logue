# logue
### A lightweight terminal logbook with Git integration.

`logue` is a minimal, curses-based logbook that lets you quickly capture notes in your terminal.  
Each entry is timestamped, tagged automatically, and stored in JSON format.  
All logs are committed and pushed to your Git repository, so your journal is version-controlled and backed up.

## Features

- Terminal UI with a simple, distraction-free design.  
- Current entry editor with arrow key navigation and editing.  
- Automatic wrapping of text without breaking words.  
- Tag extraction — write `#tags` directly in your entry, they will be saved separately in JSON.  
- Search support by date (`--search`) or by tag (`--search-tag`).  
- Git integration — entries are auto-committed and pushed.  
- Location tracking — when you start `logue`, it asks for your location and saves it alongside entries.  
- Daily view — shows only entries from the current day.  
- Custom terminal title ("logue").  

## Installation

1. Clone this repository:

```bash
git clone https://github.com/<your-username>/logue.git
cd logue
````

2. Make the script executable:

```bash
chmod +x logue.py
```

3. (Optional) Create a shortcut so you can just type `logue` into the terminal:

```bash
mkdir -p ~/bin
ln -s "$(pwd)/logue.py" ~/bin/logue
```

4. Add `~/bin` to your `PATH` if not already present. For zsh:

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Now you can run:

```bash
logue
```

## Usage

### Start logging

```bash
logue
```

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

Make sure your repository’s remote URL includes a personal access token if you want seamless pushes:

```bash
git remote set-url origin https://<USERNAME>:<TOKEN>@github.com/<USERNAME>/<REPO>.git
```

---

## License

MIT License. See `LICENSE` for details.
