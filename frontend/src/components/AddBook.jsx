import { useState, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

const addBook = async ({ file, url }) => {
  if (file) {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/books/upload_epub", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.detail || "File upload failed");
    }
    return res.json();
  } else if (url) {
    const res = await fetch("/api/books/add_web_novel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.detail || "Failed to add web novel");
    }
    return res.json();
  }
  throw new Error("Please provide a file or a URL.");
};

function AddBook() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState(null);
  const [url, setUrl] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);

  const mutation = useMutation({
    mutationFn: addBook,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      setFile(null);
      setUrl("");
    },
  });

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

  const handleSubmit = (e) => {
    e.preventDefault();
    mutation.mutate({ file, url });
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
        <button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Adding..." : "Add Book"}
        </button>
      </form>
      {mutation.isSuccess && <p>Book added successfully!</p>}
      {mutation.isError && <p className="error">{mutation.error.message}</p>}
    </div>
  );
}

export default AddBook;
