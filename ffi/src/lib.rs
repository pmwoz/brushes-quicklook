use brushkit_preview::{
    GrayscaleBitmap, PreviewEntry, PreviewOptions, SourceDimensions, TipPreview, UnavailableReason,
    preview_abr, preview_brush, preview_brushset,
};
use std::ffi::{CString, c_char, c_uint};
use std::panic::catch_unwind;
use std::ptr;

pub const BQK_FORMAT_ABR: c_uint = 0;
pub const BQK_FORMAT_BRUSH: c_uint = 1;
pub const BQK_FORMAT_BRUSHSET: c_uint = 2;

pub struct PreviewSet {
    name: Option<CString>,
    entries: Vec<Entry>,
}

struct Entry {
    name: CString,
    tip: Option<GrayscaleBitmap>,
    reason: Option<CString>,
    source_dimensions: Option<SourceDimensions>,
}

#[repr(C)]
pub struct CEntry {
    name: *const c_char,
    width: u32,
    height: u32,
    pixels: *const u8,
    unavailable_reason: *const c_char,
    source_width: u32,
    source_height: u32,
}

fn c_string(value: String) -> CString {
    CString::new(value.replace('\0', "\u{fffd}")).expect("interior NULs were replaced")
}

fn reason_text(reason: UnavailableReason) -> String {
    match reason {
        UnavailableReason::NoShapePng => "no Shape.png".to_owned(),
        UnavailableReason::UnsupportedTipKind(kind) => format!("unsupported tip kind: {kind}"),
        UnavailableReason::Corrupt(message) => message,
        UnavailableReason::TooLarge { width, height } => {
            format!("tip is {width}x{height} px, too large to preview")
        }
    }
}

fn convert_entry(entry: PreviewEntry) -> Entry {
    let (tip, reason) = match entry.tip {
        TipPreview::Available(bitmap)
            if bitmap.data.len() == bitmap.width as usize * bitmap.height as usize =>
        {
            (Some(bitmap), None)
        }
        TipPreview::Available(bitmap) => (
            None,
            Some(c_string(format!(
                "malformed tip bitmap: {} bytes for {}x{} px",
                bitmap.data.len(),
                bitmap.width,
                bitmap.height
            ))),
        ),
        TipPreview::Unavailable(reason) => (None, Some(c_string(reason_text(reason)))),
    };
    Entry {
        name: c_string(entry.name),
        source_dimensions: entry.source_dimensions,
        tip,
        reason,
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn bqk_preview(
    bytes: *const u8,
    len: usize,
    // A Rust enum would make unknown C discriminants undefined behaviour before validation.
    format: c_uint,
    max_cell: u32,
    error: *mut *mut c_char,
) -> *mut PreviewSet {
    if !error.is_null() {
        unsafe { *error = ptr::null_mut() };
    }
    let result = catch_unwind(|| {
        let preview = match format {
            BQK_FORMAT_ABR => preview_abr,
            BQK_FORMAT_BRUSH => preview_brush,
            BQK_FORMAT_BRUSHSET => preview_brushset,
            _ => return Err(format!("unknown brush format: {format}")),
        };
        if len > isize::MAX as usize || (bytes.is_null() && len != 0) {
            return Err("invalid input buffer".to_owned());
        }
        let bytes = if len == 0 {
            &[]
        } else {
            unsafe { std::slice::from_raw_parts(bytes, len) }
        };
        let set = preview(bytes, PreviewOptions { max_cell }).map_err(|e| e.to_string())?;
        let entries = set.entries.into_iter().map(convert_entry).collect();
        Ok(Box::new(PreviewSet {
            name: set.set_name.map(c_string),
            entries,
        }))
    })
    .unwrap_or_else(|_| Err("brush parser panicked".to_owned()));

    match result {
        Ok(set) => Box::into_raw(set),
        Err(message) => {
            if !error.is_null() {
                unsafe { *error = c_string(message).into_raw() };
            }
            ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn bqk_preview_set_name(set: *const PreviewSet) -> *const c_char {
    unsafe { &*set }
        .name
        .as_ref()
        .map_or(ptr::null(), |name| name.as_ptr())
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn bqk_preview_set_count(set: *const PreviewSet) -> usize {
    unsafe { &*set }.entries.len()
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn bqk_preview_set_entry(set: *const PreviewSet, index: usize) -> CEntry {
    let entry = &unsafe { &*set }.entries[index];
    let (width, height, pixels) = entry.tip.as_ref().map_or((0, 0, ptr::null()), |tip| {
        (tip.width, tip.height, tip.data.as_ptr())
    });
    CEntry {
        name: entry.name.as_ptr(),
        source_width: entry.source_dimensions.map_or(0, SourceDimensions::width),
        source_height: entry.source_dimensions.map_or(0, SourceDimensions::height),
        width,
        height,
        pixels,
        unavailable_reason: entry
            .reason
            .as_ref()
            .map_or(ptr::null(), |reason| reason.as_ptr()),
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn bqk_preview_set_free(set: *mut PreviewSet) {
    if !set.is_null() {
        unsafe { drop(Box::from_raw(set)) };
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn bqk_string_free(s: *mut c_char) {
    if !s.is_null() {
        unsafe { drop(CString::from_raw(s)) };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CStr;

    fn assert_set_or_error(bytes: &[u8], format: c_uint) {
        let mut error = ptr::null_mut();
        unsafe {
            let set = bqk_preview(bytes.as_ptr(), bytes.len(), format, 160, &mut error);
            if set.is_null() {
                assert!(!error.is_null());
                let message = CStr::from_ptr(error).to_string_lossy().into_owned();
                bqk_string_free(error);
                assert!(!message.is_empty());
                assert!(!message.starts_with("brush parser panicked"), "{message}");
            } else {
                bqk_preview_set_free(set);
                assert!(error.is_null());
            }
        }
    }

    #[test]
    fn empty_input_returns_errors_for_every_format() {
        for format in [BQK_FORMAT_ABR, BQK_FORMAT_BRUSH, BQK_FORMAT_BRUSHSET] {
            let mut error = ptr::null_mut();
            unsafe {
                let set = bqk_preview(ptr::null(), 0, format, 160, &mut error);
                assert!(set.is_null());
                assert!(!error.is_null());
                assert!(!CStr::from_ptr(error).to_bytes().is_empty());
                bqk_string_free(error);
            }
        }
    }

    #[test]
    fn truncation_sweep() {
        for (path, format) in [
            ("preview_abr/wellformed_v6_patt", BQK_FORMAT_ABR),
            ("preview_brush/root_brush", BQK_FORMAT_BRUSH),
            ("preview_brushset/ordered_set", BQK_FORMAT_BRUSHSET),
        ] {
            let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/corpus")
                .join(path);
            let bytes = std::fs::read(path).unwrap();
            for len in 0..=bytes.len() {
                assert_set_or_error(&bytes[..len], format);
            }
        }
    }

    #[test]
    fn corpus_replay() {
        for (target, format) in [
            ("preview_abr", BQK_FORMAT_ABR),
            ("preview_brush", BQK_FORMAT_BRUSH),
            ("preview_brushset", BQK_FORMAT_BRUSHSET),
        ] {
            let directory = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/corpus")
                .join(target);
            for file in std::fs::read_dir(directory).unwrap() {
                let path = file.unwrap().path();
                if path.is_file() {
                    assert_set_or_error(&std::fs::read(path).unwrap(), format);
                }
            }
        }
    }

    #[test]
    fn malformed_bitmap_is_unavailable() {
        let entry = convert_entry(PreviewEntry {
            index: 0,
            name: "Malformed tip".to_owned(),
            source_dimensions: SourceDimensions::new(800, 600),
            tip: TipPreview::Available(GrayscaleBitmap {
                width: 2,
                height: 2,
                data: vec![0; 3],
            }),
        });
        assert_eq!(entry.source_dimensions, SourceDimensions::new(800, 600));
        assert!(entry.tip.is_none());
        assert!(entry.reason.unwrap().to_str().unwrap().contains("3 bytes"));
    }

    #[test]
    fn minimal_abr_matches_preview_count() {
        let bytes = include_bytes!("../tests/fixtures/wellformed_v6_min");
        let expected = preview_abr(bytes, PreviewOptions { max_cell: 160 }).unwrap();
        let mut error = ptr::null_mut();
        unsafe {
            let set = bqk_preview(bytes.as_ptr(), bytes.len(), BQK_FORMAT_ABR, 160, &mut error);
            assert!(!set.is_null());
            assert!(error.is_null());
            assert_eq!(bqk_preview_set_count(set), expected.entries.len());
            assert!(bqk_preview_set_name(set).is_null());
            for index in 0..bqk_preview_set_count(set) {
                let entry = bqk_preview_set_entry(set, index);
                assert!(!entry.name.is_null());
                let source = expected.entries[index].source_dimensions;
                assert_eq!(
                    entry.source_width,
                    source.map_or(0, SourceDimensions::width)
                );
                assert_eq!(
                    entry.source_height,
                    source.map_or(0, SourceDimensions::height)
                );
            }
            bqk_preview_set_free(set);
        }
    }

    #[test]
    fn garbage_returns_owned_errors_for_every_format() {
        let bytes = b"not a brush file";
        for format in [BQK_FORMAT_ABR, BQK_FORMAT_BRUSH, BQK_FORMAT_BRUSHSET] {
            let mut error = ptr::null_mut();
            unsafe {
                let set = bqk_preview(bytes.as_ptr(), bytes.len(), format, 160, &mut error);
                assert!(set.is_null());
                assert!(!error.is_null());
                assert!(!CStr::from_ptr(error).to_bytes().is_empty());
                bqk_string_free(error);
            }
        }
    }

    #[test]
    fn unknown_format_returns_an_error() {
        let mut error = ptr::null_mut();
        unsafe {
            let set = bqk_preview(ptr::null(), 0, c_uint::MAX, 160, &mut error);
            assert!(set.is_null());
            assert!(!error.is_null());
            assert!(
                CStr::from_ptr(error)
                    .to_str()
                    .unwrap()
                    .starts_with("unknown brush format:")
            );
            bqk_string_free(error);
        }
    }
}
