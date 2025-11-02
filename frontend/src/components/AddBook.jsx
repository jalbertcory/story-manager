import React, { useState, useRef } from "react";

function AddBook({ onBookAdded }) {
  const [file, setFile] = useState(null);
  const [url, setUrl] = useState("");
  const [message, setMessage] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
  };

  const handleUrlChange = (e) => {
    setUrl(e.target.value);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      setFile(files[0]);
    }
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
        console.error(err);
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
        console.error(err);
      }
    } else {
      setMessage("Please select a file or enter a URL.");
    }
  };

  return (
    <div className="add-book-container">
      <h2>Add a New Book</h2>
      <form onSubmit={handleSubmit}>
        <div
          id="drop-zone"
          className={`drop-zone ${dragging ? "dragging" : ""}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current.click()}
        >
          {file ? (
            <p>Selected file: {file.name}</p>
          ) : (
            <p>Drag & drop an EPUB file here, or click to select a file</p>
          )}
          <input
            id="file-upload"
            type="file"
            accept=".epub"
            onChange={handleFileChange}
            ref={fileInputRef}
            style={{ display: "none" }}
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
