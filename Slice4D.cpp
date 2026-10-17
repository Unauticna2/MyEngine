// Native 4D slicing kernel; MASM owns the window, rendering loop and physics.
// No Python API, no GL calls. ctypes releases the GIL while this worker runs.
#include <vector>
#include <array>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
using V=std::array<double,3>;using V4=std::array<double,4>;using P2=std::array<double,2>;using M=std::array<V4,4>;
struct Vertex { V p,n;P2 uv; };struct Layer{std::vector<Vertex> v;V lo,hi;};
struct Source{std::vector<Layer> layers;};struct Result{std::vector<float> data;};
static thread_local const char* error_text="";
static V add(V a,V b){return {a[0]+b[0],a[1]+b[1],a[2]+b[2]};}
static V sub(V a,V b){return {a[0]-b[0],a[1]-b[1],a[2]-b[2]};}
static V mul(V a,double t){return {a[0]*t,a[1]*t,a[2]*t};}
static double dot(V a,V b){return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
static V cross(V a,V b){return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]};}
static V unit(V a){double l=std::sqrt(dot(a,a));return l>1e-12?mul(a,1/l):V{0,0,0};}
static V4 transform(const M&m,V p,double w){V4 q{};for(int k=0;k<4;k++)q[k]=m[k][0]*p[0]+m[k][1]*p[1]+m[k][2]*p[2]+m[k][3]*w;return q;}
static V xyz(V4 p){return {p[0],p[1],p[2]};}
static void emit(Result&o,V p,V n,P2 uv,V scale){if(o.data.size()>24000000)throw std::runtime_error("slice limit");for(int k=0;k<3;k++)o.data.push_back(float(p[k]/scale[k]));for(double x:n)o.data.push_back(float(x));for(double x:uv)o.data.push_back(float(x));}
static M rotation(const double*a){M m{};for(int i=0;i<4;i++)m[i][i]=1;for(int axis=0;axis<3;axis++){double r=a[axis]*0.017453292519943295,c=std::cos(r),s=std::sin(r);auto row=m[axis],w=m[3];for(int k=0;k<4;k++){m[axis][k]=c*row[k]-s*w[k];m[3][k]=s*row[k]+c*w[k];}}return m;}
struct Hit{V p;P2 uv;};
static void addhit(std::vector<Hit>&h,V p,P2 uv){for(auto&q:h)if(dot(sub(p,q.p),sub(p,q.p))<1e-14)return;h.push_back({p,uv});}
static void sides(Result&out,const Source&s,double spacing,double sw,const M&m,V scale,double cut){
 const int edges[9][2]={{0,1},{1,2},{2,0},{3,4},{4,5},{5,3},{0,3},{1,4},{2,5}};
 for(size_t layer=0;layer<s.layers.size();layer++){
  const auto&mesh=s.layers[layer];double low=(double(layer)-.5)*spacing*sw,high=(double(layer)+.5)*spacing*sw;
  double wl=std::min(m[3][3]*low,m[3][3]*high),wh=std::max(m[3][3]*low,m[3][3]*high);V coeff{m[3][0]*scale[0],m[3][1]*scale[1],m[3][2]*scale[2]};
  double mn=wl,mx=wh;for(int k=0;k<3;k++){mn+=std::min(coeff[k]*mesh.lo[k],coeff[k]*mesh.hi[k]);mx+=std::max(coeff[k]*mesh.lo[k],coeff[k]*mesh.hi[k]);}if(cut<mn-1e-8||cut>mx+1e-8)continue;
  for(size_t t=0;t<mesh.v.size();t+=3){
   const Vertex*verts=&mesh.v[t];double a=dot(coeff,verts[0].p),b=dot(coeff,verts[1].p),c=dot(coeff,verts[2].p);
   if(cut<std::min({a,b,c})+wl-1e-8||cut>std::max({a,b,c})+wh+1e-8)continue;
   V4 points[6];for(int side=0;side<2;side++)for(int j=0;j<3;j++){V p=verts[j].p;for(int k=0;k<3;k++)p[k]*=scale[k];points[side*3+j]=transform(m,p,side?high:low);}
   std::vector<Hit> hits;hits.reserve(6);
   for(auto&e:edges){int i=e[0],j=e[1];double da=points[i][3]-cut,db=points[j][3]-cut;
    if(std::abs(da)<1e-8)addhit(hits,xyz(points[i]),verts[i%3].uv);
    if(da*db<0){double q=da/(da-db);V p=add(xyz(points[i]),mul(sub(xyz(points[j]),xyz(points[i])),q));P2 uv;for(int k=0;k<2;k++)uv[k]=verts[i%3].uv[k]+(verts[j%3].uv[k]-verts[i%3].uv[k])*q;addhit(hits,p,uv);}
    if(std::abs(db)<1e-8)addhit(hits,xyz(points[j]),verts[j%3].uv);
   }
   if(hits.size()<3)continue;V center{0,0,0},old{};for(auto&h:hits)center=add(center,h.p);center=mul(center,1./hits.size());
   for(int k=0;k<3;k++)old[k]=(verts[0].n[k]+verts[1].n[k]+verts[2].n[k])/3/scale[k];V normal=unit(xyz(transform(m,old,0)));if(dot(normal,normal)<.5)continue;
   V u=unit(sub(hits[0].p,center)),v=cross(normal,u),local=unit({normal[0]*scale[0],normal[1]*scale[1],normal[2]*scale[2]});
   std::sort(hits.begin(),hits.end(),[&](const Hit&a,const Hit&b){V x=sub(a.p,center),y=sub(b.p,center);return std::atan2(dot(x,v),dot(x,u))<std::atan2(dot(y,v),dot(y,u));});
   for(size_t j=1;j+1<hits.size();j++){Hit tri[3]={hits[0],hits[j],hits[j+1]};if(dot(cross(sub(tri[1].p,tri[0].p),sub(tri[2].p,tri[0].p)),normal)<0)std::swap(tri[1],tri[2]);for(auto&h:tri)emit(out,h.p,local,h.uv,scale);}
  }
 }
}
struct Edge{P2 a,b;double lo,hi;int owner;double at(double y)const{return a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]);}};
static std::vector<Edge> segments(const Layer&mesh,const M&m,V scale,double w,double cut,V u,V v,int owner){
 std::vector<Edge> result;V row{m[3][0],m[3][1],m[3][2]};double target=cut-m[3][3]*w;
 for(size_t t=0;t<mesh.v.size();t+=3){V p[3];double d[3];for(int j=0;j<3;j++){p[j]=mesh.v[t+j].p;for(int k=0;k<3;k++)p[j][k]*=scale[k];d[j]=dot(row,p[j])-target;}
  if(std::min({d[0],d[1],d[2]})>1e-8||std::max({d[0],d[1],d[2]})< -1e-8||std::max({std::abs(d[0]),std::abs(d[1]),std::abs(d[2])})<1e-8)continue;
  std::vector<V>hits;auto addp=[&](V q){for(auto&r:hits)if(dot(sub(q,r),sub(q,r))<1e-16)return;hits.push_back(q);};
  for(int a=0;a<3;a++){int b=(a+1)%3;if(std::abs(d[a])<1e-8)addp(p[a]);if(d[a]*d[b]<0)addp(add(p[a],mul(sub(p[b],p[a]),d[a]/(d[a]-d[b]))));}
  if(hits.size()!=2)continue;V x=xyz(transform(m,hits[0],w)),y=xyz(transform(m,hits[1],w));P2 a{dot(x,u),dot(x,v)},b{dot(y,u),dot(y,v)};
  if(std::abs(a[1]-b[1])>1e-9)result.push_back({a,b,std::min(a[1],b[1]),std::max(a[1],b[1]),owner});
 }
 return result;
}
static void caps(Result&out,const Source&s,double spacing,double sw,const M&m,V scale,double cut){
 V n{m[0][3],m[1][3],m[2][3]};double nn=dot(n,n);if(nn<1e-14)return;V normal=unit(n),u=unit(cross(normal,std::abs(normal[1])<.8?V{0,1,0}:V{1,0,0})),v=cross(normal,u);
 for(size_t boundary=0;boundary<=s.layers.size();boundary++){
  double w=(double(boundary)-.5)*spacing*sw;V origin=mul(n,(w-m[3][3]*cut)/nn);
  auto a=boundary?segments(s.layers[boundary-1],m,scale,w,cut,u,v,0):std::vector<Edge>{};
  auto b=boundary<s.layers.size()?segments(s.layers[boundary],m,scale,w,cut,u,v,1):std::vector<Edge>{};
  std::vector<double>ys;auto addy=[&](double y){ys.push_back(std::round(y*1e10)/1e10);};
  for(auto&e:a){addy(e.a[1]);addy(e.b[1]);}for(auto&e:b){addy(e.a[1]);addy(e.b[1]);}
  for(auto&ea:a)for(auto&eb:b){double lo=std::max(ea.lo,eb.lo),hi=std::min(ea.hi,eb.hi);if(hi-lo<1e-9)continue;double d0=ea.at(lo)-eb.at(lo),d1=ea.at(hi)-eb.at(hi);if(d0*d1<0)addy(lo+(hi-lo)*d0/(d0-d1));}
  std::sort(ys.begin(),ys.end());ys.erase(std::unique(ys.begin(),ys.end()),ys.end());std::vector<Edge>edges=a;edges.insert(edges.end(),b.begin(),b.end());
  for(size_t iy=0;iy+1<ys.size();iy++){
   double low=ys[iy],high=ys[iy+1];if(high-low<1e-9)continue;double mid=(low+high)*.5;std::vector<std::pair<double,const Edge*>>hits;
   for(auto&e:edges)if(e.lo<mid&&mid<e.hi)hits.push_back({e.at(mid),&e});std::sort(hits.begin(),hits.end(),[](auto&a,auto&b){return a.first<b.first;});
   bool state[2]={false,false};const Edge*prev=nullptr;double px=0;
   for(size_t j=0;j<hits.size();){double x=hits[j].first;const Edge*edge=hits[j].second;
    if(prev&&state[0]!=state[1]&&x-px>1e-8){P2 poly[4]={{prev->at(low),low},{edge->at(low),low},{edge->at(high),high},{prev->at(high),high}};
     double sign=(state[0]?1.:-1.)*(sw>0?1.:-1.);V outward=mul(normal,sign),local=unit({outward[0]*scale[0],outward[1]*scale[1],outward[2]*scale[2]}),points[4];
     for(int k=0;k<4;k++)points[k]=add(origin,add(mul(u,poly[k][0]),mul(v,poly[k][1])));
     for(int tri=0;tri<2;tri++){int ids[3]={0,tri?2:1,tri?3:2};V face=cross(sub(points[ids[1]],points[0]),sub(points[ids[2]],points[0]));if(dot(face,face)<1e-18)continue;if(dot(face,outward)<0)std::swap(ids[0],ids[2]);for(int id:ids)emit(out,points[id],local,poly[id],scale);}
    }
    size_t k=j;while(k<hits.size()&&std::abs(hits[k].first-x)<1e-8){int owner=hits[k].second->owner;state[owner]=!state[owner];k++;}prev=edge;px=x;j=k;
   }
  }
 }
}
API const char* Slice4DError(){return error_text;}
API void* Slice4DCreate(const float*data,const uint32_t*counts,uint32_t layers){
 try{error_text="";if(!data||!counts||!layers||layers>256)throw std::runtime_error("bad source");Source*s=new Source;try{uint64_t total=0;for(uint32_t l=0;l<layers;l++){uint32_t count=counts[l];total+=count;if(count%3||total>3000000)throw std::runtime_error("source limit");Layer mesh;mesh.lo={1e100,1e100,1e100};mesh.hi={-1e100,-1e100,-1e100};if(!count){mesh.lo={0,0,0};mesh.hi={0,0,0};}mesh.v.reserve(count);for(uint32_t i=0;i<count;i++,data+=8){Vertex v{};for(int k=0;k<8;k++)if(!std::isfinite(data[k]))throw std::runtime_error("nonfinite vertex");for(int k=0;k<3;k++){v.p[k]=data[k];v.n[k]=data[k+3];mesh.lo[k]=std::min(mesh.lo[k],v.p[k]);mesh.hi[k]=std::max(mesh.hi[k],v.p[k]);}v.uv={data[6],data[7]};mesh.v.push_back(v);}s->layers.push_back(std::move(mesh));}return s;}catch(...){delete s;throw;}}
 catch(...){error_text="Invalid/oversized source or allocation failure";return nullptr;}}
API void Slice4DDestroy(void*source){delete static_cast<Source*>(source);}
API void* Slice4DCompute(void*source,double spacing,double sw,const double*angles,const double*scales,double cut){
 try{error_text="";if(!source||!angles||!scales||!std::isfinite(cut)||!std::isfinite(spacing)||spacing<=0||!std::isfinite(sw)||std::abs(sw)<1e-5)throw std::runtime_error("parameters");V scale{};for(int k=0;k<3;k++){if(!std::isfinite(angles[k])||!std::isfinite(scales[k])||std::abs(scales[k])<1e-5)throw std::runtime_error("parameters");scale[k]=scales[k];}Result*r=new Result;try{M m=rotation(angles);sides(*r,*static_cast<Source*>(source),spacing,sw,m,scale,cut);caps(*r,*static_cast<Source*>(source),spacing,sw,m,scale,cut);return r;}catch(...){delete r;throw;}}
 catch(...){error_text="Invalid slice parameters, output limit or allocation failure";return nullptr;}}
API const float* Slice4DData(void*result){return result?static_cast<Result*>(result)->data.data():nullptr;}
API uint32_t Slice4DCount(void*result){return result?uint32_t(static_cast<Result*>(result)->data.size()):0;}
API void Slice4DFree(void*result){delete static_cast<Result*>(result);}
