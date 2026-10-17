// Windows: cl /nologo /EHsc examples\ui_native_demo.cpp /Fe:build\ui_native_demo.exe
// Run from the engine directory, where MyEngineUI.dll is installed.
#include <windows.h>
#include <cstdio>
#include "../MyEngineUI.h"
int main() {
    HMODULE dll=LoadLibraryW(L".\\MyEngineUI.dll");
    if(!dll) { std::printf("LoadLibrary failed: %lu\n",GetLastError());return 1; }
    auto version=reinterpret_cast<decltype(&MEUI_Version)>(GetProcAddress(dll,"MEUI_Version"));
    auto png=reinterpret_cast<decltype(&MEUI_PngPixels)>(GetProcAddress(dll,"MEUI_PngPixels"));
    auto resize=reinterpret_cast<decltype(&MEUI_ResizeRGBA)>(GetProcAddress(dll,"MEUI_ResizeRGBA"));
    if(!version||!png||!resize||version()!=1) { FreeLibrary(dll);return 2; }
    // Inflated PNG scanline: filter None followed by one red RGBA pixel.
    const uint8_t raw[]={0,255,0,0,255};uint8_t pixel[4]={},larger[16]={};
    int code=png(raw,sizeof(raw),1,1,6,nullptr,0,nullptr,0,pixel,sizeof(pixel));
    if(!code)code=resize(pixel,sizeof(pixel),1,1,larger,sizeof(larger),2,2);
    std::printf("MyEngineUI ABI %u, result %d, pixel RGBA %u %u %u %u\n",version(),code,larger[0],larger[1],larger[2],larger[3]);
    FreeLibrary(dll);return code;
}
