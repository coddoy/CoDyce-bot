# Skill Tracker — Local Discord + Google Sheets Control Panel

A small local Python desktop app for incrementing player skill values
that live in Google Sheets and posting a notification to a Discord
channel each time a value changes.

* Each player has their own Google Sheet **and** their own Discord webhook.
* All player sheets share the same template, so skill cell locations
  (e.g. `Strength = B2`) are configured once.
* No web server, no hosting. Just `python main.py`.

## Project layout

```
main.py                # entry point
config.example.json    # copy to config.json and fill in
requirements.txt
app/
  config.py            # JSON config loader + dataclasses
  sheets.py            # gspread wrapper with per-player cache
  discord_notify.py    # webhook POST helper
  logic.py             # AppService — wires it all together
  ui.py                # Tkinter window (uses ttkbootstrap if installed)
```

## Setup

### 1. Python deps

```bash
python -m pip install -r requirements.txt
```

Requires Python 3.10+. `ttkbootstrap` is optional; the UI falls back
to plain `ttk` if it isn't installed.

### 2. Google Sheets service account

1. Create a project at <https://console.cloud.google.com/>.
2. Enable the **Google Sheets API** and the **Google Drive API**.
3. *APIs & Services → Credentials → Create Credentials → Service account*.
4. Open the new service account, *Keys → Add Key → JSON*. A JSON file
   downloads — save it next to `main.py` as `credentials.json` (or
   point `google.credentials_file` in `config.json` somewhere else).
5. Open each player's sheet, click **Share**, paste the service
   account's `client_email` (from the JSON), give it **Editor**.

### 3. Discord webhooks

For each player's destination channel:
*Channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL.*

### 4. Config file

```bash
cp config.example.json config.json
```

Fill in the spreadsheet IDs (the long string between `/d/` and `/edit`
in the sheet URL) and webhook URLs. Edit the `sheet_template.skills`
mapping to match your sheet — keys are skill names, values are A1-style
cell addresses (e.g. `B2`).

`config.json` and `credentials.json` are both git-ignored.

## Run

```bash
python main.py
```

By default the app starts in **demo mode**: a built-in 2-character /
3-skill config, an in-memory fake sheets backend, and a no-op Discord
notifier. The activity log shows the message that *would* have been
posted to Discord, but no Google Sheets reads/writes or HTTP calls
happen. This lets you click around the UI before any credentials are
configured.

Useful flags:

```bash
python main.py                      # demo mode (default)
python main.py --config foo.json    # demo mode with a custom config file
python main.py --live               # real Sheets + Discord (requires config.json)
python main.py --log-level DEBUG    # verbose logging
```

## Sheet schema

Every player's sheet is assumed to look the same:

| | A | B |
|-|-|-|
|2| Strength | 5 |
|3| Dexterity | 3 |
|4| Constitution | 4 |
|...| | |

`config.sheet_template.skills` says which cell holds each skill's
value. Add or remove rows in your sheet and update the config to match.

## How it works

1. On launch, `config.json` is loaded and validated.
2. When you select a player, the app calls `worksheet.batch_get(...)`
   once to read every skill cell in a single API call. Values are
   cached in memory until you click **Refresh** (or restart).
3. When you click **Apply**, the app:
   - writes the new value to the single skill cell with `update_acell`,
   - updates the local cache,
   - POSTs `+Δ Skill for Player` to that player's webhook.
4. If the sheet write fails the Discord post is skipped. If the
   Discord post fails *after* a successful sheet write the activity log
   warns you so you can resend manually.

## Status

The project skeleton is in place. The default `python main.py` runs
the offline demo so the UI can be iterated on without any Google or
Discord setup. Live integration (`--live`) is wired up and should work
once the service account JSON and webhook URLs are in place, but is
intentionally not the default while the project is still being built
out.
