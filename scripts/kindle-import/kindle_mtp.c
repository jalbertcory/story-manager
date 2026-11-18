// Read exported books from a Kindle that exposes its storage over MTP on macOS.
#include <libmtp.h>
#include <errno.h>
#include <stddef.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

static bool book_filename(const char *name) {
    const char *ext = strrchr(name, '.');
    return ext && (!strcasecmp(ext, ".kfx-zip") || !strcasecmp(ext, ".kfx") ||
                   !strcasecmp(ext, ".azw3") || !strcasecmp(ext, ".mobi") ||
                   !strcasecmp(ext, ".epub"));
}

static bool read_book(LIBMTP_mtpdevice_t *device, const LIBMTP_file_t *file,
                      const char *destination, bool list_only) {
    if (list_only) { printf("  %s\n", file->filename); return true; }
    char directory[PATH_MAX], path[PATH_MAX];
    if (snprintf(directory, sizeof(directory), "%s/%u", destination, file->item_id) >= (int)sizeof(directory) ||
        snprintf(path, sizeof(path), "%s/%s", directory, file->filename) >= (int)sizeof(path))
        return false;
    if (mkdir(directory, 0700) < 0) { perror("Creating local staging folder"); return false; }
    int fd = open(path, O_CREAT | O_EXCL | O_WRONLY, 0600);
    if (fd < 0) { perror("Creating local copy"); return false; }
    int result = LIBMTP_Get_File_To_File_Descriptor(device, file->item_id, fd, NULL, NULL);
    struct stat st;
    bool ok = result == 0 && fstat(fd, &st) == 0 && (uint64_t)st.st_size == file->filesize;
    if (close(fd) < 0 || !ok) {
        fprintf(stderr, "Could not read the complete file %s.\n", file->filename);
        return false;
    }
    return true;
}

#include "kindle_cleanup.h"

struct operation {
    bool list, cleanup, preview, sidecars;
    unsigned count;
};

static bool walk(LIBMTP_mtpdevice_t *device, uint32_t storage, uint32_t parent,
                 unsigned depth, const char *destination, struct operation *op, bool *found) {
    if (depth > 64) return false;
    LIBMTP_Clear_Errorstack(device);
    LIBMTP_file_t *files = LIBMTP_Get_Files_And_Folders(device, storage, parent);
    if (!files && LIBMTP_Get_Errorstack(device)) {
        LIBMTP_Dump_Errorstack(device);
        return false;
    }
    bool ok = true;
    while (files) {
        LIBMTP_file_t *f = files;
        files = f->next;
        const char *name = f->filename;
        if (ok && name && *name && *name != '.' && !strchr(name, '/')) {
            if (f->filetype == LIBMTP_FILETYPE_FOLDER && (depth || !strcasecmp(name, "dedrm"))) {
                *found = true;
                ok = walk(device, storage, f->item_id, depth + 1, destination, op, found);
            } else if (depth && f->filetype != LIBMTP_FILETYPE_FOLDER && book_filename(name)) {
                ok = op->cleanup ? clean_export(device, f, storage, destination, op->sidecars, op->preview, &op->count)
                                 : read_book(device, f, destination, op->list);
            }
        }
        LIBMTP_destroy_file_t(f);
    }
    return ok;
}

int main(int argc, char **argv) {
    if (argc < 3 || argc > 4) return 1;
    struct operation op = {0};
    op.list = !strcmp(argv[1], "list");
    op.preview = !strcmp(argv[1], "preview-books") || !strcmp(argv[1], "preview-books-and-sidecars");
    op.sidecars = !strcmp(argv[1], "preview-books-and-sidecars") || !strcmp(argv[1], "clean-books-and-sidecars");
    op.cleanup = op.preview || op.sidecars || !strcmp(argv[1], "clean-books");
    if (!op.list && !op.cleanup && strcmp(argv[1], "read")) return 1;
    if (argc != (op.cleanup ? 4 : 3)) return 1;
    unsigned long expected = 0;
    if (op.cleanup) {
        char *end = NULL;
        expected = strtoul(argv[3], &end, 10);
        if (*end || !expected || expected > UINT32_MAX) return 1;
    }
    LIBMTP_Init();
    LIBMTP_raw_device_t *devices = NULL, *kindle = NULL;
    int count = 0;
    LIBMTP_error_number_t error = LIBMTP_Detect_Raw_Devices(&devices, &count);
    if (error != LIBMTP_ERROR_NONE && error != LIBMTP_ERROR_NO_DEVICE_ATTACHED) {
        fprintf(stderr, "Could not enumerate USB file-transfer devices.\n"); return 1;
    }
    for (int i = 0; i < count; i++) {
        LIBMTP_device_entry_t entry = devices[i].device_entry;
        if (entry.vendor_id != 0x1949 ||
            (entry.product_id != 0x9981 && (!entry.product || !strstr(entry.product, "Kindle")))) continue;
        if (kindle) { fprintf(stderr, "Connect one Kindle at a time.\n"); free(devices); return 1; }
        kindle = &devices[i];
    }
    if (!kindle) { free(devices); return 2; }
    // libmtp assigns Android's reset-on-close quirk to this Paperwhite.
    // A USB reset disconnects it until the cable is reinserted (libmtp #436).
    if (kindle->device_entry.product_id == 0x9981)
        kindle->device_entry.device_flags &= ~UINT32_C(0x10000000);
    char attachment[64];
    snprintf(attachment, sizeof(attachment), "%u:%u", kindle->bus_location, kindle->devnum);
    LIBMTP_mtpdevice_t *device = LIBMTP_Open_Raw_Device_Uncached(kindle);
    free(devices);
    if (!device) { fprintf(stderr, "Cannot open the Kindle. Close other USB transfer apps and reconnect.\n"); return 1; }
    bool found = false;
    bool ok = LIBMTP_Get_Storage(device, LIBMTP_STORAGE_SORTBY_NOTSORTED) == 0;
    if (ok && !op.list && !device_marker(attachment, argv[2], op.cleanup)) {
        fprintf(stderr, "Unable to confirm the Kindle identity for cleanup.\n");
        if (op.cleanup) ok = false;
    }
    for (LIBMTP_devicestorage_t *s = device->storage; s && ok; s = s->next)
        ok = walk(device, s->id, LIBMTP_FILES_AND_FOLDERS_ROOT, 0, argv[2], &op, &found);
    LIBMTP_Release_Device(device);
    if (!found && ok) fprintf(stderr, "The Kindle has no visible dedrm folder at the root of its storage.\n");
    if (op.cleanup) printf("%u verified export(s) %s.\n", op.count, op.preview ? "matched" : "removed");
    if (op.cleanup && op.count != expected) {
        fprintf(stderr, "Only %u of %lu expected exports matched. Reconnect to scan again.\n", op.count, expected);
        ok = false;
    }
    return ok && found ? 0 : 1;
}
