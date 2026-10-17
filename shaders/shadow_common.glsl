uniform sampler2D shadowTexture;
uniform mat4 shadowMatrix;
uniform int shadowsEnabled;
uniform float shadowTexel;
uniform float shadowBias;
float visibilityAt(vec3 p,vec3 normal,vec3 lightDirection){
 if(shadowsEnabled==0)return 1.0;
 vec4 h=shadowMatrix*vec4(p,1.0);vec3 q=h.xyz/h.w*.5+.5;
 if(q.x<=0.0||q.y<=0.0||q.x>=1.0||q.y>=1.0||q.z<=0.0||q.z>=1.0)return 1.0;
 float bias=shadowBias*(1.0+2.0*(1.0-max(dot(normal,lightDirection),0.0)));
 float result=0.0;
 for(int x=-1;x<=1;x++)for(int y=-1;y<=1;y++)
  result+=(q.z-bias<=texture2D(shadowTexture,q.xy+vec2(float(x),float(y))*shadowTexel).r)?1.0:0.0;
 return result/9.0;
}
