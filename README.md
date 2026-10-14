# ChecklistApp

An offline Windows desktop checklist app using Python 3.12+, PySide6, and SQLite. No accounts, internet APIs, or database server are needed. Installation downloads dependencies; normal use is offline.

## Run on Windows 10 or 11

1. Install Python 3.12 or newer from python.org. Enable **Add Python to PATH** in the installer.
2. Download or clone this repository, then open PowerShell in the project folder.
3. Run these commands, one line at a time:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m checklist_app
```

If you have a newer Python version, replace `py -3.12` with its version, such as `py -3.13`. You do not need to activate the virtual environment. The `.venv` folder holds the app's dependencies separately from other Python projects.

## Using the app

The first launch creates five empty checklists: Daily Routine, Weekly Goals, Weekly Cleaning, Shopping List, and Projects. Add your own tasks using **Add task**. Select a checklist in the sidebar; check a task to complete it. Double-click to edit its title, description, priority, or optional due date (`YYYY-MM-DD`). Completed tasks have a strikethrough.

Create, rename, change type, duplicate, or delete checklists using the sidebar buttons. Use the up/down buttons to reorder checklists within their category. Drag tasks to reorder them while showing all tasks with no search and with “move completed tasks to bottom” disabled. Search includes descriptions; filters show complete or incomplete tasks. Progress always reflects the entire checklist, even while filtering.

Settings include dark/light appearance, completed tasks at the bottom, remembering the selected checklist, and confirmation of destructive actions. Window size and position are saved automatically. Deleting a checklist, deleting tasks, and clearing completed tasks are permanent: create a backup first if you may need them later. Confirmation is enabled by default.

Subtasks are an optional future feature and are not included in this version.

## Resets and local data

- **Normal:** never automatically resets.
- **Daily:** resets at 6:00 AM local computer time.
- **Weekly:** resets Monday at 6:00 AM local computer time.

The original request also mentioned weekly midnight in two examples/test requirements. This implementation consistently uses Monday **6:00 AM**, matching the main scheduling specification.

A one-second timer checks while the app is open; startup handles missed periods. Only completion flags change, never task identity, content, or order. Calendar period keys are stored in SQLite. Transactions protect resets, and a backward clock change does not repeat a previously processed period. A forward clock change into a new period causes a reset; changing the clock back waits until the stored period is surpassed. Calendar calculations use local wall time rather than assuming every day has exactly 24 hours, accommodating daylight saving transitions.

On Windows your actual database is:

```text
%LOCALAPPDATA%\ChecklistApp\checklists.db
```

Paste `%LOCALAPPDATA%\ChecklistApp` into File Explorer's address bar to find it. It is outside this repository and remains when you update the app or replace the executable. Startup creates missing tables without clearing existing data, uses a schema version, and refuses databases made by a newer incompatible version. Future schema changes must be implemented as migrations, with a backup before migration.

**Back up database** makes a consistent SQLite copy and refuses to overwrite an existing file. Pick a new filename. To restore: close every app instance, first preserve the current database under another name, then copy a known-good backup into the data folder as `checklists.db`. Do not restore over your only copy of personal data. The app never restores or deletes databases automatically.

For Linux development the default path is `~/.local/share/ChecklistApp/checklists.db`. Automated tests use temporary databases inside the project, never your personal database. All application settings live in SQLite.

## Test

From PowerShell in the project folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite tests database persistence, daily and weekly boundaries, missed resets, first creation, normal checklist isolation, content preservation, duplicate-reset prevention, clock rollback, backup safety, CRUD, ordering, atomic rollback, and GUI completion/search/filter/live reset. GUI tests use Qt's offscreen platform and do not touch your real database.

For a manual Windows check: create a checklist of each type, add/edit tasks with descriptions and due dates, check tasks, search/filter, reorder tasks, restart, and confirm data/settings persist. Make a backup and verify the file exists. Do not change the system clock to test resets; automated tests inject a clock safely.

## Build a standalone Windows executable

Build on Windows after installing dependencies above:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The execution-policy setting applies only to this invocation. Output is `dist\ChecklistApp.exe`. Copy that executable to the target Windows 10/11 computer; Python is not needed there. Build on the same architecture as the target computer. Launch it on Windows to verify it before distributing. PyInstaller bundles Python and Qt; the user database is never bundled. No Windows executable has been built or validated in the Linux cloud workspace.

## Troubleshooting

- **Python was not found:** install Python, reopen PowerShell, and try `py --version`.
- **No module named PySide6:** use the `.venv\Scripts\python.exe` commands above and install requirements with that same interpreter.
- **Invalid due date:** enter a real date such as `2026-10-30`, or leave the field empty.
- **Database is locked:** close other app instances or database editing tools and retry. The app waits up to five seconds before reporting a lock.
- **Cannot open database / permission denied:** check that your Windows user can write to Local AppData. Preserve your database; deleting it is not a troubleshooting step.
- **Newer database version:** use the newer app version that created it. Do not edit its schema version manually.
- **Build failed:** read the first error above the final message. Verify dependency installation and that the command is running on Windows.

## Development structure

`checklist_app/database.py` owns storage, transactions, settings, and backup. `scheduling.py` provides testable local calendar calculations. `gui.py` contains the Qt interface and timer. `__main__.py` starts the app. `windows_entry.py` is the packaging entry point. Dependencies are pinned in `requirements.txt`; caches, virtual environments, local databases/backups, and sensitive configuration files are excluded by `.gitignore`.
