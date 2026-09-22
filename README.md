# Chessmate AI

Chessmate AI is a Flask-based chess coaching and analysis web app. It combines a local Stockfish engine with an OpenAI-powered coach to help players analyze moves, get tactical guidance, and play against an adjustable AI opponent.

## Features

- Interactive chess board powered by `chessboard.js` and `chess.js`
- Move validation and engine evaluation via `python-chess`
- AI coach explanations and analysis using OpenAI chat completions
- Play against Stockfish at configurable ELO-style difficulty levels
- Save and load games with PGN/position persistence
- Load PGN files and replay game history
- Move explanation, best move suggestion, and coach question handling

## Requirements

- Python 3.10+ (recommended)
- `venv` or another virtual environment tool
- Local Stockfish binary in `engines/stockfish`
- OpenAI API key

## Installation

1. Clone the repository.
2. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root, then replace the API-key placeholder with your own OpenAI API key. The repository does not include this file because it is excluded by `.gitignore`. Do not commit the file or share the key.

Example `.env`:

```env
# Required: replace the placeholder with your OpenAI API key.
OPENAI_API_KEY=<ADD_YOUR_OPENAI_API_KEY>

# Optional: choose the OpenAI chat model used by the coach.
# If omitted, the app uses gpt-4o-mini.
OPENAI_CHAT_MODEL=gpt-4o-mini
```

## Run the app

Start the Flask server:

```bash
python app.py
```

Then open the app in your browser:

```text
http://127.0.0.1:5000
```

## Project Structure

- `app.py` — Flask application and core chess/coach logic
- `templates/` — HTML templates for pages: home, play, how-to, saved games
- `static/css/style.css` — project styling
- `engines/stockfish` — bundled Stockfish engine binary
- `saved_games.json` — local storage for saved game metadata
- `PROMPTS.md` — coach prompt specification and example behavior
- `test_logic.py` — simple chess logic demonstration script
- `remove_logo_background.py` — helper for editing PNG backgrounds
- `requirements.txt` — Python package dependencies

## Notes

- `app.py` uses `python-dotenv` to load `.env` from the project root.
- `OPENAI_API_KEY` must contain a valid OpenAI API key for the AI coach features to work.
- `OPENAI_CHAT_MODEL` comes from the app's environment configuration. It is optional; `app.py` defaults to `gpt-4o-mini` when it is not set.
- `.env` is excluded by `.gitignore`, so keep your personal API key in that local file and never commit it.
- The app expects the Stockfish binary to be available at `engines/stockfish`.
- The AI coach is driven by OpenAI chat completions and relies on the configured API key.

## License

Copyright (c) 2026 abhavgn. All rights reserved.

This repository is proprietary and may not be copied, modified, distributed, or reused without prior written permission from the copyright holder. Third-party dependencies are subject to their own licenses and are not covered by this statement.
