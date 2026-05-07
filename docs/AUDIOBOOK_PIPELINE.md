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
│    • chunk chapter text → LLM (provider from settings)   │
│    • parse characters + voice params                     │
│    • INSERT audiobook_characters (incl. Narrator)        │
│    • set status = "diarizing"                            │
│                                                          │
│  Phase 3 – Diarization (status="diarizing")              │
│    audiobook_llm.diarize_sentences(book_id)              │
│    • batch 50 sentences + 5-sentence context window      │
│    • LLM assigns character_id + tagged_text              │
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
│      concat snippets → ch{N}.mp3 (pydub)                │
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
  → UPDATE sentences SET status="ready_for_audio", audio_file_path=NULL
      WHERE character_id = {id}
  → UPDATE chapters SET needs_reassembly=TRUE
      WHERE id IN (SELECT chapter_id FROM audiobook_sentences WHERE character_id = {id})
  → Re-enqueue book starting at "audio_gen" phase
```

**Sentence speaker or tags changed:**
```
PUT /api/audiobook/sentences/{id}
  → UPDATE sentence: character_id, tagged_text, status="ready_for_audio", audio_file_path=NULL
  → UPDATE chapter SET needs_reassembly=TRUE WHERE id = sentence.chapter_id
  → Re-enqueue book starting at "audio_gen" phase
```

---

## Database Schema

### New tables (migration 0018)

**`audiobook_settings`** — global LLM and TTS configuration
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| llm_provider | String | `"openai"`, `"anthropic"`, `"custom"` |
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

**`audiobook_characters`**
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| book_id | FK → books CASCADE | |
| name | String | |
| description | Text | LLM-generated summary |
| voice_design_prompt | String | OmniVoice params e.g. `[gender-male][pitch-low]` |
| is_narrator | Boolean | |

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

**New columns on `books`**:
- `audiobook_enabled` (Boolean, default `false`) — per-book opt-in gate for this pipeline
- `audiobook_pipeline_status` (String, nullable)
Values: `None` (idle), `ingesting`, `roster_gen`, `diarizing`, `audio_gen`, `assembling`, `complete`, `error`, `paused`

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
| POST | `/api/books/{id}/audiobook/pause` | Pause workers (set status=paused) |
| POST | `/api/books/{id}/audiobook/rebuild` | Force full rebuild |
| GET | `/api/books/{id}/audiobook/status` | Pipeline status + sentence counts by status |
| GET | `/api/books/{id}/audiobook/characters` | List characters |
| PUT | `/api/audiobook/characters/{char_id}` | Update voice profile (triggers cascade) |
| GET | `/api/books/{id}/audiobook/sentences` | Paginated sentence list (`?page=&limit=&chapter_id=`) |
| PUT | `/api/audiobook/sentences/{id}` | Update speaker/tags (triggers cascade) |
| GET | `/api/audiobook/sentences/{id}/audio` | Stream sentence snippet MP3 |
| GET | `/api/books/{id}/audiobook/chapters` | Chapter list with assembly status |
| GET | `/api/books/{id}/audiobook/chapters/{cid}/audio` | Stream chapter MP3 |
| GET | `/api/audiobook/settings` | Get LLM/TTS config (API key masked) |
| PUT | `/api/audiobook/settings` | Upsert LLM/TTS config |

---

## Backend File Map

| File | Purpose |
|---|---|
| `backend/app/models.py` | +4 new models, +1 Book column |
| `backend/alembic/versions/0018_audiobook_pipeline.py` | Schema migration |
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
| `frontend/src/components/audiobook/ChapterAssembly.jsx` | Chapter assembly status list |
| `frontend/src/App.jsx` | +Audio Settings tab routing |
| `frontend/src/components/BookSettings.jsx` | +Audiobook Pipeline tab |

---

## Dependencies Added

**`pyproject.toml`** (core):
- `spacy>=3.7,<4` — sentence tokenization
- `httpx>=0.27` — HTTP client for LLM and OmniVoice calls (moved from dev)
- `pydub>=0.25` — MP3 concatenation
- `mutagen>=1.47` — MP3 duration extraction

**`Dockerfile.base`**:
- `ffmpeg` — required by `pydub` for MP3 decode/export

**`Dockerfile`** — after `uv pip install`:
```dockerfile
RUN python -m spacy download en_core_web_sm
```
