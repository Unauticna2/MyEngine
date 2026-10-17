#pragma once
#include <stdint.h>
#if defined(MYENGINE_UI_STATIC)
#define MEUI_API extern "C"
#elif defined(_WIN32) && defined(MYENGINE_UI_BUILD)
#define MEUI_API extern "C" __declspec(dllexport)
#elif defined(_WIN32)
#define MEUI_API extern "C" __declspec(dllimport)
#else
#define MEUI_API extern "C" __attribute__((visibility("default")))
#endif
// ABI 1. All buffers belong to the caller. No GL calls, global mutable state,
// retained pointers, or Python dependencies. Concurrent calls are supported.
MEUI_API uint32_t MEUI_Version();
// Input: inflated PNG scanlines, each with one filter byte (8-bit, no interlace).
// Output: RGBA8 with bottom row first, matching the engine's OpenGL convention.
// Returns 0 on success, 1 on invalid arguments, 2 on bad filter/palette, 3 on OOM.
MEUI_API int MEUI_PngPixels(const uint8_t* raw, uint64_t raw_size,
    uint32_t width, uint32_t height, uint32_t color_type,
    const uint8_t* palette, uint32_t palette_size,
    const uint8_t* alpha, uint32_t alpha_size,
    uint8_t* output, uint64_t output_size);
// Nearest-neighbor scaling; source and destination must not overlap.
MEUI_API int MEUI_ResizeRGBA(const uint8_t* source, uint64_t source_size,
    uint32_t width, uint32_t height, uint8_t* output, uint64_t output_size,
    uint32_t output_width, uint32_t output_height);
