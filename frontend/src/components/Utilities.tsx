import { useLocation } from "../lib/router";
import ReaderKeys from "./ReaderKeys";
import AuditPanel from "./utilities/AuditPanel";
import AudiobookToolsPanel from "./utilities/AudiobookToolsPanel";
import BackupsPanel from "./utilities/BackupsPanel";
import MetadataPanel from "./utilities/MetadataPanel";
import RecycleBinPanel from "./utilities/RecycleBinPanel";
import SeriesDetectionPanel from "./utilities/SeriesDetectionPanel";
import StorageCleanupPanel from "./utilities/StorageCleanupPanel";

const utilityPages = [
  { key: "audit", label: "Library audit" },
  { key: "series", label: "Series detection" },
  { key: "metadata", label: "Sync online metadata" },
  { key: "audiobooks", label: "Audiobook maintenance" },
  { key: "recycle-bin", label: "Recycle bin" },
  { key: "storage", label: "Storage cleanup" },
  { key: "backups", label: "Backups" },
  { key: "reader-access", label: "Reader access" },
];

function getRequestedUtilityTab(search: string) {
  const requested = new URLSearchParams(search).get("section");
  return utilityPages.some((tab) => tab.key === requested)
    ? requested
    : "audit";
}

function Utilities({
  onBack,
  section,
  reviewOnly = false,
}: {
  onBack?: () => void;
  section?: string;
  reviewOnly?: boolean;
}) {
  const { search } = useLocation();
  const activeTab = section || getRequestedUtilityTab(search);

  return (
    <div className={`${onBack ? "book-settings " : ""}utilities-page`}>
      <div className="settings-header">
        {onBack && (
          <button
            className="btn-text"
            onClick={onBack}
            style={{ flexShrink: 0 }}
          >
            ← Back
          </button>
        )}
        <h2>
          {reviewOnly
            ? "Metadata review"
            : utilityPages.find((page) => page.key === activeTab)?.label}
        </h2>
      </div>

      <div className="sub-tab-content utilities-tab-content">
        {activeTab === "audit" && <AuditPanel />}
        {activeTab === "series" && <SeriesDetectionPanel />}
        {activeTab === "metadata" && <MetadataPanel />}
        {activeTab === "audiobooks" && <AudiobookToolsPanel />}
        {activeTab === "recycle-bin" && <RecycleBinPanel />}
        {activeTab === "storage" && <StorageCleanupPanel />}
        {activeTab === "backups" && <BackupsPanel />}
        {activeTab === "reader-access" && <ReaderKeys showHeading={false} />}
      </div>
    </div>
  );
}

export default Utilities;
