# YouTube Shorts generator

A Python project that makes one original vertical Short per run with Gemini, Edge TTS, Pexels footage, phrase captions, and optional local music. It can require human approval before any upload. The software uses free APIs/tools; free-tier limits and YouTube's API policies still apply.

## What you need

- Python 3.10 or newer.
- FFmpeg available on your computer (`ffmpeg -version`). MoviePy uses it to encode MP4. On Windows, install FFmpeg (for example, with `winget install Gyan.FFmpeg.Shared`) and reopen the terminal after adding it to `PATH`.
- A free Gemini API key and a free Pexels API key.
- For uploads, a Google Cloud OAuth desktop-app client and a YouTube channel.
- An internet connection for the APIs and Edge TTS.

## 1. Install

Open a terminal in this `youtube-shorts` folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

On macOS/Linux, activate the environment with `source .venv/bin/activate` instead.

## 2. Get a Gemini API key

1. Open [Google AI Studio](https://aistudio.google.com/).
2. Sign in and create an API key.
3. Put it in `.env` as `GEMINI_API_KEY=your_key`.
4. Choose a model available to your account in `config.yaml` under `gemini.model`. Model availability and free quotas can change.

The app uses Gemini's REST API and requests JSON responses. No paid SDK or model is required.

## 3. Get a Pexels API key

1. Create a free account at [Pexels](https://www.pexels.com/).
2. Request an API key from [Pexels API](https://www.pexels.com/api/).
3. Put it in `.env` as `PEXELS_API_KEY=your_key`.

Pexels' API has rate limits. The app tracks downloaded clip IDs in `used_clip_ids.json` and will fail clearly rather than reuse a clip when it cannot find enough unused portrait footage.

## 4. Configure your niche and review settings

Edit `config.yaml`:

- `niche`: the subject area for topics and scripts.
- `review_mode: true`: generates into `pending/<id>/` without uploading. Set to `false` for automatic uploads.
- `privacy_status: public`: generated uploads are public. Use `private` or `unlisted` if you prefer.
- `voice.voices`: Edge TTS voices are selected in rotation.
- `music.enabled`: set `false` to disable local music. Otherwise, add royalty-free audio you are permitted to use to `music/`; its volume defaults to 10%.

The output is 1080x1920 at 30 fps. Scripts target 45-60 spoken words and 20-25 seconds, starting with the specific result in the opening line. Narration outside the configured duration stops with an actionable error if it cannot be corrected naturally.

Titles and descriptions are generated around each video's actual topic, search phrases, and beginner takeaway. Uploads include up to three relevant description hashtags, including `#Shorts`; on-screen captions display in short, readable phrase cards rather than flashing one word at a time. Tool-demo scripts lead with the outcome and keep to one tool and one result.

## 5. Google Cloud OAuth setup (uploads only)

1. In [Google Cloud Console](https://console.cloud.google.com/), create/select a project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen. Add your own Google account as a test user if the app is in testing.
3. Create an OAuth client ID with application type **Desktop app** and download its JSON.
4. Save it as `credentials/client_secret.json` (or set `YOUTUBE_OAUTH_CLIENT_FILE` in `.env` to another path).
5. Keep the downloaded client JSON and `token.json` private. Do not commit either file.

The first upload opens a browser to authorize the app. The resulting `token.json` is saved locally and refreshed when possible. Revoke access or delete the token to make the app ask for authorization again.

YouTube uploads use category 27, `selfDeclaredMadeForKids: false`, configured privacy, and the `containsSyntheticMedia` disclosure field to identify the AI-generated narration. The YouTube API may reject fields not enabled for your project; the app reports the API error. **Public uploads from new or unverified API projects may remain private until the project passes YouTube's API compliance audit.** The disclosure flag does not replace YouTube's own altered/synthetic-content requirements.

## 6. Generate and review

```powershell
python main.py --dry-run
```

This builds the video and skips the upload, regardless of `review_mode`. The result is saved under `output/dry-run/`; no Google OAuth is needed. Generation still requires working Gemini and Pexels keys and consumes a unique topic and footage IDs.

For normal review-mode generation:

```powershell
python main.py
```

Read the script and watch `pending/<id>/final.mp4`. Approve that exact item to upload:

```powershell
python approve.py <id>
```

No upload happens before approval when `review_mode: true`. If you set `review_mode: false`, `python main.py` uploads automatically (after the first OAuth login). Uploads are private by default; verify `privacy_status` before changing this behavior. Each successful upload increments the local daily counter, capped at six per day. The counter resets at local midnight; do not run simultaneous uploads.

Generated topics are recorded in `topics.json`, run metadata in `history.json`, and failures in `runs.log`. Do not delete these state files if you want duplicate-topic, clip-reuse, and quota tracking to persist.

## 7. Run daily with GitHub Actions

GitHub discovers workflow files in the repository root `.github/workflows/` directory. The workflow at `.github/workflows/daily.yml` in this project is ready to run when this folder is the repository root; it runs daily and supports manual runs. If you keep this project inside a larger repository instead, use that repository's root `.github/workflows/daily.yml` and update its working-directory paths. To set up the standalone project:

1. Open **Settings → Secrets and variables → Actions** in GitHub.
2. Add repository secrets `GEMINI_API_KEY` and `PEXELS_API_KEY`.
3. For automatic uploads, set `review_mode: false` and choose the desired `privacy_status` in `config.yaml`.
4. Complete OAuth locally with YouTube upload and management permissions. Add the base64-encoded downloaded client JSON as `YOUTUBE_OAUTH_CLIENT_JSON_B64` and the authorized `token.json` as `YOUTUBE_TOKEN_JSON_B64`. The workflow writes both files privately before running. Only store these secrets in a trusted repository, and rotate/revoke them if exposed.
5. Enable Actions for the repository. The scheduled workflow runs daily at 14:30 UTC (19:30 Pakistan time) and uploads automatically. Use **Actions → Daily YouTube Short → Run workflow** to test manually.

The workflow commits topic, voice, history, and quota state so later scheduled runs can avoid repeats and enforce the daily limit. Keep `GITHUB_TOKEN`'s repository contents permission enabled. GitHub Actions has usage limits; check the free allowance for your repository.

## 8. Schedule runs on your own computer instead

On Windows, open **Task Scheduler → Create Basic Task**, choose a daily trigger, and set the action to start a program. Use the full path to this project's `.venv\Scripts\python.exe` for **Program/script**, `main.py` for **Add arguments**, and this project's folder for **Start in**. Leave your API keys in `.env`; do not put them in the task's arguments. Local runs in review mode create pending videos for you to inspect and approve.

On macOS/Linux, open your crontab with `crontab -e` and add a line using the full project path:

```cron
17 15 * * * cd /path/to/youtube-shorts && .venv/bin/python main.py >> cron.log 2>&1
```

Cron uses the machine's local timezone; make sure the `.venv` exists and the process can read `.env` and write project state. Avoid scheduling overlapping runs.

## Files and privacy

- `main.py`, `approve.py`: generation and explicit approval entry points.
- `script_gen.py`, `voice.py`, `footage.py`, `video.py`, `uploader.py`: pipeline modules.
- `config.yaml`: niche, models, voice, review, privacy, and output configuration.
- `.env`, OAuth files, generated audio/video, and local music are ignored by Git.

Use only footage and music that you have permission to publish. Review factual accuracy, copyright, and platform policies before approving a video.
