# Raspberry Pi bot setup (from step 5)

Corrected against this repo. ChatGPT’s steps were wrong about `.env`, bare `main.py`, and inventing a systemd unit from scratch.

**Important differences from ChatGPT**

- Secrets go in **`config.json`**, not a `.env` file.
- Pi entry point is **`python main.py --bot`** (plain `main.py` opens the Tk desktop UI).
- Use the shipped unit: `deploy/discord-bot.service` (edit User / paths / venv).
- `credentials.json` is only needed for Google Sheets / `--live`. The Discord slash bot mainly needs `discord.bot_token` in `config.json`.

`config.json` is git-ignored. Your filled-in copy lives on Windows at `C:\Repos\DiscordBot\config.json` and must be copied to the Pi.

Assume:

- Pi user: `cody`
- Host: `CodysDiscordBot.local`
- Clone path: `~/CoDyce-bot`
- Venv: `venv`

---

## 5. Configure secrets on the Pi

On the Pi:

```bash
cd ~/CoDyce-bot
pwd
ls -la
```

### Option A — copy your Windows `config.json` (recommended)

From **Windows PowerShell** (not the Pi SSH session).

**Do not use a `C:\...` path with `scp` on Windows.** OpenSSH treats the `C:` as a remote hostname, which causes:

`ssh: Could not resolve hostname c: Name or service not known`

Use forward slashes, or `cd` into the folder first:

```powershell
cd C:\Repos\DiscordBot
scp ./config.json cody@CodysDiscordBot.local:~/CoDyce-bot/config.json
```

Or:

```powershell
scp C:/Repos/DiscordBot/config.json cody@CodysDiscordBot.local:~/CoDyce-bot/config.json
```

Then on the Pi:

```bash
chmod 600 config.json
```

### If `scp` still fails

Common causes and fixes:

1. **Wrong remote folder name**  
   Confirm the clone path on the Pi (`pwd` / `ls`). If the folder is not `CoDyce-bot`, change the remote path.

2. **`.local` mDNS name does not resolve from Windows**  
   Try the Pi’s IP instead:

   ```powershell
   cd C:\Repos\DiscordBot
   scp ./config.json cody@<PI_IP>:~/CoDyce-bot/config.json
   ```

   On the Pi, get the IP with: `hostname -I`

3. **OpenSSH / permission prompt**  
   Accept the host key if asked; enter the Pi password when prompted (characters will not echo).

4. **Fallback: pipe through SSH** (avoids `scp` path quirks):

   ```powershell
   Get-Content C:\Repos\DiscordBot\config.json -Raw | ssh cody@CodysDiscordBot.local "cat > ~/CoDyce-bot/config.json && chmod 600 ~/CoDyce-bot/config.json"
   ```

5. **Fallback: paste via nano**  
   On the Pi:

   ```bash
   cp config.example.json config.json
   chmod 600 config.json
   nano config.json
   ```

   Paste values from your Windows `config.json` (at least `discord.bot_token` and `discord.guild_ids`).

### Google credentials (optional for `--bot`)

Only needed later for Sheets / `--live`. Place `credentials.json` next to `main.py` and `chmod 600` it. Skip for Discord slash-command bot only.

---

## 6. Test the bot manually

```bash
cd ~/CoDyce-bot
source venv/bin/activate
python main.py --bot
```

Or:

```bash
./start-bot.sh
```

Check:

- No config/token errors
- Bot shows online in Discord
- `/hat` (and `/hit` if enabled) work in a server listed in `guild_ids`

Stop with **Ctrl+C**.

Tip: `systemctl status` opens a pager — press `q` to exit back to the shell.

---

## 7. systemd auto-start

```bash
sudo cp ~/CoDyce-bot/deploy/discord-bot.service /etc/systemd/system/discord-bot.service
sudo nano /etc/systemd/system/discord-bot.service
```

Use:

```ini
[Unit]
Description=Discord skill-tracker / hat bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cody
Group=cody
WorkingDirectory=/home/cody/CoDyce-bot
ExecStart=/home/cody/CoDyce-bot/venv/bin/python main.py --bot --log-level INFO
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now discord-bot
sudo systemctl status discord-bot
```

(Press `q` to leave the status view.)

Logs:

```bash
journalctl -u discord-bot -f
```

File logs also go to `~/CoDyce-bot/logs/bot.log`.

---

## 8. Updating later

See `HowToUpdate.txt` in the repo root for a short copy of these commands.

```bash
cd ~/CoDyce-bot
git pull
sudo systemctl restart discord-bot
```

If dependencies change:

```bash
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart discord-bot
```
