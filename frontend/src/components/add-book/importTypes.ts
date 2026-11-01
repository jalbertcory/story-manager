export const IMPORT_TYPES = [
  {
    key: "books",
    label: "Book files",
    description: "EPUB files, ZIP archives, or folders",
  },
  {
    key: "web",
    label: "Web novels",
    description: "Links to the novels you want to follow",
  },
  {
    key: "audiobook",
    label: "Audiobook",
    description: "Audiobooks with or without an EPUB",
  },
  {
    key: "libation",
    label: "Libation backup",
    description: "Import audiobooks from a Libation backup",
  },
];

export interface ImportResult {
  name: string;
  status: string;
  detail?: string | null;
}
