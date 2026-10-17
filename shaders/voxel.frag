#version 120
// Exact grid ray marching, including cameras inside solid cells.
uniform sampler3D volume;
uniform vec3 gridSize;
uniform float cellSize;
uniform float boundaryBias;
uniform int orthographic;
// SHADOW_HELPERS
uniform mat4 inverseViewProjection;
uniform mat4 viewProjection;
uniform mat4 inverseModel;
uniform mat3 normalMatrix;
uniform vec4 viewport;
uniform vec3 cameraPosition;
uniform vec3 tint;
// LIGHT_HELPERS
uniform int alphaPass;
uniform float opacity;
uniform float voxelDensity;
uniform float alphaCutoff;
uniform sampler2D opaqueDepth;
uniform int hasOpaqueDepth;

bool slab(float origin,float direction,float extent,vec3 axis,
          inout float enterT,inout float exitT,inout vec3 normal) {
    if(abs(direction)<1e-10) return origin>=0.0 && origin<extent;
    float a=-origin/direction, b=(extent-origin)/direction;
    float low=min(a,b), high=max(a,b);
    if(low>enterT) {enterT=low;normal=axis*(direction>0.0?-1.0:1.0);}
    exitT=min(exitT,high);
    return exitT>=enterT;
}
vec4 cellAt(vec3 cell) {
    if(any(lessThan(cell,vec3(0))) || any(greaterThanEqual(cell,gridSize))) return vec4(0);
    return texture3D(volume,(cell+0.5)/gridSize);
}
void main() {
    vec2 ndc=(gl_FragCoord.xy-viewport.xy)/viewport.zw*2.0-1.0;
    vec4 near4=inverseViewProjection*vec4(ndc,-1,1);
    vec4 far4=inverseViewProjection*vec4(ndc,1,1);
    vec3 nearPoint=near4.xyz/near4.w;
    vec3 direction=normalize(far4.xyz/far4.w-nearPoint);
    vec3 origin=(orthographic!=0)?nearPoint:cameraPosition;
    float nearT=max(0.0,dot(nearPoint-origin,direction));
    vec3 ro=(inverseModel*vec4(origin,1)).xyz/cellSize+gridSize*0.5;
    vec3 rd=(inverseModel*vec4(direction,0)).xyz/cellSize;
    float entry=-1e30, exitT=1e30;
    vec3 normal=vec3(0,0,1);
    if(!slab(ro.x,rd.x,gridSize.x,vec3(1,0,0),entry,exitT,normal) ||
       !slab(ro.y,rd.y,gridSize.y,vec3(0,1,0),entry,exitT,normal) ||
       !slab(ro.z,rd.z,gridSize.z,vec3(0,0,1),entry,exitT,normal)) discard;
    if(alphaPass!=0 && hasOpaqueDepth!=0){
        float opaque=texture2D(opaqueDepth,(gl_FragCoord.xy-viewport.xy)/viewport.zw).r;
        vec4 stop4=inverseViewProjection*vec4(ndc,opaque*2.0-1.0,1);
        float stopT=dot(stop4.xyz/stop4.w-origin,direction);
        exitT=min(exitT,stopT);
    }
    float t=max(entry,nearT);
    if(exitT<t) discard;
    vec3 stepDir=sign(rd);
    // Static sub-cell sine: no time-dependent flicker and no depth/silhouette wobble.
    float epsilon=max(1e-6,boundaryBias*(1.0+0.1*sin(dot(gl_FragCoord.xy,vec2(0.75487766,0.56984029)))));
    vec3 cell=clamp(floor(ro+rd*t+stepDir*epsilon),vec3(0),gridSize-1.0);
    vec3 nextT=vec3(1e30), delta=vec3(1e30);
    if(abs(rd.x)>=1e-10) {nextT.x=(cell.x+max(stepDir.x,0.0)-ro.x)/rd.x;delta.x=abs(1.0/rd.x);}
    if(abs(rd.y)>=1e-10) {nextT.y=(cell.y+max(stepDir.y,0.0)-ro.y)/rd.y;delta.y=abs(1.0/rd.y);}
    if(abs(rd.z)>=1e-10) {nextT.z=(cell.z+max(stepDir.z,0.0)-ro.z)/rd.z;delta.z=abs(1.0/rd.z);}
    vec4 sampleColor=cellAt(cell), hitColor=sampleColor;
    bool exiting=(entry<nearT && sampleColor.a>alphaCutoff);
    bool found=false;vec4 accumulated=vec4(0);float firstT=t;
    for(int iteration=0;iteration<1024;iteration++) {
        sampleColor=cellAt(cell);
        bool solid=sampleColor.a>alphaCutoff;
        if(alphaPass!=0){
            float segment=max(0.0,min(exitT,min(nextT.x,min(nextT.y,nextT.z)))-t);
            float a=1.0-exp(-max(0.0,sampleColor.a*opacity*voxelDensity)*segment/cellSize);
            if(a>.000001){
                if(!found){firstT=t;found=true;}
                vec3 n=normalize(normalMatrix*normal);
                vec3 lit=sampleColor.rgb*tint*lightingAt(origin+direction*t,n);
                accumulated.rgb+=(1.0-accumulated.a)*a*lit;
                accumulated.a+=(1.0-accumulated.a)*a;
                if(accumulated.a>.995)break;
            }
        }else{
            if(!exiting && solid) {hitColor=sampleColor;found=true;break;}
            if(exiting && !solid) {found=true;break;}
        }
        if(any(lessThan(cell,vec3(0))) || any(greaterThanEqual(cell,gridSize))) break;
        if(exiting) hitColor=sampleColor;
        float next=min(nextT.x,min(nextT.y,nextT.z));
        if(next>exitT+1e-5 || next>1e29 || alphaPass!=0 && next>=exitT) break;
        t=max(t,next);
        // Relative-to-cell-step tie tolerance, independent of camera distance.
        float eps=1e-5*min(delta.x,min(delta.y,delta.z));
        bvec3 crossed=lessThanEqual(nextT,vec3(next+eps));
        if(crossed.x) normal=vec3(-stepDir.x,0,0);
        else if(crossed.y) normal=vec3(0,-stepDir.y,0);
        else normal=vec3(0,0,-stepDir.z);
        if(crossed.x) {cell.x+=stepDir.x;nextT.x=(cell.x+max(stepDir.x,0.0)-ro.x)/rd.x;}
        if(crossed.y) {cell.y+=stepDir.y;nextT.y=(cell.y+max(stepDir.y,0.0)-ro.y)/rd.y;}
        if(crossed.z) {cell.z+=stepDir.z;nextT.z=(cell.z+max(stepDir.z,0.0)-ro.z)/rd.z;}
    }
    if(!found) discard;
    if(alphaPass!=0)t=firstT;
    vec4 clip=viewProjection*vec4(origin+direction*t,1);
    if(clip.w<=0.0) discard;
    float depth=clip.z/clip.w*0.5+0.5;
    if(depth<-.00001 || depth>1.00001) discard;
    gl_FragDepth=clamp(depth,0.0,1.0);
    vec3 n=normalize(normalMatrix*normal);
    if(alphaPass!=0){
        if(accumulated.a<=.000001)discard;
        gl_FragColor=vec4(accumulated.rgb/accumulated.a,accumulated.a);
    }else gl_FragColor=vec4(hitColor.rgb*tint*lightingAt(origin+direction*t,n),1);
}
