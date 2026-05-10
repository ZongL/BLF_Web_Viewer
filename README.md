# BLF_Web_Viewer

A web-based tool for viewing and analyzing CAN bus signal data from Vector BLF log files. Upload BLF and DBC files, select signals, and visualize time-series waveforms interactively.

## Features

- **BLF Parsing** — Reads Vector Binary Log Format files via `python-can`
- **DBC Decoding** — Decodes raw CAN frames into named signals using one or more DBC files
- **Signal Browser** — Search, sort, and select signals with sample count / min / max stats
- **Interactive Charts** — ECharts-based zoomable time-series plots with pan and brush selection
- **LTTB Downsampling** — Largest-Triangle-Three-Buckets algorithm preserves visual shape while reducing point count for large datasets
- **Multi-DBC Support** — Upload multiple DBC files simultaneously to decode across different message definitions
- **CAN FD Support** — Handles CAN FD frames with automatic data length truncation

## Quick Start

### Prerequisites
 
- Python 3.9+

### Installation & Run

```bash
# Clone the repository
git clone <repo-url>
cd BLF_Web_Viewer

# Create virtual environment and install dependencies
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

pip install -r requirements.txt

# Start the server
python app.py
```

The browser will open automatically at `http://localhost:8080`.

## Usage

1. **Upload** — Drag & drop (or click to select) a `.blf` file and one or more `.dbc` files
2. **Analyze** — Click the "Analyze" button and wait for parsing to complete
3. **Select Signals** — Browse the signal table, use search/filter to find signals, and check the ones you want to view
4. **View Charts** — Click "Show Chart" to visualize selected signals as time-series plots; use mouse to zoom and pan

## Project Structure

```
BLF_Web_Viewer/
├── app.py              # Flask server with REST API
├── parser.py           # BLF parser, DBC decoder, LTTB downsampling
├── requirements.txt    # Python dependencies
├── static/
│   ├── index.html      # Single-page frontend
│   ├── app.js          # Frontend logic (upload, signal table, charts)
│   ├── style.css       # Custom styles
│   └── logo.svg        # Site logo
└── uploads/            # Temporary upload directory (auto-created, auto-cleaned)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload BLF + DBC files, returns `session_id` |
| `GET`  | `/api/progress/<session_id>` | Poll parsing progress |
| `POST` | `/api/signals` | Fetch downsampled signal data for selected signals |

## Tech Stack

- **Backend** — Flask, python-can, cantools
- **Frontend** — Vanilla JS, Tailwind CSS, ECharts

## License

See [LICENSE](LICENSE) for details.
