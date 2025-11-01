import React, { useState, useEffect } from "react";

function EpubEditor({ bookId }) {
  const [chapters, setChapters] = useState([]);

  useEffect(() => {
    fetch(`/api/books/${bookId}/chapters`)
      .then((res) => res.json())
      .then((data) => setChapters(data));
  }, [bookId]);

  const deleteChapter = (filename) => {
    fetch(`/api/books/${bookId}/chapters/${filename}`, {
      method: "DELETE",
    }).then(() => {
      setChapters(chapters.filter((chapter) => chapter.filename !== filename));
    });
  };

  const cleanDivs = () => {
    const selectors = ["author-note-portlet"];
    fetch(`/api/books/${bookId}/clean_divs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(selectors),
    });
  };

  return (
    <div>
      <h2>EPUB Editor</h2>
      <button onClick={cleanDivs}>Clean Divs</button>
      <ul>
        {chapters.map((chapter) => (
          <li key={chapter.filename}>
            {chapter.title}
            <button onClick={() => deleteChapter(chapter.filename)}>Delete</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default EpubEditor;
