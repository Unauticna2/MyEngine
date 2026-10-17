#version 120
uniform mat4 inverseViewProjection;
uniform vec4 viewport;
uniform vec3 cameraPosition;
uniform float yaw, exposure;
uniform int cubeMode;
uniform int hasSky,hasSun,blackAsAlpha;
uniform sampler2D sunTexture;
uniform vec3 sunDirection;
uniform float sunSize,sunBrightness;
uniform sampler2D sky0,sky1,sky2,sky3,sky4,sky5;
void main() {
    vec2 ndc=(gl_FragCoord.xy-viewport.xy)/viewport.zw*2.0-1.0;
    vec4 far4=inverseViewProjection*vec4(ndc,1,1);
    vec3 d=normalize(far4.xyz/far4.w-cameraPosition);
    vec3 ray=d;
    d=vec3(cos(yaw)*d.x-sin(yaw)*d.z,d.y,sin(yaw)*d.x+cos(yaw)*d.z);
    vec3 color=vec3(0);
    if(hasSky==0) { color=vec3(0); }
    else if(cubeMode==0) {
        vec2 uv=vec2(atan(d.z,d.x)/6.28318530718+0.5,asin(clamp(d.y,-1.0,1.0))/3.14159265359+0.5);
        color=texture2D(sky0,uv).rgb;
    } else {
        vec3 a=abs(d);vec2 uv;
        // OpenGL cubemap face convention; PNG rows are flipped by the texture loader.
        if(a.x>=a.y && a.x>=a.z) {
            uv=vec2(d.x>0.0?-d.z:d.z,d.y)/a.x*.5+.5;
            color=d.x>0.0?texture2D(sky0,uv).rgb:texture2D(sky1,uv).rgb;
        } else if(a.y>=a.z) {
            uv=vec2(d.x,d.y>0.0?-d.z:d.z)/a.y*.5+.5;
            color=d.y>0.0?texture2D(sky2,uv).rgb:texture2D(sky3,uv).rgb;
        } else {
            uv=vec2(d.z>0.0?d.x:-d.x,d.y)/a.z*.5+.5;
            color=d.z>0.0?texture2D(sky4,uv).rgb:texture2D(sky5,uv).rgb;
        }
    }
    color*=exposure;
    if(hasSun!=0){
        vec3 l=normalize(sunDirection);
        vec3 right=normalize(cross(abs(l.y)>.95?vec3(0,0,1):vec3(0,1,0),l));
        vec3 up=cross(l,right);float alignment=dot(ray,l);
        if(alignment>0.0){
            vec2 uv=vec2(dot(ray,right),dot(ray,up))/(alignment*tan(sunSize*.5))*.5+.5;
            if(uv.x>=0.0&&uv.x<=1.0&&uv.y>=0.0&&uv.y<=1.0){
                vec4 sun=texture2D(sunTexture,uv);
                float a=sun.a*(blackAsAlpha!=0?max(sun.r,max(sun.g,sun.b)):1.0);
                color=mix(color,sun.rgb*sunBrightness,a);
            }
        }
    }
    gl_FragDepth=1.0;gl_FragColor=vec4(color,1);
}
