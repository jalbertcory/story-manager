// These operations share the same open MTP session for lookup, comparison and removal.
static bool device_marker(const char *attachment, const char *directory, bool compare) {
    char path[PATH_MAX];
    if (snprintf(path, sizeof(path), "%s/.device", directory) >= (int)sizeof(path)) return false;
    FILE *f = fopen(path, compare ? "rb" : "wb");
    bool ok = false;
    if (f) {
        if (compare) {
            size_t i = 0;
            while (attachment[i] && fgetc(f) == (unsigned char)attachment[i]) i++;
            ok = !attachment[i] && fgetc(f) == EOF && !ferror(f);
        } else {
            ok = fwrite(attachment, 1, strlen(attachment), f) == strlen(attachment);
        }
        if (fclose(f)) ok = false;
    }
    return ok;
}

static bool same_bytes(LIBMTP_mtpdevice_t *device, LIBMTP_file_t *entry, FILE *verified) {
    FILE *live = tmpfile();
    if (!live) return false;
    bool ok = LIBMTP_Get_File_To_File_Descriptor(device, entry->item_id, fileno(live), NULL, NULL) == 0 &&
              fseek(live, 0, SEEK_SET) == 0;
    unsigned char a[16384], b[sizeof(a)];
    size_t total = 0;
    while (ok) {
        size_t n = fread(a, 1, sizeof(a), verified);
        if (fread(b, 1, sizeof(b), live) != n || memcmp(a, b, n)) { ok = false; break; }
        total += n;
        if (n < sizeof(a)) break;
    }
    ok = ok && total == entry->filesize && !ferror(verified) && !ferror(live);
    fclose(live);
    return ok;
}

static bool children(LIBMTP_mtpdevice_t *d, uint32_t storage, uint32_t parent, LIBMTP_file_t **list) {
    LIBMTP_Clear_Errorstack(d);
    *list = LIBMTP_Get_Files_And_Folders(d, storage, parent);
    return *list || !LIBMTP_Get_Errorstack(d);
}

static bool remove_entry(LIBMTP_mtpdevice_t *d, LIBMTP_file_t *f, bool preview) {
    printf("%s %s\n", preview ? "Would remove" : "Removing", f->filename);
    fflush(stdout);
    if (preview || LIBMTP_Delete_Object(d, f->item_id) == 0) return true;
    LIBMTP_Dump_Errorstack(d);
    return false;
}

static bool items_folder(const char *name) {
    return !strncasecmp(name, "Items", 5) && strspn(name + 5, "0123456789") == strlen(name + 5);
}

enum directory { ROOT, DOCUMENTS, DOWNLOADS, ITEMS };

static bool clean_downloads(LIBMTP_mtpdevice_t *d, uint32_t storage, uint32_t parent, enum directory where,
                            const char *stem, bool sidecars, bool preview) {
    LIBMTP_file_t *list;
    if (!children(d, storage, parent, &list)) return false;
    bool ok = true;
    size_t n = strlen(stem);
    while (list) {
        LIBMTP_file_t *f = list;
        list = f->next;
        const char *name = f->filename;
        bool folder = f->filetype == LIBMTP_FILETYPE_FOLDER;
        if (ok && name) {
            if (folder && where == ROOT && !strcasecmp(name, "documents"))
                ok = clean_downloads(d, storage, f->item_id, DOCUMENTS, stem, sidecars, preview);
            else if (folder && (where == ROOT || where == DOCUMENTS) && !strcasecmp(name, "Downloads"))
                ok = clean_downloads(d, storage, f->item_id, DOWNLOADS, stem, sidecars, preview);
            else if (folder && where == DOWNLOADS && items_folder(name))
                ok = clean_downloads(d, storage, f->item_id, ITEMS, stem, sidecars, preview);
            else if (where == ITEMS && !strncmp(name, stem, n)) {
                const char *ext = name + n;
                bool download = !strcasecmp(ext, ".kfx") || !strcasecmp(ext, ".azw") ||
                                !strcasecmp(ext, ".azw3") || !strcasecmp(ext, ".mobi") || !strcasecmp(ext, ".epub");
                if ((!folder && download) || (folder && sidecars && !strcasecmp(ext, ".sdr")))
                    ok = remove_entry(d, f, preview);
            }
        }
        LIBMTP_destroy_file_t(f);
    }
    return ok;
}

static bool clean_export(LIBMTP_mtpdevice_t *device, LIBMTP_file_t *f, uint32_t storage,
                         const char *approved, bool sidecars, bool preview, unsigned *count) {
    char path[PATH_MAX], stem[PATH_MAX];
    const char *name = f->filename, *ext = strrchr(name, '.');
    if (!ext || ext - name >= (ptrdiff_t)sizeof(stem)) return false;
    size_t len = (size_t)(ext - name);
    if (len < 12 || name[len - 11] != '_' || strspn(name + len - 10, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") != 10)
        return true;
    if (snprintf(path, sizeof(path), "%s/%u/%s", approved, f->item_id, name) >= (int)sizeof(path)) return false;
    FILE *verified = fopen(path, "rb");
    if (!verified) return errno == ENOENT;
    bool ok = same_bytes(device, f, verified);
    fclose(verified);
    if (!ok) { fprintf(stderr, "Keeping changed or unreadable export: %s\n", name); return false; }
    memcpy(stem, name, len);
    stem[len] = 0;
    // Keep the export until the downloads are removed so a retry can finish the same book.
    if (!clean_downloads(device, storage, LIBMTP_FILES_AND_FOLDERS_ROOT, ROOT, stem, sidecars, preview) ||
        !remove_entry(device, f, preview)) return false;
    (*count)++;
    return true;
}
