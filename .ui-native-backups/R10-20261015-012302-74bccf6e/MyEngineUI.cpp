// MyEngine UI pixel kernel. PNG filter rules: https://www.w3.org/TR/png-3/
#define MYENGINE_UI_BUILD
#include "MyEngineUI.h"
#include <vector>
#include <cstdlib>
#include <cstring>
#include <utility>
static bool dimensions(uint32_t w,uint32_t h) { return w && h && w<=4096 && h<=4096; }
static uint32_t be16(const uint8_t* p) { return uint32_t(p[0])*256+p[1]; }
static int paeth(int a,int b,int c) {
    int p=a+b-c,pa=std::abs(p-a),pb=std::abs(p-b),pc=std::abs(p-c);
    return pa<=pb && pa<=pc ? a : pb<=pc ? b : c;
}
MEUI_API uint32_t MEUI_Version() { return 1; }
MEUI_API int MEUI_PngPixels(const uint8_t* raw,uint64_t raw_size,uint32_t w,uint32_t h,uint32_t color,
    const uint8_t* palette,uint32_t palette_size,const uint8_t* alpha,uint32_t alpha_size,uint8_t* out,uint64_t out_size) {
    unsigned channels=color==0||color==3?1:color==2?3:color==4?2:color==6?4:0;
    if(!raw||!out||!channels||!dimensions(w,h)||(palette_size&&!palette)||(alpha_size&&!alpha))return 1;
    uint64_t stride=uint64_t(w)*channels;
    if(raw_size!=(stride+1)*h || out_size!=uint64_t(w)*h*4)return 1;
    if(color==3&&(!palette_size||palette_size>768||palette_size%3))return 2;
    try {
        std::vector<uint8_t> previous(stride,0),row(stride);
        for(uint32_t y=0;y<h;y++) {
            const uint8_t* line=raw+y*(stride+1);unsigned filter=*line++;
            if(filter>4)return 2;
            for(uint32_t x=0;x<stride;x++) {
                int a=x>=channels?row[x-channels]:0,b=previous[x],c=x>=channels?previous[x-channels]:0;
                int prediction=filter==1?a:filter==2?b:filter==3?(a+b)/2:filter==4?paeth(a,b,c):0;
                row[x]=uint8_t(line[x]+prediction);
            }
            uint8_t* dest=out+uint64_t(h-1-y)*w*4;
            for(uint32_t x=0;x<w;x++,dest+=4) {
                const uint8_t* p=row.data()+x*channels;dest[3]=255;
                switch(color) {
                case 6: std::memcpy(dest,p,4);break;
                case 2:
                    std::memcpy(dest,p,3);
                    if(alpha_size==6&&p[0]==be16(alpha)&&p[1]==be16(alpha+2)&&p[2]==be16(alpha+4))dest[3]=0;
                    break;
                case 0:
                    dest[0]=dest[1]=dest[2]=p[0];
                    if(alpha_size==2&&p[0]==be16(alpha))dest[3]=0;
                    break;
                case 4: dest[0]=dest[1]=dest[2]=p[0];dest[3]=p[1];break;
                case 3:
                    if(uint32_t(p[0])*3+3>palette_size)return 2;
                    std::memcpy(dest,palette+uint32_t(p[0])*3,3);
                    if(p[0]<alpha_size)dest[3]=alpha[p[0]];
                    break;
                }
            }
            row.swap(previous);
        }
        return 0;
    } catch(...) { return 3; }
}
MEUI_API int MEUI_ResizeRGBA(const uint8_t* src,uint64_t src_size,uint32_t w,uint32_t h,
    uint8_t* out,uint64_t out_size,uint32_t nw,uint32_t nh) {
    if(!src||!out||!dimensions(w,h)||!dimensions(nw,nh)||src_size!=uint64_t(w)*h*4||out_size!=uint64_t(nw)*nh*4)return 1;
    for(uint32_t y=0;y<nh;y++) {
        const uint8_t* row=src+uint64_t(y*h/nh)*w*4;uint8_t* dest=out+uint64_t(y)*nw*4;
        if(w==nw) { std::memcpy(dest,row,uint64_t(w)*4);continue; }
        for(uint32_t x=0;x<nw;x++)std::memcpy(dest+x*4,row+(x*w/nw)*4,4);
    }
    return 0;
}
