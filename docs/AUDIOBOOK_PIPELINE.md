# EPUB-to-Audiobook Pipeline

## Overview

This pipeline converts any stored EPUB into an EPUB 3 Media Overlay audiobook. The system is a **sentence-level state machine**: each sentence in the book is independently tracked through diarization → TTS → assembly, enabling surgical regeneration of specific audio snippets without full rebuilds.

The five pipeline phases are:
1. **Ingestion** — parse EPUB, inject sentence `<span>` IDs, seed the database
2. **Roster Generation** — LLM extracts named characters and assigns OmniVoice voice profiles
3. **Diarization** — LLM assigns a speaker and non-verbal tags to every sentence
4. **Audio Generation** — OmniVoice TTS produces an MP3 snippet per sentence
5. **Assembly** — MP3 snippets are concatenated per chapter; SMIL timing files and the final EPUB 3 Media Overlay package are generated

---

## Architecture Flow

```
User: "Start Pipeline"
        │
        ▼
POST /api/books/{id}/audiobook/start
        │  sets books.audiobook_pipeline_status = "ingesting"
        ▼
AudiobookQueue.enqueue(book_id)
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│  AudiobookQueue worker (_run loop)                        │
│                                                          │
│  Phase 1 – Ingestion (status="ingesting")                │
│    audiobook_ingestion.ingest_epub(book_id)              │
│    • parse EPUB via ebooklib                             │
│    • tokenize with spaCy en_core_web_sm                  │
│    • inject <span id="ch{N}_s{M}"> around each sentence  │
│    • write modified EPUB to library/audiobooks/{id}/      │
│    • INSERT audiobook_chapters + audiobook_sentences     │
│    • set status = "roster_gen"                           │
│                                                          │
│  Phase 2 – Roster Gen (status="roster_gen")              │
│    audiobook_llm.generate_character_roster(book_id)      │
│    • sample story chapters across the book → LLM         │
│    • parse characters + voice params                     │
│    • INSERT audiobook_characters (incl. Narrator)        │
│    • set status = "diarizing"                            │
│                                                          │
│  Phase 3 – Diarization (status="diarizing")              │
│    audiobook_llm.diarize_sentences(book_id)              │
│    • batch 40 sentences + 8-sentence context window      │
│    • LLM assigns speaker, confidence, rationale + tags   │
│    • UPDATE sentence status → "ready_for_audio"          │
│    • set status = "audio_gen" when all done              │
│                                                          │
│  Phase 4 – TTS (status="audio_gen")                      │
│    audiobook_tts.generate_audio_for_book(book_id)        │
│    • for each "ready_for_audio" sentence:                │
│      POST omnivoice_endpoint {voice_prompt, tagged_text} │
│      save mp3 to library/audiobooks/{id}/snippets/       │
│      UPDATE sentence: audio_file_path, duration_ms,     │
│                        status="audio_generated"          │
│    • when chapter complete → chapter.needs_reassembly=T  │
│    • set status = "assembling" when all done             │
│                                                          │
│  Phase 5 – Assembly (status="assembling")                │
│    audiobook_assembly.assemble_book(book_id)             │
│    • for each chapter where needs_reassembly=True:       │
│      concat snippets → ch{N}.mp3 (ffmpeg)               │
│      generate .smil from html_element_id + timestamps   │
│      chapter.needs_reassembly = False                    │
│    • patch content.opf media-overlay attributes          │
│    • repackage modified EPUB                             │
│    • set status = "complete"                             │
└──────────────────────────────────────────────────────────┘
```

---

## Surgical Rebuild Logic

Changes propagate via cascades without requiring full rebuilds.

**Character voice profile updated:**
```
PUT /api/audiobook/characters/{id}
  → promote the profile into the series roster and update matching sibling-book characters
  → UPDATE sentences SET status="ready_for_audio", audio_file_path=NULL
      WHERE character_id = {id}
  → UPDATE chapters SET needs_reassembly=TRUE
      WHERE id IN (SELECT chapter_id FROM audiobook_sentences WHERE character_id = {id})
  → wait for an explicit chapter preview or full pipeline run
```

**Sentence speaker or tags changed:**
```
PUT /api/audiobook/sentences/{id}
  → UPDATE sentence: character_id, tagged_text, status="ready_for_audio", audio_file_path=NULL
  → UPDATE chapter SET needs_reassembly=TRUE WHERE id = sentence.chapter_id
  → wait for an explicit chapter preview or full pipeline run
```

---

## Database Schema

### New tables (migration 0018)

**`audiobook_settings`** — global LLM and TTS configuration
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| llm_provider | String | `"stub"`, `"ollama"`, `"openai"`, `"anthropic"`, `"custom"` |
| llm_api_key | String | Stored plaintext; masked on GET |
| llm_base_url | String | Override for custom/local LLMs |
| llm_model | String | e.g. `"gpt-4o"`, `"claude-opus-4-7"` |
| omnivoice_endpoint | String | Base URL of OmniVoice worker |
| roster_prompt_template | Text | Override default roster extraction prompt |
| diarization_prompt_template | Text | Override default diarization prompt |

**`audiobook_chapters`**
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| book_id | FK → books CASCADE | |
| chapter_number | Integer | Spine order |
| content_file_name | String | Original EPUB spine document path used by SMIL text refs |
| smil_file_path | String | Relative path to generated `.smil` |
| audio_file_path | String | Relative path to concatenated chapter MP3 |
| needs_reassembly | Boolean | Worker polls for `True` |
| preview_status | String | `queued`, `generating`, `ready`, or `error` for a manual preview |
| preview_error | Text | Last preview-generation error |

**`audiobook_characters`**
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| book_id | FK → books CASCADE | |
| series_character_id | FK → audiobook_series_characters SET NULL | Shared series voice/profile link |
| name | String | |
| description | Text | LLM-generated summary |
| voice_design_prompt | String | OmniVoice params e.g. `[gender-male][pitch-low]` |
| is_narrator | Boolean | |

**`audiobook_series_characters`** (migration 0021) — the canonical character and voice profile roster shared by
all audiobook-enabled books in a named series. Book-specific character rows remain stable for sentence assignments,
while edits to a linked voice profile propagate to matching sibling-book characters and invalidate only their derived
audio. Roster generation includes previously identified series characters as context and reuses their profiles when
the same character appears in a later book.

**`audiobook_sentences`** — the state engine
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| chapter_id | FK → audiobook_chapters CASCADE | |
| character_id | FK → audiobook_characters SET NULL | Nullable |
| html_element_id | String | Matches injected span ID e.g. `ch1_s42` |
| sequence_order | Integer | Absolute order within chapter |
| original_text | Text | Pure extracted text |
| tagged_text | Text | Text with non-verbal tags e.g. `[laughter]` |
| audio_file_path | String | Path to snippet MP3 |
| audio_duration_ms | Integer | Used for SMIL timestamp calculation |
| status | String | `pending_diarization` → `ready_for_audio` → `audio_generated` / `error` |
| speaker_confidence | Float | Model confidence from `0` to `1`; manual assignments use `1` |
| speaker_reason | Text | Short attribution rationale for review |

**New columns on `books`**:
- `audiobook_enabled` (Boolean, default `false`) — per-book opt-in gate for this pipeline
- `audiobook_pipeline_status` (String, nullable)
Values: `None` (idle), `ingesting`, `roster_gen`, `diarizing`, `audio_gen`, `assembling`, `complete`, `error`, `paused`
- `audiobook_stop_after_phase` (String, nullable) — persisted checkpoint for a single-stage run
- `audiobook_pause_requested` (Boolean, default `false`) — cooperative pause request acknowledged at a durable boundary
- `audiobook_last_error` (Text, nullable) — actionable worker error shown in the book UI
- `audiobook_summary` (Text, nullable) — roster-stage, spoiler-light story analysis
- `audiobook_progress_current` / `audiobook_progress_total` — current phase work counters
- `audiobook_progress_detail` — human-readable active operation
- `audiobook_pipeline_started_at` / `audiobook_pipeline_updated_at` — run timing
- `audiobook_batch_limit` — durable work-unit budget for **Run One Batch**
- `audiobook_llm_requests` — model calls made during the current run

Migration `0020_audiobook_observability.py` also adds chapter summaries, character aliases/evidence, and sentence
confidence/rationales. Migration `0021_series_roster_and_chapter_previews.py` adds the shared series roster links and
durable manual chapter-preview state.

---

## OmniVoice TTS Integration

OmniVoice is a self-hosted TTS worker. The endpoint URL is configured in `audiobook_settings`.

### HTTP Contract
```
POST {omnivoice_endpoint}/generate
Content-Type: application/json
Accept: audio/mpeg

{
  "voice": "[gender-female][pitch-high][speed-normal]",
  "text": "She laughed. [laughter] \"I can't believe it,\" she said."
}

Response: 200 OK
Content-Type: audio/mpeg
Body: raw MP3 bytes
```

### Voice Design Prompt Schema
The LLM roster prompt instructs the model to produce voice design strings using these parameters:

```
[gender-{male|female|neutral}]
[pitch-{low|medium|high}]
[speed-{slow|normal|fast}]
[accent-{british|american|australian|...}]   # optional
[age-{young|middle|old}]                     # optional
```

Examples:
- Narrator: `[gender-male][pitch-low][speed-normal][age-middle]`
- Child character: `[gender-female][pitch-high][speed-fast][age-young]`

Users can manually edit these values in the Character Roster UI.

### Official Local OmniVoice

Story Manager includes a native adapter for the official
[`k2-fsa/OmniVoice`](https://github.com/k2-fsa/OmniVoice) 0.2.0 release. It uses the upstream model directly, keeps it
resident between requests, translates existing bracket-style voice profiles into official voice-design attributes,
and converts the 24 kHz output to MP3.

```bash
make run-omnivoice
curl http://127.0.0.1:8001/health
```

The isolated service environment lives under `services/omnivoice/.venv`. The first start downloads about 3.3 GB of
public model weights. CUDA, Intel XPU, Apple MPS, and CPU are auto-detected; Apple Silicon uses native MPS with the
upstream audio tokenizer on CPU. Configure `http://127.0.0.1:8001` as the OmniVoice endpoint in **Audio Settings**.
The `stub` LLM provider may remain selected for deterministic local roster generation and diarization while the
OmniVoice adapter produces real speech.

The defaults use 16 diffusion steps for interactive local throughput. Set `OMNIVOICE_NUM_STEPS=32` before
`make run-omnivoice` for the upstream quality default. Other adapter options are documented in
`services/omnivoice/README.md`.

## Deterministic Local Harness

The pipeline works without API keys or network services. When no settings row exists—or when the LLM provider is
`stub`—it creates a single Narrator, assigns every sentence to that narrator, and generates timed silent placeholder
MP3s through the installed `ffmpeg` binary. This exercises ingestion, durable state transitions, surgical rebuilds,
chapter assembly, SMIL generation, and final EPUB packaging end to end.

Choose **Deterministic local harness** in Audio Settings to make this mode explicit. To switch to real generation,
choose an LLM provider and configure an OmniVoice-compatible endpoint. The harness is intentionally deterministic;
it is a validation and UI-development path, not synthetic speech.

## Recommended Local LLM (Ollama)

The recommended local analysis model is `qwen3.5:9b`. The model is about 6.6 GB, has enough instruction-following
capacity for schema-constrained roster and speaker assignment, and is substantially more practical for the many
calls required by a full book than the 17 GB 27B quality tier. Install Ollama, start its service, and pull the model:

```bash
# macOS
brew install ollama
brew services start ollama
make pull-ollama-model

curl http://127.0.0.1:11434/api/tags
```

In **Audio Settings**, click **Use Recommended Local Ollama**, then **Save & Test LLM**. The preset uses provider
`ollama`, base URL `http://127.0.0.1:11434`, and model `qwen3.5:9b`. Calls use Ollama's schema-constrained structured
outputs, thinking disabled, temperature 0, and a 32K working context. This makes roster and speaker output directly
machine-validated instead of relying on best-effort JSON prompting.

## Review and Recovery Controls

The book UI offers **Run Next Stage** for debugging or reviewing intermediate artifacts, **Run One Batch** for one
40-sentence diarization batch, one TTS sentence, or one assembly chapter, and **Run to Completion**
for unattended processing. A single-stage run persists its target phase and moves to `paused` only after that phase
has committed. **Pause Safely** is cooperative: diarization pauses between batches, TTS between sentences, and
assembly between chapters. Roster LLM requests and individual external TTS calls finish before the pause is
acknowledged. Starting or stepping again infers the next safe phase from durable chapter/sentence state, so an app
restart does not require restarting the entire book.

Worker exceptions are stored in `audiobook_last_error` and returned by the status endpoint. Retrying clears the
stale message; failed sentence audio is reset to `ready_for_audio` before TTS resumes.

The Characters tab also offers **Regenerate Character Roster**. It preserves the parsed EPUB and sentence IDs while
clearing roster, diarization, summaries, and derived audio state. Roster generation samples real story chapters
across the book and sibling books in the same series. It supplements those excerpts with capitalized-name frequency
hints and any existing series roster, reducing the chance that front matter or a one-scene cameo displaces a recurring
speaker. **Sync Series Roster** can promote an already-generated standalone book roster after its series metadata is
assigned.

## Manual Voice Evaluation

Voice-profile edits deliberately do not start a potentially expensive full-book TTS run. In **Chapter Assembly**, a
fully diarized chapter exposes **Generate Preview** (or **Rebuild Preview** after a voice change). The preview job runs
through the same serial worker as the full pipeline, generates or reuses only that chapter's sentence clips, assembles
its MP3 and SMIL, and leaves the full-book pipeline paused. A partially analyzed chapter shows its analyzed sentence
count and keeps the action disabled, preventing audio from being generated against incomplete speaker assignments.

Ready previews appear in **Listen & Read**, which provides chapter navigation, a seekable audio player, the chapter
summary, and the chapter transcript with speaker names available as sentence tooltips. This supports early voice
evaluation without pretending the final voice roster is complete; after refining a series profile, rebuild the chosen
chapter explicitly to compare it.

The library catalog shows a headphone badge on audiobook-enabled books and a count on series rows. The Audiobook
filter can show only enabled or non-enabled books, and the main sort control can order enabled books first.

---

## File Storage Layout

```
library/
└── audiobooks/
    └── {book_id}/
        ├── working.epub          # span-injected working copy of the EPUB
        ├── snippets/
        │   └── {sentence_id}.mp3 # per-sentence TTS output
        ├── ch1.mp3               # assembled chapter audio
        ├── ch1.smil              # EPUB 3 Media Overlay timing file
        ├── ch2.mp3
        ├── ch2.smil
        └── audiobook.epub        # final repackaged EPUB 3 MO
```

All paths stored in the database as relative to `LIBRARY_PATH.parent`, matching the existing pattern for `immutable_path` and `current_path`.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/books/{id}/audiobook/start` | Start or resume pipeline |
| POST | `/api/books/{id}/audiobook/step` | Run only the next recoverable phase, then pause for review |
| POST | `/api/books/{id}/audiobook/run-batch` | Run one diarization/TTS/assembly work unit, then pause |
| POST | `/api/books/{id}/audiobook/pause` | Request a cooperative pause at the next durable boundary |
| POST | `/api/books/{id}/audiobook/rebuild` | Force full rebuild |
| POST | `/api/books/{id}/audiobook/roster/rebuild` | Preserve ingestion and regenerate roster/speaker analysis |
| POST | `/api/books/{id}/audiobook/roster/share-series` | Link/promote the book roster into its series roster |
| POST | `/api/books/{id}/audiobook/chapters/{cid}/preview-audio` | Queue an explicit single-chapter audio preview |
| GET | `/api/books/{id}/audiobook/status` | Status, model, progress, summary, review flags, and sentence counts |
| GET | `/api/books/{id}/audiobook/characters` | List characters |
| PUT | `/api/audiobook/characters/{char_id}` | Update voice profile (triggers cascade) |
| GET | `/api/books/{id}/audiobook/sentences` | Paginated sentences (`?page=&limit=&chapter_id=&review_only=`) |
| PUT | `/api/audiobook/sentences/{id}` | Update speaker/tags (triggers cascade) |
| GET | `/api/audiobook/sentences/{id}/audio` | Stream sentence snippet MP3 |
| GET | `/api/books/{id}/audiobook/chapters` | Chapter list with assembly status |
| GET | `/api/books/{id}/audiobook/chapters/{cid}/audio` | Stream chapter MP3 |
| GET | `/api/books/{id}/audiobook/download` | Download the completed EPUB 3 Media Overlay audiobook |
| GET | `/api/audiobook/settings` | Get LLM/TTS config (API key masked) |
| PUT | `/api/audiobook/settings` | Upsert LLM/TTS config |
| POST | `/api/audiobook/settings/test-llm` | Validate the saved model with a structured-output request |

---

## Backend File Map

| File | Purpose |
|---|---|
| `backend/app/models.py` | Audiobook models and per-book pipeline/control state |
| `backend/alembic/versions/0018_audiobook_pipeline.py` | Core audiobook schema migration |
| `backend/alembic/versions/0019_audiobook_pipeline_controls.py` | Review, pause, and error-state migration |
| `backend/alembic/versions/0020_audiobook_observability.py` | Progress, summaries, evidence, confidence, and batch controls |
| `backend/alembic/versions/0021_series_roster_and_chapter_previews.py` | Shared series profiles and chapter-preview state |
| `backend/app/crud/audiobook.py` | DB queries for all new tables |
| `backend/app/services/audiobook_ingestion.py` | Phase 1: EPUB parse + span injection |
| `backend/app/services/audiobook_llm.py` | Phases 2 & 3: character roster + diarization |
| `backend/app/services/audiobook_tts.py` | Phase 4: OmniVoice TTS per sentence |
| `backend/app/services/audiobook_assembly.py` | Phase 5: MP3 concat + SMIL + EPUB repackage |
| `backend/app/services/audiobook_queue.py` | Async worker queue (mirrors `web_import_queue.py`) |
| `backend/app/routers/audiobook.py` | All API endpoints |
| `backend/app/main.py` | Wire queue lifecycle + router |

## Frontend File Map

| File | Purpose |
|---|---|
| `frontend/src/api/audiobook.js` | HTTP client helpers |
| `frontend/src/lib/navigation.js` | +Audio Settings tab |
| `frontend/src/components/AudiobookSettings.jsx` | Global LLM/TTS config page |
| `frontend/src/components/AudiobookPipeline.jsx` | Pipeline tab container (progress + sub-tabs) |
| `frontend/src/components/audiobook/CharacterRoster.jsx` | Character card grid with voice editing |
| `frontend/src/components/audiobook/ScriptEditor.jsx` | Paginated sentence table with inline editing |
| `frontend/src/components/audiobook/ChapterAssembly.jsx` | Chapter assembly status and manual preview controls |
| `frontend/src/components/audiobook/AudiobookReader.jsx` | Playable preview chapters with read-along text |
| `frontend/src/components/BookList.jsx` | Library audiobook filter and enabled counts |
| `frontend/src/App.jsx` | +Audio Settings tab routing and audiobook-enabled sorting |
| `frontend/src/components/BookSettings.jsx` | +Audiobook Pipeline tab |

---

## Dependencies Added

**`pyproject.toml`** (core):
- `spacy>=3.7,<4` — sentence tokenization
- `httpx2==2.5.0` — HTTP client for LLM and OmniVoice calls (exports the `httpx` module)
- `mutagen>=1.47` — MP3 duration extraction

**`Dockerfile`**:
- `ffmpeg` — placeholder MP3 generation and chapter concatenation

The application image also downloads the optional higher-quality spaCy English model after installing Python dependencies:
```dockerfile
RUN python -m spacy download en_core_web_sm
```
