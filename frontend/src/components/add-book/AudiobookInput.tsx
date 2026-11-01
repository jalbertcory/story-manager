import BookCombobox from "./BookCombobox";
import { SelectedFiles } from "./ImportLayout";
import type { AudiobookSelection } from "./useAudiobookSelection";

export default function AudiobookInput({
  audio,
  disabled,
}: {
  audio: AudiobookSelection;
  disabled: boolean;
}) {
  const { catalogLoading, catalogFailed, createsBook, audioOnly } = audio;
  return (
    <fieldset className="import-audiobook-inputs" disabled={disabled}>
      <div className="import-audio-pickers">
        <label>
          Audiobook files or ZIP
          <input
            type="file"
            multiple
            accept=".zip,.cue,.m4b,.m4a,.mp3,.mp4,.aac,.flac,.ogg,.opus,.wav,audio/*"
            onChange={(event) => {
              void audio.chooseFiles(event.target.files);
            }}
          />
        </label>
        <label>
          Or audiobook directory
          <input
            type="file"
            multiple
            webkitdirectory=""
            directory=""
            onChange={(event) => {
              void audio.chooseFiles(event.target.files);
            }}
          />
        </label>
      </div>
      <SelectedFiles files={audio.files} />
      {audio.files.length > 0 &&
        createsBook &&
        !catalogLoading &&
        !catalogFailed && (
          <p className="import-match-notice" role="status">
            No library match selected. This will be imported as an audio-only
            book.
          </p>
        )}
      {catalogLoading && <p className="hint">Checking for a library match…</p>}
      {catalogFailed && (
        <p className="error" role="alert">
          Could not check your library.{" "}
          <button
            type="button"
            onClick={() => {
              void audio.reloadCatalog();
            }}
          >
            Retry
          </button>
        </p>
      )}
      {createsBook && (
        <>
          <p className="hint">
            Book details are suggested from filenames and CUE files. After
            upload, embedded tags and cover art are extracted and metadata
            lookup runs automatically. You can override the title and author
            below.
          </p>
          <label>
            Book title
            <input
              value={audio.title}
              onChange={(event) => audio.editTitle(event.target.value)}
              placeholder="Detected from the audiobook"
            />
          </label>
          <label>
            Author (optional)
            <input
              value={audio.author}
              onChange={(event) => audio.editAuthor(event.target.value)}
            />
          </label>
        </>
      )}
      <BookCombobox
        key={audio.fileSignature}
        books={audio.catalog}
        selectedBookId={audio.selectedBookId}
        onSelect={audio.selectBook}
      />

      {audio.matchNotice && (
        <p className="import-match-notice" role="status">
          {audio.matchNotice}
        </p>
      )}
      <label>
        Edition name (optional)
        <input
          value={audio.editionName}
          onChange={(event) => audio.setEditionName(event.target.value)}
          placeholder="For example, Audible / Jeff Hays"
        />
      </label>
      <label className="import-checkbox">
        <input
          type="checkbox"
          disabled={audioOnly}
          checked={!audioOnly && audio.autoAlign}
          onChange={(event) => audio.setAutoAlign(event.target.checked)}
        />
        Improve sentence timestamps with configured speech-to-text alignment
      </label>
    </fieldset>
  );
}
