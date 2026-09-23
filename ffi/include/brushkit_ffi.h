#ifndef BRUSHKIT_FFI_H
#define BRUSHKIT_FFI_H

#include <stddef.h>
#include <stdint.h>

typedef enum bqk_format {
    BQK_FORMAT_ABR = 0,
    BQK_FORMAT_BRUSH = 1,
    BQK_FORMAT_BRUSHSET = 2,
} bqk_format;

typedef struct bqk_preview_set bqk_preview_set;

/* One brush. Every pointer stays valid until bqk_preview_set_free. */
typedef struct bqk_entry {
    const char *name;               /* UTF-8, NUL-terminated */
    uint32_t width;                 /* 0 when unavailable */
    uint32_t height;
    const uint8_t *pixels;          /* width * height gray bytes, 255 = full ink; NULL when unavailable */
    const char *unavailable_reason; /* NULL when available */
    uint32_t source_width;          /* Original raster size; both 0 when unknown. */
    uint32_t source_height;
} bqk_entry;

/* Parses len bytes as format. Tips are downsampled so the larger side is at most max_cell.
   Returns NULL on failure and stores a message in *error, freed by the caller with bqk_string_free. */
bqk_preview_set *bqk_preview(const uint8_t *bytes, size_t len, bqk_format format, uint32_t max_cell, char **error);
/* Like bqk_preview, but returns only the first count entries with an available tip, in bqk_preview order. Later entries are not built. */
bqk_preview_set *bqk_preview_first_available(const uint8_t *bytes, size_t len, bqk_format format, uint32_t max_cell, size_t count, char **error);

/* NULL when the file carries no set name. */
const char *bqk_preview_set_name(const bqk_preview_set *set);
size_t bqk_preview_set_count(const bqk_preview_set *set);
/* index must be below bqk_preview_set_count. */
bqk_entry bqk_preview_set_entry(const bqk_preview_set *set, size_t index);
void bqk_preview_set_free(bqk_preview_set *set);
void bqk_string_free(char *s);

#endif
