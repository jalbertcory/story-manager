import { describe, expect, it } from "vitest";

import {
  bookLabel,
  findFilenameBookMatch,
  normalizeMatchText,
  scoreBookSearch,
  scoreFilenameMatch,
} from "./filenameMatching";

const book = (id: number, title: string, author = "") => ({
  id,
  title,
  author,
});
const file = (name: string, webkitRelativePath = "") => ({
  name,
  webkitRelativePath,
});

describe("normalizeMatchText", () => {
  it("strips accents, punctuation, and case", () => {
    expect(normalizeMatchText("  Élan: The_Return!  ")).toBe("elan the return");
    expect(normalizeMatchText(null)).toBe("");
  });
});

describe("bookLabel", () => {
  it("falls back to an unknown author", () => {
    expect(bookLabel(book(1, "Dune", "Frank Herbert"))).toBe(
      "Dune — Frank Herbert",
    );
    expect(bookLabel(book(1, "Dune"))).toBe("Dune — Unknown author");
  });
});

describe("scoreFilenameMatch", () => {
  it("prefers a full title match over the title without its subtitle", () => {
    const full = scoreFilenameMatch(
      book(1, "Mother of Learning: Arc 1"),
      "Mother of Learning - Arc 1.m4b",
    );
    const primary = scoreFilenameMatch(
      book(1, "Mother of Learning: Arc 1"),
      "Mother of Learning.m4b",
    );
    expect(full).toBeGreaterThan(primary);
    expect(primary).toBeGreaterThan(0);
  });

  it("matches most significant title words in any order", () => {
    expect(
      scoreFilenameMatch(
        book(1, "The Wandering Inn Volume Two"),
        "Inn_Wandering_Two.mp3",
      ),
    ).toBeGreaterThan(500);
  });

  it("ignores short titles and stop words", () => {
    expect(scoreFilenameMatch(book(1, "It"), "it.mp3")).toBe(0);
    expect(scoreFilenameMatch(book(1, "The Book"), "the book.mp3")).toBe(
      1000 + "the book".length,
    );
    expect(scoreFilenameMatch(book(1, "Volume and Series"), "x.mp3")).toBe(0);
  });

  it("adds author words only to an existing title match", () => {
    expect(scoreFilenameMatch(book(1, "Dune", "Frank Herbert"), "x.mp3")).toBe(
      0,
    );
    expect(
      scoreFilenameMatch(
        book(1, "Dune Messiah", "Frank Herbert"),
        "Frank Herbert - Dune Messiah.m4b",
      ),
    ).toBe(1000 + "dune messiah".length + 20);
  });
});

describe("findFilenameBookMatch", () => {
  const catalog = [
    book(1, "Dune", "Frank Herbert"),
    book(2, "Dune Messiah", "Frank Herbert"),
    book(3, "Children of Dune", "Frank Herbert"),
  ];

  it("returns the clearly best book, reading folder paths", () => {
    expect(
      findFilenameBookMatch(
        [file("01.mp3", "Dune Messiah/01.mp3"), file("02.mp3")],
        catalog,
      )?.id,
    ).toBe(2);
  });

  it("returns null when nothing matches", () => {
    expect(findFilenameBookMatch([file("track01.mp3")], catalog)).toBeNull();
  });

  it("returns null when two books score too closely", () => {
    expect(
      findFilenameBookMatch(
        [file("Leviathan Wakes.m4b")],
        [book(1, "Leviathan Wakes"), book(2, "Leviathan Wakes")],
      ),
    ).toBeNull();
  });
});

describe("scoreBookSearch", () => {
  const dune = book(1, "Dune Messiah", "Frank Herbert");

  it("ranks title matches above author matches", () => {
    expect(scoreBookSearch(dune, "dune messiah")).toBe(100);
    expect(scoreBookSearch(dune, "dune")).toBe(90);
    expect(scoreBookSearch(dune, "messiah")).toBe(80);
    expect(scoreBookSearch(dune, "frank herbert")).toBe(70);
    expect(scoreBookSearch(dune, "frank")).toBe(60);
    expect(scoreBookSearch(dune, "herbert")).toBe(50);
    expect(scoreBookSearch(dune, "asimov")).toBe(0);
  });
});
