export default function WebUrlsInput({
  urls,
  onChange,
}: {
  urls: string[];
  onChange: (urls: string[]) => void;
}) {
  return (
    <div className="import-url-list">
      {urls.map((url, index) => (
        <label key={index}>
          Web novel URL {urls.length > 1 ? index + 1 : ""}
          <span className="import-url-row">
            <input
              type="url"
              placeholder="https://example.com/story/..."
              value={url}
              onChange={(event) =>
                onChange(
                  urls.map((item, itemIndex) =>
                    itemIndex === index ? event.target.value : item,
                  ),
                )
              }
            />
            {urls.length > 1 && (
              <button
                type="button"
                className="btn-text"
                onClick={() =>
                  onChange(urls.filter((_, itemIndex) => itemIndex !== index))
                }
              >
                Remove
              </button>
            )}
          </span>
        </label>
      ))}
      <button
        type="button"
        className="btn-text"
        onClick={() => onChange([...urls, ""])}
      >
        + Add another URL
      </button>
    </div>
  );
}
