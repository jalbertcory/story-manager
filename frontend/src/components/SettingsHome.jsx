const settings = [
  {
    title: "Cleaning rules",
    description: "Shared content rules and source presets",
    href: "/settings/cleaning",
  },
  {
    title: "Audio & AI",
    description: "Providers, voices, and prompt templates",
    href: "/settings/audio-ai",
  },
  {
    title: "Library audit",
    description: "Find missing EPUB files and covers",
    href: "/settings/library-tools",
  },
  {
    title: "Series detection",
    description: "Find series names in book titles",
    href: "/settings/library-tools?section=series",
  },
  {
    title: "Audiobook maintenance",
    description: "Update chapter matches and import Libation backups",
    href: "/settings/library-tools?section=audiobooks",
  },
  {
    title: "Backups",
    description: "Create and restore library backups",
    href: "/settings/library-tools?section=backups",
  },
  {
    title: "Recycle bin",
    description: "Restore deleted books or remove them permanently",
    href: "/settings/library-tools?section=recycle-bin",
  },
  {
    title: "Storage cleanup",
    description: "Find unused files and failed imports",
    href: "/settings/library-tools?section=storage",
  },
  {
    title: "Reader access",
    description: "Manage reader access keys",
    href: "/settings/library-tools?section=reader-access",
  },
  {
    title: "Logs",
    description: "Diagnostics and service history",
    href: "/settings/logs",
  },
];
export default function SettingsHome() {
  return (
    <section>
      <div className="workspace-heading">
        <div>
          <h2>Settings</h2>
        </div>
      </div>
      <div className="settings-directory">
        {settings.map((item) => (
          <a href={item.href} key={item.title}>
            <h3>{item.title}</h3>
            <p>{item.description}</p>
            <span aria-hidden="true">›</span>
          </a>
        ))}
      </div>
    </section>
  );
}
