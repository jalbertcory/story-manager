import { getChapterAudioUrl } from "../../api/audiobook";

function ChapterAssembly({ chapters, bookId }) {
  if (!chapters || chapters.length === 0) {
    return (
      <p className="empty-state">
        No chapters yet. Start the pipeline to begin processing.
      </p>
    );
  }

  return (
    <div className="chapter-assembly">
      <table className="chapter-table">
        <thead>
          <tr>
            <th>Chapter</th>
            <th>Assembly Status</th>
            <th>Audio Preview</th>
            <th>SMIL</th>
          </tr>
        </thead>
        <tbody>
          {chapters.map((chapter) => (
            <tr key={chapter.id}>
              <td>Chapter {chapter.chapter_number}</td>
              <td>
                {chapter.needs_reassembly ? (
                  <span className="badge badge--warning">Rebuild Pending</span>
                ) : chapter.audio_file_path ? (
                  <span className="badge badge--success">Assembled</span>
                ) : (
                  <span className="badge badge--neutral">Not yet assembled</span>
                )}
              </td>
              <td>
                {chapter.audio_file_path && !chapter.needs_reassembly && (
                  <audio
                    controls
                    src={getChapterAudioUrl(bookId, chapter.id)}
                    preload="none"
                    style={{ height: "28px" }}
                  />
                )}
              </td>
              <td>
                {chapter.smil_file_path && !chapter.needs_reassembly && (
                  <a
                    href={`/library/audiobooks/${bookId}/${chapter.smil_file_path.split("/").pop()}`}
                    download
                    className="btn-text"
                  >
                    Download SMIL
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default ChapterAssembly;
