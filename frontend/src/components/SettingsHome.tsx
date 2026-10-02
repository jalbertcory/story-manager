import Icon, { type IconName } from "./ui/Icon";

const settings: {
  title: string;
  icon: IconName;
  description: string;
  href: string;
}[] = [
  {
    title: "Cleaning rules",
    icon: "broom",
    description: "Shared content rules and source presets",
    href: "/settings/cleaning",
  },
  {
    title: "Audio & AI",
    icon: "waveform",
    description: "Providers, voices, and prompt templates",
    href: "/settings/audio-ai",
  },
  {
    title: "Library audit",
    icon: "audit",
    description: "Find missing EPUB files and covers",
    href: "/settings/library-tools",
  },
  {
    title: "Series detection",
    icon: "series",
    description: "Find series names in book titles",
    href: "/settings/library-tools?section=series",
  },
  {
    title: "Audiobook maintenance",
    icon: "headphones",
    description: "Update chapter matches and import Libation backups",
    href: "/settings/library-tools?section=audiobooks",
  },
  {
    title: "Backups",
    icon: "archive",
    description: "Create and restore library backups",
    href: "/settings/library-tools?section=backups",
  },
  {
    title: "Recycle bin",
    icon: "trash",
    description: "Restore deleted books or remove them permanently",
    href: "/settings/library-tools?section=recycle-bin",
  },
  {
    title: "Storage cleanup",
    icon: "storage",
    description: "Find unused files and failed imports",
    href: "/settings/library-tools?section=storage",
  },
  {
    title: "Reader access",
    icon: "key",
    description: "Manage reader access keys",
    href: "/settings/library-tools?section=reader-access",
  },
  {
    title: "Logs",
    icon: "logs",
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
          <p className="hint">
            Library maintenance, integrations, and diagnostics.
          </p>
        </div>
      </div>
      <div className="settings-directory">
        {settings.map((item) => (
          <a href={item.href} key={item.title}>
            <span className="settings-directory-icon" aria-hidden="true">
              <Icon name={item.icon} size={19} />
            </span>
            <div>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
            </div>
            <Icon
              name="chevronRight"
              size={16}
              className="settings-directory-chevron"
            />
          </a>
        ))}
      </div>
    </section>
  );
}
