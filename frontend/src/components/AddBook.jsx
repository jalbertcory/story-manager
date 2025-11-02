import React, { useState } from "react";

function AddBook({ onBookAdded }) {
  const [file, setFile] = useState(null);
  const [url, setUrl] = useState("");
  const [message, setMessage] = useState("");

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
  };

  const handleUrlChange = (e) => {
    setUrl(e.target.value);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage("");

    if (file) {
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/api/books/upload_epub", {
          method: "POST",
          body: formData,
        });

        if (res.ok) {
          setMessage("Book uploaded successfully!");
          onBookAdded();
        } else {
          const error = await res.json();
          setMessage(`Error: ${error.detail}`);
        }
      } catch (err) {
        setMessage("An error occurred during file upload.");
      }
    } else if (url) {
      try {
        const res = await fetch("/api/books/add_web_novel", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ url }),
        });

        if (res.ok) {
          setMessage("Web novel added successfully!");
          onBookAdded();
        } else {
          const error = await res.json();
          setMessage(`Error: ${error.detail}`);
        }
      } catch (err) {
        setMessage("An error occurred while adding the web novel.");
      }
    } else {
      setMessage("Please select a file or enter a URL.");
    }
  };

  return (
    <div className="add-book-container">
      <h2>Add a New Book</h2>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="file-upload">Upload EPUB:</label>
          <input
            id="file-upload"
            type="file"
            accept=".epub"
            onChange={handleFileChange}
          />
        </div>
        <div className="form-group">
          <label htmlFor="url-input">Or add by URL:</label>
          <input
            id="url-input"
            type="text"
            placeholder="Enter URL"
            value={url}
            onChange={handleUrlChange}
          />
        </div>
        <button type="submit">Add Book</button>
      </form>
      {message && <p>{message}</p>}
    </div>
  );
}

export default AddBook;
