// Shallow-water virtual pipes. Separate pools own their arrays: no shared mutable globals.
#include <cmath>
#include <algorithm>
#include <cstdint>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
API int FluidStep(int nx,int nz,double* h,const double* bed,const uint8_t* solid,
                  double* qx,double* qz,double* factor,double cell,double dt,double gravity,double damping) {
    if(nx<2||nz<2||nx>128||nz>128||!h||!bed||!solid||!qx||!qz||!factor||
       !(cell>0)||!(dt>0)||!std::isfinite(dt)||!std::isfinite(cell)||!std::isfinite(gravity)||!std::isfinite(damping)||gravity<0||damping<0) return 0;
    const int n=nx*nz;const double drag=std::exp(-damping*dt),area=cell*cell;
    for(int z=0;z<nz;++z)for(int x=0;x<nx-1;++x){
        int a=z*nx+x,b=a+1,f=z*(nx-1)+x;
        if(solid[a]||solid[b]){qx[f]=0;continue;}
        double surfaceA=bed[a]+h[a],surfaceB=bed[b]+h[b];
        double wet=std::max(0.0,std::max(surfaceA,surfaceB)-std::max(bed[a],bed[b]));
        qx[f]=wet<=1e-12 ? 0 : (qx[f]+dt*gravity*wet*(surfaceA-surfaceB))*drag;
    }
    for(int z=0;z<nz-1;++z)for(int x=0;x<nx;++x){
        int a=z*nx+x,b=a+nx,f=z*nx+x;
        if(solid[a]||solid[b]){qz[f]=0;continue;}
        double surfaceA=bed[a]+h[a],surfaceB=bed[b]+h[b];
        double wet=std::max(0.0,std::max(surfaceA,surfaceB)-std::max(bed[a],bed[b]));
        qz[f]=wet<=1e-12 ? 0 : (qz[f]+dt*gravity*wet*(surfaceA-surfaceB))*drag;
    }
    for(int i=0;i<n;++i)factor[i]=0;
    for(int z=0;z<nz;++z)for(int x=0;x<nx-1;++x){int a=z*nx+x;double q=qx[z*(nx-1)+x];factor[q>=0?a:a+1]+=std::abs(q);}
    for(int z=0;z<nz-1;++z)for(int x=0;x<nx;++x){int a=z*nx+x;double q=qz[z*nx+x];factor[q>=0?a:a+nx]+=std::abs(q);}
    for(int i=0;i<n;++i)factor[i]=factor[i]>0?std::min(1.0,h[i]*area/(dt*factor[i])):1.0;
    for(int z=0;z<nz;++z)for(int x=0;x<nx-1;++x){
        int a=z*nx+x,b=a+1,f=z*(nx-1)+x;double q=qx[f];q*=factor[q>=0?a:b];qx[f]=q;
        double dh=q*dt/area;h[a]-=dh;h[b]+=dh;
    }
    for(int z=0;z<nz-1;++z)for(int x=0;x<nx;++x){
        int a=z*nx+x,b=a+nx,f=z*nx+x;double q=qz[f];q*=factor[q>=0?a:b];qz[f]=q;
        double dh=q*dt/area;h[a]-=dh;h[b]+=dh;
    }
    for(int i=0;i<n;++i)if(h[i]<0)h[i]=0; // Round-off only; donor limiting preserves volume.
    return 1;
}
